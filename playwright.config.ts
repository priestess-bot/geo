import os from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const localNoProxy = ["127.0.0.1", "localhost", "::1"];
const configuredNoProxy = (process.env.NO_PROXY || process.env.no_proxy || "")
  .split(",")
  .map((entry) => entry.trim())
  .filter(Boolean);
const noProxy = Array.from(new Set([...configuredNoProxy, ...localNoProxy])).join(",");
process.env.NO_PROXY = noProxy;
process.env.no_proxy = noProxy;

const configuredAdminBaseUrl = process.env.PLAYWRIGHT_ADMIN_BASE_URL?.trim();
const adminBaseUrl = configuredAdminBaseUrl || "http://127.0.0.1:3100";
const fixtureApiBaseUrl = process.env.PLAYWRIGHT_FIXTURE_API_URL?.trim()
  || "http://127.0.0.1:3199";
const fixtureApiPort = new URL(fixtureApiBaseUrl).port || "3199";
const nextDistDir = process.env.PLAYWRIGHT_NEXT_DIST_DIR?.trim()
  || ".next-playwright";

export default defineConfig({
  testDir: "./tests/browser",
  testIgnore: "customer-geo-portal.spec.ts",
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR
    || path.join(os.tmpdir(), `geo-playwright-output-${process.pid}`),
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "line",
  timeout: 30_000,
  expect: {
    timeout: 10_000
  },
  use: {
    baseURL: adminBaseUrl,
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off"
  },
  projects: [
    {
      name: "chromium-desktop",
      use: {
        ...devices["Desktop Chrome"]
      }
    }
  ],
  webServer: configuredAdminBaseUrl
    ? undefined
    : [
        {
          command: `GEO_BROWSER_FIXTURE_PORT=${fixtureApiPort} node tests/browser/fixtures/admin-geo-api.mjs`,
          url: `${fixtureApiBaseUrl}/health`,
          reuseExistingServer: false,
          timeout: 30_000
        },
        {
          command: `NEXT_DIST_DIR=${nextDistDir} API_INTERNAL_BASE_URL=${fixtureApiBaseUrl} GEO_AUTH_MODE=development corepack pnpm --filter geo-production-admin-web exec next dev -H 127.0.0.1 -p 3100`,
          url: adminBaseUrl,
          reuseExistingServer: false,
          timeout: 120_000
        }
      ]
});
