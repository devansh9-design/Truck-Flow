// UI-only state. It never changes a core result: it only picks what is highlighted and
// which time zone times are displayed in.
import { create } from 'zustand'
import { browserTimeZone, formatTime } from '../lib/format'

interface UiState {
  selectedRouteId: string | null
  selectedCheckpointId: string | null
  /** Trip time zone: the departure input is read in it and every time is shown in it. */
  timeZone: string
  selectRoute: (id: string | null) => void
  selectCheckpoint: (id: string | null) => void
  setTimeZone: (tz: string) => void
  reset: (routeId: string | null) => void
}

export const useUi = create<UiState>((set) => ({
  selectedRouteId: null,
  selectedCheckpointId: null,
  timeZone: browserTimeZone(),
  selectRoute: (id) =>
    set((s) => (s.selectedRouteId === id ? s : { selectedRouteId: id, selectedCheckpointId: null })),
  selectCheckpoint: (id) =>
    set(() => {
      if (!id) return { selectedCheckpointId: null }
      // Checkpoint ids are "<routeId>-c<index>": selecting one also selects its route.
      const routeId = id.slice(0, id.lastIndexOf('-c'))
      return { selectedCheckpointId: id, selectedRouteId: routeId }
    }),
  setTimeZone: (timeZone) => set({ timeZone }),
  reset: (routeId) => set({ selectedRouteId: routeId, selectedCheckpointId: null }),
}))

/** Format an ISO time in the trip's time zone (re-renders when the zone changes). */
export function useTimeFormatter(): (iso: string) => string {
  const tz = useUi((s) => s.timeZone)
  return (iso) => formatTime(iso, tz)
}
