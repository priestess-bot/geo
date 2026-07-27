import { expect, test, type Page } from "@playwright/test";

const PROJECT_ID = "00000000-0000-4000-8000-000000000001";

function collectRuntimeErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

test("DIFY-BOARD-01: four published workflows and their real Prompts are read-only", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=prompts`);

  await expect(page.getByRole("heading", { level: 2, name: "Dify 工作流" })).toBeVisible();
  await expect(page.getByRole("link", { name: "在 Dify 中编辑" })).toHaveCount(4);
  for (const name of ["测试问题生成", "知识依据生成", "投放内容生成", "投放内容仿真"]) {
    await expect(page.getByRole("heading", { level: 3, name })).toBeVisible();
  }
  await expect(page.getByText("System Prompt", { exact: true })).toHaveCount(4);
  await expect(page.getByText(/Dify 托管的.*测试问题生成/)).toBeVisible();
  await expect(page.getByRole("button", { name: /保存|发布并生效/ })).toHaveCount(0);
  await expect(page.locator("textarea")).toHaveCount(0);
  await expect(page.getByText("已同步", { exact: true })).toHaveCount(4);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("dify-board-desktop.png"), fullPage: true });
});

test("DIFY-BOARD-02: published Prompt remains readable on mobile", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=prompts`);

  await expect(page.getByRole("heading", { level: 2, name: "Dify 工作流" })).toBeVisible();
  await expect(page.getByText(/Dify 托管的.*投放内容仿真/)).toBeVisible();
  await page.getByText("输入变量与版本信息", { exact: true }).first().click();
  await expect(page.getByText(/业务上下文 JSON/).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("dify-board-mobile.png"), fullPage: true });
});
