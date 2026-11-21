import type { ReactNode } from 'react'
import type { AlertsResponse, Route, WeatherAlert } from '../api/types'
import { SEVERITY_STYLE, type AlertPoint } from '../lib/alerts'
import { useTimeFormatter, useUi } from '../store/ui'

interface Props {
  routes: Route[]
  points: AlertPoint[]
  data: AlertsResponse | undefined
  loading: boolean
  error: string | null
  onRetry: () => void
}

export function SeverityChip({ alert }: { alert: Pick<WeatherAlert, 'severity'> }) {
  const s = SEVERITY_STYLE[alert.severity]
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold"
      style={{ background: s.bg, color: s.text, borderColor: s.border }}
    >
      <span aria-hidden="true">⚠</span>
      {alert.severity}
    </span>
  )
}

function When({ alert }: { alert: WeatherAlert }) {
  const formatTime = useTimeFormatter()
  const from = alert.onset ? formatTime(alert.onset) : null
  const to = alert.ends ? formatTime(alert.ends) : 'further notice'
  return <p className="text-slate-500">{from ? `${from} → ${to}` : `Until ${to}`}</p>
}

/** P3-3: NWS alerts near the routes. Informational only; never changes risk or ranking. */
export function AlertsPanel({ routes, points, data, loading, error, onRetry }: Props) {
  const selected = useUi((s) => s.selectedAlertPoint)
  const selectAlertPoint = useUi((s) => s.selectAlertPoint)
  const labelOf = (id: string) => routes.find((r) => r.id === id)?.label ?? id
  const alerts = data?.alerts ?? []

  let body: ReactNode
  if (error) {
    body = (
      <p role="alert" className="text-slate-600">
        Weather alerts are unavailable right now.{' '}
        <button type="button" onClick={onRetry} className="text-sky-700 underline hover:text-sky-900">
          Retry
        </button>
      </p>
    )
  } else if (loading || !data) {
    body = <p className="text-slate-500">Checking National Weather Service alerts along the routes…</p>
  } else if (data.coverage === 'unsupported_region') {
    body = (
      <p className="text-slate-600">
        Weather alerts are not available for this region (US National Weather Service only).
      </p>
    )
  } else if (alerts.length === 0) {
    body = <p className="text-slate-600">No active weather alerts along these routes.</p>
  } else {
    body = (
      <ul className="space-y-1.5">
        {alerts.map((a) => {
          const pt = points[a.point_index]
          const near = pt ? pt.routeIds.map(labelOf).join(', ') : ''
          const active = selected === a.point_index
          return (
            <li key={a.id}>
              <button
                type="button"
                onClick={() => selectAlertPoint(active ? null : a.point_index)}
                aria-pressed={active}
                data-testid="alert-item"
                className={`block w-full rounded-md border bg-white p-2 text-left hover:border-slate-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/60 ${
                  active ? 'border-orange-600 ring-1 ring-orange-600' : 'border-slate-200'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-semibold text-slate-900">{a.event}</span>
                  <SeverityChip alert={a} />
                </div>
                {near && <p className="text-slate-600">Near {near}</p>}
                <When alert={a} />
                {a.areas && <p className="line-clamp-2 text-slate-500">{a.areas}</p>}
              </button>
            </li>
          )
        })}
      </ul>
    )
  }

  return (
    <section aria-labelledby="alerts-heading" className="text-xs" data-testid="alerts-panel">
      <h2 id="alerts-heading" className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        Weather alerts{data && data.coverage === 'US' ? ` (${alerts.length})` : ''}
      </h2>
      <p className="mb-1.5 text-[11px] text-slate-500">
        From the National Weather Service. For information only: alerts do not change risk levels or the ranking.
      </p>
      {body}
    </section>
  )
}
