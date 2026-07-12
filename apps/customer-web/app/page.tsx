import { InvitationLoginForm } from "./_auth/InvitationLoginForm";
import { SessionDeliveryConfirm } from "./_auth/SessionDeliveryConfirm";
import {
  adminWebBaseUrl,
  hasRuntimeSession,
  latestScore,
  loadPortalRuntimeData,
  loadSessionPortal,
  pct
} from "./runtime";

// The invite_token value stays in InvitationLoginForm memory and is never read from URL state.

const modules = [
  ["visibility", "AI 可见度", "查看总分、触发率、提及率和建议率。"],
  ["sources", "信源与竞品", "查看被 AI 引用的域名、信源缺口和竞品对比。"],
  ["evidence", "证据样本", "查看采集样本、引用和可复盘证据链。"],
  ["reports", "报告交付", "查看最近报告、导出状态和客户可见材料。"],
  ["actions", "下一步行动", "查看内容、信源和复测建议。"],
  ["handoff", "交付包", "查看正式交付材料和发布准备状态。"],
  ["traceability", "可解释性", "查看审计事件、方法版本和证据映射。"]
];

export default async function CustomerHome({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) || {};
  const invitationId = Array.isArray(params.invitation_id) ? params.invitation_id[0] : params.invitation_id;
  const selectedProjectId = Array.isArray(params.project_id) ? params.project_id[0] : params.project_id;
  const [sessionData, runtimeSession] = await Promise.all([
    loadSessionPortal(selectedProjectId),
    hasRuntimeSession()
  ]);
  const data = sessionData;
  const bundle = data?.bundle;
  const project = bundle?.project?.project;
  const tenant = bundle?.project?.tenant;
  const launch = bundle?.launch_config?.launch_config;
  const projectId = project?.id || bundle?.access?.project_id || "";
  const actorId = bundle?.access?.member_user_id;
  const runtime = projectId ? await loadPortalRuntimeData(projectId, actorId) : null;
  const score = runtime ? latestScore(runtime.scores) : undefined;
  const progressWidth = typeof score === "number" ? `${Math.max(3, Math.round(score * 100))}%` : "0%";
  const authorizedProjects = sessionData?.authorized_projects || [];
  const authenticated = sessionData.authenticated;

  return (
    <main className="shell">
      <SessionDeliveryConfirm active={runtimeSession && authenticated} />
      <section className="topbar">
        <div>
          <p className="eyebrow">GEO 客户门户</p>
          <h1>{project?.target_brand || "GEO 项目工作台"}</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            {tenant?.name || "登录后查看已授权项目的可见度、信源、证据、报告与行动计划。"}
          </p>
        </div>
        {authenticated ? (
          <div className="actionRow">
            {authorizedProjects.length > 1 ? (
              <form className="tokenForm" action="/" method="get">
                <label><span>授权项目</span><select name="project_id" defaultValue={projectId}>
                  {authorizedProjects.map((record) => (
                    <option value={record.project?.id} key={record.project?.id}>{record.project?.name || record.project?.target_brand || record.project?.id}</option>
                  ))}
                </select></label>
                <button type="submit">切换</button>
              </form>
            ) : null}
            <form method="post" action="/api/auth/logout"><button className="secondary" type="submit">退出登录</button></form>
          </div>
        ) : null}
      </section>

      {!authenticated ? (
        <section className="emptyState">
          <h2>使用客户邀请登录</h2>
          <p>邀请只用于首次兑换。成功后浏览器保存安全会话，不会在 URL 中继续携带 token。</p>
          {sessionData.error ? (
            <div aria-live="polite" role="alert" style={{ color: "#9b2f20", marginTop: 12 }}>
              <p>{sessionData.error.detail}</p>
              {sessionData.error.correlation_id ? <p className="muted">关联 ID：{sessionData.error.correlation_id}</p> : null}
            </div>
          ) : null}
          <InvitationLoginForm
            initialInvitationId={invitationId || ""}
            landingPath="/"
            recommendedSurfaceUrls={{ admin: adminWebBaseUrl(), customer: "/" }}
            surface="customer"
          />
        </section>
      ) : !projectId ? (
        <section className="emptyState">
          <h2>{sessionData.error ? "项目加载失败" : "暂无授权项目"}</h2>
          <p>{sessionData.error?.detail || "当前会话没有客户门户可见的项目。"}</p>
          {sessionData.error?.correlation_id ? <p className="muted">关联 ID：{sessionData.error.correlation_id}</p> : null}
        </section>
      ) : (
        <>
          {sessionData.selection_status === "fallback" ? (
            <section aria-live="polite" className="panel" role="status" style={{ marginTop: 16 }}>
              <p>原项目已不可用，已切换到另一个授权项目。</p>
            </section>
          ) : null}
          {runtime?.errors.length ? (
            <section aria-live="polite" className="panel" role="status" style={{ marginTop: 16 }}>
              <h2>部分数据暂时不可用</h2>
              {runtime.errors.slice(0, 3).map(({ resource, error }) => (
                <p className="muted" key={resource} style={{ marginTop: 8 }}>
                  {error.detail}{error.correlation_id ? ` · 关联 ID：${error.correlation_id}` : ""}
                </p>
              ))}
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
                  <strong>{bundle?.project?.prompt_count ?? 0}</strong>
                </div>
                <div className="metric">
                  <span className="muted">竞品数量</span>
                  <strong>{bundle?.project?.competitors?.length ?? 0}</strong>
                </div>
                <div className="metric">
                  <span className="muted">审计事件</span>
                  <strong>{bundle?.audit_events?.total_count ?? 0}</strong>
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
                  <strong>{bundle?.score_weight_config?.score_weight_config?.formula_version || "visibility_v1.0"}</strong>
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
                <a className="moduleTile" href={`/portal/${id}?project_id=${encodeURIComponent(projectId)}`} key={id}>
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
