import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const suites = [
  {
    label: "Admin Chromium desktop",
    args: ["--config=playwright.config.ts", "--project=chromium-desktop", "--workers=1"]
  },
  {
    label: "Customer Chromium desktop",
    args: ["--config=playwright.customer.config.ts", "--project=customer-desktop", "--workers=1"]
  },
  {
    label: "Workflow C Chromium desktop",
    args: ["--config=playwright.workflow-c.config.ts", "--project=chromium-workflow-c", "--workers=1"]
  }
];

export function verifyRequiredReport(report, label) {
  const stats = report?.stats;
  if (!stats || typeof stats !== "object") {
    throw new Error(`${label}: Playwright JSON report has no stats`);
  }
  const counts = ["expected", "skipped", "unexpected", "flaky"].map((name) => {
    const value = stats[name];
    if (!Number.isInteger(value) || value < 0) {
      throw new Error(`${label}: Playwright JSON report has an invalid ${name} count`);
    }
    return value;
  });
  const collected = counts.reduce((total, value) => total + value, 0);
  if (collected === 0) {
    throw new Error(`${label}: zero tests were collected`);
  }
  if (stats.skipped !== 0) {
    throw new Error(`${label}: ${stats.skipped} required tests were skipped`);
  }
  if (stats.unexpected !== 0) {
    throw new Error(`${label}: ${stats.unexpected} required tests failed`);
  }
  return { collected, passed: stats.expected, flaky: stats.flaky };
}

function verifyReportFile(reportPath, label) {
  return verifyRequiredReport(JSON.parse(readFileSync(reportPath, "utf8")), label);
}

function runSuite(suite, temporaryDirectory) {
  const reportPath = path.join(
    temporaryDirectory,
    `${suite.label.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}.json`
  );
  const result = spawnSync(
    "corepack",
    [
      "pnpm",
      "exec",
      "playwright",
      "test",
      ...suite.args,
      "--reporter=line,json"
    ],
    {
      cwd: process.cwd(),
      env: { ...process.env, PLAYWRIGHT_JSON_OUTPUT_NAME: reportPath },
      stdio: "inherit"
    }
  );
  if (result.error) {
    throw new Error(`${suite.label}: unable to start Playwright`);
  }
  const summary = verifyReportFile(reportPath, suite.label);
  if (result.status !== 0) {
    throw new Error(`${suite.label}: Playwright exited with status ${result.status}`);
  }
  process.stdout.write(
    `Required browser summary [${suite.label}]: collected=${summary.collected} `
      + `passed=${summary.passed} skipped=0 flaky=${summary.flaky}\n`
  );
}

function main() {
  if (process.argv[2] === "--verify-report") {
    const reportPath = process.argv[3];
    if (!reportPath) {
      throw new Error("--verify-report requires a JSON report path");
    }
    const summary = verifyReportFile(reportPath, "Required Chromium behavior test");
    process.stdout.write(`collected=${summary.collected} passed=${summary.passed}\n`);
    return;
  }
  const temporaryDirectory = mkdtempSync(path.join(os.tmpdir(), "geo-browser-gate-"));
  const adminNextEnvironment = path.join(
    process.cwd(),
    "apps",
    "admin-web",
    "next-env.d.ts"
  );
  const originalAdminNextEnvironment = readFileSync(adminNextEnvironment);
  try {
    for (const suite of suites) {
      runSuite(suite, temporaryDirectory);
    }
  } finally {
    writeFileSync(adminNextEnvironment, originalAdminNextEnvironment, { mode: 0o644 });
    rmSync(temporaryDirectory, { recursive: true, force: true });
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    main();
  } catch (error) {
    const message = error instanceof Error ? error.message : "unknown browser gate failure";
    process.stderr.write(`Required browser gate failed: ${message}\n`);
    process.exitCode = 1;
  }
}
