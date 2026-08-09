import os from "node:os";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const CAMPAIGN_A_ID = "00000000-0000-4000-8000-000000000031";
const CAMPAIGN_B_ID = "00000000-0000-4000-8000-000000000032";
const PROTOCOL_A_ID = "00000000-0000-4000-8000-000000000041";
const PROTOCOL_DRAFT_ID = "00000000-0000-4000-8000-000000000042";
const OPPORTUNITY_A_ID = "00000000-0000-4000-8000-000000000051";
const QUERY_A_ID = "00000000-0000-4000-8000-000000000061";
const SKILL_ID = "00000000-0000-4000-8000-000000000071";
const RELEASE_ID = "00000000-0000-4000-8000-000000000073";
const BINDING_ID = "00000000-0000-4000-8000-000000000074";
const BRIEF_ID = "00000000-0000-4000-8000-000000000075";
const ATTEMPT_ID = "00000000-0000-4000-8000-000000000076";
const LEGACY_BUNDLE_ID = "00000000-0000-4000-8000-000000000078";
const FACT_ID = "00000000-0000-4000-8000-000000000105";
const EVIDENCE_ID = "00000000-0000-4000-8000-000000000106";
const PACKAGE_VERSION_ID = "00000000-0000-4000-8000-000000000112";
const PUBLICATION_ID = "00000000-0000-4000-8000-000000000113";
const SUBMISSION_ID = "00000000-0000-4000-8000-000000000114";
const QUESTION_CANDIDATE_ID = "00000000-0000-4000-8000-000000000132";
const QUESTION_SET_ID = "00000000-0000-4000-8000-000000000134";
const QUESTION_SET_ITEM_ID = "00000000-0000-4000-8000-000000000135";
const LEGACY_SIMULATION_ID = "00000000-0000-4000-8000-000000000138";
const SOURCE_STRATUM_HASH = "e748f50aa9fef8795a832a9e9b5e3734e5ce49fa0fa8534572f8efabc7cf300f";
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

