import { randomUUID } from "node:crypto";

import { AdmissionPolicyPanel } from "./AdmissionPolicyPanel";
import { AlertInbox } from "./AlertInbox";
import {
  ComparisonPanel,
  DriftPanel,
  MetricsPanel
} from "./AnalysisPanels";
import { SamplingPanel } from "./SamplingPanel";
import { ProtocolsPanel, ReportsPanel } from "./WorkflowCControlPanels";
import { workflowCHref } from "./workflowCData";
import {
  workflowViews,
  type WorkflowCWorkspaceData,
  type WorkflowView
} from "./workflowCTypes";
import styles from "./WorkflowC.module.css";
import panelStyles from "./WorkflowCPanel.module.css";

export type WorkflowCPanelProps = Readonly<{
  data: WorkflowCWorkspaceData;
  projectId: string;
}>;

export function WorkflowCWorkspace(props: WorkflowCPanelProps) {
  return (
    <main className={styles.shell}>
      <WorkflowCContents {...props} standalone />
    </main>
  );
}

export function WorkflowCPanel(props: WorkflowCPanelProps) {
  return (
    <div className={panelStyles.embeddedPanel}>
      <WorkflowCContents {...props} standalone={false} />
    </div>
  );
}

function WorkflowCContents({
  data,
  projectId,
  standalone
}: WorkflowCPanelProps & { standalone: boolean }) {
  const assessment = data.run.data?.assessment;
  const selectedAlert = data.alerts.data?.items.find(
    (item) => item.id === data.selection.alertId
  ) || null;
  const canAct = !data.alerts.problem && (
    data.currentRole === "owner"
    || data.currentRole === "admin"
    || data.currentRole === "analyst"
  );
  const canManagePolicies = !data.admissionPolicies.problem && (
    data.currentRole === "owner" || data.currentRole === "admin"
  );
  const canOperateSampling = !data.suites.problem && !data.runs.problem && (
    data.currentRole === "owner"
    || data.currentRole === "admin"
    || data.currentRole === "analyst"
  );
  const canReviewManualEvidence = !data.manualEvidence.problem && (
    data.currentRole === "owner" || data.currentRole === "admin"
  );
  const hasManagerRole = data.currentRole === "owner" || data.currentRole === "admin";
  const canManageProtocols = !data.metricProtocols.problem
    && !data.statisticalProtocols.problem
    && hasManagerRole;
  const canManageReports = !data.workflowCReports.problem
    && !data.metricSnapshots.problem
    && hasManagerRole;
  const canEnqueueAnalysis = !data.metricProtocols.problem
    && !data.statisticalProtocols.problem
    && !data.runs.problem
    && !data.metricSnapshots.problem
    && (
      data.currentRole === "owner"
      || data.currentRole === "admin"
      || data.currentRole === "analyst"
    );
  const now = new Date();
  const suppression = new Date(now.valueOf() + 60 * 60 * 1000);
  const commandKeys = {
    acknowledge: `workflow-c-alert-ack-${randomUUID()}`,
    suppress: `workflow-c-alert-suppress-${randomUUID()}`,
    unsuppress: `workflow-c-alert-unsuppress-${randomUUID()}`,
    resolve: `workflow-c-alert-resolve-${randomUUID()}`
  };
  const policyCommandKeys = {
    create: `workflow-c-policy-create-${randomUUID()}`,
    submit: `workflow-c-policy-submit-${randomUUID()}`,
    approve: `workflow-c-policy-approve-${randomUUID()}`,
    assessNoBasis: `workflow-c-policy-no-basis-${randomUUID()}`,
    revoke: `workflow-c-policy-revoke-${randomUUID()}`
  };
  const samplingCommandKeys = {
    createSuite: `workflow-c-suite-create-${randomUUID()}`,
    startRun: `workflow-c-run-start-${randomUUID()}`,
    enqueueRun: `workflow-c-run-enqueue-${randomUUID()}`,
    cancelRun: `workflow-c-run-cancel-${randomUUID()}`
  };

  return (
    <>
      <header className={standalone ? styles.header : panelStyles.panelHeader}>
        <div>
          <p className={styles.kicker}>GEO 测量控制台</p>
          {standalone
            ? <h1>采样、证据与告警</h1>
            : <h2>采样、证据与告警</h2>}
          <div className={styles.headerMeta}>
            <span>项目 <code>{projectId}</code></span>
            <span>{roleLabel(data.currentRole)}</span>
          </div>
        </div>
        {standalone ? (
          <nav className={styles.headerActions} aria-label="页面导航">
            <a href={`/projects/${encodeURIComponent(projectId)}`}>返回项目</a>
            <a href="/projects">项目列表</a>
          </nav>
        ) : null}
      </header>

      {data.alerts.problem ? (
        <div className={panelStyles.controlGate}>
          <LoadProblem label="Workflow C 控制平面" problem={data.alerts.problem} />
        </div>
      ) : null}

      <section className={styles.summaryBand} aria-label="当前运行摘要">
        <Summary label="已规划" value={assessment?.planned_task_count ?? "-"} />
        <Summary label="有效" value={assessment?.valid_task_count ?? "-"} tone="good" />
        <Summary label="无效" value={assessment?.invalid_task_count ?? "-"} tone="bad" />
        <Summary label="缺失" value={assessment?.missing_task_count ?? "-"} tone="warning" />
        <Summary
          label="证据"
          value={assessment ? evidenceLabel(assessment.status) : "未选择"}
          tone={assessment?.status === "complete" ? "good" : "warning"}
        />
        <Summary
          label="活动告警"
          value={data.alerts.data?.items.filter((item) => item.status !== "resolved").length ?? "-"}
          tone="bad"
        />
      </section>

      <ResourceSelector data={data} projectId={projectId} />

      <nav className={styles.viewTabs} aria-label="测量视图">
        {workflowViews.map((view) => (
          <a
            aria-current={data.activeView === view ? "page" : undefined}
            className={data.activeView === view ? styles.activeTab : undefined}
            href={workflowCHref(projectId, data.selection, view)}
            key={view}
          >
            {viewLabel(view)}
          </a>
        ))}
      </nav>

      <div className={styles.workspace}>
        {data.activeView === "overview" ? <Overview data={data} /> : null}
        {data.activeView === "admission" ? (
          <AdmissionPolicyPanel
            actorId={data.actorId}
            canManage={canManagePolicies}
            commandKeys={policyCommandKeys}
            policies={data.admissionPolicies}
            projectId={projectId}
            runtimeOptions={data.admissionRuntimeOptions}
            selectedPolicyId={data.selection.policyId}
            selection={data.selection}
            validUntilDefault={localDateTime(new Date(now.valueOf() + 30 * 24 * 60 * 60 * 1000))}
          />
        ) : null}
        {data.activeView === "sampling" ? (
          <SamplingPanel
            actorId={data.actorId}
            admissionPolicies={data.admissionPolicies}
            canOperate={canOperateSampling}
            canReview={canReviewManualEvidence}
            commandKeys={samplingCommandKeys}
            manualCommandKey={`workflow-c-manual-${randomUUID()}`}
            manualEvidence={data.manualEvidence}
            projectId={projectId}
            requestedNotBefore={localDateTime(now)}
            resource={data.run}
            runs={data.runs}
            surfaceParserReleases={data.surfaceParserReleases}
            suite={data.suite}
            suiteInputOptions={data.suiteInputOptions}
            suites={data.suites}
          />
        ) : null}
        {data.activeView === "protocols" ? (
          <ProtocolsPanel
            canAnalyze={canEnqueueAnalysis}
            canManage={canManageProtocols}
            data={data}
            projectId={projectId}
          />
        ) : null}
        {data.activeView === "metrics" ? <MetricsPanel resource={data.metrics} /> : null}
        {data.activeView === "comparisons" ? <ComparisonPanel resource={data.comparisons} /> : null}
        {data.activeView === "drift" ? <DriftPanel resource={data.drift} /> : null}
        {data.activeView === "reports" ? (
          <ReportsPanel canManage={canManageReports} data={data} projectId={projectId} />
        ) : null}
        {data.activeView === "alerts" ? (
          <AlertInbox
            alerts={data.alerts}
            canAct={canAct}
            commandKeys={commandKeys}
            notifications={data.notifications}
            projectId={projectId}
            selected={selectedAlert}
            selection={data.selection}
            suppressionDefault={localDateTime(suppression)}
          />
        ) : null}
      </div>
    </>
  );
}

