// Heatmap helpers (CORE-6). Display only: values come from the API, already classified
// with the same rules as checkpoints; nothing here feeds back into risk or ranking.
import type { Color } from '@deck.gl/core'
import type { HeatmapResponse, HeatmapVariable, Route } from '../api/types'
import { RISK_STYLE } from './risk'

export const HEATMAP_HOURS = 49

interface Band {
  upTo: number // band applies to values below this (the last band is open-ended)
  color: string
  alpha: number
  /** Where the band's colour is exact; defaults to the band centre. */
  at?: number
}

export interface VariableStyle {
  key: HeatmapVariable
  label: string
  unit: string
  /** Value mapped to the top of the colour range (deck.gl maps value / max). */
  max: number
  /** Values below this fade towards transparent, so calm areas don't hide the map. */
  fadeBelow: number
  bands: Band[]
  /** Legend tick values (thresholds from the spec rules). */
  ticks: number[]
  format: (v: number) => string
}

const C = RISK_STYLE

/** Bands follow the spec §5 thresholds, so heatmap colours match checkpoint colours. */
export const VARIABLES: Record<HeatmapVariable, VariableStyle> = {
  risk: {
    key: 'risk',
    label: 'Risk',
    unit: '',
    max: 5.5,
    fadeBelow: 0.5,
    bands: [
      // Scores 1-5 show exactly the checkpoint colours.
      { upTo: 1.5, color: C.LOW.color, alpha: 70, at: 1 },
      { upTo: 2.5, color: C.MODERATE.color, alpha: 190, at: 2 },
      { upTo: 3.5, color: C.HIGH.color, alpha: 210, at: 3 },
      { upTo: 4.5, color: C.SEVERE.color, alpha: 220, at: 4 },
      { upTo: Infinity, color: C.NO_TRAVEL.color, alpha: 230, at: 5 },
    ],
    ticks: [1, 2, 3, 4, 5],
    format: (v) => ['', 'Low', 'Mod', 'High', 'Sev', 'No Go'][Math.round(v)] ?? '',
  },
  wind_mph: {
    key: 'wind_mph',
    label: 'Wind',
    unit: 'mph',
    max: 65,
    fadeBelow: 25,
    bands: [
      { upTo: 25, color: C.LOW.color, alpha: 90 },
      { upTo: 35, color: C.MODERATE.color, alpha: 190 },
      { upTo: 45, color: C.HIGH.color, alpha: 210 },
      { upTo: 55, color: C.SEVERE.color, alpha: 220 },
      { upTo: Infinity, color: C.NO_TRAVEL.color, alpha: 230 },
    ],
    ticks: [25, 35, 45, 55],
    format: (v) => `${v}`,
  },
  rain_in_hr: {
    key: 'rain_in_hr',
    label: 'Rain',
    unit: 'in/hr',
    max: 1.25,
    fadeBelow: 0.1,
    bands: [
      { upTo: 0.1, color: C.LOW.color, alpha: 90 },
      { upTo: 0.25, color: C.MODERATE.color, alpha: 190 },
      { upTo: 0.5, color: C.HIGH.color, alpha: 210 },
      { upTo: 1.0, color: C.SEVERE.color, alpha: 220 },
      { upTo: Infinity, color: C.NO_TRAVEL.color, alpha: 230 },
    ],
    ticks: [0.1, 0.25, 0.5, 1.0],
    format: (v) => `${v}`,
  },
  snow_in_hr: {
    key: 'snow_in_hr',
    label: 'Snow',
    unit: 'in/hr',
    max: 3.75,
    fadeBelow: 0.5,
    bands: [
      { upTo: 0.5, color: C.LOW.color, alpha: 90 },
      { upTo: 1.0, color: C.MODERATE.color, alpha: 190 },
      { upTo: 2.0, color: C.HIGH.color, alpha: 210 },
      { upTo: 3.0, color: C.SEVERE.color, alpha: 220 },
      { upTo: Infinity, color: C.NO_TRAVEL.color, alpha: 230 },
    ],
    ticks: [0.5, 1, 2, 3],
    format: (v) => `${v}`,
  },
}

export const VARIABLE_ORDER: HeatmapVariable[] = ['risk', 'wind_mph', 'rain_in_hr', 'snow_in_hr']

const hexToRgb = (hex: string): [number, number, number] => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
]

export function bandFor(style: VariableStyle, value: number): Band {
  return style.bands.find((b) => value < b.upTo) ?? style.bands[style.bands.length - 1]
}

