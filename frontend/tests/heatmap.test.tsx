import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { HeatmapResponse } from '../src/api/types'
import { HeatmapPanel } from '../src/components/HeatmapPanel'
import {
  anchors,
  colorAt,
  colorRange,
  frameImage,
  gridBounds,
  HEATMAP_HOURS,
  hourZero,
  truckPosition,
  VARIABLES,
} from '../src/lib/heatmap'
import { RISK_STYLE } from '../src/lib/risk'
import { useUi } from '../src/store/ui'
import { ANALYZE } from './fixtures'

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))

/** 2 rows x 3 cols; every frame has value = 10*row + col + hour/100 (or null at r1c2). */
function heat(): HeatmapResponse {
  const times = Array.from({ length: 49 }, (_, h) => new Date(Date.UTC(2026, 10, 21, 13 + h)).toISOString())
  const frame = (h: number) => [0, 1, 2, 10, 11, null].map((v) => (v === null ? null : v + h / 100))
  const frames = Array.from({ length: 49 }, (_, h) => frame(h))
  return {
    grid: { rows: 2, cols: 3, lats: [39.0, 40.0], lons: [-110.0, -109.0, -108.0] },
    times,
    hours: 49,
    variables: { risk: frames, wind_mph: frames, rain_in_hr: frames, snow_in_hr: frames },
    source: 'open-meteo',
    generated_at: times[0],
  }
}

describe('heatmap colour scales', () => {
  it('uses the spec §5 thresholds as legend ticks', () => {
    expect(VARIABLES.wind_mph.ticks).toEqual([25, 35, 45, 55])
    expect(VARIABLES.rain_in_hr.ticks).toEqual([0.1, 0.25, 0.5, 1.0])
    expect(VARIABLES.snow_in_hr.ticks).toEqual([0.5, 1, 2, 3])
    expect(VARIABLES.risk.ticks).toEqual([1, 2, 3, 4, 5])
  })

  it('shows each risk score in its checkpoint colour', () => {
    const levels = ['LOW', 'MODERATE', 'HIGH', 'SEVERE', 'NO_TRAVEL'] as const
    levels.forEach((l, i) => expect(colorAt(VARIABLES.risk, i + 1).slice(0, 3)).toEqual(rgb(RISK_STYLE[l].color)))
  })

  it('puts each weather threshold halfway between the two level colours', () => {
    for (const key of ['wind_mph', 'rain_in_hr', 'snow_in_hr'] as const) {
      const s = VARIABLES[key]
      const a = anchors(s)
      // Inside a band the colour is that band's; band centres increase.
      expect(a.map((x) => x.v)).toEqual([...a.map((x) => x.v)].sort((p, q) => p - q))
      expect(colorAt(s, a[1].v).slice(0, 3)).toEqual(rgb(RISK_STYLE.MODERATE.color))
    }
  })

  it('builds a colour range deck.gl can sample', () => {
    const r = colorRange(VARIABLES.risk)
    expect(r).toHaveLength(64)
    r.forEach((c) => expect(c).toHaveLength(4))
  })
})

describe('frame images', () => {
  it('has one pixel per cell with the north row first', () => {
    const h = heat()
    const img = frameImage(h, 'risk', 0)
    expect([img.width, img.height]).toEqual([3, 2])
    // Image row 0 is grid row 1 (north): its first cell has value 10 -> No Travel colour.
    expect(Array.from(img.data.slice(0, 3))).toEqual(rgb(RISK_STYLE.NO_TRAVEL.color))
    // Image row 1 is grid row 0 (south): value 1 at column 1 -> Low colour.
    expect(Array.from(img.data.slice(16, 19))).toEqual(rgb(RISK_STYLE.LOW.color))
  })

  it('leaves cells without data fully transparent (never drawn as calm)', () => {
    const img = frameImage(heat(), 'risk', 0)
    expect(img.data[2 * 4 + 3]).toBe(0) // north row, column 2 is null
  })

  it('fades calm weather towards transparent', () => {
    const img = frameImage(heat(), 'wind_mph', 0) // value 0 at south-west cell
    expect(img.data[3 * 4 + 3]).toBe(0)
  })

  it('covers the cells edge to edge', () => {
    expect(gridBounds(heat())).toEqual([-110.5, 38.5, -107.5, 40.5])
  })

  it('has 49 hourly frames: hour 0 is the departure hour rounded down', () => {
    expect(HEATMAP_HOURS).toBe(49)
    expect(hourZero('2026-11-21T13:40:00Z')).toBe('2026-11-21T13:00:00Z')
  })
})

