import { useEffect, useRef, useState } from 'react'
import { ApiError } from './api/client'
import { useAlerts, useAnalyze, useHeatmap } from './api/hooks'
import type { AnalyzeRequest } from './api/types'
import { useSessionCheck } from './api/account'
import { AccountMenu } from './components/Account'
import { AlertsPanel } from './components/AlertsPanel'
import { MOBILE_QUERY, useBottomSheet, useMediaQuery, type Snap } from './components/BottomSheet'
import { HeatmapPanel } from './components/HeatmapPanel'
import { Results } from './components/Results'
import { StatusPill } from './components/StatusPill'
import { SavedTripsList } from './components/SavedTrips'
import { TripForm, type TripFormValues } from './components/TripForm'
import { isoToZonedInput, nextHourInput, zonedInputToIso } from './lib/format'
import { departureHasPassed, type SavedTrip } from './lib/savedTrips'
import { UnitToggle } from './components/UnitToggle'
import { Legend } from './map/Legend'
import { MapView } from './map/MapView'
import { useUi } from './store/ui'

/** Seconds since `start` (ms), ticking while `start` is set. */
function useElapsed(start: number | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (start === null) return
    const t = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(t)
  }, [start])
  return start === null ? 0 : Math.max(0, Math.floor((now - start) / 1000))
}

