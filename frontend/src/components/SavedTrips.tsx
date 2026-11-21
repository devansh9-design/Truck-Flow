import { useState } from 'react'
import { useTrips } from '../api/account'
import type { AnalyzeResponse } from '../api/types'
import { formatTime } from '../lib/format'
import { riskStyle } from '../lib/risk'
import type { SavedTrip } from '../lib/savedTrips'
import { useUi, useUnitFormat } from '../store/ui'

/** P3-4: save the analysed trip's inputs (not its results: reopening re-runs the analysis). */
export function SaveTripButton({ data }: { data: AnalyzeResponse }) {
  const source = useTrips()
  const timeZone = useUi((s) => s.timeZone)
  const [state, setState] = useState<'idle' | 'saving' | 'failed'>('idle')
  const saved = source.isSaved(data, timeZone)
  const failText = source.signedIn
    ? "Couldn't save to your account. Try again."
    : 'This browser blocked storage; the trip is kept for this visit only.'
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        disabled={saved || state === 'saving'}
        onClick={async () => {
          setState('saving')
          setState((await source.save(data, timeZone)) ? 'idle' : 'failed')
        }}
        className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-800 shadow-sm hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50 disabled:cursor-default disabled:border-emerald-300 disabled:bg-emerald-50 disabled:text-emerald-800"
      >
        {saved ? '✓ Trip saved' : state === 'saving' ? 'Saving…' : '☆ Save trip'}
      </button>
      {!source.signedIn && !saved && (
        <span className="text-[11px] text-slate-500">
          Saved in this browser · sign in to keep trips on every device
        </span>
      )}
      {state === 'failed' && (
        <span role="alert" className="text-[11px] text-amber-800">
          {failText}
        </span>
      )}
    </div>
  )
}

interface ListProps {
  onReopen: (trip: SavedTrip) => void
  busy: boolean
}

/** Saved trips, newest first. Reopen re-runs the analysis so weather is always fresh. */
export function SavedTripsList({ onReopen, busy }: ListProps) {
  const { trips, remove, signedIn } = useTrips()
  const u = useUnitFormat()
  if (trips.length === 0) return null
  return (
    <details className="group rounded-lg border border-slate-200 bg-white text-xs shadow-sm" data-testid="saved-trips">
      <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 font-semibold text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50">
        <span>
          {signedIn ? 'Your saved trips' : 'Saved trips'} ({trips.length})
        </span>
        <span aria-hidden="true" className="text-slate-400 transition-transform group-open:rotate-180">
          ▾
        </span>
      </summary>
      <ul className="divide-y divide-slate-100 border-t border-slate-100">
        {trips.map((t) => {
          const lvl = riskStyle(t.summary.max_level)
          const name = `${t.origin.label} to ${t.destination.label}`
          return (
            <li key={t.id} className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-slate-900" title={name}>
                  {t.origin.label} <span aria-hidden="true">→</span>
                  <span className="sr-only">to</span> {t.destination.label}
                </p>
                <p className="truncate text-slate-500">
                  {formatTime(t.departure_time, t.time_zone)} · {u.weight(t.load_weight_lb)}
                </p>
                <p className="truncate text-[11px] text-slate-500">
                  When saved: {t.summary.recommended_label}, {u.distance(t.summary.distance_mi, 0)}, worst {lvl.label}
                </p>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => onReopen(t)}
                aria-label={`Reopen ${name}`}
                className="min-h-8 rounded-md bg-sky-700 px-2.5 py-1 font-semibold text-white hover:bg-sky-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50 disabled:bg-slate-400"
              >
                Reopen
              </button>
              <button
                type="button"
                onClick={() => remove(t.id)}
                aria-label={`Delete saved trip ${name}`}
                className="min-h-8 rounded-md px-2 py-1 text-slate-500 hover:bg-red-50 hover:text-red-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
              >
                <span aria-hidden="true">🗑</span>
              </button>
            </li>
          )
        })}
      </ul>
    </details>
  )
}
