import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const RUNTIME_SELECTION_ID = "00000000-0000-4000-8000-000000000713";
const COMPLETED_REVIEW_JOB_ID = "00000000-0000-4000-8000-000000000717";

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
  expect((await request.post(`${FIXTURE_API}/__synthetic_mode`, { data: { mode } })).ok()).toBe(true);
}

async function requestLog(request: APIRequestContext): Promise<Array<{
  method: string;
  path: string;
  body?: Record<string, unknown>;
}>> {
  const response = await request.get(`${FIXTURE_API}/__requests`);
  expect(response.ok()).toBe(true);
  return await response.json() as Array<{
    method: string;
    path: string;
    body?: Record<string, unknown>;
  }>;
}

test.beforeEach(async ({ request }) => resetFixture(request));

test("SYNTH-DIRECT-UI-01: direct generation stays on one page and renders governed results", async ({ page, request }, testInfo) => {
  test.setTimeout(75_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_view=generate`);

  await expect(page.getByRole("heading", { level: 2, name: "合成测评实验室" })).toBeVisible();
  await expect(page.getByText("可以生成", { exact: true })).toBeVisible();
  const labNavigation = page.getByRole("navigation", { name: "合成测评实验室功能" });
  await expect(labNavigation.getByRole("link")).toHaveCount(2);
  await expect(labNavigation.getByRole("link", { name: /生成工作台/ })).toHaveAttribute("aria-current", "page");
  await expect(labNavigation.getByRole("link", { name: /渠道风格/ })).toBeVisible();
  for (const removedView of ["测评套件", "授权设置", "语料实验", "任务与结果"]) {
    await expect(labNavigation.getByText(removedView, { exact: true })).toHaveCount(0);
  }

  await page.getByText("查看技术边界", { exact: true }).click();
  await expect(page.getByText("synthetic = true", { exact: true })).toBeVisible();
  await expect(page.getByText("test_only = true", { exact: true })).toBeVisible();
  await expect(page.getByText("publication_eligible = false", { exact: true })).toBeVisible();

  const composer = page.locator("section").filter({
    has: page.getByRole("heading", { level: 3, name: "生成一条仿真用户文案" })
  });
  await expect(composer.getByLabel("发布渠道")).toHaveValue("reddit");
  await expect(composer.getByLabel("目标产品")).toHaveValue("00000000-0000-4000-8000-000000000750");
  await expect(composer.getByText("2 条已批准事实将作为模型上下文", { exact: true })).toBeVisible();
  await expect(composer.locator('select[name="runtime_selection_id"]')).toHaveValue(RUNTIME_SELECTION_ID);
  await composer.locator("details").getByText("高级设置与实际输入", { exact: true }).click();
  await expect(composer.getByText("Triple-Cam AI Vision Robot Mower V600", { exact: true })).toBeVisible();
  await expect(composer.getByText("600 square metres (0.15 acre)", { exact: true })).toBeVisible();
  await expect(composer.getByText("加入有证据支持的竞品上下文", { exact: true }).locator("..").getByRole("checkbox")).toBeDisabled();

  await page.evaluate(() => {
    (window as typeof window & { __directGenerationMarker?: string }).__directGenerationMarker = "kept";
  });
  await composer.getByLabel("生成目标").fill(
    "Explain whether the TerraMow V600 fits a medium Australian lawn without inventing ownership or performance."
  );
  await composer.getByRole("button", { name: "生成仿真文案" }).click();
  await expect(page.getByRole("status").filter({ hasText: "生成任务已开始" })).toBeVisible();
  await expect(page.getByText("For a medium Australian lawn", { exact: false })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("候选数量", { exact: true }).locator("..")).toContainText("4");
  await expect(page.getByText("包含知识库未覆盖的推演，已单独标记", { exact: true })).toBeVisible();
  const usedKnowledge = page.getByText("本次实际调用的知识", { exact: true }).locator("..").locator("..");
  await expect(usedKnowledge).toContainText("2 条");
  await expect(page.getByText("已匹配", { exact: true })).toHaveCount(2);
  await expect(usedKnowledge.getByRole("link", { name: "查看证据与追溯链" })).toHaveCount(2);
  expect(await page.evaluate(() => (
    window as typeof window & { __directGenerationMarker?: string }
  ).__directGenerationMarker)).toBe("kept");
  await expect(page).toHaveURL(new RegExp(`synthetic_view=generate`));

  const generationWrite = (await requestLog(request)).find(
    (entry) => entry.method === "POST" && entry.path.endsWith("/jobs/direct-generation")
  );
  expect(Object.keys(generationWrite?.body || {}).sort()).toEqual([
    "channel", "channel_style_hash", "channel_style_version_id", "generation_goal",
    "include_competitor_context", "knowledge_snapshot_hash", "runtime_selection_id",
    "style_pass_threshold", "subject_entity_id"
  ]);
  expect(generationWrite?.body).toMatchObject({
    channel: "reddit",
    subject_entity_id: "00000000-0000-4000-8000-000000000750",
    runtime_selection_id: RUNTIME_SELECTION_ID,
    style_pass_threshold: 4.2,
    include_competitor_context: false
  });
  expect(generationWrite?.body).not.toHaveProperty("job_id");
  expect(generationWrite?.body).not.toHaveProperty("input_hash");
  expect(generationWrite?.body).not.toHaveProperty("runtime_inputs");

  await page.screenshot({ path: testInfo.outputPath("synthetic-direct-result-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const resultTop = await page.getByText("任务结果", { exact: true }).boundingBox();
  const historyTop = await page.getByRole("heading", { level: 3, name: "生成历史" }).boundingBox();
  expect(resultTop?.y || 0).toBeLessThan(historyTop?.y || 0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("synthetic-direct-result-mobile.png"), fullPage: true });
});

test("SYNTH-STYLE-UI-01: nine manual channel styles save a new version without navigation", async ({ page, request }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_view=style`);

  await expect(page.getByRole("heading", { level: 3, name: "九渠道手工风格设置" })).toBeVisible();
  const channelRail = page.getByRole("navigation", { name: "渠道风格列表" });
  await expect(channelRail.getByRole("button")).toHaveCount(9);
  await expect(channelRail.getByRole("button", { name: /Reddit/ })).toContainText("版本 1");
  await expect(page.getByText("手工初始预设 · 待样本校准", { exact: true })).toBeVisible();
  const directive = page.getByLabel("风格说明");
  await expect(directive).toContainText("reddit fixture style");

  await page.evaluate(() => {
    (window as typeof window & { __styleSaveMarker?: string }).__styleSaveMarker = "kept";
  });
  const edited = "Write candid Australian English for Reddit. Use only approved facts, show practical trade-offs, and state unknowns plainly.";
  await directive.fill(edited);
  await page.getByRole("button", { name: "保存为新版本" }).click();
  await expect(page.getByRole("status").filter({ hasText: "渠道风格版本 2 已保存" })).toBeVisible();
  await expect(channelRail.getByRole("button", { name: /Reddit/ })).toContainText("版本 2");
  await expect(directive).toHaveValue(edited);
  expect(await page.evaluate(() => (
    window as typeof window & { __styleSaveMarker?: string }
  ).__styleSaveMarker)).toBe("kept");

  const styleWrite = (await requestLog(request)).find(
    (entry) => entry.method === "POST" && entry.path.endsWith("/channel-styles/reddit/versions")
  );
  expect(styleWrite?.body).toEqual({ expected_current_version: 1, directive: edited });
  await channelRail.getByRole("button", { name: /Amazon/ }).click();
  await expect(directive).toContainText("amazon fixture style");

  await page.screenshot({ path: testInfo.outputPath("synthetic-channel-style-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("synthetic-channel-style-mobile.png"), fullPage: true });
});

test("SYNTH-DIRECT-UI-02: missing data and backend conflicts remain actionable", async ({ page, request }) => {
  await setMode(request, "empty");
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_view=generate`);
  await expect(page.getByText("需要补充生成条件", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "生成仿真文案" })).toBeDisabled();

  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_view=style`);
  const emptyRail = page.getByRole("navigation", { name: "渠道风格列表" });
  await expect(emptyRail.getByText("待填写", { exact: true })).toHaveCount(9);
  await expect(page.getByRole("button", { name: "保存为新版本" })).toBeDisabled();

  await setMode(request, "unavailable");
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_view=generate`);
  await expect(page.getByRole("alert").filter({ hasText: "产品与风格加载失败" })).toBeVisible();
  await expect(page.getByText("可以刷新重试；其他未依赖此数据的功能仍可继续使用。", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "生成仿真文案" })).toBeDisabled();

  await setMode(request, "normal");
  await page.reload();
  await page.getByLabel("生成目标").fill("Create a bounded V600 Reddit comment.");
  await setMode(request, "conflict");
  await page.getByRole("button", { name: "生成仿真文案" }).click();
  const conflict = page.getByRole("alert").filter({ hasText: "状态冲突" });
  await expect(conflict).toContainText("409");
  await expect(conflict).toContainText("请刷新后重试");
  await expect(page.getByRole("button", { name: "生成仿真文案" })).toBeEnabled();
});

test("SYNTH-DIRECT-UI-03: old result links open inside the new generation workspace", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(
    `/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_view=results&synthetic_job_id=${COMPLETED_REVIEW_JOB_ID}`
  );

  await expect(page.getByRole("heading", { level: 3, name: "生成一条仿真用户文案" })).toBeVisible();
  await expect(page.getByText("I compared it with the usual big-name option", { exact: false })).toBeVisible();
  await expect(page.getByText("带提醒完成", { exact: true })).toBeVisible();
  await expect(page.getByText("修订轮次", { exact: true }).locator("..")).toContainText("1");
  await expect(page.getByText("Dify 调用", { exact: true }).locator("..")).toContainText("2");
  await expect(page.getByText("本次实际调用的知识", { exact: true }).locator("..")).toContainText("0 条");
  await expect(page.getByRole("navigation", { name: "合成测评实验室功能" }).getByRole("link", { name: /生成工作台/ })).toHaveAttribute("aria-current", "page");
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("synthetic-legacy-result-in-workbench.png"), fullPage: true });
});
