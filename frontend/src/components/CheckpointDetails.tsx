import type { Checkpoint, RiskLevel } from '../api/types'
import { riskStyle } from '../lib/risk'
import { useTimeFormatter, useUnitFormat } from '../store/ui'
import { RiskBadge } from './RiskBadge'

function FactorRow({ name, value, level }: { name: string; value: string; level: RiskLevel }) {
  const s = riskStyle(level)
  return (
    <tr>
      <th scope="row" className="py-0.5 pr-3 text-left font-normal text-slate-500">
        {name}
      </th>
      <td className="py-0.5 pr-3 text-right tabular-nums text-slate-900">{value}</td>
      <td className="py-0.5 text-slate-600">
        <span aria-hidden="true" style={{ color: s.color }}>
          ●
        </span>{' '}
        {s.label}
      </td>
    </tr>
  )
}

/** Everything known about one checkpoint: ETA, the forecast at its ETA hour, risk and why. */
export function CheckpointDetails({ cp, routeLabel, isLast }: { cp: Checkpoint; routeLabel: string; isLast: boolean }) {
  const place = cp.index === 0 ? 'Origin' : isLast ? 'Destination' : `Checkpoint ${cp.index}`
  const f = cp.risk.factors
  const formatTime = useTimeFormatter()
  const u = useUnitFormat()
  return (
    <div className="min-w-56 text-xs">
      <div className="mb-1 flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-slate-900">
            {routeLabel} · {place}
          </div>
          <div className="text-slate-500">{u.distance(cp.mile)} along the route</div>
        </div>
        <RiskBadge level={cp.risk.level} size="sm" />
      </div>
      <dl className="mb-2 grid grid-cols-[auto_1fr] gap-x-2 text-slate-700">
        <dt className="text-slate-500">ETA</dt>
        <dd>{formatTime(cp.eta)}</dd>
        <dt className="text-slate-500">Forecast</dt>
        <dd>{formatTime(cp.forecast_hour)}</dd>
      </dl>
      <table className="mb-2 w-full">
        <tbody>
          <FactorRow name="Wind" value={u.speed(cp.weather.wind_mph)} level={f.wind} />
          <FactorRow name="Rain" value={u.rate(cp.weather.rain_in_hr)} level={f.rain} />
          <FactorRow name="Snow" value={u.rate(cp.weather.snow_in_hr)} level={f.snow} />
        </tbody>
      </table>
      {f.load_override && (
        <p className="mb-1 font-medium text-red-800">Load rule raised this to {riskStyle(f.load_override).label}.</p>
      )}
      <p className="text-slate-700">{cp.risk.reason}</p>
    </div>
  )
}
