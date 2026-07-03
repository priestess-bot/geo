import { InvitationForm, TokenCreateForm, TokenRevokeForm } from "./ProjectActions";
import { actorHeaders, apiBase, runtimeRequest } from "../../runtime";

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

type PageResponse<T> = { total_count: number; records: T[] };

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

async function loadPage<T>(path: string, projectId: string): Promise<PageResponse<T>> {
  const response = await runtimeRequest<PageResponse<T>>(path, { query: { project_id: projectId, limit: 10 } });
  return response.ok && response.data ? response.data : { total_count: 0, records: [] };
}

export default async function ProjectDetailPage({ params }: { params: Promise<{ project_id: string }> }) {
  const { project_id: projectId } = await params;
  const [record, launchConfig, members, invitations, tokens, scores, reports, jobs, actions, graphs] = await Promise.all([
    loadProject(projectId),
    loadLaunchConfig(projectId),
    loadPage<Record<string, unknown>>("/v1/project-members/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/project-member-invitations/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/customer-portal/tokens/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/visibility-scores/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/reports/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/report-export-jobs/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/action-plans/runtime", projectId),
    loadPage<Record<string, unknown>>("/v1/citation-graphs/runtime", projectId)
  ]);
  const launch = launchConfig?.launch_config || {};
  const defaultEmail = typeof launch.customer_email === "string" ? launch.customer_email : undefined;

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
        <h2>客户入口</h2>
        <p className="muted" style={{ marginTop: 8 }}>
          主流程是创建 viewer 邀请，客户首次用 invitation token 进入 Customer Web 并换取门户 token。raw token 只显示一次。
        </p>
        <InvitationForm projectId={projectId} defaultEmail={defaultEmail} />
        <div className="twoCol compact">
          <div className="detailPanel">
            <h3>门户 token</h3>
            <TokenCreateForm projectId={projectId} />
            <TokenRevokeForm projectId={projectId} />
          </div>
          <div className="detailPanel">
            <h3>已有 token 元数据</h3>
            <pre>{JSON.stringify(tokens, null, 2)}</pre>
          </div>
        </div>
      </section>

      <section className="twoCol">
        <div className="detailPanel">
          <h2>成员</h2>
          <pre>{JSON.stringify(members, null, 2)}</pre>
        </div>
        <div className="detailPanel">
          <h2>邀请</h2>
          <pre>{JSON.stringify(invitations, null, 2)}</pre>
        </div>
      </section>

      <section className="grid">
        <RuntimeSummary title="评分快照" page={scores} />
        <RuntimeSummary title="报告" page={reports} />
        <RuntimeSummary title="报告任务" page={jobs} />
        <RuntimeSummary title="行动计划" page={actions} />
        <RuntimeSummary title="信源图谱" page={graphs} />
      </section>
    </main>
  );
}

function RuntimeSummary({ title, page }: { title: string; page: PageResponse<Record<string, unknown>> }) {
  return (
    <div className="projectCard">
      <span className="statusPill">{page.total_count} 条</span>
      <h2>{title}</h2>
      <p className="muted">读取真实 runtime API；无数据时保持空状态。</p>
      <pre>{JSON.stringify(page.records.slice(0, 2), null, 2)}</pre>
    </div>
  );
}
