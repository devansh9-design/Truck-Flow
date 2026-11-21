// Driving mode UI (phase 1, D17): start button, live status bar, risk warning dialog.
import { useEffect, useRef, useState } from 'react'
import { keepRoute, recheck, switchRoute } from '../api/driving'
import type { AnalyzeResponse, Route } from '../api/types'
import { RECHECK_EVERY_MS } from '../lib/driving'
import { useDriving } from '../store/driving'

export function StartDrivingButton({ data, route }: { data: AnalyzeResponse; route: Route }) {
  const active = useDriving((s) => s.active)
  const start = useDriving((s) => s.start)
  const supported = typeof navigator !== 'undefined' && !!navigator.geolocation
  if (active) return null
  return (
    <section aria-label="Driving mode" className="rounded-lg border border-slate-200 bg-white p-3 text-xs">
      <button
        type="button"
        disabled={!supported}
        onClick={() =>
          start(
            {
              destination: data.trip.destination,
              load_weight_lb: data.trip.load_weight_lb,
              interval_mi: data.trip.interval_mi,
            },
            route.label,
            route.geometry.coordinates,
            route.summary,
          )
        }
        className="w-full rounded-md bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/50 disabled:bg-slate-400"
      >
        ▶ Start trip on {route.label}
      </button>
      <p className="mt-1.5 text-slate-500">
        {supported
          ? 'Driving mode follows your location and re-checks the weather ahead every 15 minutes. If another route becomes safer, it tells you. Keep the app open on screen.'
          : 'This device cannot share its location, so driving mode is not available.'}
      </p>
    </section>
  )
}

function useNow(everyMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), everyMs)
    return () => window.clearInterval(t)
  }, [everyMs])
  return now
}

const btn =
  'min-h-9 rounded-md border px-3 py-1.5 text-xs font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50 disabled:opacity-50'

/** Live status while driving: route, last/next check, GPS and errors, controls. */
export function DrivingBar({ onEnd }: { onEnd: () => void }) {
  const st = useDriving()
  // The clock ticks every 15 s; never let it lag behind the last check.
  const now = Math.max(useNow(15_000), st.lastCheck.at)
  if (!st.active) return null
  const ago = st.lastCheck.pos ? Math.max(0, Math.round((now - st.lastCheck.at) / 60_000)) : null
  const next = st.lastCheck.pos ? Math.max(0, Math.ceil((st.lastCheck.at + RECHECK_EVERY_MS - now) / 60_000)) : null
  const line =
    st.status === 'arrived'
      ? `Arrived near ${st.trip?.destination.label ?? 'your destination'}.`
      : st.status === 'checking'
        ? 'Checking the weather on the road ahead…'
        : st.status === 'locating' || !st.position
          ? 'Getting your location…'
          : ago === null
            ? 'Location found. Checking the road ahead…'
            : `Last check ${ago === 0 ? 'just now' : `${ago} min ago`} · next within ${next} min`

  return (
    <section
      aria-label="Driving mode status"
      data-testid="driving-bar"
      className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-xs text-emerald-950"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold">
          <span aria-hidden="true">🚚</span> Driving · {st.routeLabel}
        </p>
        <span
          aria-hidden="true"
          className={`h-2 w-2 rounded-full ${st.gpsError ? 'bg-amber-500' : st.status === 'arrived' ? 'bg-slate-400' : 'bg-emerald-600 animate-pulse'}`}
        />
      </div>
      <p role="status" className="mt-0.5">
        {line}
      </p>
      {st.gpsError && <p className="mt-1 font-medium text-amber-900">{st.gpsError}</p>}
      {st.checkError && <p className="mt-1 text-red-800">Re-check failed: {st.checkError}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void recheck()}
          disabled={!st.position || st.status !== 'monitoring'}
          className={`${btn} border-emerald-400 bg-white text-emerald-900 hover:bg-emerald-100`}
        >
          Check now
        </button>
        <button
          type="button"
          aria-pressed={!st.muted}
          onClick={() => st.set({ muted: !st.muted })}
          className={`${btn} border-emerald-400 bg-white text-emerald-900 hover:bg-emerald-100`}
        >
          {st.muted ? '🔇 Voice off' : '🔊 Voice on'}
        </button>
        <button
          type="button"
          onClick={onEnd}
          className={`${btn} border-slate-300 bg-white text-slate-800 hover:bg-slate-100`}
        >
          {st.status === 'arrived' ? 'Close' : 'End trip'}
        </button>
      </div>
      <p className="mt-2 text-[11px] text-emerald-900/80">
        Your location is only used to re-check the route; it is not saved.
      </p>
    </section>
  )
}

/** Big, simple warning: two large buttons, readable at a glance. */
export function DrivingWarningDialog() {
  const warning = useDriving((s) => s.warning)
  const primary = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (warning) primary.current?.focus()
  }, [warning])
  if (!warning) return null
  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-slate-900/40 p-3 pt-6 md:items-center">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="drive-warn-title"
        aria-describedby="drive-warn-text"
        data-testid="driving-warning"
        className="w-[min(480px,100%)] rounded-2xl border-4 border-red-600 bg-white p-5 shadow-2xl"
      >
        <p className="text-xs font-bold tracking-wide text-red-700 uppercase">
          <span aria-hidden="true">▲</span> Weather warning
        </p>
        <h2 id="drive-warn-title" className="mt-1 text-xl font-bold text-slate-900">
          {warning.title}
        </h2>
        <p id="drive-warn-text" className="mt-2 text-base text-slate-800">
          {warning.message}
        </p>
        <p className="mt-2 text-sm font-semibold text-slate-700">Pull over safely before using the screen.</p>
        <div className="mt-4 grid gap-2">
          {warning.kind === 'switch' ? (
            <>
              <button
                ref={primary}
                type="button"
                onClick={switchRoute}
                className="min-h-14 rounded-xl bg-emerald-700 px-4 text-lg font-bold text-white hover:bg-emerald-800 focus:outline-none focus-visible:ring-4 focus-visible:ring-emerald-500/50"
              >
                Switch to {warning.suggestLabel}
              </button>
              <button
                type="button"
                onClick={keepRoute}
                className="min-h-14 rounded-xl border-2 border-slate-300 bg-white px-4 text-lg font-semibold text-slate-800 hover:bg-slate-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-slate-400/50"
              >
                Keep my route
              </button>
            </>
          ) : (
            <button
              ref={primary}
              type="button"
              onClick={keepRoute}
              className="min-h-14 rounded-xl bg-slate-900 px-4 text-lg font-bold text-white hover:bg-slate-800 focus:outline-none focus-visible:ring-4 focus-visible:ring-slate-500/50"
            >
              OK
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
