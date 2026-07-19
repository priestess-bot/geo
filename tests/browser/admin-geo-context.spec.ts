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
const FACT_ID = "00000000-0000-4000-8000-000000000105";
const EVIDENCE_ID = "00000000-0000-4000-8000-000000000106";
const PACKAGE_VERSION_ID = "00000000-0000-4000-8000-000000000112";
const PUBLICATION_ID = "00000000-0000-4000-8000-000000000113";
const SUBMISSION_ID = "00000000-0000-4000-8000-000000000114";
const QUESTION_CANDIDATE_ID = "00000000-0000-4000-8000-000000000132";
const QUESTION_SET_ID = "00000000-0000-4000-8000-000000000134";
const QUESTION_SET_ITEM_ID = "00000000-0000-4000-8000-000000000135";
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

  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=campaigns&campaign_id=${CAMPAIGN_A_ID}&protocol_id=${PROTOCOL_A_ID}&opportunity_id=${OPPORTUNITY_A_ID}&brief_version_id=${BRIEF_ID}&attempt_id=${ATTEMPT_ID}&skill_id=${SKILL_ID}`);
  await expect(page).toHaveTitle(/GEO 项目管理台/);
  await expect(page.getByRole("heading", { name: "GEO 测试问题" })).toBeVisible();
  const generationPanel = page.locator("details").filter({
    has: page.getByText("生成测试问题", { exact: true })
  });
  await generationPanel.locator(":scope > summary").click();
  await generationPanel.locator('select[name="fact_candidate_ids"]').selectOption(FACT_ID);
  await generationPanel.getByRole("textbox", { name: "人群" }).fill("Australian homeowners");
  await generationPanel.getByRole("textbox", { name: "主题" }).fill("robotic lawn mower");
  await generationPanel.getByRole("textbox", { name: "场景" })
    .fill("Researching a reliable mower for a medium lawn");
  await generationPanel.getByRole("textbox", { name: "意图" }).fill("compare suitable products");
  await generationPanel.getByRole("button", { name: "生成候选问题" }).click();
  await expect(generationPanel.getByRole("status")).toContainText("测试问题生成任务已排队");
  await expect(page.getByTestId("question-generation-job")).toHaveCount(1);
  await expect(page.getByText("1 个维度", { exact: true })).toBeVisible();
  await expect(page.getByText("Fact · Fixture product specification", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("可能重复", { exact: true })).toBeVisible();
  await expect(page.getByText("最近相似度 94.7%", { exact: true })).toBeVisible();

  const approvedQuestion = "Which robotic mower is reliable for a medium Australian lawn?";
  const candidateRow = page.getByText(approvedQuestion, { exact: true })
    .locator("xpath=ancestor::article[1]");
  await candidateRow.getByRole("textbox", { name: "审核说明" })
    .fill("Fact lineage is sufficient and the intent is distinct");
  await candidateRow.getByRole("button", { name: "保存人工审核" }).click();
  await expect(candidateRow).toContainText("已批准");

  const setPanel = page.locator("details").filter({
    has: page.getByText("创建 QuestionSet 草稿", { exact: true })
  });
  await setPanel.locator(":scope > summary").click();
  await setPanel.getByRole("textbox", { name: "QuestionSet 名称" })
    .fill("AU robotic mower evaluation");
  await setPanel.locator('select[name="candidate_ids"]').selectOption(QUESTION_CANDIDATE_ID);
  await setPanel.getByRole("button", { name: "创建不可变问题清单" }).click();
  let setRow = page.locator("article").filter({ hasText: "AU robotic mower evaluation · v1" });
  await expect(setRow).toContainText("100%");
  await setRow.getByRole("button", { name: "批准 QuestionSet" }).click();
  setRow = page.locator("article").filter({ hasText: "AU robotic mower evaluation · v1" });
  await setRow.getByRole("button", { name: "冻结 QuestionSet" }).click();
  setRow = page.locator("article").filter({ hasText: "AU robotic mower evaluation · v1" });
  await expect(setRow).toContainText("已冻结");
  await setRow.locator('select[name="protocol_id"]').selectOption(PROTOCOL_DRAFT_ID);
  await setRow.getByRole("button", { name: "绑定到 draft 监测方案" }).click();
  await expect(setRow).toContainText("已绑定监测方案：GEO question evaluation draft");
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-f019-question-set-desktop.png"), fullPage: true });
  await setRow.getByRole("link", { name: "进入内部 GEO 仿真" }).click();

  const simulationPanel = page.getByTestId("prompt-simulation-panel");
  await expect(simulationPanel.getByText("TEST ONLY", { exact: true }).first()).toBeVisible();
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
  await simulationPanel.getByRole("button", { name: "运行 TEST ONLY 预览" }).click();
  const simulationStatus = simulationPanel.getByRole("status")
    .filter({ hasText: "内部 GEO 问题仿真任务已排队" });
  await expect(simulationStatus).toBeVisible();
  await simulationStatus.getByRole("link", { name: "打开结果" }).click();
  await expect(page.getByText("NON-PUBLISHABLE", { exact: true })).toBeVisible();
  await expect(page.getByText("test_only=true · publication_eligible=false", { exact: true }))
    .toBeVisible();
  await expect(page.getByText("geo_question_test", { exact: true })).toBeVisible();
  await expect(page.getByText("Fixture Mower is one evidence-grounded option for the stated lawn scenario.", { exact: true }))
    .toBeVisible();
  await expect(page.getByTestId("prompt-simulation-panel").getByRole("button", { name: /发布/ }))
    .toHaveCount(0);

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
    .toEqual({ decision: "approved", notes: "Fact lineage is sufficient and the intent is distinct" });
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
  await expect(page.getByText("NON-PUBLISHABLE", { exact: true })).toBeVisible();
  const width = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: window.innerWidth
  }));
  expect(width.document).toBeLessThanOrEqual(width.viewport + 1);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-f019-question-simulation-mobile.png"), fullPage: true });
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

test("F012: Campaign switch clears every descendant context and invalid deep links do not select the first child", async ({ page }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&campaign_id=${CAMPAIGN_A_ID}&protocol_id=${PROTOCOL_A_ID}&destination_id=00000000-0000-4000-8000-000000000021&opportunity_id=${OPPORTUNITY_A_ID}&placement_stage=generation&measurement_window=t56`);

  await expect(page.getByLabel("当前 Campaign")).toHaveValue(CAMPAIGN_A_ID);
  await page.getByLabel("当前 Campaign").selectOption(CAMPAIGN_B_ID);
  await expect(page).toHaveURL(new RegExp(`campaign_id=${CAMPAIGN_B_ID}`));
  const switched = new URL(page.url());
  for (const key of ["protocol_id", "destination_id", "opportunity_id", "brief_version_id", "attempt_id", "skill_id", "bundle_id", "job_id", "version_id", "publication_id", "submission_id", "simulation_id", "question_generation_job_id"]) {
    expect(switched.searchParams.has(key), `${key} must be cleared`).toBe(false);
  }
  expect(switched.searchParams.get("placement_stage")).toBe("brief");
  expect(switched.searchParams.get("measurement_window")).toBe("baseline");
  await expect(page.getByLabel("当前 Campaign")).toHaveValue(CAMPAIGN_B_ID);
  await expect(page.getByText("当前 Campaign 没有渠道任务", { exact: true })).toBeVisible();
  await expect(page.getByText("请选择一个渠道任务。", { exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-campaign-context.png"), fullPage: true });

  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=campaigns&campaign_id=${CAMPAIGN_A_ID}&protocol_id=00000000-0000-4000-8000-999999999999`);
  await expect(page).toHaveURL(new RegExp(`campaign_id=${CAMPAIGN_A_ID}`));
  expect(new URL(page.url()).searchParams.has("protocol_id")).toBe(false);
  await expect(page.getByText("OpenAI AU frozen baseline", { exact: true })).toBeVisible();

  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&skill_id=${SKILL_ID}`);
  await expect(page).toHaveURL((url) => !url.searchParams.has("skill_id"));
  await expect(page.getByText("未选择 Campaign。", { exact: true })).toBeVisible();
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
  await expect(metric).toContainText("0 sampled · 0 valid · 0 invalid · 3 missing");
  await metric.getByText("指标审计信息", { exact: true }).click();
  await expect(metric).toContainText(`Result ${"9".repeat(64)}`);
  await expect(metric).toContainText(`Observations ${"a1".repeat(32)}`);
  await expect(metric).toContainText("metric-observation-membership-v1 · 0 observations");
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
  const passedResult = page.getByText(`Result ${"e".repeat(64)}`, { exact: true });
  if (!await passedResult.isVisible()) {
    const summary = page.getByText("验证规则与证据哈希", { exact: true });
    if (await summary.locator("..").getAttribute("open") === null) await summary.click();
    await expect(summary.locator("..")).toHaveAttribute("open", "");
  }
  await expect(passedResult).toBeVisible();
  const failedHistory = page.getByText(new RegExp(`第 1 次 · failed · ${"d".repeat(64)}`));
  const historySummary = page.getByText("历史验证 Attempt", { exact: true });
  await historySummary.click();
  await expect(historySummary.locator("..")).toHaveAttribute("open", "");
  await expect(failedHistory).toBeVisible();

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{ method: string; path: string }>;
  expect(logged.filter((item) => item.path.endsWith(`/submissions/${SUBMISSION_ID}/verification-jobs`))).toHaveLength(2);
  expect(logged.some((item) => /model[-_]?call|placement\.generate/.test(item.path))).toBe(false);
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-publication-verification-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
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
  const traceLink = page.getByRole("link", { name: "Evidence 与追溯链" });
  await expect(traceLink).toBeVisible();
  await traceLink.click();

  await expect(page.getByRole("heading", { name: "正式 Evidence 提升" })).toBeVisible();
  await expect(page.getByText("Source", { exact: true })).toBeVisible();
  await expect(page.getByText("Document", { exact: true })).toBeVisible();
  await expect(page.getByText("Approved Fact", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "提升为正式 Evidence" }).click();
  await expect(page.getByText(EVIDENCE_ID, { exact: true })).toBeVisible();
  await expect(page.getByText("knowledge-fact-evidence-v1", { exact: true })).toBeVisible();
  await expect(page.getByText("5".repeat(64), { exact: true })).toBeVisible();
  await expect(page.getByText("6".repeat(64), { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "进入 Evidence Pack" }).click();
  const campaignSelect = page.getByLabel("当前 Campaign");
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

test("F014: Opportunity binding and Bundle creation freeze the approved Prompt Release identity", async ({ page, request }) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.goto(`/projects/${PROJECT_ID}?tab=geo&geo_section=placement&placement_stage=evidence&campaign_id=${CAMPAIGN_A_ID}&opportunity_id=${OPPORTUNITY_A_ID}&brief_version_id=${BRIEF_ID}&attempt_id=${ATTEMPT_ID}&skill_id=${SKILL_ID}`);

  await expect(page.getByText("尚未绑定已批准 Prompt Release。", { exact: true }).first()).toBeVisible();
  const administration = page.locator("details").filter({ has: page.getByText("高级：Prompt 规则与版本管理", { exact: true }) });
  await administration.locator(":scope > summary").click();
  await expect(administration.getByRole("button", { name: "撤销 Release" })).toBeVisible();
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

  const logged = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{ method: string; path: string; body: Record<string, any> }>;
  const bindingRequest = logged.find((item) => item.method === "POST" && item.path.endsWith(`/opportunities/${OPPORTUNITY_A_ID}/prompt-release-bindings`));
  expect(bindingRequest?.body).toMatchObject({
    template_release_id: RELEASE_ID,
    reason: "Pin approved release for this Opportunity",
    expected_binding_version: 1
  });
  expect(bindingRequest?.body).not.toHaveProperty("expected_previous_binding_id");
  const bundleRequest = logged.find((item) => item.method === "POST" && item.path.endsWith(`/brief-versions/${BRIEF_ID}/prompt-bundles`));
  expect(bundleRequest?.body).toMatchObject({
    campaign_id: CAMPAIGN_A_ID,
    opportunity_id: OPPORTUNITY_A_ID,
    prompt_release_binding_id: BINDING_ID,
    confirmed_release_hash: RELEASE_HASH,
    evidence_pack_attempt_id: ATTEMPT_ID
  });
  expect(bundleRequest?.body).not.toHaveProperty("template_release_id");
  await page.screenshot({ path: path.join(os.tmpdir(), "geo-admin-prompt-binding.png"), fullPage: true });
  expect(runtimeErrors).toEqual([]);
});