describe('truck position at the slider hour', () => {
  const route = ANALYZE.routes[0] // ETAs 13:00, 14:00, 15:00, 16:00 UTC
  const at = (iso: string) => truckPosition(route, new Date(iso).getTime())

  it('waits at the origin before departure and stops at the destination', () => {
    expect(at('2026-11-21T12:00:00Z')).toMatchObject({ state: 'waiting', lon: route.checkpoints[0].lon })
    expect(at('2026-11-21T18:00:00Z')).toMatchObject({ state: 'arrived', lon: route.checkpoints[3].lon })
  })

  it('interpolates between checkpoint ETAs', () => {
    const p = at('2026-11-21T14:30:00Z')
    expect(p.state).toBe('driving')
    expect(p.lon).toBeCloseTo((route.checkpoints[1].lon + route.checkpoints[2].lon) / 2, 6)
  })
})

describe('HeatmapPanel', () => {
  beforeEach(() => {
    useUi.setState({ heatHour: 0, heatVariable: 'risk', heatVisible: true, timeZone: 'UTC' })
  })

  it('has a 0–48 h slider labelled with the time', () => {
    const h = heat()
    render(<HeatmapPanel times={h.times} loading={false} error={null} onRetry={() => {}} route={undefined} />)
    const slider = screen.getByRole('slider', { name: /forecast hour/i })
    expect(slider).toHaveAttribute('min', '0')
    expect(slider).toHaveAttribute('max', '48')
    expect(screen.getByText('Departure hour')).toBeInTheDocument()
    // jsdom has no native range keyboard handling; browsers do (arrows, Home, End).
    fireEvent.change(slider, { target: { value: '3' } })
    expect(useUi.getState().heatHour).toBe(3)
    expect(screen.getByText('+3 h')).toBeInTheDocument()
    expect(slider).toHaveAttribute('aria-valuetext', expect.stringContaining('3 hours after departure'))
    fireEvent.change(slider, { target: { value: '48' } })
    expect(useUi.getState().heatHour).toBe(48)
  })

  it('switches variable and visibility', async () => {
    const h = heat()
    render(<HeatmapPanel times={h.times} loading={false} error={null} onRetry={() => {}} route={undefined} />)
    await userEvent.click(screen.getByRole('radio', { name: 'Snow' }))
    expect(useUi.getState().heatVariable).toBe('snow_in_hr')
    await userEvent.click(screen.getByRole('checkbox', { name: /forecast heatmap/i }))
    expect(useUi.getState().heatVisible).toBe(false)
  })

  it('shows an error with retry and says core results are unaffected', async () => {
    const retry = vi.fn()
    render(<HeatmapPanel times={undefined} loading={false} error="down" onRetry={retry} route={undefined} />)
    expect(screen.getByRole('alert')).toHaveTextContent(/unaffected/)
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(retry).toHaveBeenCalled()
  })

  it('disables the slider while the forecast loads', () => {
    render(<HeatmapPanel times={undefined} loading error={null} onRetry={() => {}} route={undefined} />)
    expect(screen.getByRole('slider', { name: /forecast hour/i })).toBeDisabled()
    expect(screen.getByText(/Loading 48-hour forecast/)).toBeInTheDocument()
  })
})
