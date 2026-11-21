import { useHealth } from '../api/hooks'

export function StatusPill() {
  const { data, isPending, isError, refetch, isFetching } = useHealth()
  let dot = 'bg-amber-400 animate-pulse'
  let text = 'Waking services…'
  if (isError) {
    dot = 'bg-red-500'
    text = 'API unreachable'
  } else if (!isPending && data) {
    const ok = data.risk_engine === 'ok'
    dot = ok ? 'bg-emerald-500' : 'bg-red-500'
    text = ok ? 'Services ready' : 'Risk engine down'
  }
  return (
    <div role="status" className="flex items-center gap-1.5 text-[11px] text-slate-600">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dot}`} />
      {text}
      {(isError || data?.risk_engine === 'down') && (
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="ml-1 rounded px-1 text-sky-700 underline hover:text-sky-900 disabled:opacity-50"
        >
          Retry
        </button>
      )}
    </div>
  )
}
