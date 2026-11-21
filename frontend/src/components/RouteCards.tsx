import { RISK_LEVELS, type Route } from '../api/types'
import { formatDuration, formatMiles, formatNumber } from '../lib/format'
import { riskStyle } from '../lib/risk'
import { useTimeFormatter, useUi } from '../store/ui'
import { RiskBadge } from './RiskBadge'

function LevelBar({ route }: { route: Route }) {
  const total = RISK_LEVELS.reduce((s, l) => s + route.summary.miles_by_level[l], 0) || 1
  const parts = RISK_LEVELS.filter((l) => route.summary.miles_by_level[l] > 0)
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full bg-slate-200" aria-hidden="true">
        {parts.map((l) => (
          <div
            key={l}
            style={{ width: `${(route.summary.miles_by_level[l] / total) * 100}%`, background: riskStyle(l).color }}
          />
        ))}
      </div>
      <p className="sr-only">
        Miles by risk level:{' '}
        {parts.map((l) => `${riskStyle(l).label} ${formatMiles(route.summary.miles_by_level[l])}`).join(', ')}
      </p>
    </div>
  )
}

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] text-slate-500">{label}</dt>
      <dd className={`tabular-nums ${strong ? 'font-semibold text-slate-900' : 'text-slate-800'}`}>{value}</dd>
    </div>
  )
}

export function RouteCard({ route, reason }: { route: Route; reason?: string }) {
  const selected = useUi((s) => s.selectedRouteId === route.id)
  const selectRoute = useUi((s) => s.selectRoute)
  const s = route.summary
  const formatTime = useTimeFormatter()
  return (
    <button
      type="button"
      onClick={() => selectRoute(route.id)}
      aria-pressed={selected}
      data-testid={`route-card-${route.id}`}
      className={`block w-full rounded-lg border bg-white p-3 text-left text-sm shadow-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/60 ${
        selected ? 'border-sky-600 ring-1 ring-sky-600' : 'border-slate-200 hover:border-slate-400'
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
              route.recommended ? 'bg-sky-700 text-white' : 'bg-slate-200 text-slate-700'
            }`}
            aria-label={`Rank ${route.rank}`}
          >
            {route.rank}
          </span>
          <span className="font-semibold text-slate-900">{route.label}</span>
          {route.recommended && (
            <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[11px] font-semibold text-sky-800">
              ★ Recommended
            </span>
          )}
        </div>
        <RiskBadge level={s.max_level} size="sm" />
      </div>

      <dl className="mb-2 grid grid-cols-3 gap-x-2 gap-y-1.5">
        <Stat label="Distance" value={formatMiles(route.distance_mi)} />
        <Stat label="Drive time" value={formatDuration(route.duration_s)} />
        <Stat label="Avg risk" value={formatNumber(s.avg_risk, 2)} />
        <Stat label="No Travel" value={formatMiles(s.no_travel_mi)} strong={s.no_travel_mi > 0} />
        <Stat label="Severe" value={formatMiles(s.severe_mi)} strong={s.severe_mi > 0} />
        <Stat label="High" value={formatMiles(s.high_mi)} strong={s.high_mi > 0} />
      </dl>
      <LevelBar route={route} />
      <p className="mt-2 text-xs text-slate-500">Arrives {formatTime(route.arrival_time)}</p>

      {route.warnings.includes('NO_TRAVEL_CONDITIONS') && (
        <p className="mt-2 rounded bg-purple-50 px-2 py-1 text-xs font-medium text-purple-900">
          ✕ No Travel conditions on {formatMiles(s.no_travel_mi)} of this route.
        </p>
      )}
      {reason && <p className="mt-2 border-t border-slate-100 pt-2 text-xs text-slate-700">{reason}</p>}
    </button>
  )
}
