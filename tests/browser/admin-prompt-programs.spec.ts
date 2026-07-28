import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const PROJECT_ID = "00000000-0000-4000-8000-000000000001";

function collectRuntimeErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

test("DIFY-BOARD-01: ten published workflows and their real Prompts are read-only", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.context().route("http://127.0.0.1:15000/**", (route) => route.fulfill({
    body: "Dify workflow fixture",
    contentType: "text/plain",
    status: 200
  }));
  await page.goto(`/projects/${PROJECT_ID}?tab=prompts`);

  await expect(page.getByRole("heading", { level: 2, name: "Dify 工作流" })).toBeVisible();
  const difyLinks = page.getByRole("link", { name: "打开 Dify 工作流" });
  await expect(difyLinks).toHaveCount(10);
  await expect(difyLinks.first()).toHaveAttribute(
    "href",
    `http://127.0.0.1:15000/app/fixture-app-0/workflow`
  );
  for (const name of [
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
    const workflow = page.getByRole("region", { name });
    await expect(workflow.getByRole("heading", { level: 3, name })).toBeVisible();
    await expect(workflow.getByText("输入", { exact: true })).toBeVisible();
    await expect(workflow.getByText("产出", { exact: true })).toBeVisible();
    await expect(workflow.getByText("业务运行中", { exact: true })).toBeVisible();
    await expect(workflow.getByText("发布图一致", { exact: true })).toBeVisible();
    await expect(workflow.getByText("下一步", { exact: true })).toBeVisible();
  }
  await expect(page.getByText("System Prompt", { exact: true })).toHaveCount(10);
  await expect(page.getByText(/Dify 托管的.*测试问题生成/)).toBeVisible();
  await expect(page.getByText(/Dify 托管的.*风格画像生成/)).toBeVisible();
  await expect(page.getByText(/Dify 托管的.*证据建议生成/)).toBeVisible();
  await expect(page.getByRole("button", { name: /保存|发布并生效/ })).toHaveCount(0);
  await expect(page.locator("textarea")).toHaveCount(0);
  await expect(page.getByText("发布图一致", { exact: true })).toHaveCount(10);
  await expect(page.getByRole("region", { name: "GEO 内置评审" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "GEO 内置评审" })).toBeVisible();
  for (const name of ["风格评审", "候选仲裁", "指标评审", "离线回答"]) {
    const workflow = page.getByRole("article").filter({ has: page.getByRole("heading", { level: 3, name }) });
    await expect(workflow).toBeVisible();
    await expect(workflow.getByText(/由 GEO Worker 执行，不读取 Dify 工作流/)).toBeVisible();
    await expect(workflow.getByRole("link", { name: /Dify/ })).toHaveCount(0);
  }
  await expect(page.getByText("GEO 原生执行", { exact: true })).toHaveCount(4);
  await expect(page.getByRole("heading", { level: 3, name: "参考内容翻译" })).toBeVisible();
  await expect(page.getByRole("region", { name: "预留能力" })).toBeVisible();
  await expect(page.getByText("预留，暂不可用", { exact: true })).toBeVisible();
  await expect(page.getByText(/待迁移|待接入统一运行时/)).toHaveCount(0);
  const popupPromise = page.waitForEvent("popup");
  await difyLinks.first().click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL("http://127.0.0.1:15000/app/fixture-app-0/workflow");
  await popup.close();
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("dify-board-desktop.png"), fullPage: true });
});

test("DIFY-BOARD-03: migrated workflow states explain impact and next action", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  try {
    await setDifyScenario(request, "style-drifted");
    await page.goto(`/projects/${PROJECT_ID}?tab=prompts&state=drifted`);
    let workflow = page.getByRole("region", { name: "风格画像生成" });
    await expect(workflow.getByText("运行已阻断", { exact: true })).toBeVisible();
    await expect(workflow.getByText("发布图已漂移", { exact: true })).toBeVisible();
    await expect(workflow.getByText(/新图不会用于业务任务/)).toBeVisible();
    await expect(workflow.getByText(/注册、验证并激活新的 Workflow Release/)).toBeVisible();

    await setDifyScenario(request, "recommendation-blocked");
    await page.goto(`/projects/${PROJECT_ID}?tab=prompts&state=blocked`);
    workflow = page.getByRole("region", { name: "证据建议生成" });
    await expect(workflow.getByText("运行已阻断", { exact: true })).toBeVisible();
    await expect(workflow.getByText("发布图一致", { exact: true })).toBeVisible();
    await expect(workflow.getByText(/Dify API 凭据不可用/)).toBeVisible();
    await expect(workflow.getByText(/修复或轮换凭据/)).toBeVisible();

    await setDifyScenario(request, "migration-pending");
    await page.goto(`/projects/${PROJECT_ID}?tab=prompts&state=migration-pending`);
    for (const name of ["风格画像生成", "证据建议生成"]) {
      workflow = page.getByRole("region", { name });
      await expect(workflow.getByText("尚未完成迁移", { exact: true })).toBeVisible();
      await expect(workflow.getByText("未验证发布图", { exact: true })).toBeVisible();
      await expect(workflow.getByText(/旧版业务结果（如有）不计作 Dify 验证/)).toBeVisible();
      await expect(workflow.getByText(/完成真实 Canary 并激活/)).toBeVisible();
      await expect(workflow.getByText("尚未绑定 Dify 应用", { exact: true })).toBeVisible();
      await expect(workflow.getByRole("link", { name: "打开 Dify 工作流" })).toHaveCount(0);
    }
  } finally {
    await setDifyScenario(request, "default");
  }
  expect(runtimeErrors).toEqual([]);
});

async function setDifyScenario(request: APIRequestContext, scenario: string): Promise<void> {
  const response = await request.post("http://127.0.0.1:3199/__dify_runtime_scenario", {
    data: { scenario }
  });
  expect(response.ok()).toBe(true);
}

test("DIFY-BOARD-02: published Prompt remains readable on mobile", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=prompts`);

  await expect(page.getByRole("heading", { level: 2, name: "Dify 工作流" })).toBeVisible();
  await expect(page.getByText(/Dify 托管的.*证据建议生成/)).toBeVisible();
  await page.getByText("输入变量与版本信息", { exact: true }).first().click();
  await expect(page.getByText(/业务上下文 JSON/).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("dify-board-mobile.png"), fullPage: true });
});
