import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";

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
  expect((await request.post(`${FIXTURE_API}/__prompt_bootstrap_mode`, { data: { mode } })).ok()).toBe(true);
}

test.beforeEach(async ({ request }) => resetFixture(request));

test("M1-PROMPT-BOOTSTRAP-WEB-01: catalog evaluates fixtures and safely retries a partial draft batch", async ({ page, request }, testInfo) => {
  test.setTimeout(90_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await setMode(request, "partial");
  await page.goto(`/projects/${PROJECT_ID}?tab=prompts&prompt_bootstrap_kind=generation`);

  const catalog = page.getByRole("region", { name: "基线目录（Draft Bootstrap）" });
  await expect(page).toHaveTitle(/GEO/i);
  await expect(catalog).toBeVisible();
  await expect(catalog.getByText("10 Kinds", { exact: true })).toBeVisible();
  await expect(catalog.getByText("50 Fixtures", { exact: true })).toBeVisible();
  await expect(catalog.getByText("目录不是批准结果", { exact: true })).toBeVisible();
  await expect(catalog.locator("table").first().locator("tbody tr")).toHaveCount(10);
  await catalog.getByText("Rubric（权重合计 100）", { exact: true }).click();
  await catalog.getByText("固定 Fixtures（5）", { exact: true }).click();
  await catalog.getByText("Output Schema 与 Application Rules", { exact: true }).click();
  await expect(catalog.getByText("positive", { exact: true })).toBeVisible();
  await expect(catalog.getByText("fabricated_citation", { exact: true })).toBeVisible();
  await expect(catalog.getByText("schema.portable_strict", { exact: true })).toBeVisible();
  await expect(catalog.getByText("尚无本次创建结果", { exact: true })).toBeVisible();

  const evaluation = catalog.locator("section").filter({
    has: page.getByRole("heading", { name: "离线评估 5 个固定 Fixture" })
  });
  await evaluation.getByRole("button", { name: "运行离线评估" }).click();
  await expect(evaluation.getByRole("status")).toContainText("5 个固定 Fixture 全部通过");
  await expect(evaluation.getByRole("status")).toContainText("score 100 / minimum 95");

  const create = catalog.locator("section").filter({
    has: page.getByRole("heading", { name: "创建 10 个未批准 Draft" })
  });
  await create.getByRole("button", { name: "创建 / 恢复 10 个 Draft" }).click();
  const partial = create.getByRole("alert");
  await expect(partial).toContainText("partial_failure");
  await expect(partial).toContainText("Created9");
  await expect(partial).toContainText("Failed1");
  await expect(partial).toContainText("Fixture persistence was interrupted");
  await create.getByRole("button", { name: "使用同一 Key 重试失败项" }).click();
  const completed = create.getByRole("status");
  await expect(completed).toContainText("completed");
  await expect(completed).toContainText("Created1");
  await expect(completed).toContainText("Replayed9");
  await expect(completed).toContainText("Failed0");
  await completed.getByText("查看 10 项创建明细", { exact: true }).click();
  await expect(completed.getByText("release state: draft · 未批准").first()).toBeVisible();

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string;
    path: string;
    idempotency_key?: string;
  }>;
  const draftRequests = logged.filter((entry) => entry.method === "POST" && entry.path.endsWith("/prompt-bootstrap/drafts"));
  expect(draftRequests).toHaveLength(2);
  expect(draftRequests[0].idempotency_key).toBe(draftRequests[1].idempotency_key);
  expect(draftRequests[0].idempotency_key).toContain("prompt-bootstrap-drafts-");
  expect(logged.some((entry) => entry.path.includes("/prompt-bootstrap/") && /(approve|freeze|bind)$/.test(entry.path))).toBe(false);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("prompt-bootstrap-desktop.png"), fullPage: true });

  await catalog.getByText("Rubric（权重合计 100）", { exact: true }).click();
  await catalog.getByText("固定 Fixtures（5）", { exact: true }).click();
  await catalog.getByText("Output Schema 与 Application Rules", { exact: true }).click();
  await completed.getByText("查看 10 项创建明细", { exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "基线目录（Draft Bootstrap）" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("prompt-bootstrap-mobile.png"), fullPage: true });
  const mobileNavigator = catalog.getByText("选择基线 Kind", { exact: true });
  await mobileNavigator.click();
  const mobileNavigatorDetails = mobileNavigator.locator("..");
  await mobileNavigatorDetails.getByLabel("Kind").selectOption("revision");
  await mobileNavigatorDetails.getByRole("button", { name: "查看 Kind" }).click();
  await expect(page).toHaveURL(/prompt_bootstrap_kind=revision/);
  await expect(page.getByRole("heading", { name: "revision", exact: true })).toBeVisible();
});

test("M1-PROMPT-BOOTSTRAP-WEB-02: analyst and unavailable runtime fail closed", async ({ page, request }) => {
  expect((await request.post(`${FIXTURE_API}/__secret_mode`, { data: { role: "analyst" } })).ok()).toBe(true);
  await page.goto(`/projects/${PROJECT_ID}?tab=prompts`);
  await expect(page.getByRole("alert").filter({ hasText: "Prompt 基线目录加载失败" })).toContainText("403");
  await expect(page.getByRole("button", { name: "创建 / 恢复 10 个 Draft" })).toHaveCount(0);

  await resetFixture(request);
  await setMode(request, "unavailable");
  await page.reload();
  await expect(page.getByRole("alert").filter({ hasText: "Prompt 基线目录 unavailable" })).toContainText("503");
  await expect(page.getByRole("button", { name: "运行离线评估" })).toHaveCount(0);
});
