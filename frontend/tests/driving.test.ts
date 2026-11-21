// Driving mode (D17): when to re-check, which route is being driven, when to warn.
import { describe, expect, it } from 'vitest'
import type { Route, RouteSummary } from '../src/api/types'
import {
  assess,
  distanceToLineMi,
  hasArrived,
  hazardText,
  matchCurrentRoute,
  MIN_RECHECK_GAP_MS,
  overlapShare,
  RECHECK_EVERY_MS,
  saferOnWeather,
  shouldRecheck,
  worsened,
} from '../src/lib/driving'
import { unitFormat } from '../src/lib/units'
import { ANALYZE } from './fixtures'

type Coord = [number, number]
const f = unitFormat('imperial')

const summary = (over: Partial<RouteSummary> = {}): RouteSummary => ({
  miles_by_level: { LOW: 100, MODERATE: 0, HIGH: 0, SEVERE: 0, NO_TRAVEL: 0 },
  severe_mi: 0,
  high_mi: 0,
  no_travel_mi: 0,
  has_no_travel: false,
  avg_risk: 1,
  max_level: 'LOW',
  ...over,
})

const withSummary = (r: Route, s: Partial<RouteSummary>, extra: Partial<Route> = {}): Route => ({
  ...r,
  summary: summary(s),
  ...extra,
})

// Two lines along 40N and one along 41N, ~85 mi long.
const lineA: Coord[] = [
  [-105, 40],
  [-104, 40],
]
const lineB: Coord[] = [
  [-105, 41],
  [-104, 41],
]

describe('geometry', () => {
  it('measures distance to a line', () => {
    expect(distanceToLineMi([-104.5, 40], lineA)).toBeCloseTo(0, 5)
    expect(distanceToLineMi([-104.5, 40.1], lineA)).toBeCloseTo(6.9, 1)
  })

  it('overlap share is 1 on the same road and 0 on a road 69 mi away', () => {
    expect(overlapShare(lineA, lineA)).toBe(1)
    expect(overlapShare(lineB, lineA)).toBe(0)
  })

  it('matches the fresh route that follows the road being driven', () => {
    const r0 = ANALYZE.routes.find((r) => r.id === 'r0')!
    const r1 = ANALYZE.routes.find((r) => r.id === 'r1')!
    const routes = [
      { ...r0, geometry: { type: 'LineString' as const, coordinates: lineB } },
      { ...r1, geometry: { type: 'LineString' as const, coordinates: lineA } },
    ]
    // The truck has driven part of A: the remaining part still lies on A.
    const remaining: Coord[] = [
      [-104.6, 40],
      [-104, 40],
    ]
    const m = matchCurrentRoute(routes, lineA)
    expect(m.route.id).toBe(r1.id)
    expect(m.onRoute).toBe(true)
    expect(matchCurrentRoute(routes, remaining).route.id).toBe(r1.id)
    expect(
      matchCurrentRoute(routes, [
        [-100, 30],
        [-99, 30],
      ]).onRoute,
    ).toBe(false)
  })
})

describe('when to re-check', () => {
  const t0 = 1_000_000_000_000
  const here: Coord = [-104.99, 39.74]

  it('re-checks on the first GPS fix', () => {
    expect(shouldRecheck({ at: t0, pos: null }, here, t0)).toBe(true)
    expect(shouldRecheck({ at: t0, pos: null }, null, t0)).toBe(false)
  })

  it('every 15 minutes even when stopped', () => {
    expect(shouldRecheck({ at: t0, pos: here }, here, t0 + RECHECK_EVERY_MS - 1)).toBe(false)
    expect(shouldRecheck({ at: t0, pos: here }, here, t0 + RECHECK_EVERY_MS)).toBe(true)
  })

  it('early after 25 mi of driving, but not more than every 5 minutes', () => {
    const far: Coord = [-104.99, 40.2] // ~32 mi north
    expect(shouldRecheck({ at: t0, pos: here }, far, t0 + MIN_RECHECK_GAP_MS - 1)).toBe(false)
    expect(shouldRecheck({ at: t0, pos: here }, far, t0 + MIN_RECHECK_GAP_MS)).toBe(true)
    expect(shouldRecheck({ at: t0, pos: here }, [-104.99, 39.9], t0 + MIN_RECHECK_GAP_MS)).toBe(false)
  })

  it('arrival within 3 mi of the destination', () => {
    expect(hasArrived([-111.89, 40.76], [-111.9, 40.77])).toBe(true)
    expect(hasArrived([-111.89, 40.76], [-111.89, 40.86])).toBe(false)
  })
})

