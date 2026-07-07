import {
  BrandAssetsPanel,
  CompetitorEditor,
  ContentWorkbenchPanel,
  FixtureE2EForm,
  HumanReviewPanel,
  InvitationForm,
  InvitationList,
  KnowledgeFactImportForm,
  KnowledgeDashboardPanel,
  KnowledgeDocumentImportPanel,
  KnowledgeQualityPanel,
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
  ActionPlanPanel,
  TokenList,
  TokenCreateForm,
  TokenRevokeForm
} from "./ProjectActions";
import type { ReactNode } from "react";
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
  { id: "search", label: "检索" },
  { id: "dashboard", label: "知识库看板" },
  { id: "quality", label: "质检" }
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

async function loadProject(projectId: string): Promise<RuntimeProject | null> {
  try {
    const response = await fetch(`${apiBase()}/v1/projects/runtime?project_id=${encodeURIComponent(projectId)}`, {
      cache: "no-store",
      headers: actorHeaders()
    });
    if (!response.ok) {
      return null;
    }
    const page = (await response.json()) as ProjectPage;
    return page.records[0] || null;
  } catch {
    return null;
  }
}

async function loadLaunchConfig(projectId: string): Promise<LaunchConfigResponse | null> {
  try {
    const response = await fetch(`${apiBase()}/v1/project-launch-configs/runtime?project_id=${encodeURIComponent(projectId)}`, {
      cache: "no-store",
      headers: actorHeaders()
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
    query: { project_id: projectId, formula_version: formulaVersion || "au_visibility_v1" }
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
  const response = await runtimeRequest<KnowledgeSearchPage>("/v1/knowledge-facts/runtime/search", {
    query: {
      project_id: projectId,
      query: effectiveQuery,
      market_code: marketCode || "AU",
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
      market_code: marketCode || "AU",
      city: city || null,
      records: []
    };
}

async function loadKnowledgeApplication(projectId: string): Promise<Record<string, unknown>> {
  const response = await runtimeRequest<Record<string, unknown>>("/v1/knowledge-applications/runtime", {
    query: { project_id: projectId, limit: 50 }
  });
  return response.ok && response.data
    ? response.data
    : {
      project_id: projectId,
      knowledge_documents: [],
      knowledge_facts: [],
      generation_jobs: [],
      prompt_candidates: [],
      faq_candidates: [],
      content_drafts: [],
      total_count: 0
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
  const knowledgeMarket = queryValue(queryParams, "knowledge_market") || "AU";
  const knowledgeCity = queryValue(queryParams, "knowledge_city");
  const knowledgeImported = queryValue(queryParams, "knowledge_imported");

  const promptQuery = {
    status: promptStatus === "all" ? undefined : promptStatus || undefined,
    intent_type: promptIntent || undefined,
    city: promptCity || undefined,
    offset: promptOffset
  };

  const [record, launchConfig] = await Promise.all([
    loadProject(projectId),
    loadLaunchConfig(projectId)
  ]);
  const launch = launchConfig?.launch_config || {};
  const scoringProfile = stringValue(launch, "scoring_profile") || "au_visibility_v1";

  const [
    scoreConfig,
    scoreFormulas,
    scoreProfiles,
    members,
    invitations,
    tokens,
    prompts,
    knowledge,
    knowledgeApplication,
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
    loadPage<Record<string, unknown>>("/v1/customer-portal/tokens/runtime", projectId),
    loadPage<PromptRecord>("/v1/prompts/runtime", projectId, promptQuery, promptLimit),
    loadKnowledgeSearch(projectId, knowledgeQuery, knowledgeMarket || record?.project.market_code || "AU", knowledgeCity),
    loadKnowledgeApplication(projectId),
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
  const defaultEmail = typeof launch.customer_email === "string" ? launch.customer_email : undefined;
  const competitors = record?.competitors || [];
  const connectorReady = launchConnectorsReady(launch);

  return (
    <main className="shell">
      <section className="topbar compactTopbar">
        <nav className="nav">
          <a className="button secondary" href="/projects">项目列表</a>
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
          <div className="stat"><span className="muted">市场</span><strong>{record.project.market_code || "AU"}</strong></div>
          <ProjectStatusControls
            category={record.project.category}
            competitorCount={competitors.length}
            connectorReady={connectorReady}
            launchStatus={stringValue(launch, "status")}
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
            tokens={tokens}
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
            importedCount={knowledgeImported}
            marketCode={knowledgeMarket || record?.project.market_code || "AU"}
            projectId={projectId}
            searchCity={knowledgeCity}
            searchPage={knowledge}
            searchQuery={knowledgeQuery}
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
  projectId,
  tokens
}: {
  defaultEmail?: string;
  invitations: PageResponse<Record<string, unknown>>;
  launch: Record<string, unknown>;
  members: PageResponse<Record<string, unknown>>;
  projectId: string;
  tokens: PageResponse<Record<string, unknown>>;
}) {
  return (
    <section className="detailPanel unframedPanel">
      <p className="eyebrow">用户入口</p>
      <h2>邀请、成员与门户 token</h2>
      <p className="muted formIntro">
        用户入口分三层：先发客户邀请，客户兑换后成为项目成员，再由门户 token/session 控制后续访问。新建项目时填写的客户邮箱和默认 viewer 权限在这里明文展示。
      </p>
      <AccessOverview defaultEmail={defaultEmail} invitations={invitations} launch={launch} members={members} tokens={tokens} />
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
      <div className="twoCol compact">
        <div className="detailPanel">
          <p className="eyebrow">门户 token</p>
          <h3>生成、撤销与查看状态</h3>
          <TokenCreateForm projectId={projectId} />
          <TokenRevokeForm projectId={projectId} />
          <TokenList tokens={tokens.records} />
        </div>
        <div className="detailPanel">
          <p className="eyebrow">成员权限</p>
          <h3>内部和客户成员</h3>
          <MemberManagement projectId={projectId} />
          <MemberList members={members.records} />
        </div>
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
              <input suppressHydrationWarning name="prompt_city" defaultValue={city} placeholder="Sydney" />
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
      {activeTab === "templates" ? <PromptTemplatePanel application={application} /> : null}
      {activeTab === "imports" ? <PromptImportHistoryPanel application={application} projectId={projectId} /> : null}
    </>
  );
}

function KnowledgePanel({
  activeTab,
  application,
  importedCount,
  marketCode,
  projectId,
  searchCity,
  searchPage,
  searchQuery
}: {
  activeTab: string;
  application: Record<string, unknown>;
  importedCount: string;
  marketCode: string;
  projectId: string;
  searchCity: string;
  searchPage: KnowledgeSearchPage;
  searchQuery: string;
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
          defaultMarketCode={marketCode || "AU"}
          importedCount={importedCount}
          projectId={projectId}
          searchQuery={searchQuery}
        />
      ) : null}
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
              <input suppressHydrationWarning name="knowledge_market" defaultValue={marketCode || "AU"} required />
            </label>
            <label>
              <span>城市</span>
              <input suppressHydrationWarning name="knowledge_city" defaultValue={searchCity} placeholder="可选，例如 Sydney" />
            </label>
            <button type="submit">检索知识库</button>
          </form>
          <SummaryTable rows={[
            ["匹配事实", String(searchPage.total_count)],
            ["检索词", searchPage.query || searchQuery],
            ["市场", searchPage.market_code || marketCode || "AU"],
            ["Embedding", searchPage.embedding_model || "fixture-knowledge-embedding-v1"]
          ]} />
          <KnowledgeSearchResults searchPage={searchPage} />
        </section>
      ) : null}
      {activeTab === "dashboard" ? <KnowledgeDashboardPanel application={application} searchPage={searchPage} /> : null}
      {activeTab === "quality" ? <KnowledgeQualityPanel application={application} projectId={projectId} /> : null}
    </>
  );
}

function KnowledgeSearchResults({ searchPage }: { searchPage: KnowledgeSearchPage }) {
  return (
    <div className="detailPanel spacedPanel">
      <p className="eyebrow">检索结果</p>
      <h3>当前项目可用知识事实</h3>
      {searchPage.records.length ? (
        <div className="knowledgeFactList">
          {searchPage.records.map((record, index) => {
            const fact = record.fact || {};
            const factId = `${index}-${stringValue(fact, "id") || "knowledge-fact"}`;
            return (
              <div className="knowledgeFactRow" key={factId}>
                <div>
                  <strong>{stringValue(fact, "subject") || "未知主体"} · {stringValue(fact, "predicate") || "未知谓词"}</strong>
                  <p>{stringValue(fact, "object_value") || "无事实内容"}</p>
                  <p className="muted">
                    {stringValue(fact, "fact_type") || "unknown"} · {stringValue(fact, "market_code") || "AU"} · {stringValue(fact, "city") || "global"} · {statusLabel(stringValue(fact, "status"))}
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
        <EmptyState text="暂无可检索知识事实。请先导入并批准知识，再使用检索词验证。" />
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
          <ContentWorkbenchPanel content={contentEngines} projectId={projectId} />
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
  members,
  tokens
}: {
  defaultEmail?: string;
  invitations: PageResponse<Record<string, unknown>>;
  launch: Record<string, unknown>;
  members: PageResponse<Record<string, unknown>>;
  tokens: PageResponse<Record<string, unknown>>;
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
        <strong>门户 token / session</strong>
        <p>门户 token 只显示一次，用于客户门户登录换取会话；撤销后客户不能继续下载报告或查看项目内容。</p>
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
          ["门户 token", String(tokens.total_count)]
        ]} />
      </div>
    </div>
  );
}

function StatusPanel({
  actions,
  activeTab,
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
      {activeTab === "collection" ? <RuntimeSummary title="采集运行" page={collectionRuns} /> : null}
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
