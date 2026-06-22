type PortalBundle = {
  access?: { project_id?: string; member_user_id?: string };
  project?: {
    project?: { id?: string; name?: string; target_brand?: string; status?: string };
    tenant?: { name?: string };
    competitors?: Array<{ canonical_name?: string }>;
    prompt_count?: number;
  };
  launch_config?: { launch_config?: { customer_email?: string; primary_domain?: string; status?: string } } | null;
  score_weight_config?: { score_weight_config?: { formula_version?: string } } | null;
  lifecycle_events?: { total_count?: number };
  audit_events?: { total_count?: number };
};

type PortalAccessResponse = {
  portal_token?: string | null;
  bundle?: PortalBundle;
};

const modules = [
  ["visibility", "AI 可见度", "查看总分、触发率、提及率和建议率。"],
  ["sources", "信源与竞品", "查看被 AI 引用的域名、信源缺口和竞品对比。"],
  ["evidence", "证据样本", "查看采集样本、引用和可复盘证据链。"],
  ["reports", "报告交付", "查看最近报告、导出状态和客户可见材料。"],
  ["actions", "下一步行动", "查看内容、信源和复测建议。"],
  ["handoff", "交付包", "查看试点交付包准备状态。"],
  ["traceability", "可解释性", "查看审计事件、方法版本和证据映射。"]
];

function apiBase(): string {
  return process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://api:8000";
}

async function loadPortal(token: string | undefined): Promise<PortalAccessResponse | null> {
  if (!token) {
    return null;
  }
  try {
    const response = await fetch(`${apiBase()}/v1/customer-portal/access`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ portal_token: token }),
      cache: "no-store"
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as PortalAccessResponse;
  } catch {
    return null;
  }
}

function pct(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "待采集";
  }
  return `${Math.round(value * 100)}%`;
}

export default async function CustomerHome({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) || {};
  const token = Array.isArray(params.portal_token) ? params.portal_token[0] : params.portal_token;
  const data = await loadPortal(token);
  const bundle = data?.bundle;
  const project = bundle?.project?.project;
  const tenant = bundle?.project?.tenant;
  const launch = bundle?.launch_config?.launch_config;
  const projectId = project?.id || bundle?.access?.project_id || "";
  const score = undefined;

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
            <input name="portal_token" defaultValue={token || ""} placeholder="geno-portal-..." />
          </label>
          <button type="submit">打开项目</button>
        </form>
      </section>

      {!bundle ? (
        <section className="emptyState">
          <h2>等待连接客户项目</h2>
          <p>请输入后台生成的门户 token。此页面只展示绑定项目，不提供项目列表和内部排障信息。</p>
        </section>
      ) : (
        <>
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
                    <div className="progressFill" style={{ width: "36%" }} />
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
                  <span className="muted">启动配置</span>
                  <strong>{launch?.status || "待确认"}</strong>
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
                <a className="moduleTile" href={`/portal/${id}?portal_token=${encodeURIComponent(token || "")}`} key={id}>
                  <span className="statusPill">查看详情</span>
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
