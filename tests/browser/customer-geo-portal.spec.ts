import os from "node:os";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const PROJECT_A = "10000000-0000-4000-8000-000000000001";
const PROJECT_B = "10000000-0000-4000-8000-000000000002";
const CAMPAIGN_A = "20000000-0000-4000-8000-000000000001";
const CAMPAIGN_B = "20000000-0000-4000-8000-000000000002";
const CAMPAIGN_MALICIOUS = "20000000-0000-4000-8000-000000000003";
const CAMPAIGN_FORBIDDEN = "20000000-0000-4000-8000-000000000004";
const CAMPAIGN_UNAVAILABLE = "20000000-0000-4000-8000-000000000005";
const CAMPAIGN_LONG = "20000000-0000-4000-8000-000000000006";
const CAMPAIGN_INVALID_METRIC = "20000000-0000-4000-8000-000000000007";
const CAMPAIGN_INVALID_COUNT = "20000000-0000-4000-8000-000000000008";
const CAMPAIGN_UNRELATED_FORBIDDEN = "20000000-0000-4000-8000-000000000009";
const CAMPAIGN_UNRELATED_UNAVAILABLE = "20000000-0000-4000-8000-000000000010";
const campaignSelect = 'select[name="campaign_id"]';
const FIXTURE_API = process.env.PLAYWRIGHT_CUSTOMER_FIXTURE_API_URL
  || "http://127.0.0.1:3198";

function runtimeErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

test("F027: Customer downloads only the selected Campaign approved export ZIP", async ({ page, request }) => {
  await request.delete(`${FIXTURE_API}/__requests`);
  await page.goto(`/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_A}`);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载当前 Campaign 数据" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(
    `geo-project-export-${CAMPAIGN_A}.zip`
  );
  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string;
    path: string;
  }>;
  expect(logged.some((item) => (
    item.method === "GET"
    && item.path.endsWith(`/project-exports/campaigns/${CAMPAIGN_A}/download`)
  ))).toBe(true);
  expect(logged.some((item) => item.path.includes(CAMPAIGN_B))).toBe(false);
});

test("Workflow C: Customer reads only the selected Campaign approved projection", async ({ page, request }) => {
  const errors = runtimeErrors(page);
  await request.delete(`${FIXTURE_API}/__requests`);
  await page.goto(`/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_A}`);
  await page.waitForLoadState("networkidle");

  const section = page.locator('section[aria-labelledby="workflow-c-report-heading"]');
  await expect(section.getByRole("heading", { name: "已批准跨引擎报告" })).toBeVisible();
  await expect(section.getByText("1 份已批准")).toBeVisible();
  await expect(section.getByRole("heading", { name: "跨引擎推荐表现" })).toBeVisible();
  await expect(section.getByText("Provider API", { exact: true })).toBeVisible();
  await expect(section.getByText("品牌提及")).toBeVisible();
  await expect(section.getByText("0.78")).toBeVisible();
  await expect(section.getByRole("row", { name: "竞品相对位置 -1" })).toBeVisible();
  await expect(section.getByRole("row", { name: "情感 1.0000" })).toBeVisible();
  await expect(section.getByRole("row", { name: "来源域名多样性 4" })).toBeVisible();
  await expect(section.getByRole("row", { name: "批准语料吸收度 0.7500" })).toBeVisible();
  await expect(section.getByRole("row", { name: "提及率 1.0000" })).toBeVisible();
  await expect(section.getByText("自动化界面与 Provider API 使用独立分母。")).toBeVisible();
  await expect(section.getByText("2".repeat(64))).toBeVisible();
  await expect(section.getByText("1".repeat(64))).toHaveCount(0);
  await expect(section.getByRole("button")).toHaveCount(0);
  const reportList = section.getByRole("list", { name: "已批准 Workflow C 报告" });
  await expect(reportList).toBeVisible();
  await expect(reportList.locator(":scope > li")).toHaveCount(1);
  await expect(section.getByRole("article", { name: "跨引擎推荐表现" })).toBeVisible();
  await expect(section.getByRole("table", { name: "Workflow C 已批准指标" })).toBeVisible();
  await expect(section.getByRole("columnheader", { name: "指标" })).toBeVisible();
  await expect(section.getByRole("columnheader", { name: "批准值" })).toBeVisible();
  await expect(section.getByRole("complementary", { name: "报告注意事项" })).toBeVisible();
  await expect(section.locator(`time[datetime="2026-07-19T06:00:00Z"]`)).toBeVisible();

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string;
    path: string;
    query: string;
  }>;
  expect(logged.some((item) => (
    item.method === "GET"
    && item.path.endsWith("/geo/workflow-c-reports")
    && new URLSearchParams(item.query).get("campaign_id") === CAMPAIGN_A
  ))).toBe(true);
  expect(errors).toEqual([]);
});

