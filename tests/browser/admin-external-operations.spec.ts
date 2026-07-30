import { expect, test, type Page } from "@playwright/test";

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
