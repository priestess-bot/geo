import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const SUITE_ID = "00000000-0000-4000-8000-000000000707";
const SOURCE_REVISION_ID = "00000000-0000-4000-8000-000000000703";
const EXISTING_STYLE_COLLECTION_JOB_ID = "00000000-0000-4000-8000-000000000712";
const COMPLETED_REVIEW_JOB_A_ID = "00000000-0000-4000-8000-000000000716";
const COMPLETED_REVIEW_JOB_B_ID = "00000000-0000-4000-8000-000000000717";
const CANDIDATE_CORPUS_JOB_ID = "00000000-0000-4000-8000-000000000718";
const APPROVED_CORPUS_JOB_ID = "00000000-0000-4000-8000-000000000719";
const QUESTION_SET_ID = "00000000-0000-4000-8000-000000000720";
const RUNTIME_SELECTION_ID = "00000000-0000-4000-8000-000000000713";
const MANUAL_PREVIEW_ID = "00000000-0000-4000-8000-000000000723";

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

async function requestLog(request: APIRequestContext): Promise<Array<{
  method: string;
  path: string;
  body?: Record<string, unknown>;
}>> {
  let lastError: unknown;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await request.get(`${FIXTURE_API}/__requests`);
      expect(response.ok()).toBe(true);
      return await response.json() as Array<{
        method: string;
        path: string;
        body?: Record<string, unknown>;
      }>;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 200 * (attempt + 1)));
    }
  }
  throw lastError;
}

test.beforeEach(async ({ request }) => resetFixture(request));

test("M1-SYNTH-WEB-01: Admin admits a server-owned Style Collection job and observes its state", async ({ page, request }, testInfo) => {
  test.setTimeout(75_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_suite_id=${SUITE_ID}&synthetic_job_id=${EXISTING_STYLE_COLLECTION_JOB_ID}`);

  await expect(page.getByRole("heading", { level: 2, name: "合成测评实验室" })).toBeVisible();
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
  const logged = await requestLog(request);
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
  await expect(page.getByRole("heading", { level: 2, name: "合成测评实验室" })).toBeVisible();
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
  await expect(page.getByRole("alert").filter({ hasText: "合成测评实验室暂不可用" }).first()).toBeVisible();
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

test("M3-SYNTH-WEB-01: Corpus approval and three-arm jobs use selector-only admission", async ({ page, request }) => {
  test.setTimeout(75_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab`);

  const candidate = page.getByRole("group", {
    name: "从通过或 Warning 的 Review 结果冻结候选 Corpus"
  });
  await candidate.getByLabel("Completed Review Jobs").selectOption([
    COMPLETED_REVIEW_JOB_A_ID,
    COMPLETED_REVIEW_JOB_B_ID
  ]);
  await candidate.getByRole("button", { name: "冻结候选 Corpus" }).click();
  await expect(candidate.locator("..").getByRole("status")).toContainText(
    "候选 Corpus 已冻结 Review lineage 并排队。"
  );

  const approval = page.getByRole("group", { name: "批准候选 Corpus" });
  await expect(approval.getByLabel("Candidate Corpus")).toHaveValue(CANDIDATE_CORPUS_JOB_ID);
  await approval.getByRole("button", { name: "批准并冻结" }).click();
  await expect(approval.locator("..").getByRole("status")).toContainText(
    "Corpus 人工批准已排队"
  );

  const experiment = page.getByRole("group", {
    name: "运行 baseline / current / candidate 三臂配对实验"
  });
  await expect(experiment.getByLabel("Question Set")).toHaveValue(QUESTION_SET_ID);
  await expect(experiment.getByLabel("Current approved Corpus")).toHaveValue(
    APPROVED_CORPUS_JOB_ID
  );
  await expect(experiment.getByLabel("Candidate Corpus")).toHaveValue(
    CANDIDATE_CORPUS_JOB_ID
  );
  await expect(experiment.getByLabel("Minimum valid pair ratio")).toHaveValue("0.8");
  await experiment.getByRole("button", { name: "运行三臂实验" }).click();
  await expect(experiment.locator("..").getByRole("status")).toContainText(
    "三臂配对 Offline Experiment 已冻结并排队。"
  );

  const logged = await requestLog(request);
  const writes = logged.filter((entry) => entry.method === "POST"
    && (entry.path.endsWith("/jobs/corpus")
      || entry.path.endsWith("/jobs/offline-experiment")));
  expect(writes.map((entry) => entry.body)).toEqual([
    {
      role: "new_candidate_corpus",
      review_job_ids: [COMPLETED_REVIEW_JOB_A_ID, COMPLETED_REVIEW_JOB_B_ID],
      source_corpus_job_id: null
    },
    {
      role: "current_approved_corpus",
      review_job_ids: [],
      source_corpus_job_id: CANDIDATE_CORPUS_JOB_ID
    },
    {
      question_set_id: QUESTION_SET_ID,
      current_corpus_job_id: APPROVED_CORPUS_JOB_ID,
      candidate_corpus_job_id: CANDIDATE_CORPUS_JOB_ID,
      runtime_selection_id: RUNTIME_SELECTION_ID,
      minimum_valid_pair_ratio: 0.8
    }
  ]);
  for (const entry of writes) {
    expect(entry.body).not.toHaveProperty("job_id");
    expect(entry.body).not.toHaveProperty("input_hash");
    expect(entry.body).not.toHaveProperty("runtime_inputs");
  }
  expect(runtimeErrors).toEqual([]);
});

