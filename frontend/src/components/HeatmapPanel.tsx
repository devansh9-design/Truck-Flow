import { useEffect, useState } from 'react'
import type { HeatmapVariable, Route } from '../api/types'
import { colorAt, truckPosition, VARIABLE_ORDER, VARIABLES } from '../lib/heatmap'
import { useTimeFormatter, useUi } from '../store/ui'

interface Props {
  times: string[] | undefined
  loading: boolean
  error: string | null
  onRetry: () => void
  route: Route | undefined
}

function LegendBar({ variable }: { variable: HeatmapVariable }) {
  const s = VARIABLES[variable]
  const stops = Array.from({ length: 33 }, (_, i) => {
    const [r, g, bl] = colorAt(s, (i / 32) * s.max)
    return `rgb(${r} ${g} ${bl}) ${(i / 32) * 100}%`
  })
  return (
    <div aria-hidden="true">
      <div className="h-2 rounded-full" style={{ background: `linear-gradient(to right, ${stops.join(', ')})` }} />
      <div className="relative mt-0.5 h-3 text-[10px] text-slate-500">
        {s.ticks.map((t) => (
          <span key={t} className="absolute -translate-x-1/2 tabular-nums" style={{ left: `${(t / s.max) * 100}%` }}>
            {s.format(t)}
          </span>
        ))}
        {s.unit && <span className="absolute right-0">{s.unit}</span>}
      </div>
    </div>
  )
}

const PLAY_STEP_MS = 400

export function HeatmapPanel({ times, loading, error, onRetry, route }: Props) {
  const hour = useUi((s) => s.heatHour)
  const setHour = useUi((s) => s.setHeatHour)
  const variable = useUi((s) => s.heatVariable)
  const setVariable = useUi((s) => s.setHeatVariable)
  const visible = useUi((s) => s.heatVisible)
  const setVisible = useUi((s) => s.setHeatVisible)
  const formatTime = useTimeFormatter()
  const [playing, setPlaying] = useState(false)
  const ready = !!times && !loading && !error

  useEffect(() => {
    if (!playing) return
    const t = window.setInterval(() => {
      const h = useUi.getState().heatHour
      if (h >= 48) {
        setPlaying(false)
        return
      }
      setHour(h + 1)
    }, PLAY_STEP_MS)
    return () => window.clearInterval(t)
  }, [playing, setHour])

  const at = times?.[hour]
  const truck = route && at ? truckPosition(route, new Date(at).getTime()) : null
  const truckText =
    truck?.state === 'waiting' ? 'not yet departed' : truck?.state === 'arrived' ? 'arrived' : 'on the road'

  return (
    <section
      aria-label="Weather forecast heatmap"
      className="pointer-events-auto rounded-xl bg-white/95 p-3 text-xs text-slate-700 shadow-lg backdrop-blur"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <label className="flex cursor-pointer items-center gap-2 font-semibold text-slate-900">
          <input
            type="checkbox"
            checked={visible}
            onChange={(e) => setVisible(e.target.checked)}
            className="h-4 w-4 accent-sky-700"
          />
          Forecast heatmap
        </label>
        <div role="radiogroup" aria-label="Heatmap variable" className="flex rounded-md bg-slate-100 p-0.5">
          {VARIABLE_ORDER.map((v) => (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={variable === v}
              onClick={() => setVariable(v)}
              className={`rounded px-2 py-1 text-[11px] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50 ${
                variable === v ? 'bg-white font-semibold text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              {VARIABLES[v].label}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-red-800">
          Heatmap unavailable: {error}{' '}
          <button type="button" onClick={onRetry} className="underline hover:text-red-950">
            Retry
          </button>
          <span className="block text-slate-500">Routes and checkpoint risk above are unaffected.</span>
        </p>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                if (hour >= 48) setHour(0)
                setPlaying((p) => !p)
              }}
              disabled={!ready}
              aria-label={playing ? 'Pause forecast animation' : 'Play forecast animation'}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-700 text-white hover:bg-sky-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50 disabled:bg-slate-300"
            >
              <span aria-hidden="true">{playing ? '❚❚' : '▶'}</span>
            </button>
            <input
              type="range"
              min={0}
              max={48}
              step={1}
              value={hour}
              disabled={!ready}
              onChange={(e) => {
                setPlaying(false)
                setHour(Number(e.target.value))
              }}
              aria-label="Forecast hour after departure"
              aria-valuetext={at ? `${hour} hours after departure, ${formatTime(at)}` : `${hour} hours`}
              className="h-2 w-full cursor-pointer accent-sky-700 disabled:cursor-wait"
            />
          </div>
          <div className="mt-1 flex items-baseline justify-between gap-2">
            <span className="font-semibold tabular-nums text-slate-900">
              {hour === 0 ? 'Departure hour' : `+${hour} h`}
            </span>
            <span className="truncate text-slate-600">
              {loading ? 'Loading 48-hour forecast…' : at ? formatTime(at) : ''}
            </span>
          </div>
          {route && truck && (
            <p className="mt-0.5 text-[11px] text-slate-500">
              <span aria-hidden="true">🚚</span> {route.label}: {truckText}
            </p>
          )}
          <div className="mt-2">
            <LegendBar variable={variable} />
          </div>
        </>
      )}
    </section>
  )
}

