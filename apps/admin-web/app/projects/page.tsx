import { redirect } from "next/navigation";

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
  error?: string;
  correlation_id?: string;
  status?: number;
};

const hydrationControlProps = { suppressHydrationWarning: true };
const PROJECT_PAGE_SIZE = 50;

async function loadProjects(status: string, offset: number): Promise<ProjectPage> {
  const query = new URLSearchParams({
    limit: String(PROJECT_PAGE_SIZE),
    offset: String(offset),
    surface: "admin"
  });
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
      headers: await actorHeaders()
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => undefined) as {
        detail?: unknown;
        correlation_id?: unknown;
      } | undefined;
      return {
        total_count: 0,
        records: [],
        error: typeof payload?.detail === "string" ? payload.detail : `项目加载失败（${response.status}）`,
        correlation_id: typeof payload?.correlation_id === "string" ? payload.correlation_id : undefined,
        status: response.status
      };
    }
    return (await response.json()) as ProjectPage;
  } catch {
    return { total_count: 0, records: [], error: "项目服务暂时不可用，请稍后重试。" };
  }
}

export default async function ProjectsPage({
  searchParams
}: {
  searchParams?: Promise<{ status?: string; q?: string; offset?: string }>;
}) {
  const params = await searchParams;
  const status = params?.status || "";
  const query = (params?.q || "").trim().toLowerCase();
  const offset = Math.max(0, Math.floor(Number(params?.offset || 0) || 0));
  const page = await loadProjects(status, offset);
  if (page.status === 401) {
    redirect("/login");
  }
  if (!page.error && offset > 0 && (page.total_count === 0 || offset >= page.total_count)) {
    const lastOffset = page.total_count > 0
      ? Math.floor((page.total_count - 1) / PROJECT_PAGE_SIZE) * PROJECT_PAGE_SIZE
      : 0;
    redirect(projectPageHref(params, lastOffset));
  }
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

      {!page.error && page.total_count > 0 ? (
        <nav aria-label="项目分页" className="actionRow" style={{ alignItems: "center", marginTop: 14 }}>
          <span className="muted">
            {offset + 1}-{Math.min(offset + page.records.length, page.total_count)} / {page.total_count}
          </span>
          {offset > 0 ? (
            <a className="button secondary" href={projectPageHref(params, Math.max(0, offset - PROJECT_PAGE_SIZE))}>上一页</a>
          ) : null}
          {offset + page.records.length < page.total_count ? (
            <a className="button secondary" href={projectPageHref(params, offset + page.records.length)}>下一页</a>
          ) : null}
        </nav>
      ) : null}

      {page.error ? (
        <section className="notice error" aria-live="polite" role="alert" style={{ marginTop: 18 }}>
          <p>{page.error}</p>
          {page.correlation_id ? <p className="muted">关联 ID：{page.correlation_id}</p> : null}
        </section>
      ) : null}

      {records.length === 0 && !page.error ? (
        <section className="panel" style={{ marginTop: 18 }}>
          <h2>暂无可管理项目</h2>
          <p className="muted" style={{ marginTop: 8 }}>
            {query ? "当前页没有匹配项目。" : "当前会话没有此入口可见的项目。"}
          </p>
        </section>
      ) : null}
    </main>
  );
}

function projectPageHref(
  params: { status?: string; q?: string; offset?: string } | undefined,
  offset: number
): string {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.q) query.set("q", params.q);
  if (offset > 0) query.set("offset", String(offset));
  const suffix = query.toString();
  return suffix ? `/projects?${suffix}` : "/projects";
}
