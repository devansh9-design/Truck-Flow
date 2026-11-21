// Typed client for the public Django API. Full analyze/heatmap types land in Chunks 3–4.

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> }
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, init)
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server.')
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const err = (body as ApiErrorBody | null)?.error
    throw new ApiError(res.status, err?.code ?? 'UNKNOWN', err?.message ?? `HTTP ${res.status}`)
  }
  return body as T
}

export interface Health {
  status: 'ok'
  risk_engine: 'ok' | 'down'
  time: string
}

export const getHealth = () => getJson<Health>('/api/health')
