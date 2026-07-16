import type { CatalogLoadResult } from "../../catalogTypes";
import { EntityPanel } from "../../EntityPanel";
import { EvidencePanel } from "../../EvidencePanel";
import { InvitationManagementPanel } from "../../InvitationManagementPanel";
import type { InvitationLoadResult } from "../../invitationTypes";
import { MarketProfilePanel } from "../../MarketProfilePanel";
import { MemberGovernancePanel } from "../../MemberGovernancePanel";
import type { ProjectMemberLoadResult } from "../../memberTypes";
import { ProjectSettingsForm } from "../../ProjectSettingsForm";
import { ResourceProblem } from "../../ResourceProblem";
import { GeoShell } from "../../geo/features/geo/GeoShell";
import type { GeoWorkspaceData } from "../../geo/features/geo/model";
import { workbenchHref, workbenchTabs, type WorkbenchTab } from "./tabs";

type Props = Readonly<{
  activeTab: WorkbenchTab;
  catalog: CatalogLoadResult;
  geoData: GeoWorkspaceData | null;
  invitations: InvitationLoadResult;
  members: ProjectMemberLoadResult;
  projectId: string;
}>;

export function WorkbenchShell({
  activeTab,
  catalog,
  geoData,
  invitations,
  members,
  projectId
}: Props) {
  const project = catalog.project.data;
  if (!project) return <ProjectFailure problem={catalog.project.problem} />;
  const canManageProject = members.currentRole === "owner" || members.currentRole === "admin";

  return (
    <main className="shell">
      <section className="topbar compactTopbar">
        <nav className="nav">
          <a className="button secondary" href="/projects">项目列表</a>
          <a className="button secondary" href="/">返回首页</a>
        </nav>
      </section>

      <section className="projectHero">
        <p className="eyebrow">项目详情</p>
        <h1>{project.name}</h1>
        <p className="projectMeta">
          {statusLabel(project.status)} · Tenant {project.tenant_id} · {project.id}
        </p>
      </section>

      <section className="stats projectBoard" aria-label="项目看板">
        <div className="stat"><span className="muted">状态</span><strong>{statusLabel(project.status)}</strong></div>
        <div className="stat"><span className="muted">实体</span><strong>{catalog.entities.data.length}</strong></div>
        <div className="stat"><span className="muted">市场</span><strong>{catalog.markets.data.length}</strong></div>
        <div className="stat"><span className="muted">证据</span><strong>{catalog.evidence.data.length}</strong></div>
        <div className="stat"><span className="muted">成员角色</span><strong>{members.currentRole ? roleLabel(members.currentRole) : "未识别"}</strong></div>
      </section>

      <nav className="tabBar" aria-label="项目工作台">
        {workbenchTabs.map((tab) => (
          <a
            className={`tabLink${tab.id === activeTab ? " active" : ""}`}
            href={workbenchHref(project.id, tab.id)}
            key={tab.id}
          >
            {tab.label}
          </a>
        ))}
      </nav>

      <section className="workspacePanel">
        {activeTab === "basic" ? (
          <BasicPanel
            canManageProject={canManageProject}
            catalog={catalog}
            projectId={project.id}
          />
        ) : null}
        {activeTab === "entry" ? (
          <EntryPanel invitations={invitations} members={members} projectId={project.id} />
        ) : null}
        {activeTab === "prompts" ? <PromptPanel projectId={project.id} /> : null}
        {activeTab === "knowledge" ? (
          <KnowledgePanel catalog={catalog} projectId={project.id} />
        ) : null}
        {activeTab === "operations" ? <OperationsPanel projectId={project.id} /> : null}
        {activeTab === "geo" ? (
          geoData ? <GeoShell data={geoData} projectId={project.id} /> : <EmptyState text="正在准备 GEO 投放工作区。" />
        ) : null}
        {activeTab === "status" ? (
          <StatusPanel catalog={catalog} invitations={invitations} members={members} projectId={project.id} />
        ) : null}
        {activeTab === "e2e" ? <E2EPanel projectId={project.id} /> : null}
      </section>
    </main>
  );
}

function BasicPanel({
  canManageProject,
  catalog,
  projectId
}: {
  canManageProject: boolean;
  catalog: CatalogLoadResult;
  projectId: string;
}) {
  return (
    <div className="sectionStack">
      <section className="detailPanel unframedPanel">
        <div className="sectionTitle">
          <div><p className="eyebrow">项目与品牌</p><h2>项目设置</h2></div>
        </div>
        {catalog.project.data && canManageProject ? (
          <ProjectSettingsForm project={catalog.project.data} />
        ) : (
          <EmptyState text="仅项目负责人或管理员可以修改名称和状态。" />
        )}
      </section>
      <EntityPanel projectId={projectId} resource={catalog.entities} />
      <MarketProfilePanel projectId={projectId} resource={catalog.markets} />
    </div>
  );
}

