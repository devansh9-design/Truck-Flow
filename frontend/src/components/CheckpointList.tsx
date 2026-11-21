import type { Route } from '../api/types'
import { useTimeFormatter, useUi, useUnitFormat } from '../store/ui'
import { RiskBadge } from './RiskBadge'

/** Text view of the selected route's checkpoints (risk + ETA), mirrored on the map. */
export function CheckpointList({ route }: { route: Route }) {
  const selectedId = useUi((s) => s.selectedCheckpointId)
  const selectCheckpoint = useUi((s) => s.selectCheckpoint)
  const last = route.checkpoints.length - 1
  const formatTime = useTimeFormatter()
  const u = useUnitFormat()
  return (
    <section aria-labelledby="cp-heading">
      <h2 id="cp-heading" className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        {route.label} checkpoints ({route.checkpoints.length})
      </h2>
      <ol className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-xs">
        {route.checkpoints.map((cp) => (
          <li key={cp.id}>
            <button
              type="button"
              onClick={() => selectCheckpoint(cp.id)}
              aria-current={selectedId === cp.id ? 'true' : undefined}
              className={`grid w-full grid-cols-[3.5rem_1fr_auto] items-center gap-2 px-2.5 py-1.5 text-left hover:bg-slate-50 focus:outline-none focus-visible:bg-sky-50 ${
                selectedId === cp.id ? 'bg-sky-50' : ''
              }`}
            >
              <span className="tabular-nums text-slate-500">
                {cp.index === 0 ? 'Start' : cp.index === last ? 'End' : u.distance(cp.mile, 0)}
              </span>
              <span className="truncate text-slate-800">{formatTime(cp.eta)}</span>
              <RiskBadge level={cp.risk.level} size="sm" />
            </button>
          </li>
        ))}
      </ol>
    </section>
  )
}
