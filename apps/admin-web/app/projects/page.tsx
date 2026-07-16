import { redirect } from "next/navigation";

import { runtimeRequest } from "../runtime";
import {
  isProjectListResponse,
  type ProjectListResponse,
  type ProjectLoadProblem
} from "./projectTypes";

const PAGE_SIZE = 50;

type ProjectPageResult = Readonly<{
  page: ProjectListResponse;
  problem?: ProjectLoadProblem;
}>;

const emptyPage: ProjectListResponse = { items: [], total: 0, limit: PAGE_SIZE, offset: 0 };

async function loadProjects(offset: number): Promise<ProjectPageResult> {
  const response = await runtimeRequest<ProjectListResponse>("/v1/projects", {
    query: { limit: PAGE_SIZE, offset }
  });
  if (!response.ok) {
    return {
      page: emptyPage,
      problem: {
        status: response.status,
        detail: response.error || "项目列表暂时不可用。",
        ...(response.problem.correlation_id
          ? { correlationId: response.problem.correlation_id }
          : {})
      }
    };
  }
  if (!isProjectListResponse(response.data)) {
    return {
      page: emptyPage,
      problem: {
        status: 502,
        detail: "项目接口返回了无法识别的响应。",
        ...(response.response.correlationId
          ? { correlationId: response.response.correlationId }
          : {})
      }
    };
  }
  return { page: response.data };
}

export default async function ProjectsPage({
  searchParams
}: {
  searchParams?: Promise<{ q?: string; offset?: string }>;
}) {
  const params = await searchParams;
  const query = (params?.q || "").trim().toLowerCase();
  const offset = Math.max(0, Math.floor(Number(params?.offset || 0) || 0));
  const result = await loadProjects(offset);
  if (result.problem?.status === 401) redirect("/login");
  if (!result.problem && offset > 0 && offset >= result.page.total) {
    const last = result.page.total
      ? Math.floor((result.page.total - 1) / PAGE_SIZE) * PAGE_SIZE
      : 0;
    redirect(projectPageHref(params, last));
  }
  const projects = query
    ? result.page.items.filter((project) => (
        `${project.name} ${project.key} ${project.id} ${project.role}`.toLowerCase().includes(query)
      ))
    : result.page.items;

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">Project Catalog</p>
          <h1>项目列表</h1>
          <p className="muted" style={{ marginTop: 8 }}>当前 OIDC 身份获授权的内部项目。</p>
        </div>
        <nav className="nav">
          <a className="button" href="/projects/new">新建项目</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <form className="toolbar" action="/projects">
        <label>
          <span>搜索当前页</span>
          <input name="q" defaultValue={params?.q || ""} placeholder="项目名、Key、ID 或角色" />
        </label>
        <button type="submit">筛选</button>
      </form>

      {result.problem ? <ProblemNotice problem={result.problem} /> : null}

      {!result.problem && projects.length ? (
        <section className="tablePanel">
          <div className="tableHeader">
            <span>项目</span><span>Project Key</span><span>当前角色</span><span>Catalog</span><span>GEO</span>
          </div>
          {projects.map((project) => (
            <div className="tableRow" key={project.id}>
              <div><strong>{project.name}</strong><p className="muted">{project.id}</p></div>
              <code>{project.key}</code>
              <span className="statusPill">{roleLabel(project.role)}</span>
              <a className="button" href={`/projects/${encodeURIComponent(project.id)}`}>
                打开项目工作台
              </a>
              <a className="button secondary" href={`/projects/${encodeURIComponent(project.id)}?tab=geo`}>
                GEO 投放
              </a>
            </div>
          ))}
        </section>
      ) : null}

      {!result.problem && !projects.length ? (
        <section className="panel" style={{ marginTop: 18 }}>
          <h2>{query ? "当前页无匹配项目" : "暂无可管理项目"}</h2>
          <p className="muted" style={{ marginTop: 8 }}>
            {query ? "清除搜索条件后重试。" : "请确认 OIDC 项目成员关系，或创建新项目。"}
          </p>
        </section>
      ) : null}

      {!result.problem && result.page.total > 0 ? (
        <nav aria-label="项目分页" className="actionRow" style={{ marginTop: 14 }}>
          <span className="muted">
            {offset + 1}-{Math.min(offset + result.page.items.length, result.page.total)} / {result.page.total}
          </span>
          {offset > 0 ? (
            <a className="button secondary" href={projectPageHref(params, Math.max(0, offset - PAGE_SIZE))}>
              上一页
            </a>
          ) : null}
          {offset + result.page.items.length < result.page.total ? (
            <a className="button secondary" href={projectPageHref(params, offset + result.page.items.length)}>
              下一页
            </a>
          ) : null}
        </nav>
      ) : null}
    </main>
  );
}

function ProblemNotice({ problem }: { problem: ProjectLoadProblem }) {
  const title = problem.status === 403 ? "无权读取项目" : "项目列表加载失败";
  return (
    <section className="notice error" role="alert" style={{ marginTop: 18 }}>
      <strong>{title}</strong><span>{problem.detail}</span>
      {problem.correlationId ? <small>关联 ID：{problem.correlationId}</small> : null}
    </section>
  );
}

function projectPageHref(
  params: { q?: string; offset?: string } | undefined,
  offset: number
): string {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (offset > 0) query.set("offset", String(offset));
  const suffix = query.toString();
  return suffix ? `/projects?${suffix}` : "/projects";
}

function roleLabel(role: string): string {
  if (role === "owner") return "负责人";
  if (role === "admin") return "管理员";
  if (role === "analyst") return "分析师";
  return role;
}
