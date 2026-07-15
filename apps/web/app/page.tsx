type PageResponse<T> = {
  total_count: number;
  records: T[];
};

type RuntimeProject = {
  project: {
    id: string;
    name: string;
    market_code: string;
    industry_code?: string;
    target_brand: string;
    category?: string;
    prompt_version?: string;
    status: string;
  };
  tenant: { id?: string; name: string };
  brand?: { canonical_name?: string; official_domains?: string[] } | null;
  competitors: Array<{ canonical_name: string; official_domains?: string[] }>;
  prompt_count: number;
  audit_events?: Array<{ event_type?: string }>;
};

type ScoreSnapshot = {
  snapshot: {
    id?: string;
    final_score?: number;
    trigger_rate?: number;
    mention_rate?: number;
    recommendation_rate?: number;
    dispersion?: number;
    formula_version?: string;
  };
  contributions?: Array<{
    component_name?: string;
    component_score?: number;
    weight?: number;
    weighted_contribution?: number;
  }>;
};

type CitationGraph = {
  nodes: Array<{
    node: {
      id?: string;
      source_domain?: string;
      source_type?: string;
      citation_count?: number;
    };
  }>;
  source_gaps: Array<{
    source_type?: string;
    gap_type?: string;
    recommendation?: string;
  }>;
  competitor_benchmarks: Array<{
    competitor_name: string;
    metric_scope?: string;
    payload?: {
      mention_count?: number;
      mention_rate?: number;
      recommendation_count?: number;
      citation_overlap_count?: number;
    };
  }>;
};

type ReportExport = {
  report_export: {
    id: string;
    report_version: string;
    report_type?: string;
    sample_size?: number;
    exported_at?: string;
    markdown_url?: string | null;
    pdf_url?: string | null;
    csv_url?: string | null;
  };
  score_snapshots?: Array<{ final_score?: number }>;
  answer_runs?: Array<{ id?: string }>;
};

type ActionPlan = {
  action_recommendations: Array<{
    id?: string;
    title: string;
    description?: string;
    priority?: string;
    status?: string;
    source_gap_type?: string | null;
    next_check_date?: string;
  }>;
  retest_schedule?: {
    scheduled_dates?: string[];
    sample_size?: number;
  };
};

type DeliveryProgress = {
  status?: string;
  delivery_progress_ready?: boolean;
  ready_for_customer_report_handoff?: boolean;
  ready_for_trial_customer_handoff?: boolean;
  generated_at?: string;
  summary?: {
    engineering_progress_percent?: number;
    customer_report_handoff_readiness_percent?: number;
    structural_auditability_percent?: number;
    trial_customer_handoff_readiness_percent?: number;
    ready_progress_gate_count?: number;
    total_progress_gate_count?: number;
    blocked_progress_gate_count?: number;
    blocked_customer_gate_count?: number;
    next_action?: string;
    next_work_item_id?: string;
    next_work_item_title?: string;
    next_work_item_stage?: string;
    remaining_blocker_count?: number;
  };
};

type CustomerHandoffPackage = {
  status?: string;
  generated_at?: string;
  customer_handoff_package_manifest_ready?: boolean;
  customer_handoff_package_ready?: boolean;
  ready_for_report_export_handoff?: boolean;
  ready_for_trial_customer_handoff?: boolean;
  next_action?: string;
  summary?: {
    ready_source_artifact_count?: number;
    required_source_artifact_count?: number;
    blocked_source_artifact_count?: number;
    engineering_progress_percent?: number;
    customer_report_handoff_readiness_percent?: number;
    structural_auditability_percent?: number;
    trial_customer_handoff_readiness_percent?: number;
    missing_required_count?: number;
    next_action?: string;
  };
  handoff_index?: Array<{
    name?: string;
    stage?: string;
    artifact_type?: string;
    customer_visible?: boolean;
    status?: string;
  }>;
  customer_handoff_package_markdown?: {
    exists?: boolean;
    path?: string;
    customer_visible?: boolean;
  };
};

type EvidenceRun = {
  answer_run: {
    id: string;
    platform?: string;
    city?: string;
    status?: string;
    collected_at?: string;
  };
  citations?: Array<{ domain?: string; source_type?: string }>;
};

type RuntimePaths = {
  projects: string;
  scores: string;
  graphs: string;
  reports: string;
  actions: string;
  evidence: string;
  deliveryProgress: string;
  customerHandoffPackage: string;
};

