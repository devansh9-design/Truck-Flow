// P3-4: saved trips, mirrored to localStorage. Reading or writing them never touches a core result.
import { create } from 'zustand'
import type { AnalyzeResponse } from '../api/types'
import { addTrip, loadTrips, removeTrip, tripFromResult, writeTrips, type SavedTrip } from '../lib/savedTrips'

interface SavedTripsState {
  trips: SavedTrip[]
  /** false if the browser refused to store it (the list still shows it for this session). */
  save: (data: AnalyzeResponse, timeZone: string) => boolean
  remove: (id: string) => void
}

export const useSavedTrips = create<SavedTripsState>((set, get) => ({
  trips: loadTrips(),
  save: (data, timeZone) => {
    const trips = addTrip(get().trips, tripFromResult(data, timeZone))
    set({ trips })
    return writeTrips(trips)
  },
  remove: (id) => {
    const trips = removeTrip(get().trips, id)
    set({ trips })
    writeTrips(trips)
  },
}))
