// Signed-in session (ADR 013). Optional: with no token the app works as a guest.
// The token is a bearer token for the API (the API and the app are different sites, where
// cookies are unreliable). Kept in localStorage so a reload stays signed in; it expires
// after 30 days without use and is revoked on sign-out.
import { create } from 'zustand'
import type { User } from '../api/types'

const KEY = 'truckrisk.auth.v1'

interface Stored {
  token: string
  user: User
}

function load(): Stored | null {
  try {
    const raw = globalThis.localStorage?.getItem(KEY)
    if (!raw) return null
    const v = JSON.parse(raw) as Stored
    return typeof v?.token === 'string' && v.user && typeof v.user.email === 'string' ? v : null
  } catch {
    return null
  }
}

function save(v: Stored | null): void {
  try {
    if (v) globalThis.localStorage?.setItem(KEY, JSON.stringify(v))
    else globalThis.localStorage?.removeItem(KEY)
  } catch {
    /* storage blocked: the session lasts until the tab closes */
  }
}

interface AuthState {
  token: string | null
  user: User | null
  setSession: (token: string, user: User) => void
  setUser: (user: User) => void
  clear: () => void
}

const initial = load()

export const useAuth = create<AuthState>((set, get) => ({
  token: initial?.token ?? null,
  user: initial?.user ?? null,
  setSession: (token, user) => {
    save({ token, user })
    set({ token, user })
  },
  setUser: (user) => {
    const token = get().token
    if (!token) return
    save({ token, user })
    set({ user })
  },
  clear: () => {
    save(null)
    set({ token: null, user: null })
  },
}))

/** Countries whose roads are signed in miles: new accounts there start with imperial units. */
export const IMPERIAL_COUNTRIES = new Set(['US', 'GB', 'LR', 'MM'])
