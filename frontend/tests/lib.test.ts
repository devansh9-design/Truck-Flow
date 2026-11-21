import { describe, expect, it } from 'vitest'
import { RISK_LEVELS, type DecidedBy } from '../src/api/types'
import { formatDuration, formatMiles, formatTime, nextHourInput, zonedInputToIso, zoneOffsetMinutes } from '../src/lib/format'
import { decidedByText, RISK_STYLE, riskColorExpression } from '../src/lib/risk'
import { riskSegments, cumulativeMiles, haversineMi } from '../src/lib/segments'
import { validateTrip } from '../src/lib/validate'
import { ANALYZE } from './fixtures'

describe('risk styles', () => {
  it('covers all 5 levels with colour, label and icon', () => {
    expect(Object.keys(RISK_STYLE).sort()).toEqual([...RISK_LEVELS].sort())
    for (const l of RISK_LEVELS) {
      const s = RISK_STYLE[l]
      expect(s.color).toMatch(/^#[0-9a-f]{6}$/i)
      expect(s.label.length).toBeGreaterThan(0)
      expect(s.icon.length).toBeGreaterThan(0)
    }
  })

  it('uses a distinct colour and icon per level', () => {
    expect(new Set(RISK_LEVELS.map((l) => RISK_STYLE[l].color)).size).toBe(5)
    expect(new Set(RISK_LEVELS.map((l) => RISK_STYLE[l].icon)).size).toBe(5)
  })

  it('builds a MapLibre match expression for every level', () => {
    const expr = riskColorExpression()
    for (const l of RISK_LEVELS) expect(expr).toContain(l)
  })

  it('explains every decided_by key', () => {
    const keys: DecidedBy[] = ['no_travel_mi', 'severe_mi', 'high_mi', 'avg_risk', 'duration_s', 'tie', 'only_route']
    for (const k of keys) expect(decidedByText(k)).not.toBe(k)
  })
})

describe('formatting', () => {
  it('formats miles and durations', () => {
    expect(formatMiles(521.44)).toBe('521.4 mi')
    expect(formatMiles(1234)).toBe('1,234.0 mi')
    expect(formatDuration(30240)).toBe('8 h 24 min')
    expect(formatDuration(3600)).toBe('1 h')
    expect(formatDuration(1500)).toBe('25 min')
  })

  it('reads the departure input as wall time in the trip zone', () => {
    expect(zonedInputToIso('2026-11-21T06:00', 'America/Denver')).toBe('2026-11-21T06:00:00-07:00')
    expect(zonedInputToIso('2026-07-01T06:00', 'America/Denver')).toBe('2026-07-01T06:00:00-06:00')
    expect(zonedInputToIso('2026-11-21T06:00', 'Asia/Kolkata')).toBe('2026-11-21T06:00:00+05:30')
    expect(zonedInputToIso('2026-11-21T06:00', 'UTC')).toBe('2026-11-21T06:00:00+00:00')
    expect(() => zonedInputToIso('', 'UTC')).toThrow()
  })

  it('handles the US DST change days', () => {
    // 2026-03-08 02:00 local jumps to 03:00 in Denver; 2026-11-01 01:00–02:00 repeats.
    expect(zonedInputToIso('2026-03-08T12:00', 'America/Denver')).toBe('2026-03-08T12:00:00-06:00')
    expect(zonedInputToIso('2026-11-01T12:00', 'America/Denver')).toBe('2026-11-01T12:00:00-07:00')
    expect(zoneOffsetMinutes('America/New_York', Date.UTC(2026, 0, 15))).toBe(-300)
  })

  it('defaults departure to the next whole hour in the trip zone', () => {
    const now = new Date(Date.UTC(2026, 10, 20, 16, 41)) // 09:41 in Denver
    expect(nextHourInput('America/Denver', now)).toBe('2026-11-20T10:00')
    expect(nextHourInput('UTC', new Date(Date.UTC(2026, 10, 20, 23, 5)))).toBe('2026-11-21T00:00')
    // 04:20Z is 09:50 in Kolkata (+05:30): next wall hour is 10:00, not 10:30.
    expect(nextHourInput('Asia/Kolkata', new Date(Date.UTC(2026, 10, 20, 4, 20)))).toBe('2026-11-20T10:00')
  })

  it('shows times in the trip zone', () => {
    expect(formatTime('2026-11-21T13:00:00Z', 'America/Denver')).toMatch(/6:00\sAM MST/)
  })
})

describe('trip validation', () => {
  const now = new Date('2026-11-20T12:00:00Z')
  const ok = {
    origin: 'Denver, CO',
    destination: 'Salt Lake City, UT',
    departure: '2026-11-20T13:00',
    timeZone: 'UTC',
    load: '42000',
  }

  it('accepts a valid trip', () => {
    expect(validateTrip(ok, now)).toEqual({})
  })

  it('flags each bad field', () => {
    expect(validateTrip({ ...ok, origin: 'D' }, now).origin).toBeDefined()
    expect(validateTrip({ ...ok, destination: ' denver, co ' }, now).destination).toMatch(/differ/)
    expect(validateTrip({ ...ok, departure: '' }, now).departure_time).toBeDefined()
    expect(validateTrip({ ...ok, load: '0' }, now).load_weight_lb).toBeDefined()
    expect(validateTrip({ ...ok, load: '100001' }, now).load_weight_lb).toBeDefined()
    expect(validateTrip({ ...ok, load: '100000' }, now).load_weight_lb).toBeUndefined()
  })

  it('allows up to 1 hour in the past', () => {
    expect(validateTrip({ ...ok, departure: '2026-11-20T11:00' }, now).departure_time).toBeUndefined()
    expect(validateTrip({ ...ok, departure: '2026-11-20T10:59' }, now).departure_time).toBeDefined()
    // Same wall time read in Denver (UTC-7) is 17:59Z: fine.
    expect(validateTrip({ ...ok, departure: '2026-11-20T10:59', timeZone: 'America/Denver' }, now).departure_time)
      .toBeUndefined()
  })
})

describe('risk segments', () => {
  it('measures distance with haversine', () => {
    // 1° of latitude ≈ 69.1 mi
    expect(haversineMi([0, 0], [0, 1])).toBeCloseTo(69.09, 1)
    const cum = cumulativeMiles([
      [0, 0],
      [0, 1],
      [0, 2],
    ])
    expect(cum[2]).toBeCloseTo(2 * cum[1], 6)
  })

  it('makes one segment per checkpoint gap, coloured by the worse endpoint', () => {
    const r = ANALYZE.routes[1] // LOW, HIGH, SEVERE, LOW
    const segs = riskSegments(r)
    expect(segs).toHaveLength(r.checkpoints.length - 1)
    expect(segs.map((s) => s.properties.level)).toEqual(['HIGH', 'SEVERE', 'SEVERE'])
  })

  it('starts and ends segments on the route line', () => {
    const r = ANALYZE.routes[0]
    const segs = riskSegments(r)
    const coords = r.geometry.coordinates
    expect(segs[0].geometry.coordinates[0]).toEqual(coords[0])
    const last = segs[segs.length - 1].geometry.coordinates
    expect(last[last.length - 1][0]).toBeCloseTo(coords[coords.length - 1][0], 6)
  })
})
