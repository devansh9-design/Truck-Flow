import { useState, type FormEvent } from 'react'
import { INTERVALS, type AnalyzeRequest, type Interval } from '../api/types'
import { browserTimeZone, nextHourInput, TRIP_TIME_ZONES, zonedInputToIso } from '../lib/format'
import { validateTrip, type FieldErrors } from '../lib/validate'
import { useUi, useUnitFormat } from '../store/ui'

export interface TripFormValues {
  origin: string
  destination: string
  /** datetime-local value, read in the trip time zone */
  departure: string
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
  const timeZone = useUi((s) => s.timeZone)
  const setTimeZone = useUi((s) => s.setTimeZone)
  const [departure, setDeparture] = useState(() => initial?.departure ?? nextHourInput(timeZone))
  const [load, setLoad] = useState(initial?.load ?? '42000')
  const [interval, setIntervalMi] = useState<Interval>(initial?.interval ?? 25)
  // A reopened trip may use a zone that is not in the list on this device.
  const zones = baseZones.some((z) => z.id === timeZone) ? baseZones : [{ id: timeZone, label: timeZone }, ...baseZones]
  const [errors, setErrors] = useState<FieldErrors>({})
  const u = useUnitFormat()

  const errorFor = (k: keyof FieldErrors) => errors[k] ?? (serverField?.field === k ? serverField.message : undefined)

  function submit(ev: FormEvent) {
    ev.preventDefault()
    const e = validateTrip({ origin, destination, departure, timeZone, load })
    setErrors(e)
    if (Object.keys(e).length) return
    onSubmit({
      origin: origin.trim(),
      destination: destination.trim(),
      departure_time: zonedInputToIso(departure, timeZone),
      load_weight_lb: Number(load),
      interval_mi: interval,
    })
  }

  const swap = () => {
    setOrigin(destination)
    setDestination(origin)
  }

  return (
    <form onSubmit={submit} noValidate aria-label="Trip details" className="space-y-3">
      <div className="relative space-y-3">
        <div>
          <label htmlFor="origin" className="mb-1 block text-xs font-medium text-slate-700">
            Origin
          </label>
          <input
            id="origin"
            className={inputCls}
            placeholder="e.g. Denver, CO"
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            aria-invalid={!!errorFor('origin')}
            aria-describedby={errorFor('origin') ? 'origin-err' : undefined}
            autoComplete="off"
          />
          <FieldError id="origin-err" msg={errorFor('origin')} />
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between">
            <label htmlFor="destination" className="block text-xs font-medium text-slate-700">
              Destination
            </label>
            <button
              type="button"
              onClick={swap}
              className="rounded px-1.5 text-xs text-sky-700 hover:bg-sky-50 focus:outline-none focus:ring-2 focus:ring-sky-600/40"
              aria-label="Swap origin and destination"
            >
              ⇅ Swap
            </button>
          </div>
          <input
            id="destination"
            className={inputCls}
            placeholder="e.g. Salt Lake City, UT"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            aria-invalid={!!errorFor('destination')}
            aria-describedby={errorFor('destination') ? 'destination-err' : undefined}
            autoComplete="off"
          />
          <FieldError id="destination-err" msg={errorFor('destination')} />
        </div>
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
          Load weight (lb)
        </label>
        <input
          id="load"
          type="number"
          inputMode="numeric"
          min={1}
          max={100000}
          step={100}
          className={inputCls}
          value={load}
          onChange={(e) => setLoad(e.target.value)}
          aria-invalid={!!errorFor('load_weight_lb')}
          aria-describedby={errorFor('load_weight_lb') ? 'load-err' : undefined}
        />
        {u.units === 'metric' && Number(load) > 0 && (
          <p className="mt-1 text-[11px] text-slate-500">≈ {u.weight(Number(load))}</p>
        )}
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
              {mi} mi
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
    </form>
  )
}
