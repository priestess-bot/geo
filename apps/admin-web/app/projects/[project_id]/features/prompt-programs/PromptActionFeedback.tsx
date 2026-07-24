import type { PromptActionState, PromptProgramDiffResponse } from "./promptProgramTypes";
import styles from "./PromptPrograms.module.css";

export function PromptActionFeedback({ state }: { state: PromptActionState }) {
  if (state.kind === "idle") return null;
  return (
    <div
      className={state.kind === "error" ? styles.errorFeedback : styles.successFeedback}
      role={state.kind === "error" ? "alert" : "status"}
    >
      <strong>{state.status ? `${state.status} · ` : ""}{state.message}</strong>
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
      {state.release ? (
        <div className={styles.feedbackLineage}>
          <span>Release v{state.release.version} · {state.release.status}</span>
          <code>{state.release.id}</code>
          <code>{state.release.releaseHash}</code>
        </div>
      ) : null}
      {state.job ? (
        <dl className={styles.feedbackDetails}>
          <div><dt>Job</dt><dd><code>{state.job.id}</code></dd></div>
          <div><dt>Status</dt><dd>{state.job.status}</dd></div>
          <div><dt>Input SHA-256</dt><dd><code>{state.job.inputHash}</code></dd></div>
          <div><dt>TestSet SHA-256</dt><dd><code>{state.job.testSetHash}</code></dd></div>
        </dl>
      ) : null}
      {state.admittedEvidenceHash ? (
        <div className={styles.feedbackLineage}>
          <span>Admitted Evidence SHA-256</span>
          <code>{state.admittedEvidenceHash}</code>
        </div>
      ) : null}
      {state.binding ? (
        <dl className={styles.feedbackDetails}>
          <div><dt>Binding</dt><dd><code>{state.binding.id}</code></dd></div>
          <div><dt>Binding version</dt><dd>{state.binding.version}</dd></div>
          <div><dt>Release SHA-256</dt><dd><code>{state.binding.releaseHash}</code></dd></div>
        </dl>
      ) : null}
      {state.diff ? <PromptDiffComparison diff={state.diff} /> : null}
      {state.nextHref ? <a className={styles.resultLink} href={state.nextHref}>打开结果</a> : null}
    </div>
  );
}

function PromptDiffComparison({ diff }: { diff: PromptProgramDiffResponse }) {
  return (
    <section className={styles.diffResult} aria-label="Prompt Release 差异结果">
      <header>
        <strong>{diff.changed_fields.length ? `${diff.changed_fields.length} 个字段变化` : "无字段变化"}</strong>
        <span>{diff.changed_fields.length ? diff.changed_fields.join(" · ") : "identical"}</span>
      </header>
      <div className={styles.diffColumns}>
        <DiffColumn
          label="Baseline"
          releaseHash={diff.base_release_hash}
          releaseId={diff.base_release_id}
          systemHash={diff.base_system_hash}
          userHash={diff.base_user_hash}
        />
        <DiffColumn
          label="Candidate"
          releaseHash={diff.candidate_release_hash}
          releaseId={diff.candidate_release_id}
          systemHash={diff.candidate_system_hash}
          userHash={diff.candidate_user_hash}
        />
      </div>
      <div className={styles.fixedInputHash}>
        <span>Fixed input SHA-256</span><code>{diff.fixed_input_hash}</code>
      </div>
    </section>
  );
}

function DiffColumn({
  label,
  releaseHash,
  releaseId,
  systemHash,
  userHash
}: {
  label: string;
  releaseHash: string;
  releaseId: string;
  systemHash: string;
  userHash: string;
}) {
  return (
    <dl className={styles.diffColumn}>
      <div><dt>{label} Release</dt><dd><code>{releaseId}</code></dd></div>
      <div><dt>Release SHA-256</dt><dd><code>{releaseHash}</code></dd></div>
      <div><dt>System SHA-256</dt><dd><code>{systemHash}</code></dd></div>
      <div><dt>User SHA-256</dt><dd><code>{userHash}</code></dd></div>
    </dl>
  );
}
