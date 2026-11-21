import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { ANALYZE, apiPaths, fillTrip, mockBackend } from './support.ts'

const recommended = ANALYZE.routes.find((r: { recommended: boolean }) => r.recommended)

test.describe('CORE-5: routes, checkpoints, risk, ETAs and summaries', () => {
  test('one submit shows 3 routes, every checkpoint with risk and ETA, and the cards', async ({ page }) => {
    const mocks = await mockBackend(page)
    await page.goto('/')
    await expect(page.getByRole('status').filter({ hasText: 'Services ready' })).toBeVisible()

    await fillTrip(page)
    await page.getByRole('button', { name: 'Compare routes' }).click()

    // Three summary cards, recommended one marked, with the deciding key.
    await expect(page.locator('[data-testid^="route-card-"]')).toHaveCount(3)
    await expect(page.getByTestId(`route-card-${recommended.id}`)).toContainText('Recommended')
    await expect(page.getByTestId('recommendation')).toContainText(`Take ${recommended.label}`)

    // Every checkpoint of the selected route is a labelled marker (risk + ETA in its name)
    // and a row in the list with its risk level as text.
    const markers = page.getByTestId('checkpoint-marker')
    await expect(markers).toHaveCount(recommended.checkpoints.length)
    await expect(markers.first()).toHaveAttribute('aria-label', /risk, ETA /)
    const rows = page
      .getByRole('heading', { name: /checkpoints/ })
      .locator('xpath=..')
      .getByRole('listitem')
    await expect(rows).toHaveCount(recommended.checkpoints.length)

    // A checkpoint popup shows ETA, forecast hour and the reason.
    await markers.nth(1).click()
    const popup = page.locator('.maplibregl-popup')
    await expect(popup).toContainText('ETA')
    await expect(popup).toContainText('Forecast')
    await expect(popup).toContainText(recommended.checkpoints[1].risk.reason)

    // Selecting another route shows its checkpoints.
    const other = ANALYZE.routes.find((r: { recommended: boolean }) => !r.recommended)
    await page.getByTestId(`route-card-${other.id}`).click()
    await expect(
      page.getByRole('heading', { name: `${other.label} checkpoints (${other.checkpoints.length})` }),
    ).toBeVisible()
    await expect(markers).toHaveCount(other.checkpoints.length)

    expect(apiPaths(mocks).filter((p) => p === '/api/analyze')).toHaveLength(1)
  })
})

test.describe('CORE-6: heatmap with a 0–48 h slider', () => {
  test('slider moves 0 → 48 with the keyboard and never refetches', async ({ page }) => {
    const mocks = await mockBackend(page)
    await page.goto('/')
    await fillTrip(page)
    await page.getByRole('button', { name: 'Compare routes' }).click()

    const slider = page.getByRole('slider', { name: 'Forecast hour after departure' })
    await expect(slider).toBeEnabled()
    await expect(page.getByText('Departure hour')).toBeVisible()
    const heatmapCalls = () => apiPaths(mocks).filter((p) => p === '/api/heatmap').length
    expect(heatmapCalls()).toBe(1)
    const callsBefore = mocks.apiCalls.length

    await slider.focus()
    await page.keyboard.press('ArrowRight')
    await expect(slider).toHaveValue('1')
    await page.keyboard.press('PageUp')
    await expect(slider).toHaveValue('7')
    await expect(slider).toHaveAttribute('aria-valuetext', /^7 hours after departure, /)
    await page.keyboard.press('End')
    await expect(slider).toHaveValue('48')
    await expect(page.getByText('+48 h')).toBeVisible()
    await page.keyboard.press('PageDown')
    await expect(slider).toHaveValue('42')
    await page.keyboard.press('Home')
    await expect(slider).toHaveValue('0')

    // Variables switch without any request either.
    await page.getByRole('radio', { name: 'Snow' }).click()
    await page.getByRole('radio', { name: 'Wind' }).click()

    expect(mocks.apiCalls.length).toBe(callsBefore) // no network calls while scrubbing (NFR-2)
  })
})

test.describe('Errors', () => {
  test('a failed analysis shows a banner with Try again, and the map stays', async ({ page }) => {
    const mocks = await mockBackend(page)
    mocks.analyzeStatus = 502
    await page.goto('/')
    await fillTrip(page)
    await page.getByRole('button', { name: 'Compare routes' }).click()

    const alert = page.getByRole('alert').filter({ hasText: "Couldn't analyze this trip" })
    await expect(alert).toContainText('unavailable right now')
    await expect(page.locator('.maplibregl-canvas')).toBeVisible() // no blank screen
    await expect(page.locator('[data-testid^="route-card-"]')).toHaveCount(0) // never partial

    mocks.analyzeStatus = 200
    await alert.getByRole('button', { name: 'Try again' }).click()
    await expect(page.locator('[data-testid^="route-card-"]')).toHaveCount(3)
    await expect(alert).toBeHidden()
  })

  test('input problems are shown on the form, not as a retryable outage', async ({ page }) => {
    await mockBackend(page)
    await page.goto('/')
    await page.getByLabel('Origin', { exact: true }).fill('Denver')
    await page.getByLabel('Destination', { exact: true }).fill('denver')
    await page.getByRole('button', { name: 'Compare routes' }).click()
    await expect(page.getByText('Destination must differ from the origin.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0)
  })
})

test.describe('Accessibility (I4)', () => {
  const serious = (v: { impact?: string | null }) => v.impact === 'serious' || v.impact === 'critical'

  test('start screen has no serious or critical axe violations', async ({ page }) => {
    await mockBackend(page)
    await page.goto('/')
    await expect(page.getByRole('status').filter({ hasText: 'Services ready' })).toBeVisible()
    const { violations } = await new AxeBuilder({ page }).analyze()
    expect(violations.filter(serious).map((v) => `${v.id}: ${v.help}`)).toEqual([])
  })

  test('results screen has no serious or critical axe violations', async ({ page }) => {
    await mockBackend(page)
    await page.goto('/')
    await fillTrip(page)
    await page.getByRole('button', { name: 'Compare routes' }).click()
    await expect(page.locator('[data-testid^="route-card-"]')).toHaveCount(3)
    await expect(page.getByRole('slider', { name: 'Forecast hour after departure' })).toBeEnabled()
    const { violations } = await new AxeBuilder({ page }).analyze()
    expect(violations.filter(serious).map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([])
  })

  test('keyboard only: fill the form and submit with Enter', async ({ page }) => {
    await mockBackend(page)
    await page.goto('/')
    await page.getByLabel('Origin', { exact: true }).focus()
    await page.keyboard.type('Denver, CO')
    await page.keyboard.press('Tab') // swap button
    await page.keyboard.press('Tab')
    await page.keyboard.type('Salt Lake City, UT')
    await page.keyboard.press('Enter')
    await expect(page.locator('[data-testid^="route-card-"]')).toHaveCount(3)
    // Route cards are reachable and selectable with the keyboard.
    const card = page.locator('[data-testid^="route-card-"]').nth(1)
    await card.focus()
    await page.keyboard.press('Enter')
    await expect(card).toHaveAttribute('aria-pressed', 'true')
  })
})
