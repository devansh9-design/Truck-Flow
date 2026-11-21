// Typed client for the public Django API (the only API the browser talks to).
import type { AnalyzeRequest, AnalyzeResponse, Health } from './types'

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

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, init)
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server. Check your connection and try again.')
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const err = (body as ApiErrorBody | null)?.error
    const field = typeof err?.details?.field === 'string' ? err.details.field : null
    throw new ApiError(res.status, err?.code ?? 'UNKNOWN', err?.message ?? `Server error (HTTP ${res.status}).`, field)
  }
  return body as T
}

export const getHealth = () => getJson<Health>('/api/health')

export const analyzeTrip = (req: AnalyzeRequest) =>
  getJson<AnalyzeResponse>('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