test("Workflow C: Summary counts approved reports without exposing report internals", async ({ page }) => {
  await page.goto(`/portal/summary?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_A}`);
  await page.waitForLoadState("networkidle");
  const metric = page.locator(".metricStat").filter({ hasText: "Workflow C 报告" });
  await expect(metric).toContainText("1");
  await expect(page.getByText("50000000-0000-4000-8000-000000000002")).toHaveCount(0);
});

test("Workflow C: empty approved projection is distinct from a transport failure", async ({ page }) => {
  await page.goto(`/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_B}`);
  await page.waitForLoadState("networkidle");
  const section = page.locator('section[aria-labelledby="workflow-c-report-heading"]');
  await expect(section.getByText("0 份已批准")).toBeVisible();
  await expect(section.getByText("当前 Campaign 暂无已批准的 Workflow C 报告。")).toBeVisible();
  await expect(page.getByText("当前 Campaign 暂无已批准报告。草稿和未批准快照不会显示。")).toBeVisible();
  await expect(page.locator(".problemBand")).toHaveCount(0);
});

test("Workflow C: 403 and 503 failures preserve the legacy approved-report view", async ({ page }) => {
  for (const scenario of [
    {
      campaignId: CAMPAIGN_FORBIDDEN,
      detail: "Workflow C reports are not authorized for this Campaign.",
      requestId: "customer-workflow-c-forbidden"
    },
    {
      campaignId: CAMPAIGN_UNAVAILABLE,
      detail: "Workflow C report storage is temporarily unavailable.",
      requestId: "customer-workflow-c-unavailable"
    }
  ]) {
    await page.goto(`/portal/reports?project_id=${PROJECT_A}&campaign_id=${scenario.campaignId}`);
    await page.waitForLoadState("networkidle");
    const workflowSection = page.locator('section[aria-labelledby="workflow-c-report-heading"]');
    await expect(workflowSection.getByRole("alert")).toContainText("Workflow C 报告暂不可用");
    await expect(workflowSection.getByRole("alert")).toContainText(scenario.detail);
    await expect(workflowSection.getByRole("alert")).toContainText(scenario.requestId);
    await expect(page.getByText("当前 Campaign 暂无已批准报告。草稿和未批准快照不会显示。")).toBeVisible();
    await expect(page.locator(".problemBand")).toContainText(scenario.detail);
  }
});

test("Workflow C: unknown payload fields fail closed without hiding the legacy view", async ({ page }) => {
  await page.goto(`/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_MALICIOUS}`);
  await page.waitForLoadState("networkidle");
  const workflowSection = page.locator('section[aria-labelledby="workflow-c-report-heading"]');
  await expect(workflowSection.getByRole("alert")).toContainText("Workflow C 报告暂不可用");
  await expect(workflowSection.getByRole("alert")).toContainText(
    "The Customer API returned data outside its stable contract."
  );
  await expect(page.getByText("customer-secret-must-not-render")).toHaveCount(0);
  await expect(page.getByText("不得进入客户门户")).toHaveCount(0);
  await expect(page.getByText("当前 Campaign 暂无已批准报告。草稿和未批准快照不会显示。")).toBeVisible();

  await page.goto(
    `/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_INVALID_METRIC}`
  );
  await page.waitForLoadState("networkidle");
  const invalidMetricSection = page.locator(
    'section[aria-labelledby="workflow-c-report-heading"]'
  );
  await expect(invalidMetricSection.getByRole("alert")).toContainText(
    "The Customer API returned data outside its stable contract."
  );
  await expect(page.getByText("越界指标不得进入客户门户")).toHaveCount(0);
  await expect(page.getByText("当前 Campaign 暂无已批准报告。草稿和未批准快照不会显示。")).toBeVisible();

  await page.goto(
    `/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_INVALID_COUNT}`
  );
  await page.waitForLoadState("networkidle");
  const invalidCountSection = page.locator(
    'section[aria-labelledby="workflow-c-report-heading"]'
  );
  await expect(invalidCountSection.getByRole("alert")).toContainText(
    "The Customer API returned data outside its stable contract."
  );
  await expect(page.getByText("非整数 Count 不得进入客户门户")).toHaveCount(0);
  await expect(page.getByText("当前 Campaign 暂无已批准报告。草稿和未批准快照不会显示。")).toBeVisible();
});

