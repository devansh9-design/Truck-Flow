// Driving mode monitor (phase 1, D17): follows the phone's GPS while the app is open, keeps the
// screen awake, re-analyses the road ahead on a schedule and raises a warning when weather
// makes another route meaningfully safer or the current route worse.
import { useEffect, useRef } from 'react'
import { assess, DISMISS_MS, hasArrived, matchCurrentRoute, shouldRecheck, worsened } from '../lib/driving'
import { unitFormat } from '../lib/units'
import { useDriving } from '../store/driving'
import { useUi } from '../store/ui'
import { ApiError, analyzeTrip } from './client'

const TICK_MS = 30_000

export function speak(text: string) {
  if (useDriving.getState().muted) return
  try {
    const synth = globalThis.speechSynthesis
    if (!synth) return
    synth.cancel()
    synth.speak(new SpeechSynthesisUtterance(text))
  } catch {
    /* speech is a convenience */
  }
  try {
    navigator.vibrate?.([250, 120, 250])
  } catch {
    /* not supported */
  }
}

/** One re-check: analyse from the current position, find the road being driven, assess. */
export async function recheck(): Promise<void> {
  const st = useDriving.getState()
  if (!st.active || !st.trip || !st.position || st.status === 'checking' || st.status === 'arrived') return
  const pos = st.position
  st.set({ status: 'checking', checkError: null })
  try {
    const res = await analyzeTrip({
      origin: { label: 'Current position', lat: pos.lat, lon: pos.lon },
      destination: st.trip.destination,
      departure_time: new Date().toISOString(),
      load_weight_lb: st.trip.load_weight_lb,
      interval_mi: st.trip.interval_mi,
    })
    const after = useDriving.getState()
    if (!after.active) return // trip ended while checking
    const { route: current } = matchCurrentRoute(res.routes, after.reference)
    const best = res.routes.find((r) => r.id === res.recommendation.route_id) ?? current
    const now = Date.now()
    let warning = assess(current, best, after.lastSummary, now, unitFormat(useUi.getState().units))
    // "Keep my route" silences warnings for a while, unless things get worse than at that moment.
    const d = after.dismissed
    if (warning && d && now < d.until && !worsened(current.summary, d.summary)) warning = null
    useUi.getState().selectRoute(current.id)
    after.set({
      status: 'monitoring',
      liveData: res,
      reference: current.geometry.coordinates,
      routeLabel: current.label,
      lastCheck: { at: now, pos: [pos.lon, pos.lat] },
      lastSummary: current.summary,
      warning: warning ?? after.warning,
    })
    if (warning) speak(warning.spoken)
  } catch (e) {
    useDriving.getState().set({
      status: 'monitoring',
      // Try again at the next tick rather than at once.
      lastCheck: { at: Date.now(), pos: [pos.lon, pos.lat] },
      checkError: e instanceof ApiError ? e.message : 'The re-check failed. It will be retried.',
    })
  }
}

/** Accept the suggested route: show it and keep monitoring it. */
export function switchRoute() {
  const st = useDriving.getState()
  const id = st.warning?.suggestRouteId
  const route = st.liveData?.routes.find((r) => r.id === id)
  if (!route) return st.set({ warning: null })
  useUi.getState().selectRoute(route.id)
  st.set({
    warning: null,
    reference: route.geometry.coordinates,
    routeLabel: route.label,
    lastSummary: route.summary,
    dismissed: null,
  })
}

export function keepRoute() {
  const st = useDriving.getState()
  st.set({
    warning: null,
    dismissed: st.lastSummary ? { until: Date.now() + DISMISS_MS, summary: st.lastSummary } : null,
  })
}

/** Runs while driving mode is on (mount once, in App). */
export function useDrivingMonitor() {
  const active = useDriving((s) => s.active)
  const wakeLock = useRef<{ release: () => Promise<void> } | null>(null)

  // GPS
  useEffect(() => {
    if (!active) return
    const geo = globalThis.navigator?.geolocation
    if (!geo) {
      useDriving.getState().set({ gpsError: 'This device cannot share its location, so driving mode cannot run.' })
      return
    }
    const id = geo.watchPosition(
      (p) => {
        const st = useDriving.getState()
        if (st.status === 'arrived') return // announced once; the driver closes the bar
        const pos = { lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }
        if (st.trip && hasArrived([pos.lon, pos.lat], [st.trip.destination.lon, st.trip.destination.lat])) {
          st.set({ position: pos, status: 'arrived', warning: null, gpsError: null })
          speak('You have arrived. Driving mode has ended.')
          return
        }
        st.set({ position: pos, gpsError: null, status: st.status === 'locating' ? 'monitoring' : st.status })
        if (shouldRecheck(st.lastCheck, [pos.lon, pos.lat], Date.now())) void recheck()
      },
      (err) => {
        useDriving.getState().set({
          gpsError:
            err.code === err.PERMISSION_DENIED
              ? 'Location permission was refused. Allow location for this site to use driving mode.'
              : 'Waiting for a GPS signal…',
        })
      },
      { enableHighAccuracy: true, maximumAge: 15_000, timeout: 60_000 },
    )
    return () => geo.clearWatch(id)
  }, [active])

  // Timed re-checks even when the truck is stopped (weather changes anyway).
  useEffect(() => {
    if (!active) return
    const t = window.setInterval(() => {
      const st = useDriving.getState()
      if (st.status === 'arrived' || !st.position) return
      if (shouldRecheck(st.lastCheck, [st.position.lon, st.position.lat], Date.now())) void recheck()
    }, TICK_MS)
    return () => window.clearInterval(t)
  }, [active])

  // Keep the screen on while driving (where supported); re-acquire after the tab returns.
  useEffect(() => {
    if (!active) return
    const nav = navigator as Navigator & {
      wakeLock?: { request: (t: 'screen') => Promise<{ release: () => Promise<void> }> }
    }
    const acquire = () => {
      if (document.visibilityState !== 'visible' || !nav.wakeLock) return
      nav.wakeLock.request('screen').then(
        (l) => (wakeLock.current = l),
        () => undefined,
      )
    }
    acquire()
    document.addEventListener('visibilitychange', acquire)
    return () => {
      document.removeEventListener('visibilitychange', acquire)
      void wakeLock.current?.release().catch(() => undefined)
      wakeLock.current = null
    }
  }, [active])
}