function Overview({ data }: { data: WorkflowCWorkspaceData }) {
  const run = data.run.data;
  const metrics = data.metrics.data;
  const comparisons = data.comparisons.data;
  const drift = data.drift.data;
  return (
    <div className={styles.overviewGrid}>
      <section className={styles.overviewPrimary}>
        <SectionHeading eyebrow="采样运行" title={run ? `运行 ${shortId(run.run.id)}` : "未选择运行"} />
        {data.run.problem ? <LoadProblem label="采样运行" problem={data.run.problem} /> : null}
        {run ? (
          <dl className={styles.factGrid}>
            <Fact label="状态" value={run.run.status} />
            <Fact label="采集方式" value={captureLabel(run.suite.source_stratum.capture_method)} />
            <Fact label="完成度" value={percent(run.assessment.valid_completion_ratio)} />
            <Fact label="有效问题" value={`${run.assessment.sufficient_question_count} / ${run.assessment.question_count}`} />
            <Fact label="适配器" value={run.suite.source_stratum.adapter_release} />
            <Fact label="分母 SHA-256" value={run.assessment.denominator_hash} />
          </dl>
        ) : <EmptyState title="采样运行未加载" />}
      </section>
      <section>
        <SectionHeading eyebrow="证据质量" title="结果门禁" />
        <div className={styles.signalList}>
          <Signal label="语义指标" value={metrics ? `${metrics.results.length} 项指标` : "未选择"} />
          <Signal label="最差问题" value={metrics?.performance.worst_question_id || "-"} />
          <Signal label="比较结论" value={comparisons?.results[0] ? conclusionLabel(comparisons.results[0].conclusion) : "未选择"} />
          <Signal label="漂移信号" value={drift ? String(drift.model_drift.length + drift.source_drift.length + drift.effect_drift.length) : "未选择"} />
          <Signal label="告警" value={String(data.alerts.data?.total ?? 0)} />
        </div>
      </section>
    </div>
  );
}

