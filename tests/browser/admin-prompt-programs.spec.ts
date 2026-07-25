import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const PROGRAM_ID = "00000000-0000-4000-8000-000000000501";
const CANDIDATE_ID = "00000000-0000-4000-8000-000000000503";
const BOOTSTRAP_TEST_SET_ID = "00000000-0000-4000-8000-000000000910";

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

test("M1-PROMPT-WEB-01: Admin governs, diffs and binds Prompt Program releases", async ({ page, request }, testInfo) => {
  test.setTimeout(75_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=prompts&prompt_program_id=${PROGRAM_ID}&prompt_release_id=${CANDIDATE_ID}`);

  await expect(page.getByRole("heading", { level: 2, name: "Prompt 程序" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "发布版本 v2" })).toBeVisible();
  await expect(page.locator('option[value="reference_translation"]')).toHaveAttribute("disabled", "");
  await expect(page.getByText("synthetic_lab.generation", { exact: true }).first()).toBeVisible();

  const diffSection = page.locator("section").filter({
    has: page.getByRole("heading", { name: "固定输入差异" })
  }).last();
  await diffSection.getByLabel("固定输入（JSON 对象）").fill(JSON.stringify({
    scenario: "sensitive Australian consumer query"
  }));
  await diffSection.getByRole("button", { name: "比较版本" }).click();
  const diffResult = page.getByRole("region", { name: "Prompt 发布版本差异结果" });
  await expect(diffResult).toContainText("user_template");
  await expect(diffResult).toContainText("基线发布版本");
  await expect(diffResult).toContainText("候选版本发布版本");
  await expect(diffResult).not.toContainText("sensitive Australian consumer query");

  const testSection = page.locator("section").filter({
    has: page.getByRole("heading", { name: "测试执行" })
  }).last();
  await expect(testSection.getByLabel("已批准运行时")).toHaveValue(
    "00000000-0000-4000-8000-000000000510"
  );
  await expect(testSection).not.toContainText("Runtime Manifest ID");
  await expect(testSection).not.toContainText("Adapter Release ID");
  await expect(testSection).not.toContainText("Model Release ID");
  await testSection.getByRole("button", { name: "运行固定测试集" }).click();
  await expect(testSection.getByRole("status")).toContainText("测试任务已排队");
  await expect(testSection.getByRole("status")).toContainText("输入 SHA-256");
  await expect(page.getByText(/prompt-test:00000000-0000-4000-8000-000000000505/).first()).toBeVisible();

  const governance = page.locator("section").filter({
    has: page.getByRole("heading", { name: "批准与冻结" })
  }).last();
  await expect(governance.getByRole("button", { name: "批准" })).toBeEnabled();
  await governance.getByRole("button", { name: "批准" }).click();
  await expect(governance.getByRole("status")).toContainText("发布版本已批准");
  await expect(governance.getByRole("button", { name: "冻结" })).toBeEnabled();
  await governance.getByRole("button", { name: "冻结" }).click();
  await expect(governance.getByRole("status").last()).toContainText("发布版本已冻结");

  const binding = page.locator("section").filter({
    has: page.getByRole("heading", { name: "运行时绑定" })
  }).last();
  await expect(binding.getByRole("button", { name: "绑定冻结发布版本" })).toBeEnabled();
  await expect(binding.getByText("用途（由冻结发布版本固定）", { exact: true })).toBeVisible();
  await expect(binding.locator('input[name="purpose"]')).toBeHidden();
  await expect(binding.locator('input[name="expected_version"]')).toHaveValue("0");
  await binding.locator('input[name="purpose"]').evaluate((element) => {
    (element as HTMLInputElement).value = "synthetic_lab.style_judge";
  });
  await binding.getByRole("button", { name: "绑定冻结发布版本" }).click();
  await expect(binding.getByRole("alert")).toContainText("用途或冻结发布版本身份已变化");
  let logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string;
    path: string;
  }>;
  expect(logged.some((entry) => entry.path.endsWith("/prompt-program-bindings") && entry.method === "POST")).toBe(false);
  await page.reload();
  const restoredBinding = page.locator("section").filter({
    has: page.getByRole("heading", { name: "运行时绑定" })
  }).last();
  await restoredBinding.getByRole("button", { name: "绑定冻结发布版本" }).click();
  await expect(restoredBinding.getByRole("status")).toContainText("冻结发布版本已绑定");
  await expect(restoredBinding.getByRole("status")).toContainText("绑定版本");

  const retirement = page.locator("section").filter({
    has: page.getByRole("heading", { name: "批准与冻结" })
  }).last();
  await retirement.getByText("停止该发布版本的新运行时解析", { exact: true }).click();
  await retirement.getByRole("button", { name: "退役发布版本" }).click();
  await expect(retirement.getByRole("status").last()).toContainText("发布版本已退役");
  await expect(
    page.getByRole("region", { name: "发布版本 v2" }).getByText("已退役", { exact: true }).first()
  ).toBeVisible();
  await expect(
    page.locator("section").filter({ has: page.getByRole("heading", { name: "运行时绑定" }) })
      .last()
      .getByRole("button", { name: "绑定冻结发布版本" })
  ).toBeDisabled();

  const nextRelease = page.locator("details").filter({
    has: page.getByText("创建下一版发布版本", { exact: true })
  });
  await nextRelease.locator(":scope > summary").click();
  await expect(nextRelease.getByText("用途（由 Prompt 程序类型固定）", { exact: true })).toBeVisible();
  await expect(nextRelease.locator('input[name="purpose"]')).toBeHidden();
  await expect(nextRelease.locator('input[name="test_set_id"]')).toBeHidden();
  await expect(nextRelease.locator('input[name="test_set_hash"]')).toBeHidden();
  await expect(nextRelease.getByLabel("固定测试集（目录）")).toHaveValue(
    `${BOOTSTRAP_TEST_SET_ID}:1:${"2".repeat(64)}`
  );
  await nextRelease.getByLabel("系统模板").fill("Return governed JSON for {{scenario}}.");
  await nextRelease.getByLabel("用户模板").fill("Generate a concise {{scenario}} result.");
  await nextRelease.getByText("冻结 Schema、模型策略与测试集", { exact: true }).click();
  await nextRelease.getByRole("button", { name: "创建 v3" }).click();
  await expect(nextRelease.getByRole("status")).toContainText("发布版本 v3 已创建");
  await nextRelease.getByRole("link", { name: "打开结果" }).click();
  await expect(page.getByRole("heading", { level: 3, name: "发布版本 v3" })).toBeVisible();

  logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string;
    path: string;
  }>;
  expect(logged.some((entry) => entry.path.endsWith("/diff") && entry.method === "POST")).toBe(true);
  expect(logged.some((entry) => entry.path.endsWith("/tests") && entry.method === "POST")).toBe(true);
  expect(logged.some((entry) => entry.path.endsWith("/approve") && entry.method === "POST")).toBe(true);
  expect(logged.some((entry) => entry.path.endsWith("/freeze") && entry.method === "POST")).toBe(true);
  expect(logged.some((entry) => entry.path.endsWith("/retire") && entry.method === "POST")).toBe(true);
  expect(logged.some((entry) => entry.path.endsWith("/prompt-program-bindings") && entry.method === "POST")).toBe(true);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("prompt-programs-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { level: 2, name: "Prompt 程序" })).toBeVisible();
  const documentFitsViewport = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth
  );
  expect(documentFitsViewport).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("prompt-programs-mobile.png"), fullPage: true });
});