test("F019-WEB-01: Admin completes governed QuestionSet binding and a non-publishable GEO simulation", async ({ page, request }) => {
  test.setTimeout(60_000);
  const runtimeErrors = collectRuntimeErrors(page);
  expect((await request.patch(
    `${FIXTURE_API}/v1/projects/${PROJECT_ID}/knowledge/fact-candidates/${FACT_ID}`,
    { data: { decision: "approved", notes: "Approved for GEO question evaluation" } }
  )).ok()).toBe(true);
  expect((await request.post(
    `${FIXTURE_API}/v1/projects/${PROJECT_ID}/knowledge/fact-candidates/${FACT_ID}/evidence`,
    { data: {
      title: "Fixture governed mower fact",
      subject_entity_id: "00000000-0000-4000-8000-000000000011",
      subject_role: "product",
      usage_rights: "public_reference",
      confidentiality: "public",
      public_citation: { disclosure_allowed: true, attribution_required: true }
    } }
  )).ok()).toBe(true);
  expect((await request.post(
    `${FIXTURE_API}/v1/projects/${PROJECT_ID}/geo/brief-versions/${BRIEF_ID}/evidence-pack-attempts`
  )).ok()).toBe(true);
  expect((await request.post(
    `${FIXTURE_API}/v1/projects/${PROJECT_ID}/geo/campaigns/${CAMPAIGN_A_ID}/opportunities/${OPPORTUNITY_A_ID}/prompt-release-bindings`,
    { data: { template_release_id: RELEASE_ID, reason: "Approved internal test release", expected_binding_version: 1 } }
  )).ok()).toBe(true);

  await page.goto(`/projects/${PROJECT_ID}?tab=measurement&workflow_view=questions&question_step=generate&campaign_id=${CAMPAIGN_A_ID}`);
  await expect(page).toHaveTitle(/GEO 项目管理台/);
  await expect(page.getByRole("heading", { name: "测量与告警" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "测试问题", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "生成 100 个测试问题" })).toBeVisible();
  const generationPanel = page.locator("section").filter({
    has: page.getByRole("heading", { name: "生成 100 个测试问题" })
  }).first();
  await generationPanel.getByText("只生成一个自定义问题（兼容旧流程）", { exact: true }).click();
  const factCheckbox = generationPanel.getByRole("checkbox", {
    name: /Fixture product specification/
  });
  await expect(factCheckbox).not.toBeChecked();
  await factCheckbox.check();
  await generationPanel.getByRole("textbox", { name: "目标人群" }).fill("Australian homeowners");
  await generationPanel.getByRole("textbox", { name: "产品或主题" }).fill("robotic lawn mower");
  await generationPanel.getByRole("textbox", { name: "具体场景" })
    .fill("Researching a reliable mower for a medium lawn");
  await generationPanel.getByRole("textbox", { name: "用户意图" }).fill("compare suitable products");
  await generationPanel.getByRole("button", { name: "生成候选问题" }).click();
  await expect(page.getByTestId("question-generation-job")).toHaveCount(1);
  const questionJob = page.getByTestId("question-generation-job");
  await expect(questionJob).toContainText("2 条候选");
  await expect(questionJob).toContainText("Dify · deepseek-chat");
  await questionJob.getByText("技术信息", { exact: true }).click();
  await expect(questionJob.getByText("请求模型 deepseek-v4-flash", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "审核候选", exact: true }).last().click();
  await expect(page).toHaveURL(/question_step=review/);
  await expect(page.getByText(/Fixture product specification · Fixture Mower supports/).first()).toBeVisible();
  await expect(page.getByText("可能重复", { exact: true })).toBeVisible();
  await expect(page.getByText("最近相似度 94.7%", { exact: true })).toBeVisible();

  const approvedQuestion = "Which robotic mower is reliable for a medium Australian lawn?";
  const candidateRow = page.getByText(approvedQuestion, { exact: true })
    .locator("xpath=ancestor::article[1]");
  await expect(candidateRow.getByRole("textbox", { name: "审核说明" })).toHaveCount(0);
  await candidateRow.getByRole("button", { name: "批准", exact: true }).click();
  await expect(page.getByText("已批准 1 条问题", { exact: true })).toBeVisible();
  await expect(page.getByText("正在提交...", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "进入问题清单" }).click();
  await expect(page).toHaveURL(/question_step=sets/);

  const setPanel = page.locator("section").filter({
    has: page.getByRole("heading", { name: "创建问题清单" })
  }).first();
  await setPanel.getByRole("textbox", { name: "清单名称" })
    .fill("AU robotic mower evaluation");
  await expect(setPanel.getByRole("checkbox", { name: approvedQuestion })).toBeChecked();
  await setPanel.getByRole("button", { name: "创建问题清单草稿" }).click();
  let setRow = page.getByTestId("question-set").filter({ hasText: "AU robotic mower evaluation" });
  await expect(setRow).toContainText("100%");
  await setRow.getByRole("button", { name: "批准问题清单" }).click();
  setRow = page.getByTestId("question-set").filter({ hasText: "AU robotic mower evaluation" });
  await setRow.getByRole("button", { name: "冻结问题清单" }).click();
  setRow = page.getByTestId("question-set").filter({ hasText: "AU robotic mower evaluation" });
  await expect(setRow).toContainText("已冻结");
  await setRow.locator('select[name="protocol_id"]').selectOption(PROTOCOL_DRAFT_ID);
  await setRow.getByRole("button", { name: "绑定监测方案" }).click();
  await expect(setRow).toContainText("已绑定：GEO question evaluation draft");
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-f019-question-set-desktop.png"), fullPage: true });
  await expect(setRow.getByRole("link", { name: "前往 GEO 运行内部仿真" })).toHaveAttribute(
    "href",
    new RegExp(`tab=geo.*campaign_id=${CAMPAIGN_A_ID}.*question_set_id=${QUESTION_SET_ID}`)
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.locator("details.mobileProjectTabs")).toBeVisible();
  await expect(page.getByText("当前视图：测试问题", { exact: true })).toBeVisible();
  const questionWidth = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
    overflow: Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .map((element) => {
        const bounds = element.getBoundingClientRect();
        return {
          node: `${element.tagName.toLowerCase()}.${element.className}`,
          right: Math.round(bounds.right),
          width: Math.round(bounds.width)
        };
      })
      .filter((item) => item.right > window.innerWidth + 1 || item.width > window.innerWidth + 1)
      .slice(0, 12)
  }));
  expect(
    questionWidth.document,
    `mobile overflow: ${JSON.stringify(questionWidth.overflow)}`
  ).toBeLessThanOrEqual(questionWidth.viewport + 1);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-f019-question-set-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&placement_stage=simulation&campaign_id=${CAMPAIGN_A_ID}&protocol_id=${PROTOCOL_A_ID}&opportunity_id=${OPPORTUNITY_A_ID}&brief_version_id=${BRIEF_ID}&attempt_id=${ATTEMPT_ID}&skill_id=${SKILL_ID}&question_set_id=${QUESTION_SET_ID}`);

  const simulationPanel = page.getByTestId("prompt-simulation-panel");
  await expect(simulationPanel.getByText("仅限测试", { exact: true }).first()).toBeVisible();
  await simulationPanel.locator('select[name="simulation_purpose"]')
    .selectOption("geo_question_test");
  const bindingOption = simulationPanel.locator('select[name="question_binding"] option')
    .filter({ hasText: approvedQuestion });
  const bindingValue = await bindingOption.getAttribute("value");
  expect(bindingValue).toBeTruthy();
  await simulationPanel.locator('select[name="question_binding"]').selectOption(bindingValue!);
  await simulationPanel.locator('select[name="primary_brand_entity_id"]')
    .selectOption("00000000-0000-4000-8000-000000000070");
  await simulationPanel.locator('select[name="product_entity_id"]')
    .selectOption("00000000-0000-4000-8000-000000000011");
  await simulationPanel.locator('select[name="evidence_item_ids"]').selectOption(EVIDENCE_ID);
  await simulationPanel.locator('input[name="audience"]').fill("Australian lawn owners");
  await simulationPanel.locator('select[name="deliverable"]').selectOption("short review");
  await simulationPanel.getByRole("button", { name: "运行仅测试预览" }).click();
  const simulationStatus = simulationPanel.getByRole("status")
    .filter({ hasText: "内部 GEO 问题仿真任务已排队" });
  await expect(simulationStatus).toBeVisible();
  await simulationStatus.getByRole("link", { name: "打开结果" }).click();
  await expect(page.getByText("不可发布", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("test_only=true · publication_eligible=false", { exact: true }))
    .toBeVisible();
  await expect(page.getByText("geo_question_test", { exact: true })).toBeVisible();
  await expect(page.locator('input[name="audience"]')).toHaveValue("Australian lawn owners");
  await expect(page.locator('select[name="deliverable"]')).toHaveValue("short review");
  await expect(page.locator('select[name="evidence_item_ids"] option:checked')).toHaveValue(EVIDENCE_ID);
  await expect(page.getByText("Fixture Mower is one evidence-grounded option for the stated lawn scenario.", { exact: true }))
    .toBeVisible();
  await expect(page.getByTestId("prompt-simulation-panel").getByRole("button", { name: /发布/ }))
    .toHaveCount(0);
  const currentArtifactLink = page.getByRole("link", { name: "下载仅测试工件" });
  await expect(currentArtifactLink).toHaveAttribute("href", new RegExp(
    `simulation-download/[^?]+\\?campaign_id=${CAMPAIGN_A_ID}$`
  ));
  const currentDownloadPromise = page.waitForEvent("download");
  await currentArtifactLink.click();
  const currentDownload = await currentDownloadPromise;
  expect(currentDownload.suggestedFilename()).toBe(
    "geo-prompt-simulation-00000000-0000-4000-8000-000000000136.json"
  );

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string; path: string; body: Record<string, any>;
  }>;
  const generation = logged.find((item) => item.method === "POST"
    && item.path.endsWith(`/knowledge/campaigns/${CAMPAIGN_A_ID}/question-generations`));
  expect(generation?.body).toMatchObject({
    fact_candidate_ids: [FACT_ID],
    graph_entity_ids: [],
    semantic_duplicate_threshold: 0.92,
    dimensions: [{ turn_index: 1, platform: "chatgpt_search", query_kind: "recommendation" }]
  });
  expect(logged.find((item) => item.method === "PATCH"
    && item.path.endsWith(`/question-candidates/${QUESTION_CANDIDATE_ID}`))?.body)
    .toEqual({ decision: "approved" });
  expect(logged.find((item) => item.method === "POST"
    && item.path.endsWith(`/question-sets/${QUESTION_SET_ID}/freeze`))).toBeTruthy();
  expect(logged.find((item) => item.method === "POST"
    && item.path.endsWith(`/monitoring-protocols/${PROTOCOL_DRAFT_ID}/question-set-binding`))?.body)
    .toEqual({ campaign_id: CAMPAIGN_A_ID, question_set_id: QUESTION_SET_ID,
      confirmed_content_hash: "3a".repeat(32) });
  const simulation = logged.find((item) => item.method === "POST"
    && item.path.endsWith("/geo/prompt-simulations"));
  expect(simulation?.body).toMatchObject({
    simulation_purpose: "geo_question_test",
    question_set_id: QUESTION_SET_ID,
    confirmed_question_set_hash: "3a".repeat(32),
    question_set_item_id: QUESTION_SET_ITEM_ID,
    prompt_release_binding_id: BINDING_ID,
    confirmed_release_hash: RELEASE_HASH,
    evidence_item_ids: [EVIDENCE_ID]
  });
  expect(simulation?.body).not.toHaveProperty("question_candidate_id");
  expect(logged.some((item) => item.method === "POST"
    && /publication|submissions|observations|monitoring-metrics|monitoring-reports/.test(item.path)))
    .toBe(false);

  await page.screenshot({ path: path.join(os.tmpdir(), "geo-f019-question-simulation-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.locator('input[name="idempotency_key"]').first()).not.toHaveValue("");
  await expect(page.getByText("不可发布", { exact: true }).first()).toBeVisible();
  const width = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: window.innerWidth
  }));
  expect(width.document).toBeLessThanOrEqual(width.viewport + 1);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-f019-question-simulation-mobile.png"), fullPage: true });
  expect(runtimeErrors).toEqual([]);
});

test("Measurement workspace repairs duplicates and freezes an exact 100-question successor", async ({ page, request }) => {
  test.setTimeout(60_000);
  const runtimeErrors = collectRuntimeErrors(page);
  expect((await request.patch(
    `${FIXTURE_API}/v1/projects/${PROJECT_ID}/knowledge/fact-candidates/${FACT_ID}`,
    { data: { decision: "approved" } }
  )).ok()).toBe(true);

  await page.goto(`/projects/${PROJECT_ID}?tab=measurement&workflow_view=questions&question_step=generate&campaign_id=${CAMPAIGN_A_ID}`);
  const generationPanel = page.locator("section").filter({
    has: page.getByRole("heading", { name: "生成 100 个测试问题" })
  }).first();
  await expect(generationPanel.getByText("类别基准")).toBeVisible();
  await expect(generationPanel.getByText("50", { exact: true })).toBeVisible();
  await generationPanel.getByRole("button", { name: "生成完整 100 题" }).click();

  const questionJob = page.getByTestId("question-generation-job");
  await expect(questionJob).toContainText("100 条候选");
  await expect(questionJob).toContainText("100 题覆盖库 · 10/10 批");
  await expect(questionJob).toContainText("固定基准 + Dify · deepseek-chat");
  await page.getByRole("link", { name: "审核候选", exact: true }).last().click();
  await expect(page).toHaveURL(/question_step=review/);
  await expect(page.getByRole("heading", { name: "检查 100 题测量库" })).toBeVisible();
  await expect(page.getByText("当前显示 100 / 100 条", { exact: true })).toBeVisible();
  await expect(page.getByTestId("question-coverage-candidate").first()
    .getByText("可冻结", { exact: true })).toBeVisible();

  const reviewPanel = page.locator("section").filter({
    has: page.getByRole("heading", { name: "检查 100 题测量库" })
  }).first();
  await reviewPanel.getByLabel("问题分层").selectOption("product_fit");
  await expect(reviewPanel.getByText("当前显示 40 / 100 条", { exact: true })).toBeVisible();
  await reviewPanel.getByLabel("问题分层").selectOption("brand_control");
  await expect(reviewPanel.getByText("当前显示 10 / 100 条", { exact: true })).toBeVisible();
  await reviewPanel.getByLabel("问题分层").selectOption("all");

  const coverageCandidates = reviewPanel.getByTestId("question-coverage-candidate");
  await expect(coverageCandidates).toHaveCount(100);
  await expect(reviewPanel.getByText("99/100", { exact: true })).toBeVisible();
  await expect(reviewPanel.getByText("还需修正 1 条问题", { exact: true })).toBeVisible();
  const duplicateCandidate = coverageCandidates.nth(1);
  await expect(duplicateCandidate.getByText("需修改", { exact: true })).toBeVisible();
  await duplicateCandidate.getByRole("button", { name: "编辑", exact: true }).click();
  const revisedQuestion = "What should an Australian homeowner compare before choosing a robotic mower?";
  await duplicateCandidate.getByRole("textbox", { name: "问题文字" }).fill(revisedQuestion);
  await duplicateCandidate.getByRole("button", { name: "保存修改" }).click();
  await expect(reviewPanel.getByText(revisedQuestion, { exact: true })).toBeVisible();
  await expect(reviewPanel.getByText("已修改", { exact: true })).toBeVisible();
  await expect(reviewPanel.getByText("100/100", { exact: true })).toBeVisible();
  await reviewPanel.getByRole("button", { name: "确认并冻结 100 条" }).click();

  await expect(page).toHaveURL(/question_step=sets/);
  const setRow = page.getByTestId("question-set");
  await expect(setRow).toContainText("已冻结");
  await expect(setRow).toContainText("100/100");
  await expect(setRow).toContainText(revisedQuestion);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-question-coverage-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByTestId("question-set")).toContainText("100/100");
  const mobileWidth = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: window.innerWidth
  }));
  expect(mobileWidth.document).toBeLessThanOrEqual(mobileWidth.viewport + 1);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-question-coverage-mobile.png"), fullPage: true });

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string; path: string; body: Record<string, unknown>;
  }>;
  const generation = logged.find((item) => item.method === "POST"
    && item.path.endsWith(`/knowledge/campaigns/${CAMPAIGN_A_ID}/question-generations`));
  expect(generation?.body).toMatchObject({
    generation_mode: "coverage_pack",
    coverage_profile: "au-cross-engine-balanced-v1",
    target_count: 100
  });
  const finalization = logged.find((item) => item.method === "POST"
    && item.path.endsWith("/question-sets/finalize-coverage-pack"));
  expect(finalization?.body.included_candidate_ids).toHaveLength(100);
  expect(runtimeErrors).toEqual([]);
});

test("Legacy GEO question links redirect to the measurement question workspace", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=campaigns&campaign_id=${CAMPAIGN_A_ID}&question_generation_job_id=00000000-0000-4000-8000-000000000131`);

  await expect(page).toHaveURL((url) => (
    url.pathname === `/projects/${PROJECT_ID}`
    && url.searchParams.get("tab") === "measurement"
    && url.searchParams.get("workflow_view") === "questions"
    && url.searchParams.get("campaign_id") === CAMPAIGN_A_ID
    && url.searchParams.get("question_generation_job_id") === "00000000-0000-4000-8000-000000000131"
    && !url.searchParams.has("geo_section")
  ));
  await expect(page.getByRole("heading", { name: "测量与告警" })).toBeVisible();
  expect(runtimeErrors).toEqual([]);
});

