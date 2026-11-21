import type { AnalyzeResponse } from '../api/types'
import { decidedByText } from '../lib/risk'
import { useTimeFormatter, useUi } from '../store/ui'
import { CheckpointList } from './CheckpointList'
import { RouteCard } from './RouteCards'

export function Results({ data }: { data: AnalyzeResponse }) {
  const selectedId = useUi((s) => s.selectedRouteId)
  const { trip, routes, recommendation, notes } = data
  const formatTime = useTimeFormatter()
  const recommended = routes.find((r) => r.id === recommendation.route_id)
  const selected = routes.find((r) => r.id === selectedId) ?? recommended

  return (
    <div className="space-y-4">
      <section aria-label="Trip" className="text-xs text-slate-600">
        <p className="font-medium text-slate-900">
          {trip.origin.label} <span aria-hidden="true">→</span>
          <span className="sr-only">to</span> {trip.destination.label}
        </p>
        <p>
          Departs {formatTime(trip.departure_time)} · {trip.load_weight_lb.toLocaleString('en-US')} lb ·
          every {trip.interval_mi} mi
        </p>
      </section>

      {recommended && (
        <section
          aria-labelledby="rec-heading"
          className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm"
          data-testid="recommendation"
        >
          <h2 id="rec-heading" className="font-semibold text-sky-900">
            ★ Take {recommended.label}
          </h2>
          <p className="mt-0.5 text-xs font-medium text-sky-800">Decided by: {decidedByText(recommendation.decided_by)}</p>
          <p className="mt-1 text-xs text-slate-700">{recommendation.reason}</p>
          {recommended.warnings.includes('NO_TRAVEL_CONDITIONS') && (
            <p role="alert" className="mt-2 rounded bg-purple-100 px-2 py-1 text-xs font-semibold text-purple-900">
              Every option has No Travel conditions. Consider delaying departure.
            </p>
          )}
        </section>
      )}

      <section aria-labelledby="routes-heading" className="space-y-2">
        <h2 id="routes-heading" className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
          Route options ({routes.length})
        </h2>
        {routes.map((r) => (
          <RouteCard key={r.id} route={r} />
        ))}
        {notes.length > 0 && (
          <ul className="space-y-0.5 text-[11px] text-slate-500">
            {notes.map((n) => (
              <li key={n}>ⓘ {n}</li>
            ))}
          </ul>
        )}
      </section>

      {selected && <CheckpointList route={selected} />}
    </div>
  )
}
