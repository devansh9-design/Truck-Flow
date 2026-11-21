// Upgrade 2 (non-core): saved trips, unit toggle, weather alerts, mobile layout.
// None of these may change a core result: the tests check that too.
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { ANALYZE, apiPaths, fillTrip, mockBackend } from './support.ts'

const recommended = ANALYZE.routes.find((r: { recommended: boolean }) => r.recommended)
const cards = (page: Page) => page.locator('[data-testid^="route-card-"]')

async function analyze(page: Page) {
  await fillTrip(page)
  await page.getByRole('button', { name: 'Compare routes' }).click()
  await expect(cards(page)).toHaveCount(3)
}

test.describe('P3-4 saved trips', () => {
  test('save → reload → listed → reopen re-runs the analysis', async ({ page }) => {
    const mocks = await mockBackend(page)
    await page.goto('/')
    await analyze(page)
    await page.getByRole('button', { name: /Save trip/ }).click()
    await expect(page.getByRole('button', { name: /Trip saved/ })).toBeDisabled()

    await page.reload()
    const saved = page.getByTestId('saved-trips')
    await expect(saved).toContainText('Saved trips (1)')
    await saved.locator('summary').click()
    await expect(saved).toContainText(ANALYZE.trip.origin.label)

    const analyzeCalls = () => apiPaths(mocks).filter((p) => p === '/api/analyze').length
    const before = analyzeCalls()
    await saved.getByRole('button', { name: /^Reopen / }).click()
    await expect(cards(page)).toHaveCount(3)
    expect(analyzeCalls()).toBe(before + 1)
    // Reopening sends the resolved places (no re-geocoding) and refills the form.
    const body = mocks.apiCalls
      .filter((r) => r.url().endsWith('/api/analyze'))
      .at(-1)!
      .postDataJSON()
    expect(body.origin).toEqual(ANALYZE.trip.origin)
    await expect(page.getByLabel('Origin', { exact: true })).toHaveValue(ANALYZE.trip.origin.label)

    await saved.getByRole('button', { name: /^Delete saved trip / }).click()
    await expect(saved).toHaveCount(0)
    await page.reload()
    await expect(page.getByTestId('saved-trips')).toHaveCount(0)
  })
})

test.describe('P3-2 unit toggle', () => {
  test('numbers switch to metric; order, recommendation and risk stay identical', async ({ page }) => {
    await mockBackend(page)
    await page.goto('/')
    await analyze(page)
    const order = () => cards(page).evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')))
    const markers = () =>
      page.getByTestId('checkpoint-marker').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')))
    const before = {
      order: await order(),
      rec: await page.getByTestId('recommendation').innerText(),
      markers: await markers(),
    }
    const card = page.getByTestId(`route-card-${recommended.id}`)
    await expect(card).toContainText(' mi')

    await page.getByRole('radio', { name: 'km', exact: true }).click()
    await expect(card).toContainText(' km')
    await expect(card).not.toContainText(/\d mi\b/)
    // The form and trip summary switch too: load in kg, checkpoint spacing in km.
    await expect(page.getByLabel('Load weight (kg)')).toHaveValue('19051')
    await expect(page.getByLabel('40 km')).toBeChecked()
    await expect(page.locator('section[aria-label="Trip"]')).not.toContainText(/\d (mi|lb)\b/)
    expect(await order()).toEqual(before.order)
    expect(await page.getByTestId('recommendation').innerText()).toBe(before.rec)
    expect(await markers()).toEqual(before.markers)

    await page.reload()
    await expect(page.getByRole('radio', { name: 'km', exact: true })).toHaveAttribute('aria-checked', 'true')
  })
})

test.describe('P3-3 weather alerts', () => {
  test('US trip: listed in the panel and badged on the map; ranking unchanged', async ({ page }) => {
    const mocks = await mockBackend(page)
    await page.goto('/')
    await analyze(page)
    const panel = page.getByTestId('alerts-panel')
    await expect(panel).toContainText('Weather alerts (1)')
    await expect(panel.getByTestId('alert-item')).toContainText('High Wind Warning')
    await expect(panel.getByTestId('alert-item')).toContainText('Severe')
    const badge = page.getByTestId('alert-badge')
    await expect(badge).toHaveCount(1)
    await expect(badge).toHaveAttribute('aria-label', /High Wind Warning/)
    await badge.click()
    await expect(page.locator('.maplibregl-popup')).toContainText('Weather alerts (NWS)')
    await expect(page.getByTestId('recommendation')).toContainText(`Take ${recommended.label}`)

    const sent = mocks.apiCalls.find((r) => r.url().endsWith('/api/alerts'))!.postDataJSON()
    expect(sent.points.length).toBeGreaterThan(1)
    expect(sent.points.length).toBeLessThanOrEqual(100)
  })

  test('non-US trip: panel says alerts are not available for this region', async ({ page }) => {
    const mocks = await mockBackend(page)
    mocks.alerts = { alerts: [], coverage: 'unsupported_region' }
    await page.goto('/')
    await analyze(page)
    await expect(page.getByTestId('alerts-panel')).toContainText('not available for this region')
    await expect(page.getByTestId('alert-badge')).toHaveCount(0)
  })
})

test.describe('P3-1 mobile (360 px)', () => {
  test.use({ viewport: { width: 360, height: 740 }, hasTouch: true, isMobile: true })

  test('bottom sheet with form, then results with map, slider and no sideways scroll', async ({ page }) => {
    await mockBackend(page)
    await page.goto('/')
    const panel = page.getByTestId('panel')
    await expect(panel).toHaveAttribute('data-snap', 'full')
    await analyze(page)
    await expect(panel).toHaveAttribute('data-snap', 'half')
    await expect(page.getByTestId('recommendation')).toBeInViewport()

    const slider = page.getByRole('slider', { name: 'Forecast hour after departure' })
    await expect(slider).toBeEnabled()
    await expect(slider).toBeInViewport()
    await page.getByRole('button', { name: 'Next hour' }).tap()
    await expect(slider).toHaveValue('1')
    expect((await slider.boundingBox())!.height).toBeGreaterThanOrEqual(40) // touch-sized hit area

    const handle = page.getByTestId('sheet-handle')
    await handle.tap()
    await expect(panel).toHaveAttribute('data-snap', 'full')
    await handle.tap()
    await expect(panel).toHaveAttribute('data-snap', 'peek')

    expect(await page.evaluate<number>('document.documentElement.scrollWidth')).toBeLessThanOrEqual(360)
    const { violations } = await new AxeBuilder({ page }).analyze()
    const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([])
  })
})
