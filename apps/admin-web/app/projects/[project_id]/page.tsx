type RuntimeProject = {
  project: { id: string; name?: string; target_brand?: string; status?: string; market_code?: string };
  tenant?: { name?: string };
  competitors?: Array<{ canonical_name?: string; official_domains?: string[] }>;
  prompt_count?: number;
};

type ProjectPage = {
  total_count: number;
  records: RuntimeProject[];
};

type LaunchConfigResponse = {
  launch_config?: Record<string, unknown>;
};

function apiBase(): string {
  return process.env.API_INTERNAL_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://api:8000";
}

function actorHeaders(): HeadersInit {
  return { "X-GENO-Actor-Id": process.env.GENO_ADMIN_ACTOR_ID || "runtime-console" };
}

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

export default async function ProjectDetailPage({ params }: { params: Promise<{ project_id: string }> }) {
  const { project_id: projectId } = await params;
  const [record, launchConfig] = await Promise.all([loadProject(projectId), loadLaunchConfig(projectId)]);

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">项目详情</p>
          <h1>{record?.project.target_brand || "项目未读取"}</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            {record?.tenant?.name || "API 未连接或无权限"} · {projectId}
          </p>
        </div>
        <nav className="nav">
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <section className="twoCol">
        <div className="detailPanel">
          <h2>项目配置</h2>
          <pre>{JSON.stringify(record || {}, null, 2)}</pre>
        </div>
        <div className="detailPanel">
          <h2>启动配置</h2>
          <pre>{JSON.stringify(launchConfig?.launch_config || {}, null, 2)}</pre>
        </div>
      </section>

      <section className="panel" style={{ marginTop: 16 }}>
        <h2>客户门户 token</h2>
        <p className="muted" style={{ marginTop: 8 }}>
          后台应调用 `POST /v1/customer-portal/tokens/runtime` 为 viewer 成员生成门户 token。raw token 只返回一次，
          数据库只保存 hash；撤销调用 `/v1/customer-portal/tokens/runtime/revoke`。
        </p>
        <div className="testRow">
          <span className="muted">后续将把这里接成表单按钮，并在生成后只显示一次 raw token。</span>
          <button type="button">生成 token</button>
        </div>
      </section>
    </main>
  );
}
