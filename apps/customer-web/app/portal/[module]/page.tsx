import { latestScore, loadPortalRuntimeData, loadSessionPortal, pct, type PortalBundle, type PortalRuntimeData } from "../../runtime";

const moduleMeta: Record<string, { title: string; intro: string }> = {
  visibility: { title: "AI 可见度", intro: "汇总项目当前在 AI 搜索和搜索增强结果中的出现、提及和推荐表现。" },
  sources: { title: "信源与竞品", intro: "梳理 AI 引用来源、品牌可控信源缺口和主要竞品对比。" },
  evidence: { title: "证据样本", intro: "查看支撑结论的采集样本、引用和证据链上下文。" },
  reports: { title: "报告交付", intro: "查看客户可见报告、导出状态和交付材料。" },
  actions: { title: "下一步行动", intro: "展示内容、信源、复测和运营动作建议。" },
  handoff: { title: "交付包", intro: "查看正式交付包准备状态和缺口。" },
  traceability: { title: "可解释性", intro: "查看方法版本、审计事件和证据映射摘要。" }
};

type PortalRecord = Record<string, unknown>;

function objectValue(value: unknown): PortalRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as PortalRecord : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function textValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function shortValue(value: unknown): string {
  const text = textValue(value);
  return text.length > 18 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
}

function statusLabel(status: unknown): string {
  const labels: Record<string, string> = {
    active: "运行中",
    approved: "已审批",
    archived: "已归档",
    awaiting_url_backfill: "等待 URL 回填",
    blocked: "阻塞",
    cancelled: "已取消",
    client_ready: "客户可见",
    configured: "已配置",
    draft: "草稿",
    failed: "失败",
    internal_review: "内部复核",
    open: "待处理",
    pending: "待处理",
    pending_human_review: "待人工审核",
    published: "已发布",
    queued: "已排队",
    ready: "就绪",
    revoked: "已撤回",
    running: "运行中",
    succeeded: "已完成"
  };
  const raw = textValue(status);
  return labels[raw.toLowerCase()] || raw || "未知";
}

function metricValue(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.abs(value) <= 1 ? `${Math.round(value * 100)}%` : value.toFixed(2);
  }
  return textValue(value) || "暂无";
}

function KeyValueGrid({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="kvGrid">
      {rows.map(([label, value], index) => (
        <div className="kvItem" key={`${index}-${label}`}>
          <span>{label}</span>
          <strong>{value || "暂无"}</strong>
        </div>
      ))}
    </div>
  );
}

function RecordList({
  emptyText,
  records,
  render,
  title
}: {
  emptyText: string;
  records: PortalRecord[];
  render: (record: PortalRecord, index: number) => { title: string; subtitle: string; meta?: string };
  title: string;
}) {
  return (
    <div className="detailPanel">
      <h2>{title}</h2>
      <div className="list">
        {records.length ? (
          records.slice(0, 8).map((record, index) => {
            const item = render(record, index);
            return (
              <div className="listItem" key={`${index}-${item.title}-${item.subtitle}`}>
                <strong>{item.title || "未命名"}</strong>
                <p className="muted">{item.subtitle || "无详情"}</p>
                {item.meta ? <p className="muted">{item.meta}</p> : null}
              </div>
            );
          })
        ) : (
          <p className="muted">{emptyText}</p>
        )}
      </div>
    </div>
  );
}

