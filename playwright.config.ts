import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir: './tests/e2e', timeout: 7200_000, expect: {timeout: 15_000}, retries: 0, workers: 1,
  reporter: [['list'], ['html', {open: 'never'}]],
  use: {baseURL: 'http://127.0.0.1:8000', channel: 'chromium', launchOptions: {chromiumSandbox: true},
    trace: 'retain-on-failure', screenshot: 'only-on-failure', acceptDownloads: true},
});