export default function App() {
  useSessionCheck()
  const analyze = useAnalyze()
  const reset = useUi((s) => s.reset)
  const setTimeZone = useUi((s) => s.setTimeZone)
  const [form, setForm] = useState<{ key: number; initial?: TripFormValues }>({ key: 0 })
  const [reopenNote, setReopenNote] = useState<string | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const elapsed = useElapsed(analyze.isPending ? startedAt : null)
  const data = analyze.isPending ? undefined : analyze.data
  const heat = useHeatmap(data)
  const alerts = useAlerts(data)
  const selectedRouteId = useUi((s) => s.selectedRouteId)
  const selectedRoute = data?.routes.find((r) => r.id === selectedRouteId)
  const err = analyze.error instanceof ApiError ? analyze.error : null
  const serverField = err?.field ? { field: err.field, message: err.message } : null

  // Outages and timeouts are worth retrying as-is; input problems (4xx) are not.
  const retryable = !!err && (err.status === 0 || err.status >= 500)

  // P3-1: bottom sheet under 768 px. Full for the form, peek while analysing (the map shows
  // progress), half for results; picking something on the map lowers it to peek.
  const isMobile = useMediaQuery(MOBILE_QUERY)
  const [snap, setSnap] = useState<Snap>('full')
  const sheet = useBottomSheet(snap, setSnap)
  const resultsRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!isMobile) return
    return useUi.subscribe((s, prev) => {
      const cp = s.selectedCheckpointId && s.selectedCheckpointId !== prev.selectedCheckpointId
      const al = s.selectedAlertPoint !== null && s.selectedAlertPoint !== prev.selectedAlertPoint
      if (cp || al) setSnap('peek')
    })
  }, [isMobile])
  const heatPanelPx = 176
  const mapBottomInset = isMobile ? sheet.height + (data ? heatPanelPx : 0) : 0

  function submit(req: AnalyzeRequest) {
    setStartedAt(Date.now())
    setSnap('peek')
    analyze.mutate(req, {
      onSuccess: (res) => {
        reset(res.recommendation.route_id)
        setSnap('half')
        // On a phone the form fills the sheet: bring the recommendation into view.
        if (isMobile) requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ block: 'start' }))
      },
      onError: () => setSnap('full'),
    })
  }

  /** P3-4: reopening a saved trip fills the form and re-runs the analysis (fresh weather). */
  function reopen(t: SavedTrip) {
    const passed = departureHasPassed(t.departure_time)
    const departure = passed ? nextHourInput(t.time_zone) : isoToZonedInput(t.departure_time, t.time_zone)
    setTimeZone(t.time_zone)
    setForm((f) => ({
      key: f.key + 1,
      initial: {
        origin: t.origin.label,
        destination: t.destination.label,
        departure,
        load: String(t.load_weight_lb),
        interval: t.interval_mi,
      },
    }))
    setReopenNote(passed ? 'The saved departure time has passed, so this trip was re-run from the next hour.' : null)
    submit({
      origin: t.origin,
      destination: t.destination,
      departure_time: zonedInputToIso(departure, t.time_zone),
      load_weight_lb: t.load_weight_lb,
      interval_mi: t.interval_mi,
    })
  }

  return (
    <div className="relative flex h-dvh overflow-hidden bg-slate-50 text-slate-900">
      <aside
        aria-label="Trip panel"
        data-testid="panel"
        data-snap={isMobile ? snap : undefined}
        style={isMobile ? sheet.style : undefined}
        className={
          isMobile
            ? 'absolute inset-x-0 bottom-0 z-20 flex flex-col overflow-hidden rounded-t-2xl bg-slate-50 shadow-[0_-6px_24px_rgb(15_23_42/0.2)]'
            : 'flex w-[400px] flex-none flex-col border-r border-slate-200 bg-slate-50'
        }
      >
        {isMobile && (
          <button
            {...sheet.handleProps}
            className="flex h-7 w-full shrink-0 cursor-grab touch-none items-center justify-center rounded-t-2xl bg-white focus:outline-none focus-visible:bg-sky-50"
          >
            <span aria-hidden="true" className="h-1.5 w-10 rounded-full bg-slate-300" />
          </button>
        )}
        <header className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 border-b border-slate-200 bg-white px-4 py-2 md:py-3">
          <div>
            <h1 className="text-base font-bold tracking-tight">Truck Weather Router</h1>
            <p className="hidden text-[11px] text-slate-500 sm:block">Three truck routes, weather at every ETA</p>
          </div>
          <div className="flex items-center gap-2">
            <UnitToggle />
            <StatusPill />
            <AccountMenu />
          </div>
        </header>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain p-4">
          <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
            <TripForm
              key={form.key}
              initial={form.initial}
              busy={analyze.isPending}
              serverField={serverField}
              onSubmit={(req) => {
                setReopenNote(null)
                submit(req)
              }}
            />
          </div>

          <SavedTripsList onReopen={reopen} busy={analyze.isPending} />

          {reopenNote && !analyze.isPending && (
            <p role="status" className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
              {reopenNote}
            </p>
          )}

          {analyze.isError && !serverField && (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900">
              <p className="font-semibold">Couldn't analyze this trip</p>
              <p className="mt-0.5 text-xs">{analyze.error.message}</p>
              {retryable && analyze.variables && (
                <button
                  type="button"
                  onClick={() => submit(analyze.variables!)}
                  className="mt-2 rounded-md border border-red-300 bg-white px-3 py-1 text-xs font-semibold text-red-900 hover:bg-red-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
                >
                  Try again
                </button>
              )}
            </div>
          )}

          <div ref={resultsRef} className="scroll-mt-2" />
          {data && !analyze.isPending && (
            <Results
              data={data}
              alerts={
                <AlertsPanel
                  routes={data.routes}
                  points={alerts.points}
                  data={alerts.data}
                  loading={alerts.isPending}
                  error={alerts.isError ? alerts.error.message : null}
                  onRetry={() => alerts.refetch()}
                />
              }
            />
          )}

          {!data && !analyze.isPending && !analyze.isError && (
            <p className="px-1 text-xs text-slate-500">
              Enter a trip to compare three truck routes. Each checkpoint is checked against the forecast for the hour
              the truck is due there, then routes are ranked by No Travel, Severe and High miles, average risk and time.
            </p>
          )}
        </div>
      </aside>

      <main className="relative min-w-0 flex-1" aria-label="Route map">
        <MapView
          data={data}
          heat={heat.data}
          alerts={{ points: alerts.points, data: alerts.data }}
          bottomInset={mapBottomInset}
        />
        <div className="pointer-events-none absolute top-3 left-3">
          <Legend compact={isMobile} />
        </div>
        {data && (
          <div
            className="pointer-events-none absolute left-1/2 z-10 w-[min(540px,calc(100%-16px))] -translate-x-1/2 md:bottom-7"
            style={isMobile ? { bottom: sheet.height + 8 } : undefined}
          >
            <HeatmapPanel
              times={heat.data?.times}
              loading={heat.isPending}
              error={heat.isError ? heat.error.message : null}
              onRetry={() => heat.refetch()}
              route={selectedRoute}
            />
          </div>
        )}
        {analyze.isPending && (
          <div
            role="status"
            aria-live="polite"
            className="absolute inset-0 flex items-center justify-center bg-white/40 backdrop-blur-[1px]"
          >
            <div className="flex items-center gap-3 rounded-lg bg-white px-4 py-3 text-sm shadow-lg">
              <span
                aria-hidden="true"
                className="h-5 w-5 animate-spin rounded-full border-2 border-sky-700 border-t-transparent"
              />
              <div>
                <p className="font-medium">Analyzing trip… {elapsed}s</p>
                <p className="text-xs text-slate-500">Finding truck routes and checking weather at each ETA</p>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
