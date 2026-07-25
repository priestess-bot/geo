import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_WORKFLOW_C_FIXTURE_URL || "http://127.0.0.1:3299";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const SUITE_ID = "00000000-0000-4000-8000-000000000701";
const RUN_ID = "00000000-0000-4000-8000-000000000702";
const MANUAL_SUITE_ID = "00000000-0000-4000-8000-000000000750";
const MANUAL_RUN_ID = "00000000-0000-4000-8000-000000000751";
const AIO_PARSER_RELEASE_ID = "00000000-0000-4000-8000-000000000760";
const ALERT_ID = "00000000-0000-4000-8000-000000000703";
const METRIC_PROTOCOL_ID = "00000000-0000-4000-8000-000000000771";
const REPORT_ID = "00000000-0000-4000-8000-000000000774";
const CAMPAIGN_ID = "00000000-0000-4000-8000-000000000776";
const MONITORING_REPORT_ID = "00000000-0000-4000-8000-000000000777";
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

function manualWorkspaceUrl(): string {
  return `/projects/${PROJECT_ID}/workflow-c?${new URLSearchParams({
    workflow_view: "sampling",
    suite_id: MANUAL_SUITE_ID,
    run_id: MANUAL_RUN_ID
  }).toString()}`;
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
    "协议与任务": "protocols",
    "指标": "metrics",
    "比较": "comparisons",
    "漂移": "drift",
    "报告": "reports",
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

test("M4-WORKFLOW-C-WEB-03: protocols, durable jobs and reports complete maker-checker paths", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(workspaceUrl("protocols"));

  await expect(page.getByRole("heading", { name: "Analysis Protocols" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "分析任务" })).toBeVisible();
  const metricLifecycle = page.locator("div").filter({ hasText: METRIC_PROTOCOL_ID }).filter({
    has: page.getByRole("button", { name: "批准 Protocol" })
  }).last();
  await metricLifecycle.getByLabel("批准原因").fill("independent protocol review passed");
  await metricLifecycle.getByRole("button", { name: "批准 Protocol" }).click();
  await expect(page.locator("tr").filter({ hasText: METRIC_PROTOCOL_ID }).getByText("approved", { exact: true })).toBeVisible();

  const semanticButton = page.getByRole("button", { name: "入队 Semantic Metrics" });
  const semanticForm = page.locator("form").filter({ has: semanticButton });
  await semanticForm.getByLabel("Sampling Run").selectOption(RUN_ID);
  await semanticForm.getByLabel("Approved Metric Protocol").selectOption(METRIC_PROTOCOL_ID);
  await semanticButton.click();
  await expect(page.getByText(/Semantic Metrics 分析任务已入队/)).toBeVisible();

  await page.goto(workspaceUrl("reports"));
  await expect(page.getByRole("heading", { name: "Approved Workflow C Reports" })).toBeVisible();
  await expect(page.getByText("Approved Australian evidence", { exact: true }).first()).toBeVisible();
  const metricOne = page.getByLabel("Metric 1");
  const metricValueOne = page.getByLabel("Metric value 1");
  await metricOne.selectOption("source_domain_diversity");
  await expect(metricValueOne).toHaveAttribute("min", "0");
  await expect(metricValueOne).toHaveAttribute("step", "1");
  await expect(metricValueOne).not.toHaveAttribute("max", /.+/);
  await metricOne.selectOption("sentiment");
  await expect(metricValueOne).toHaveAttribute("min", "-1");
  await expect(metricValueOne).toHaveAttribute("max", "1");
  await expect(metricValueOne).toHaveAttribute("step", "any");
  await metricOne.selectOption("brand_mention");
  await expect(metricValueOne).toHaveAttribute("min", "0");
  await expect(metricValueOne).toHaveAttribute("max", "1");
  await page.getByLabel("Campaign ID").fill(CAMPAIGN_ID);
  await page.getByLabel("Monitoring Report ID").fill(MONITORING_REPORT_ID);
  await page.getByLabel("Monitoring Report SHA-256").fill("7".repeat(64));
  await page.getByLabel("Semantic Snapshot").selectOption(METRIC_HASH);
  await page.getByLabel("Headline").fill("Range validation probe");
  await metricValueOne.evaluate((element) => element.removeAttribute("max"));
  await metricValueOne.fill("1.0000000000000000001");
  await page.getByRole("button", { name: "创建报告草稿" }).click();
  await expect(page.getByText(/Count Metric 必须是非负整数/)).toBeVisible();
  await metricOne.selectOption("source_domain_diversity");
  await metricValueOne.evaluate((element) => element.setAttribute("step", "any"));
  await metricValueOne.fill("4.5");
  await page.getByRole("button", { name: "创建报告草稿" }).click();
  await expect(page.getByText(/Count Metric 必须是非负整数/)).toBeVisible();
  const reportLifecycle = page.locator("div").filter({ hasText: REPORT_ID }).filter({
    has: page.getByRole("button", { name: "批准报告" })
  }).last();
  await reportLifecycle.getByLabel("决策原因").fill("customer-safe projection independently verified");
  await reportLifecycle.getByRole("button", { name: "批准报告" }).click();
  await expect(page.locator("article").filter({ hasText: REPORT_ID }).getByText("approved", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json();
  expect(logged.filter((item: { method: string; path: string }) => (
    item.method === "POST" && item.path === `/v1/projects/${PROJECT_ID}/analysis/reports`
  ))).toHaveLength(0);
  for (const path of [
    `/v1/projects/${PROJECT_ID}/analysis/metric-protocols/${METRIC_PROTOCOL_ID}/approve`,
    `/v1/projects/${PROJECT_ID}/analysis/semantic-metrics/jobs`,
    `/v1/projects/${PROJECT_ID}/analysis/reports/${REPORT_ID}/approve`
  ]) {
    const command = logged.find((item: { method: string; path: string }) => item.method === "POST" && item.path === path);
    expect(command?.idempotency_key).toBeTruthy();
  }
  expect(runtimeErrors).toEqual([]);
});

test("M4-WORKFLOW-C-WEB-04: protocol and report command failures stay visible", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(workspaceUrl("protocols"));
  const metricLifecycle = page.locator("div").filter({ hasText: METRIC_PROTOCOL_ID }).filter({
    has: page.getByRole("button", { name: "批准 Protocol" })
  }).last();
  await metricLifecycle.getByLabel("批准原因").fill("fixture-force-conflict");
  await metricLifecycle.getByRole("button", { name: "批准 Protocol" }).click();
  await expect(page.getByText(/状态冲突：Metric Protocol version conflict/)).toBeVisible();

  await page.goto(workspaceUrl("reports"));
  const reportLifecycle = page.locator("div").filter({ hasText: REPORT_ID }).filter({
    has: page.getByRole("button", { name: "批准报告" })
  }).last();
  await reportLifecycle.getByLabel("决策原因").fill("fixture-force-unavailable");
  await reportLifecycle.getByRole("button", { name: "批准报告" }).click();
  await expect(page.getByText(/服务不可用：Workflow C Report service unavailable/)).toBeVisible();
  expect(runtimeErrors).toEqual([]);
});

test("M5-SURFACE-PARSER-WEB-01: manual parser selection and review stay explicitly non-live", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(manualWorkspaceUrl());

  await expect(page).toHaveTitle("GEO 项目管理台");
  await expect(page.getByRole("heading", { level: 1, name: "Sampling, Evidence & Alerts" })).toBeVisible();
  await expect(page.locator("[data-nextjs-dialog-overlay]")).toHaveCount(0);
  await expect(page.getByText("Fixture/manual parser", { exact: true })).toBeVisible();
  await expect(page.getByText("Non-live evidence · no Australian egress proof", { exact: true })).toBeVisible();

  const parserSelect = page.getByLabel("Surface parser release");
  await expect(parserSelect.locator("option")).toHaveCount(2);
  await parserSelect.selectOption(AIO_PARSER_RELEASE_ID);
  await expect(parserSelect).toHaveValue(AIO_PARSER_RELEASE_ID);
  await expect(page.getByLabel("证据类型")).toHaveValue("transcript_export");
  await expect(page.getByLabel("文件")).toHaveAttribute("accept", "application/json,.json");

  await expect(page.getByText("Google AI Overviews", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("manual_ui", { exact: true })).toBeVisible();
  await expect(page.getByText("non-live", { exact: true })).toBeVisible();
  await expect(page.getByText("captured", { exact: true })).toBeVisible();
  await expect(page.getByText("137", { exact: true })).toBeVisible();
  await expect(page.getByText("3", { exact: true })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("fixture answer must remain encrypted");
  await expect(page.locator("body")).not.toContainText("https://example.test/citation");
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("surface-parser-manual-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(parserSelect).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("surface-parser-manual-mobile.png"), fullPage: true });
});
