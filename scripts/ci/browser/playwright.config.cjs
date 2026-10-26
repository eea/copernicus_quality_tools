const { defineConfig, devices } = require('@playwright/test');
const path = require('node:path');

if (!process.env.QC_TOOL_BROWSER_BASE_URL || !process.env.QC_TOOL_BROWSER_FIXTURES ||
    !process.env.QC_TOOL_BROWSER_ARTIFACTS_DIR) {
  throw new Error('Run browser smoke tests through scripts/ci/browser/run.sh.');
}

module.exports = defineConfig({
  testDir: __dirname,
  testMatch: 'uploads.spec.cjs',
  // All projects share one deliberately small SQLite frontend. Each journey
  // owns its product and delivery; serialization also avoids SQLite contention.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  outputDir: path.join(process.env.QC_TOOL_BROWSER_ARTIFACTS_DIR, 'test-results'),
  reporter: [['list'], ['junit', {
    outputFile: path.join(process.env.QC_TOOL_BROWSER_ARTIFACTS_DIR, 'results.xml'),
  }]],
  use: {
    baseURL: process.env.QC_TOOL_BROWSER_BASE_URL,
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
  ],
});
