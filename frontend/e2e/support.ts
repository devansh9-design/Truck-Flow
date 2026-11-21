import type { Page, Request } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
export const ANALYZE = JSON.parse(readFileSync(join(here, 'fixtures', 'analyze.json'), 'utf8'))
export const HEATMAP = readFileSync(join(here, 'fixtures', 'heatmap.json'), 'utf8')
// Shared fixture: one recorded NWS High Wind Warning at point 1 (shared/fixtures/alerts_response.json).
export const ALERTS = JSON.parse(readFileSync(join(here, 'fixtures', 'alerts.json'), 'utf8'))

const BLANK_STYLE = JSON.stringify({
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#eef2f6' } }],
})

export interface Mocks {
  /** Every request the app made to the fake API host, in order. */
  apiCalls: Request[]
  analyzeStatus: number
  /** Body for POST /api/alerts (P3-3). */
  alerts: unknown
  /** A fake account server (A6-A9): users by email, the token in use, saved trips. */
  account: {
    users: Record<string, { password: string; user: Record<string, unknown> }>
    token: string | null
    trips: Record<string, unknown>[]
  }
}

const COUNTRIES = {
  continents: ['Europe', 'North America'],
  countries: [
    { code: 'ES', name: 'Spain', continent: 'Europe' },
    { code: 'FR', name: 'France', continent: 'Europe' },
    { code: 'US', name: 'United States', continent: 'North America' },
  ],
}

/** Answer the fake API and map hosts from fixtures. Change `analyzeStatus` to simulate errors. */
export async function mockBackend(page: Page): Promise<Mocks> {
  const mocks: Mocks = {
    apiCalls: [],
    analyzeStatus: 200,
    alerts: ALERTS,
    account: { users: {}, token: null, trips: [] },
  }
  await page.route('http://tiles.test/**', (route) =>
    route.fulfill({ contentType: 'application/json', body: BLANK_STYLE }),
  )
  await page.route('http://api.test/**', async (route) => {
    const req = route.request()
    mocks.apiCalls.push(req)
    const path = new URL(req.url()).pathname
    if (path === '/api/health') {
      return route.fulfill({ json: { status: 'ok', risk_engine: 'ok', time: new Date().toISOString() } })
    }
    if (path === '/api/analyze') {
      if (mocks.analyzeStatus !== 200) {
        return route.fulfill({
          status: mocks.analyzeStatus,
          json: {
            error: {
              code: 'UPSTREAM_ERROR',
              message: 'The weather service is unavailable right now. Please try again.',
            },
          },
        })
      }
      return route.fulfill({ json: ANALYZE })
    }
    const acct = mocks.account
    const signedIn = !!acct.token && req.headers()['authorization'] === `Bearer ${acct.token}`
    const needAuth = () =>
      route.fulfill({ status: 401, json: { error: { code: 'NOT_AUTHENTICATED', message: 'Please sign in.' } } })
    if (path === '/api/countries') return route.fulfill({ json: COUNTRIES })
    if (path === '/api/auth/signup') {
      const b = req.postDataJSON()
      const c = COUNTRIES.countries.find((x) => x.code === b.country)!
      const user = {
        id: 1,
        email: b.email,
        name: b.name,
        country: c.code,
        country_name: c.name,
        continent: c.continent,
        is_staff: false,
        date_joined: new Date().toISOString(),
      }
      acct.users[b.email] = { password: b.password, user }
      acct.token = 'tok-1'
      return route.fulfill({ status: 201, json: { token: acct.token, expires_at: '2099-01-01T00:00:00Z', user } })
    }
    if (path === '/api/auth/login') {
      const b = req.postDataJSON()
      const u = acct.users[b.email]
      if (!u || u.password !== b.password) {
        return route.fulfill({
          status: 401,
          json: { error: { code: 'INVALID_CREDENTIALS', message: 'Email or password is incorrect.' } },
        })
      }
      acct.token = 'tok-2'
      return route.fulfill({ json: { token: acct.token, expires_at: '2099-01-01T00:00:00Z', user: u.user } })
    }
    if (path === '/api/auth/me') {
      if (!signedIn) return needAuth()
      return route.fulfill({ json: { user: Object.values(acct.users)[0].user } })
    }
    if (path === '/api/auth/logout') {
      acct.token = null
      return route.fulfill({ status: 204, body: '' })
    }
    if (path.startsWith('/api/trips')) {
      if (!signedIn) return needAuth()
      if (path === '/api/trips/import') {
        acct.trips = req
          .postDataJSON()
          .trips.map((t: object, i: number) => ({ id: `s${i}`, saved_at: new Date().toISOString(), ...t }))
        return route.fulfill({ json: { trips: acct.trips } })
      }
      if (req.method() === 'POST') {
        const trip = { id: `s${acct.trips.length + 10}`, saved_at: new Date().toISOString(), ...req.postDataJSON() }
        acct.trips.unshift(trip)
        return route.fulfill({ status: 201, json: { trip } })
      }
      if (req.method() === 'DELETE') {
        acct.trips = acct.trips.filter((t) => `/api/trips/${t.id}` !== path)
        return route.fulfill({ status: 204, body: '' })
      }
      return route.fulfill({ json: { trips: acct.trips } })
    }
    if (path === '/api/alerts') {
      return route.fulfill({ json: mocks.alerts })
    }
    if (path === '/api/heatmap') {
      return route.fulfill({ contentType: 'application/json', body: HEATMAP })
    }
    return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message: 'Not found.' } } })
  })
  return mocks
}

export async function fillTrip(page: Page) {
  await page.getByLabel('Origin', { exact: true }).fill('Denver, CO')
  await page.getByLabel('Destination', { exact: true }).fill('Salt Lake City, UT')
  await page.getByLabel('Time zone').selectOption('America/Denver')
}

export const apiPaths = (m: Mocks) => m.apiCalls.map((r) => new URL(r.url()).pathname)