test("Legacy Prompt Simulation remains project-visible, read-only, and downloadable", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&placement_stage=simulation&simulation_id=${LEGACY_SIMULATION_ID}`);

  const panel = page.getByTestId("prompt-simulation-panel");
  await expect(panel.getByText("迁移历史（只读） · 1", { exact: true })).toBeVisible();
  await expect(panel.getByTestId("legacy-simulation-readonly")).toContainText("不能作为新建、审核、导出或发布输入");
  await expect(panel.getByText("Migrated legacy simulation remains available for audit and download.", { exact: true }))
    .toBeVisible();
  await expect(panel.getByRole("button", { name: "运行仅测试预览" })).toHaveCount(0);
  await expect(panel.getByRole("button", { name: /发布/ })).toHaveCount(0);

  const artifactLink = panel.getByRole("link", { name: "下载仅测试工件" });
  await expect(artifactLink).toHaveAttribute(
    "href",
    `/projects/${PROJECT_ID}/simulation-download/${LEGACY_SIMULATION_ID}`
  );
  const downloadPromise = page.waitForEvent("download");
  await artifactLink.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(`geo-prompt-simulation-${LEGACY_SIMULATION_ID}.json`);

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string;
    path: string;
  }>;
  expect(logged.some((item) => item.method === "POST"
    && item.path.endsWith("/geo/prompt-simulations"))).toBe(false);
  expect(runtimeErrors).toEqual([]);
});

test("F027: Admin downloads Campaign-scoped reproducible project export ZIP", async ({ page, request }) => {
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=campaigns&campaign_id=${CAMPAIGN_A_ID}`);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出当前 Campaign" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(
    "geo-project-export-00000000-0000-4000-8000-000000000401.zip"
  );

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string;
    path: string;
    body: Record<string, unknown>;
  }>;
  const exportRequest = logged.find((item) => (
    item.method === "POST" && item.path.endsWith("/project-exports")
  ));
  expect(exportRequest?.body).toEqual({ campaign_id: CAMPAIGN_A_ID });
});

