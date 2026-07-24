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
const adminServerPort = localPort("PLAYWRIGHT_ADMIN_SERVER_PORT", "3100");
const adminBaseUrl = configuredAdminBaseUrl || `http://127.0.0.1:${adminServerPort}`;
const fixtureApiBaseUrl = process.env.PLAYWRIGHT_FIXTURE_API_URL?.trim()
  || "http://127.0.0.1:3199";
const fixtureApiPort = new URL(fixtureApiBaseUrl).port || "3199";
const nextDistDir = process.env.PLAYWRIGHT_NEXT_DIST_DIR?.trim()
  || ".next-playwright";

export default defineConfig({
  testDir: "./tests/browser",
  // These surfaces need different fixture APIs and are exercised by their
  // dedicated Playwright configurations below the required browser gate.
  testIgnore: [
    "customer-geo-portal.spec.ts",
    "admin-workflow-c.spec.ts"
  ],
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR
    || path.join(os.tmpdir(), `geo-playwright-output-${process.pid}`),
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // The Admin browser specs deliberately share one mutable fixture API. Keep
  // its lifecycle serial so one spec cannot reset another spec's evidence.
  workers: 1,
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
          command: `NEXT_DIST_DIR=${nextDistDir} API_INTERNAL_BASE_URL=${fixtureApiBaseUrl} GEO_AUTH_MODE=development corepack pnpm --filter geo-production-admin-web exec next dev -H 127.0.0.1 -p ${adminServerPort}`,
          url: adminBaseUrl,
          reuseExistingServer: false,
          timeout: 120_000
        }
      ]
});

function localPort(name: string, fallback: string): string {
  const value = process.env[name]?.trim() || fallback;
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be a TCP port`);
  }
  return String(port);
}