function ResourceSelector({ data, projectId }: { data: WorkflowCWorkspaceData; projectId: string }) {
  return (
    <details className={styles.resourceSelector}>
      <summary>资源定位</summary>
      <form action={`/projects/${encodeURIComponent(projectId)}/workflow-c`} method="get">
        <input name="workflow_view" type="hidden" value={data.activeView} />
        <ResourceSelect
          defaultValue={data.selection.suiteId}
          label="采样套件"
          name="suite_id"
          options={(data.suites.data?.items || []).map((item) => ({
            label: `${item.source_stratum.platform} · ${shortId(item.id)} · ${item.planned_task_count} 项任务`,
            value: item.id
          }))}
        />
        <ResourceSelect
          defaultValue={data.selection.runId}
          label="采样运行"
          name="run_id"
          options={(data.runs.data?.items || []).map((item) => ({
            label: `${item.status} · ${shortId(item.id)} · ${item.reserved_task_count} 项任务`,
            value: item.id
          }))}
        />
        <ResourceSelect
          defaultValue={data.selection.snapshotHash}
          label="指标快照"
          name="metric_snapshot"
          options={(data.metricSnapshots.data?.items || []).map((item) => ({
            label: `${formatResourceTime(item.computed_at)} · ${shortHash(item.snapshot_hash)}`,
            value: item.snapshot_hash
          }))}
        />
        <ResourceSelect
          defaultValue={data.selection.familyHash}
          label="比较族"
          name="comparison_family"
          options={(data.comparisonFamilies.data?.items || []).map((item) => ({
            label: `${item.family} · ${shortHash(item.family_hash)}`,
            value: item.family_hash
          }))}
        />
        <ResourceSelect
          defaultValue={data.selection.driftHash}
          label="漂移报告"
          name="drift_report"
          options={(data.driftReports.data?.items || []).map((item) => ({
            label: `${item.method_version} · ${shortHash(item.report_hash)}`,
            value: item.report_hash
          }))}
        />
        <ResourceSelect
          defaultValue={data.selection.alertId}
          label="告警"
          name="alert_id"
          options={(data.alerts.data?.items || []).map((item) => ({
            label: `${item.status} · ${item.rule.rule_key} · ${shortId(item.id)}`,
            value: item.id
          }))}
        />
        <ResourceSelect
          defaultValue={data.selection.policyId}
          label="准入策略"
          name="policy_id"
          options={(data.admissionPolicies.data?.items || []).map((item) => ({
            label: `${item.platform} · r${item.revision} · ${item.status}`,
            value: item.id
          }))}
        />
        <button type="submit">加载</button>
      </form>
    </details>
  );
}

