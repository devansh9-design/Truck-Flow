// Upgrade 2 (non-core): unit conversion, saved trips, alert sampling, alerts panel.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import type { AlertsResponse, WeatherAlert } from '../src/api/types'
import { AlertsPanel } from '../src/components/AlertsPanel'
import { Results } from '../src/components/Results'
import { alertPoints, alertsByPoint, pointsAlong, topSeverity } from '../src/lib/alerts'
import {
  addTrip,
  departureHasPassed,
  loadTrips,
  MAX_SAVED_TRIPS,
  removeTrip,
  SAVED_TRIPS_KEY,
  tripFromResult,
  writeTrips,
  type SavedTrip,
} from '../src/lib/savedTrips'
import { haversineMi } from '../src/lib/segments'
import { inHrToMmHr, kmhToMph, kmToMi, lbToKg, miToKm, mmHrToInHr, mphToKmh, unitFormat } from '../src/lib/units'
import { useUi } from '../src/store/ui'
import { ANALYZE } from './fixtures'

describe('P3-2 unit conversion (display only)', () => {
  it('converts with the exact factors', () => {
    expect(miToKm(1)).toBeCloseTo(1.609344, 9)
    expect(mphToKmh(45)).toBeCloseTo(72.42048, 6)
    expect(inHrToMmHr(1)).toBe(25.4)
    expect(lbToKg(1000)).toBeCloseTo(453.59237, 6)
  })

  it.each([0, 0.01, 0.25, 1, 3, 35, 45, 525.2, 99999])('round-trips %s within tolerance', (v) => {
    expect(kmToMi(miToKm(v))).toBeCloseTo(v, 9)
    expect(kmhToMph(mphToKmh(v))).toBeCloseTo(v, 9)
    expect(mmHrToInHr(inHrToMmHr(v))).toBeCloseTo(v, 9)
  })

  it('formats per unit system', () => {
    const imp = unitFormat('imperial')
    const met = unitFormat('metric')
    expect(imp.distance(525.2)).toBe('525.2 mi')
    expect(met.distance(525.2)).toBe('845.2 km')
    expect(imp.speed(45)).toBe('45.0 mph')
    expect(met.speed(45)).toBe('72.4 km/h')
    expect(imp.rate(0.25)).toBe('0.25 in/hr')
    expect(met.rate(0.25)).toBe('6.4 mm/hr')
    expect(met.weight(42000)).toBe('19,051 kg')
    expect(met.convert(1, 'in/hr')).toBe(25.4)
    expect(met.convert(3, '')).toBe(3)
  })
})

describe('P3-2 toggle never changes a core result', () => {
  beforeEach(() => {
    useUi.getState().setUnits('imperial')
    useUi.getState().reset(ANALYZE.recommendation.route_id)
  })

  it('switches numbers but keeps order, recommendation and risk levels', () => {
    const { container } = render(<Results data={ANALYZE} />)
    const cards = () => [...container.querySelectorAll('[data-testid^="route-card-"]')]
    const order = () => cards().map((e) => e.getAttribute('data-testid'))
    const levels = () => cards().map((e) => e.textContent!.match(/Low|Moderate|High|Severe|No Travel/)?.[0])
    const before = { order: order(), levels: levels(), rec: screen.getByTestId('recommendation').textContent }
    const card = () => within(screen.getByTestId('route-card-r0'))
    expect(card().getAllByText(/ mi$/).length).toBeGreaterThan(0)

    act(() => useUi.getState().setUnits('metric'))
    expect(card().getAllByText(/ km$/).length).toBeGreaterThan(0)
    expect(card().queryAllByText(/ mi$/)).toHaveLength(0)
    expect(order()).toEqual(before.order)
    expect(levels()).toEqual(before.levels)
    expect(screen.getByTestId('recommendation').textContent).toBe(before.rec)
  })

  it('remembers the choice in this browser', () => {
    useUi.getState().setUnits('metric')
    expect(localStorage.getItem('truckrisk.units')).toBe('metric')
    useUi.getState().setUnits('imperial')
  })
})

class MemoryStore {
  data = new Map<string, string>()
  getItem = (k: string) => this.data.get(k) ?? null
  setItem = (k: string, v: string) => {
    this.data.set(k, v)
  }
}

const trip = (i: number, over: Partial<SavedTrip> = {}): SavedTrip => ({
  ...tripFromResult(ANALYZE, 'America/Denver', new Date(Date.UTC(2026, 10, 20, 0, i))),
  id: `t${i}`,
  load_weight_lb: 1000 + i,
  ...over,
})

