import { randomUUID } from "node:crypto";

import type { ManagedMemberRole } from "../../memberTypes";
import {
  AuthorizationCommands,
  CreateAuthorizationForm,
  ProfileCommands,
  FreezeSuiteForm
} from "./SyntheticLabGovernanceForms";
import {
  CorpusOfflineExperimentForms,
  ReviewCaseRunForm,
  StyleCollectionAdmissionForm,
  StyleProfileBuildForm,
  SelectedJobControls
} from "./SyntheticLabJobForms";
import {
  CreateReviewCaseForm,
  CreateReviewSuiteForm,
  CreateStyleProfileForm,
  CreateStyleSourceForm,
  ManualImportApprovalForm,
  ManualSampleImportForm,
} from "./SyntheticLabResourceForms";
import type {
  ReviewCase,
  ReviewSuite,
  StyleProfile,
  StyleSource,
  SyntheticLoadProblem,
  SyntheticWorkspaceData
} from "./syntheticLabTypes";
import { SyntheticLabWarnings } from "./SyntheticLabWarnings";
import styles from "./SyntheticLab.module.css";

export function SyntheticLabWorkspace({
  actorIdentityId,
  currentRole,
  data,
  projectId
}: {
  actorIdentityId: string;
  currentRole: ManagedMemberRole | null;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  const problems = [
    data.authorizationsProblem,
    data.sourcesProblem,
    data.importPreviewsProblem,
    data.importPreviewProblem,
    data.inventoryProblem,
    data.runtimeOptionsProblem,
    data.loginSecretsProblem,
    data.profilesProblem,
    data.suitesProblem,
    data.casesProblem,
    data.jobProblem
  ].filter((problem): problem is SyntheticLoadProblem => Boolean(problem));
  const runtimeUnavailable = problems.some((problem) => problem.status === 503);
  const coreProjectionUnsafe = Boolean(
    data.authorizationsProblem || data.sourcesProblem || data.inventoryProblem
      || data.profilesProblem || data.suitesProblem
  );
  const canContribute = !coreProjectionUnsafe
    && (currentRole === "owner" || currentRole === "admin" || currentRole === "analyst");
  const canApprove = !coreProjectionUnsafe && (currentRole === "owner" || currentRole === "admin");
  const selectedSuite = data.suites.items.find((item) => item.id === data.selectedSuiteId) || null;
  return (
    <div className={styles.workspace} data-testid="synthetic-lab-workspace">
      <header className={styles.workspaceHeader}>
        <div><p>仅限管理员的测评环境</p><h2>合成测评实验室</h2></div>
        <div className={styles.summary}>
          <span><strong>{data.authorizations.total}</strong> 条授权</span>
          <span><strong>{data.sources.total}</strong> 个风格来源</span>
          <span><strong>{data.importPreviews.total}</strong> 个导入预览</span>
          <span><strong>{data.profiles.total}</strong> 个风格画像</span>
          <span><strong>{data.suites.total}</strong> 个测评套件</span>
        </div>
      </header>

      <SyntheticBoundaryBand />
      <SyntheticLabWarnings summary={data.selectedJob?.warning_summary} />

      {runtimeUnavailable ? (
        <div className={styles.unavailable} role="alert">
          <strong>合成测评实验室暂不可用</strong>
          <span>持久化运行时未连接，所有命令保持关闭。</span>
        </div>
      ) : null}
      {problems.map((problem, index) => <LoadProblem key={`${problem.detail}:${index}`} problem={problem} />)}

      <section className={styles.section} aria-labelledby="synthetic-authorization-heading">
        <div className={styles.sectionHeading}>
          <div><p>人工准入门禁</p><h3 id="synthetic-authorization-heading">采集授权</h3></div>
          <span>批准前不允许采集</span>
        </div>
        <details className={styles.createSection}><summary>新增待评估授权</summary><CreateAuthorizationForm canCreate={canApprove} commandKey={key("authorization-create")} projectId={projectId} /></details>
        {!data.authorizationsProblem && data.authorizations.items.length === 0
          ? <EmptyState text="暂无授权记录；在线采集必须保持关闭。" />
          : null}
        {data.authorizations.items.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>渠道 / 适配器</th><th>状态</th><th>限流</th><th>证据与版本</th><th>操作</th></tr></thead>
              <tbody>{data.authorizations.items.map((authorization) => (
                <tr key={authorization.id}>
                  <td><strong>{authorization.channel}</strong><code>{authorization.adapter_release}</code></td>
                  <td><Status value={authorization.effective_state} /></td>
                  <td>{authorization.max_requests_per_period ?? "-"} / {authorization.period_seconds ?? "-"}s<small>并发 {authorization.max_concurrency ?? "-"}</small></td>
                  <td><span>v{authorization.version_number}</span><code>{authorization.record_hash}</code><code>{authorization.evidence_reference_hash || "无证据"}</code></td>
                  <td><AuthorizationCommands authorization={authorization} canApprove={canApprove} canReassess={canContribute} commandKeys={{ decide: key("authorization-decide"), reassess: key("authorization-reassess"), revoke: key("authorization-revoke") }} projectId={projectId} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className={styles.section} aria-labelledby="synthetic-source-heading">
        <div className={styles.sectionHeading}>
          <div><p>受治理的风格采集</p><h3 id="synthetic-source-heading">风格来源与人工样本</h3></div>
          <span>澳洲英文 · 9 个渠道</span>
        </div>
        <details className={styles.createSection}><summary>新增风格来源</summary><CreateStyleSourceForm canContribute={canContribute} commandKey={key("source-create")} projectId={projectId} /></details>
        <details className={styles.createSection}><summary>排队自动风格采集</summary><StyleCollectionAdmissionForm authorizations={data.authorizations.items} canContribute={canContribute} commandKey={key("style-collection-admit")} loginSecrets={data.loginSecrets} projectId={projectId} sources={data.sources.items} /></details>
        <details className={styles.createSection}><summary>上传 text / CSV / JSONL</summary><ManualSampleImportForm canContribute={canContribute} commandKey={key("sample-import-preview")} projectId={projectId} sources={data.sources.items} /></details>
        {!data.sourcesProblem && data.sources.items.length === 0 ? <EmptyState text="暂无风格来源。" /> : null}
        {data.sources.items.length ? <StyleSourceTable items={data.sources.items} /> : null}
        {data.importPreviews.items.length ? <ImportPreviewTable items={data.importPreviews.items} projectId={projectId} /> : null}
        {data.selectedImportPreview ? <ManualImportApprovalForm actorIdentityId={actorIdentityId} canContribute={canContribute} commandKey={key("sample-import-approve")} preview={data.selectedImportPreview} projectId={projectId} /> : null}
      </section>

      <section className={styles.section} aria-labelledby="synthetic-profile-heading">
        <div className={styles.sectionHeading}>
          <div><p>已批准风格证据</p><h3 id="synthetic-profile-heading">风格画像</h3></div>
          <span>冻结门槛 ≥ 200 明审样本</span>
        </div>
        <details className={styles.createSection}><summary>创建风格画像草稿</summary><CreateStyleProfileForm canContribute={canContribute} commandKey={key("profile-create")} inventory={data.inventory} projectId={projectId} /></details>
        {!data.profilesProblem && data.profiles.items.length === 0 ? <EmptyState text="暂无风格画像。" /> : null}
        {data.profiles.items.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead><tr><th>渠道 / 风格画像</th><th>状态</th><th>样本</th><th>溯源哈希</th><th>操作</th></tr></thead>
              <tbody>{data.profiles.items.map((profile) => (
                <tr key={profile.id}>
                  <td><strong>{profile.channel} · v{profile.version_number}</strong><code>{profile.id}</code></td>
                  <td><Status value={profile.status} /></td>
                  <td>{profile.approved_sample_count}</td>
                  <td><code>{profile.corpus_hash}</code><code>{profile.profile_hash}</code><code>{profile.prompt_release_hash}</code></td>
                  <td>
                    <ProfileCommands canApprove={canApprove} canContribute={canContribute} commandKeys={{ decision: key("profile-decision"), freeze: key("profile-freeze"), submit: key("profile-submit") }} profile={profile} projectId={projectId} />
                    {profile.status === "draft" ? <StyleProfileBuildForm canContribute={canContribute && !data.runtimeOptionsProblem} commandKey={key("profile-build")} inventory={data.inventory} profile={profile} projectId={projectId} runtimes={data.runtimeOptions.items} /> : null}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className={styles.section} aria-labelledby="synthetic-suite-heading">
        <div className={styles.sectionHeading}>
          <div><p>固定回归合同</p><h3 id="synthetic-suite-heading">测评套件 / 用例</h3></div>
          <span>{data.selectedCases.total} 个已选用例</span>
        </div>
        <details className={styles.createSection}><summary>创建测评套件</summary><CreateReviewSuiteForm canContribute={canContribute} commandKey={key("suite-create")} projectId={projectId} /></details>
        {!data.suitesProblem && data.suites.items.length === 0 ? <EmptyState text="暂无测评套件。" /> : null}
        {data.suites.items.length ? <SuiteTable items={data.suites.items} projectId={projectId} selectedSuiteId={data.selectedSuiteId} /> : null}
        {selectedSuite ? (
          <div className={styles.selectedSuite}>
            <div className={styles.sectionHeading}><h4>{selectedSuite.channel} · 测评套件 v{selectedSuite.version_number}</h4><Status value={selectedSuite.status} /></div>
            <details className={styles.createSection}><summary>新增测评用例</summary><CreateReviewCaseForm canContribute={canContribute} commandKey={key("case-create")} inventory={data.inventory} projectId={projectId} suite={selectedSuite} /></details>
            {data.casesProblem ? null : data.selectedCases.items.length === 0 ? <EmptyState text="所选测评套件暂无用例。" /> : <CaseTable items={data.selectedCases.items} />}
            <FreezeSuiteForm canApprove={canApprove} cases={data.selectedCases.items} commandKey={key("suite-freeze")} projectId={projectId} suite={selectedSuite} />
            {selectedSuite.status === "frozen" ? <ReviewCaseRunForm canContribute={canContribute && !data.runtimeOptionsProblem} cases={data.selectedCases.items} commandKey={key("review-case-run")} projectId={projectId} runtimes={data.runtimeOptions.items} suite={selectedSuite} /> : null}
          </div>
        ) : <p className={styles.selectionHint}>打开一个测评套件后可管理用例与冻结清单。</p>}
      </section>

      <section className={styles.section} aria-labelledby="synthetic-job-heading">
        <div className={styles.sectionHeading}>
          <div><p>持久化任务 + Outbox</p><h3 id="synthetic-job-heading">生成、修订、语料与三臂实验</h3></div>
          <span>每批次冻结 Fact / Profile / Prompt</span>
        </div>
        <CorpusOfflineExperimentForms
          canApprove={canApprove}
          canContribute={canContribute && !data.runtimeOptionsProblem}
          commandKeys={{
            candidate: key("corpus-candidate"),
            approve: key("corpus-approve"),
            experiment: key("offline-experiment")
          }}
          inventory={data.inventory}
          projectId={projectId}
          runtimes={data.runtimeOptions.items}
        />
        {data.jobProblem ? null : data.selectedJob ? (
          <div className={styles.jobDetail}>
            <div className={styles.sectionHeading}><div><p>所选任务</p><h4>{data.selectedJob.kind}</h4></div><Status value={data.selectedJob.status} /></div>
            <dl className={styles.metadataGrid}>
              <Metadata label="任务 ID" value={data.selectedJob.id} />
              <Metadata label="版本" value={String(data.selectedJob.version)} />
              <Metadata label="输入哈希" value={data.selectedJob.input_hash} />
              <Metadata label="结果哈希" value={data.selectedJob.result_hash || "尚未完成"} />
              <Metadata label="围栏代次" value={String(data.selectedJob.fencing_generation)} />
              <Metadata label="已请求取消" value={String(data.selectedJob.cancel_requested)} />
            </dl>
            <SelectedJobControls canContribute={canContribute} commandKey={key("job-cancel")} job={data.selectedJob} projectId={projectId} />
          </div>
        ) : <EmptyState text="尚未选择任务；提交任务后可打开其状态页。" />}
      </section>
    </div>
  );
}

export function SyntheticLabLoading() {
  return (
    <div className={styles.workspace} aria-busy="true">
      <header className={styles.workspaceHeader}><div><p>仅限管理员的测评环境</p><h2>合成测评实验室</h2></div><span>正在加载...</span></header>
      <SyntheticBoundaryBand />
      <SyntheticLabWarnings />
    </div>
  );
}

function SyntheticBoundaryBand() {
  return (
    <section className={styles.boundaryBand} aria-label="合成测评实验室安全边界">
      <strong>仅限内部合成证据</strong>
      <code>synthetic = true</code><code>test_only = true</code><code>publication_eligible = false</code>
      <span>客户门户不读取、不展示且不可发布这些结果。</span>
    </section>
  );
}

function StyleSourceTable({ items }: { items: StyleSource[] }) {
  return <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>渠道</th><th>访问方式</th><th>状态</th><th>修订</th><th>定位哈希</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.channel}</strong><code>{item.id}</code></td><td>{accessModeLabel(item.access_mode)}</td><td><Status value={item.status} /></td><td>r{item.revision_number}</td><td><code>{item.source_locator_hash}</code></td></tr>)}</tbody></table></div>;
}

function ImportPreviewTable({ items, projectId }: { items: SyntheticWorkspaceData["importPreviews"]["items"]; projectId: string }) {
  return <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>文件</th><th>状态</th><th>行</th><th>可选 / 阻断</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.filename}</strong><small>{item.channel} · {item.import_format}</small></td><td><Status value={item.status} /></td><td>{item.row_count}</td><td>{item.selectable_count} / {item.blocked_count}</td><td><a className={styles.resultLink} href={syntheticHref(projectId, { synthetic_import_preview_id: item.id })}>复核</a></td></tr>)}</tbody></table></div>;
}

function SuiteTable({ items, projectId, selectedSuiteId }: { items: ReviewSuite[]; projectId: string; selectedSuiteId: string | null }) {
  return <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>渠道 / 测评套件</th><th>状态</th><th>用例</th><th>用例集哈希</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr className={item.id === selectedSuiteId ? styles.activeRow : undefined} key={item.id}><td><strong>{item.channel} · v{item.version_number}</strong><code>{item.id}</code></td><td><Status value={item.status} /></td><td>{item.case_count}</td><td><code>{item.case_set_hash}</code></td><td><a className={styles.resultLink} href={syntheticHref(projectId, { synthetic_suite_id: item.id })}>打开</a></td></tr>)}</tbody></table></div>;
}

function CaseTable({ items }: { items: ReviewCase[] }) {
  return <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>用例</th><th>模式</th><th>渠道</th><th>竞品</th><th>内容哈希</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.ordinal} · {item.case_key}</strong><code>{item.id}</code></td><td>{caseModeLabel(item.mode)}</td><td>{item.channel}</td><td>{item.competitor_scenario ? "是" : "否"}</td><td><code>{item.content_hash}</code></td></tr>)}</tbody></table></div>;
}