test("F027: Admin export reports terminal failure without waiting for the polling timeout", async ({ page, request }) => {
  expect((await request.post(`${FIXTURE_API}/__project_export_status`, {
    data: { status: "dead_lettered", error_code: "artifact_upload_failed" }
  })).ok()).toBe(true);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=campaigns&campaign_id=${CAMPAIGN_A_ID}`);

  await page.getByRole("button", { name: "导出当前 Campaign" }).click();

  const exportAlert = page.locator('span[role="alert"]');
  await expect(exportAlert).toContainText("dead_lettered");
  await expect(exportAlert).toContainText("artifact_upload_failed");
  await expect(page.getByRole("button", { name: "导出当前 Campaign" })).toBeEnabled();
});

test("F012: Campaign switch clears every descendant context and invalid deep links do not select the first child", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&campaign_id=${CAMPAIGN_A_ID}&protocol_id=${PROTOCOL_A_ID}&destination_id=00000000-0000-4000-8000-000000000021&opportunity_id=${OPPORTUNITY_A_ID}&placement_stage=generation&measurement_window=t56`);

  await expect(page.getByLabel("当前活动")).toHaveValue(CAMPAIGN_A_ID);
  await page.getByLabel("当前活动").selectOption(CAMPAIGN_B_ID);
  await expect(page).toHaveURL(new RegExp(`campaign_id=${CAMPAIGN_B_ID}`));
  const switched = new URL(page.url());
  for (const key of ["protocol_id", "destination_id", "opportunity_id", "brief_version_id", "attempt_id", "skill_id", "bundle_id", "job_id", "version_id", "publication_id", "submission_id", "simulation_id"]) {
    expect(switched.searchParams.has(key), `${key} must be cleared`).toBe(false);
  }
  expect(switched.searchParams.get("placement_stage")).toBe("brief");
  expect(switched.searchParams.get("measurement_window")).toBe("baseline");
  await expect(page.getByLabel("当前活动")).toHaveValue(CAMPAIGN_B_ID);
  await expect(page.getByText("当前 Campaign 没有渠道任务", { exact: true })).toBeVisible();
  await expect(page.getByText("请选择一个渠道任务。", { exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-campaign-context.png"), fullPage: true });

  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=campaigns&campaign_id=${CAMPAIGN_A_ID}&protocol_id=00000000-0000-4000-8000-999999999999`);
  await expect(page).toHaveURL((url) => (
    url.searchParams.get("campaign_id") === CAMPAIGN_A_ID
    && !url.searchParams.has("protocol_id")
  ));
  await expect(page.getByText("OpenAI AU frozen baseline", { exact: true })).toBeVisible();

  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&skill_id=${SKILL_ID}`);
  await expect(page).toHaveURL((url) => !url.searchParams.has("skill_id"));
  await expect(page.getByText("未选择活动。", { exact: true })).toBeVisible();
  expect(runtimeErrors).toEqual([]);
});

test("F009: observation source controls expose only public capture methods and serialize provenance", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=observations&campaign_id=${CAMPAIGN_A_ID}&protocol_id=${PROTOCOL_A_ID}`);
  await expect(page.getByRole("link", { name: "下载内部 CSV" })).toBeVisible();
  const officialReport = page.locator("details").filter({ has: page.getByText("导入官方报告", { exact: true }) });
  await officialReport.locator(":scope > summary").click();
  await officialReport.locator('select[name="official_platform"]').selectOption("microsoft");
  await expect(officialReport.locator('input[name="official_surface"]')).toHaveValue("bing_ai_performance_report");
  await expect(officialReport.locator('select[name="capture_method"]')).toHaveCount(0);
  await page.getByText("录入观察样本", { exact: true }).click();

  const capture = page.locator('select[name="capture_method"]');
  await expect(capture.locator("option")).toHaveText([
    "人工消费者界面",
    "Provider API",
    "Grounded Proxy API"
  ]);
  const platform = page.locator('select[name="source_platform"]');
  const surface = page.locator('select[name="source_surface"]');
  await platform.selectOption("microsoft");
  await expect(surface.locator("option")).toHaveText([
    "Bing Search",
    "Bing Copilot"
  ]);
  await platform.selectOption("anthropic");
  await expect(surface).toHaveValue("claude_ai");

  await capture.selectOption("provider_api");
  await expect(surface).toHaveValue("openai_api");
  await expect(page.locator('input[name="configured_model"]')).toHaveAttribute("required", "");
  await expect(page.locator('input[name="adapter_name"]')).toHaveAttribute("required", "");
  await expect(page.locator('input[name="adapter_version"]')).toHaveAttribute("required", "");
  await expect(page.locator('input[name="provider_request_id"]')).toHaveAttribute("required", "");
  await page.locator('input[name="search_enabled"]').uncheck();
  await expect(page.locator('select[name="search_mode"]')).toHaveValue("disabled");
  await page.locator('input[name="search_enabled"]').check();
  await expect(page.locator('select[name="search_mode"]')).toHaveValue("automatic");

  const fillProviderObservation = async (rawEvidence?: string) => {
    await capture.selectOption("provider_api");
    await expect(page.locator('select[name="search_mode"]')).toHaveValue("automatic");
    await page.locator('select[name="configured_model_state"]').selectOption("disclosed");
    await page.locator('select[name="reported_model_state"]').selectOption("not_disclosed");
    await page.locator('select[name="monitoring_query_id"]').selectOption(QUERY_A_ID);
    await page.locator('input[name="observed_at"]').fill("2026-07-19T10:30");
    await page.locator('input[name="configured_model"]').fill("gpt-5-search");
    await page.locator('input[name="region"]').fill("AU");
    await page.locator('textarea[name="prompt_text"]').fill("Which robotic mower should I buy?");
    await page.locator('input[name="adapter_name"]').fill("openai-responses");
    await page.locator('input[name="adapter_version"]').fill("2.1.0");
    await page.locator('input[name="provider_request_id"]').fill("req_fixture_001");
    if (rawEvidence) await page.locator('textarea[name="raw_answer"]').fill(rawEvidence);
  };

  await fillProviderObservation();
  await page.getByRole("button", { name: "保存观察样本" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "必须保存原始回答" }))
    .toContainText("必须保存原始回答、内联响应或不可变工件");

  await fillProviderObservation('{"answer":"Fixture answer","citations":[]}');
  await page.getByRole("button", { name: "保存观察样本" }).click();
  await expect(page.getByRole("status")).toContainText("原始观察样本与引用已保存");
  await expect(page.getByText("Provider API · OpenAI API", { exact: true })).toBeVisible();

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{ method: string; path: string; body: Record<string, any> }>;
  const imported = logged.find((item) => item.method === "POST" && item.path.endsWith(`/monitoring-protocols/${PROTOCOL_A_ID}/observations`));
  expect(imported?.body).toMatchObject({
    campaign_id: CAMPAIGN_A_ID,
    capture_method: "provider_api",
    monitoring_query_id: QUERY_A_ID,
    source: {
      platform: "openai",
      surface: "openai_api",
      surface_kind: "provider_api",
      configured_model: { state: "disclosed", value: "gpt-5-search" },
      run: {
        engine: "openai",
        device: "api",
        client_kind: "api",
        search_enabled: true,
        search_mode: "automatic",
        adapter_name: "openai-responses",
        adapter_version: "2.1.0",
        provider_request_id: "req_fixture_001"
      },
      raw_evidence: {
        kind: "inline_response",
        inline_response: { answer: "Fixture answer", citations: [] }
      }
    }
  });

  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-observation-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "AI 搜索观察" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-observation-mobile.png"), fullPage: true });
  expect(runtimeErrors).toEqual([]);
});

test("F021: frozen protocol strata can compute an auditable insufficient-evidence snapshot with zero samples", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=campaigns&campaign_id=${CAMPAIGN_A_ID}&protocol_id=${PROTOCOL_A_ID}`);

  const protocolPanel = page.locator("details").filter({ has: page.getByText("新建监测方案", { exact: true }) });
  await protocolPanel.locator(":scope > summary").click();
  const sampleSize = protocolPanel.locator('input[name="sample_size"]');
  const minimumValid = protocolPanel.locator('input[name="minimum_valid_repeats"]');
  await expect(sampleSize).toBeEnabled();
  await expect(sampleSize).toHaveAttribute("min", "3");
  await expect(minimumValid).toHaveValue("3");
  await sampleSize.fill("10");
  await expect(minimumValid).toHaveAttribute("min", "8");
  await expect(minimumValid).toHaveValue("8");

  const operations = page.locator("details").filter({ has: page.getByText("高级运营：查询建议、指标与客户报告", { exact: true }) });
  await operations.locator(":scope > summary").click();
  const legacySuggestion = operations.getByTestId("legacy-query-suggestion");
  await expect(legacySuggestion).toContainText("迁移历史 · 缺少问题簇 · 只读");
  await expect(legacySuggestion).toContainText("请在上方提交包含问题簇的新建议");
  await expect(legacySuggestion.getByRole("button", { name: "批准建议" })).toHaveCount(0);
  await expect(operations.locator('input[name="query_cluster_key"]').first()).toHaveAttribute("required", "");
  const metricSection = operations.getByRole("heading", { name: "指标与报告" }).locator("..");
  const sourceSelect = metricSection.locator('select[name="source_stratum_hash"]');
  const clusterSelect = metricSection.locator('select[name="query_cluster_key"]');
  await expect(sourceSelect.locator(`option[value="${SOURCE_STRATUM_HASH}"]`))
    .toContainText("人工消费者界面 · openai / chatgpt_search");
  await sourceSelect.selectOption(SOURCE_STRATUM_HASH);
  await clusterSelect.selectOption("robot-mower-recommendation");
  await metricSection.getByRole("button", { name: "计算指标" }).click();

  const metric = page.getByTestId("monitoring-metric-snapshot");
  await expect(metric.getByText("证据不足", { exact: true })).toBeVisible();
  await expect(metric).toContainText("有效重复未达到冻结门槛，本快照不作趋势判断。");
  await expect(metric).toContainText("已采样");
  await expect(metric).toContainText("有效");
  await expect(metric).toContainText("无效");
  await expect(metric).toContainText("缺失");
  await expect(metric).toContainText("采样完成度");
  await expect(metric).toContainText("有效完成度");
  await expect(metric).toContainText("Wilson 95% CI");
  await expect(metric).toContainText("问题区间");
  await expect(metric).toContainText("无效原因");
  await expect(metric).toContainText("混杂因素");
  await expect(metric).toContainText("最弱问题");
  await metric.getByText("逐问题分母与区间", { exact: true }).click();
  await expect(metric).toContainText("0 已采样 · 0 有效 · 0 无效 · 3 缺失");
  await metric.getByText("指标审计信息", { exact: true }).click();
  await expect(metric).toContainText(`结果 ${"9".repeat(64)}`);
  await expect(metric).toContainText(`观察记录 ${"a1".repeat(32)}`);
  await expect(metric).toContainText("metric-observation-membership-v1 · 0 条观察记录");
  await expect(metric).not.toContainText(/improved|declined|stable|改善|下降|稳定/i);

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{ method: string; path: string; body: Record<string, any> }>;
  const computation = logged.find((item) => item.method === "POST" && item.path.endsWith(`/monitoring-protocols/${PROTOCOL_A_ID}/metrics`));
  expect(computation?.body).toEqual({
    campaign_id: CAMPAIGN_A_ID,
    measurement_window: "baseline",
    source_stratum_hash: SOURCE_STRATUM_HASH,
    query_cluster_key: "robot-mower-recommendation"
  });
  expect(logged.some((item) => item.method === "POST" && item.path.endsWith("/observations"))).toBe(false);
  expect(runtimeErrors).toEqual([]);
});

