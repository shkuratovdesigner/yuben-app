import { defineConfig, devices } from '@playwright/test';

const desktop = { viewport: { width: 1440, height: 900 } };
const mobile = { viewport: { width: 390, height: 844 }, hasTouch: true };

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 30_000,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:5289' },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5289',
    reuseExistingServer: true,
  },
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'], ...desktop }, grep: /@desktop|@all/ },
    { name: 'webkit-desktop', use: { ...devices['Desktop Safari'], ...desktop }, grep: /@desktop|@all/ },
    { name: 'chromium-mobile', use: { ...devices['Pixel 7'], ...mobile }, grep: /@mobile|@all/ },
    { name: 'webkit-mobile', use: { ...devices['iPhone 14'], ...mobile }, grep: /@mobile|@all/ },
  ],
});