function EntryPanel({
  invitations,
  members,
  projectId
}: {
  invitations: InvitationLoadResult;
  members: ProjectMemberLoadResult;
  projectId: string;
}) {
  return (
    <div className="sectionStack">
      <section className="detailPanel unframedPanel">
        <p className="eyebrow">用户入口</p>
        <h2>邀请、成员与安全会话</h2>
        <p className="muted formIntro">
          客户入口与内部 OIDC 成员在同一工作台管理，避免项目主入口被拆散。
        </p>
      </section>
      <InvitationManagementPanel data={invitations} projectId={projectId} />
      <MemberGovernancePanel data={members} projectId={projectId} />
    </div>
  );
}

function PromptPanel({ projectId }: { projectId: string }) {
  return (
    <section className="detailPanel unframedPanel">
      <p className="eyebrow">Prompt</p>
      <h2>Prompt 配置与生成规则</h2>
      <p className="muted formIntro">
        旧 Prompt 工作台入口保留；GEO 文案生产使用可编辑 Prompt Skill、不可变 Release 和 Prompt Bundle。
      </p>
      <a className="button" href={`/projects/${encodeURIComponent(projectId)}?tab=geo&geo_section=placement&placement_stage=intake`}>
        打开 GEO Prompt / Bundle
      </a>
    </section>
  );
}

function KnowledgePanel({
  catalog,
  projectId
}: {
  catalog: CatalogLoadResult;
  projectId: string;
}) {
  return (
    <div className="sectionStack">
      <section className="detailPanel unframedPanel">
        <p className="eyebrow">知识库</p>
        <h2>证据治理与事实来源</h2>
        <p className="muted formIntro">
          这里保留知识库主入口，并接入新的实体、市场、事实证据和真实消费者使用描述治理模型。
        </p>
      </section>
      <EvidencePanel
        entities={catalog.entities.data}
        projectId={projectId}
        resource={catalog.evidence}
      />
    </div>
  );
}

function OperationsPanel({ projectId }: { projectId: string }) {
  return (
    <section className="detailPanel unframedPanel">
      <p className="eyebrow">运营工作台</p>
      <h2>内容、投放与复测运营</h2>
      <p className="muted formIntro">
        旧运营入口保留；新的发布请求、人工投放、URL 回填、验证和 T+28/T+56/T+84 测量进入 GEO 投放工作流。
      </p>
      <a className="button" href={`/projects/${encodeURIComponent(projectId)}?tab=geo&geo_section=placement&placement_stage=publication`}>
        打开发布与测量
      </a>
    </section>
  );
}

function StatusPanel({
  catalog,
  invitations,
  members,
  projectId
}: {
  catalog: CatalogLoadResult;
  invitations: InvitationLoadResult;
  members: ProjectMemberLoadResult;
  projectId: string;
}) {
  const rows: Array<[string, string]> = [
    ["项目", catalog.project.data?.status || "unknown"],
    ["实体", String(catalog.entities.data.length)],
    ["市场", String(catalog.markets.data.length)],
    ["证据", String(catalog.evidence.data.length)],
    ["邀请", String(invitations.page.total)],
    ["内部成员", String(members.page.total)]
  ];
  return (
    <section className="detailPanel unframedPanel">
      <p className="eyebrow">项目状态</p>
      <h2>运行摘要</h2>
      <SummaryTable rows={rows} />
      <p className="muted formIntro">项目 ID：{projectId}</p>
    </section>
  );
}

function E2EPanel({ projectId }: { projectId: string }) {
  return (
    <section className="detailPanel unframedPanel">
      <p className="eyebrow">全流程测试</p>
      <h2>采集、生成、投放与客户交付验收</h2>
      <p className="muted formIntro">
        开发验收从此项目主入口进入；GEO 全流程测试请使用运行手册和当前项目下的 GEO 投放主 Tab。
      </p>
      <a className="button" href={`/projects/${encodeURIComponent(projectId)}?tab=geo`}>
        打开 GEO 全流程
      </a>
    </section>
  );
}

function ProjectFailure({ problem }: { problem?: { status?: number; detail: string; correlationId?: string } }) {
  const title = problem?.status === 403
    ? "无权访问项目"
    : problem?.status === 404
      ? "项目不存在"
      : "项目加载失败";
  return (
    <main className="shell">
      <section className="topbar">
        <div><h1>{title}</h1><p className="muted" style={{ marginTop: 8 }}>{problem?.detail || "项目服务暂时不可用，请稍后重试。"}</p></div>
        <nav className="nav"><a className="button secondary" href="/projects">返回项目列表</a></nav>
      </section>
      {problem ? <ResourceProblem label="项目" problem={problem} /> : null}
    </main>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="muted emptyState">{text}</p>;
}

function SummaryTable({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="summaryTable">
      {rows.map(([label, value]) => (
        <div key={label}><span>{label}</span><strong>{value || "无"}</strong></div>
      ))}
    </div>
  );
}

function statusLabel(status: string): string {
  if (status === "active") return "运行中";
  if (status === "paused") return "已暂停";
  if (status === "archived") return "已归档";
  return status;
}

function roleLabel(role: string): string {
  if (role === "owner") return "负责人";
  if (role === "admin") return "管理员";
  if (role === "analyst") return "分析师";
  return role;
}
