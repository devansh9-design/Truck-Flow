import { useState, type FormEvent } from 'react'
import { INTERVALS, type AnalyzeRequest, type Interval, type Place } from '../api/types'
import { EXAMPLE } from '../lib/example'
import { browserTimeZone, nextHourInput, TRIP_TIME_ZONES, zonedInputToIso } from '../lib/format'
import { validateTrip, type FieldErrors } from '../lib/validate'
import { loadInputText, loadInputToLb, LOAD_MAX_KG, LOAD_MAX_LB, miToKm, type LoadInput } from '../lib/units'
import { useAuth } from '../store/auth'
import { useUi, useUnitFormat } from '../store/ui'
import { PlaceInput } from './PlaceInput'

export interface TripFormValues {
  origin: string
  destination: string
  /** Exact places (e.g. a reopened saved trip): sent as coordinates, not re-geocoded. */
  originPlace?: Place | null
  destinationPlace?: Place | null
  /** datetime-local value, read in the trip time zone */
  departure: string
  /** pounds */
  load: string
  interval: Interval
}

interface Props {
  /** Prefill (e.g. a reopened saved trip); remount with a new `key` to apply. */
  initial?: TripFormValues
  busy: boolean
  serverField?: { field: string; message: string } | null
  onSubmit: (req: AnalyzeRequest) => void
}

function zoneOptions(): { id: string; label: string }[] {
  const own = browserTimeZone()
  if (TRIP_TIME_ZONES.some((z) => z.id === own)) return TRIP_TIME_ZONES
  return [{ id: own, label: `${own} (this device)` }, ...TRIP_TIME_ZONES]
}

const baseZones = zoneOptions()

const inputCls =
  'w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm ' +
  'focus:border-sky-600 focus:outline-none focus:ring-2 focus:ring-sky-600/30 aria-[invalid=true]:border-red-500'

function FieldError({ id, msg }: { id: string; msg?: string }) {
  if (!msg) return null
  return (
    <p id={id} className="mt-1 text-xs text-red-700">
      {msg}
    </p>
  )
}

