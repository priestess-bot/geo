type PortalBundle = {
  access?: { project_id?: string; member_user_id?: string };
  project?: {
    project?: { id?: string; name?: string; target_brand?: string; status?: string };
    competitors?: Array<{ canonical_name?: string; official_domains?: string[] }>;
    prompt_count?: number;
  };
  launch_config?: { launch_config?: Record<string, unknown> } | null;
  score_weight_config?: { score_weight_config?: Record<string, unknown> } | null;
  lifecycle_events?: { total_count?: number; records?: unknown[] };
  audit_events?: { total_count?: number; records?: unknown[] };
};

type PortalAccessResponse = {
  bundle?: PortalBundle;
};

const moduleMeta: Record<string, { title: string; intro: string }> = {
  visibility: { title: "AI 可见度", intro: "汇总项目当前在 AI 搜索和搜索增强结果中的出现、提及和推荐表现。" },
  sources: { title: "信源与竞品", intro: "梳理 AI 引用来源、品牌可控信源缺口和主要竞品对比。" },
  evidence: { title: "证据样本", intro: "查看支撑结论的采集样本、引用和证据链上下文。" },
  reports: { title: "报告交付", intro: "查看客户可见报告、导出状态和交付材料。" },
  actions: { title: "下一步行动", intro: "展示内容、信源、复测和运营动作建议。" },
  handoff: { title: "交付包", intro: "查看试点阶段交付包准备状态和缺口。" },
  traceability: { title: "可解释性", intro: "查看方法版本、审计事件和证据映射摘要。" }
};

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

function panelFor(moduleId: string, bundle: PortalBundle) {
  const project = bundle.project?.project;
  const competitors = bundle.project?.competitors || [];
  if (moduleId === "sources") {
    return (
      <div className="detailPanel">
        <h2>竞品与信源范围</h2>
        <div className="list">
          {competitors.map((competitor, index) => (
            <div className="listItem" key={`${competitor.canonical_name}-${index}`}>
              <strong>{competitor.canonical_name || "未命名竞品"}</strong>
              <p className="muted">{(competitor.official_domains || []).join(", ") || "官方域名待补充"}</p>
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (moduleId === "traceability") {
    return (
      <div className="twoCol">
        <div className="detailPanel">
          <h2>审计事件</h2>
          <p className="muted" style={{ marginTop: 8 }}>当前返回 {bundle.audit_events?.total_count ?? 0} 条审计事件摘要。</p>
          <pre>{JSON.stringify(bundle.audit_events?.records?.slice(0, 5) || [], null, 2)}</pre>
        </div>
        <div className="detailPanel">
          <h2>生命周期</h2>
          <p className="muted" style={{ marginTop: 8 }}>当前返回 {bundle.lifecycle_events?.total_count ?? 0} 条项目生命周期事件。</p>
          <pre>{JSON.stringify(bundle.lifecycle_events?.records?.slice(0, 5) || [], null, 2)}</pre>
        </div>
      </div>
    );
  }
  if (moduleId === "reports" || moduleId === "handoff") {
    return (
      <div className="detailPanel">
        <h2>交付状态</h2>
        <p className="muted" style={{ marginTop: 8 }}>
          当前阶段优先展示项目、启动配置和可解释性链路；报告 artifact 与交付包详情接入后会在此页呈现客户可见下载入口。
        </p>
        <pre>{JSON.stringify(bundle.launch_config?.launch_config || {}, null, 2)}</pre>
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
  const data = await loadPortal(token);
  const meta = moduleMeta[module] || { title: "项目详情", intro: "查看项目详情。" };

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
        panelFor(module, data.bundle)
      )}
    </main>
  );
}