type CustomerHomeData = {
  projects: PageResponse<RuntimeProject>;
  scores: PageResponse<ScoreSnapshot>;
  graphs: PageResponse<CitationGraph>;
  reports: PageResponse<ReportExport>;
  actions: PageResponse<ActionPlan>;
  evidence: PageResponse<EvidenceRun>;
  deliveryProgress: DeliveryProgress | null;
  customerHandoffPackage: CustomerHandoffPackage | null;
};

const endpoints = {
  projects: "/v1/projects/runtime",
  scores: "/v1/visibility-scores/runtime",
  graphs: "/v1/citation-graphs/runtime",
  reports: "/v1/reports/runtime",
  actions: "/v1/action-plans/runtime",
  evidence: "/v1/evidence-runs/runtime",
  deliveryProgress: "/v1/delivery-progress/au",
  customerHandoffPackage: "/v1/customer-handoff-package/au"
};

const emptyPage = <T,>(): PageResponse<T> => ({ total_count: 0, records: [] });

function cleanFilter(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed || undefined;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

function runtimePath(path: string, params: Record<string, string | number | undefined>): string {
  return `${path}${buildQuery(params)}`;
}

async function fetchRuntimeEndpoint<T>(
  baseUrl: string,
  path: string,
  fallback: T
): Promise<{ payload: T; error: string | null }> {
  try {
    const response = await fetch(`${baseUrl}${path}`, { cache: "no-store" });
    if (!response.ok) {
      return { payload: fallback, error: "数据暂不可用" };
    }
    return { payload: (await response.json()) as T, error: null };
  } catch {
    return { payload: fallback, error: "后端未连接" };
  }
}

async function fetchCustomerHomeData(projectId?: string): Promise<{
  data: CustomerHomeData;
  errors: string[];
  displayUrl: string;
  paths: RuntimePaths;
}> {
  const baseUrl = process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  const displayUrl = process.env.NEXT_PUBLIC_API_BASE_URL || baseUrl;
  const paths: RuntimePaths = {
    projects: runtimePath(endpoints.projects, { market_code: "AU", limit: 20 }),
    scores: runtimePath(endpoints.scores, { project_id: projectId, limit: 1 }),
    graphs: runtimePath(endpoints.graphs, { project_id: projectId, limit: 1 }),
    reports: runtimePath(endpoints.reports, { project_id: projectId, limit: 5 }),
    actions: runtimePath(endpoints.actions, { project_id: projectId, limit: 1 }),
    evidence: runtimePath(endpoints.evidence, { project_id: projectId, limit: 5 }),
    deliveryProgress: endpoints.deliveryProgress,
    customerHandoffPackage: endpoints.customerHandoffPackage
  };

  const projects = await fetchRuntimeEndpoint<PageResponse<RuntimeProject>>(baseUrl, paths.projects, emptyPage<RuntimeProject>());
  const selectedProjectId = projectId || projects.payload.records[0]?.project.id;
  const selectedPaths = {
    ...paths,
    scores: runtimePath(endpoints.scores, { project_id: selectedProjectId, limit: 1 }),
    graphs: runtimePath(endpoints.graphs, { project_id: selectedProjectId, limit: 1 }),
    reports: runtimePath(endpoints.reports, { project_id: selectedProjectId, limit: 5 }),
    actions: runtimePath(endpoints.actions, { project_id: selectedProjectId, limit: 1 }),
    evidence: runtimePath(endpoints.evidence, { project_id: selectedProjectId, limit: 5 })
  };

  const [scores, graphs, reports, actions, evidence, deliveryProgress, customerHandoffPackage] = await Promise.all([
    fetchRuntimeEndpoint<PageResponse<ScoreSnapshot>>(baseUrl, selectedPaths.scores, emptyPage<ScoreSnapshot>()),
    fetchRuntimeEndpoint<PageResponse<CitationGraph>>(baseUrl, selectedPaths.graphs, emptyPage<CitationGraph>()),
    fetchRuntimeEndpoint<PageResponse<ReportExport>>(baseUrl, selectedPaths.reports, emptyPage<ReportExport>()),
    fetchRuntimeEndpoint<PageResponse<ActionPlan>>(baseUrl, selectedPaths.actions, emptyPage<ActionPlan>()),
    fetchRuntimeEndpoint<PageResponse<EvidenceRun>>(baseUrl, selectedPaths.evidence, emptyPage<EvidenceRun>()),
    fetchRuntimeEndpoint<DeliveryProgress | null>(baseUrl, selectedPaths.deliveryProgress, null),
    fetchRuntimeEndpoint<CustomerHandoffPackage | null>(baseUrl, selectedPaths.customerHandoffPackage, null)
  ]);

  const errors = [
    projects.error,
    scores.error,
    graphs.error,
    reports.error,
    actions.error,
    evidence.error,
    deliveryProgress.error,
    customerHandoffPackage.error
  ].filter((error): error is string => Boolean(error));

  return {
    data: {
      projects: projects.payload,
      scores: scores.payload,
      graphs: graphs.payload,
      reports: reports.payload,
      actions: actions.payload,
      evidence: evidence.payload,
      deliveryProgress: deliveryProgress.payload,
      customerHandoffPackage: customerHandoffPackage.payload
    },
    errors: Array.from(new Set(errors)),
    displayUrl,
    paths: selectedPaths
  };
}

function pct(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "待采集";
  return `${Math.round(value * 1000) / 10}%`;
}

function score(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "待采集";
  return String(Math.round(value * 10) / 10);
}

function percentValue(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "待采集";
  return `${Math.round(value * 10) / 10}%`;
}

function dateText(value: string | undefined): string {
  if (!value) return "暂无";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function statusText(value: boolean | undefined, readyLabel = "已就绪", blockedLabel = "待完成"): string {
  if (value === true) return readyLabel;
  if (value === false) return blockedLabel;
  return "待采集";
}

function tone(value: boolean | undefined): string {
  if (value === true) return "ready";
  if (value === false) return "blocked";
  return "pending";
}

function firstSourceDomains(graph: CitationGraph | undefined): string {
  const domains = Array.from(
    new Set(graph?.nodes.map((item) => item.node.source_domain).filter((domain): domain is string => Boolean(domain)))
  ).slice(0, 4);
  return domains.length ? domains.join("、") : "待采集";
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="customerFact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusPill({ label, state }: { label: string; state?: boolean }) {
  return <span className={`customerStatusPill ${tone(state)}`}>{label}</span>;
}

export default async function CustomerHome({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = (await searchParams) || {};
  const requestedProjectId = cleanFilter(resolvedSearchParams.project_id);
  const { data, errors, displayUrl } = await fetchCustomerHomeData(requestedProjectId);
  const selectedProject =
    (requestedProjectId && data.projects.records.find((record) => record.project.id === requestedProjectId)) ||
    data.projects.records[0];
  const selectedProjectId = selectedProject?.project.id;
  const latestScore = data.scores.records[0];
  const latestGraph = data.graphs.records[0];
  const latestReport = data.reports.records[0];
  const latestActionPlan = data.actions.records[0];
  const progress = data.deliveryProgress;
  const progressSummary = progress?.summary;
  const handoff = data.customerHandoffPackage;
  const handoffSummary = handoff?.summary;
  const traceabilityHref = selectedProjectId
    ? `/traceability?project_id=${encodeURIComponent(selectedProjectId)}`
    : "/traceability";
  const opsHref = selectedProjectId ? `/ops?project_id=${encodeURIComponent(selectedProjectId)}` : "/ops";
  const reportLinks = [
    latestReport?.report_export.markdown_url ? { label: "Markdown", href: latestReport.report_export.markdown_url } : null,
    latestReport?.report_export.pdf_url ? { label: "PDF", href: latestReport.report_export.pdf_url } : null,
    latestReport?.report_export.csv_url ? { label: "CSV", href: latestReport.report_export.csv_url } : null
  ].filter((link): link is { label: string; href: string } => Boolean(link));
  const visibleArtifacts = (handoff?.handoff_index || []).filter((item) => item.customer_visible).slice(0, 4);
  const topActions = latestActionPlan?.action_recommendations.slice(0, 3) || [];
  const competitors = latestGraph?.competitor_benchmarks.slice(0, 3) || [];

  return (
    <main className="shell customerShell">
      <section className="topbar customerTopbar">
        <div>
          <p className="eyebrow">GEO SaaS AU</p>
          <h1>GEO 澳大利亚客户工作台</h1>
          <p className="customerLead">面向客户交付查看项目进度、AI 可见度、报告状态和下一步行动。</p>
        </div>
        <div className="apiBox customerUtilityBox">
          <span>当前数据源</span>
          <strong>{displayUrl ? "运行时 API 已配置" : "待配置"}</strong>
          <a className="inlineLink" href={opsHref}>
            内部控制台
          </a>
        </div>
      </section>

      {errors.length ? (
        <section className="notice customerNotice">
          <strong>数据暂不可用</strong>
          <span>{errors.includes("后端未连接") ? "后端未连接，请先启动 API 服务。" : "部分运行时数据暂不可用。"}</span>
          <span>首页仅展示真实数据；未读取到的模块会显示待采集或待生成。</span>
        </section>
      ) : null}

      <section className="customerProjectBar" aria-label="项目选择">
        <div>
          <h2>项目概览</h2>
          <span>{selectedProject ? `${selectedProject.tenant.name} / ${selectedProject.project.name}` : "暂无澳大利亚项目"}</span>
        </div>
        <form className="customerProjectForm">
          <label>
            <span>项目</span>
            <select name="project_id" defaultValue={selectedProjectId || ""}>
              {data.projects.records.length ? (
                data.projects.records.map((record) => (
                  <option key={record.project.id} value={record.project.id}>
                    {record.tenant.name} / {record.project.name}
                  </option>
                ))
              ) : (
                <option value="">暂无 AU 项目</option>
              )}
            </select>
          </label>
          <button className="actionButton" type="submit">
            切换项目
          </button>
        </form>
      </section>

      {!selectedProject ? (
        <section className="customerEmptyState">
          <h2>暂无澳大利亚项目</h2>
          <p>当前没有读取到 AU runtime project。请先在内部控制台创建或导入项目，然后返回客户工作台查看交付状态。</p>
          <a className="actionButton" href="/ops">
            进入内部控制台
          </a>
        </section>
      ) : (
        <>
          <section className="customerSummaryGrid" aria-label="核心指标">
            <Fact label="目标品牌" value={selectedProject.project.target_brand || selectedProject.brand?.canonical_name || "待配置"} />
            <Fact label="Prompt 数量" value={selectedProject.prompt_count || "待导入"} />
            <Fact label="工程进度" value={percentValue(progressSummary?.engineering_progress_percent)} />
            <Fact label="试点交付" value={percentValue(progressSummary?.trial_customer_handoff_readiness_percent)} />
          </section>

          <section className="customerDashboard" aria-label="客户工作台">
            <article className="panel customerPanel">
              <div className="panelHeader">
                <div>
                  <p className="eyebrow">Visibility</p>
                  <h2>AI 可见度</h2>
                </div>
                <StatusPill label={latestScore ? "已采集" : "待采集"} state={Boolean(latestScore)} />
              </div>
              <div className="customerScoreValue">{score(latestScore?.snapshot.final_score)}</div>
              <dl className="customerFactsGrid">
                <Fact label="触发率" value={pct(latestScore?.snapshot.trigger_rate)} />
                <Fact label="提及率" value={pct(latestScore?.snapshot.mention_rate)} />
                <Fact label="推荐率" value={pct(latestScore?.snapshot.recommendation_rate)} />
                <Fact label="评分公式" value={latestScore?.snapshot.formula_version || "待采集"} />
              </dl>
            </article>

            <article className="panel customerPanel">
              <div className="panelHeader">
                <div>
                  <p className="eyebrow">Delivery</p>
                  <h2>试点交付状态</h2>
                </div>
                <StatusPill label={statusText(progress?.ready_for_trial_customer_handoff, "可试点", "未就绪")} state={progress?.ready_for_trial_customer_handoff} />
              </div>
              <dl className="customerFactsGrid">
                <Fact label="工程进度" value={percentValue(progressSummary?.engineering_progress_percent)} />
                <Fact label="客户报告" value={percentValue(progressSummary?.customer_report_handoff_readiness_percent)} />
                <Fact label="可审计度" value={percentValue(progressSummary?.structural_auditability_percent)} />
                <Fact label="阻塞项" value={progressSummary?.remaining_blocker_count ?? "待采集"} />
              </dl>
              <p className="customerPanelNote">下一步：{progressSummary?.next_work_item_title || progressSummary?.next_action || "待生成"}</p>
            </article>

            <article className="panel customerPanel">
              <div className="panelHeader">
                <div>
                  <p className="eyebrow">Report</p>
                  <h2>报告状态</h2>
                </div>
                <StatusPill label={latestReport ? "已生成" : "待生成"} state={Boolean(latestReport)} />
              </div>
              <dl className="customerFactsGrid">
                <Fact label="报告版本" value={latestReport?.report_export.report_version || "待生成"} />
                <Fact label="样本量" value={latestReport?.report_export.sample_size ?? "待生成"} />
                <Fact label="导出时间" value={dateText(latestReport?.report_export.exported_at)} />
                <Fact label="客户包" value={statusText(handoff?.customer_handoff_package_ready, "已准备", "待完善")} />
              </dl>
              <div className="customerLinkRow">
                {reportLinks.length ? reportLinks.map((link) => <a key={link.label} href={link.href}>{link.label}</a>) : <span>报告文件待生成</span>}
              </div>
            </article>

            <article className="panel customerPanel">
              <div className="panelHeader">
                <div>
                  <p className="eyebrow">Sources</p>
                  <h2>竞品与信源</h2>
                </div>
                <StatusPill label={latestGraph ? "已采集" : "待采集"} state={Boolean(latestGraph)} />
              </div>
              <dl className="customerFactsGrid">
                <Fact label="信源域名" value={firstSourceDomains(latestGraph)} />
                <Fact label="信源缺口" value={latestGraph?.source_gaps.length ?? "待采集"} />
                <Fact label="竞品样本" value={competitors.length || "待采集"} />
                <Fact label="证据样本" value={data.evidence.total_count || "待采集"} />
              </dl>
              <ul className="customerPlainList">
                {competitors.length ? (
                  competitors.map((item) => <li key={item.competitor_name}>{item.competitor_name}</li>)
                ) : (
                  <li>竞品对标待采集</li>
                )}
              </ul>
            </article>

            <article className="panel customerPanel">
              <div className="panelHeader">
                <div>
                  <p className="eyebrow">Package</p>
                  <h2>客户交付包</h2>
                </div>
                <StatusPill label={statusText(handoff?.ready_for_report_export_handoff, "可交付", "待完善")} state={handoff?.ready_for_report_export_handoff} />
              </div>
              <dl className="customerFactsGrid">
                <Fact label="来源产物" value={`${handoffSummary?.ready_source_artifact_count ?? 0}/${handoffSummary?.required_source_artifact_count ?? 0}`} />
                <Fact label="缺失项" value={handoffSummary?.missing_required_count ?? "待采集"} />
                <Fact label="试点 readiness" value={percentValue(handoffSummary?.trial_customer_handoff_readiness_percent)} />
                <Fact label="Markdown" value={handoff?.customer_handoff_package_markdown?.exists ? "已生成" : "待生成"} />
              </dl>
              <ul className="customerPlainList">
                {visibleArtifacts.length ? (
                  visibleArtifacts.map((item) => <li key={`${item.name}-${item.stage}`}>{item.name || item.artifact_type || "交付产物"}</li>)
                ) : (
                  <li>客户可见产物待整理</li>
                )}
              </ul>
            </article>

            <article className="panel customerPanel">
              <div className="panelHeader">
                <div>
                  <p className="eyebrow">Next</p>
                  <h2>下一步行动</h2>
                </div>
                <StatusPill label={topActions.length ? "已生成" : "待生成"} state={Boolean(topActions.length)} />
              </div>
              <ul className="customerActionList">
                {topActions.length ? (
                  topActions.map((action) => (
                    <li key={action.id || action.title}>
                      <strong>{action.title}</strong>
                      <span>{action.description || action.source_gap_type || action.status || "等待补充说明"}</span>
                    </li>
                  ))
                ) : (
                  <li>
                    <strong>{handoffSummary?.next_action || progressSummary?.next_action || "待生成行动计划"}</strong>
                    <span>完成下一轮采集或报告生成后，这里会展示客户可读的优化动作。</span>
                  </li>
                )}
              </ul>
            </article>
          </section>

          <section className="customerFooterActions" aria-label="只读入口">
            <a className="actionButton" href={traceabilityHref}>
              查看溯源图谱
            </a>
            <a className="resetLink" href={opsHref}>
              内部控制台
            </a>
          </section>
        </>
      )}
    </main>
  );
}
