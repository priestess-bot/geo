import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const REFERENCE_ID = "00000000-0000-4000-8000-000000000601";
const SECRET_A = "SECRET_BROWSER_CANARY_A_7619";
const SECRET_B = "SECRET_BROWSER_CANARY_B_4285";

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

async function setSecretMode(
  request: APIRequestContext,
  values: { actor_id?: "actor-a" | "actor-b"; role?: string; unavailable?: boolean }
): Promise<void> {
  expect((await request.post(`${FIXTURE_API}/__secret_mode`, { data: values })).ok()).toBe(true);
}

function innermostSection(page: Page, heading: string) {
  return page.locator("section").filter({
    has: page.getByRole("heading", { name: heading })
  }).last();
}

test.beforeEach(async ({ request }) => resetFixture(request));

test("M1-SECRET-WEB-01: Admin completes write-only two-person rotation lifecycle", async ({ page, request }, testInfo) => {
  test.setTimeout(90_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=secrets`);

  await expect(page.getByRole("heading", { level: 2, name: "密钥库" })).toBeVisible();
  await expect(page.getByText("暂无 Secret Reference", { exact: true })).toBeVisible();
  const createPanel = page.locator("details").filter({
    has: page.getByText("新建 Secret Reference", { exact: true })
  });
  await createPanel.locator(":scope > summary").click();
  const createSecret = createPanel.getByLabel("SecretValue · write-only · max 64 KiB");
  await expect(createSecret).toHaveAttribute("required", "");
  await expect(createSecret).toHaveAttribute("maxlength", "65536");
  await expect(createPanel.getByLabel("Reference ID")).toHaveCount(0);
  await createPanel.getByLabel("用途").selectOption("model_provider.openai");
  await createSecret.fill(SECRET_A);
  await createPanel.getByRole("button", { name: "创建 Reference" }).click();
  await expect(createPanel.getByRole("status")).toContainText("Secret Reference 已创建");
  await expect(createPanel.getByLabel("SecretValue · write-only · max 64 KiB")).toHaveValue("");
  await expect(page.getByRole("heading", { level: 3, name: "Secret Reference" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(SECRET_A);

  let verifyBand = innermostSection(page, "Canary 验证与双人激活");
  await expect(verifyBand.getByRole("button", { name: "验证 Canary" })).toBeEnabled();
  await verifyBand.getByRole("button", { name: "验证 Canary" }).click();
  await expect(verifyBand.getByRole("status")).toContainText("canary 已验证");
  await expect(verifyBand.getByRole("button", { name: "第二人激活" })).toBeEnabled();
  await verifyBand.getByRole("button", { name: "第二人激活" }).click();
  await expect(verifyBand.getByRole("alert")).toContainText("403");
  await expect(verifyBand.getByRole("alert")).toContainText("双人激活条件未满足");

  await setSecretMode(request, { actor_id: "actor-b" });
  await page.reload();
  verifyBand = innermostSection(page, "Canary 验证与双人激活");
  await verifyBand.getByRole("button", { name: "第二人激活" }).click();
  await expect(verifyBand.getByRole("status")).toContainText("第二位操作人已激活");

  const rotationBand = innermostSection(page, "Stage Rotation");
  const rotationSecret = rotationBand.getByLabel("SecretValue · write-only · max 64 KiB");
  await expect(rotationSecret).toBeEnabled();
  await rotationSecret.fill(SECRET_B);
  await rotationBand.getByRole("button", { name: "暂存新版本" }).click();
  await expect(rotationBand.getByRole("status")).toContainText("Rotation v2 已暂存");
  await expect(rotationBand.getByLabel("SecretValue · write-only · max 64 KiB")).toHaveValue("");
  await expect(page.locator("body")).not.toContainText(SECRET_B);

  verifyBand = innermostSection(page, "Canary 验证与双人激活");
  await verifyBand.getByRole("button", { name: "验证 Canary" }).click();
  await expect(verifyBand.getByRole("status").filter({ hasText: "canary 已验证" })).toBeVisible();
  await setSecretMode(request, { actor_id: "actor-a" });
  await page.reload();
  verifyBand = innermostSection(page, "Canary 验证与双人激活");
  await verifyBand.getByRole("button", { name: "第二人激活" }).click();
  await expect(verifyBand.getByRole("status")).toContainText("第二位操作人已激活");

  const revokeBand = innermostSection(page, "Revoke Version");
  await revokeBand.getByLabel("Secret version").fill("1");
  await revokeBand.getByRole("button", { name: "撤销版本" }).click();
  await expect(revokeBand.getByRole("status")).toContainText("Secret Version 已撤销");
  await revokeBand.getByLabel("Secret version").fill("1");
  await revokeBand.getByRole("button", { name: "撤销版本" }).click();
  await expect(revokeBand.getByRole("alert")).toContainText("409");
  await expect(revokeBand.getByRole("alert")).toContainText("状态冲突");

  const audit = innermostSection(page, "Audit 与版本状态");
  await expect(audit).toContainText("version activated");
  await expect(audit).toContainText("version revoked");
  await expect(audit).toContainText("v8");
  const loggedText = await (await request.get(`${FIXTURE_API}/__requests`)).text();
  expect(loggedText).not.toContain(SECRET_A);
  expect(loggedText).not.toContain(SECRET_B);
  expect(loggedText).toContain("[REDACTED]");
  await expect(page.locator("body")).not.toContainText(SECRET_A);
  await expect(page.locator("body")).not.toContainText(SECRET_B);
  expect(runtimeErrors).toEqual([]);

  await page.screenshot({ path: testInfo.outputPath("secret-store-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("secret-store-mobile.png"), fullPage: true });
});

test("M1-SECRET-WEB-02: Secret Store fails closed for unavailable runtime and analyst role", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await setSecretMode(request, { unavailable: true });
  await page.goto(`/projects/${PROJECT_ID}?tab=secrets`);
  const unavailable = page.getByRole("alert").filter({ hasText: "所有写入保持关闭" });
  await expect(unavailable).toContainText("密钥库暂不可用");
  const createPanel = page.locator("details").filter({
    has: page.getByText("新建 Secret Reference", { exact: true })
  });
  await createPanel.locator(":scope > summary").click();
  await expect(createPanel.getByRole("button", { name: "创建 Reference" })).toBeDisabled();
  await expect(page.getByText("暂无 Secret Reference", { exact: true })).toHaveCount(0);

  await setSecretMode(request, { unavailable: false, role: "analyst" });
  await page.reload();
  await expect(page.getByText("分析师", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "403" }).first()).toBeVisible();
  const analystCreate = page.locator("details").filter({
    has: page.getByText("新建 Secret Reference", { exact: true })
  });
  await analystCreate.locator(":scope > summary").click();
  await expect(analystCreate.getByRole("button", { name: "创建 Reference" })).toBeDisabled();
  expect(runtimeErrors).toEqual([]);
});
