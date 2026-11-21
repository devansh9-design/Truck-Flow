// A10: suggestions while typing, with an optional country filter. Picking one sends exact
// coordinates; typing free text still works (server geocodes it).
import { expect, test } from '@playwright/test'
import { mockBackend } from './support.ts'

test('typing "B" suggests places; picking one sends exact coordinates', async ({ page }) => {
  const mocks = await mockBackend(page)
  await page.goto('/')
  const dest = page.getByRole('combobox', { name: 'Destination', exact: true })
  await dest.fill('B')
  const list = page.getByRole('listbox', { name: 'Destination suggestions' })
  await expect(list.getByRole('option')).toHaveCount(2) // Barcelona and Barcelos
  await expect(dest).toHaveAttribute('aria-expanded', 'true')

  // Keyboard: ArrowDown highlights, Enter picks (and does not submit the form).
  await dest.press('ArrowDown')
  await expect(list.getByRole('option').first()).toHaveAttribute('aria-selected', 'true')
  await dest.press('Enter')
  await expect(dest).toHaveValue('Barcelona, Catalonia, Spain')
  await expect(page.getByText('✓ Exact location selected')).toBeVisible()

  await page.getByRole('combobox', { name: 'Origin', exact: true }).fill('Denv')
  await page.getByRole('option', { name: 'Denver, CO, United States' }).click()
  await page.getByRole('button', { name: 'Compare routes' }).click()
  await expect(page.locator('[data-testid^="route-card-"]')).toHaveCount(3)
  const body = mocks.apiCalls.find((r) => r.url().endsWith('/api/analyze'))!.postDataJSON()
  expect(body.destination).toEqual({ label: 'Barcelona, Catalonia, Spain', lat: 41.38804, lon: 2.17001 })
  expect(body.origin).toEqual({ label: 'Denver, CO, United States', lat: 39.74, lon: -104.99 })
})

test('country filter narrows suggestions; typing again clears the exact place', async ({ page }) => {
  const mocks = await mockBackend(page)
  await page.goto('/')
  await page.getByLabel('Search destination in').selectOption('PT')
  const dest = page.getByRole('combobox', { name: 'Destination', exact: true })
  await dest.fill('Bar')
  const options = page.getByRole('listbox', { name: 'Destination suggestions' }).getByRole('option')
  await expect(options).toHaveCount(1)
  await expect(options.first()).toHaveText('Barcelos, Portugal')
  const sent = mocks.apiCalls.filter((r) => r.url().includes('/api/places/suggest')).at(-1)!
  expect(new URL(sent.url()).searchParams.get('country')).toBe('PT')

  await options.first().click()
  await expect(page.getByText('✓ Exact location selected')).toBeVisible()
  await dest.fill('Barcelos, Braga')
  await expect(page.getByText('✓ Exact location selected')).toHaveCount(0)
  await expect(dest).toHaveAttribute('aria-expanded', 'false') // no match in the mock: list closes

  await dest.press('Escape')
})

test('signed-in users get their profile country as the default filter', async ({ page }) => {
  const mocks = await mockBackend(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Sign in' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('tab', { name: 'Create account' }).click()
  await dialog.getByLabel('Name').fill('Ana Ruiz')
  await dialog.getByLabel('Email').fill('ana@example.test')
  await dialog.getByLabel('Password').fill('lorry-weather-42')
  await dialog.getByLabel('Country').selectOption('ES')
  await dialog.locator('form').getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByTestId('account-menu')).toBeVisible()
  await expect(page.getByLabel('Search origin in')).toHaveValue('ES')
  await expect(page.getByLabel('Search destination in')).toHaveValue('ES')
  await page.getByRole('combobox', { name: 'Origin', exact: true }).fill('Bar')
  const options = page.getByRole('listbox', { name: 'Origin suggestions' }).getByRole('option')
  await expect(options).toHaveCount(1)
  await expect(options.first()).toHaveText('Barcelona, Catalonia, Spain') // Spain only
  expect(mocks.account.token).not.toBeNull()
})
