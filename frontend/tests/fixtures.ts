// Small synthetic /api/analyze response (shape per docs/API contracts.md A3).
import type { AnalyzeResponse, Checkpoint, RiskLevel, Route } from '../src/api/types'

const SCORE: Record<RiskLevel, number> = { LOW: 1, MODERATE: 2, HIGH: 3, SEVERE: 4, NO_TRAVEL: 5 }

function cp(routeId: string, index: number, mile: number, lon: number, level: RiskLevel): Checkpoint {
  const eta = new Date(Date.UTC(2026, 10, 21, 13 + index)).toISOString().replace('.000', '')
  return {
    id: `${routeId}-c${index}`,
    index,
    mile,
    lat: 40,
    lon,
    eta,
    forecast_hour: eta,
    weather: { wind_mph: 10 + index, rain_in_hr: 0, snow_in_hr: level === 'SEVERE' ? 3 : 0 },
    risk: {
      level,
      score: SCORE[level],
      factors: { wind: 'LOW', rain: 'LOW', snow: level, load_override: null },
      reason: `Snow ${level.toLowerCase()} at this hour.`,
    },
  }
}

function route(id: string, rank: number, label: string, levels: RiskLevel[], extra: Partial<Route> = {}): Route {
  const cps = levels.map((l, i) => cp(id, i, i * 25, -105 + i * 0.5, l))
  const total = (levels.length - 1) * 25
  return {
    id,
    rank,
    recommended: rank === 1,
    label,
    distance_mi: total,
    duration_s: 3600 * (levels.length - 1),
    arrival_time: cps[cps.length - 1].eta,
    geometry: { type: 'LineString', coordinates: cps.map((c) => [c.lon, c.lat]) },
    checkpoints: cps,
    summary: {
      miles_by_level: { LOW: total, MODERATE: 0, HIGH: 0, SEVERE: 0, NO_TRAVEL: 0 },
      severe_mi: 0,
      high_mi: 0,
      no_travel_mi: 0,
      has_no_travel: false,
      avg_risk: 1,
      max_level: levels.reduce((a, b) => (SCORE[b] > SCORE[a] ? b : a)),
    },
    warnings: [],
    ...extra,
  }
}

export const ANALYZE: AnalyzeResponse = {
  trip: {
    origin: { label: 'Denver, CO, United States', lat: 39.74, lon: -104.99 },
    destination: { label: 'Salt Lake City, UT, United States', lat: 40.76, lon: -111.89 },
    departure_time: '2026-11-21T13:00:00Z',
    load_weight_lb: 42000,
    interval_mi: 25,
  },
  routes: [
    route('r1', 1, 'Route B', ['LOW', 'LOW', 'MODERATE', 'LOW']),
    route('r0', 2, 'Route A', ['LOW', 'HIGH', 'SEVERE', 'LOW']),
    route('r2', 3, 'Route C', ['LOW', 'NO_TRAVEL', 'LOW'], {
      warnings: ['NO_TRAVEL_CONDITIONS'],
    }),
  ],
  recommendation: { route_id: 'r1', decided_by: 'severe_mi', reason: 'Fewest Severe miles (0.0 vs 25.0).' },
  corridor: { bbox: [-106, 39, -103, 41] },
  notes: ['Router returned 3 routes.'],
}
