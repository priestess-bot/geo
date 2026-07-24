import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_WORKFLOW_C_FIXTURE_URL || "http://127.0.0.1:3299";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const SUITE_ID = "00000000-0000-4000-8000-000000000701";
const RUN_ID = "00000000-0000-4000-8000-000000000702";
const ALERT_ID = "00000000-0000-4000-8000-000000000703";
const METRIC_HASH = "a".repeat(64);
const COMPARISON_HASH = "b".repeat(64);
const DRIFT_HASH = "c".repeat(64);

function workspaceUrl(view = "overview"): string {
  const query = new URLSearchParams({
    workflow_view: view,
    suite_id: SUITE_ID,
    run_id: RUN_ID,
    metric_snapshot: METRIC_HASH,
    comparison_family: COMPARISON_HASH,
    drift_report: DRIFT_HASH,
    alert_id: ALERT_ID
  });
  return `/projects/${PROJECT_ID}/workflow-c?${query.toString()}`;
}

function embeddedWorkspaceUrl(): string {
  const url = new URL(workspaceUrl(), "http://fixture.local");
  url.pathname = `/projects/${PROJECT_ID}`;
  url.searchParams.set("tab", "measurement");
  return `${url.pathname}?${url.searchParams.toString()}`;
}

function collectRuntimeErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

async function resetFixture(request: APIRequestContext): Promise<void> {
  expect((await request.delete(`${FIXTURE_API}/__requests`)).ok()).toBe(true);
}

async function openView(page: Page, name: string): Promise<void> {
  await page.getByRole("link", { name, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`workflow_view=${viewKey(name)}`));
}

function viewKey(name: string): string {
  const views: Record<string, string> = {
    "总览": "overview",
    "采样": "sampling",
    "指标": "metrics",
    "比较": "comparisons",
    "漂移": "drift",
    "告警": "alerts"
  };
  return views[name] || "overview";
}

async function submitAlertCommand(page: Page, buttonName: string, reason: string): Promise<void> {
  const button = page.getByRole("button", { name: buttonName, exact: true });
  const form = page.locator("form").filter({ has: button });
  await form.getByLabel(buttonName === "抑制" ? "抑制原因" : "处置原因").fill(reason);
  await button.click();
}

test.beforeEach(async ({ request }) => resetFixture(request));

test("M4-WORKFLOW-C-WEB-00: project workbench embeds one semantic measurement panel", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(embeddedWorkspaceUrl());

  await expect(page).toHaveTitle("GEO 项目管理台");
  await expect(page.getByRole("heading", { level: 1, name: "Workflow C Browser Fixture" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Sampling, Evidence & Alerts" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Measurement & Alerts" })).toHaveClass(/active/);
  await expect(page.locator("main")).toHaveCount(1);
  await expect(page.getByText("Planned", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "采样", exact: true })).toHaveAttribute("href", /\/workflow-c\?/);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("workflow-c-embedded-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { level: 2, name: "Sampling, Evidence & Alerts" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("workflow-c-embedded-mobile.png"), fullPage: true });
});

test("M4-WORKFLOW-C-WEB-01: fixed denominator and five-state evidence stay explainable", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(workspaceUrl());

  await expect(page).toHaveTitle("GEO 项目管理台");
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT_ID}/workflow-c`));
  await expect(page.getByRole("heading", { level: 1, name: "Sampling, Evidence & Alerts" })).toBeVisible();
  await expect(page.locator("[data-nextjs-dialog-overlay]")).toHaveCount(0);
  await expect(page.getByText("Planned", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("10", { exact: true }).first()).toBeVisible();

  await openView(page, "采样");
  await expect(page.getByText("Evidence complete", { exact: true })).toBeVisible();
  await expect(page.getByText("Provider API", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Denominator SHA-256", { exact: true })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Automated UI");
  await expect(page.locator("body")).not.toContainText("lease_token");

  await openView(page, "指标");
  await expect(page.getByText("Mean negative gain", { exact: true })).toBeVisible();
  await expect(page.getByText("Worst question", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Metric evidence", { exact: true })).toBeVisible();
  await expect(page.getByText("metric-judge-release-v3", { exact: true })).toBeVisible();

  await openView(page, "比较");
  await expect(page.getByText("达到等效门槛", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("不确定", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("证据不足", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("胜出", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("负向", { exact: true }).first()).toBeVisible();

  await openView(page, "漂移");
  await expect(page.getByRole("heading", { name: "Model drift", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Source composition drift", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Effect drift", exact: true })).toBeVisible();
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("workflow-c-evidence-desktop.png"), fullPage: true });
});

test("M4-WORKFLOW-C-WEB-02: alert inbox records all dispositions and notification projections", async ({ page, request }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(workspaceUrl("alerts"));

  await expect(page.getByRole("heading", { name: "negative-gain-worst-question" })).toBeVisible();
  await expect(page.getByText("Admin inbox", { exact: true })).toBeVisible();
  await expect(page.getByText("Local SMTP", { exact: true })).toBeVisible();
  await expect(page.getByText("Internal Webhook", { exact: true })).toBeVisible();

  await submitAlertCommand(page, "确认", "triage owner confirmed the frozen evidence");
  await expect(page.getByText("acknowledged", { exact: true }).first()).toBeVisible();
  await submitAlertCommand(page, "抑制", "planned investigation window");
  await expect(page.getByText("suppressed", { exact: true }).first()).toBeVisible();
  await submitAlertCommand(page, "解除抑制", "investigation window completed");
  await expect(page.getByText("acknowledged", { exact: true }).first()).toBeVisible();
  await submitAlertCommand(page, "解决", "root cause and follow-up evidence recorded");
  await expect(page.getByText("resolved", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("acknowledge", { exact: true })).toBeVisible();
  await expect(page.getByText("unsuppress", { exact: true })).toBeVisible();
  await expect(page.getByText("root cause and follow-up evidence recorded", { exact: true })).toBeVisible();

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json();
  const commandRequests = logged.filter((item: { method: string; path: string }) => (
    item.method === "POST" && item.path.includes(`/alerts/${ALERT_ID}/`)
  ));
  expect(commandRequests).toHaveLength(4);
  expect(commandRequests.every((item: { idempotency_key: string | null }) => Boolean(item.idempotency_key))).toBe(true);
  expect(logged.filter((item: { path: string }) => item.path === "/v1/auth/me").length).toBeGreaterThanOrEqual(5);
  expect(runtimeErrors).toEqual([]);

  await page.screenshot({ path: testInfo.outputPath("workflow-c-alerts-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(workspaceUrl("sampling"));
  await expect(page.getByText("Evidence complete", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("workflow-c-sampling-mobile.png"), fullPage: true });
});
