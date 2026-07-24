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

const configuredAdminBaseUrl = process.env.PLAYWRIGHT_WORKFLOW_C_ADMIN_URL?.trim();
const adminServerPort = localPort("PLAYWRIGHT_WORKFLOW_C_SERVER_PORT", "3200");
const adminBaseUrl = configuredAdminBaseUrl || `http://127.0.0.1:${adminServerPort}`;
const fixtureBaseUrl = process.env.PLAYWRIGHT_WORKFLOW_C_FIXTURE_URL?.trim()
  || "http://127.0.0.1:3299";
const fixturePort = new URL(fixtureBaseUrl).port || "3299";

export default defineConfig({
  testDir: "./tests/browser",
  testMatch: "admin-workflow-c.spec.ts",
  outputDir: path.join(os.tmpdir(), `geo-workflow-c-playwright-${process.pid}`),
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: "line",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: adminBaseUrl,
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off"
  },
  projects: [{
    name: "chromium-workflow-c",
    use: { ...devices["Desktop Chrome"] }
  }],
  webServer: configuredAdminBaseUrl ? undefined : [
    {
      command: `GEO_WORKFLOW_C_FIXTURE_PORT=${fixturePort} node tests/browser/fixtures/workflow-c-api.mjs`,
      url: `${fixtureBaseUrl}/health`,
      reuseExistingServer: false,
      timeout: 30_000
    },
    {
      command: `NEXT_DIST_DIR=.next-workflow-c-playwright API_INTERNAL_BASE_URL=${fixtureBaseUrl} GEO_AUTH_MODE=development GEO_ADMIN_ACTOR_ID=workflow-c-owner GEO_ADMIN_TENANT_ID=00000000-0000-4000-8000-000000000002 corepack pnpm --filter geo-production-admin-web exec next dev -H 127.0.0.1 -p ${adminServerPort}`,
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
