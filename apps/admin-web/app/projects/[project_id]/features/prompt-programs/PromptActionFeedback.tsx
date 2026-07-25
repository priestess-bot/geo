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
          <span>发布版本 v{state.release.version} · {state.release.status}</span>
          <code>{state.release.id}</code>
          <code>{state.release.releaseHash}</code>
        </div>
      ) : null}
      {state.job ? (
        <dl className={styles.feedbackDetails}>
          <div><dt>任务</dt><dd><code>{state.job.id}</code></dd></div>
          <div><dt>状态</dt><dd>{state.job.status}</dd></div>
          <div><dt>输入 SHA-256</dt><dd><code>{state.job.inputHash}</code></dd></div>
          <div><dt>测试集 SHA-256</dt><dd><code>{state.job.testSetHash}</code></dd></div>
        </dl>
      ) : null}
      {state.admittedEvidenceHash ? (
        <div className={styles.feedbackLineage}>
          <span>已准入证据 SHA-256</span>
          <code>{state.admittedEvidenceHash}</code>
        </div>
      ) : null}
      {state.binding ? (
        <dl className={styles.feedbackDetails}>
          <div><dt>绑定</dt><dd><code>{state.binding.id}</code></dd></div>
          <div><dt>绑定版本</dt><dd>{state.binding.version}</dd></div>
          <div><dt>发布版本 SHA-256</dt><dd><code>{state.binding.releaseHash}</code></dd></div>
        </dl>
      ) : null}
      {state.diff ? <PromptDiffComparison diff={state.diff} /> : null}
      {state.nextHref ? <a className={styles.resultLink} href={state.nextHref}>打开结果</a> : null}
    </div>
  );
}

function PromptDiffComparison({ diff }: { diff: PromptProgramDiffResponse }) {
  return (
    <section className={styles.diffResult} aria-label="Prompt 发布版本差异结果">
      <header>
        <strong>{diff.changed_fields.length ? `${diff.changed_fields.length} 个字段变化` : "无字段变化"}</strong>
        <span>{diff.changed_fields.length ? diff.changed_fields.join(" · ") : "完全一致"}</span>
      </header>
      <div className={styles.diffColumns}>
        <DiffColumn
          label="基线"
          releaseHash={diff.base_release_hash}
          releaseId={diff.base_release_id}
          systemHash={diff.base_system_hash}
          userHash={diff.base_user_hash}
        />
        <DiffColumn
          label="候选版本"
          releaseHash={diff.candidate_release_hash}
          releaseId={diff.candidate_release_id}
          systemHash={diff.candidate_system_hash}
          userHash={diff.candidate_user_hash}
        />
      </div>
      <div className={styles.fixedInputHash}>
        <span>固定输入 SHA-256</span><code>{diff.fixed_input_hash}</code>
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
      <div><dt>{label}发布版本</dt><dd><code>{releaseId}</code></dd></div>
      <div><dt>发布版本 SHA-256</dt><dd><code>{releaseHash}</code></dd></div>
      <div><dt>系统 SHA-256</dt><dd><code>{systemHash}</code></dd></div>
      <div><dt>用户 SHA-256</dt><dd><code>{userHash}</code></dd></div>
    </dl>
  );
}