test("Workflow C: unrelated modules never request or surface report failures", async ({ page, request }) => {
  await request.delete(`${FIXTURE_API}/__requests`);
  await page.goto(
    `/portal/metrics?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_UNRELATED_FORBIDDEN}`
  );
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "已批准报告关联的不可变快照" })).toBeVisible();
  await expect(page.locator(".problemBand")).toHaveCount(0);

  await page.goto(
    `/portal/placements?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_UNRELATED_UNAVAILABLE}`
  );
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "公开投放地址" })).toBeVisible();
  await expect(page.locator(".problemBand")).toHaveCount(0);

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    path: string;
    query: string;
  }>;
  const unrelatedCampaigns = new Set([
    CAMPAIGN_UNRELATED_FORBIDDEN,
    CAMPAIGN_UNRELATED_UNAVAILABLE
  ]);
  expect(logged.some((item) => (
    item.path.endsWith("/geo/workflow-c-reports")
    && unrelatedCampaigns.has(new URLSearchParams(item.query).get("campaign_id") || "")
  ))).toBe(false);
  for (const campaignId of unrelatedCampaigns) {
    expect(logged.some((item) => item.path.endsWith(`/campaigns/${campaignId}/read-model`)))
      .toBe(true);
  }
});

test("Workflow C: 320px layout contains maximum-length approved content", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await page.goto(`/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_LONG}`);
  await page.waitForLoadState("networkidle");

  const section = page.locator('section[aria-labelledby="workflow-c-report-heading"]');
  const headline = section.getByRole("heading", { name: "H".repeat(200) });
  const hashContainer = section.locator(".reportMetadata dd").filter({ hasText: "f".repeat(64) });
  const warning = section.locator(".reportWarnings li");
  await expect(headline).toBeVisible();
  await expect(hashContainer).toBeVisible();
  await expect(warning).toBeVisible();
  expect(await headline.evaluate((element) => getComputedStyle(element).overflowWrap)).toBe("anywhere");
  expect(await hashContainer.locator("code").evaluate((element) => getComputedStyle(element).wordBreak)).toBe("break-all");
  expect(await warning.evaluate((element) => getComputedStyle(element).overflowWrap)).toBe("anywhere");
  expect(await page.evaluate(() => (
    document.documentElement.scrollWidth <= document.documentElement.clientWidth
  ))).toBe(true);
  const tableScroll = section.locator(".workflowMetricTable");
  expect(await tableScroll.evaluate((element) => ({
    contained: element.scrollWidth > element.clientWidth,
    overflowX: getComputedStyle(element).overflowX
  }))).toEqual({ contained: true, overflowX: "auto" });

  await page.screenshot({
    path: path.join(os.tmpdir(), `geo-customer-workflow-c-320-${test.info().project.name}.png`),
    fullPage: true
  });
});

test("Workflow C: keyboard focus is visible and portal navigation works with Enter", async ({ page }) => {
  await page.goto(`/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_A}`);
  await page.waitForLoadState("networkidle");
  const metricsLink = page.getByRole("link", { name: "趋势指标" });
  let reached = false;
  for (let index = 0; index < 24; index += 1) {
    await page.keyboard.press("Tab");
    reached = await metricsLink.evaluate((element) => element === document.activeElement);
    if (reached) break;
  }
  expect(reached).toBe(true);
  await expect(metricsLink).toBeFocused();
  expect(await metricsLink.evaluate((element) => ({
    focusVisible: element.matches(":focus-visible"),
    outlineStyle: getComputedStyle(element).outlineStyle,
    outlineWidth: getComputedStyle(element).outlineWidth
  }))).toEqual({ focusVisible: true, outlineStyle: "solid", outlineWidth: "3px" });
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL((url) => (
    url.pathname === "/portal/metrics"
    && url.searchParams.get("project_id") === PROJECT_A
    && url.searchParams.get("campaign_id") === CAMPAIGN_A
  ));
});

