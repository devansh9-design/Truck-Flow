import { useEffect, useState } from 'react'
import { ApiError } from './api/client'
import { useAnalyze, useHeatmap } from './api/hooks'
import type { AnalyzeRequest } from './api/types'
import { HeatmapPanel } from './components/HeatmapPanel'
import { Results } from './components/Results'
import { StatusPill } from './components/StatusPill'
import { TripForm } from './components/TripForm'
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
  const analyze = useAnalyze()
  const reset = useUi((s) => s.reset)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const elapsed = useElapsed(analyze.isPending ? startedAt : null)
  const data = analyze.isPending ? undefined : analyze.data
  const heat = useHeatmap(data)
  const selectedRouteId = useUi((s) => s.selectedRouteId)
  const selectedRoute = data?.routes.find((r) => r.id === selectedRouteId)
  const err = analyze.error instanceof ApiError ? analyze.error : null
  const serverField = err?.field ? { field: err.field, message: err.message } : null

  // Outages and timeouts are worth retrying as-is; input problems (4xx) are not.
  const retryable = !!err && (err.status === 0 || err.status >= 500)

  function submit(req: AnalyzeRequest) {
    setStartedAt(Date.now())
    analyze.mutate(req, { onSuccess: (res) => reset(res.recommendation.route_id) })
  }

  return (
    <div className="flex h-dvh flex-col bg-slate-50 text-slate-900 md:flex-row">
      <aside className="order-2 flex min-h-0 flex-1 flex-col border-slate-200 bg-slate-50 md:order-1 md:w-[400px] md:flex-none md:border-r">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
          <div>
            <h1 className="text-base font-bold tracking-tight">Truck Weather Router</h1>
            <p className="text-[11px] text-slate-500">Three truck routes, weather at every ETA</p>
          </div>
          <StatusPill />
        </header>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
            <TripForm busy={analyze.isPending} serverField={serverField} onSubmit={submit} />
          </div>

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

          {data && !analyze.isPending && <Results data={data} />}

          {!data && !analyze.isPending && !analyze.isError && (
            <p className="px-1 text-xs text-slate-500">
              Enter a trip to compare three truck routes. Each checkpoint is checked against the forecast for the hour
              the truck is due there, then routes are ranked by No Travel, Severe and High miles, average risk and time.
            </p>
          )}
        </div>
      </aside>

      <main className="relative order-1 h-[45dvh] md:order-2 md:h-auto md:flex-1" aria-label="Route map">
        <MapView data={data} heat={heat.data} />
        <div className="pointer-events-none absolute top-3 left-3">
          <Legend />
        </div>
        {data && (
          <div className="pointer-events-none absolute bottom-7 left-1/2 w-[min(540px,calc(100%-24px))] -translate-x-1/2">
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
