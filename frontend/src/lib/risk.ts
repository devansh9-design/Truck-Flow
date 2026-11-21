// Risk level → colour + label + icon. Risk is always shown as text and icon as well as
// colour (NFR-5), so the palette never carries meaning on its own.
import { RISK_LEVELS, type DecidedBy, type RiskLevel } from '../api/types'

export interface RiskStyle {
  label: string
  short: string
  icon: string
  color: string
  text: string
}

export const RISK_STYLE: Record<RiskLevel, RiskStyle> = {
  LOW: { label: 'Low', short: 'LOW', icon: '✓', color: '#1b9e77', text: '#ffffff' },
  MODERATE: { label: 'Moderate', short: 'MOD', icon: '!', color: '#e6c229', text: '#1f1a00' },
  HIGH: { label: 'High', short: 'HIGH', icon: '‼', color: '#f28e2b', text: '#1f1000' },
  SEVERE: { label: 'Severe', short: 'SEV', icon: '▲', color: '#d7263d', text: '#ffffff' },
  NO_TRAVEL: { label: 'No Travel', short: 'NO GO', icon: '✕', color: '#4b1d6e', text: '#ffffff' },
}

export const riskStyle = (level: RiskLevel): RiskStyle => RISK_STYLE[level]

/** MapLibre `match` expression colouring a feature by its `level` property. */
export const riskColorExpression = (): unknown[] => [
  'match',
  ['get', 'level'],
  ...RISK_LEVELS.flatMap((l) => [l, RISK_STYLE[l].color]),
  '#888888',
]

const DECIDED_BY_TEXT: Record<DecidedBy, string> = {
  no_travel_mi: 'Fewest No Travel miles',
  severe_mi: 'Fewest Severe miles',
  high_mi: 'Fewest High miles',
  avg_risk: 'Lowest average risk',
  duration_s: 'Shortest travel time',
  tie: 'Tied on every key',
  only_route: 'Only route available',
}

export const decidedByText = (key: DecidedBy): string => DECIDED_BY_TEXT[key] ?? key
