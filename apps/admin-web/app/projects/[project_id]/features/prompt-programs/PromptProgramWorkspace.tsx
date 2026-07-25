import { randomUUID } from "node:crypto";

import type { ManagedMemberRole } from "../../memberTypes";
import { PromptBootstrapCatalogPanel } from "./PromptBootstrapCatalog";
import { PromptReleaseCommands } from "./PromptReleaseCommands";
import { PromptReleaseEditorForm } from "./PromptReleaseEditorForm";
import type {
  PromptLoadProblem,
  PromptProgramBindingOption,
  PromptProgramRelease,
  PromptProgramSummary,
  PromptTestRuntimeOption,
  PromptWorkspaceData
} from "./promptProgramTypes";
import styles from "./PromptPrograms.module.css";

export function PromptProgramWorkspace({
  actorIdentityId,
  currentRole,
  data,
  projectId
}: {
  actorIdentityId: string;
  currentRole: ManagedMemberRole | null;
  data: PromptWorkspaceData;
  projectId: string;
}) {
  const canContribute = currentRole === "owner" || currentRole === "admin" || currentRole === "analyst";
  const canApprove = currentRole === "owner" || currentRole === "admin";
  const latestReleaseVersion = data.releases.items[0]?.version || 0;
  const currentBinding = data.selectedProgram
    ? data.bindings.items.find((item) => (
      item.project_id === projectId
      && item.program_kind === data.selectedProgram?.program_kind
      && item.purpose === data.selectedProgram?.purpose
    )) || null
    : null;
  return (
    <div className={styles.workspace}>
      <header className={styles.workspaceHeader}>
        <div><p>Prompt 治理</p><h2>Prompt 程序</h2></div>
        <div className={styles.summary}>
          <span><strong>{data.programs.total}</strong> 个程序</span>
          <span><strong>{data.releases.total}</strong> 个发布版本</span>
          <span><strong>{currentRole ? roleLabel(currentRole) : "未授权"}</strong> 当前角色</span>
        </div>
      </header>

      <PromptBootstrapCatalogPanel
        catalog={data.bootstrap}
        currentRole={currentRole}
        problem={data.bootstrapProblem}
        projectId={projectId}
        selectedKind={data.selectedBootstrapKind}
      />

      <details className={styles.createSection}>
        <summary>新建 Prompt 程序</summary>
        <PromptReleaseEditorForm
          catalog={data.bootstrap}
          disabled={!canContribute}
          expectedVersion={0}
          idempotencyKey={`admin-prompt-program-${randomUUID()}`}
          mode="program"
          projectId={projectId}
        />
      </details>

      {data.programsProblem ? <LoadProblem label="程序列表" problem={data.programsProblem} /> : null}
      {!data.programsProblem && data.programs.items.length === 0 ? (
        <div className={styles.emptyState}><strong>暂无 Prompt 程序</strong></div>
      ) : null}

      {data.programs.items.length ? (
        <section className={styles.programSection} aria-labelledby="prompt-program-list-heading">
          <div className={styles.sectionHeading}>
            <h3 id="prompt-program-list-heading">程序列表</h3>
            <span>{data.programs.offset + 1}-{Math.min(data.programs.offset + data.programs.items.length, data.programs.total)} / {data.programs.total}</span>
          </div>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>用途</th><th>类型</th><th>所有者</th><th>操作</th></tr></thead>
              <tbody>{data.programs.items.map((program) => (
                <ProgramRow
                  active={program.id === data.selectedProgram?.id}
                  key={program.id}
                  program={program}
                  projectId={projectId}
                />
              ))}</tbody>
            </table>
          </div>
          <Pagination data={data} projectId={projectId} />
        </section>
      ) : null}

      {data.selectedProgram ? (
        <section className={styles.releaseSection} aria-labelledby="prompt-release-heading">
          <div className={styles.sectionHeading}>
            <div><p>{kindLabel(data.selectedProgram.program_kind)}</p><h3 id="prompt-release-heading">{data.selectedProgram.purpose}</h3></div>
            <code>{data.selectedProgram.id}</code>
          </div>
          <details className={styles.createSection}>
            <summary>创建下一版发布版本</summary>
            <PromptReleaseEditorForm
              catalog={data.bootstrap}
              disabled={!canContribute || latestReleaseVersion < 1 || data.selectedProgram.program_kind === "reference_translation"}
              expectedVersion={latestReleaseVersion}
              idempotencyKey={`admin-prompt-release-${randomUUID()}`}
              key={data.selectedProgram.id}
              mode="release"
              programId={data.selectedProgram.id}
              programKind={data.selectedProgram.program_kind}
              programPurpose={data.selectedProgram.purpose}
              projectId={projectId}
            />
          </details>
          {data.releasesProblem ? <LoadProblem label="发布版本列表" problem={data.releasesProblem} /> : null}
          {!data.releasesProblem && data.releases.items.length === 0 ? (
            <div className={styles.emptyState}><strong>此程序没有发布版本</strong></div>
          ) : null}
          {data.releases.items.length ? (
            <ReleaseTable
              items={data.releases.items}
              projectId={projectId}
              selectedReleaseId={data.selectedRelease?.id}
            />
          ) : null}
        </section>
      ) : null}

      {data.selectedRelease ? (
        <ReleaseDetail
          actorIdentityId={actorIdentityId}
          canApprove={canApprove}
          canContribute={canContribute}
          projectId={projectId}
          release={data.selectedRelease}
          releases={data.releases.items}
          runtimeOptions={data.testRuntimes}
          runtimeProblem={data.testRuntimesProblem}
          currentBinding={currentBinding}
          bindingProblem={data.bindingsProblem}
        />
      ) : data.selectedProgram && data.releases.items.length ? (
        <div className={styles.loadError} role="alert"><strong>所选发布版本不属于当前程序。</strong></div>
      ) : null}
    </div>
  );
}

