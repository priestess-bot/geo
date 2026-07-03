import { latestScore, loadPortal, loadPortalRuntimeData, pct } from "./runtime";

const modules = [
  ["visibility", "AI 可见度", "查看总分、触发率、提及率和建议率。"],
  ["sources", "信源与竞品", "查看被 AI 引用的域名、信源缺口和竞品对比。"],
  ["evidence", "证据样本", "查看采集样本、引用和可复盘证据链。"],
  ["reports", "报告交付", "查看最近报告、导出状态和客户可见材料。"],
  ["actions", "下一步行动", "查看内容、信源和复测建议。"],
  ["handoff", "交付包", "查看试点交付包准备状态。"],
  ["traceability", "可解释性", "查看审计事件、方法版本和证据映射。"]
];

export default async function CustomerHome({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) || {};
  const token = Array.isArray(params.portal_token) ? params.portal_token[0] : params.portal_token;
  const invitationId = Array.isArray(params.invitation_id) ? params.invitation_id[0] : params.invitation_id;
  const inviteToken = Array.isArray(params.invite_token) ? params.invite_token[0] : params.invite_token;
  const acceptedBy = Array.isArray(params.accepted_by) ? params.accepted_by[0] : params.accepted_by;
  const data = await loadPortal({ portalToken: token, invitationId, inviteToken, acceptedBy });
  const bundle = data?.bundle;
  const project = bundle?.project?.project;
  const tenant = bundle?.project?.tenant;
  const launch = bundle?.launch_config?.launch_config;
  const projectId = project?.id || bundle?.access?.project_id || "";
  const actorId = bundle?.access?.member_user_id;
  const runtime = projectId ? await loadPortalRuntimeData(projectId, actorId) : null;
  const score = runtime ? latestScore(runtime.scores) : undefined;
  const progressWidth = typeof score === "number" ? `${Math.max(3, Math.round(score * 100))}%` : "0%";
  const continuationToken = token || data?.portal_token || "";

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">GENO AU 客户门户</p>
          <h1>{project?.target_brand || "澳大利亚 GEO 项目工作台"}</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            {tenant?.name || "连接门户 token 后查看单个项目的可见度、信源、证据、报告与行动计划。"}
          </p>
        </div>
        <form className="tokenForm" action="/" method="get">
          <label>
            <span>门户 token</span>
            <input name="portal_token" defaultValue={continuationToken || ""} placeholder="geno-portal-..." />
          </label>
          <button type="submit">打开项目</button>
        </form>
      </section>

      {!bundle ? (
        <section className="emptyState">
          <h2>等待连接客户项目</h2>
          <p>请输入后台生成的门户 token，或使用邀请链接首次进入。此页面只展示绑定项目，不提供项目列表和内部排障信息。</p>
        </section>
      ) : (
        <>
          {data?.portal_token ? (
            <section className="panel" style={{ marginTop: 18 }}>
              <h2>门户 token 已生成</h2>
              <p className="muted" style={{ marginTop: 8 }}>此 token 只显示一次，后续可用它直接打开客户门户。</p>
              <p style={{ marginTop: 10 }}><code>{data.portal_token}</code></p>
            </section>
          ) : null}
          <section className="heroGrid">
            <div className="panel">
              <div className="scoreBand">
                <div>
                  <p className="eyebrow">当前 AI 可见度</p>
                  <div className="scoreValue">{pct(score)}</div>
                </div>
                <div>
                  <h2>{project?.name || "项目概览"}</h2>
                  <p className="muted" style={{ marginTop: 8 }}>
                    主域名 {launch?.primary_domain || "待配置"}，项目状态 {project?.status || "待确认"}。
                  </p>
                  <div className="progressTrack" style={{ marginTop: 14 }}>
                    <div className="progressFill" style={{ width: progressWidth }} />
                  </div>
                </div>
              </div>
              <div className="metricGrid">
                <div className="metric">
                  <span className="muted">提示问题</span>
                  <strong>{bundle.project?.prompt_count ?? 0}</strong>
                </div>
                <div className="metric">
                  <span className="muted">竞品数量</span>
                  <strong>{bundle.project?.competitors?.length ?? 0}</strong>
                </div>
                <div className="metric">
                  <span className="muted">审计事件</span>
                  <strong>{bundle.audit_events?.total_count ?? 0}</strong>
                </div>
                <div className="metric">
                  <span className="muted">报告</span>
                  <strong>{runtime?.reports.total_count ?? 0}</strong>
                </div>
              </div>
            </div>
            <div className="panel">
              <h2>项目资料</h2>
              <div className="list">
                <div className="listItem">
                  <span className="muted">客户邮箱</span>
                  <strong>{launch?.customer_email || "待配置"}</strong>
                </div>
                <div className="listItem">
                  <span className="muted">评分方法</span>
                  <strong>{bundle.score_weight_config?.score_weight_config?.formula_version || "au_visibility_v1"}</strong>
                </div>
                <div className="listItem">
                  <span className="muted">项目 ID</span>
                  <strong>{projectId}</strong>
                </div>
              </div>
            </div>
          </section>

          <section className="panel" style={{ marginTop: 16 }}>
            <h2>工作台模块</h2>
            <div className="moduleGrid">
              {modules.map(([id, title, description]) => (
                <a className="moduleTile" href={`/portal/${id}?portal_token=${encodeURIComponent(continuationToken || "")}`} key={id}>
                  <span className="statusPill">{moduleCount(id, runtime)} 条</span>
                  <h3>{title}</h3>
                  <p className="muted">{description}</p>
                </a>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}

function moduleCount(id: string, runtime: Awaited<ReturnType<typeof loadPortalRuntimeData>> | null): number {
  if (!runtime) {
    return 0;
  }
  if (id === "visibility") return runtime.scores.total_count;
  if (id === "sources") return runtime.graphs.total_count;
  if (id === "evidence") return runtime.evidence.total_count;
  if (id === "reports" || id === "handoff") return runtime.reports.total_count;
  if (id === "actions") return runtime.actions.total_count;
  if (id === "traceability") return runtime.traceability ? 1 : 0;
  return 0;
}
