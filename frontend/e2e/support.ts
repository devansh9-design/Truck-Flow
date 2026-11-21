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
}

/** Answer the fake API and map hosts from fixtures. Change `analyzeStatus` to simulate errors. */
export async function mockBackend(page: Page): Promise<Mocks> {
  const mocks: Mocks = { apiCalls: [], analyzeStatus: 200, alerts: ALERTS }
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