/** Colour anchors: each band's colour at its centre (thresholds fall halfway between). */
export function anchors(style: VariableStyle): { v: number; rgba: [number, number, number, number] }[] {
  let lo = 0
  return style.bands.map((b) => {
    const hi = Math.min(b.upTo, style.max)
    const v = b.at ?? (b.upTo === Infinity ? (lo + style.max) / 2 : (lo + hi) / 2)
    lo = hi
    return { v, rgba: [...hexToRgb(b.color), b.alpha] }
  })
}

/** Smooth colour for a value: linear blend between neighbouring band anchors. */
export function colorAt(style: VariableStyle, value: number): [number, number, number, number] {
  const a = anchors(style)
  if (value <= a[0].v) return a[0].rgba
  for (let k = 1; k < a.length; k++) {
    if (value <= a[k].v) {
      const f = (value - a[k - 1].v) / (a[k].v - a[k - 1].v)
      return a[k].rgba.map((c, j) => Math.round(a[k - 1].rgba[j] + (c - a[k - 1].rgba[j]) * f)) as [
        number,
        number,
        number,
        number,
      ]
    }
  }
  return a[a.length - 1].rgba
}

/** deck.gl samples colorRange at value / max, so sample our scale the same way. */
export function colorRange(style: VariableStyle, steps = 64): Color[] {
  const out: Color[] = []
  for (let i = 0; i < steps; i++) out.push(colorAt(style, ((i + 0.5) / steps) * style.max))
  return out
}

/** Geographic bounds of the grid image: cell centres +/- half a cell. */
export function gridBounds(h: HeatmapResponse): [number, number, number, number] {
  const { lats, lons } = h.grid
  const dLat = lats.length > 1 ? lats[1] - lats[0] : 0.1
  const dLon = lons.length > 1 ? lons[1] - lons[0] : 0.1
  return [lons[0] - dLon / 2, lats[0] - dLat / 2, lons[lons.length - 1] + dLon / 2, lats[lats.length - 1] + dLat / 2]
}

export interface FrameImage {
  width: number
  height: number
  data: Uint8ClampedArray<ArrayBuffer>
}

/**
 * One frame as an RGBA image, one pixel per grid cell (north row first, as images are
 * stored top-down). The GPU's linear filtering blends neighbouring cells into a smooth
 * field while every cell centre keeps its exact colour. null -> fully transparent.
 */
export function frameImage(h: HeatmapResponse, variable: HeatmapVariable, hour: number): FrameImage {
  const { rows, cols } = h.grid
  const style = VARIABLES[variable]
  const frame = h.variables[variable][hour] ?? []
  const data = new Uint8ClampedArray(new ArrayBuffer(rows * cols * 4))
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const v = frame[r * cols + c]
      const o = ((rows - 1 - r) * cols + c) * 4
      if (v === null || v === undefined) continue // alpha stays 0
      const [red, green, blue, alpha] = colorAt(style, v)
      const fade = style.fadeBelow > 0 ? Math.min(Math.max(v / style.fadeBelow, 0), 1) : 1
      data[o] = red
      data[o + 1] = green
      data[o + 2] = blue
      data[o + 3] = Math.round(alpha * fade)
    }
  }
  return { width: cols, height: rows, data }
}

/** Departure rounded down to the hour = slider hour 0 (D14), as ISO UTC. */
export function hourZero(departureIso: string): string {
  const d = new Date(departureIso)
  d.setUTCMinutes(0, 0, 0)
  return d.toISOString().replace('.000Z', 'Z')
}

/** Where the truck is at a given time on a route, from checkpoint ETAs (display only). */
export function truckPosition(
  route: Route,
  atMs: number,
): { lon: number; lat: number; state: 'waiting' | 'driving' | 'arrived' } {
  const cps = route.checkpoints
  const first = cps[0]
  const last = cps[cps.length - 1]
  if (atMs <= new Date(first.eta).getTime()) return { lon: first.lon, lat: first.lat, state: 'waiting' }
  if (atMs >= new Date(last.eta).getTime()) return { lon: last.lon, lat: last.lat, state: 'arrived' }
  for (let k = 1; k < cps.length; k++) {
    const a = cps[k - 1]
    const b = cps[k]
    const ta = new Date(a.eta).getTime()
    const tb = new Date(b.eta).getTime()
    if (atMs <= tb) {
      const f = tb === ta ? 0 : (atMs - ta) / (tb - ta)
      return { lon: a.lon + (b.lon - a.lon) * f, lat: a.lat + (b.lat - a.lat) * f, state: 'driving' }
    }
  }
  return { lon: last.lon, lat: last.lat, state: 'arrived' }
}