test("F023: Project and Campaign never first-fallback and invalid deep links stay invalid", async ({ page }) => {
  const errors = runtimeErrors(page);
  await page.goto("/portal/summary");
  await expect(page.getByRole("heading", { name: "未选择项目" })).toBeVisible();
  await expect(page.getByLabel("授权项目")).toHaveValue("");

  await page.goto("/portal/summary?project_id=ffffffff-ffff-4fff-8fff-ffffffffffff");
  await expect(page.getByRole("heading", { name: "无权访问所选项目" })).toBeVisible();
  await expect(page.getByLabel("授权项目")).toHaveValue("");

  await page.getByLabel("授权项目").selectOption(PROJECT_A);
  await page.getByRole("button", { name: "切换" }).first().click();
  await expect(page).toHaveURL(new RegExp(`project_id=${PROJECT_A}$`));
  await expect(page.getByRole("heading", { name: "未选择 Campaign" })).toBeVisible();
  await expect(page.locator(campaignSelect)).toHaveValue("");

  await page.goto(`/portal/metrics?project_id=${PROJECT_A}&campaign_id=ffffffff-ffff-4fff-8fff-ffffffffffff`);
  await expect(page.getByRole("heading", { name: "无权访问所选 Campaign" })).toBeVisible();
  await expect(page.locator(campaignSelect)).toHaveValue("");
  expect(errors).toEqual([]);
});

test("F023: selector, modules, refresh and browser history preserve exact Campaign scope", async ({ page }) => {
  const errors = runtimeErrors(page);
  await page.goto(`/portal/summary?project_id=${PROJECT_A}`);
  await page.locator(campaignSelect).selectOption(CAMPAIGN_A);
  await page.getByRole("button", { name: "切换" }).nth(1).click();
  await expect(page).toHaveURL(new RegExp(`project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_A}`));
  await expect(page.getByText("最近批准的测量")).toBeVisible();
  await expect(page.getByText("67%")).toBeVisible();
  await expect(page.getByText("统计口径 v2").first()).toBeVisible();

  await page.getByRole("link", { name: "趋势指标" }).click();
  await expect(page).toHaveURL((url) => (
    url.pathname === "/portal/metrics"
    && url.searchParams.get("project_id") === PROJECT_A
    && url.searchParams.get("campaign_id") === CAMPAIGN_A
  ));
  await expect(page.getByText("已批准报告关联的不可变快照")).toBeVisible();
  await page.reload();
  await expect(page.locator(campaignSelect)).toHaveValue(CAMPAIGN_A);

  await page.getByRole("link", { name: "已批准报告" }).click();
  await expect(page.getByText("快照")).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL((url) => (
    url.pathname.startsWith("/portal/")
    && url.searchParams.get("project_id") === PROJECT_A
    && url.searchParams.get("campaign_id") === CAMPAIGN_A
  ));
  await expect(page.locator(campaignSelect)).toHaveValue(CAMPAIGN_A);
  await expect(page.getByText("统计口径 v2").first()).toBeVisible();
  expect(await page.evaluate(() => (
    document.documentElement.scrollWidth <= document.documentElement.clientWidth
  ))).toBe(true);

  await page.screenshot({
    path: path.join(os.tmpdir(), `geo-customer-f023-${test.info().project.name}.png`),
    fullPage: true
  });
  expect(errors).toEqual([]);
});

test("F023: no approved report and no Campaign are distinct, project switch clears Campaign", async ({ page }) => {
  await page.goto(`/portal/reports?project_id=${PROJECT_A}&campaign_id=${CAMPAIGN_B}`);
  await expect(page.getByText("当前 Campaign 暂无已批准报告。草稿和未批准快照不会显示。")).toBeVisible();
  await expect(page.getByText("当前 Campaign 暂无已批准的 Workflow C 报告。")).toBeVisible();
  await expect(page.locator(campaignSelect)).toHaveValue(CAMPAIGN_B);

  await page.getByLabel("授权项目").selectOption(PROJECT_B);
  await page.getByRole("button", { name: "切换" }).first().click();
  await expect(page).toHaveURL(new RegExp(`project_id=${PROJECT_B}$`));
  expect(new URL(page.url()).searchParams.has("campaign_id")).toBe(false);
  await expect(page.getByRole("heading", { name: "暂无 Campaign" })).toBeVisible();
});
