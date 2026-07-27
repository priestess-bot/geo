import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const RECOMMENDATION_ID = "00000000-0000-4000-8000-000000000801";

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

async function setMode(request: APIRequestContext, mode: string): Promise<void> {
  expect((await request.post(`${FIXTURE_API}/__recommendation_mode`, { data: { mode } })).ok()).toBe(true);
}

test.beforeEach(async ({ request }) => resetFixture(request));

test("M5-REC-WEB-01: approval creates only an unstarted draft and remains responsive", async ({ page, request }, testInfo) => {
  test.setTimeout(75_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=recommendations&recommendation_id=${RECOMMENDATION_ID}`);

  await expect(page).toHaveTitle(/GEO/i);
  await expect(page.getByRole("heading", { level: 2, name: "建议" })).toBeVisible();
  await expect(page.getByText("批准只创建未启动草稿", { exact: false })).toBeVisible();
  await expect(page.getByText("真实观测 / 投影", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "批准并创建草稿" }).click();

  const approvalResult = page.getByRole("status").filter({ hasText: "已批准并仅创建未启动草稿" });
  await expect(approvalResult).toContainText("仅创建未启动草稿");
  await expect(page.getByRole("heading", { level: 3, name: "建议 v3" })).toBeVisible();
  await expect(page.getByText("已排队：false · 已执行：false · 已发布：false", { exact: true })).toBeVisible();
  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{ path: string }>;
  expect(logged.some((entry) => entry.path.endsWith(`/${RECOMMENDATION_ID}/approve`))).toBe(true);
  expect(logged.some((entry) => /\/(execute|publish)$/.test(entry.path))).toBe(false);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("recommendations-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { level: 2, name: "建议" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("recommendations-mobile.png"), fullPage: true });
});

test("M5-REC-WEB-02: partial 503 keeps selected evidence readable but disables commands", async ({ page, request }) => {
  await setMode(request, "partial-unavailable");
  await page.goto(`/projects/${PROJECT_ID}?tab=recommendations&recommendation_id=${RECOMMENDATION_ID}`);

  await expect(page.getByRole("alert").filter({ hasText: "建议列表加载失败" })).toContainText("503");
  await expect(page.getByRole("heading", { level: 3, name: "建议 v2" })).toBeVisible();
  await expect(page.getByRole("button", { name: "批准并创建草稿" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "记录当前证据审核" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "拒绝建议" })).toBeDisabled();
});

test("M5-REC-WEB-03: analyst cannot perform approval commands", async ({ page, request }) => {
  expect((await request.post(`${FIXTURE_API}/__secret_mode`, { data: { role: "analyst" } })).ok()).toBe(true);
  await page.goto(`/projects/${PROJECT_ID}?tab=recommendations&recommendation_id=${RECOMMENDATION_ID}`);

  await expect(page.getByText("分析师 当前角色", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "批准并创建草稿" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "记录当前证据审核" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "拒绝建议" })).toBeDisabled();
});

test("M5-REC-WEB-04: generation uses approved Prompt and runtime catalogs", async ({ page, request }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=recommendations&recommendation_id=${RECOMMENDATION_ID}`);

  await expect(page.getByRole("heading", { level: 3, name: "重新生成建议" })).toBeVisible();
  await expect(page.getByLabel("建议 Prompt")).toHaveValue(
    "00000000-0000-4000-8000-000000000811"
  );
  await expect(page.getByLabel("批准的模型运行时")).toHaveValue(
    "00000000-0000-4000-8000-000000000814"
  );
  await expect(page.getByLabel("批准的模型运行时")).toContainText("openai · gpt-5.2");
  await page.getByRole("button", { name: "创建生成任务" }).click();

  await expect(page.getByRole("status").filter({ hasText: "Durable Job 队列" }))
    .toContainText("queued");
  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    path: string;
    body: Record<string, unknown>;
  }>;
  const enqueue = logged.find((entry) => entry.path.endsWith("/recommendations/generation-jobs"));
  expect(enqueue).toBeTruthy();
  expect(JSON.stringify(enqueue?.body)).toContain("runtime_selection_id");
  expect(JSON.stringify(enqueue?.body)).not.toContain("adapter_release_id");
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("recommendation-generation-catalog.png"), fullPage: false });
});
