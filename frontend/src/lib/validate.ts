// Client-side checks mirroring the server's validation (the server stays authoritative).
import { zonedInputToIso } from './format'

export interface FieldErrors {
  origin?: string
  destination?: string
  departure_time?: string
  load_weight_lb?: string
}

const PAST_TOLERANCE_MS = 60 * 60 * 1000

export function validateTrip(
  v: { origin: string; destination: string; departure: string; timeZone: string; load: string },
  now: Date = new Date(),
): FieldErrors {
  const e: FieldErrors = {}
  const o = v.origin.trim()
  const d = v.destination.trim()
  if (o.length < 2) e.origin = 'Enter an origin (at least 2 characters).'
  if (d.length < 2) e.destination = 'Enter a destination (at least 2 characters).'
  if (!e.origin && !e.destination && o.toLowerCase() === d.toLowerCase())
    e.destination = 'Destination must differ from the origin.'
  let t = Number.NaN
  try {
    t = new Date(zonedInputToIso(v.departure, v.timeZone)).getTime()
  } catch {
    // left as NaN: reported below
  }
  if (Number.isNaN(t)) e.departure_time = 'Choose a departure date and time.'
  else if (t < now.getTime() - PAST_TOLERANCE_MS) e.departure_time = 'Departure cannot be more than 1 hour in the past.'
  const load = Number(v.load)
  if (!v.load || !Number.isFinite(load) || load < 1 || load > 100_000)
    e.load_weight_lb = 'Load weight must be between 1 and 100,000 lb.'
  return e
}
