// Split a route line into risk-coloured pieces between consecutive checkpoints.
// Display only: the level of each piece is the worse endpoint, mirroring how the backend
// scores segments (ADR-007), but nothing here feeds back into scoring or ranking.
import type { Checkpoint, RiskLevel, Route } from '../api/types'

type Coord = [number, number]

const EARTH_RADIUS_MI = 3958.7613
const rad = (d: number) => (d * Math.PI) / 180

export function haversineMi([lon1, lat1]: Coord, [lon2, lat2]: Coord): number {
  const dLat = rad(lat2 - lat1)
  const dLon = rad(lon2 - lon1)
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_MI * Math.asin(Math.min(1, Math.sqrt(a)))
}

export function cumulativeMiles(coords: Coord[]): number[] {
  const out = [0]
  for (let i = 1; i < coords.length; i++) out.push(out[i - 1] + haversineMi(coords[i - 1], coords[i]))
  return out
}

function interpolate(a: Coord, b: Coord, t: number): Coord {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

/** Coordinates of the line between distances `from` and `to` (same units as `cum`). */
export function sliceLine(coords: Coord[], cum: number[], from: number, to: number): Coord[] {
  const at = (d: number): Coord => {
    if (d <= 0) return coords[0]
    const last = cum.length - 1
    if (d >= cum[last]) return coords[last]
    let i = 1
    while (cum[i] < d) i++
    const span = cum[i] - cum[i - 1]
    return interpolate(coords[i - 1], coords[i], span === 0 ? 0 : (d - cum[i - 1]) / span)
  }
  const out: Coord[] = [at(from)]
  for (let i = 0; i < coords.length; i++) if (cum[i] > from && cum[i] < to) out.push(coords[i])
  out.push(at(to))
  return out
}

const worse = (a: Checkpoint, b: Checkpoint): RiskLevel => (a.risk.score >= b.risk.score ? a.risk.level : b.risk.level)

export interface RiskSegment {
  type: 'Feature'
  properties: { level: RiskLevel; from_mile: number; to_mile: number }
  geometry: { type: 'LineString'; coordinates: Coord[] }
}

export function riskSegments(route: Route): RiskSegment[] {
  const coords = route.geometry.coordinates
  const cps = route.checkpoints
  if (coords.length < 2 || cps.length < 2) return []
  const cum = cumulativeMiles(coords)
  const lineMi = cum[cum.length - 1]
  const routeMi = cps[cps.length - 1].mile || lineMi
  // Backend miles and our haversine length differ slightly; scale so the ends line up.
  const scale = routeMi > 0 ? lineMi / routeMi : 1
  const segs: RiskSegment[] = []
  for (let i = 0; i < cps.length - 1; i++) {
    const a = cps[i]
    const b = cps[i + 1]
    segs.push({
      type: 'Feature',
      properties: { level: worse(a, b), from_mile: a.mile, to_mile: b.mile },
      geometry: { type: 'LineString', coordinates: sliceLine(coords, cum, a.mile * scale, b.mile * scale) },
    })
  }
  return segs
}
