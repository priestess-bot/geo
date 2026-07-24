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

const configuredWebBaseUrl = process.env.PLAYWRIGHT_CUSTOMER_BASE_URL?.trim();
const customerServerPort = localPort("PLAYWRIGHT_CUSTOMER_SERVER_PORT", "3101");
const webBaseUrl = configuredWebBaseUrl || `http://127.0.0.1:${customerServerPort}`;
const apiBaseUrl = process.env.PLAYWRIGHT_CUSTOMER_FIXTURE_API_URL?.trim()
  || "http://127.0.0.1:3198";
const apiPort = new URL(apiBaseUrl).port || "3198";

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "customer-geo-portal.spec.ts",
  outputDir: path.join(os.tmpdir(), `geo-customer-playwright-${process.pid}`),
  fullyParallel: false,
  reporter: "line",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: webBaseUrl,
    navigationTimeout: 15_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure"
  },
  projects: [
    { name: "customer-desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "customer-mobile",
      use: { ...devices["iPhone 13"], browserName: "chromium" }
    }
  ],
  webServer: configuredWebBaseUrl
    ? undefined
    : [
        {
          command: `GEO_CUSTOMER_FIXTURE_PORT=${apiPort} node tests/browser/fixtures/customer-geo-api.mjs`,
          url: `${apiBaseUrl}/health`,
          reuseExistingServer: false,
          timeout: 30_000
        },
        {
          command: `API_CUSTOMER_BASE_URL=${apiBaseUrl} corepack pnpm --filter geo-production-customer-web exec next dev -H 127.0.0.1 -p ${customerServerPort}`,
          url: webBaseUrl,
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