describe('P3-4 saved trips store', () => {
  it('adds newest first, lists and deletes', () => {
    let list = addTrip([], trip(1))
    list = addTrip(list, trip(2))
    expect(list.map((t) => t.id)).toEqual(['t2', 't1'])
    list = removeTrip(list, 't2')
    expect(list.map((t) => t.id)).toEqual(['t1'])
  })

  it('caps at 20, dropping the oldest', () => {
    let list: SavedTrip[] = []
    for (let i = 0; i < 25; i++) list = addTrip(list, trip(i))
    expect(list).toHaveLength(MAX_SAVED_TRIPS)
    expect(list[0].id).toBe('t24')
    expect(list.at(-1)!.id).toBe('t5')
  })

  it('replaces an identical trip instead of duplicating it', () => {
    const list = addTrip(addTrip([], trip(1)), trip(1, { id: 'again' }))
    expect(list.map((t) => t.id)).toEqual(['again'])
  })

  it('survives a page reload (storage round trip)', () => {
    const store = new MemoryStore()
    expect(writeTrips([trip(2), trip(1)], store)).toBe(true)
    expect(loadTrips(store).map((t) => t.id)).toEqual(['t2', 't1'])
  })

  it.each(['{not json', '"a string"', '{"a":1}', 'null'])('survives corrupt storage: %s', (raw) => {
    const store = new MemoryStore()
    store.setItem(SAVED_TRIPS_KEY, raw)
    expect(loadTrips(store)).toEqual([])
  })

  it('drops malformed entries and keeps good ones', () => {
    const store = new MemoryStore()
    store.setItem(SAVED_TRIPS_KEY, JSON.stringify([{ id: 'x' }, trip(1), { ...trip(2), interval_mi: 7 }]))
    expect(loadTrips(store).map((t) => t.id)).toEqual(['t1'])
  })

  it('reports storage that refuses writes', () => {
    const broken = {
      getItem: () => null,
      setItem: () => {
        throw new Error('QuotaExceeded')
      },
    }
    expect(writeTrips([trip(1)], broken)).toBe(false)
    expect(writeTrips([trip(1)], null)).toBe(false)
  })

  it('stores resolved places so reopening skips geocoding', () => {
    const t = tripFromResult(ANALYZE, 'America/Denver')
    expect(t.origin).toEqual(ANALYZE.trip.origin)
    expect(t.summary.recommended_label).toBe('Route B')
  })

  it('flags departures that have passed', () => {
    const now = new Date('2026-11-20T12:00:00Z')
    expect(departureHasPassed('2026-11-20T11:00:00Z', now)).toBe(true)
    expect(departureHasPassed('2026-11-20T11:45:00Z', now)).toBe(false)
    expect(departureHasPassed('2026-11-21T11:00:00Z', now)).toBe(false)
  })
})

describe('P3-3 alert points', () => {
  // A straight line about 300 mi long, due east along 40N.
  const line: [number, number][] = [
    [-110, 40],
    [-104.35, 40],
  ]
  const route = (id: string, coordinates: [number, number][]) => ({
    ...ANALYZE.routes[0],
    id,
    geometry: { type: 'LineString' as const, coordinates },
  })

  it('samples about every 50 mi with both ends', () => {
    const pts = pointsAlong(line, 50)
    const total = haversineMi(line[0], line[1])
    expect(pts[0]).toEqual(line[0])
    expect(pts.at(-1)).toEqual(line[1])
    expect(pts).toHaveLength(Math.floor(total / 50) + 2)
    expect(haversineMi(pts[0], pts[1])).toBeCloseTo(50, 0)
  })

  it('shares points between overlapping routes and respects the cap', () => {
    const pts = alertPoints([route('a', line), route('b', line)])
    expect(pts.every((p) => p.routeIds.join() === 'a,b')).toBe(true)
    const long = route('c', [
      [-120, 40],
      [-75, 40],
    ])
    expect(alertPoints([long]).length).toBeLessThanOrEqual(100)
    expect(alertPoints([long], 10).length).toBeLessThanOrEqual(10)
  })

  it('groups by point and picks the most severe', () => {
    const base = { headline: null, areas: '', onset: null, ends: null, point_index: 2 }
    const alerts: WeatherAlert[] = [
      { ...base, id: '1', event: 'A', severity: 'Minor' },
      { ...base, id: '2', event: 'B', severity: 'Severe' },
    ]
    const g = alertsByPoint(alerts)
    expect([...g.keys()]).toEqual([2])
    expect(topSeverity(g.get(2)!)).toBe('Severe')
  })
})

describe('P3-3 alerts panel', () => {
  const points = [{ lat: 40, lon: -105, routeIds: ['r0', 'r1'] }]
  const props = { routes: ANALYZE.routes, points, loading: false, error: null, onRetry: () => {} }

  it('lists alerts with severity and the routes they are near', async () => {
    const data: AlertsResponse = {
      coverage: 'US',
      alerts: [
        {
          id: 'w',
          event: 'High Wind Warning',
          severity: 'Severe',
          headline: null,
          areas: 'South Laramie Range',
          onset: '2026-11-20T15:00:00Z',
          ends: null,
          point_index: 0,
        },
      ],
    }
    render(<AlertsPanel {...props} data={data} />)
    const item = screen.getByTestId('alert-item')
    expect(item).toHaveTextContent('High Wind Warning')
    expect(item).toHaveTextContent('Severe')
    expect(item).toHaveTextContent('Near Route A, Route B')
    expect(item).toHaveTextContent('further notice')
    await userEvent.click(item)
    expect(useUi.getState().selectedAlertPoint).toBe(0)
  })

  it('says alerts are not available outside the US', () => {
    render(<AlertsPanel {...props} data={{ coverage: 'unsupported_region', alerts: [] }} />)
    expect(screen.getByTestId('alerts-panel')).toHaveTextContent('not available for this region')
  })

  it('degrades gracefully when the alert service fails', () => {
    render(<AlertsPanel {...props} data={undefined} error="boom" />)
    expect(screen.getByRole('alert')).toHaveTextContent('unavailable')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
