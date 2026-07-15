import Link from "next/link";
import type { ReactNode } from "react";

import type { CustomerProblemDetails, CustomerProjectSummary } from "@geo/types/customer";

import type { SessionPortalResponse } from "../runtime";

export type PortalModule = "summary" | "metrics" | "placements" | "reports";

const NAVIGATION: ReadonlyArray<Readonly<{
  id: PortalModule;
  label: string;
}>> = [
  { id: "summary", label: "项目概览" },
  { id: "metrics", label: "趋势指标" },
  { id: "placements", label: "投放与窗口" },
  { id: "reports", label: "已批准报告" }
];

export function PortalChrome({
  active,
  children,
  problems,
  session
}: Readonly<{
  active: PortalModule;
  children: ReactNode;
  problems: CustomerProblemDetails[];
  session: SessionPortalResponse;
}>) {
  const project = session.selectedProject;
  const projectId = project?.project_id || "";
  return (
    <main className="shell">
      <header className="topbar">
        <div className="brandBlock">
          <p className="eyebrow">GEO 客户门户</p>
          <h1>{project?.display_name || "项目工作台"}</h1>
          <p className="muted">
            {project ? `${project.market_code} 市场 · ${project.status}` : "客户只读视图"}
          </p>
        </div>
        <div className="sessionActions">
          <ProjectSelector active={active} projects={session.projects} selected={project} />
          <form action="/api/auth/logout" method="post">
            <button className="secondary" type="submit">退出</button>
          </form>
        </div>
      </header>

      <div className="portalContext">
        <nav aria-label="客户门户视图" className="portalNav">
          {NAVIGATION.map((item) => (
            <Link
              aria-current={active === item.id ? "page" : undefined}
              className={active === item.id ? "active" : undefined}
              href={`/portal/${item.id}?project_id=${encodeURIComponent(projectId)}`}
              key={item.id}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <p className="roleLine">
          当前项目角色：{project?.role || "未提供"}
          {session.roles.length ? ` · 会话角色：${session.roles.join("、")}` : ""}
        </p>
      </div>

      {session.selectionStatus === "fallback" ? (
        <Notice detail="请求的项目已不在当前授权范围，已切换到另一个授权项目。" />
      ) : null}
      {problems.length ? <ProblemSummary problems={problems} /> : null}
      <div className="portalContent">{children}</div>
    </main>
  );
}

export function PortalAccessState({
  detail,
  requestId,
  title
}: Readonly<{ detail: string; requestId?: string; title: string }>) {
  return (
    <main className="shell">
      <section aria-live="polite" className="emptyState" role="status">
        <p className="eyebrow">GEO 客户门户</p>
        <h1>{title}</h1>
        <p>{detail}</p>
        {requestId ? <p className="muted">请求 ID：{requestId}</p> : null}
        <div className="actionRow">
          <Link className="button" href="/">返回登录页</Link>
        </div>
      </section>
    </main>
  );
}

function ProjectSelector({
  active,
  projects,
  selected
}: Readonly<{
  active: PortalModule;
  projects: CustomerProjectSummary[];
  selected: CustomerProjectSummary | null;
}>) {
  if (projects.length <= 1) return null;
  return (
    <form action={`/portal/${active}`} className="projectSelector" method="get">
      <label>
        <span>授权项目</span>
        <select defaultValue={selected?.project_id} name="project_id">
          {projects.map((project) => (
            <option key={project.project_id} value={project.project_id}>
              {project.display_name} · {project.market_code} · {project.role}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">切换</button>
    </form>
  );
}

function Notice({ detail }: Readonly<{ detail: string }>) {
  return (
    <section aria-live="polite" className="noticeBand" role="status">
      <p>{detail}</p>
    </section>
  );
}

function ProblemSummary({ problems }: Readonly<{ problems: CustomerProblemDetails[] }>) {
  return (
    <section aria-live="polite" className="problemBand" role="status">
      <h2>部分数据暂不可用</h2>
      {problems.slice(0, 3).map((problem, index) => (
        <p key={`${problem.instance}-${problem.request_id}-${index}`}>
          {problem.detail}
          {problem.request_id ? ` · 请求 ID：${problem.request_id}` : ""}
        </p>
      ))}
    </section>
  );
}
