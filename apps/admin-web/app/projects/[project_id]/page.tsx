import {
  BrandEntityForm,
  CompetitorEditor,
  FixtureE2EForm,
  InvitationForm,
  InvitationList,
  LaunchConfigForm,
  MemberList,
  MemberManagement,
  ProjectBasicsForm,
  ProjectLifecycleForm,
  PromptEditor,
  PromptImportForm,
  TokenList,
  TokenCreateForm,
  TokenRevokeForm
} from "./ProjectActions";
import { actorHeaders, adminDevToolsEnabled, apiBase, runtimeRequest } from "../../runtime";

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
  { id: "prompts", label: "Prompt 配置" },
  { id: "status", label: "项目状态" },
  { id: "e2e", label: "全流程测试" }
] as const;

const basicTabs = [
  { id: "project", label: "基础配置" },
  { id: "launch", label: "启动配置" },
  { id: "brand", label: "品牌配置" },
  { id: "competitors", label: "竞品配置" }
] as const;

const statusTabs = [
  { id: "collection", label: "采集运行" },
  { id: "scores", label: "评分快照" },
  { id: "reports", label: "报告" },
  { id: "jobs", label: "报告任务" },
  { id: "actions", label: "行动计划" },
  { id: "graphs", label: "信源图谱" },
  { id: "lifecycle", label: "最近生命周期" }
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

async function loadPage<T>(
  path: string,
  projectId: string,
  query: Record<string, string | number | undefined> = {},
  limit = 10
): Promise<PageResponse<T>> {
  const response = await runtimeRequest<PageResponse<T>>(path, { query: { project_id: projectId, limit, ...query } });
  return response.ok && response.data ? response.data : { total_count: 0, records: [], limit, offset: 0 };
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
  const activeBasicTab = normalizeTab(queryValue(queryParams, "basic_tab"), basicTabs, "project");
  const activeStatusTab = normalizeTab(queryValue(queryParams, "status_tab"), statusTabs, "collection");
  const promptStatus = queryValue(queryParams, "prompt_status");
  const promptIntent = queryValue(queryParams, "prompt_intent");
  const promptCity = queryValue(queryParams, "prompt_city");
  const promptOffset = Math.max(0, Number(queryValue(queryParams, "prompt_offset") || 0) || 0);
  const promptLimit = normalizePromptLimit(queryValue(queryParams, "prompt_limit"));
  const promptImported = queryValue(queryParams, "prompt_imported");

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

  const [scoreConfig, scoreFormulas, members, invitations, tokens, prompts, collectionRuns, scores, reports, jobs, actions, graphs] = await Promise.all([
    loadScoreWeightConfig(projectId, scoringProfile),
    loadScoreFormulas(),
    loadPage<Record<string, unknown>>("/v1/project-members/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/project-member-invitations/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/customer-portal/tokens/runtime", projectId),
    loadPage<PromptRecord>("/v1/prompts/runtime", projectId, promptQuery, promptLimit),
    loadPage<Record<string, unknown>>("/v1/collection-runs/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/visibility-scores/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/reports/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/report-export-jobs/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/action-plans/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/citation-graphs/runtime", projectId)
  ]);
  const defaultEmail = typeof launch.customer_email === "string" ? launch.customer_email : undefined;
  const competitors = record?.competitors || [];

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
          <div className="stat"><span className="muted">状态</span><strong>{statusLabel(record.project.status)}</strong></div>
          <div className="stat"><span className="muted">竞品数</span><strong>{competitors.length}</strong></div>
          <div className="stat"><span className="muted">Prompt 数</span><strong>{record.prompt_count ?? prompts.total_count}</strong></div>
          <div className="stat"><span className="muted">市场</span><strong>{record.project.market_code || "AU"}</strong></div>
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
  scoreFormulas
}: {
  activeTab: string;
  competitors: RuntimeProject["competitors"];
  launch: Record<string, unknown>;
  projectId: string;
  record: RuntimeProject | null;
  scoreConfig: ScoreWeightConfigResponse | null;
  scoreFormulas: Array<Record<string, unknown>>;
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
              <p className="eyebrow">基础配置</p>
              <h2>项目与租户</h2>
            </div>
            {record ? <ProjectLifecycleForm projectId={projectId} status={record.project.status} /> : null}
          </div>
          {record ? <ProjectBasicsForm record={record} /> : <EmptyState text="项目未读取，检查 API 或权限。" />}
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
          />
        </section>
      ) : null}
      {activeTab === "brand" ? (
        <section className="detailPanel unframedPanel">
          <p className="eyebrow">品牌配置</p>
          <h2>目标品牌</h2>
          <BrandEntityForm brand={record?.brand || null} fallbackName={record?.project.target_brand} projectId={projectId} />
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
        创建 viewer 邀请后，客户首次使用 invitation token 进入 Customer Web 并换取门户 token。raw token 只显示一次。
      </p>
      <AccessOverview defaultEmail={defaultEmail} invitations={invitations} launch={launch} members={members} tokens={tokens} />
      <div className="detailPanel nestedPanel">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">客户邀请</p>
            <h3>创建和跟踪客户入口</h3>
          </div>
        </div>
        <InvitationForm projectId={projectId} defaultEmail={defaultEmail} />
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
  city,
  importedCount,
  intent,
  limit,
  offset,
  projectId,
  prompts,
  status
}: {
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
    <section className="detailPanel unframedPanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">Prompt 配置</p>
          <h2>筛选、编辑与导入</h2>
        </div>
        <a className="button secondary" href={exportHref}>导出 CSV</a>
      </div>
      <form className="promptToolbar" action={`/projects/${projectId}`} method="get">
        <input suppressHydrationWarning type="hidden" name="tab" value="prompts" />
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
  return (
    <div className="accessFlow">
      <div className="detailPanel">
        <p className="eyebrow">访问对象</p>
        <h3>新建项目时的客户访问权限</h3>
        <SummaryTable rows={[
          ["客户邮箱", defaultEmail || "未配置"],
          ["默认角色", pendingInvitations[0] ? stringValue(childRecord(pendingInvitations[0], "invitation"), "role") || "viewer" : "viewer"],
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
      {rows.map(([label, value]) => (
        <div key={`${label}-${value}`}>
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

function statusLabel(status?: string): string {
  const labels: Record<string, string> = {
    configured: "已配置",
    active: "运行中",
    paused: "已暂停",
    archived: "已归档",
    draft: "草稿",
    ready: "就绪",
    fixture: "开发测试",
    pending: "待处理",
    accepted: "已接受",
    revoked: "已撤销"
  };
  return labels[String(status || "").toLowerCase()] || status || "未知";
}