describe('weather comparison (No Travel, then Severe, then High miles)', () => {
  it('needs a real difference, not rounding noise', () => {
    expect(saferOnWeather(summary({ severe_mi: 0 }), summary({ severe_mi: 0.8 }))).toBe(false)
    expect(saferOnWeather(summary({ severe_mi: 0 }), summary({ severe_mi: 12 }))).toBe(true)
  })

  it('No Travel miles decide first', () => {
    expect(saferOnWeather(summary({ no_travel_mi: 0, severe_mi: 40 }), summary({ no_travel_mi: 5 }))).toBe(true)
    expect(saferOnWeather(summary({ no_travel_mi: 5 }), summary({ no_travel_mi: 0, severe_mi: 40 }))).toBe(false)
  })

  it('High miles need a bigger margin', () => {
    expect(saferOnWeather(summary({ high_mi: 0 }), summary({ high_mi: 8 }))).toBe(false)
    expect(saferOnWeather(summary({ high_mi: 0 }), summary({ high_mi: 30 }))).toBe(true)
  })

  it('worsened = more No Travel or Severe miles than before', () => {
    expect(worsened(summary({ severe_mi: 20 }), summary({ severe_mi: 0 }))).toBe(true)
    expect(worsened(summary({ severe_mi: 0.5 }), summary({ severe_mi: 0 }))).toBe(false)
    expect(worsened(summary({ high_mi: 50 }), summary())).toBe(false)
  })
})

describe('warnings', () => {
  const r0 = ANALYZE.routes.find((r) => r.id === 'r0')!
  const r1 = ANALYZE.routes.find((r) => r.id === 'r1')!
  const now = Date.parse('2026-11-21T12:00:00Z')

  it('suggests a safer route, naming the hazard and the time cost', () => {
    const current = withSummary(r0, { severe_mi: 25 }, { duration_s: 10_000 })
    const best = withSummary(r1, {}, { duration_s: 10_720 })
    const w = assess(current, best, summary(), now, f)!
    expect(w.kind).toBe('switch')
    expect(w.suggestRouteId).toBe(r1.id)
    expect(w.title).toBe(`Safer route available: ${r1.label}`)
    expect(w.message).toMatch(
      /^Weather on your route has worsened: 25 mi of Severe conditions \(heavy snow\), starting 50 mi ahead/,
    )
    expect(w.message).toContain('(12 min longer)')
    expect(w.spoken).toContain('Pull over safely')
  })

  it('a faster route alone never triggers a warning while driving', () => {
    const current = withSummary(r0, {}, { duration_s: 10_000 })
    const best = withSummary(r1, {}, { duration_s: 8_000 })
    expect(assess(current, best, summary(), now, f)).toBeNull()
  })

  it('warns that the route got worse when nothing safer exists', () => {
    const current = withSummary(r1, { severe_mi: 25 })
    const w = assess(current, current, summary(), now, f)!
    expect(w.kind).toBe('worsened')
    expect(w.message).toContain('No safer route was found')
  })

  it('no warning when nothing changed', () => {
    const current = withSummary(r1, { severe_mi: 25 })
    expect(assess(current, current, summary({ severe_mi: 25 }), now, f)).toBeNull()
  })

  it('hazard text uses the chosen units and is empty for a calm route', () => {
    const current = withSummary(r0, { severe_mi: 25 })
    expect(hazardText(current, now, unitFormat('metric'))).toMatch(/^40 km of Severe conditions/)
    expect(hazardText(withSummary(r1, {}), now, f)).toBeNull()
  })
})
