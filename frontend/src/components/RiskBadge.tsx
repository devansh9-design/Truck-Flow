import type { RiskLevel } from '../api/types'
import { riskStyle } from '../lib/risk'

export function RiskBadge({ level, size = 'md' }: { level: RiskLevel; size?: 'sm' | 'md' }) {
  const s = riskStyle(level)
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-semibold whitespace-nowrap ${
        size === 'sm' ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-0.5 text-xs'
      }`}
      style={{ background: s.color, color: s.text }}
    >
      <span aria-hidden="true">{s.icon}</span>
      {s.label}
    </span>
  )
}
