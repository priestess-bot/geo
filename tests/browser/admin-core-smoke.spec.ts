import { expect, test, type Page } from "@playwright/test";

function collectRuntimeErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

async function expectNoFrameworkErrorOverlay(page: Page): Promise<void> {
  await expect(page.locator("[data-nextjs-dialog-overlay], [data-nextjs-toast-errors-parent]"))
    .toHaveCount(0);
}

test("F025-WEB-BOOT-01: admin desktop entry renders and its primary flow responds", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);

  const response = await page.goto("/", { waitUntil: "domcontentloaded" });

  expect(response?.ok()).toBe(true);
  await expect(page).toHaveTitle("GEO 项目管理台");
  await expect(page.getByRole("heading", { level: 1, name: "GEO 项目管理台" })).toBeVisible();
  await expect(page.locator("body")).not.toBeEmpty();
  await expectNoFrameworkErrorOverlay(page);

  await page.getByRole("link", { name: /新建 GEO 项目/ }).click();

  await expect(page).toHaveURL(/\/projects\/new$/);
  await expect(page.getByRole("heading", { level: 1, name: "新建项目" })).toBeVisible();
  await expectNoFrameworkErrorOverlay(page);

  const projectName = page.getByLabel("项目名称");
  await projectName.fill("Browser smoke project");
  await expect(projectName).toHaveValue("Browser smoke project");
  await expect(page.getByRole("button", { name: "创建项目" })).toBeEnabled();
  expect(runtimeErrors).toEqual([]);
});
