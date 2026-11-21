// P3-3 weather alerts (non-core, informational only). Nothing here feeds risk or ranking.
import type { AlertSeverity, Route, WeatherAlert } from '../api/types'
import { haversineMi } from './segments'

export const ALERT_SPACING_MI = 50
export const ALERT_MAX_POINTS = 100
/** Points closer than this to one already chosen (e.g. shared stretches) are skipped. */
const DEDUPE_MI = 10

export interface AlertPoint {
  lat: number
  lon: number
  /** Routes passing this point (ids). */
  routeIds: string[]
}

/** Points every `spacingMi` along one line ([lon, lat] pairs), always with both ends. */
export function pointsAlong(coords: [number, number][], spacingMi: number): [number, number][] {
  if (coords.length === 0) return []
  const out: [number, number][] = [coords[0]]
  let next = spacingMi
  let walked = 0
  for (let i = 1; i < coords.length; i++) {
    const a = coords[i - 1]
    const b = coords[i]
    const d = haversineMi(a, b)
    while (d > 0 && walked + d >= next) {
      const t = (next - walked) / d
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
      next += spacingMi
    }
    walked += d
  }
  const last = coords[coords.length - 1]
  const tail = out[out.length - 1]
  if (tail[0] !== last[0] || tail[1] !== last[1]) out.push(last)
  return out
}

/**
 * About every 50 mi along every route, shared stretches only once, at most 100 points
 * (the spacing widens for very long trips so the cap is never exceeded).
 */
export function alertPoints(routes: Route[], maxPoints = ALERT_MAX_POINTS): AlertPoint[] {
  let spacing = ALERT_SPACING_MI
  for (;;) {
    const chosen: AlertPoint[] = []
    for (const r of routes) {
      for (const [lon, lat] of pointsAlong(r.geometry.coordinates, spacing)) {
        const near = chosen.find((p) => haversineMi([p.lon, p.lat], [lon, lat]) < DEDUPE_MI)
        if (near) {
          if (!near.routeIds.includes(r.id)) near.routeIds.push(r.id)
        } else {
          chosen.push({ lat: round4(lat), lon: round4(lon), routeIds: [r.id] })
        }
      }
    }
    if (chosen.length <= maxPoints) return chosen
    spacing *= 1.5
  }
}

const round4 = (n: number) => Math.round(n * 1e4) / 1e4

export const SEVERITY_ORDER: AlertSeverity[] = ['Extreme', 'Severe', 'Moderate', 'Minor', 'Unknown']

/** Alert badges use an amber/orange scale and a ⚠ icon, distinct from the risk palette. */
export const SEVERITY_STYLE: Record<AlertSeverity, { bg: string; text: string; border: string }> = {
  Extreme: { bg: '#7c2d12', text: '#ffffff', border: '#431407' },
  Severe: { bg: '#c2410c', text: '#ffffff', border: '#7c2d12' },
  Moderate: { bg: '#f59e0b', text: '#1f1300', border: '#b45309' },
  Minor: { bg: '#fde68a', text: '#3b2a00', border: '#d97706' },
  Unknown: { bg: '#e2e8f0', text: '#0f172a', border: '#64748b' },
}

/** Alerts grouped by the request point they were found at (one map badge per point). */
export function alertsByPoint(alerts: WeatherAlert[]): Map<number, WeatherAlert[]> {
  const out = new Map<number, WeatherAlert[]>()
  for (const a of alerts) {
    const list = out.get(a.point_index) ?? []
    list.push(a)
    out.set(a.point_index, list)
  }
  return out
}

/** The most severe of a non-empty list. */
export function topSeverity(alerts: WeatherAlert[]): AlertSeverity {
  return SEVERITY_ORDER.find((s) => alerts.some((a) => a.severity === s)) ?? 'Unknown'
}
