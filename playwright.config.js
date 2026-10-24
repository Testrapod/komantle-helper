import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/web',
  testMatch: '*.spec.js',
  fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:4173/komantle-helper/', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'python3 -m scripts.serve_preview --directory .preview',
    url: 'http://127.0.0.1:4173/komantle-helper/',
    reuseExistingServer: !process.env.CI,
  },
});
