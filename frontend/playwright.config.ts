import { defineConfig, devices } from '@playwright/test'

// E2E (T4) + accessibility (I4). Fully offline: the app is pointed at fake API and map
// hosts, and every request to them is answered by page.route() from recorded fixtures.
const PORT = 5174

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  // One browser at a time: each page needs two software (SwiftShader) WebGL contexts.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    viewport: { width: 1280, height: 800 },
    timezoneId: 'America/Denver',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
        // MapLibre needs WebGL; headless Chromium provides it through SwiftShader.
        launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
      },
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    env: {
      VITE_API_BASE_URL: 'http://api.test',
      VITE_MAP_STYLE_URL: 'http://tiles.test/style.json',
    },
  },
})
