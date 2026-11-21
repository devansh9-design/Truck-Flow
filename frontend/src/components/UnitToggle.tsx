import type { Units } from '../lib/units'
import { useUi } from '../store/ui'

const OPTIONS: { id: Units; label: string; title: string }[] = [
  { id: 'imperial', label: 'mi', title: 'Imperial: miles, mph, in/hr, lb' },
  { id: 'metric', label: 'km', title: 'Metric: km, km/h, mm/hr, kg' },
]

/** P3-2: switches display units only. Risk and ranking are always computed in imperial. */
export function UnitToggle() {
  const units = useUi((s) => s.units)
  const setUnits = useUi((s) => s.setUnits)
  return (
    <div role="radiogroup" aria-label="Display units" className="flex rounded-md bg-slate-100 p-0.5 text-[11px]">
      {OPTIONS.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={units === o.id}
          title={o.title}
          onClick={() => setUnits(o.id)}
          className={`min-w-8 rounded px-2 py-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50 ${
            units === o.id ? 'bg-white font-semibold text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
