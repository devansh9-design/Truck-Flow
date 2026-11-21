// Driving mode (phase 1, D17): re-check the road ahead while the trip is under way.
// Every re-check is an ordinary analysis (same CORE rules and ranking) from the truck's
// current position to the destination, departing now. This file only decides *when* to
// re-check, which new route is the one being driven, and whether to warn.
import type { Checkpoint, Route, RouteSummary } from '../api/types'
import { riskStyle } from './risk'
import { haversineMi } from './segments'

type Coord = [number, number] // [lon, lat]

export const RECHECK_EVERY_MS = 15 * 60_000
/** Re-check early after this much driving... */
export const RECHECK_AFTER_MI = 25
/** ...but never more often than this. */
export const MIN_RECHECK_GAP_MS = 5 * 60_000
export const ARRIVED_WITHIN_MI = 3
/** Differences in No Travel / Severe miles at or below this are noise (rounding, segment ends). */
export const MILES_TOLERANCE = 1
/** High miles must improve by more than this before a switch is suggested. */
export const HIGH_MILES_TOLERANCE = 10
/** "Keep my route" silences warnings this long, unless the route gets worse. */
export const DISMISS_MS = 30 * 60_000

// --- geometry --------------------------------------------------------------------------------

/** Distance from point p to segment a-b in miles (local equirectangular projection). */
function pointSegmentMi(p: Coord, a: Coord, b: Coord): number {
  const kx = 69.172 * Math.cos((p[1] * Math.PI) / 180)
  const ky = 69.0
  const ax = (a[0] - p[0]) * kx
  const ay = (a[1] - p[1]) * ky
  const bx = (b[0] - p[0]) * kx
  const by = (b[1] - p[1]) * ky
  const dx = bx - ax
  const dy = by - ay
  const len2 = dx * dx + dy * dy
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2))
  return Math.hypot(ax + t * dx, ay + t * dy)
}

export function distanceToLineMi(p: Coord, line: Coord[]): number {
  if (line.length === 1) return haversineMi(p, line[0])
  let best = Infinity
  for (let i = 1; i < line.length; i++) best = Math.min(best, pointSegmentMi(p, line[i - 1], line[i]))
  return best
}

/** Points about every `stepMi` along a line (always including both ends). */
function samples(line: Coord[], stepMi: number): Coord[] {
  const out: Coord[] = [line[0]]
  let acc = 0
  for (let i = 1; i < line.length; i++) {
    acc += haversineMi(line[i - 1], line[i])
    if (acc >= stepMi) {
      out.push(line[i])
      acc = 0
    }
  }
  if (out[out.length - 1] !== line[line.length - 1]) out.push(line[line.length - 1])
  return out
}

/** Share (0-1) of `route` that lies within `withinMi` of the `reference` line. */
export function overlapShare(route: Coord[], reference: Coord[], withinMi = 0.5, stepMi = 2): number {
  if (route.length === 0 || reference.length === 0) return 0
  const pts = samples(route, stepMi)
  return pts.filter((p) => distanceToLineMi(p, reference) <= withinMi).length / pts.length
}

/**
 * Which route of a fresh analysis is the road the truck is on: the one that overlaps the
 * route being driven the most. `onRoute` is false when no route follows it well (the driver
 * left the planned road).
 */
export function matchCurrentRoute(routes: Route[], reference: Coord[]): { route: Route; onRoute: boolean } {
  let best = routes[0]
  let bestShare = -1
  for (const r of routes) {
    const share = overlapShare(r.geometry.coordinates, reference)
    if (share > bestShare) {
      best = r
      bestShare = share
    }
  }
  return { route: best, onRoute: bestShare >= 0.5 }
}

// --- timing ----------------------------------------------------------------------------------

export interface LastCheck {
  at: number
  pos: Coord | null
}

export function shouldRecheck(last: LastCheck, pos: Coord | null, now: number): boolean {
  if (!pos) return false
  if (!last.pos) return true // first GPS fix of the trip
  const gap = now - last.at
  if (gap >= RECHECK_EVERY_MS) return true
  return gap >= MIN_RECHECK_GAP_MS && haversineMi(last.pos, pos) >= RECHECK_AFTER_MI
}

export const hasArrived = (pos: Coord, destination: Coord) => haversineMi(pos, destination) <= ARRIVED_WITHIN_MI

// --- assessment -------------------------------------------------------------------------------

