import { latestScore, loadPortal, loadPortalRuntimeData, pct, type PortalBundle, type PortalRuntimeData } from "../../runtime";

const moduleMeta: Record<string, { title: string; intro: string }> = {
  visibility: { title: "AI 可见度", intro: "汇总项目当前在 AI 搜索和搜索增强结果中的出现、提及和推荐表现。" },
  sources: { title: "信源与竞品", intro: "梳理 AI 引用来源、品牌可控信源缺口和主要竞品对比。" },
  evidence: { title: "证据样本", intro: "查看支撑结论的采集样本、引用和证据链上下文。" },
  reports: { title: "报告交付", intro: "查看客户可见报告、导出状态和交付材料。" },
  actions: { title: "下一步行动", intro: "展示内容、信源、复测和运营动作建议。" },
  handoff: { title: "交付包", intro: "查看试点阶段交付包准备状态和缺口。" },
  traceability: { title: "可解释性", intro: "查看方法版本、审计事件和证据映射摘要。" }
};

function panelFor(moduleId: string, bundle: PortalBundle, runtime: PortalRuntimeData | null, portalToken?: string) {
  const project = bundle.project?.project;
  const competitors = bundle.project?.competitors || [];
  if (moduleId === "visibility") {
    const score = runtime ? latestScore(runtime.scores) : undefined;
    return (
      <div className="twoCol">
        <div className="detailPanel">
          <h2>AI 可见度</h2>
          <div className="scoreValue">{pct(score)}</div>
          <p className="muted" style={{ marginTop: 8 }}>共读取 {runtime?.scores.total_count ?? 0} 个评分快照。</p>
        </div>
        <div className="detailPanel">
          <h2>评分解释</h2>
          <pre>{JSON.stringify(runtime?.scores.records?.[0] || {}, null, 2)}</pre>
        </div>
      </div>
    );
  }
  if (moduleId === "sources") {
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
          <pre>{JSON.stringify(runtime?.graphs.records?.[0] || {}, null, 2)}</pre>
        </div>
      </div>
    );
  }
  if (moduleId === "evidence") {
    return (
      <div className="twoCol">
        <div className="detailPanel">
          <h2>证据样本</h2>
          <p className="muted" style={{ marginTop: 8 }}>当前返回 {runtime?.evidence.total_count ?? 0} 条证据。</p>
          <pre>{JSON.stringify(runtime?.evidence.records?.slice(0, 5) || [], null, 2)}</pre>
        </div>
        <div className="detailPanel">
          <h2>采集批次</h2>
          <pre>{JSON.stringify(runtime?.collectionRuns.records?.slice(0, 5) || [], null, 2)}</pre>
        </div>
      </div>
    );
  }
  if (moduleId === "traceability") {
    return (
      <div className="twoCol">
        <div className="detailPanel">
          <h2>Traceability Bundle</h2>
          <pre>{JSON.stringify(runtime?.traceability || {}, null, 2)}</pre>
        </div>
        <div className="detailPanel">
          <h2>审计摘要</h2>
          <pre>{JSON.stringify(bundle.audit_events?.records?.slice(0, 5) || [], null, 2)}</pre>
        </div>
      </div>
    );
  }
  if (moduleId === "reports" || moduleId === "handoff") {
    const reports = runtime?.reports.records || [];
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
                      <a className="button secondary" href={artifactHref(reportId, "markdown", portalToken)}>Markdown</a>
                      <a className="button secondary" href={artifactHref(reportId, "csv", portalToken)}>CSV</a>
                      <a className="button secondary" href={artifactHref(reportId, "pdf", portalToken)}>PDF</a>
                    </div>
                  ) : null}
                </div>
              );
            })}
            {reports.length === 0 ? <p className="muted">报告尚未生成。</p> : null}
          </div>
        </div>
        <div className="detailPanel">
          <h2>报告任务</h2>
          <pre>{JSON.stringify(runtime?.reportJobs.records?.slice(0, 5) || [], null, 2)}</pre>
        </div>
      </div>
    );
  }
  if (moduleId === "actions") {
    return (
      <div className="detailPanel">
        <h2>下一步行动</h2>
        <p className="muted" style={{ marginTop: 8 }}>当前返回 {runtime?.actions.total_count ?? 0} 个行动计划。</p>
        <pre>{JSON.stringify(runtime?.actions.records?.slice(0, 5) || [], null, 2)}</pre>
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
        <pre>{JSON.stringify(bundle.score_weight_config?.score_weight_config || {}, null, 2)}</pre>
      </div>
    </div>
  );
}

function artifactHref(reportId: string, type: string, portalToken?: string): string {
  const params = new URLSearchParams({ report_export_id: reportId, type });
  if (portalToken) {
    params.set("portal_token", portalToken);
  }
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
  const token = Array.isArray(query.portal_token) ? query.portal_token[0] : query.portal_token;
  const data = await loadPortal({ portalToken: token });
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
        <a className="button secondary" href={`/?portal_token=${encodeURIComponent(token || "")}`}>返回仪表盘</a>
      </div>
      {!data?.bundle ? (
        <section className="emptyState">
          <h2>无法读取项目</h2>
          <p>请确认门户 token 是否有效，或由后台重新生成客户门户 token。</p>
        </section>
      ) : (
        panelFor(module, data.bundle, runtime, token)
      )}
    </main>
  );
}
