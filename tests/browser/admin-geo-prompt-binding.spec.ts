import os from "node:os";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const CAMPAIGN_ID = "00000000-0000-4000-8000-000000000031";
const OPPORTUNITY_ID = "00000000-0000-4000-8000-000000000051";
const SKILL_ID = "00000000-0000-4000-8000-000000000071";
const RELEASE_ID = "00000000-0000-4000-8000-000000000073";
const BINDING_ID = "00000000-0000-4000-8000-000000000074";
const BRIEF_ID = "00000000-0000-4000-8000-000000000075";
const ATTEMPT_ID = "00000000-0000-4000-8000-000000000076";
const LEGACY_BUNDLE_ID = "00000000-0000-4000-8000-000000000078";
const RELEASE_HASH = "d".repeat(64);

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

test("F014: Opportunity binding and Bundle creation freeze the approved Prompt Release identity", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&placement_stage=evidence&campaign_id=${CAMPAIGN_ID}&opportunity_id=${OPPORTUNITY_ID}&brief_version_id=${BRIEF_ID}&attempt_id=${ATTEMPT_ID}&skill_id=${SKILL_ID}`);

  await expect(page.getByText("尚未绑定已批准 Prompt 发布版本。", { exact: true }).first()).toBeVisible();
  const administration = page.locator("details").filter({ has: page.getByText("高级：Prompt 规则与版本管理", { exact: true }) });
  await administration.locator(":scope > summary").click();
  await expect(administration.getByRole("button", { name: "撤销发布版本" })).toBeVisible();
  await administration.locator('select[name="template_release_id"]').selectOption(RELEASE_ID);
  await administration.getByRole("textbox", { name: "变更原因" }).fill("Pin approved release for this Opportunity");
  await administration.getByRole("button", { name: "确认并追加绑定" }).click();
  await expect(administration.getByRole("status")).toContainText("Opportunity 已追加 Prompt Release 绑定");
  await expect(page.getByText("placement.owned_site.article", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("v5", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("v2", { exact: true }).first()).toBeVisible();

  const bundleButton = page.getByRole("button", { name: "确认并冻结生成输入" });
  await expect(bundleButton).toBeEnabled();
  const confirmation = page.locator('input[name="confirm_prompt_release"]');
  await expect(confirmation).toHaveAttribute("required", "");
  await confirmation.check();
  await bundleButton.click();
  await expect(page.getByRole("status").filter({ hasText: "Prompt Bundle 工件已冻结" }))
    .toContainText("Prompt Bundle 工件已冻结");

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string; path: string; body: Record<string, unknown>;
  }>;
  const bindingRequest = logged.find((item) => item.method === "POST"
    && item.path.endsWith(`/opportunities/${OPPORTUNITY_ID}/prompt-release-bindings`));
  expect(bindingRequest?.body).toMatchObject({
    template_release_id: RELEASE_ID,
    reason: "Pin approved release for this Opportunity",
    expected_binding_version: 1
  });
  expect(bindingRequest?.body).not.toHaveProperty("expected_previous_binding_id");
  const bundleRequest = logged.find((item) => item.method === "POST"
    && item.path.endsWith(`/brief-versions/${BRIEF_ID}/prompt-bundles`));
  expect(bundleRequest?.body).toMatchObject({
    campaign_id: CAMPAIGN_ID,
    opportunity_id: OPPORTUNITY_ID,
    prompt_release_binding_id: BINDING_ID,
    confirmed_release_hash: RELEASE_HASH,
    evidence_pack_attempt_id: ATTEMPT_ID
  });
  expect(bundleRequest?.body).not.toHaveProperty("template_release_id");
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-prompt-binding.png"), fullPage: true });
  expect(runtimeErrors).toEqual([]);
});

test("legacy Prompt Bundle remains readable but cannot start new generation work", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  expect((await request.post(`${FIXTURE_API}/__legacy_prompt_bundle`)).ok()).toBe(true);

  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&placement_stage=generation&campaign_id=${CAMPAIGN_ID}&opportunity_id=${OPPORTUNITY_ID}&brief_version_id=${BRIEF_ID}&attempt_id=${ATTEMPT_ID}&bundle_id=${LEGACY_BUNDLE_ID}`);

  const legacyNotice = page.getByTestId("legacy-prompt-bundle");
  await expect(legacyNotice).toContainText("迁移历史生成输入只读");
  await expect(legacyNotice.getByRole("link", { name: "返回准备证据并重建" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始生成" })).toHaveCount(0);
  await expect(page.getByText("缺少已批准 Prompt Release 绑定", { exact: false })).toBeVisible();
  expect(runtimeErrors).toEqual([]);
});
