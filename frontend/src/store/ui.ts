// UI-only state. It never changes a core result: it only picks what is highlighted and
// which time zone times are displayed in.
import { create } from 'zustand'
import type { HeatmapVariable } from '../api/types'
import { browserTimeZone, formatTime } from '../lib/format'
import { loadUnits, storeUnits, unitFormat, type UnitFormat, type Units } from '../lib/units'

interface UiState {
  selectedRouteId: string | null
  selectedCheckpointId: string | null
  /** P3-3: alert point (index into the alerts request) whose alerts are open on the map. */
  selectedAlertPoint: number | null
  selectAlertPoint: (i: number | null) => void
  /** Trip time zone: the departure input is read in it and every time is shown in it. */
  timeZone: string
  /** P3-2: display units only; the wire and the rules stay imperial. */
  units: Units
  setUnits: (u: Units) => void
  /** Heatmap: slider hour 0..48 (0 = departure hour), variable, visibility (CORE-6). */
  heatHour: number
  heatVariable: HeatmapVariable
  heatVisible: boolean
  setHeatHour: (h: number) => void
  setHeatVariable: (v: HeatmapVariable) => void
  setHeatVisible: (on: boolean) => void
  selectRoute: (id: string | null) => void
  selectCheckpoint: (id: string | null) => void
  setTimeZone: (tz: string) => void
  reset: (routeId: string | null) => void
}

export const useUi = create<UiState>((set) => ({
  selectedRouteId: null,
  selectedCheckpointId: null,
  selectedAlertPoint: null,
  selectAlertPoint: (selectedAlertPoint) => set({ selectedAlertPoint }),
  timeZone: browserTimeZone(),
  units: loadUnits(),
  setUnits: (units) => {
    storeUnits(units)
    set({ units })
  },
  heatHour: 0,
  heatVariable: 'risk',
  heatVisible: true,
  setHeatHour: (h) => set({ heatHour: Math.max(0, Math.min(48, Math.round(h))) }),
  setHeatVariable: (heatVariable) => set({ heatVariable }),
  setHeatVisible: (heatVisible) => set({ heatVisible }),
  selectRoute: (id) => set((s) => (s.selectedRouteId === id ? s : { selectedRouteId: id, selectedCheckpointId: null })),
  selectCheckpoint: (id) =>
    set(() => {
      if (!id) return { selectedCheckpointId: null }
      // Checkpoint ids are "<routeId>-c<index>": selecting one also selects its route.
      const routeId = id.slice(0, id.lastIndexOf('-c'))
      return { selectedCheckpointId: id, selectedRouteId: routeId }
    }),
  setTimeZone: (timeZone) => set({ timeZone }),
  reset: (routeId) =>
    set({ selectedRouteId: routeId, selectedCheckpointId: null, selectedAlertPoint: null, heatHour: 0 }),
}))

/** Format an ISO time in the trip's time zone (re-renders when the zone changes). */
export function useTimeFormatter(): (iso: string) => string {
  const tz = useUi((s) => s.timeZone)
  return (iso) => formatTime(iso, tz)
}

/** Number formatters for the chosen display units. */
export function useUnitFormat(): UnitFormat {
  return unitFormat(useUi((s) => s.units))
}
