// Typed client for the public Django API (the only API the browser talks to).
import { useAuth } from '../store/auth'
import type { SavedTrip } from '../lib/savedTrips'
import type {
  AlertsResponse,
  AnalyzeRequest,
  AnalyzeResponse,
  CountriesResponse,
  Health,
  HeatmapResponse,
  Place,
  PlaceSuggestion,
  Session,
  User,
} from './types'

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly field: string | null
  constructor(status: number, code: string, message: string, field: string | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.field = field
  }
}

export async function getJson<T>(path: string, init?: RequestInit, signedIn = true): Promise<T> {
  const token = signedIn ? useAuth.getState().token : null
  const headers = new Headers(init?.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server. Check your connection and try again.')
  }
  const body = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) {
    const err = (body as ApiErrorBody | null)?.error
    // An expired or revoked session: sign out locally and, for guest-allowed calls, retry as a guest.
    if (token && err?.code === 'TOKEN_INVALID') {
      useAuth.getState().clear()
      return getJson<T>(path, init, false)
    }
    const field = typeof err?.details?.field === 'string' ? err.details.field : null
    throw new ApiError(res.status, err?.code ?? 'UNKNOWN', err?.message ?? `Server error (HTTP ${res.status}).`, field)
  }
  return body as T
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const getHealth = () => getJson<Health>('/api/health')

export function getHeatmap(bbox: number[], start: string, loadLb: number) {
  const q = new URLSearchParams({ bbox: bbox.join(','), start, load_weight_lb: String(loadLb) })
  return getJson<HeatmapResponse>(`/api/heatmap?${q}`)
}

export const analyzeTrip = (req: AnalyzeRequest) =>
  getJson<AnalyzeResponse>('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })

export const getAlerts = (points: { lat: number; lon: number }[]) =>
  getJson<AlertsResponse>('/api/alerts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ points }),
  })

// --- Accounts (A6-A9) ---------------------------------------------------------------------

export const getCountries = () => getJson<CountriesResponse>('/api/countries', undefined, false)

export const signUp = (b: { name: string; email: string; password: string; country: string }) =>
  getJson<Session>('/api/auth/signup', json('POST', b), false)

export const signIn = (b: { email: string; password: string }) =>
  getJson<Session>('/api/auth/login', json('POST', b), false)

export const signOut = () => getJson<null>('/api/auth/logout', json('POST'))

export const getMe = () => getJson<{ user: User }>('/api/auth/me')

export const updateMe = (b: { name?: string; country?: string }) =>
  getJson<{ user: User }>('/api/auth/me', json('PATCH', b))

export const deleteMe = (password: string) => getJson<null>('/api/auth/me', json('DELETE', { password }))

export const changePassword = (b: { current_password: string; new_password: string }) =>
  getJson<null>('/api/auth/password', json('POST', b))

type TripInput = Omit<SavedTrip, 'id' | 'saved_at'>
const tripInput = ({ id: _id, saved_at: _at, ...rest }: SavedTrip): TripInput => rest

export const listTrips = () => getJson<{ trips: SavedTrip[] }>('/api/trips')

export const createTrip = (t: SavedTrip) => getJson<{ trip: SavedTrip }>('/api/trips', json('POST', tripInput(t)))

export const removeServerTrip = (id: string) => getJson<null>(`/api/trips/${encodeURIComponent(id)}`, json('DELETE'))

export const importTrips = (trips: SavedTrip[]) =>
  getJson<{ trips: SavedTrip[] }>('/api/trips/import', json('POST', { trips: trips.map(tripInput) }))

// --- Place suggestions (A10) --------------------------------------------------------------

export function suggestPlaces(q: string, country: string, near: string) {
  const p = new URLSearchParams({ q })
  if (country) p.set('country', country)
  if (near) p.set('near', near)
  return getJson<{ suggestions: PlaceSuggestion[] }>(`/api/places/suggest?${p}`)
}

export const lookupPlace = (id: string) => getJson<Place>(`/api/places/lookup?${new URLSearchParams({ id })}`)
