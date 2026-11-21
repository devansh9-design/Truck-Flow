import { RISK_LEVELS } from '../api/types'
import { riskStyle } from '../lib/risk'

export function Legend() {
  return (
    <div className="pointer-events-auto rounded-lg bg-white/95 p-2.5 text-[11px] text-slate-700 shadow-md backdrop-blur">
      <div className="mb-1 font-semibold text-slate-900">Risk level</div>
      <ul className="space-y-0.5">
        {RISK_LEVELS.map((l) => {
          const s = riskStyle(l)
          return (
            <li key={l} className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="flex h-3.5 w-3.5 items-center justify-center rounded-full text-[8px] font-bold"
                style={{ background: s.color, color: s.text }}
              >
                {s.icon}
              </span>
              {s.label}
            </li>
          )
        })}
      </ul>
      <div className="mt-1.5 space-y-0.5 border-t border-slate-200 pt-1.5">
        <div className="flex items-center gap-1.5">
          <svg width="18" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="18" y2="3" stroke="#0369a1" strokeWidth="3" strokeDasharray="4 3" />
          </svg>
          Recommended
        </div>
        <div className="flex items-center gap-1.5">
          <svg width="18" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="18" y2="3" stroke="#64748b" strokeWidth="3" />
          </svg>
          Alternative
        </div>
      </div>
    </div>
  )
}