function ProgramRow({
  active,
  program,
  projectId
}: {
  active: boolean;
  program: PromptProgramSummary;
  projectId: string;
}) {
  return (
    <tr className={active ? styles.activeRow : undefined}>
      <td><strong>{program.purpose}</strong><code>{program.id}</code></td>
      <td>{kindLabel(program.program_kind)}</td>
      <td><code>{program.owner_id}</code></td>
      <td><a className={styles.tableLink} href={workspaceHref(projectId, program.id)}>打开</a></td>
    </tr>
  );
}

function ReleaseTable({
  items,
  projectId,
  selectedReleaseId
}: {
  items: PromptProgramRelease[];
  projectId: string;
  selectedReleaseId?: string;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th>版本</th><th>状态</th><th>发布版本 SHA-256</th><th>模型策略</th><th>操作</th></tr></thead>
        <tbody>{items.map((release) => (
          <tr className={release.id === selectedReleaseId ? styles.activeRow : undefined} key={release.id}>
            <td><strong>v{release.version}</strong><code>{release.id}</code></td>
            <td><StatusPill value={release.state.status} /><small>状态 v{release.state.version}</small></td>
            <td><code>{release.release_hash}</code></td>
            <td><span>{release.model_policy_version}</span><code>{release.model_policy_hash}</code></td>
            <td><a className={styles.tableLink} href={workspaceHref(projectId, release.program_id, release.id)}>检查</a></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function ReleaseDetail({
  actorIdentityId,
  canApprove,
  canContribute,
  projectId,
  release,
  releases,
  runtimeOptions,
  runtimeProblem,
  currentBinding,
  bindingProblem
}: {
  actorIdentityId: string;
  canApprove: boolean;
  canContribute: boolean;
  projectId: string;
  release: PromptProgramRelease;
  releases: PromptProgramRelease[];
  runtimeOptions: PromptTestRuntimeOption[];
  runtimeProblem?: PromptLoadProblem;
  currentBinding: PromptProgramBindingOption | null;
  bindingProblem?: PromptLoadProblem;
}) {
  const baselines = releases.filter(
    (item) => item.version < release.version
      && (item.state.status === "approved" || item.state.status === "frozen")
  );
  return (
    <section className={styles.detailSection} aria-labelledby="prompt-release-detail-heading">
      <div className={styles.sectionHeading}>
        <div><p>发布版本溯源</p><h3 id="prompt-release-detail-heading">发布版本 v{release.version}</h3></div>
        <StatusPill value={release.state.status} />
      </div>
      <dl className={styles.lineageGrid}>
        <Lineage label="发布版本 SHA-256" value={release.release_hash} />
        <Lineage label="系统模板 SHA-256" value={release.system_template_hash} />
        <Lineage label="用户模板 SHA-256" value={release.user_template_hash} />
        <Lineage label="模型策略 SHA-256" value={release.model_policy_hash} />
        <Lineage label="变量 / 输入 / 输出" value={`${release.variable_schema_version} · ${release.input_schema_version} · ${release.output_schema_version}`} />
        <Lineage label="测试集" value={`${release.test_set_id} · v${release.test_set_version}`} />
        <Lineage label="编译器" value={release.compiler_version} />
        <Lineage label="状态操作人 / 时间" value={`${release.state.acted_by} · ${formatTime(release.state.acted_at)}`} />
        <Lineage label="证据引用" value={release.state.evidence_ref || "尚无"} />
      </dl>
      <PromptReleaseCommands
        actorIdentityId={actorIdentityId}
        baselineReleases={baselines}
        canApprove={canApprove}
        canContribute={canContribute}
        commandKeys={{
          approve: `admin-prompt-approve-${randomUUID()}`,
          bind: `admin-prompt-bind-${randomUUID()}`,
          diff: `admin-prompt-diff-${randomUUID()}`,
          freeze: `admin-prompt-freeze-${randomUUID()}`,
          retire: `admin-prompt-retire-${randomUUID()}`,
          test: `admin-prompt-test-${randomUUID()}`
        }}
        key={release.id}
        projectId={projectId}
        release={release}
        runtimeOptions={runtimeOptions}
        runtimeProblem={runtimeProblem}
        currentBinding={currentBinding}
        bindingProblem={bindingProblem}
      />
    </section>
  );
}

function Lineage({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd><code>{value}</code></dd></div>;
}

function Pagination({ data, projectId }: { data: PromptWorkspaceData; projectId: string }) {
  const previousOffset = Math.max(0, data.programs.offset - data.programs.limit);
  const nextOffset = data.programs.offset + data.programs.limit;
  return (
    <nav className={styles.pagination} aria-label="Prompt Program 分页">
      {data.programs.offset > 0
        ? <a href={pageHref(projectId, previousOffset, data.programs.limit)}>上一页</a>
        : <span aria-disabled="true">上一页</span>}
      <strong>第 {Math.floor(data.programs.offset / data.programs.limit) + 1} 页</strong>
      {nextOffset < data.programs.total
        ? <a href={pageHref(projectId, nextOffset, data.programs.limit)}>下一页</a>
        : <span aria-disabled="true">下一页</span>}
    </nav>
  );
}

function LoadProblem({ label, problem }: { label: string; problem: PromptLoadProblem }) {
  return (
    <div className={styles.loadError} role="alert">
      <strong>{problem.status ? `${problem.status} · ` : ""}{label}加载失败</strong>
      <span>{problem.detail}</span>
      {problem.correlationId ? <small>关联 ID：{problem.correlationId}</small> : null}
    </div>
  );
}

function StatusPill({ value }: { value: string }) {
  return <span className={`${styles.statusPill} ${styles[`status_${value}`] || ""}`}>{promptStatusLabel(value)}</span>;
}

function promptStatusLabel(value: string): string {
  return {
    draft: "草稿",
    tested: "已测试",
    approved: "已批准",
    frozen: "已冻结",
    retired: "已退役"
  }[value] || value;
}

function workspaceHref(projectId: string, programId: string, releaseId?: string): string {
  const params = new URLSearchParams({ tab: "prompts", prompt_program_id: programId });
  if (releaseId) params.set("prompt_release_id", releaseId);
  return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
}

function pageHref(projectId: string, offset: number, limit: number): string {
  const page = Math.floor(offset / limit) + 1;
  return `/projects/${encodeURIComponent(projectId)}?tab=prompts&prompt_page=${page}`;
}

function kindLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function roleLabel(value: ManagedMemberRole): string {
  if (value === "owner") return "负责人";
  if (value === "admin") return "管理员";
  return "分析师";
}

function formatTime(value: string): string {
  const time = new Date(value);
  return Number.isNaN(time.valueOf()) ? value : time.toLocaleString("zh-CN");
}
