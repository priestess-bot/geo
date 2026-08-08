import {
  EmptyState,
  Fact,
  LoadProblem,
  SectionHeading,
  captureLabel
} from "./WorkflowCWorkspace";
import { SamplingCommands, type SamplingCommandKeys } from "./SamplingCommands";
import { ManualEvidenceCommands } from "./ManualEvidenceCommands";
import { ConsumerSurfaceCaptureSetup } from "./ConsumerSurfaceCaptureSetup";
import type { QuestionWorkspaceData } from "./questionWorkspaceData";
import type {
  AdmissionPolicyPage,
  AdmissionRuntimeOptionPage,
  BrowserCaptureInventory,
  BrowserCaptureReadiness,
  ManualEvidenceImportPage,
  Resource,
  SamplingRun,
  SamplingRunDetail,
  SamplingSuite,
  SamplingSuiteInputOption,
  SurfaceParserReleasePage
} from "./workflowCTypes";
import styles from "./WorkflowC.module.css";

export function SamplingPanel({
  admissionPolicies,
  admissionRuntimeOptions,
  browserCaptureInventory,
  browserCaptureReadiness,
  canOperate,
  canReview,
  commandKeys,
  manualCommandKey,
  manualEvidence,
  questionWorkspace,
  actorId,
  projectId,
  requestedNotBefore,
  resource,
  runs,
  surfaceParserReleases,
  suite,
  suiteInputOptions,
  suites
}: {
  admissionPolicies: Resource<AdmissionPolicyPage>;
  admissionRuntimeOptions: Resource<AdmissionRuntimeOptionPage>;
  browserCaptureInventory: Resource<BrowserCaptureInventory>;
  browserCaptureReadiness: Resource<BrowserCaptureReadiness>;
  actorId: string;
  canOperate: boolean;
  canReview: boolean;
  commandKeys: SamplingCommandKeys;
  manualCommandKey: string;
  manualEvidence: Resource<ManualEvidenceImportPage>;
  questionWorkspace: QuestionWorkspaceData | null;
  projectId: string;
  requestedNotBefore: string;
  resource: Resource<SamplingRunDetail>;
  runs: Resource<{ items: SamplingRun[]; total: number }>;
  surfaceParserReleases: Resource<SurfaceParserReleasePage>;
  suite: Resource<SamplingSuite>;
  suiteInputOptions: Resource<{ items: SamplingSuiteInputOption[]; total: number }>;
  suites: Resource<{ items: SamplingSuite[]; total: number }>;
}) {
  const commands = (
    <>
      <ConsumerSurfaceCaptureSetup
        admissionPolicies={admissionPolicies.data?.items || []}
        admissionRuntimeOptions={admissionRuntimeOptions.data?.items || []}
        canOperate={canOperate}
        inventory={browserCaptureInventory}
        projectId={projectId}
        questionSets={questionWorkspace?.questionSets.data || []}
        readiness={browserCaptureReadiness}
        suiteInputOptions={suiteInputOptions.data?.items || []}
      />
      <SamplingCommands
        admissionPolicies={admissionPolicies.data?.items || []}
        canOperate={canOperate}
        commandKeys={commandKeys}
        projectId={projectId}
        requestedNotBefore={requestedNotBefore}
        runs={runs.data?.items || []}
        selectedRun={resource.data?.run || null}
        suiteInputOptions={suiteInputOptions.data?.items || []}
        suites={suites.data?.items || []}
      />
      <ManualEvidenceCommands
        actorId={actorId}
        canOperate={canOperate}
        canReview={canReview}
        capturedAt={requestedNotBefore}
        commandKey={manualCommandKey}
        imports={manualEvidence.data?.items || []}
        projectId={projectId}
        runId={resource.data?.run.id || null}
        releases={surfaceParserReleases.data?.items || []}
        source={resource.data?.suite.source_stratum || suite.data?.source_stratum || null}
        tasks={resource.data?.tasks || []}
      />
      {surfaceParserReleases.problem
        ? <LoadProblem label="消费者界面解析器发布版本" problem={surfaceParserReleases.problem} />
        : null}
    </>
  );
  if (resource.problem) return <div className={styles.sectionStack}>{commands}<LoadProblem label="采样运行" problem={resource.problem} /></div>;
  if (!resource.data) {
    return (
      <div className={styles.sectionStack}>
        {commands}
        <section>
          <SectionHeading eyebrow="采样" title="运行清单" />
          {suite.problem ? <LoadProblem label="采样套件" problem={suite.problem} /> : null}
          {suiteInputOptions.problem ? <LoadProblem label="采样套件选项" problem={suiteInputOptions.problem} /> : null}
          {suites.problem ? <LoadProblem label="采样套件列表" problem={suites.problem} /> : null}
          {runs.problem ? <LoadProblem label="采样运行列表" problem={runs.problem} /> : null}
          {suite.data ? <SuiteFacts suite={suite.data} /> : <EmptyState title="未选择采样运行" />}
        </section>
      </div>
    );
  }
  const data = resource.data;
  const assessment = data.assessment;
  const observations = new Map(data.observations.map((item) => [item.task_id, item]));
  return (
    <div className={styles.sectionStack}>
      {commands}
      <section>
        <SectionHeading eyebrow="采样" title={`运行 ${data.run.id}`} />
        <div className={styles.denominatorBand}>
          <Denominator label="已规划" value={assessment.planned_task_count} />
          <Denominator label="有效" value={assessment.valid_task_count} tone="good" />
          <Denominator label="无效" value={assessment.invalid_task_count} tone="bad" />
          <Denominator label="缺失" value={assessment.missing_task_count} tone="warning" />
          <Denominator label="有效完成度" value={percent(assessment.valid_completion_ratio)} />
        </div>
        <div className={styles.resultBanner} data-status={assessment.status}>
          <strong>{assessment.status === "complete" ? "证据完整" : "证据不足"}</strong>
          <span>{assessment.sufficient_question_count} / {assessment.question_count} 个问题满足冻结重复下限</span>
        </div>
        <dl className={styles.compactFacts}>
          <Fact label="分母 SHA-256" value={assessment.denominator_hash} />
          <Fact label="运行准入 SHA-256" value={data.run.admission_grant_hash} />
          <Fact label="准入策略" value={data.run.admission_policy_id} />
          <Fact label="策略 SHA-256" value={data.run.admission_policy_hash} />
          <Fact label="授权有效至" value={formatTime(data.run.authorization_valid_until)} />
          <Fact label="统计方法" value={data.suite.statistics_method_version} />
        </dl>
        <SuiteFacts suite={data.suite} />
      </section>

      <section>
        <SectionHeading eyebrow="已规划分母" title="任务" />
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead><tr><th>问题</th><th>重复</th><th>采集方式</th><th>状态</th><th>尝试</th><th>证据</th><th>任务键</th></tr></thead>
            <tbody>{data.tasks.map((task) => {
              const observation = observations.get(task.id);
              return (
                <tr key={task.id}>
                  <td><strong>{task.question_id}</strong><small>{task.question_version}</small></td>
                  <td>{task.repetition}</td>
                  <td>{captureLabel(task.capture_method)}</td>
                  <td><Status value={task.status} /></td>
                  <td>{task.attempt_ids.length} / {task.max_attempts}</td>
                  <td>{observation ? <Status value={observation.evidence_status} /> : "缺失"}</td>
                  <td><code>{task.task_key}</code></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      </section>

      <section>
        <SectionHeading eyebrow="执行溯源" title="尝试" />
        {data.attempts.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.dataTable}>
              <thead><tr><th>尝试</th><th>任务</th><th>序号</th><th>记录</th><th>调用数</th><th>Provider 响应</th><th>实际位置</th></tr></thead>
              <tbody>{data.attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td><code>{attempt.id}</code></td>
                  <td><Status value={attempt.job_status} /></td>
                  <td>{attempt.ordinal}</td>
                  <td>v{attempt.record_version}</td>
                  <td>{attempt.attempt_count}</td>
                  <td><code>{attempt.provider_response_id || "-"}</code></td>
                  <td>{attempt.actual_location ? <><strong>{attempt.actual_location.location_control}</strong><small>{actualLocation(attempt.actual_location)}</small><code>{attempt.actual_location.location_evidence_hash}</code></> : "-"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <EmptyState title="尝试尚未创建" />}
      </section>

      <section>
        <SectionHeading eyebrow="胜出证据" title="观察记录" />
        {data.observations.length ? (
          <div className={styles.observationList}>
            {data.observations.map((observation) => (
              <article key={observation.id}>
                <header><div><strong>{observation.task_key}</strong><small>{formatTime(observation.observed_at)}</small></div><Status value={observation.evidence_status} /></header>
                <p>{observation.evidence.derived_summary}</p>
                {observation.ineligible_reasons.length ? <ul>{observation.ineligible_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : null}
                <dl className={styles.compactFacts}>
                  <Fact label="胜出尝试" value={observation.winning_attempt_id} />
                  <Fact label="观察记录 SHA-256" value={observation.observation_hash} />
                  <Fact label="参数 SHA-256" value={observation.evidence.result_parameters_hash} />
                  <Fact label="证据定位" value={observation.evidence.evidence_locator} />
                  <Fact label="原始清单 SHA-256" value={observation.evidence.raw_manifest_hash} />
                  <Fact label="派生清单 SHA-256" value={observation.evidence.derived_manifest_hash} />
                  <Fact label="实际位置" value={observation.actual_location ? actualLocation(observation.actual_location) : "-"} />
                </dl>
              </article>
            ))}
          </div>
        ) : <EmptyState title="观察记录尚未形成" />}
      </section>
    </div>
  );
}

function SuiteFacts({ suite }: { suite: SamplingSuite }) {
  const source = suite.source_stratum;
  return (
    <dl className={styles.factGrid}>
      <Fact label="采样套件" value={suite.id} />
      <Fact label="问题集" value={suite.question_set_id} />
      <Fact label="采集方式" value={captureLabel(source.capture_method)} />
      <Fact label="界面" value={`${source.platform} / ${source.surface}`} />
      <Fact label="模型" value={`${source.configured_model} / ${source.reported_model}`} />
      <Fact label="区域设置" value={`${source.locale} · ${source.region} · ${source.language}`} />
      <Fact label="适配器" value={source.adapter_release} />
      <Fact label="来源分层 SHA-256" value={source.stratum_hash} />
      <Fact label="采样套件 SHA-256" value={suite.suite_hash} />
      <Fact label="冻结信息" value={`${formatTime(suite.frozen_at)} · ${suite.frozen_by}`} />
    </dl>
  );
}

function Denominator({ label, tone, value }: { label: string; tone?: string; value: string | number }) {
  return <div data-tone={tone}><span>{label}</span><strong>{value}</strong></div>;
}

function Status({ value }: { value: string }) {
  return <span className={styles.status} data-status={value}>{statusLabel(value)}</span>;
}

function statusLabel(value: string): string {
  return { planned: "已规划", pending: "待处理", running: "运行中", complete: "已完成", completed: "已完成", failed: "失败", cancelled: "已取消", valid: "有效", invalid: "无效", missing: "缺失", eligible: "合格", ineligible: "不合格" }[value] || value.replaceAll("_", " ");
}

function percent(value: string): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : value;
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}

function actualLocation(value: {
  effective_country: string | null;
  effective_region: string | null;
  effective_locale: string | null;
  effective_language: string | null;
}): string {
  return [
    value.effective_country,
    value.effective_region,
    value.effective_locale,
    value.effective_language
  ].filter(Boolean).join(" · ") || "未受控";
}
