import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const SUITE_ID = "00000000-0000-4000-8000-000000000707";
const SOURCE_REVISION_ID = "00000000-0000-4000-8000-000000000703";
const EXISTING_STYLE_COLLECTION_JOB_ID = "00000000-0000-4000-8000-000000000712";

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

test.beforeEach(async ({ request }) => resetFixture(request));

test("M1-SYNTH-WEB-01: Admin admits a server-owned Style Collection job and observes its state", async ({ page, request }, testInfo) => {
  test.setTimeout(75_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_suite_id=${SUITE_ID}&synthetic_job_id=${EXISTING_STYLE_COLLECTION_JOB_ID}`);

  await expect(page.getByRole("heading", { level: 2, name: "Synthetic Lab" })).toBeVisible();
  await expect(page.getByText("synthetic = true", { exact: true })).toBeVisible();
  await expect(page.getByText("test_only = true", { exact: true })).toBeVisible();
  await expect(page.getByText("publication_eligible = false", { exact: true })).toBeVisible();
  const warnings = page.getByRole("region", { name: "Warning 数量、占比与分层" });
  await expect(warnings).toContainText("2");
  await expect(warnings).toContainText("5");
  await expect(warnings).toContainText("40%");
  await expect(warnings).toContainText("derived_or_unknown");
  await expect(warnings.getByText("guided_scenario", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "yes", exact: true })).toBeVisible();

  const admissionSection = page.locator("details").filter({
    has: page.getByText("排队自动 Style Collection", { exact: true })
  });
  await admissionSection.locator("summary").click();
  const admissionForm = admissionSection.locator("form");
  await expect(admissionForm.getByLabel("Style Source")).toHaveValue(SOURCE_REVISION_ID);
  await expect(admissionForm.getByLabel("Approved adapter")).toBeEnabled();
  await expect(admissionForm.getByLabel("Login Secret Reference")).toHaveValue("");
  await expect(admissionForm.locator('input[name="job_id"]')).toHaveCount(0);
  await expect(admissionForm.locator('input[name="resource_id"]')).toHaveCount(0);
  await admissionForm.getByRole("button", { name: "批准并排队采集" }).click();
  await expect(admissionForm.getByRole("status")).toContainText("Style Collection 已通过授权与 live canary 门禁并排队。");
  const resultLink = admissionForm.getByRole("link", { name: "打开 Job" });
  const resultHref = await resultLink.getAttribute("href");
  const admittedJobId = new URL(resultHref || "", "http://fixture.invalid")
    .searchParams.get("synthetic_job_id");
  expect(admittedJobId).not.toBeNull();
  if (!admittedJobId) throw new Error("Style Collection admission did not return a Job identity");
  expect(admittedJobId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(admittedJobId).not.toBe(EXISTING_STYLE_COLLECTION_JOB_ID);
  await expect(admissionForm.getByRole("status")).toContainText(admittedJobId);

  await resultLink.click();
  await expect(page).toHaveURL(new RegExp(`synthetic_job_id=${admittedJobId}`));
  await expect(page.getByText("style_collection", { exact: true })).toBeVisible();
  await expect(page.getByText("queued", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "取消任务" }).click();
  await expect(page.getByRole("status").last()).toContainText("任务取消已记录");
  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{ method: string; path: string; body?: Record<string, unknown> }>;
  const admission = logged.find((entry) => entry.method === "POST" && entry.path.endsWith("/jobs/style-collection"));
  expect(admission?.body).toEqual({
    style_source_revision_id: SOURCE_REVISION_ID,
    adapter_release: "manual-import-v1-with-an-extraordinarily-long-release-identity-for-overflow-validation",
    login_secret_reference_id: null
  });
  expect(logged.some((entry) => entry.method === "POST" && entry.path.endsWith(`/jobs/${admittedJobId}/cancel`))).toBe(true);
  expect(JSON.stringify(admission?.body)).not.toContain("job_id");
  expect(JSON.stringify(admission?.body)).not.toContain("input_hash");
  expect(JSON.stringify(admission?.body)).not.toContain("resource_id");
  expect(JSON.stringify(logged)).not.toContain("raw_text");
  expect(JSON.stringify(logged)).not.toContain("secret_value");
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("synthetic-lab-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { level: 2, name: "Synthetic Lab" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("synthetic-lab-mobile.png"), fullPage: true });
});

test("M1-SYNTH-WEB-02: empty and unavailable projections fail closed", async ({ page, request }) => {
  await setMode(request, "empty");
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab`);
  await expect(page.getByText("暂无 Style Source。", { exact: true })).toBeVisible();
  await expect(page.getByText("暂无可分层 warning evidence；不会将缺失证据记为 0。", { exact: true })).toBeVisible();

  await setMode(request, "unavailable");
  await page.reload();
  await expect(page.getByRole("alert").filter({ hasText: "Synthetic Lab unavailable" }).first()).toBeVisible();
  const admissionSection = page.locator("details").filter({
    has: page.getByText("排队自动 Style Collection", { exact: true })
  });
  await admissionSection.locator("summary").click();
  await expect(admissionSection.getByRole("button", { name: "批准并排队采集" })).toBeDisabled();
});

test("M1-SYNTH-WEB-03: state conflicts are explicit and keep the boundary visible", async ({ page, request }) => {
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_job_id=${EXISTING_STYLE_COLLECTION_JOB_ID}`);
  await setMode(request, "conflict");
  await page.getByRole("button", { name: "取消任务" }).click();
  const conflict = page.getByRole("alert").filter({ hasText: "状态冲突" });
  await expect(conflict).toContainText("409");
  await expect(conflict).toContainText("状态冲突");
  await expect(page.getByText("publication_eligible = false", { exact: true })).toBeVisible();
});
