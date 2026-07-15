import { redirect } from "next/navigation";

import { loadCatalog } from "./catalogData";
import { EntityPanel } from "./EntityPanel";
import { EvidencePanel } from "./EvidencePanel";
import { InvitationManagementPanel } from "./InvitationManagementPanel";
import { loadProjectInvitations } from "./invitationData";
import { MarketProfilePanel } from "./MarketProfilePanel";
import { MemberGovernancePanel } from "./MemberGovernancePanel";
import { loadProjectMembers } from "./memberData";
import { ProjectSettingsForm } from "./ProjectSettingsForm";
import { ResourceProblem } from "./ResourceProblem";
import type { ProjectLoadProblem } from "../projectTypes";
import styles from "./Catalog.module.css";

export default async function ProjectDetailPage({
  params
}: {
  params: Promise<{ project_id: string }>;
}) {
  const { project_id: projectId } = await params;
  const [catalog, invitations, members] = await Promise.all([
    loadCatalog(projectId),
    loadProjectInvitations(projectId),
    loadProjectMembers(projectId)
  ]);
  if (catalog.project.problem?.status === 401) redirect("/login");
  const project = catalog.project.data;
  if (!project) return <ProjectFailure problem={catalog.project.problem} />;
  const canManageProject = members.currentRole === "owner" || members.currentRole === "admin";

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">Project Catalog</p>
          <h1>{project.name}</h1>
          <div className={styles.projectMeta} style={{ marginTop: 10 }}>
            <span>{statusLabel(project.status)}</span>
            <span>项目 ID：{project.id}</span>
            <span>Tenant：{project.tenant_id}</span>
          </div>
        </div>
        <nav className="nav">
          <a className="button" href={`/projects/${encodeURIComponent(project.id)}/geo`}>GEO 投放工作区</a>
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <div className={styles.workspace}>
        <section className={styles.section} id="project">
          <header className={styles.sectionHeader}>
            <div><p>Project boundary</p><h2>项目设置</h2></div>
            <span className={styles.badge}>更新于 {formatDate(project.updated_at)}</span>
          </header>
          {canManageProject ? (
            <ProjectSettingsForm project={project} />
          ) : (
            <div className={styles.empty}>仅项目负责人或管理员可以修改名称和状态。</div>
          )}
        </section>

        <EntityPanel projectId={project.id} resource={catalog.entities} />
        <MarketProfilePanel projectId={project.id} resource={catalog.markets} />
        <EvidencePanel
          entities={catalog.entities.data}
          projectId={project.id}
          resource={catalog.evidence}
        />
        <InvitationManagementPanel data={invitations} projectId={project.id} />
        <section className={styles.section} id="members">
          <header className={styles.sectionHeader}>
            <div><p>Internal access</p><h2>内部成员治理</h2></div>
          </header>
          <MemberGovernancePanel data={members} projectId={project.id} />
        </section>
      </div>
    </main>
  );
}

function ProjectFailure({ problem }: { problem?: ProjectLoadProblem }) {
  const status = problem?.status;
  const title = status === 403
    ? "无权访问项目"
    : status === 404
      ? "项目不存在"
      : "项目加载失败";
  const fallback = status === 403
    ? "当前 OIDC 身份没有此项目的读取权限。"
    : status === 404
      ? "项目不存在、已删除或当前租户不可见。"
      : "项目服务暂时不可用，请稍后重试。";
  return (
    <main className="shell">
      <section className="topbar">
        <div><h1>{title}</h1><p className="muted" style={{ marginTop: 8 }}>{problem?.detail || fallback}</p></div>
        <nav className="nav"><a className="button secondary" href="/projects">返回项目列表</a></nav>
      </section>
      {problem ? <ResourceProblem label="项目" problem={problem} /> : null}
    </main>
  );
}

function statusLabel(status: string): string {
  if (status === "active") return "运行中";
  if (status === "paused") return "已暂停";
  if (status === "archived") return "已归档";
  return status;
}

function formatDate(value: string): string {
  return value.slice(0, 16).replace("T", " ");
}