function panelFor(moduleId: string, bundle: PortalBundle, runtime: PortalRuntimeData | null) {
  const project = bundle.project?.project;
  const competitors = bundle.project?.competitors || [];
  if (moduleId === "visibility") {
    const score = runtime ? latestScore(runtime.scores) : undefined;
    const scoreRecord = objectValue(runtime?.scores.records?.[0]);
    const snapshot = objectValue(scoreRecord.snapshot || scoreRecord.visibility_score_snapshot || scoreRecord);
    const contributionCount = arrayValue(scoreRecord.score_contributions).length || Number(snapshot.contribution_count || 0);
    return (
      <div className="twoCol">
        <div className="detailPanel">
          <h2>AI 可见度</h2>
          <div className="scoreValue">{pct(score)}</div>
          <p className="muted" style={{ marginTop: 8 }}>共读取 {runtime?.scores.total_count ?? 0} 个评分快照。</p>
        </div>
        <div className="detailPanel">
          <h2>评分解释</h2>
          <KeyValueGrid rows={[
            ["公式版本", textValue(snapshot.formula_version) || textValue(snapshot.score_formula_version)],
            ["总分", metricValue(snapshot.final_score ?? snapshot.score)],
            ["平台", textValue(snapshot.platform) || textValue(snapshot.provider)],
            ["时间窗", [textValue(snapshot.window_start), textValue(snapshot.window_end)].filter(Boolean).join(" 至 ")],
            ["贡献项", String(contributionCount || 0)]
          ]} />
        </div>
      </div>
    );
  }
  if (moduleId === "sources") {
    const graphRecord = objectValue(runtime?.graphs.records?.[0]);
    const graph = objectValue(graphRecord.citation_graph || graphRecord.graph || graphRecord);
    const sourceCount = arrayValue(graph.sources || graph.nodes).length || Number(graph.source_count || 0);
    const edgeCount = arrayValue(graph.edges).length || Number(graph.edge_count || 0);
    const sourceGaps = arrayValue(graph.source_gaps);
    return (
      <div className="twoCol">
        <div className="detailPanel">
          <h2>竞品范围</h2>
          <div className="list">
            {competitors.map((competitor, index) => (
              <div className="listItem" key={`${competitor.canonical_name}-${index}`}>
                <strong>{competitor.canonical_name || "未命名竞品"}</strong>
                <p className="muted">{(competitor.official_domains || []).join(", ") || "官方域名待补充"}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="detailPanel">
          <h2>信源图谱</h2>
          <KeyValueGrid rows={[
            ["信源数量", String(sourceCount || 0)],
            ["引用关系", String(edgeCount || 0)],
            ["缺口数量", String(sourceGaps.length || Number(graph.source_gap_count || 0))],
            ["最近更新", textValue(graph.updated_at || graph.created_at)]
          ]} />
          {sourceGaps.length ? (
            <div className="list">
              {sourceGaps.slice(0, 5).map((gap, index) => {
                const item = objectValue(gap);
                return (
                  <div className="listItem" key={`${index}-${textValue(item.domain)}`}>
                    <strong>{textValue(item.domain) || textValue(item.source) || "未命名信源缺口"}</strong>
                    <p className="muted">{textValue(item.reason) || textValue(item.recommendation) || "等待补充说明"}</p>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      </div>
    );
  }
  if (moduleId === "evidence") {
    const evidenceRecords = (runtime?.evidence.records || []).map(objectValue);
    const collectionRecords = (runtime?.collectionRuns.records || []).map(objectValue);
    return (
      <div className="twoCol">
        <RecordList
          title={`证据样本 · ${runtime?.evidence.total_count ?? 0} 条`}
          emptyText="当前没有客户可见证据样本。"
          records={evidenceRecords}
          render={(record) => {
            const answer = objectValue(record.answer_run);
            const raw = objectValue(record.raw_answer);
            return {
              title: textValue(answer.prompt_text) || textValue(raw.prompt_text) || shortValue(answer.id || raw.id) || "回答证据",
              subtitle: `${statusLabel(answer.status || raw.status)} · ${textValue(answer.platform || raw.platform) || "未知平台"}`,
              meta: textValue(raw.created_at || answer.created_at)
            };
          }}
        />
        <RecordList
          title="采集批次"
          emptyText="暂无采集批次。"
          records={collectionRecords}
          render={(record) => {
            const run = objectValue(record.collection_run || record);
            return {
              title: textValue(run.run_name) || shortValue(run.id) || "采集批次",
              subtitle: `${statusLabel(run.status)} · ${textValue(run.platform) || textValue(run.collection_mode) || "多平台"}`,
              meta: textValue(run.started_at || run.created_at)
            };
          }}
        />
      </div>
    );
  }
  if (moduleId === "traceability") {
    const traceability = objectValue(runtime?.traceability);
    const auditRecords = (bundle.audit_events?.records || []).map(objectValue);
    return (
      <div className="twoCol">
        <div className="detailPanel">
          <h2>Traceability Bundle</h2>
          <KeyValueGrid rows={[
            ["报告数量", String(runtime?.reports.total_count ?? 0)],
            ["评分快照", String(runtime?.scores.total_count ?? 0)],
            ["证据运行", String(runtime?.evidence.total_count ?? 0)],
            ["行动计划", String(runtime?.actions.total_count ?? 0)],
            ["方法版本", textValue(traceability.method_version || traceability.formula_version)]
          ]} />
        </div>
        <RecordList
          title="审计摘要"
          emptyText="暂无客户可见审计事件。"
          records={auditRecords}
          render={(record) => ({
            title: textValue(record.event_type) || "audit_event",
            subtitle: textValue(record.actor_id) || textValue(record.actor_type) || "system",
            meta: textValue(record.created_at)
          })}
        />
      </div>
    );
  }
  if (moduleId === "reports" || moduleId === "handoff") {
    const reports = runtime?.reports.records || [];
    const jobs = (runtime?.reportJobs.records || []).map(objectValue);
    return (
      <div className="twoCol">
        <div className="detailPanel">
          <h2>报告交付</h2>
          <p className="muted" style={{ marginTop: 8 }}>当前返回 {runtime?.reports.total_count ?? 0} 份报告。</p>
          <div className="list">
            {reports.slice(0, 5).map((item, index) => {
              const report = (item as { report_export?: { id?: string; report_version?: string; report_type?: string } }).report_export || {};
              const reportId = report.id || "";
              return (
                <div className="listItem" key={`${reportId}-${index}`}>
                  <strong>{report.report_version || report.report_type || reportId || "未命名报告"}</strong>
                  <p className="muted">{reportId || "报告 id 待确认"}</p>
                  {reportId ? (
                    <div className="actionRow">
                      <a className="button secondary" href={artifactHref(reportId, "markdown")}>Markdown</a>
                      <a className="button secondary" href={artifactHref(reportId, "csv")}>CSV</a>
                      <a className="button secondary" href={artifactHref(reportId, "pdf")}>PDF</a>
                    </div>
                  ) : null}
                </div>
              );
            })}
            {reports.length === 0 ? <p className="muted">报告尚未生成。</p> : null}
          </div>
        </div>
        <RecordList
          title="报告任务"
          emptyText="暂无报告导出任务。"
          records={jobs}
          render={(record) => {
            const job = objectValue(record.report_export_job || record);
            return {
              title: `${textValue(job.artifact_type) || "artifact"} · ${shortValue(job.id) || "job"}`,
              subtitle: statusLabel(job.status),
              meta: textValue(job.created_at || job.updated_at)
            };
          }}
        />
      </div>
    );
  }
  if (moduleId === "actions") {
    const plans = (runtime?.actions.records || []).map(objectValue);
    const actionRows = plans.flatMap((record) => arrayValue(record.action_recommendations).map(objectValue));
    const retestRows = plans.map((record) => objectValue(record.retest_schedule || {})).filter((record) => Object.keys(record).length);
    const comparisonRows = plans.flatMap((record) => arrayValue(record.retest_comparisons).map(objectValue));
    return (
      <div className="twoCol">
        <RecordList
          title={`行动建议 · ${actionRows.length} 条`}
          emptyText="暂无客户可见行动建议。"
          records={actionRows}
          render={(record) => ({
            title: textValue(record.title) || shortValue(record.id) || "行动建议",
            subtitle: `${statusLabel(record.status)} · ${textValue(record.action_type) || "recommendation"}`,
            meta: textValue(record.visibility_note) || textValue(record.reason)
          })}
        />
        <div className="detailPanel">
          <h2>复测结果</h2>
          <KeyValueGrid rows={[
            ["复测计划", String(retestRows.length)],
            ["对比记录", String(comparisonRows.length)],
            ["最近 before", metricValue(comparisonRows[0]?.baseline_score)],
            ["最近 after", metricValue(comparisonRows[0]?.retest_score)],
            ["最近 delta", metricValue(comparisonRows[0]?.score_delta)]
          ]} />
        </div>
      </div>
    );
  }
  return (
    <div className="twoCol">
      <div className="detailPanel">
        <h2>项目摘要</h2>
        <div className="list">
          <div className="listItem">
            <span className="muted">品牌</span>
            <strong>{project?.target_brand || "待配置"}</strong>
          </div>
          <div className="listItem">
            <span className="muted">项目状态</span>
            <strong>{project?.status || "待确认"}</strong>
          </div>
          <div className="listItem">
            <span className="muted">提示问题</span>
            <strong>{bundle.project?.prompt_count ?? 0}</strong>
          </div>
        </div>
      </div>
      <div className="detailPanel">
        <h2>方法配置</h2>
        <KeyValueGrid rows={[
          ["公式版本", textValue(bundle.score_weight_config?.score_weight_config?.formula_version)],
          ["启动状态", statusLabel(bundle.launch_config?.launch_config?.status)],
          ["客户邮箱", textValue(bundle.launch_config?.launch_config?.customer_email)],
          ["主域名", textValue(bundle.launch_config?.launch_config?.primary_domain)]
        ]} />
      </div>
    </div>
  );
}

function artifactHref(reportId: string, type: string): string {
  const params = new URLSearchParams({ report_export_id: reportId, type });
  return `/api/report-artifact?${params.toString()}`;
}

export default async function PortalModule({
  params,
  searchParams
}: {
  params: Promise<{ module: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { module } = await params;
  const query = (await searchParams) || {};
  const projectQuery = Array.isArray(query.project_id) ? query.project_id[0] : query.project_id;
  const data = await loadSessionPortal(projectQuery);
  const meta = moduleMeta[module] || { title: "项目详情", intro: "查看项目详情。" };
  const projectId = data?.bundle?.project?.project?.id || data?.bundle?.access?.project_id || "";
  const actorId = data?.bundle?.access?.member_user_id;
  const runtime = projectId ? await loadPortalRuntimeData(projectId, actorId) : null;

  return (
    <main className="shell">
      <div className="detailHeader">
        <div>
          <p className="eyebrow">客户门户详情</p>
          <h1>{meta.title}</h1>
          <p className="muted" style={{ marginTop: 8 }}>{meta.intro}</p>
        </div>
        <a className="button secondary" href={`/?project_id=${encodeURIComponent(projectId)}`}>返回仪表盘</a>
      </div>
      {!data?.bundle ? (
        <section className="emptyState">
          <h2>无法读取项目</h2>
          <p>请先使用有效邀请登录，并确认当前账号已获项目访问权限。</p>
        </section>
      ) : (
        panelFor(module, data.bundle, runtime)
      )}
    </main>
  );
}
