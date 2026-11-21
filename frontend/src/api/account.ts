// Account hooks (A6-A9). Signing in is optional; nothing here touches a core result.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { sameTrip, tripFromResult, type SavedTrip } from '../lib/savedTrips'
import { useAuth } from '../store/auth'
import { useSavedTrips } from '../store/savedTrips'
import {
  createTrip,
  getCountries,
  getMe,
  importTrips,
  listTrips,
  removeServerTrip,
  signIn,
  signOut,
  signUp,
} from './client'
import type { AnalyzeResponse, Session } from './types'

export const useCountries = () =>
  useQuery({ queryKey: ['countries'], queryFn: getCountries, staleTime: Infinity, gcTime: Infinity, retry: 2 })

/** On load, refresh the stored profile (and drop a session the server no longer accepts). */
export function useSessionCheck() {
  const token = useAuth((s) => s.token)
  const setUser = useAuth((s) => s.setUser)
  const me = useQuery({
    queryKey: ['me', token],
    queryFn: getMe,
    enabled: !!token,
    retry: false,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  })
  useEffect(() => {
    if (me.data) setUser(me.data.user)
  }, [me.data, setUser])
}

const tripsKey = (userId: number | undefined) => ['trips', userId] as const

/**
 * After sign-in or sign-up: store the session and move trips saved in this browser into
 * the account (the server keeps the newest 20). Returns how many were moved.
 */
export function useStartSession() {
  const qc = useQueryClient()
  return async (s: Session): Promise<number> => {
    useAuth.getState().setSession(s.token, s.user)
    qc.removeQueries({ queryKey: ['trips'] })
    const local = useSavedTrips.getState().trips
    if (local.length === 0) return 0
    try {
      const res = await importTrips(local)
      qc.setQueryData(tripsKey(s.user.id), res)
      useSavedTrips.getState().clear()
      return local.length
    } catch {
      return 0 // kept in the browser; nothing is lost
    }
  }
}

export const useSignIn = () => useMutation({ mutationFn: signIn })
export const useSignUp = () => useMutation({ mutationFn: signUp })

export function useSignOut() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => signOut().catch(() => null), // sign out locally even if the server is unreachable
    onSettled: () => {
      useAuth.getState().clear()
      qc.removeQueries({ queryKey: ['trips'] })
      qc.removeQueries({ queryKey: ['me'] })
    },
  })
}

export interface TripsSource {
  signedIn: boolean
  trips: SavedTrip[]
  loading: boolean
  error: string | null
  save: (data: AnalyzeResponse, timeZone: string) => Promise<boolean>
  remove: (id: string) => Promise<void>
  isSaved: (data: AnalyzeResponse, timeZone: string) => boolean
}

/** Saved trips: the account's (server) when signed in, else this browser's (P3-4). */
export function useTrips(): TripsSource {
  const user = useAuth((s) => s.user)
  const qc = useQueryClient()
  const local = useSavedTrips()
  const server = useQuery({
    queryKey: tripsKey(user?.id),
    queryFn: listTrips,
    enabled: !!user,
    staleTime: 60 * 1000,
  })
  const trips = user ? (server.data?.trips ?? []) : local.trips

  return {
    signedIn: !!user,
    trips,
    loading: !!user && server.isPending,
    error: user && server.isError ? server.error.message : null,
    isSaved: (data, tz) => trips.some((t) => sameTrip(t, tripFromResult(data, tz))),
    save: async (data, tz) => {
      if (!user) return local.save(data, tz)
      try {
        await createTrip(tripFromResult(data, tz))
        await qc.invalidateQueries({ queryKey: tripsKey(user.id) })
        return true
      } catch {
        return false
      }
    },
    remove: async (id) => {
      if (!user) return local.remove(id)
      await removeServerTrip(id).catch(() => null)
      await qc.invalidateQueries({ queryKey: tripsKey(user.id) })
    },
  }
}