function ResourceSelect({
  defaultValue,
  label,
  name,
  options
}: {
  defaultValue?: string;
  label: string;
  name: string;
  options: Array<{ label: string; value: string }>;
}) {
  return (
    <label>
      <span>{label}</span>
      <select defaultValue={defaultValue || ""} name={name}>
        <option value="">未选择</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

export function LoadProblem({ label, problem }: { label: string; problem: { status?: number; detail: string; correlationId?: string } }) {
  return (
    <div className={styles.loadProblem} role="alert">
      <strong>{problem.status ? `${problem.status} · ` : ""}{label}加载失败</strong>
      <span>{problem.detail}</span>
      {problem.correlationId ? <small>关联 ID：{problem.correlationId}</small> : null}
    </div>
  );
}

export function EmptyState({ title }: { title: string }) {
  return <div className={styles.emptyState}><strong>{title}</strong><span>暂无可展示记录。</span></div>;
}

export function SectionHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
  return <div className={styles.sectionHeading}><div><p>{eyebrow}</p><h2>{title}</h2></div></div>;
}

export function Fact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function Summary({ label, tone, value }: { label: string; tone?: "good" | "warning" | "bad"; value: string | number }) {
  return <div className={tone ? styles[`summary_${tone}`] : undefined}><span>{label}</span><strong>{value}</strong></div>;
}

function Signal({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

export function captureLabel(value: string): string {
  if (value === "provider_api") return "Provider API";
  if (value === "proxy_grounded_api") return "代理接地 API";
  if (value === "manual_ui") return "人工界面";
  return value;
}

export function conclusionLabel(value: string): string {
  if (value === "win") return "胜出";
  if (value === "loss") return "负向";
  if (value === "equivalent") return "达到等效门槛";
  if (value === "inconclusive") return "不确定";
  return "证据不足";
}

function viewLabel(view: WorkflowView): string {
  return {
    overview: "总览",
    admission: "授权策略",
    sampling: "采样",
    protocols: "协议与任务",
    metrics: "指标",
    comparisons: "比较",
    drift: "漂移",
    reports: "报告",
    alerts: "告警"
  }[view];
}

function evidenceLabel(value: string): string {
  return value === "complete" ? "可判定" : "证据不足";
}

function roleLabel(value: WorkflowCWorkspaceData["currentRole"]): string {
  if (value === "owner") return "负责人";
  if (value === "admin") return "管理员";
  if (value === "analyst") return "分析师";
  if (value === "viewer") return "只读";
  return "未授权";
}

function percent(value: string): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : value;
}

function shortId(value: string): string {
  return value.length > 13 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

function shortHash(value: string): string {
  return value.length > 15 ? `${value.slice(0, 10)}...${value.slice(-5)}` : value;
}

function formatResourceTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}

function localDateTime(value: Date): string {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.valueOf() - offset).toISOString().slice(0, 16);
}