export function TripForm({ initial, busy, serverField, onSubmit }: Props) {
  const [origin, setOrigin] = useState(initial?.origin ?? '')
  const [destination, setDestination] = useState(initial?.destination ?? '')
  const [originPlace, setOriginPlace] = useState<Place | null>(initial?.originPlace ?? null)
  const [destinationPlace, setDestinationPlace] = useState<Place | null>(initial?.destinationPlace ?? null)
  // Country filter per field: null follows the signed-in user's country (or "any" for guests).
  const profileCountry = useAuth((s) => s.user?.country ?? '')
  const [originCountry, setOriginCountry] = useState<string | null>(null)
  const [destinationCountry, setDestinationCountry] = useState<string | null>(null)
  const timeZone = useUi((s) => s.timeZone)
  const setTimeZone = useUi((s) => s.setTimeZone)
  const [departure, setDeparture] = useState(() => initial?.departure ?? nextHourInput(timeZone))
  // Kept in the units it was typed in; shown converted, so toggling never alters the weight.
  const [loadInput, setLoadInput] = useState<LoadInput>({ text: initial?.load ?? '42000', units: 'imperial' })
  const [interval, setIntervalMi] = useState<Interval>(initial?.interval ?? 25)
  // A reopened trip may use a zone that is not in the list on this device.
  const zones = baseZones.some((z) => z.id === timeZone) ? baseZones : [{ id: timeZone, label: timeZone }, ...baseZones]
  const [errors, setErrors] = useState<FieldErrors>({})
  const u = useUnitFormat()
  const metric = u.units === 'metric'
  const load = loadInputText(loadInput, u.units)

  const errorFor = (k: keyof FieldErrors) => errors[k] ?? (serverField?.field === k ? serverField.message : undefined)

  function submit(ev: FormEvent) {
    ev.preventDefault()
    const e = validateTrip({ origin, destination, departure, timeZone, load, units: u.units })
    setErrors(e)
    if (Object.keys(e).length) return
    onSubmit({
      origin: originPlace ?? origin.trim(),
      destination: destinationPlace ?? destination.trim(),
      departure_time: zonedInputToIso(departure, timeZone),
      load_weight_lb: loadInputToLb(loadInput),
      interval_mi: interval,
    })
  }

  /** One click to a result: fills the form with a sample trip and runs it. */
  function runExample() {
    const dep = nextHourInput(timeZone)
    setOrigin(EXAMPLE.origin)
    setDestination(EXAMPLE.destination)
    setOriginPlace(null)
    setDestinationPlace(null)
    setDeparture(dep)
    setLoadInput({ text: String(EXAMPLE.loadLb), units: 'imperial' })
    setIntervalMi(EXAMPLE.interval)
    setErrors({})
    onSubmit({
      origin: EXAMPLE.origin,
      destination: EXAMPLE.destination,
      departure_time: zonedInputToIso(dep, timeZone),
      load_weight_lb: EXAMPLE.loadLb,
      interval_mi: EXAMPLE.interval,
    })
  }

  const swap = () => {
    setOrigin(destination)
    setDestination(origin)
    setOriginPlace(destinationPlace)
    setDestinationPlace(originPlace)
    setOriginCountry(destinationCountry)
    setDestinationCountry(originCountry)
  }

  return (
    <form onSubmit={submit} noValidate aria-label="Trip details" className="space-y-3">
      <div className="relative space-y-3">
        <PlaceInput
          id="origin"
          label="Origin"
          placeholder="Start typing, e.g. Denver"
          text={origin}
          place={originPlace}
          onText={setOrigin}
          onPlace={setOriginPlace}
          country={originCountry ?? profileCountry}
          onCountry={setOriginCountry}
          error={errorFor('origin')}
        />
        <PlaceInput
          id="destination"
          label="Destination"
          placeholder="Start typing, e.g. Salt Lake City"
          text={destination}
          place={destinationPlace}
          onText={setDestination}
          onPlace={setDestinationPlace}
          country={destinationCountry ?? profileCountry}
          onCountry={setDestinationCountry}
          near={originPlace}
          error={errorFor('destination')}
          action={
            <button
              type="button"
              onClick={swap}
              className="rounded px-1.5 text-xs text-sky-700 hover:bg-sky-50 focus:outline-none focus:ring-2 focus:ring-sky-600/40"
              aria-label="Swap origin and destination"
            >
              ⇅ Swap
            </button>
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-3 min-[400px]:grid-cols-2">
        <div>
          <label htmlFor="departure" className="mb-1 block text-xs font-medium text-slate-700">
            Departure
          </label>
          <input
            id="departure"
            type="datetime-local"
            className={inputCls}
            value={departure}
            onChange={(e) => setDeparture(e.target.value)}
            aria-invalid={!!errorFor('departure_time')}
            aria-describedby={errorFor('departure_time') ? 'departure-err' : undefined}
          />
        </div>
        <div>
          <label htmlFor="tz" className="mb-1 block text-xs font-medium text-slate-700">
            Time zone
          </label>
          <select id="tz" className={inputCls} value={timeZone} onChange={(e) => setTimeZone(e.target.value)}>
            {zones.map((z) => (
              <option key={z.id} value={z.id}>
                {z.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <FieldError id="departure-err" msg={errorFor('departure_time')} />

      <div>
        <label htmlFor="load" className="mb-1 block text-xs font-medium text-slate-700">
          Load weight ({metric ? 'kg' : 'lb'})
        </label>
        <input
          id="load"
          type="number"
          inputMode="numeric"
          min={1}
          max={metric ? LOAD_MAX_KG : LOAD_MAX_LB}
          step={metric ? 50 : 100}
          className={inputCls}
          value={load}
          onChange={(e) => setLoadInput({ text: e.target.value, units: u.units })}
          aria-invalid={!!errorFor('load_weight_lb')}
          aria-describedby={errorFor('load_weight_lb') ? 'load-err' : undefined}
        />
        <FieldError id="load-err" msg={errorFor('load_weight_lb')} />
      </div>

      <fieldset>
        <legend className="mb-1 text-xs font-medium text-slate-700">Checkpoint every</legend>
        <div className="grid grid-cols-3 gap-1 rounded-md bg-slate-100 p-1">
          {INTERVALS.map((mi) => (
            <label
              key={mi}
              className={`cursor-pointer rounded px-2 py-1.5 text-center text-sm transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-sky-600/50 ${
                interval === mi
                  ? 'bg-white font-semibold text-slate-900 shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <input
                type="radio"
                name="interval"
                value={mi}
                checked={interval === mi}
                onChange={() => setIntervalMi(mi)}
                className="sr-only"
              />
              {metric ? `${Math.round(miToKm(mi))} km` : `${mi} mi`}
            </label>
          ))}
        </div>
      </fieldset>

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-md bg-sky-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-sky-800 focus:outline-none focus:ring-2 focus:ring-sky-600/50 focus:ring-offset-1 disabled:cursor-wait disabled:bg-slate-400"
      >
        {busy ? 'Analyzing routes…' : 'Compare routes'}
      </button>
      <button
        type="button"
        onClick={runExample}
        disabled={busy}
        className="w-full rounded-md border border-sky-700 bg-white px-4 py-2 text-sm font-medium text-sky-800 transition-colors hover:bg-sky-50 focus:outline-none focus:ring-2 focus:ring-sky-600/50 focus:ring-offset-1 disabled:cursor-wait disabled:border-slate-300 disabled:text-slate-400"
      >
        Try an example: Denver → Salt Lake City
      </button>
    </form>
  )
}
