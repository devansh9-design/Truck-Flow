// Driving mode (D17): GPS position -> re-check from the truck's position -> warning when
// weather makes another route safer. GPS and the API are simulated.
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { ANALYZE, fillTrip, mockBackend, type Mocks } from './support.ts'

// Somewhere on the way out of Denver, far from Salt Lake City.
test.use({ geolocation: { latitude: 39.9, longitude: -105.1 }, permissions: ['geolocation'] })

const recommended = ANALYZE.routes.find((r: { recommended: boolean }) => r.recommended)
const safer = ANALYZE.routes.find((r: { id: string }) => r.id === 'r0')

/** The same routes, but a storm now puts 30 Severe miles on the recommended one. */
function stormOnRecommended() {
  const a = structuredClone(ANALYZE)
  for (const r of a.routes) {
    const hit = r.id === recommended.id
    r.recommended = r.id === safer.id
    if (hit) {
      r.summary.severe_mi = 30
      r.checkpoints[5].risk.level = 'SEVERE'
      r.checkpoints[5].risk.factors.wind = 'SEVERE'
    }
  }
  a.recommendation = { route_id: safer.id, decided_by: 'severe_mi', reason: 'Fewest Severe miles (0.0 vs 30.0).' }
  return a
}

async function startTrip(page: Page, recheckBody: unknown = stormOnRecommended()): Promise<Mocks> {
  const mocks = await mockBackend(page)
  await page.goto('/')
  await fillTrip(page)
  await page.getByRole('button', { name: 'Compare routes' }).click()
  await expect(page.locator('[data-testid^="route-card-"]')).toHaveCount(3)
  mocks.analyzeOverride = recheckBody
  await page.getByRole('button', { name: `▶ Start trip on ${recommended.label}` }).click()
  return mocks
}

test('weather turns bad on the route: warning offers the safer route; switching follows it', async ({ page }) => {
  const mocks = await startTrip(page)
  await expect(page.getByTestId('driving-bar')).toContainText(`Driving · ${recommended.label}`)
  await expect(page.getByTestId('you-marker')).toBeVisible()

  // The first GPS fix triggers a re-check from the truck's position.
  const warning = page.getByRole('alertdialog')
  await expect(warning).toBeVisible()
  await expect(warning).toContainText(`Safer route available: ${safer.label}`)
  await expect(warning).toContainText('30 mi of Severe conditions (strong wind)')
  await expect(warning).toContainText('Pull over safely before using the screen.')
  await expect(warning.getByRole('button', { name: `Switch to ${safer.label}` })).toBeFocused()
  const { violations } = await new AxeBuilder({ page }).analyze()
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([])

  const recheck = mocks.apiCalls
    .filter((r) => r.url().endsWith('/api/analyze'))
    .at(-1)!
    .postDataJSON()
  expect(recheck.origin).toEqual({ label: 'Current position', lat: 39.9, lon: -105.1 })
  expect(recheck.destination).toEqual(ANALYZE.trip.destination)
  expect(Date.now() - Date.parse(recheck.departure_time)).toBeLessThan(60_000)

  await warning.getByRole('button', { name: `Switch to ${safer.label}` }).click()
  await expect(warning).toHaveCount(0)
  await expect(page.getByTestId(`route-card-${safer.id}`)).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('driving-bar')).toContainText(`Driving · ${safer.label}`)
})

test('keep my route silences the same warning; ending the trip restores the plan', async ({ page }) => {
  const mocks = await startTrip(page)
  const warning = page.getByRole('alertdialog')
  await expect(warning).toBeVisible()
  await warning.getByRole('button', { name: 'Keep my route' }).click()
  await expect(warning).toHaveCount(0)

  const before = mocks.apiCalls.filter((r) => r.url().endsWith('/api/analyze')).length
  await page.getByRole('button', { name: 'Check now' }).click()
  await expect.poll(() => mocks.apiCalls.filter((r) => r.url().endsWith('/api/analyze')).length).toBe(before + 1)
  await expect(page.getByTestId('driving-bar')).toContainText('Last check just now')
  await expect(warning).toHaveCount(0) // same situation, dismissed: no repeat

  await page.getByRole('button', { name: 'End trip' }).click()
  await expect(page.getByTestId('driving-bar')).toHaveCount(0)
  await expect(page.getByTestId(`route-card-${recommended.id}`)).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: `▶ Start trip on ${recommended.label}` })).toBeVisible()
})

test('no warning when the weather has not changed', async ({ page }) => {
  const mocks = await startTrip(page, null) // re-checks return the same calm analysis
  await expect(page.getByTestId('driving-bar')).toContainText('Last check just now')
  const before = mocks.apiCalls.filter((r) => r.url().endsWith('/api/analyze')).length
  await page.getByRole('button', { name: 'Check now' }).click()
  await expect.poll(() => mocks.apiCalls.filter((r) => r.url().endsWith('/api/analyze')).length).toBe(before + 1)
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(page.getByTestId('driving-bar')).toContainText(`Driving · ${recommended.label}`)
})