/** True when `a` is meaningfully safer than `b` on the weather keys (No Travel, Severe, High). */
export function saferOnWeather(a: RouteSummary, b: RouteSummary): boolean {
  if (a.no_travel_mi < b.no_travel_mi - MILES_TOLERANCE) return true
  if (Math.abs(a.no_travel_mi - b.no_travel_mi) > MILES_TOLERANCE) return false
  if (a.severe_mi < b.severe_mi - MILES_TOLERANCE) return true
  if (Math.abs(a.severe_mi - b.severe_mi) > MILES_TOLERANCE) return false
  return a.high_mi < b.high_mi - HIGH_MILES_TOLERANCE
}

/** True when the route got worse since `before` (more No Travel or Severe miles). */
export function worsened(now: RouteSummary, before: RouteSummary): boolean {
  return now.no_travel_mi > before.no_travel_mi + MILES_TOLERANCE || now.severe_mi > before.severe_mi + MILES_TOLERANCE
}

export interface Format {
  distance: (mi: number, digits?: number) => string
}

const FACTOR_WORDS = { wind: 'strong wind', rain: 'heavy rain', snow: 'heavy snow' } as const

/** What makes a checkpoint risky, in words ("strong wind", "strong wind for this load"). */
export function cause(cp: Checkpoint): string {
  const f = cp.risk.factors
  const order = ['NO_TRAVEL', 'SEVERE', 'HIGH', 'MODERATE', 'LOW']
  const worst = (['wind', 'rain', 'snow'] as const).reduce((w, k) =>
    order.indexOf(f[k]) < order.indexOf(f[w]) ? k : w,
  )
  return f.load_override ? `${FACTOR_WORDS[worst]} for this load` : FACTOR_WORDS[worst]
}

function inAbout(seconds: number): string {
  const min = Math.max(0, Math.round(seconds / 60))
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h} h ${m} min` : `${h} h`
}

/** "18 mi of Severe conditions (strong wind), starting 40 mi ahead in about 45 min". */
export function hazardText(route: Route, now: number, f: Format): string | null {
  const s = route.summary
  const level = s.no_travel_mi > 0 ? 'NO_TRAVEL' : s.severe_mi > 0 ? 'SEVERE' : s.high_mi > 0 ? 'HIGH' : null
  if (!level) return null
  const miles = level === 'NO_TRAVEL' ? s.no_travel_mi : level === 'SEVERE' ? s.severe_mi : s.high_mi
  const first = route.checkpoints.find((c) => c.risk.level === level)
  const where = first
    ? `, starting ${f.distance(first.mile, 0)} ahead in about ${inAbout((Date.parse(first.eta) - now) / 1000)}`
    : ''
  const why = first ? ` (${cause(first)})` : ''
  return `${f.distance(miles, 0)} of ${riskStyle(level).label} conditions${why}${where}`
}

function timeDelta(seconds: number): string {
  const min = Math.round(seconds / 60)
  if (Math.abs(min) < 1) return 'about the same time'
  return min > 0 ? `${inAbout(seconds)} longer` : `${inAbout(-seconds)} shorter`
}

export interface DrivingWarning {
  kind: 'switch' | 'worsened'
  title: string
  message: string
  /** Shorter text read aloud. */
  spoken: string
  /** Route to switch to (kind "switch"). */
  suggestRouteId?: string
  suggestLabel?: string
}

/**
 * Should the driver be warned after a re-check?
 * - "switch": another route is meaningfully safer on No Travel / Severe / High miles
 *   (time alone never triggers a warning while driving).
 * - "worsened": the current route got worse since the last check and nothing safer exists.
 */
export function assess(
  current: Route,
  best: Route,
  previous: RouteSummary | null,
  now: number,
  f: Format,
): DrivingWarning | null {
  const hazard = hazardText(current, now, f)
  const gotWorse = !!previous && worsened(current.summary, previous)
  if (best.id !== current.id && saferOnWeather(best.summary, current.summary)) {
    const lead = gotWorse ? 'Weather on your route has worsened' : 'Your route has risky weather ahead'
    const delta = timeDelta(best.duration_s - current.duration_s)
    return {
      kind: 'switch',
      title: `Safer route available: ${best.label}`,
      message: `${lead}: ${hazard ?? 'more risk than another route'}. ${best.label} avoids most of it (${delta}).`,
      spoken: `${lead}. ${best.label} is safer. Pull over safely before using the screen.`,
      suggestRouteId: best.id,
      suggestLabel: best.label,
    }
  }
  if (gotWorse) {
    return {
      kind: 'worsened',
      title: 'Weather on your route has worsened',
      message: `${hazard ?? 'Risk has increased ahead'}. No safer route was found. Consider stopping somewhere safe until it passes.`,
      spoken: 'Weather on your route has worsened. No safer route was found. Consider stopping somewhere safe.',
    }
  }
  return null
}
