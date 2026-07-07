import { ProjectLifecycleForm } from "./[project_id]/ProjectActions";
import { actorHeaders, apiBase } from "../runtime";
import { projectStatusLabel } from "./status";

type RuntimeProject = {
  project: { id: string; name?: string; target_brand?: string; status?: string; market_code?: string; category?: string };
  tenant?: { name?: string };
  competitors?: Array<{ canonical_name?: string }>;
  prompt_count?: number;
};

type ProjectPage = {
  total_count: number;
  records: RuntimeProject[];
};

const hydrationControlProps = { suppressHydrationWarning: true };

async function loadProjects(status: string): Promise<ProjectPage> {
  const query = new URLSearchParams({ limit: "50" });
  if (status === "all") {
    query.set("include_archived", "true");
  } else if (status === "archived") {
    query.set("status", "archived");
    query.set("include_archived", "true");
  } else if (status) {
    query.set("status", status);
  }
  try {
    const response = await fetch(`${apiBase()}/v1/projects/runtime?${query.toString()}`, {
      cache: "no-store",
      headers: actorHeaders()
    });
    if (!response.ok) {
      return { total_count: 0, records: [] };
    }
    return (await response.json()) as ProjectPage;
  } catch {
    return { total_count: 0, records: [] };
  }
}

export default async function ProjectsPage({ searchParams }: { searchParams?: Promise<{ status?: string; q?: string }> }) {
  const params = await searchParams;
  const status = params?.status || "";
  const query = (params?.q || "").trim().toLowerCase();
  const page = await loadProjects(status);
  const records = query
    ? page.records.filter((record) => {
        const haystack = [
          record.project.name,
          record.project.target_brand,
          record.project.category,
          record.project.id,
          record.tenant?.name
        ].filter(Boolean).join(" ").toLowerCase();
        return haystack.includes(query);
      })
    : page.records;
  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <h1>项目列表</h1>
          <p className="muted" style={{ marginTop: 8 }}>只展示内部项目列表，客户门户不会暴露此页面。</p>
        </div>
        <nav className="nav">
          <a className="button" href="/projects/new">新建项目</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <form className="toolbar" action="/projects">
        <label>
          <span>搜索项目</span>
          <input {...hydrationControlProps} name="q" defaultValue={params?.q || ""} placeholder="项目名、品牌、租户、ID" />
        </label>
        <label>
          <span>状态筛选</span>
          <select {...hydrationControlProps} name="status" defaultValue={status}>
            <option value="">默认隐藏已归档</option>
            <option value="all">全部</option>
            <option value="active">运行中</option>
            <option value="paused">暂停中</option>
            <option value="archived">已归档</option>
          </select>
        </label>
        <button type="submit">筛选</button>
      </form>

      <section className="tablePanel">
        <div className="tableHeader">
          <span>项目</span>
          <span>租户</span>
          <span>状态</span>
          <span>规模</span>
          <span>操作</span>
        </div>
        {records.map((record) => (
          <div className="tableRow" key={record.project.id}>
            <div>
              <strong>{record.project.target_brand || record.project.name}</strong>
              <p className="muted">{record.project.name || "未命名项目"} · {record.project.category || "未填写品类"}</p>
              <p className="muted">{record.project.id}</p>
            </div>
            <span>{record.tenant?.name || "未绑定租户"}</span>
            <span className="statusPill">{projectStatusLabel(record.project.status)}</span>
            <span className="muted">竞品 {record.competitors?.length ?? 0} 个 · Prompt {record.prompt_count ?? 0} 条</span>
            <div className="actionRow">
              <a className="button secondary" href={`/projects/${record.project.id}`}>打开详情</a>
              <ProjectLifecycleForm projectId={record.project.id} status={record.project.status} />
            </div>
          </div>
        ))}
      </section>

      {records.length === 0 ? (
        <section className="panel" style={{ marginTop: 18 }}>
          <h2>暂无项目或 API 未连接</h2>
          <p className="muted" style={{ marginTop: 8 }}>请先使用“新建项目”向导创建第一个澳大利亚 GEO 项目。</p>
        </section>
      ) : null}
    </main>
  );
}
