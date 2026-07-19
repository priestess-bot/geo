import os from "node:os";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const PROJECT_A = "10000000-0000-4000-8000-000000000001";
const PROJECT_B = "10000000-0000-4000-8000-000000000002";
const CAMPAIGN_A = "20000000-0000-4000-8000-000000000001";
const CAMPAIGN_B = "20000000-0000-4000-8000-000000000002";
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
  await expect(page.locator(campaignSelect)).toHaveValue(CAMPAIGN_B);

  await page.getByLabel("授权项目").selectOption(PROJECT_B);
  await page.getByRole("button", { name: "切换" }).first().click();
  await expect(page).toHaveURL(new RegExp(`project_id=${PROJECT_B}$`));
  expect(new URL(page.url()).searchParams.has("campaign_id")).toBe(false);
  await expect(page.getByRole("heading", { name: "暂无 Campaign" })).toBeVisible();
});
