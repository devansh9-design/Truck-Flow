// P3-4 saved trips: browser-only (localStorage). A saved trip stores the inputs plus a short
// summary; reopening it re-runs the analysis, so weather and ranking are always fresh.
import type { AnalyzeResponse, Interval, Place, RiskLevel } from '../api/types'
import { INTERVALS, RISK_LEVELS } from '../api/types'

export const SAVED_TRIPS_KEY = 'truckrisk.savedTrips.v1'
export const MAX_SAVED_TRIPS = 20

export interface SavedTrip {
  id: string
  saved_at: string
  origin: Place
  destination: Place
  departure_time: string
  load_weight_lb: number
  interval_mi: Interval
  /** Trip time zone the departure was entered in. */
  time_zone: string
  /** Snapshot at save time, for the list only (reopening re-runs the analysis). */
  summary: { recommended_label: string; max_level: RiskLevel; distance_mi: number }
}

type Store = Pick<Storage, 'getItem' | 'setItem'>

function storage(): Store | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null
  }
}

const isPlace = (p: unknown): p is Place =>
  !!p &&
  typeof (p as Place).label === 'string' &&
  Number.isFinite((p as Place).lat) &&
  Number.isFinite((p as Place).lon)

function isSavedTrip(t: unknown): t is SavedTrip {
  const x = t as SavedTrip
  return (
    !!x &&
    typeof x.id === 'string' &&
    typeof x.saved_at === 'string' &&
    isPlace(x.origin) &&
    isPlace(x.destination) &&
    typeof x.departure_time === 'string' &&
    Number.isFinite(x.load_weight_lb) &&
    INTERVALS.includes(x.interval_mi) &&
    typeof x.time_zone === 'string' &&
    !!x.summary &&
    RISK_LEVELS.includes(x.summary.max_level)
  )
}

/** Saved trips, newest first. Corrupt storage or bad entries are ignored, never thrown. */
export function loadTrips(store: Store | null = storage()): SavedTrip[] {
  try {
    const raw = store?.getItem(SAVED_TRIPS_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isSavedTrip).slice(0, MAX_SAVED_TRIPS) : []
  } catch {
    return []
  }
}

/** Returns false when the browser refuses to store (private mode, quota). */
export function writeTrips(trips: SavedTrip[], store: Store | null = storage()): boolean {
  try {
    if (!store) return false
    store.setItem(SAVED_TRIPS_KEY, JSON.stringify(trips.slice(0, MAX_SAVED_TRIPS)))
    return true
  } catch {
    return false
  }
}

/** Same trip = same places, departure, load and interval. */
export const sameTrip = (a: Omit<SavedTrip, 'id' | 'saved_at' | 'summary'>, b: typeof a) =>
  a.origin.lat === b.origin.lat &&
  a.origin.lon === b.origin.lon &&
  a.destination.lat === b.destination.lat &&
  a.destination.lon === b.destination.lon &&
  Date.parse(a.departure_time) === Date.parse(b.departure_time) &&
  a.load_weight_lb === b.load_weight_lb &&
  a.interval_mi === b.interval_mi

export function tripFromResult(data: AnalyzeResponse, timeZone: string, now: Date = new Date()): SavedTrip {
  const rec = data.routes.find((r) => r.id === data.recommendation.route_id) ?? data.routes[0]
  return {
    id: `${now.getTime().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    saved_at: now.toISOString(),
    origin: data.trip.origin,
    destination: data.trip.destination,
    departure_time: data.trip.departure_time,
    load_weight_lb: data.trip.load_weight_lb,
    interval_mi: data.trip.interval_mi,
    time_zone: timeZone,
    summary: {
      recommended_label: rec?.label ?? '',
      max_level: rec?.summary.max_level ?? 'LOW',
      distance_mi: rec?.distance_mi ?? 0,
    },
  }
}

/** Newest first; an identical trip is replaced (not duplicated); capped at 20 (oldest dropped). */
export function addTrip(trips: SavedTrip[], trip: SavedTrip): SavedTrip[] {
  return [trip, ...trips.filter((t) => !sameTrip(t, trip))].slice(0, MAX_SAVED_TRIPS)
}

export const removeTrip = (trips: SavedTrip[], id: string): SavedTrip[] => trips.filter((t) => t.id !== id)

/**
 * The API refuses departures more than 1 h in the past, so a saved trip whose departure has
 * passed (with a 30 min margin) is reopened at the next whole hour instead.
 */
export const departureHasPassed = (iso: string, now: Date = new Date()) =>
  Date.parse(iso) < now.getTime() - 30 * 60 * 1000