test("M1-SYNTH-GOV-UX-01: governance forms start neutral and approvals require complete allowances", async ({ page, request }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await setMode(request, "governance");
  await page.goto(`/projects/${PROJECT_ID}?tab=synthetic-lab`);
  await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT_ID}\\?tab=synthetic-lab`));
  await expect(page).toHaveTitle("GEO 项目管理台");

  const authorizationCommands = page.locator("details").filter({
    has: page.getByText("决策、撤销与重评", { exact: true })
  });
  await authorizationCommands.locator("summary").click();
  const authorizationDecision = authorizationCommands.getByLabel("Authorization 决策");
  const authorizationSubmit = authorizationCommands.getByRole("button", {
    name: "记录授权决策"
  });
  await expect(authorizationDecision).toHaveValue("");
  await expect(authorizationSubmit).toBeDisabled();
  await expect(authorizationCommands.getByLabel("自动风格采集")).not.toBeChecked();
  await expect(authorizationCommands.getByLabel("证据引用")).toBeDisabled();

  await authorizationDecision.selectOption("approved");
  await expect(authorizationCommands.getByLabel("证据引用")).toBeEnabled();
  for (const label of [
    "证据引用",
    "自动风格采集",
    "Requests / period",
    "Period seconds",
    "Max concurrency",
    "Expires at"
  ]) {
    await expect(authorizationCommands.getByLabel(label)).toHaveAttribute("required", "");
  }
  await authorizationSubmit.click();
  await expect(authorizationCommands.getByLabel("证据引用")).toBeFocused();
  expect((await requestLog(request)).some((entry) => entry.path.endsWith("/decision"))).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("synthetic-governance-neutral.png"), fullPage: false });

  const profileDecision = page.getByLabel("Profile 审批决定");
  await expect(profileDecision).toHaveValue("");
  await expect(page.getByRole("button", { name: "记录决定" })).toBeDisabled();

  const manualUpload = page.locator("details").filter({
    has: page.getByText("上传 text / CSV / JSONL", { exact: true })
  });
  await manualUpload.locator("summary").click();
  await expect(manualUpload.getByLabel("来源权利")).toHaveValue("");
  await expect(manualUpload.getByLabel("来源权利")).toHaveAttribute("required", "");

  expect((await request.post(`${FIXTURE_API}/__secret_mode`, {
    data: { role: "analyst" }
  })).ok()).toBe(true);
  await page.reload();
  const analystAuthorization = page.locator("details").filter({
    has: page.getByText("决策、撤销与重评", { exact: true })
  });
  await analystAuthorization.locator("summary").click();
  await expect(analystAuthorization.getByLabel("Authorization 决策")).toBeDisabled();
  await expect(page.getByLabel("Profile 审批决定")).toBeDisabled();
  await expect(page.getByRole("button", { name: "记录决定" })).toBeDisabled();
  expect(runtimeErrors).toEqual([]);
});

test("M1-SYNTH-GOV-UX-02: a manual preview submitter cannot self-approve", async ({ page, request }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  const previewUrl = `/projects/${PROJECT_ID}?tab=synthetic-lab&synthetic_import_preview_id=${MANUAL_PREVIEW_ID}`;
  await page.goto(previewUrl);
  const selfReview = page.getByRole("group", {
    name: "独立复核 · australian-reddit-style-samples.txt"
  });
  await expect(page.getByText("提交者不能复核自己的导入预览", { exact: false })).toBeVisible();
  await expect(selfReview.getByRole("button", { name: "批准所选样本" })).toBeDisabled();
  expect((await requestLog(request)).some((entry) => entry.path.endsWith("/approve"))).toBe(false);

  expect((await request.post(`${FIXTURE_API}/__secret_mode`, {
    data: { actor_id: "actor-b", role: "owner" }
  })).ok()).toBe(true);
  await page.reload();
  const independentReview = page.getByRole("group", {
    name: "独立复核 · australian-reddit-style-samples.txt"
  });
  const selectableRow = independentReview.locator('input[name="selected_row_numbers"][value="1"]');
  const blockedRow = independentReview.locator('input[name="selected_row_numbers"][value="2"]');
  await expect(selectableRow).toBeEnabled();
  await expect(selectableRow).toBeChecked();
  await expect(blockedRow).toBeDisabled();
  await expect(independentReview).toContainText("restricted_identifier");
  await independentReview.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("synthetic-independent-review.png"), fullPage: false });
  await independentReview.getByLabel("澳洲英文已明审").check();
  await independentReview.getByLabel("匿名化已明审").check();
  await setMode(request, "manual_approval_rejected");
  await independentReview.getByRole("button", { name: "批准所选样本" }).click();
  const backendRejection = page.getByRole("alert").filter({
    hasText: "权限不足，或授权/双人批准条件未满足"
  });
  await expect(backendRejection).toContainText("403");
  await page.screenshot({ path: testInfo.outputPath("synthetic-review-backend-rejection.png"), fullPage: false });

  await setMode(request, "normal");
  await independentReview.getByLabel("澳洲英文已明审").check();
  await independentReview.getByLabel("匿名化已明审").check();
  await independentReview.getByRole("button", { name: "批准所选样本" }).click();
  await expect(page.getByRole("status").filter({ hasText: "导入已批准" })).toContainText(
    "接受 1，拒绝 1"
  );
  const approvals = (await requestLog(request)).filter(
    (entry) => entry.method === "POST" && entry.path.endsWith("/approve")
  );
  expect(approvals).toHaveLength(2);
  for (const approval of approvals) {
    expect(approval.body).toEqual({
      expected_version: 1,
      selected_row_numbers: [1],
      au_english_verified: true,
      anonymization_verified: true
    });
  }
  expect(runtimeErrors).toEqual([]);
});