test("F011: a failed public URL check is retried explicitly after external content correction", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&placement_stage=publication&campaign_id=${CAMPAIGN_A_ID}&opportunity_id=${OPPORTUNITY_A_ID}&version_id=${PACKAGE_VERSION_ID}&publication_id=${PUBLICATION_ID}&submission_id=${SUBMISSION_ID}`);
  await expect(page).toHaveTitle(/GEO 项目管理台/);
  expect(page.url()).toContain(`submission_id=${SUBMISSION_ID}`);
  await expect(page.getByRole("heading", { name: "公开 URL 验证" })).toBeVisible();
  await expect(page.getByText(/Unhandled Runtime Error|Application error/)).toHaveCount(0);

  const urlInput = page.getByRole("textbox", { name: "公开 URL", exact: true });
  await expect(urlInput).toHaveValue("");
  await urlInput.fill("https://example.test/au/fixture-review");
  await page.getByRole("button", { name: "保存公开 URL" }).click();
  await expect(page.getByRole("status")).toContainText("公开 URL 已回填");

  await page.getByRole("button", { name: "请求验证" }).click();
  await expect(page.getByText("最近验证 · 第 1 次执行", { exact: true })).toBeVisible();
  await expect(page.getByText("approved_content_missing", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "重新验证" })).toBeEnabled();
  const verifierVersion = page.getByText("规则 publication-url-verifier-v2", { exact: true });
  if (!await verifierVersion.isVisible()) {
    const summary = page.getByText("验证规则与证据哈希", { exact: true });
    await summary.click();
    await expect(summary.locator("..")).toHaveAttribute("open", "");
  }
  await expect(verifierVersion).toBeVisible();

  const corrected = await request.post(`${FIXTURE_API}/__verification_semantics`, {
    data: { approved_content: true }
  });
  expect(corrected.ok()).toBe(true);
  await page.getByRole("button", { name: "重新验证" }).click();
  await expect(page.getByText("最近验证 · 第 1 次执行", { exact: true })).toBeVisible();
  await expect(page.getByText("approved_content_missing", { exact: true })).toHaveCount(0);
  const passedResult = page.getByText(`结果 ${"e".repeat(64)}`, { exact: true });
  if (!await passedResult.isVisible()) {
    const summary = page.getByText("验证规则与证据哈希", { exact: true });
    if (await summary.locator("..").getAttribute("open") === null) await summary.click();
    await expect(summary.locator("..")).toHaveAttribute("open", "");
  }
  await expect(passedResult).toBeVisible();
  const failedHistory = page.getByText(new RegExp(`第 1 次 · failed · ${"d".repeat(64)}`));
  const historySummary = page.getByText("历史验证尝试", { exact: true });
  await historySummary.click();
  await expect(historySummary.locator("..")).toHaveAttribute("open", "");
  await expect(failedHistory).toBeVisible();

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{ method: string; path: string }>;
  expect(logged.filter((item) => item.path.endsWith(`/submissions/${SUBMISSION_ID}/verification-jobs`))).toHaveLength(2);
  expect(logged.some((item) => /model[-_]?call|placement\.generate/.test(item.path))).toBe(false);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-publication-verification-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.locator('input[name="idempotency_key"]').first()).not.toHaveValue("");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-publication-verification-mobile.png"), fullPage: true });
  expect(runtimeErrors).toEqual([]);
});

test("F013: approved Fact becomes governed Evidence and remains traceable inside a rebuilt Evidence Pack", async ({ page, request }) => {
  test.setTimeout(45_000);
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=knowledge&knowledge_tab=trace`);

  await expect(page.getByRole("heading", { name: "事实候选与证据追踪" })).toBeVisible();
  await expect(page.getByText("Fixture Mower supports medium Australian lawns with governed boundary wire guidance.", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "审核说明" }).fill("Approved against the source revision and chunk hashes");
  await page.getByRole("button", { name: "保存审核" }).click();
  const traceLink = page.getByRole("link", { name: "证据与追溯链" });
  await expect(traceLink).toBeVisible();
  await traceLink.click();

  const promotionPanel = page.getByRole("heading", { name: "正式证据提升" })
    .locator("xpath=ancestor::section[1]");
  await expect(promotionPanel).toBeVisible();
  await expect(promotionPanel.getByText("来源", { exact: true })).toBeVisible();
  await expect(promotionPanel.getByText("文档", { exact: true })).toBeVisible();
  await expect(promotionPanel.getByText("已批准事实", { exact: true })).toBeVisible();
  await promotionPanel.getByRole("button", { name: "提升为正式 Evidence" }).click();
  await expect(page.getByText(EVIDENCE_ID, { exact: true })).toBeVisible();
  await expect(page.getByText("knowledge-fact-evidence-v1", { exact: true })).toBeVisible();
  await expect(page.getByText("5".repeat(64), { exact: true })).toBeVisible();
  await expect(page.getByText("6".repeat(64), { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "进入证据包" }).click();
  const campaignSelect = page.getByLabel("当前活动");
  await expect(campaignSelect).toBeEnabled();
  await expect(campaignSelect).toHaveValue("");
  await expect(campaignSelect.locator(`option[value="${CAMPAIGN_A_ID}"]`))
    .toHaveAttribute("data-href", new RegExp(`campaign_id=${CAMPAIGN_A_ID}`));
  await campaignSelect.selectOption(CAMPAIGN_A_ID);
  await expect(page).toHaveURL(new RegExp(`campaign_id=${CAMPAIGN_A_ID}`));
  await expect(page.getByLabel("当前渠道任务")).toBeVisible();
  await page.getByLabel("当前渠道任务").selectOption(OPPORTUNITY_A_ID);
  await expect(page).toHaveURL(new RegExp(`opportunity_id=${OPPORTUNITY_A_ID}`));
  await page.getByRole("link", { name: /版本 1/ }).click();
  await expect(page).toHaveURL(new RegExp(`brief_version_id=${BRIEF_ID}`));
  await page.getByRole("link", { name: "继续选择证据" }).click();
  await page.getByRole("button", { name: "重新构建证据" }).click();
  const buildStatus = page.getByRole("status").filter({ hasText: "Evidence Pack 构建任务已创建" });
  await expect(buildStatus).toContainText("Evidence Pack 构建任务已创建");
  await buildStatus.getByRole("link", { name: "打开结果" }).click();

  await expect(page).toHaveURL(new RegExp(`campaign_id=${CAMPAIGN_A_ID}`));
  await expect(page).toHaveURL(new RegExp(`opportunity_id=${OPPORTUNITY_A_ID}`));
  await expect(page).toHaveURL(new RegExp(`attempt_id=${ATTEMPT_ID}`));
  const evidenceRow = page.locator("tbody tr").filter({ hasText: "Fixture product specification" });
  await expect(evidenceRow).toContainText("public_reference");
  await expect(evidenceRow).toContainText("允许");
  await evidenceRow.getByText("技术信息", { exact: true }).click();
  await expect(evidenceRow.getByText(`Fact ${FACT_ID}`, { exact: true })).toBeVisible();
  await expect(evidenceRow.getByText("knowledge-fact-evidence-v1", { exact: true })).toBeVisible();

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{ method: string; path: string; body: Record<string, any> }>;
  expect(logged.find((item) => item.method === "PATCH" && item.path.endsWith(`/fact-candidates/${FACT_ID}`))?.body).toEqual({
    decision: "approved",
    notes: "Approved against the source revision and chunk hashes"
  });
  const promotion = logged.find((item) => item.method === "POST" && item.path.endsWith(`/fact-candidates/${FACT_ID}/evidence`));
  expect(promotion?.body).toMatchObject({
    subject_entity_id: "00000000-0000-4000-8000-000000000011",
    subject_role: "product",
    usage_rights: "public_reference",
    confidentiality: "public"
  });
  for (const derived of ["pipeline_run_id", "knowledge_source_id", "knowledge_document_id", "knowledge_chunk_id", "promotion_request_hash", "evidence_snapshot_hash"]) {
    expect(promotion?.body).not.toHaveProperty(derived);
  }
  expect(logged.some((item) => item.method === "POST" && item.path.endsWith(`/brief-versions/${BRIEF_ID}/evidence-pack-attempts`))).toBe(true);
  expect(runtimeErrors).toEqual([]);
});
