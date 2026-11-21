// Wire types for the public Django API (docs/API contracts.md, A1–A5).
// All values are imperial (mi, mph, in/hr, lb); all times are UTC ISO 8601.

export const RISK_LEVELS = ['LOW', 'MODERATE', 'HIGH', 'SEVERE', 'NO_TRAVEL'] as const
export type RiskLevel = (typeof RISK_LEVELS)[number]

export type Interval = 10 | 25 | 50
export const INTERVALS: readonly Interval[] = [10, 25, 50]

export interface Place {
  label: string
  lat: number
  lon: number
}

export interface Weather {
  wind_mph: number
  rain_in_hr: number
  snow_in_hr: number
}

export interface RiskFactors {
  wind: RiskLevel
  rain: RiskLevel
  snow: RiskLevel
  load_override: 'SEVERE' | 'NO_TRAVEL' | null
}

export interface Risk {
  level: RiskLevel
  score: number
  factors: RiskFactors
  reason: string
}

export interface Checkpoint {
  id: string
  index: number
  mile: number
  lat: number
  lon: number
  eta: string
  forecast_hour: string
  weather: Weather
  risk: Risk
}

export interface RouteSummary {
  miles_by_level: Record<RiskLevel, number>
  severe_mi: number
  high_mi: number
  no_travel_mi: number
  has_no_travel: boolean
  avg_risk: number
  max_level: RiskLevel
}

export interface Route {
  id: string
  rank: number
  recommended: boolean
  label: string
  distance_mi: number
  duration_s: number
  arrival_time: string
  geometry: { type: 'LineString'; coordinates: [number, number][] }
  checkpoints: Checkpoint[]
  summary: RouteSummary
  warnings: string[]
}

export type DecidedBy = 'no_travel_mi' | 'severe_mi' | 'high_mi' | 'avg_risk' | 'duration_s' | 'tie' | 'only_route'

export interface AnalyzeRequest {
  origin: string | Place
  destination: string | Place
  departure_time: string
  load_weight_lb: number
  interval_mi: Interval
}

export interface AnalyzeResponse {
  trip: {
    origin: Place
    destination: Place
    departure_time: string
    load_weight_lb: number
    interval_mi: Interval
  }
  routes: Route[]
  recommendation: { route_id: string; decided_by: DecidedBy; reason: string }
  corridor: { bbox: [number, number, number, number] }
  notes: string[]
}

// A4 (CORE-6): 49 hourly frames per variable; each frame is rows x cols values,
// row-major from the south-west cell. null = no usable forecast for that cell/hour.
export type HeatmapVariable = 'risk' | 'wind_mph' | 'rain_in_hr' | 'snow_in_hr'

export interface HeatmapResponse {
  grid: { rows: number; cols: number; lats: number[]; lons: number[] }
  times: string[]
  hours: number
  variables: Record<HeatmapVariable, (number | null)[][]>
  source: string
  generated_at: string
}

export interface Health {
  status: 'ok'
  risk_engine: 'ok' | 'down'
  time: string
}

// A5 (non-core, informational): NWS active alerts near the routes. Never affects risk or ranking.
export type AlertSeverity = 'Extreme' | 'Severe' | 'Moderate' | 'Minor' | 'Unknown'

export interface WeatherAlert {
  id: string
  event: string
  severity: AlertSeverity
  headline: string | null
  areas: string
  onset: string | null
  /** null: NWS gives no end time ("until further notice"). */
  ends: string | null
  /** Index into the request's `points`: where the alert was found. */
  point_index: number
}

export interface AlertsResponse {
  alerts: WeatherAlert[]
  coverage: 'US' | 'unsupported_region'
}

// A6-A9: accounts (optional sign-in), profile country, saved trips on the server.
export interface User {
  id: number
  email: string
  name: string
  /** ISO 3166-1 alpha-2 */
  country: string
  country_name: string
  continent: string
  is_staff: boolean
  date_joined: string
}

export interface Session {
  token: string
  expires_at: string
  user: User
}

export interface Country {
  code: string
  name: string
  continent: string
}

export interface CountriesResponse {
  continents: string[]
  countries: Country[]
}
