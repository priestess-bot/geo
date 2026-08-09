import { expect, test, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";

test("EXT-ADMIN-ALERT-01: external operations renders actionable drift input", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));

  const response = await page.goto(
    `/projects/${PROJECT_ID}?tab=external-data`,
    { waitUntil: "networkidle" }
  );

  expect(response?.ok()).toBe(true);
  await expect(page.getByRole("heading", { level: 2, name: "外部数据与归因" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "外部运行异常" })).toBeVisible();
  await expect(page.getByText("浏览器构建漂移", { exact: true })).toBeVisible();
  await expect(page.getByText("严重", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "处理" })).toHaveAttribute(
    "href", `/projects/${PROJECT_ID}?tab=external-data&section=browser`
  );
  await expect(page.locator("[data-nextjs-dialog-overlay], [data-nextjs-toast-errors-parent]"))
    .toHaveCount(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  expect(errors).toEqual([]);
});

test("EXT-ADMIN-SURFACE-01: a new consumer surface starts fail-closed", async ({ page }) => {
  const response = await page.goto(
    `/projects/${PROJECT_ID}?tab=external-data`,
    { waitUntil: "networkidle" }
  );

  expect(response?.ok()).toBe(true);
  const form = page.getByRole("button", { name: "创建界面版本" }).locator("xpath=ancestor::form");
  await expect(form.locator('select[name="authorization_track"]')).toHaveValue("B");
  await expect(form.locator('select[name="authorization_status"]')).toHaveValue("not_assessed");
  await expect(form.locator('textarea[name="selectors"]')).toHaveValue("");
  await expect(form.locator('textarea[name="block_detectors"]')).toHaveValue("");
  await expect(form.locator('textarea[name="selectors"]')).toHaveAttribute(
    "placeholder", /实测 CSS 选择器/
  );
  await expect(page.getByRole("button", { name: "批准版本" })).toHaveCount(0);
});

test("EXT-ADMIN-CONNECTOR-01: Secret purpose follows the selected GSC/GA4 definition", async ({ page, request }) => {
  const response = await page.goto(
    `/projects/${PROJECT_ID}?tab=external-data`,
    { waitUntil: "networkidle" }
  );

  expect(response?.ok()).toBe(true);
  const form = page.getByRole("button", { name: "创建连接" }).locator("xpath=ancestor::form");
  const definition = form.getByTestId("connector-definition-select");
  const purpose = form.getByTestId("connector-secret-purpose");
  await expect(definition).toHaveValue("00000000-0000-4000-8000-000000000611");
  await expect(purpose).toHaveValue("connector.gsc");
  await expect(purpose).toHaveAttribute("readonly", "");

  await definition.selectOption("00000000-0000-4000-8000-000000000612");
  await expect(purpose).toHaveValue("connector.ga4");
  await form.getByLabel("连接名称").fill("GA4 浏览器合同测试");
  await form.getByLabel("密钥引用 ID").fill("00000000-0000-4000-8000-000000000601");
  await form.getByRole("button", { name: "创建连接" }).click();
  await expect(form.getByRole("status")).toContainText("连接已创建");

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json();
  const create = logged.find((item: { path?: string }) => item.path === `${
    "/v1/projects/00000000-0000-4000-8000-000000000001"
  }/connectors/connections`);
  expect(create?.body).toMatchObject({
    definition_id: "00000000-0000-4000-8000-000000000612",
    secret_purpose: "connector.ga4"
  });
});
