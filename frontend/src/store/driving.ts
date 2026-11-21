// Driving mode state (phase 1, D17). UI-only: re-checks are ordinary analyses; nothing here
// changes how risk or ranking are computed.
import { create } from 'zustand'
import type { AnalyzeResponse, Interval, Place, RouteSummary } from '../api/types'
import type { DrivingWarning, LastCheck } from '../lib/driving'

type Coord = [number, number]

export interface DrivingTrip {
  destination: Place
  load_weight_lb: number
  interval_mi: Interval
}

export interface DrivingState {
  active: boolean
  status: 'locating' | 'monitoring' | 'checking' | 'arrived'
  trip: DrivingTrip | null
  /** Route being driven: label and line (used to recognise it in each fresh analysis). */
  routeLabel: string
  reference: Coord[]
  position: { lat: number; lon: number; accuracy: number } | null
  gpsError: string | null
  checkError: string | null
  lastCheck: LastCheck
  /** Current route's summary at the last check (to spot worsening). */
  lastSummary: RouteSummary | null
  /** Latest re-check result, shown instead of the original analysis while driving. */
  liveData: AnalyzeResponse | null
  warning: DrivingWarning | null
  dismissed: { until: number; summary: RouteSummary } | null
  muted: boolean
  start: (trip: DrivingTrip, routeLabel: string, reference: Coord[], summary: RouteSummary) => void
  stop: () => void
  set: (patch: Partial<DrivingState>) => void
}

const idle = {
  active: false,
  status: 'locating' as const,
  trip: null,
  routeLabel: '',
  reference: [] as Coord[],
  position: null,
  gpsError: null,
  checkError: null,
  lastCheck: { at: 0, pos: null },
  lastSummary: null,
  liveData: null,
  warning: null,
  dismissed: null,
}

export const useDriving = create<DrivingState>((set) => ({
  ...idle,
  muted: false,
  start: (trip, routeLabel, reference, summary) =>
    set({
      ...idle,
      active: true,
      trip,
      routeLabel,
      reference,
      lastSummary: summary,
      lastCheck: { at: Date.now(), pos: null },
    }),
  stop: () => set({ ...idle }),
  set: (patch) => set(patch),
}))
