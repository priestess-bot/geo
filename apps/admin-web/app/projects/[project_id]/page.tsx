import {
  BrandAssetsPanel,
  CompetitorEditor,
  CollectionJobPanel,
  ContentWorkbenchPanel,
  FixtureE2EForm,
  HumanReviewPanel,
  InvitationForm,
  InvitationList,
  KnowledgeDashboardPanel,
  KnowledgeChunkControlForm,
  KnowledgeFactExtractionForm,
  KnowledgeDocumentImportPanel,
  KnowledgeMaintenanceRunForm,
  KnowledgeQualityPanel,
  KnowledgeQualityRiskAcceptForm,
  KnowledgeStageRetryForm,
  type KnowledgeFactSearchResult,
  LaunchConfigForm,
  ManualBackfillPanel,
  MemberList,
  MemberManagement,
  ProjectBasicsForm,
  ProjectStatusControls,
  PromptCandidatePanel,
  PromptEditor,
  PromptGenerationPanel,
  PromptImportForm,
  PromptImportHistoryPanel,
  PromptTemplatePanel,
  QualityOpsPanel,
  ReportCenterPanel,
  ActionPlanPanel
} from "./ProjectActions";
import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { actorHeaders, adminDevToolsEnabled, apiBase, runtimeRequest } from "../../runtime";
import { projectStatusLabel, statusLabel } from "../status";

type RuntimeProject = {
  project: { id: string; name?: string; target_brand?: string; category?: string; status?: string; market_code?: string };
  tenant?: { name?: string };
  brand?: {
    canonical_name?: string;
    official_domains?: string[];
    parent_company?: string | null;
    product_lines?: string[];
    status?: string;
  } | null;
  competitors?: Array<{
    id?: string;
    canonical_name?: string;
    official_domains?: string[];
    parent_company?: string | null;
    product_lines?: string[];
    status?: string;
  }>;
  prompt_count?: number;
  audit_events?: Array<Record<string, unknown>>;
};

type ProjectPage = {
  total_count: number;
  records: RuntimeProject[];
};

type ProjectLoadResult = {
  record: RuntimeProject | null;
  status?: number;
  correlation_id?: string;
};

type LaunchConfigResponse = {
  launch_config?: Record<string, unknown>;
};

type PageResponse<T> = { total_count: number; records: T[]; limit?: number; offset?: number };

type ScoreWeightConfigResponse = {
  score_weight_config?: Record<string, unknown>;
  audit_events?: Array<Record<string, unknown>>;
};

type ScoreFormulaResponse = {
  formulas?: Array<Record<string, unknown>>;
};

type ScoreProfileResponse = {
  records?: Array<{ score_weight_profile?: Record<string, unknown> }>;
  total_count?: number;
};

type KnowledgeSearchPage = {
  total_count: number;
  limit: number;
  offset: number;
  query: string;
  market_code: string;
  city?: string | null;
  embedding_model?: string;
  records: KnowledgeFactSearchResult[];
  audit_events?: Array<Record<string, unknown>>;
};

type PromptRecord = {
  id?: string;
  project_id?: string;
  text?: string;
  intent_type?: string;
  city?: string;
  language?: string;
  target_brand?: string;
  competitors?: string[];
  priority?: number;
  intent_weight?: number | string;
  prompt_version?: string;
  status?: string;
};

type QueryParams = Record<string, string | string[] | undefined>;

type KnowledgeChunkFilters = {
  query: string;
  status: string;
  embeddingStatus: string;
  chunkType: string;
  qualityFlag: string;
  sourceAssetId: string;
};

const mainTabs = [
  { id: "basic", label: "基础配置" },
  { id: "entry", label: "用户入口" },
  { id: "prompts", label: "Prompt" },
  { id: "knowledge", label: "知识库" },
  { id: "operations", label: "运营工作台" },
  { id: "status", label: "项目状态" },
  { id: "e2e", label: "全流程测试" }
] as const;

const basicTabs = [
  { id: "project", label: "项目与品牌" },
  { id: "launch", label: "启动配置" },
  { id: "competitors", label: "竞品配置" }
] as const;

const promptTabs = [
  { id: "config", label: "Prompt 配置" },
  { id: "generate", label: "Prompt 生成" },
  { id: "candidates", label: "候选审核" },
  { id: "templates", label: "生成模板" },
  { id: "imports", label: "导入记录" }
] as const;

const knowledgeTabs = [
  { id: "import", label: "导入" },
  { id: "processing", label: "处理任务" },
  { id: "chunks", label: "Chunk 可视化" },
  { id: "search", label: "检索" },
  { id: "dashboard", label: "知识库看板" },
  { id: "quality", label: "质检" },
  { id: "trace", label: "证据追踪" }
] as const;

const statusTabs = [
  { id: "collection", label: "采集运行" },
  { id: "scores", label: "评分快照" },
  { id: "graphs", label: "信源图谱" },
  { id: "lifecycle", label: "最近生命周期" }
] as const;

const operationTabs = [
  { id: "backfill", label: "Google 补录" },
  { id: "review", label: "人工复核" },
  { id: "reports", label: "报告中心" },
  { id: "actions", label: "行动与复测" },
  { id: "content", label: "内容与分发" },
  { id: "assets", label: "品牌资产" },
  { id: "quality", label: "质量与运维" }
] as const;

async function loadProject(projectId: string): Promise<ProjectLoadResult> {
  try {
    const query = new URLSearchParams({ project_id: projectId, surface: "admin" });
    const response = await fetch(`${apiBase()}/v1/projects/runtime?${query.toString()}`, {
      cache: "no-store",
      headers: await actorHeaders()
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => undefined) as { correlation_id?: unknown } | undefined;
      return {
        record: null,
        status: response.status,
        correlation_id: typeof payload?.correlation_id === "string" ? payload.correlation_id : undefined
      };
    }
    const page = (await response.json()) as ProjectPage;
    return { record: page.records[0] || null, status: page.records[0] ? 200 : 404 };
  } catch {
    return { record: null };
  }
}

