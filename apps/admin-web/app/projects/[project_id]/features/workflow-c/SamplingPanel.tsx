import {
  EmptyState,
  Fact,
  LoadProblem,
  SectionHeading,
  captureLabel
} from "./WorkflowCWorkspace";
import { SamplingCommands, type SamplingCommandKeys } from "./SamplingCommands";
import { ManualEvidenceCommands } from "./ManualEvidenceCommands";
import type {
  AdmissionPolicyPage,
  ManualEvidenceImportPage,
  Resource,
  SamplingRun,
  SamplingRunDetail,
  SamplingSuite,
  SamplingSuiteInputOption
} from "./workflowCTypes";
import styles from "./WorkflowC.module.css";

export function SamplingPanel({
  admissionPolicies,
  canOperate,
  canReview,
  commandKeys,
  manualCommandKey,
  manualEvidence,
  actorId,
  projectId,
  requestedNotBefore,
  resource,
  runs,
  suite,
  suiteInputOptions,
  suites
}: {
  admissionPolicies: Resource<AdmissionPolicyPage>;
  actorId: string;
  canOperate: boolean;
  canReview: boolean;
  commandKeys: SamplingCommandKeys;
  manualCommandKey: string;
  manualEvidence: Resource<ManualEvidenceImportPage>;
  projectId: string;
  requestedNotBefore: string;
  resource: Resource<SamplingRunDetail>;
  runs: Resource<{ items: SamplingRun[]; total: number }>;
  suite: Resource<SamplingSuite>;
  suiteInputOptions: Resource<{ items: SamplingSuiteInputOption[]; total: number }>;
  suites: Resource<{ items: SamplingSuite[]; total: number }>;
}) {
  const commands = (
    <>
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
        tasks={resource.data?.tasks || []}
      />
    </>
  );
  if (resource.problem) return <div className={styles.sectionStack}>{commands}<LoadProblem label="Sampling Run" problem={resource.problem} /></div>;
  if (!resource.data) {
    return (
      <div className={styles.sectionStack}>
        {commands}
        <section>
          <SectionHeading eyebrow="Sampling" title="Run inventory" />
          {suite.problem ? <LoadProblem label="Sampling Suite" problem={suite.problem} /> : null}
          {suiteInputOptions.problem ? <LoadProblem label="Sampling Suite options" problem={suiteInputOptions.problem} /> : null}
          {suites.problem ? <LoadProblem label="Sampling Suites" problem={suites.problem} /> : null}
          {runs.problem ? <LoadProblem label="Sampling Runs" problem={runs.problem} /> : null}
          {suite.data ? <SuiteFacts suite={suite.data} /> : <EmptyState title="Sampling Run 未选择" />}
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
        <SectionHeading eyebrow="Sampling" title={`Run ${data.run.id}`} />
        <div className={styles.denominatorBand}>
          <Denominator label="Planned" value={assessment.planned_task_count} />
          <Denominator label="Valid" value={assessment.valid_task_count} tone="good" />
          <Denominator label="Invalid" value={assessment.invalid_task_count} tone="bad" />
          <Denominator label="Missing" value={assessment.missing_task_count} tone="warning" />
          <Denominator label="Valid completion" value={percent(assessment.valid_completion_ratio)} />
        </div>
        <div className={styles.resultBanner} data-status={assessment.status}>
          <strong>{assessment.status === "complete" ? "Evidence complete" : "Insufficient evidence"}</strong>
          <span>{assessment.sufficient_question_count} / {assessment.question_count} questions meet the frozen repeat floor</span>
        </div>
        <dl className={styles.compactFacts}>
          <Fact label="Denominator SHA-256" value={assessment.denominator_hash} />
          <Fact label="Run admission SHA-256" value={data.run.admission_grant_hash} />
          <Fact label="Admission Policy" value={data.run.admission_policy_id} />
          <Fact label="Policy SHA-256" value={data.run.admission_policy_hash} />
          <Fact label="Authorization valid until" value={formatTime(data.run.authorization_valid_until)} />
          <Fact label="Statistics method" value={data.suite.statistics_method_version} />
        </dl>
        <SuiteFacts suite={data.suite} />
      </section>

      <section>
        <SectionHeading eyebrow="Planned denominator" title="Tasks" />
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead><tr><th>Question</th><th>Repeat</th><th>Capture</th><th>Status</th><th>Attempts</th><th>Evidence</th><th>Task key</th></tr></thead>
            <tbody>{data.tasks.map((task) => {
              const observation = observations.get(task.id);
              return (
                <tr key={task.id}>
                  <td><strong>{task.question_id}</strong><small>{task.question_version}</small></td>
                  <td>{task.repetition}</td>
                  <td>{captureLabel(task.capture_method)}</td>
                  <td><Status value={task.status} /></td>
                  <td>{task.attempt_ids.length} / {task.max_attempts}</td>
                  <td>{observation ? <Status value={observation.evidence_status} /> : "missing"}</td>
                  <td><code>{task.task_key}</code></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      </section>

      <section>
        <SectionHeading eyebrow="Execution lineage" title="Attempts" />
        {data.attempts.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.dataTable}>
              <thead><tr><th>Attempt</th><th>Job</th><th>Ordinal</th><th>Record</th><th>Calls</th><th>Provider response</th><th>Actual location</th></tr></thead>
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
        ) : <EmptyState title="Attempt 尚未创建" />}
      </section>

      <section>
        <SectionHeading eyebrow="Winning evidence" title="Observations" />
        {data.observations.length ? (
          <div className={styles.observationList}>
            {data.observations.map((observation) => (
              <article key={observation.id}>
                <header><div><strong>{observation.task_key}</strong><small>{formatTime(observation.observed_at)}</small></div><Status value={observation.evidence_status} /></header>
                <p>{observation.evidence.derived_summary}</p>
                {observation.ineligible_reasons.length ? <ul>{observation.ineligible_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : null}
                <dl className={styles.compactFacts}>
                  <Fact label="Winning Attempt" value={observation.winning_attempt_id} />
                  <Fact label="Observation SHA-256" value={observation.observation_hash} />
                  <Fact label="Parameters SHA-256" value={observation.evidence.result_parameters_hash} />
                  <Fact label="Evidence locator" value={observation.evidence.evidence_locator} />
                  <Fact label="Raw manifest SHA-256" value={observation.evidence.raw_manifest_hash} />
                  <Fact label="Derived manifest SHA-256" value={observation.evidence.derived_manifest_hash} />
                  <Fact label="Actual location" value={observation.actual_location ? actualLocation(observation.actual_location) : "-"} />
                </dl>
              </article>
            ))}
          </div>
        ) : <EmptyState title="Observation 尚未形成" />}
      </section>
    </div>
  );
}

function SuiteFacts({ suite }: { suite: SamplingSuite }) {
  const source = suite.source_stratum;
  return (
    <dl className={styles.factGrid}>
      <Fact label="Suite" value={suite.id} />
      <Fact label="Question Set" value={suite.question_set_id} />
      <Fact label="Capture" value={captureLabel(source.capture_method)} />
      <Fact label="Surface" value={`${source.platform} / ${source.surface}`} />
      <Fact label="Model" value={`${source.configured_model} / ${source.reported_model}`} />
      <Fact label="Locale" value={`${source.locale} · ${source.region} · ${source.language}`} />
      <Fact label="Adapter" value={source.adapter_release} />
      <Fact label="SourceStratum SHA-256" value={source.stratum_hash} />
      <Fact label="Suite SHA-256" value={suite.suite_hash} />
      <Fact label="Frozen" value={`${formatTime(suite.frozen_at)} · ${suite.frozen_by}`} />
    </dl>
  );
}

function Denominator({ label, tone, value }: { label: string; tone?: string; value: string | number }) {
  return <div data-tone={tone}><span>{label}</span><strong>{value}</strong></div>;
}

function Status({ value }: { value: string }) {
  return <span className={styles.status} data-status={value}>{value.replaceAll("_", " ")}</span>;
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
  ].filter(Boolean).join(" · ") || "not controlled";
}
