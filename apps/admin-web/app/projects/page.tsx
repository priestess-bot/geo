type RuntimeProject = {
  project: { id: string; name?: string; target_brand?: string; status?: string; market_code?: string };
  tenant?: { name?: string };
  competitors?: Array<{ canonical_name?: string }>;
  prompt_count?: number;
};

type ProjectPage = {
  total_count: number;
  records: RuntimeProject[];
};

function apiBase(): string {
  return process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://api:8000";
}

async function loadProjects(): Promise<ProjectPage> {
  try {
    const response = await fetch(`${apiBase()}/v1/projects/runtime?limit=50`, {
      cache: "no-store",
      headers: { "X-GENO-Actor-Id": process.env.GENO_ADMIN_ACTOR_ID || "runtime-console" }
    });
    if (!response.ok) {
      return { total_count: 0, records: [] };
    }
    return (await response.json()) as ProjectPage;
  } catch {
    return { total_count: 0, records: [] };
  }
}

export default async function ProjectsPage() {
  const page = await loadProjects();
  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">项目列表</p>
          <h1>运行态 GEO 项目</h1>
          <p className="muted" style={{ marginTop: 8 }}>只展示内部项目列表，客户门户不会暴露此页面。</p>
        </div>
        <nav className="nav">
          <a className="button" href="/projects/new">新建项目</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <section className="grid">
        {page.records.map((record) => (
          <a className="projectCard" href={`/projects/${record.project.id}`} key={record.project.id}>
            <span className="statusPill">{record.project.status || "unknown"}</span>
            <h2>{record.project.target_brand || record.project.name}</h2>
            <p className="muted">{record.tenant?.name || "未绑定租户"} · {record.project.market_code || "AU"}</p>
            <p className="muted">竞品 {record.competitors?.length ?? 0} 个，提示问题 {record.prompt_count ?? 0} 条。</p>
          </a>
        ))}
      </section>

      {page.records.length === 0 ? (
        <section className="panel" style={{ marginTop: 18 }}>
          <h2>暂无项目或 API 未连接</h2>
          <p className="muted" style={{ marginTop: 8 }}>请先使用“新建项目”向导创建第一个澳大利亚 GEO 项目。</p>
        </section>
      ) : null}
    </main>
  );
}