async function loadLaunchConfig(projectId: string): Promise<LaunchConfigResponse | null> {
  try {
    const response = await fetch(`${apiBase()}/v1/project-launch-configs/runtime?project_id=${encodeURIComponent(projectId)}`, {
      cache: "no-store",
      headers: await actorHeaders()
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as LaunchConfigResponse;
  } catch {
    return null;
  }
}

async function loadScoreWeightConfig(projectId: string, formulaVersion: string): Promise<ScoreWeightConfigResponse | null> {
  const response = await runtimeRequest<ScoreWeightConfigResponse>("/v1/score-weight-configs/runtime", {
    query: { project_id: projectId, formula_version: formulaVersion || "visibility_v1.0" }
  });
  return response.ok && response.data ? response.data : null;
}

async function loadScoreFormulas(): Promise<ScoreFormulaResponse> {
  const response = await runtimeRequest<ScoreFormulaResponse>("/v1/score-formulas/runtime");
  return response.ok && response.data ? response.data : { formulas: [] };
}

async function loadScoreProfiles(): Promise<ScoreProfileResponse> {
  const response = await runtimeRequest<ScoreProfileResponse>("/v1/score-weight-profiles/runtime");
  return response.ok && response.data ? response.data : { records: [], total_count: 0 };
}

async function loadPage<T>(
  path: string,
  projectId: string,
  query: Record<string, string | number | undefined> = {},
  limit = 10
): Promise<PageResponse<T>> {
  const response = await runtimeRequest<PageResponse<T>>(path, { query: { project_id: projectId, limit, ...query } });
  return response.ok && response.data ? response.data : { total_count: 0, records: [], limit, offset: 0 };
}

async function loadKnowledgeSearch(
  projectId: string,
  query: string,
  marketCode: string,
  city: string
): Promise<KnowledgeSearchPage> {
  const effectiveQuery = query.trim() || "shipping returns reviews";
  const response = await runtimeRequest<KnowledgeSearchPage>("/v1/knowledge/chunks/runtime/search", {
    query: {
      project_id: projectId,
      query: effectiveQuery,
      market_code: marketCode || "GLOBAL",
      city: city || undefined,
      limit: 10
    }
  });
  return response.ok && response.data
    ? response.data
    : {
      total_count: 0,
      limit: 10,
      offset: 0,
      query: effectiveQuery,
      market_code: marketCode || "GLOBAL",
      city: city || null,
      records: []
    };
}

async function loadKnowledgePipelineData(
  projectId: string,
  chunkFilters: KnowledgeChunkFilters
): Promise<Record<string, PageResponse<Record<string, unknown>>>> {
  const [
    pipelineRuns,
    importJobs,
    sourceAssets,
    parserRuns,
    blocks,
    tables,
    ocrSpans,
    pageSnapshots,
    chunks,
    qualityFindings,
    qualityGateRuns,
    traceRefs,
    factCandidates,
    approvedFacts,
    factExtractionJobs,
    promptGenerationJobs,
    promptTemplates,
    contentGenerationJobs,
    promptCandidates,
    contentDrafts
  ] = await Promise.all([
    loadPage<Record<string, unknown>>("/v1/knowledge/pipeline-runs/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/import-jobs/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/source-assets/runtime", projectId, {}, 50),
    loadPage<Record<string, unknown>>("/v1/knowledge/parser-runs/runtime", projectId, {}, 50),
    loadPage<Record<string, unknown>>("/v1/knowledge/blocks/runtime", projectId, {}, 100),
    loadPage<Record<string, unknown>>("/v1/knowledge/tables/runtime", projectId, {}, 50),
    loadPage<Record<string, unknown>>("/v1/knowledge/ocr-spans/runtime", projectId, {}, 50),
    loadPage<Record<string, unknown>>("/v1/knowledge/page-snapshots/runtime", projectId, {}, 50),
    loadPage<Record<string, unknown>>("/v1/knowledge/chunks/runtime", projectId, {
      query: chunkFilters.query || undefined,
      status: chunkFilters.status || undefined,
      embedding_status: chunkFilters.embeddingStatus || undefined,
      chunk_type: chunkFilters.chunkType || undefined,
      quality_flag: chunkFilters.qualityFlag || undefined,
      source_asset_id: chunkFilters.sourceAssetId || undefined
    }, 50),
    loadPage<Record<string, unknown>>("/v1/knowledge/quality-findings/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/quality-gate-runs/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/trace-refs/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/fact-candidates/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/approved-facts/runtime", projectId, {}, 50),
    loadPage<Record<string, unknown>>("/v1/knowledge/fact-extraction-jobs/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/prompt-generation-jobs/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/prompt-generation-templates/runtime", projectId, {}, 50),
    loadPage<Record<string, unknown>>("/v1/knowledge/content-generation-jobs/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/prompt-candidates/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/knowledge/content-drafts/runtime", projectId, {}, 20)
  ]);
  const latestPipelineRunId = String(pipelineRuns.records[0]?.id || "");
  const stageResponse = latestPipelineRunId
    ? await runtimeRequest<PageResponse<Record<string, unknown>>>(
        `/v1/knowledge/pipeline-runs/runtime/${encodeURIComponent(latestPipelineRunId)}/stages`,
        { query: { project_id: projectId } }
      )
    : null;
  const pipelineStages = stageResponse?.ok && stageResponse.data
    ? stageResponse.data
    : { total_count: 0, records: [], limit: 50, offset: 0 };
  return {
    pipelineRuns,
    importJobs,
    sourceAssets,
    parserRuns,
    blocks,
    tables,
    ocrSpans,
    pageSnapshots,
    chunks,
    qualityFindings,
    qualityGateRuns,
    traceRefs,
    factCandidates,
    approvedFacts,
    factExtractionJobs,
    promptGenerationJobs,
    promptTemplates,
    contentGenerationJobs,
    promptCandidates,
    contentDrafts,
    pipelineStages
  };
}

function knowledgeApplicationFromPipeline(
  projectId: string,
  pipeline: Record<string, PageResponse<Record<string, unknown>>>
): Record<string, unknown> {
  const factJobs = (pipeline.factExtractionJobs?.records || []).map((job) => ({
    ...job,
    job_type: "extract_facts",
    generation_model: job.model,
    generation_prompt_version: job.prompt_version
  }));
  const promptJobs = (pipeline.promptGenerationJobs?.records || []).map((job) => ({
    ...job,
    job_type: "prompt_candidates",
    generation_model: job.model,
    generation_prompt_version: job.template_version
  }));
  const contentJobs = (pipeline.contentGenerationJobs?.records || []).map((job) => ({
    ...job,
    job_type: "content_draft",
    generation_model: job.model,
    generation_prompt_version: job.template_version
  }));
  return {
    project_id: projectId,
    knowledge_documents: pipeline.sourceAssets?.records || [],
    knowledge_facts: pipeline.approvedFacts?.records || [],
    generation_jobs: [...factJobs, ...promptJobs, ...contentJobs],
    prompt_candidates: pipeline.promptCandidates?.records || [],
    faq_candidates: [],
    content_drafts: pipeline.contentDrafts?.records || [],
    prompt_templates: pipeline.promptTemplates?.records || [],
    total_count:
      (pipeline.sourceAssets?.total_count || 0)
      + (pipeline.approvedFacts?.total_count || 0)
      + (pipeline.promptCandidates?.total_count || 0)
      + (pipeline.contentDrafts?.total_count || 0)
  };
}

async function loadBrandKit(projectId: string): Promise<Record<string, unknown> | null> {
  const response = await runtimeRequest<Record<string, unknown>>("/v1/project-brand-kits/runtime", {
    query: { project_id: projectId }
  });
  if (!response.ok || !response.data) {
    return null;
  }
  return response.data;
}

export default async function ProjectDetailPage({
  params,
  searchParams
}: {
  params: Promise<{ project_id: string }>;
  searchParams: Promise<QueryParams>;
}) {
  const { project_id: projectId } = await params;
  const queryParams = await searchParams;
  const activeTab = normalizeTab(queryValue(queryParams, "tab"), mainTabs, "basic");
  const requestedBasicTab = queryValue(queryParams, "basic_tab");
  const activeBasicTab = normalizeTab(requestedBasicTab === "brand" ? "project" : requestedBasicTab, basicTabs, "project");
  const activePromptTab = normalizeTab(queryValue(queryParams, "prompt_tab"), promptTabs, "config");
  const activeKnowledgeTab = normalizeTab(queryValue(queryParams, "knowledge_tab"), knowledgeTabs, "import");
  const activeStatusTab = normalizeTab(queryValue(queryParams, "status_tab"), statusTabs, "collection");
  const activeOperationTab = normalizeTab(queryValue(queryParams, "operation_tab"), operationTabs, "backfill");
  const promptStatus = queryValue(queryParams, "prompt_status");
  const promptIntent = queryValue(queryParams, "prompt_intent");
  const promptCity = queryValue(queryParams, "prompt_city");
  const promptOffset = Math.max(0, Number(queryValue(queryParams, "prompt_offset") || 0) || 0);
  const promptLimit = normalizePromptLimit(queryValue(queryParams, "prompt_limit"));
  const promptImported = queryValue(queryParams, "prompt_imported");
  const knowledgeQuery = queryValue(queryParams, "knowledge_query") || "shipping returns reviews";
  const knowledgeMarket = queryValue(queryParams, "knowledge_market");
  const knowledgeCity = queryValue(queryParams, "knowledge_city");
  const knowledgeImported = queryValue(queryParams, "knowledge_imported");
  const knowledgeSourceUploaded = queryValue(queryParams, "source_uploaded");
  const knowledgeSourceRejected = queryValue(queryParams, "source_rejected");
  const traceChunkId = queryValue(queryParams, "trace_chunk_id");
  const knowledgeChunkFilters: KnowledgeChunkFilters = {
    query: queryValue(queryParams, "chunk_query"),
    status: queryValue(queryParams, "chunk_status"),
    embeddingStatus: queryValue(queryParams, "chunk_embedding_status"),
    chunkType: queryValue(queryParams, "chunk_type"),
    qualityFlag: queryValue(queryParams, "chunk_quality_flag"),
    sourceAssetId: queryValue(queryParams, "chunk_source_asset_id")
  };

  const promptQuery = {
    status: promptStatus === "all" ? undefined : promptStatus || undefined,
    intent_type: promptIntent || undefined,
    city: promptCity || undefined,
    offset: promptOffset
  };

  const [projectResult, launchConfig] = await Promise.all([
    loadProject(projectId),
    loadLaunchConfig(projectId)
  ]);
  if (projectResult.status === 401) {
    redirect("/login");
  }
  const record = projectResult.record;
  if (!record) {
    const title = projectResult.status === 403
      ? "无权访问项目"
      : projectResult.status === 404
        ? "项目不存在或已撤回"
        : "项目加载失败";
    const detail = projectResult.status === 403
      ? "当前会话没有此项目的管理权限。"
      : projectResult.status === 404
        ? "该项目不存在、已撤回，或当前会话不可见。"
        : "项目服务暂时不可用，请稍后重试。";
    return (
      <main className="shell">
        <section className="topbar">
          <div>
            <h1>{title}</h1>
            <p className="muted" style={{ marginTop: 8 }}>{detail}</p>
            {projectResult.correlation_id ? (
              <p className="muted" style={{ marginTop: 8 }}>关联 ID：{projectResult.correlation_id}</p>
            ) : null}
          </div>
          <nav className="nav"><a className="button secondary" href="/projects">返回项目列表</a></nav>
        </section>
      </main>
    );
  }
  const launch = launchConfig?.launch_config || {};
  const scoringProfile = stringValue(launch, "scoring_profile") || "visibility_v1.0";

  const [
    scoreConfig,
    scoreFormulas,
    scoreProfiles,
    members,
    invitations,
    prompts,
    knowledge,
    knowledgePipeline,
    collectionJobs,
    collectionRuns,
    scores,
    reports,
    jobs,
    actions,
    graphs,
    evidenceRuns,
    humanReviews,
    humanReviewQueue,
    contentEngines,
    brandAssets,
    fidelityChecks,
    savedViews,
    runtimeAlerts,
    brandKit
  ] = await Promise.all([
    loadScoreWeightConfig(projectId, scoringProfile),
    loadScoreFormulas(),
    loadScoreProfiles(),
    loadPage<Record<string, unknown>>("/v1/project-members/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/project-member-invitations/runtime", projectId),
    loadPage<PromptRecord>("/v1/prompts/runtime", projectId, promptQuery, promptLimit),
    loadKnowledgeSearch(projectId, knowledgeQuery, knowledgeMarket || record?.project.market_code || "GLOBAL", knowledgeCity),
    loadKnowledgePipelineData(projectId, knowledgeChunkFilters),
    loadPage<Record<string, unknown>>("/v1/collection-jobs/runtime", projectId, {}, 20),
    loadPage<Record<string, unknown>>("/v1/collection-runs/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/visibility-scores/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/reports/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/report-export-jobs/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/action-plans/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/citation-graphs/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/evidence-runs/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/human-reviews/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/human-reviews/runtime/queue", projectId),
    loadPage<Record<string, unknown>>("/v1/content-engines/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/project-brand-assets/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/fidelity-checks/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/runtime-saved-views", projectId),
    loadPage<Record<string, unknown>>("/v1/runtime-alerts", projectId),
    loadBrandKit(projectId)
  ]);
  const knowledgeApplication = knowledgeApplicationFromPipeline(projectId, knowledgePipeline);
  const chunkTraceResponse = traceChunkId
    ? await runtimeRequest<Record<string, unknown>>(
        `/v1/knowledge/chunks/runtime/${encodeURIComponent(traceChunkId)}/trace`,
        { query: { project_id: projectId } }
      )
    : null;
  const knowledgeChunkTrace = chunkTraceResponse?.ok && chunkTraceResponse.data ? chunkTraceResponse.data : null;
  const defaultEmail = typeof launch.customer_email === "string" ? launch.customer_email : undefined;
  const competitors = record?.competitors || [];
  const connectorReady = launchConnectorsReady(launch);

  return (
    <main className="shell">
      <section className="topbar compactTopbar">
        <nav className="nav">
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href={`/projects/${projectId}/geo`}>GEO 投放工作区</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <section className="projectHero">
        <p className="eyebrow">项目详情</p>
        <h1>{record?.project.target_brand || record?.project.name || "项目未读取"}</h1>
        <p className="projectMeta">
          {record?.tenant?.name || "API 未连接或无权限"} · {projectId}
        </p>
      </section>

      {record ? (
        <section className="stats projectBoard" aria-label="项目看板">
          <div className="stat"><span className="muted">状态</span><strong>{projectStatusLabel(record.project.status)}</strong></div>
          <div className="stat"><span className="muted">竞品数</span><strong>{competitors.length}</strong></div>
          <div className="stat"><span className="muted">Prompt 数</span><strong>{record.prompt_count ?? prompts.total_count}</strong></div>
          <div className="stat"><span className="muted">市场</span><strong>{record.project.market_code || "GLOBAL"}</strong></div>
          <ProjectStatusControls
            category={record.project.category}
            competitorCount={competitors.length}
            connectorReady={connectorReady}
            primaryDomain={stringValue(launch, "primary_domain")}
            projectId={projectId}
            promptCount={record.prompt_count ?? prompts.total_count}
            status={record.project.status}
            targetBrand={record.project.target_brand}
          />
        </section>
      ) : null}

      <TabBar
        active={activeTab}
        items={mainTabs}
        hrefFor={(tab) => tabHref(projectId, { tab })}
      />

      <section className="workspacePanel">
        {activeTab === "basic" ? (
          <BasicConfigPanel
            activeTab={activeBasicTab}
            competitors={competitors}
            launch={launch}
            projectId={projectId}
            record={record}
            scoreConfig={scoreConfig}
            scoreFormulas={scoreFormulas.formulas || []}
            scoreProfiles={scoreProfiles.records || []}
          />
        ) : null}
        {activeTab === "entry" ? (
          <EntryPanel
            defaultEmail={defaultEmail}
            invitations={invitations}
            launch={launch}
            members={members}
            projectId={projectId}
          />
        ) : null}
        {activeTab === "prompts" ? (
          <PromptPanel
            activeTab={activePromptTab}
            application={knowledgeApplication}
            city={promptCity}
            intent={promptIntent}
            offset={promptOffset}
            projectId={projectId}
            importedCount={promptImported}
            limit={promptLimit}
            status={promptStatus}
            prompts={prompts}
          />
        ) : null}
        {activeTab === "knowledge" ? (
          <KnowledgePanel
            activeTab={activeKnowledgeTab}
            application={knowledgeApplication}
            chunkTrace={knowledgeChunkTrace}
            chunkFilters={knowledgeChunkFilters}
          importedCount={knowledgeImported}
            pipeline={knowledgePipeline}
            locale={stringValue(launch, "locale") || "en"}
            marketCode={knowledgeMarket || record?.project.market_code || "GLOBAL"}
            projectId={projectId}
            searchCity={knowledgeCity}
            searchPage={knowledge}
          searchQuery={knowledgeQuery}
          sourceRejected={knowledgeSourceRejected}
          sourceUploaded={knowledgeSourceUploaded}
          />
        ) : null}
        {activeTab === "operations" ? (
          <OperationsPanel
            actions={actions}
            activeTab={activeOperationTab}
            brandAssets={brandAssets}
            brandKit={brandKit}
            contentEngines={contentEngines}
            evidenceRuns={evidenceRuns}
            fidelityChecks={fidelityChecks}
            humanReviewQueue={humanReviewQueue}
            humanReviews={humanReviews}
            jobs={jobs}
            knowledgePipeline={knowledgePipeline}
            projectId={projectId}
            prompts={prompts}
            reports={reports}
            runtimeAlerts={runtimeAlerts}
            savedViews={savedViews}
          />
        ) : null}
        {activeTab === "status" ? (
          <StatusPanel
            actions={actions}
            activeTab={activeStatusTab}
            collectionJobs={collectionJobs}
            collectionRuns={collectionRuns}
            graphs={graphs}
            jobs={jobs}
            record={record}
            reports={reports}
            scores={scores}
            projectId={projectId}
          />
        ) : null}
        {activeTab === "e2e" ? <E2EPanel devToolsEnabled={adminDevToolsEnabled()} projectId={projectId} /> : null}
      </section>
    </main>
  );
}

function BasicConfigPanel({
  activeTab,
  competitors,
  launch,
  projectId,
  record,
  scoreConfig,
  scoreFormulas,
  scoreProfiles
}: {
  activeTab: string;
  competitors: RuntimeProject["competitors"];
  launch: Record<string, unknown>;
  projectId: string;
  record: RuntimeProject | null;
  scoreConfig: ScoreWeightConfigResponse | null;
  scoreFormulas: Array<Record<string, unknown>>;
  scoreProfiles: Array<{ score_weight_profile?: Record<string, unknown> }>;
}) {
  return (
    <>
      <TabBar
        active={activeTab}
        className="subtabBar"
        items={basicTabs}
        hrefFor={(basicTab) => tabHref(projectId, { tab: "basic", basic_tab: basicTab })}
      />
      {activeTab === "project" ? (
        <section className="detailPanel unframedPanel">
          <div className="sectionTitle">
            <div>
              <p className="eyebrow">项目与品牌</p>
              <h2>项目、租户和目标品牌</h2>
            </div>
          </div>
          {record ? (
            <ProjectBasicsForm record={record} />
          ) : (
            <EmptyState text="项目未读取，检查 API 或权限。" />
          )}
        </section>
      ) : null}
      {activeTab === "launch" ? (
        <section className="detailPanel unframedPanel">
          <p className="eyebrow">启动配置</p>
          <h2>客户入口与采集参数</h2>
          <p className="muted formIntro">常用字段、评分配置和连接器都在当前页面显式呈现；高级配置只放调度等低频参数。</p>
          <LaunchConfigForm
            competitors={competitors || []}
            launch={launch}
            projectId={projectId}
            scoreConfig={scoreConfig?.score_weight_config || null}
            scoreFormulas={scoreFormulas}
            scoreProfiles={scoreProfiles}
          />
        </section>
      ) : null}
      {activeTab === "competitors" ? (
        <section className="detailPanel unframedPanel">
          <p className="eyebrow">竞品配置</p>
          <h2>逐条管理竞品</h2>
          <p className="muted formIntro">每个竞品折叠展示；归档竞品使用 archived 状态，不做物理删除。</p>
          <CompetitorEditor competitors={competitors || []} projectId={projectId} />
        </section>
      ) : null}
    </>
  );
}

function EntryPanel({
  defaultEmail,
  invitations,
  launch,
  members,
  projectId
}: {
  defaultEmail?: string;
  invitations: PageResponse<Record<string, unknown>>;
  launch: Record<string, unknown>;
  members: PageResponse<Record<string, unknown>>;
  projectId: string;
}) {
  return (
    <section className="detailPanel unframedPanel">
      <p className="eyebrow">用户入口</p>
      <h2>邀请、成员与安全会话</h2>
      <p className="muted formIntro">
        用户入口只有一条正式路径：发送一次性邀请，客户兑换后成为项目成员并建立安全会话。新建项目时填写的客户邮箱和默认查看权限在这里明文展示。
      </p>
      <AccessOverview defaultEmail={defaultEmail} invitations={invitations} launch={launch} members={members} />
      <div className="detailPanel nestedPanel">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">客户邀请</p>
            <h3>创建和跟踪客户入口</h3>
          </div>
        </div>
        <InvitationForm
          projectId={projectId}
          defaultEmail={defaultEmail}
          pendingInvitations={invitations.records.filter(
            (record) => stringValue(childRecord(record, "invitation"), "status") === "pending"
          )}
        />
        <InvitationList invitations={invitations.records} projectId={projectId} />
      </div>
      <div className="detailPanel">
          <p className="eyebrow">成员权限</p>
          <h3>内部和客户成员</h3>
          <MemberManagement projectId={projectId} />
          <MemberList members={members.records} />
      </div>
    </section>
  );
}

function PromptPanel({
  activeTab,
  application,
  city,
  importedCount,
  intent,
  limit,
  offset,
  projectId,
  prompts,
  status
}: {
  activeTab: string;
  application: Record<string, unknown>;
  city: string;
  importedCount: string;
  intent: string;
  limit: number;
  offset: number;
  projectId: string;
  prompts: PageResponse<PromptRecord>;
  status: string;
}) {
  const nextOffset = offset + limit;
  const previousOffset = Math.max(0, offset - limit);
  const hasNext = nextOffset < prompts.total_count;
  const exportHref = promptExportHref(projectId, { city, intent, status });
  return (
    <>
      <TabBar
        active={activeTab}
        className="subtabBar"
        items={promptTabs}
        hrefFor={(promptTab) => tabHref(projectId, { tab: "prompts", prompt_tab: promptTab })}
      />
      {activeTab === "config" ? (
        <section className="detailPanel unframedPanel">
          <div className="sectionTitle">
            <div>
              <p className="eyebrow">Prompt 配置</p>
              <h2>正式采集 Prompt</h2>
            </div>
            <a className="button secondary" href={exportHref}>导出 CSV</a>
          </div>
          <form className="promptToolbar" action={`/projects/${projectId}`} method="get">
            <input suppressHydrationWarning type="hidden" name="tab" value="prompts" />
            <input suppressHydrationWarning type="hidden" name="prompt_tab" value="config" />
            <input suppressHydrationWarning type="hidden" name="prompt_offset" value="0" />
            <label>
              <span>状态</span>
              <select suppressHydrationWarning name="prompt_status" defaultValue={status || "all"}>
                <option value="all">全部</option>
                <option value="active">运行中</option>
                <option value="paused">已暂停</option>
                <option value="archived">已归档</option>
              </select>
            </label>
            <label>
              <span>Intent</span>
              <input suppressHydrationWarning name="prompt_intent" defaultValue={intent} placeholder="brand_awareness" />
            </label>
            <label>
              <span>城市</span>
              <input suppressHydrationWarning name="prompt_city" defaultValue={city} placeholder="例如 Shanghai" />
            </label>
            <label>
              <span>每页显示</span>
              <select suppressHydrationWarning name="prompt_limit" defaultValue={String(limit)}>
                <option value="10">10 条</option>
                <option value="20">20 条</option>
                <option value="50">50 条</option>
              </select>
            </label>
            <button type="submit">筛选</button>
          </form>
          {importedCount ? (
            <div className="notice success">
              <p>Prompt 已导入：{importedCount} 条。项目看板和列表已刷新。</p>
            </div>
          ) : null}
          <div className="summaryStrip">
            <span>Prompt 总数</span>
            <strong>{prompts.total_count}</strong>
            <span>当前页</span>
            <strong>{prompts.records.length}</strong>
            <span>每页</span>
            <strong>{limit}</strong>
          </div>
          <div className="promptTable">
            <div className="promptHeader">
              <span>Prompt</span>
              <span>Intent</span>
              <span>城市</span>
              <span>状态</span>
              <span>优先级</span>
              <span>操作</span>
            </div>
            {prompts.records.length ? (
              prompts.records.map((prompt, index) => (
                <PromptEditor projectId={projectId} prompt={prompt} key={prompt.id || `${prompt.text}-${index}`} />
              ))
            ) : (
              <EmptyState text="没有匹配的 Prompt。" />
            )}
          </div>
          <div className="paginationRow">
            <a
              aria-disabled={offset === 0}
              className={`button secondary${offset === 0 ? " disabledLink" : ""}`}
              href={tabHref(projectId, {
                tab: "prompts",
                prompt_tab: "config",
                prompt_status: status || undefined,
                prompt_intent: intent || undefined,
                prompt_city: city || undefined,
                prompt_limit: String(limit),
                prompt_offset: previousOffset ? String(previousOffset) : undefined
              })}
            >
              上一页
            </a>
            <span className="muted">第 {Math.floor(offset / limit) + 1} 页</span>
            <a
              aria-disabled={!hasNext}
              className={`button secondary${!hasNext ? " disabledLink" : ""}`}
              href={tabHref(projectId, {
                tab: "prompts",
                prompt_tab: "config",
                prompt_status: status || undefined,
                prompt_intent: intent || undefined,
                prompt_city: city || undefined,
                prompt_limit: String(limit),
                prompt_offset: hasNext ? String(nextOffset) : undefined
              })}
            >
              下一页
            </a>
          </div>
          <div className="detailPanel nestedPanel">
            <h3>CSV 导入</h3>
            <PromptImportForm projectId={projectId} promptLimit={limit} />
          </div>
        </section>
      ) : null}
      {activeTab === "generate" ? <PromptGenerationPanel application={application} projectId={projectId} /> : null}
      {activeTab === "candidates" ? <PromptCandidatePanel application={application} projectId={projectId} /> : null}
      {activeTab === "templates" ? <PromptTemplatePanel application={application} projectId={projectId} /> : null}
      {activeTab === "imports" ? <PromptImportHistoryPanel application={application} projectId={projectId} /> : null}
    </>
  );
}

function KnowledgePanel({
  activeTab,
  application,
  chunkTrace,
  chunkFilters,
  importedCount,
  locale,
  pipeline,
  marketCode,
  projectId,
  searchCity,
  searchPage,
  searchQuery,
  sourceRejected,
  sourceUploaded
}: {
  activeTab: string;
  application: Record<string, unknown>;
  chunkTrace: Record<string, unknown> | null;
  chunkFilters: KnowledgeChunkFilters;
  importedCount: string;
  locale: string;
  pipeline: Record<string, PageResponse<Record<string, unknown>>>;
  marketCode: string;
  projectId: string;
  searchCity: string;
  searchPage: KnowledgeSearchPage;
  searchQuery: string;
  sourceRejected: string;
  sourceUploaded: string;
}) {
  return (
    <>
      <TabBar
        active={activeTab}
        className="subtabBar"
        items={knowledgeTabs}
        hrefFor={(knowledgeTab) => tabHref(projectId, { tab: "knowledge", knowledge_tab: knowledgeTab })}
      />
      {activeTab === "import" ? (
        <KnowledgeDocumentImportPanel
          application={application}
          defaultLocale={locale}
          defaultMarketCode={marketCode || "GLOBAL"}
          importedCount={importedCount}
          pipeline={pipeline}
          projectId={projectId}
        />
      ) : null}
      {activeTab === "processing" ? (
        <KnowledgeProcessingPanel
          pipeline={pipeline}
          projectId={projectId}
          sourceRejected={sourceRejected}
          sourceUploaded={sourceUploaded}
        />
      ) : null}
      {activeTab === "chunks" ? <KnowledgeChunksPanel chunkFilters={chunkFilters} chunkTrace={chunkTrace} pipeline={pipeline} projectId={projectId} /> : null}
      {activeTab === "search" ? (
        <section className="detailPanel unframedPanel knowledgePanel">
          <div className="sectionTitle">
            <div>
              <p className="eyebrow">知识库检索</p>
              <h2>验证已批准知识是否可用</h2>
            </div>
          </div>
          <form className="knowledgeSearchForm" action={`/projects/${projectId}`} method="get">
            <input suppressHydrationWarning type="hidden" name="tab" value="knowledge" />
            <input suppressHydrationWarning type="hidden" name="knowledge_tab" value="search" />
            <label>
              <span>检索词</span>
              <input suppressHydrationWarning name="knowledge_query" defaultValue={searchQuery} required />
            </label>
            <label>
              <span>市场</span>
              <input suppressHydrationWarning name="knowledge_market" defaultValue={marketCode || "GLOBAL"} required />
            </label>
            <label>
              <span>城市</span>
              <input suppressHydrationWarning name="knowledge_city" defaultValue={searchCity} placeholder="可选，例如 Shanghai" />
            </label>
            <button type="submit">检索知识库</button>
          </form>
          <SummaryTable rows={[
            ["匹配事实", String(searchPage.total_count)],
            ["检索词", searchPage.query || searchQuery],
            ["市场", searchPage.market_code || marketCode || "GLOBAL"],
            ["Embedding", searchPage.embedding_model || "BAAI/bge-m3"]
          ]} />
          <KnowledgeSearchResults searchPage={searchPage} />
        </section>
      ) : null}
      {activeTab === "dashboard" ? <KnowledgeDashboardPanel application={application} searchPage={searchPage} /> : null}
      {activeTab === "quality" ? <KnowledgeQualityPanel application={application} pipeline={pipeline} projectId={projectId} /> : null}
      {activeTab === "trace" ? <KnowledgeTracePanel chunkTrace={chunkTrace} pipeline={pipeline} /> : null}
    </>
  );
}

function KnowledgeProcessingPanel({
  pipeline,
  projectId,
  sourceRejected,
  sourceUploaded
}: {
  pipeline: Record<string, PageResponse<Record<string, unknown>>>;
  projectId: string;
  sourceRejected: string;
  sourceUploaded: string;
}) {
  const runs = pipeline.pipelineRuns?.records || [];
  const importJobs = pipeline.importJobs?.records || [];
  const gateRuns = pipeline.qualityGateRuns?.records || [];
  const findings = pipeline.qualityFindings?.records || [];
  const stages = pipeline.pipelineStages?.records || [];
  const assets = pipeline.sourceAssets?.records || [];
  const parserRuns = pipeline.parserRuns?.records || [];
  const blocks = pipeline.blocks?.records || [];
  const tables = pipeline.tables?.records || [];
  const ocrSpans = pipeline.ocrSpans?.records || [];
  const pageSnapshots = pipeline.pageSnapshots?.records || [];
  return (
    <section className="detailPanel unframedPanel knowledgePanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">知识库处理任务</p>
          <h2>Pipeline、Job 和 Quality Gate</h2>
        </div>
      </div>
      {sourceUploaded ? (
        <div className="notice success">
          <p>文件批次已提交：{sourceUploaded} 个通过预检并进入处理，{sourceRejected || "0"} 个被预检阻断。阻断详情保留在 Quality Findings。</p>
        </div>
      ) : null}
      <div className="metricGrid compact">
        <MetricCard label="Pipeline" value={runs.length} />
        <MetricCard label="导入任务" value={importJobs.length} />
        <MetricCard label="阶段" value={stages.length} />
        <MetricCard label="Gate Runs" value={gateRuns.length} />
        <MetricCard label="质量问题" value={findings.length} />
        <MetricCard label="来源资产" value={assets.length} />
        <MetricCard label="解析运行" value={parserRuns.length} />
        <MetricCard label="Blocks" value={blocks.length} />
        <MetricCard label="表格 / OCR" value={tables.length + ocrSpans.length} />
      </div>
      <div className="twoCol compact">
        <SimpleRecordList
          title="Pipeline Runs"
          emptyText="暂无 Pipeline。"
          records={runs}
          pick={(run) => [
            `${stringValue(run, "run_type") || "run"} · ${shortValue(stringValue(run, "id"))}`,
            `${statusLabel(stringValue(run, "status"))} · ${stringValue(run, "entry_source") || "mixed"} · 等待审核 ${stringValue(run, "waiting_review_count") || "0"}`
          ]}
        />
        <SimpleRecordList
          title="Import Jobs"
          emptyText="暂无导入任务。"
          records={importJobs}
          pick={(job) => [
            `${stringValue(job, "source_mode") || "source"} · ${shortValue(stringValue(job, "id"))}`,
            `${statusLabel(stringValue(job, "status"))} · attempt ${stringValue(job, "attempt_count") || "0"} · ${stringValue(job, "last_error_code") || "无错误"}`
          ]}
        />
      </div>
      <div className="knowledgeArtifactGrid">
        <section className="knowledgeArtifactSection">
          <p className="eyebrow">来源与大产物</p>
          <h3>Source Assets</h3>
          <div className="compactList">
            {assets.map((asset, index) => (
              <div className="compactListItem knowledgeArtifactRow" key={`${stringValue(asset, "id")}-${index}`}>
                <div>
                  <strong>{stringValue(asset, "filename") || stringValue(asset, "title") || shortValue(stringValue(asset, "id"))}</strong>
                  <span>{stringValue(asset, "asset_type")} · {statusLabel(stringValue(asset, "status"))} · {stringValue(asset, "parser_engine") || "待路由"}</span>
                </div>
                <a className="button secondary" href={`/api/knowledge/source-asset?project_id=${encodeURIComponent(projectId)}&source_asset_id=${encodeURIComponent(stringValue(asset, "id"))}`}>下载</a>
              </div>
            ))}
            {!assets.length ? <p className="muted emptyState">暂无来源资产。</p> : null}
          </div>
        </section>
        <SimpleRecordList
          title="Parser Runs"
          emptyText="暂无解析运行。"
          records={parserRuns}
          pick={(run) => [
            `${stringValue(run, "adapter_engine") || "auto"} · ${shortValue(stringValue(run, "id"))}`,
            `${statusLabel(stringValue(run, "status"))} · blocks ${stringValue(run, "block_count") || "0"} · tables ${stringValue(run, "table_count") || "0"} · OCR ${stringValue(run, "ocr_span_count") || "0"}${stringValue(run, "fallback_reason") ? ` · 降级：${stringValue(run, "fallback_reason")}` : ""}`
          ]}
        />
        <SimpleRecordList
          title="Blocks"
          emptyText="暂无解析块。"
          records={blocks}
          pick={(block) => [
            `${stringValue(block, "block_type") || "paragraph"} · page ${stringValue(block, "page_number") || "-"} · order ${stringValue(block, "reading_order") || stringValue(block, "block_index")}`,
            `${shortValue(stringValue(block, "text"), 120)} · confidence ${stringValue(block, "confidence") || "无"}`
          ]}
        />
        <SimpleRecordList
          title="表格产物"
          emptyText="暂无表格产物。"
          records={tables}
          pick={(table) => [
            `${stringValue(table, "caption") || "未命名表格"} · page ${stringValue(table, "page_number") || "-"}`,
            `${stringValue(table, "row_count") || "0"} 行 × ${stringValue(table, "column_count") || "0"} 列 · CSV ${shortValue(stringValue(table, "csv_asset_id")) || "无"} · HTML ${shortValue(stringValue(table, "html_asset_id")) || "无"}`
          ]}
        />
        <SimpleRecordList
          title="OCR Spans"
          emptyText="暂无 OCR 结果。"
          records={ocrSpans}
          pick={(span) => [
            `page ${stringValue(span, "page_number") || "-"} · ${stringValue(span, "language") || "未知语言"}`,
            `${shortValue(stringValue(span, "text"), 120)} · confidence ${stringValue(span, "confidence") || "无"}`
          ]}
        />
        <SimpleRecordList
          title="页面快照"
          emptyText="暂无页面快照。"
          records={pageSnapshots}
          pick={(page) => [
            `${stringValue(page, "title") || "页面"} · page ${stringValue(page, "page_number") || "-"}`,
            `${stringValue(page, "source_url") || "本地文件"} · ${shortValue(stringValue(page, "text_preview"), 100)}`
          ]}
        />
      </div>
      <div className="twoCol compact">
        <SimpleRecordList
          title="Latest Pipeline Stages"
          emptyText="暂无阶段状态。"
          records={stages}
          pick={(stage) => [
            `${stringValue(stage, "stage_key") || "stage"} · ${shortValue(stringValue(stage, "id"))}`,
            `${statusLabel(stringValue(stage, "status"))} · retry ${stringValue(stage, "retry_count") || "0"} · ${stringValue(stage, "error_code") || "无错误"}`
          ]}
        />
        <SimpleRecordList
          title="Quality Gate Runs"
          emptyText="暂无门禁运行。"
          records={gateRuns}
          pick={(gate) => [
            `${stringValue(gate, "gate_key") || "gate"} · ${shortValue(stringValue(gate, "id"))}`,
            `${statusLabel(stringValue(gate, "status"))} · findings ${arrayValue(gate["finding_ids"]).length}`
          ]}
        />
        <SimpleRecordList
          title="Quality Findings"
          emptyText="暂无质量问题。"
          records={findings}
          pick={(finding) => [
            `${stringValue(finding, "finding_type") || "finding"} · ${stringValue(finding, "severity") || "warning"}`,
            `${statusLabel(stringValue(finding, "status"))} · ${shortValue(stringValue(finding, "message"), 100)}`
          ]}
        />
      </div>
      <div className="twoCol compact">
        <KnowledgeMaintenanceRunForm projectId={projectId} runs={runs} />
        <KnowledgeStageRetryForm projectId={projectId} stages={stages} />
      </div>
      <KnowledgeQualityRiskAcceptForm gateRuns={gateRuns} projectId={projectId} />
    </section>
  );
}

function KnowledgeChunksPanel({
  chunkFilters,
  chunkTrace,
  pipeline,
  projectId
}: {
  chunkFilters: KnowledgeChunkFilters;
  chunkTrace: Record<string, unknown> | null;
  pipeline: Record<string, PageResponse<Record<string, unknown>>>;
  projectId: string;
}) {
  const chunks = pipeline.chunks?.records || [];
  const assets = pipeline.sourceAssets?.records || [];
  const selectedChunk = (chunkTrace?.knowledge_chunk || {}) as Record<string, unknown>;
  const selectedBlocks = Array.isArray(chunkTrace?.blocks) ? chunkTrace.blocks as Record<string, unknown>[] : [];
  const selectedFacts = Array.isArray(chunkTrace?.approved_facts) ? chunkTrace.approved_facts as Record<string, unknown>[] : [];
  const runs = pipeline.pipelineRuns?.records || [];
  const importJobs = pipeline.importJobs?.records || [];
  return (
    <section className="detailPanel unframedPanel knowledgePanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">Chunk 可视化</p>
          <h2>解析块、向量状态和 Qdrant Payload</h2>
        </div>
      </div>
      <div className="metricGrid compact">
        <MetricCard label="Chunk 数" value={chunks.length} />
        <MetricCard label="已向量化" value={chunks.filter((chunk) => stringValue(chunk, "embedding_status") === "embedded").length} />
        <MetricCard label="禁用/过期" value={chunks.filter((chunk) => ["disabled", "superseded", "archived"].includes(stringValue(chunk, "status"))).length} />
        <MetricCard label="Qdrant 点" value={chunks.filter((chunk) => stringValue(chunk, "qdrant_point_id")).length} />
      </div>
      <form className="promptToolbar knowledgeChunkFilters" action={`/projects/${projectId}`} method="get">
        <input suppressHydrationWarning type="hidden" name="tab" value="knowledge" />
        <input suppressHydrationWarning type="hidden" name="knowledge_tab" value="chunks" />
        <label><span>包含文本</span><input suppressHydrationWarning name="chunk_query" defaultValue={chunkFilters.query} placeholder="搜索 Chunk 正文" /></label>
        <label><span>生命周期</span><select suppressHydrationWarning name="chunk_status" defaultValue={chunkFilters.status}><option value="">全部</option><option value="active">运行中</option><option value="disabled">已禁用</option><option value="superseded">已替代</option><option value="archived">已归档</option></select></label>
        <label><span>向量状态</span><select suppressHydrationWarning name="chunk_embedding_status" defaultValue={chunkFilters.embeddingStatus}><option value="">全部</option><option value="embedded">已向量化</option><option value="pending">等待向量化</option><option value="failed">向量化失败</option><option value="stale">已过期</option><option value="disabled">已禁用</option></select></label>
        <label><span>Chunk 类型</span><select suppressHydrationWarning name="chunk_type" defaultValue={chunkFilters.chunkType}><option value="">全部</option><option value="text">正文</option><option value="table">表格</option><option value="mixed">混合</option></select></label>
        <label><span>质量标记</span><input suppressHydrationWarning name="chunk_quality_flag" defaultValue={chunkFilters.qualityFlag} placeholder="例如 chunk_duplicate" /></label>
        <label><span>来源</span><select suppressHydrationWarning name="chunk_source_asset_id" defaultValue={chunkFilters.sourceAssetId}><option value="">全部来源</option>{assets.map((asset) => <option key={stringValue(asset, "id")} value={stringValue(asset, "id")}>{stringValue(asset, "filename") || stringValue(asset, "title") || shortValue(stringValue(asset, "id"))}</option>)}</select></label>
        <button type="submit">应用筛选</button>
        <a className="button secondary" href={tabHref(projectId, { tab: "knowledge", knowledge_tab: "chunks" })}>清除</a>
      </form>
      <div className="knowledgeChunkWorkbench">
        <aside className="knowledgeChunkSources">
          <p className="eyebrow">来源</p>
          <h3>文件与网页</h3>
          {assets.map((asset) => (
            <div className="knowledgeSourceItem" key={stringValue(asset, "id")}>
              <strong>{stringValue(asset, "filename") || stringValue(asset, "title") || shortValue(stringValue(asset, "id"))}</strong>
              <span>{stringValue(asset, "asset_type")} · {statusLabel(stringValue(asset, "status"))}</span>
            </div>
          ))}
          {!assets.length ? <p className="muted">暂无来源。</p> : null}
        </aside>
        <div className="knowledgeChunkList">
          <p className="eyebrow">知识单元</p>
          <h3>Chunks</h3>
          {chunks.length ? chunks.map((chunk, index) => (
            <a
              className={`knowledgeChunkItem ${stringValue(selectedChunk, "id") === stringValue(chunk, "id") ? "active" : ""}`}
              href={tabHref(projectId, {
                tab: "knowledge",
                knowledge_tab: "chunks",
                trace_chunk_id: stringValue(chunk, "id"),
                chunk_query: chunkFilters.query,
                chunk_status: chunkFilters.status,
                chunk_embedding_status: chunkFilters.embeddingStatus,
                chunk_type: chunkFilters.chunkType,
                chunk_quality_flag: chunkFilters.qualityFlag,
                chunk_source_asset_id: chunkFilters.sourceAssetId
              })}
              key={`${stringValue(chunk, "id") || "chunk"}-${index}`}
            >
              <strong>{stringValue(chunk, "chunk_type") || "text"} · {shortValue(stringValue(chunk, "id"))}</strong>
              <p>{shortValue(stringValue(chunk, "text"), 220)}</p>
              <span>{statusLabel(stringValue(chunk, "status"))} · {statusLabel(stringValue(chunk, "embedding_status"))} · v{stringValue(chunk, "chunk_version") || "1"}</span>
            </a>
          )) : <EmptyState text="暂无 chunk。请先创建并启动知识库 Pipeline。" />}
        </div>
        <aside className="knowledgeChunkEvidence">
          <p className="eyebrow">证据</p>
          <h3>{stringValue(selectedChunk, "id") ? `Chunk ${shortValue(stringValue(selectedChunk, "id"))}` : "选择一个 Chunk"}</h3>
          {stringValue(selectedChunk, "id") ? (
            <>
              <SummaryTable rows={[
                ["状态", statusLabel(stringValue(selectedChunk, "status"))],
                ["Qdrant", shortValue(stringValue(selectedChunk, "qdrant_point_id")) || "未写入"],
                ["来源 Block", String(selectedBlocks.length)],
                ["正式事实", String(selectedFacts.length)]
              ]} />
              <div className="knowledgeEvidenceText">{stringValue(selectedChunk, "text")}</div>
              {selectedBlocks.slice(0, 5).map((block) => (
                <div className="knowledgeEvidenceBlock" key={stringValue(block, "id")}>
                  <strong>{stringValue(block, "block_type") || "block"} · page {stringValue(block, "page_number") || "-"}</strong>
                  <p>{shortValue(stringValue(block, "text"), 180)}</p>
                </div>
              ))}
              <a className="button secondary" href={tabHref(projectId, { tab: "knowledge", knowledge_tab: "trace", trace_chunk_id: stringValue(selectedChunk, "id") })}>打开完整证据链</a>
            </>
          ) : <p className="muted">点击中间列表中的 Chunk 查看原始 Block、向量状态和正式事实。</p>}
        </aside>
      </div>
      <div className="twoCol compact">
        <KnowledgeMaintenanceRunForm projectId={projectId} runs={runs} />
        <KnowledgeFactExtractionForm assets={assets} importJobs={importJobs} projectId={projectId} runs={runs} />
      </div>
      <KnowledgeChunkControlForm chunks={chunks} projectId={projectId} />
    </section>
  );
}

function KnowledgeTracePanel({
  chunkTrace,
  pipeline
}: {
  chunkTrace: Record<string, unknown> | null;
  pipeline: Record<string, PageResponse<Record<string, unknown>>>;
}) {
  const traceRefs = pipeline.traceRefs?.records || [];
  const selectedChunk = (chunkTrace?.knowledge_chunk || {}) as Record<string, unknown>;
  const selectedBlocks = Array.isArray(chunkTrace?.blocks) ? chunkTrace.blocks as Record<string, unknown>[] : [];
  const selectedFacts = Array.isArray(chunkTrace?.approved_facts) ? chunkTrace.approved_facts as Record<string, unknown>[] : [];
  const selectedPrompts = Array.isArray(chunkTrace?.prompt_candidates) ? chunkTrace.prompt_candidates as Record<string, unknown>[] : [];
  const selectedDrafts = Array.isArray(chunkTrace?.content_drafts) ? chunkTrace.content_drafts as Record<string, unknown>[] : [];
  return (
    <section className="detailPanel unframedPanel knowledgePanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">证据追踪</p>
          <h2>Source Asset 到 Chunk 到 Fact 到 Prompt / Content</h2>
        </div>
      </div>
      {chunkTrace ? (
        <div className="detailPanel spacedPanel">
          <p className="eyebrow">选中 Chunk 完整链路</p>
          <h3>{shortValue(stringValue(selectedChunk, "id"))} · {statusLabel(stringValue(selectedChunk, "status"))}</h3>
          <SummaryTable rows={[
            ["Source Asset", shortValue(stringValue((chunkTrace.source_asset || {}) as Record<string, unknown>, "id")) || "无"],
            ["Parser Run", shortValue(stringValue((chunkTrace.parser_run || {}) as Record<string, unknown>, "id")) || "无"],
            ["Blocks", String(selectedBlocks.length)],
            ["Active Facts", String(selectedFacts.length)],
            ["Prompt Candidates", String(selectedPrompts.length)],
            ["Content Drafts", String(selectedDrafts.length)]
          ]} />
          <p className="muted">{stringValue(selectedChunk, "text") || "无 Chunk 文本"}</p>
        </div>
      ) : (
        <p className="muted formIntro">从“Chunk 可视化”点击“查看证据链”，可查看该 Chunk 到 Block、Parser、Source Asset 和正式事实的完整路径。</p>
      )}
      <SimpleRecordList
        title="Trace Refs"
        emptyText="暂无追踪关系。"
        records={traceRefs}
        pick={(trace) => [
          `${stringValue(trace, "source_type")} -> ${stringValue(trace, "target_type")} · ${stringValue(trace, "trace_role")}`,
          `${shortValue(stringValue(trace, "source_id"))} -> ${shortValue(stringValue(trace, "target_id"))} · confidence ${stringValue(trace, "confidence") || "无"}`
        ]}
      />
    </section>
  );
}

function KnowledgeSearchResults({ searchPage }: { searchPage: KnowledgeSearchPage }) {
  return (
    <div className="detailPanel spacedPanel">
      <p className="eyebrow">检索结果</p>
      <h3>当前项目可用知识片段</h3>
      {searchPage.records.length ? (
        <div className="knowledgeFactList">
          {searchPage.records.map((record, index) => {
            const fact = record.fact || {};
            const chunk = record.chunk || {};
            const item = Object.keys(chunk).length ? chunk : fact;
            const factId = `${index}-${stringValue(item, "id") || "knowledge-item"}`;
            return (
              <div className="knowledgeFactRow" key={factId}>
                <div>
                  <strong>{stringValue(item, "subject") || stringValue(item, "chunk_type") || "知识片段"} · {shortValue(stringValue(item, "id"))}</strong>
                  <p>{stringValue(item, "text") || stringValue(item, "object_value") || "无事实内容"}</p>
                  <p className="muted">
                    {stringValue(item, "fact_type") || stringValue(item, "chunk_type") || "text"} · {stringValue(item, "market_code") || "GLOBAL"} · {stringValue(item, "city") || "global"} · {statusLabel(stringValue(item, "status"))}
                  </p>
                </div>
                <div className="knowledgeScore">
                  <span>相关度</span>
                  <strong>{typeof record.score === "number" ? record.score.toFixed(3) : "0.000"}</strong>
                  {record.fallback_used ? <small>GLOBAL fallback</small> : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <EmptyState text="暂无可检索知识片段。请先完成导入、解析、切分和向量索引，再使用检索词验证。" />
      )}
    </div>
  );
}

function OperationsPanel({
  actions,
  activeTab,
  brandAssets,
  brandKit,
  contentEngines,
  evidenceRuns,
  fidelityChecks,
  humanReviewQueue,
  humanReviews,
  jobs,
  knowledgePipeline,
  projectId,
  prompts,
  reports,
  runtimeAlerts,
  savedViews
}: {
  actions: PageResponse<Record<string, unknown>>;
  activeTab: string;
  brandAssets: PageResponse<Record<string, unknown>>;
  brandKit: Record<string, unknown> | null;
  contentEngines: PageResponse<Record<string, unknown>>;
  evidenceRuns: PageResponse<Record<string, unknown>>;
  fidelityChecks: PageResponse<Record<string, unknown>>;
  humanReviewQueue: PageResponse<Record<string, unknown>>;
  humanReviews: PageResponse<Record<string, unknown>>;
  jobs: PageResponse<Record<string, unknown>>;
  knowledgePipeline: Record<string, PageResponse<Record<string, unknown>>>;
  projectId: string;
  prompts: PageResponse<PromptRecord>;
  reports: PageResponse<Record<string, unknown>>;
  runtimeAlerts: PageResponse<Record<string, unknown>>;
  savedViews: PageResponse<Record<string, unknown>>;
}) {
  return (
    <>
      <TabBar
        active={activeTab}
        className="subtabBar operationSubtabs"
        items={operationTabs}
        hrefFor={(operationTab) => tabHref(projectId, { tab: "operations", operation_tab: operationTab })}
      />
      {activeTab === "backfill" ? (
        <OperationSection
          title="Google 补录"
          description="用于 Google AI Mode 暂未自动化时的正式证据补录。运营人员把人工采集到的回答、citation、截图或 HTML 快照写入证据链，后续评分和报告按这些证据计算。"
          flow="选择 Prompt 或导入 CSV -> 填写回答和证据 URL -> 写入 EvidenceRun/RawAnswer -> 在项目状态里查看采集运行。"
        >
          <ManualBackfillPanel evidenceRuns={evidenceRuns} projectId={projectId} prompts={prompts} />
        </OperationSection>
      ) : null}
      {activeTab === "review" ? (
        <OperationSection
          title="人工复核"
          description="用于修正自动解析、评分输入或知识抽取中的不确定结果。这里记录人工决策和修正内容，保证报告数字可以追溯到人审记录。"
          flow="从复核队列选择目标 -> 记录通过/拒绝/修正 -> 保存审计事件 -> 报告和评分使用最终审核状态。"
        >
          <HumanReviewPanel projectId={projectId} queue={humanReviewQueue} reviews={humanReviews} />
        </OperationSection>
      ) : null}
      {activeTab === "reports" ? (
        <OperationSection
          title="报告中心"
          description="用于生成、审批、发布和撤回客户可见报告。报告任务负责产物生成，报告生命周期负责是否允许客户下载。"
          flow="创建报告任务 -> 任务完成并生成 PDF/Markdown/CSV -> 审批发布 -> 客户门户下载；撤回后客户访问应失败。"
        >
          <ReportCenterPanel jobs={jobs} projectId={projectId} reports={reports} />
        </OperationSection>
      ) : null}
      {activeTab === "actions" ? (
        <OperationSection
          title="行动与复测"
          description="用于把评分问题转成可执行建议，并在优化后重新采集同一组 Prompt 形成前后对比。"
          flow="查看行动建议 -> 分配 owner 和状态 -> 设置客户是否可见 -> 触发复测 -> 查看 before/after/delta。"
        >
          <ActionPlanPanel actions={actions} projectId={projectId} />
        </OperationSection>
      ) : null}
      {activeTab === "content" ? (
        <OperationSection
          title="内容与分发"
          description="用于审核基于知识库生成的 GEO 文案，并手工回填实际发布 URL 或证明。它不替代 CMS 发布，只记录分发结果。"
          flow="生成或导入内容草稿 -> 审核草稿 -> 手工发布到目标渠道 -> 回填 URL/proof -> 后续复测验证效果。"
        >
          <ContentWorkbenchPanel
            content={contentEngines}
            contentDrafts={knowledgePipeline.contentDrafts?.records || []}
            contentGenerationJobs={knowledgePipeline.contentGenerationJobs?.records || []}
            projectId={projectId}
          />
        </OperationSection>
      ) : null}
      {activeTab === "assets" ? (
        <OperationSection
          title="品牌资产"
          description="用于登记 logo、图片、品牌文档等客户资产，供报告模板、客户门户和内容生成使用。"
          flow="登记资产 URL -> 标注类型和分类 -> 质检/扫描 -> 在报告和内容工作台引用。"
        >
          <BrandAssetsPanel assets={brandAssets} brandKit={brandKit} projectId={projectId} />
        </OperationSection>
      ) : null}
      {activeTab === "quality" ? (
        <OperationSection
          title="质量与运维"
          description="用于保存常用视图、创建报告一致性检查并查看运行告警。它服务于交付质量，不负责配置连接器密钥。"
          flow="创建 fidelity check -> 查看 mismatch 和告警 -> 保存常用排查视图 -> 在最终验收中复核。"
        >
          <QualityOpsPanel
            alerts={runtimeAlerts}
            fidelityChecks={fidelityChecks}
            projectId={projectId}
            reports={reports}
            savedViews={savedViews}
          />
        </OperationSection>
      ) : null}
    </>
  );
}

function OperationSection({
  children,
  description,
  flow,
  title
}: {
  children: ReactNode;
  description: string;
  flow: string;
  title: string;
}) {
  return (
    <section className="operationSection">
      <div className="operationGuide">
        <div>
          <p className="eyebrow">运营工作台</p>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <div>
          <span>操作流程</span>
          <strong>{flow}</strong>
        </div>
      </div>
      {children}
    </section>
  );
}

function AccessOverview({
  defaultEmail,
  invitations,
  launch,
  members
}: {
  defaultEmail?: string;
  invitations: PageResponse<Record<string, unknown>>;
  launch: Record<string, unknown>;
  members: PageResponse<Record<string, unknown>>;
}) {
  const pendingInvitations = invitations.records.filter((record) => stringValue(childRecord(record, "invitation"), "status") === "pending");
  const defaultRole = pendingInvitations[0] ? stringValue(childRecord(pendingInvitations[0], "invitation"), "role") || "viewer" : "viewer";
  return (
    <div className="accessFlow">
      <div className="accessStep">
        <span>1</span>
        <strong>客户邀请</strong>
        <p>运营人员输入客户邮箱并生成一次性 invitation token。若同一客户已有待处理邀请，必须确认旧邀请失效后再生成新邀请。</p>
      </div>
      <div className="accessStep">
        <span>2</span>
        <strong>成员权限</strong>
        <p>客户兑换邀请后写入项目成员。新建项目默认客户权限为 {defaultRole === "viewer" ? "客户查看者" : defaultRole}，只允许访问授权项目。</p>
      </div>
      <div className="accessStep">
        <span>3</span>
        <strong>安全会话</strong>
        <p>邀请只能兑换一次。兑换后由服务端会话控制客户访问，URL 不携带长期 token；撤销会话或成员权限后立即失去访问权。</p>
      </div>
      <div className="detailPanel">
        <p className="eyebrow">访问对象</p>
        <h3>新建项目时的客户访问权限</h3>
        <SummaryTable rows={[
          ["客户邮箱", defaultEmail || "未配置"],
          ["默认角色", defaultRole === "viewer" ? "客户查看者" : defaultRole],
          ["入口状态", pendingInvitations.length ? "已有待处理邀请" : "暂无待处理邀请"],
          ["访问项目", stringValue(launch, "project_id") || "当前项目"]
        ]} />
      </div>
      <div className="detailPanel">
        <p className="eyebrow">访问状态</p>
        <h3>当前入口资源</h3>
        <SummaryTable rows={[
          ["成员数量", String(members.total_count)],
          ["邀请数量", String(invitations.total_count)],
          ["访问方式", "安全会话"]
        ]} />
      </div>
    </div>
  );
}

function StatusPanel({
  actions,
  activeTab,
  collectionJobs,
  collectionRuns,
  graphs,
  jobs,
  record,
  reports,
  scores,
  projectId
}: {
  actions: PageResponse<Record<string, unknown>>;
  activeTab: string;
  collectionJobs: PageResponse<Record<string, unknown>>;
  collectionRuns: PageResponse<Record<string, unknown>>;
  graphs: PageResponse<Record<string, unknown>>;
  jobs: PageResponse<Record<string, unknown>>;
  record: RuntimeProject | null;
  reports: PageResponse<Record<string, unknown>>;
  scores: PageResponse<Record<string, unknown>>;
  projectId: string;
}) {
  return (
    <>
      <TabBar
        active={activeTab}
        className="subtabBar"
        items={statusTabs}
        hrefFor={(statusTab) => tabHref(projectId, { tab: "status", status_tab: statusTab })}
      />
      {activeTab === "collection" ? (
        <>
          <CollectionJobPanel
            jobs={collectionJobs}
            projectId={projectId}
            projectStatus={record?.project.status || "paused"}
          />
          <RuntimeSummary title="采集运行" page={collectionRuns} />
        </>
      ) : null}
      {activeTab === "scores" ? <RuntimeSummary title="评分快照" page={scores} /> : null}
      {activeTab === "reports" ? <RuntimeSummary title="报告" page={reports} /> : null}
      {activeTab === "jobs" ? <RuntimeSummary title="报告任务" page={jobs} /> : null}
      {activeTab === "actions" ? <RuntimeSummary title="行动计划" page={actions} /> : null}
      {activeTab === "graphs" ? <RuntimeSummary title="信源图谱" page={graphs} /> : null}
      {activeTab === "lifecycle" ? (
        <section className="detailPanel unframedPanel">
          <p className="eyebrow">最近生命周期</p>
          <h2>配置审计</h2>
          <SummaryTable rows={(record?.audit_events || []).slice(0, 10).map((event) => [
            String(event.event_type || "audit_event"),
            String(event.created_at || event.method_version || "")
          ])} />
        </section>
      ) : null}
    </>
  );
}

function E2EPanel({ devToolsEnabled, projectId }: { devToolsEnabled: boolean; projectId: string }) {
  return (
    <section className="detailPanel unframedPanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">全流程测试</p>
          <h2>采集、评分、报告与追溯</h2>
        </div>
      </div>
      {devToolsEnabled ? (
        <>
          <p className="muted formIntro">开发工具已开启：使用本地 collector 写入当前项目，用真实数据库和对象存储验证本地闭环。</p>
          <FixtureE2EForm projectId={projectId} />
        </>
      ) : (
        <p className="muted formIntro">生产环境不暴露本地测试入口。请通过正式采集任务和最终验收命令执行全流程验证。</p>
      )}
    </section>
  );
}

function TabBar<T extends readonly { id: string; label: string }[]>({
  active,
  className,
  hrefFor,
  items
}: {
  active: string;
  className?: string;
  hrefFor: (id: T[number]["id"]) => string;
  items: T;
}) {
  return (
    <nav className={className ? `tabBar ${className}` : "tabBar"}>
      {items.map((item) => (
        <a className={`tabLink${item.id === active ? " active" : ""}`} href={hrefFor(item.id)} key={item.id}>
          {item.label}
        </a>
      ))}
    </nav>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="muted emptyState">{text}</p>;
}

function SummaryTable({ rows }: { rows: Array<[string, string]> }) {
  if (rows.length === 0) {
    return <EmptyState text="暂无数据。" />;
  }
  return (
    <div className="summaryTable">
      {rows.map(([label, value], index) => (
        <div key={`${index}-${label}-${value}`}>
          <span>{label}</span>
          <strong>{value || "无"}</strong>
        </div>
      ))}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metricCard">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SimpleRecordList({
  emptyText,
  pick,
  records,
  title
}: {
  emptyText: string;
  pick: (record: Record<string, unknown>) => [string, string];
  records: Array<Record<string, unknown>>;
  title: string;
}) {
  return (
    <div className="detailPanel">
      <p className="eyebrow">{title}</p>
      {records.length ? (
        <div className="compactList">
          {records.map((record, index) => {
            const [primary, secondary] = pick(record);
            return (
              <div className="compactListItem" key={`${stringValue(record, "id") || title}-${index}`}>
                <strong>{primary}</strong>
                <span>{secondary}</span>
              </div>
            );
          })}
        </div>
      ) : (
        <EmptyState text={emptyText} />
      )}
    </div>
  );
}

function childRecord(record: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = record[key];
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function shortValue(value: string, maxLength = 14): string {
  if (!value) {
    return "";
  }
  return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value;
}

function numberValue(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function percentValue(value: number | null): string {
  return value === null ? "" : `${Math.round(value * 100)}%`;
}

function runtimeSummaryRows(title: string, records: Array<Record<string, unknown>>): Array<[string, string]> {
  return records.slice(0, 6).map((record, index) => {
    if (title === "采集运行") {
      const run = childRecord(record, "collection_run");
      return [
        `${stringValue(run, "run_type") || `采集运行 ${index + 1}`} · ${stringValue(run, "mode") || "unknown"}`,
        `${stringValue(run, "success_count") || "0"}/${stringValue(run, "attempted_runs") || "0"} · ${percentValue(numberValue(run, "success_rate"))}`
      ];
    }
    if (title === "评分快照") {
      const snapshot = childRecord(record, "score_snapshot");
      return [
        stringValue(snapshot, "formula_version") || `评分快照 ${index + 1}`,
        `${stringValue(snapshot, "final_score") || "0"} · ${stringValue(snapshot, "created_at") || ""}`
      ];
    }
    if (title === "报告") {
      const report = childRecord(record, "report_export");
      return [
        stringValue(report, "report_version") || `报告 ${index + 1}`,
        `${stringValue(report, "report_type") || "runtime"} · ${stringValue(report, "exported_at") || ""}`
      ];
    }
    if (title === "行动计划") {
      const schedule = childRecord(record, "retest_schedule");
      return [
        `Action ${index + 1}`,
        `${stringValue(schedule, "sample_size") || "0"} samples · ${stringValue(schedule, "created_at") || ""}`
      ];
    }
    if (title === "信源图谱") {
      const nodes = Array.isArray(record.nodes) ? record.nodes.length : 0;
      const gaps = Array.isArray(record.source_gaps) ? record.source_gaps.length : 0;
      return [`图谱 ${index + 1}`, `${nodes} nodes · ${gaps} gaps`];
    }
    return [
      String(record.title || record.status || record.id || `${title} ${index + 1}`),
      String(record.created_at || record.updated_at || record.report_version || record.score || "")
    ];
  });
}

function RuntimeSummary({ title, page }: { title: string; page: PageResponse<Record<string, unknown>> }) {
  return (
    <section className="detailPanel unframedPanel">
      <span className="statusPill">{page.total_count} 条</span>
      <h2>{title}</h2>
      <p className="muted">运行结果只做摘要展示，不作为配置编辑对象。</p>
      <SummaryTable rows={runtimeSummaryRows(title, page.records)} />
    </section>
  );
}

function normalizeTab<T extends readonly { id: string }[]>(value: string, items: T, fallback: T[number]["id"]): T[number]["id"] {
  return items.some((item) => item.id === value) ? value as T[number]["id"] : fallback;
}

function queryValue(params: QueryParams, key: string): string {
  const value = params[key];
  return Array.isArray(value) ? value[0] || "" : value || "";
}

function tabHref(projectId: string, query: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value) {
      params.set(key, value);
    }
  }
  const suffix = params.toString();
  return `/projects/${projectId}${suffix ? `?${suffix}` : ""}`;
}

function normalizePromptLimit(raw: string): number {
  const parsed = Number(raw || "20");
  return [10, 20, 50].includes(parsed) ? parsed : 20;
}

function promptExportHref(projectId: string, filters: { city: string; intent: string; status: string }): string {
  const url = new URL("/v1/prompts/runtime/export.csv", browserApiBase());
  url.searchParams.set("project_id", projectId);
  if (filters.city) {
    url.searchParams.set("city", filters.city);
  }
  if (filters.intent) {
    url.searchParams.set("intent_type", filters.intent);
  }
  if (filters.status && filters.status !== "all") {
    url.searchParams.set("status", filters.status);
  }
  url.searchParams.set("limit", "200");
  return url.toString();
}

function browserApiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:18003";
}

function launchConnectorsReady(launch: Record<string, unknown>): boolean {
  const externalConnectors = childRecord(launch, "external_connectors");
  const statuses = ["openai", "perplexity", "google_ai_mode"].map((key) =>
    stringValue(childRecord(externalConnectors, key), "status").toLowerCase()
  );
  return statuses.some((status) => ["active", "ready", "manual_ready"].includes(status));
}
