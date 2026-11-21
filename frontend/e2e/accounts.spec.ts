// Accounts (A6-A9): optional sign-in. Guests keep full use of the app; an account adds a
// profile country and saved trips on the server. Routes and risk never change.
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { ANALYZE, fillTrip, mockBackend } from './support.ts'

const cards = (page: Page) => page.locator('[data-testid^="route-card-"]')

async function createAccount(page: Page, country = 'ES') {
  await page.getByRole('button', { name: 'Sign in' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('tab', { name: 'Create account' }).click()
  await dialog.getByLabel('Name').fill('Ana Ruiz')
  await dialog.getByLabel('Email').fill('ana@example.test')
  await dialog.getByLabel('Password').fill('lorry-weather-42')
  await dialog.getByLabel('Country').selectOption(country)
  await dialog.locator('form').getByRole('button', { name: 'Create account' }).click()
}

test('guests can analyze without an account', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/')
  await fillTrip(page)
  await page.getByRole('button', { name: 'Compare routes' }).click()
  await expect(cards(page)).toHaveCount(3)
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})

test('sign up: profile country, metric units, browser trips move to the account, survives reload', async ({ page }) => {
  const mocks = await mockBackend(page)
  await page.goto('/')
  await fillTrip(page)
  await page.getByRole('button', { name: 'Compare routes' }).click()
  await page.getByRole('button', { name: /Save trip/ }).click() // saved in this browser as a guest

  await createAccount(page)
  await expect(page.getByRole('status').filter({ hasText: 'Moved 1 saved trip' })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(mocks.account.trips).toHaveLength(1)
  expect(mocks.account.trips[0]).toMatchObject({ origin: ANALYZE.trip.origin })
  await expect(page.getByRole('radio', { name: 'km', exact: true })).toHaveAttribute('aria-checked', 'true')

  const menu = page.getByTestId('account-menu')
  await menu.locator('summary').click()
  await expect(menu).toContainText('Spain · Europe')

  await page.reload()
  await expect(page.getByTestId('account-menu')).toBeVisible()
  await expect(page.getByTestId('saved-trips')).toContainText('Your saved trips (1)')
  const signedInRequest = mocks.apiCalls.find((r) => r.url().endsWith('/api/trips') && r.method() === 'GET')!
  expect(signedInRequest.headers()['authorization']).toMatch(/^Bearer /)
})

test('signed-in saves go to the server; sign out returns to guest; wrong password is refused', async ({ page }) => {
  const mocks = await mockBackend(page)
  await page.goto('/')
  await createAccount(page, 'US')
  await expect(page.getByTestId('account-menu')).toBeVisible()
  await expect(page.getByRole('radio', { name: 'mi', exact: true })).toHaveAttribute('aria-checked', 'true')

  await fillTrip(page)
  await page.getByRole('button', { name: 'Compare routes' }).click()
  await page.getByRole('button', { name: /Save trip/ }).click()
  await expect(page.getByRole('button', { name: /Trip saved/ })).toBeDisabled()
  expect(mocks.account.trips).toHaveLength(1)
  expect(await page.evaluate<string | null>("localStorage.getItem('truckrisk.savedTrips.v1')")).toBeNull()

  await page.getByTestId('account-menu').locator('summary').click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByTestId('saved-trips')).toHaveCount(0) // the account's trips are not shown to guests

  await page.getByRole('button', { name: 'Sign in' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Email').fill('ana@example.test')
  await dialog.getByLabel('Password').fill('wrong-password')
  await dialog.locator('form').getByRole('button', { name: 'Sign in' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Email or password is incorrect.')
  await dialog.getByLabel('Password').fill('lorry-weather-42')
  await dialog.locator('form').getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByTestId('saved-trips')).toContainText('Your saved trips (1)')
})

test('sign-in dialog has no serious or critical axe violations', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('dialog').getByRole('tab', { name: 'Create account' }).click()
  await expect(page.getByRole('dialog').getByLabel('Country')).toBeEnabled()
  const { violations } = await new AxeBuilder({ page }).analyze()
  const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([])
})
