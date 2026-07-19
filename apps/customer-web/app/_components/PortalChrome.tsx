import Link from "next/link";
import type { ReactNode } from "react";

import type {
  CustomerCampaign,
  CustomerProblemDetails,
  CustomerProjectSummary
} from "@geo/types/customer";

import type { CampaignPortalResponse, SessionPortalResponse } from "../runtime";
import { ProjectExportButton } from "./ProjectExportButton";

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
  campaignPortal,
  children,
  problems,
  session
}: Readonly<{
  active: PortalModule;
  campaignPortal: CampaignPortalResponse | null;
  children: ReactNode;
  problems: CustomerProblemDetails[];
  session: SessionPortalResponse;
}>) {
  const project = session.selectedProject;
  const campaign = campaignPortal?.selectedCampaign || null;
  return (
    <main className="shell">
      <header className="topbar">
        <div className="brandBlock">
          <p className="eyebrow">GEO 客户门户</p>
          <h1>{project?.display_name || "选择项目"}</h1>
          <p className="muted">{contextLine(project, campaign)}</p>
        </div>
        <div className="sessionActions">
          <ProjectSelector active={active} projects={session.projects} selected={project} />
          {project && campaignPortal ? (
            <CampaignSelector
              active={active}
              campaigns={campaignPortal.campaigns}
              projectId={project.project_id}
              selected={campaign}
            />
          ) : null}
          {project && campaign ? (
            <ProjectExportButton campaignId={campaign.id} projectId={project.project_id} />
          ) : null}
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
              href={portalHref(item.id, project?.project_id, campaign?.id)}
              key={item.id}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <p className="roleLine">
          当前项目角色：{project?.role || "未选择"}
          {session.roles.length ? ` · 会话角色：${session.roles.join("、")}` : ""}
        </p>
      </div>

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

export function PortalSelectionState({
  detail,
  title
}: Readonly<{ detail: string; title: string }>) {
  return (
    <section aria-live="polite" className="selectionState" role="status">
      <p className="eyebrow">当前视图</p>
      <h2>{title}</h2>
      <p>{detail}</p>
    </section>
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
  if (!projects.length) return null;
  return (
    <form action={`/portal/${active}`} className="projectSelector" method="get">
      <label>
        <span>授权项目</span>
        <select defaultValue={selected?.project_id || ""} name="project_id" required>
          <option disabled value="">选择项目</option>
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

function CampaignSelector({
  active,
  campaigns,
  projectId,
  selected
}: Readonly<{
  active: PortalModule;
  campaigns: CustomerCampaign[];
  projectId: string;
  selected: CustomerCampaign | null;
}>) {
  if (!campaigns.length) return null;
  return (
    <form action={`/portal/${active}`} className="projectSelector" method="get">
      <input name="project_id" type="hidden" value={projectId} />
      <label>
        <span>Campaign</span>
        <select defaultValue={selected?.id || ""} name="campaign_id" required>
          <option disabled value="">选择 Campaign</option>
          {campaigns.map((campaign) => (
            <option key={campaign.id} value={campaign.id}>
              {campaign.name} · {campaign.status}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">切换</button>
    </form>
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

function portalHref(
  module: PortalModule,
  projectId?: string,
  campaignId?: string
): string {
  const query = new URLSearchParams();
  if (projectId) query.set("project_id", projectId);
  if (campaignId) query.set("campaign_id", campaignId);
  const value = query.toString();
  return `/portal/${module}${value ? `?${value}` : ""}`;
}

function contextLine(
  project: CustomerProjectSummary | null,
  campaign: CustomerCampaign | null
): string {
  if (!project) return "客户只读视图";
  const market = `${project.market_code} 市场 · ${project.status}`;
  return campaign ? `${market} · ${campaign.name}` : market;
}
