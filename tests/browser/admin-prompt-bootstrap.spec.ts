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

test.beforeEach(async ({ request }) => resetFixture(request));

test("DIFY-BOARD-03: legacy Prompt deep links stay on the read-only Dify board", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=prompts&prompt_flow=knowledge.question_generation`);

  await expect(page).toHaveTitle(/GEO/i);
  await expect(page.getByRole("heading", { level: 2, name: "Dify 工作流" })).toBeVisible();
  for (const label of [
    "测试问题生成",
    "知识依据生成",
    "投放内容生成",
    "投放内容仿真",
    "合成候选生成",
    "Claim 提取",
    "知识冲突检查",
    "候选修订",
    "风格画像生成",
    "证据建议生成"
  ]) {
    await expect(page.getByRole("heading", { level: 3, name: label })).toBeVisible();
  }
  await expect(page.locator("textarea")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /保存|发布并生效|运行固定测试集/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "打开 Dify 工作流" })).toHaveCount(10);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("legacy-deep-link-read-only.png"), fullPage: true });
});