function Status({ value }: { value: string }) {
  return <span className={`${styles.statusPill} ${styles[`status_${value}`] || ""}`}>{statusLabel(value)}</span>;
}

function statusLabel(value: string): string {
  return {
    active: "启用",
    draft: "草稿",
    pending: "待处理",
    pending_review: "待审核",
    in_review: "审核中",
    approved: "已批准",
    frozen: "已冻结",
    queued: "排队中",
    running: "运行中",
    succeeded: "成功",
    passed: "通过",
    completed_with_warning: "警告完成",
    failed: "失败",
    cancelled: "已取消",
    revoked: "已撤销"
  }[value] || value;
}

function accessModeLabel(value: string): string {
  return { public: "公开", authenticated: "已登录", manual_import: "人工导入" }[value] || value;
}

function caseModeLabel(value: string): string {
  return { autonomous_scenario: "自主场景", guided_scenario: "引导场景" }[value] || value;
}

function Metadata({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd><code>{value}</code></dd></div>;
}

function EmptyState({ text }: { text: string }) {
  return <div className={styles.emptyState}><strong>{text}</strong></div>;
}

function LoadProblem({ problem }: { problem: SyntheticLoadProblem }) {
  return <div className={styles.loadError} role="alert"><strong>{problem.status ? `${problem.status} · ` : ""}加载失败</strong><span>{problem.detail}</span>{problem.correlationId ? <small>关联 ID：{problem.correlationId}</small> : null}</div>;
}

function key(scope: string): string {
  return `synthetic-${scope}-${randomUUID()}`;
}

function syntheticHref(projectId: string, values: Record<string, string>): string {
  const query = new URLSearchParams({ tab: "synthetic-lab", ...values });
  return `/projects/${encodeURIComponent(projectId)}?${query.toString()}`;
}
