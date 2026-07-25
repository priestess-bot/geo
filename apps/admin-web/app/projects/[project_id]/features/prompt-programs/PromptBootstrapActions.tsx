"use client";

import { useActionState } from "react";

import {
  createPromptBootstrapDraftsAction,
  evaluatePromptBootstrapAction
} from "./promptBootstrapActions";
import {
  initialBootstrapActionState,
  initialBootstrapEvaluationState,
  type PromptBootstrapActionState,
  type PromptBootstrapEvaluationState
} from "./promptBootstrapTypes";
import { promptProgramKinds } from "./promptProgramTypes";
import styles from "./PromptBootstrap.module.css";

export function PromptBootstrapDraftForm({
  canManage,
  catalogHash,
  projectId
}: {
  canManage: boolean;
  catalogHash: string;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(
    createPromptBootstrapDraftsAction,
    initialBootstrapActionState
  );
  const failed = state.batch?.failed_count || 0;
  return (
    <section className={styles.actionSection} aria-labelledby="prompt-bootstrap-create-heading">
      <div className={styles.sectionHeading}>
        <div><p>逐项幂等批处理</p><h4 id="prompt-bootstrap-create-heading">创建 {promptProgramKinds.length} 个未批准草稿</h4></div>
        <span>负责人 / 管理员</span>
      </div>
      <div className={styles.boundaryNotice}>
        <strong>只创建草稿</strong>
        <span>不会执行测试、批准、冻结或运行时绑定；每项独立提交，失败项可安全重试。</span>
      </div>
      <form action={action} className={styles.actionForm}>
        <input name="project_id" type="hidden" value={projectId} />
        <input name="catalog_hash" type="hidden" value={catalogHash} />
        <input name="idempotency_key" type="hidden" value={`prompt-bootstrap-drafts-${projectId}-${catalogHash}`} />
        <button disabled={!canManage || pending} type="submit">
          {pending ? "处理中..." : failed ? "使用同一键重试失败项" : `创建 / 恢复 ${promptProgramKinds.length} 个草稿`}
        </button>
      </form>
      <DraftFeedback state={state} />
    </section>
  );
}

export function PromptBootstrapEvaluationForm({
  canManage,
  catalogHash,
  fixtureIds,
  programKind,
  projectId,
  specHash,
  testSetHash
}: {
  canManage: boolean;
  catalogHash: string;
  fixtureIds: readonly string[];
  programKind: string;
  projectId: string;
  specHash: string;
  testSetHash: string;
}) {
  const [state, action, pending] = useActionState(
    evaluatePromptBootstrapAction,
    initialBootstrapEvaluationState
  );
  const initialOutputs = JSON.stringify(
    Object.fromEntries(fixtureIds.map((fixtureId) => [fixtureId, {}])),
    null,
    2
  );
  return (
    <section className={styles.actionSection} aria-labelledby="prompt-bootstrap-evaluate-heading">
      <div className={styles.sectionHeading}>
        <div><p>确定性本地评审</p><h4 id="prompt-bootstrap-evaluate-heading">离线评估 5 个固定用例</h4></div>
        <span>0 次外部模型调用</span>
      </div>
      <form action={action} className={styles.evaluationForm}>
        <input name="project_id" type="hidden" value={projectId} />
        <input name="program_kind" type="hidden" value={programKind} />
        <input name="catalog_hash" type="hidden" value={catalogHash} />
        <input name="spec_hash" type="hidden" value={specHash} />
        <input name="test_set_hash" type="hidden" value={testSetHash} />
        <label>
          <span>5 个固定用例输出（JSON 对象）</span>
          <textarea
            defaultValue={initialOutputs}
            disabled={!canManage || pending}
            maxLength={1_000_000}
            name="outputs"
            required
            spellCheck={false}
          />
        </label>
        <button disabled={!canManage || pending} type="submit">{pending ? "评估中..." : "运行离线评估"}</button>
      </form>
      <EvaluationFeedback state={state} />
    </section>
  );
}

function DraftFeedback({ state }: { state: PromptBootstrapActionState }) {
  if (state.kind === "idle") {
    return <div className={styles.resultEmpty}><strong>尚无本次创建结果</strong><span>目录预览不会自动创建任何程序或发布版本。</span></div>;
  }
  if (state.kind === "error") return <Problem state={state} />;
  const batch = state.batch;
  if (!batch) return null;
  return (
    <div className={batch.failed_count ? styles.partialResult : styles.successResult} role={batch.failed_count ? "alert" : "status"}>
      <div className={styles.resultHeader}>
        <div><strong>{state.message}</strong><span>{batch.completion_status}</span></div>
        <dl>
          <div><dt>已创建</dt><dd>{batch.created_count}</dd></div>
          <div><dt>已重放</dt><dd>{batch.replayed_count}</dd></div>
          <div><dt>失败</dt><dd>{batch.failed_count}</dd></div>
        </dl>
      </div>
      <details className={styles.resultDisclosure}>
        <summary>查看 {batch.items.length} 项创建明细</summary>
        <div className={styles.tableWrap}>
          <table className={styles.resultTable}>
          <thead><tr><th>类型</th><th>结果</th><th>程序 / 草稿发布版本</th><th>失败或幂等证据</th></tr></thead>
            <tbody>{batch.items.map((item) => (
              <tr key={item.program_kind}>
                <td><strong>{item.program_kind}</strong><code>{item.spec_hash}</code></td>
                <td><ResultStatus value={item.status} /></td>
                <td>{item.program && item.release ? <><code>{item.program.id}</code><code>{item.release.id}</code><span>发布版本状态：草稿 · 未批准</span></> : <span>未创建</span>}</td>
                <td>{item.failure ? <><strong>{item.failure.code}</strong><span>{item.failure.detail}</span><small>可重试：{String(item.failure.retryable)}</small></> : <code>{item.idempotency_key_hash}</code>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </details>
      <small>原子性：否 · 可安全重试：是 · {batch.action_boundary}</small>
    </div>
  );
}

function EvaluationFeedback({ state }: { state: PromptBootstrapEvaluationState }) {
  if (state.kind === "idle") return null;
  if (state.kind === "error") return <Problem state={state} />;
  const result = state.evaluation;
  if (!result) return null;
  return (
    <div className={result.passed ? styles.successResult : styles.partialResult} role="status">
      <div className={styles.resultHeader}>
        <div><strong>{state.message}</strong><span>{result.program_kind} · 得分 {result.score} / 最低 {result.minimum_score}</span></div>
        <code>{result.result_hash}</code>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.evaluationTable}>
          <thead><tr><th>固定用例 / 场景</th><th>得分</th><th>结果</th><th>失败条件</th></tr></thead>
          <tbody>{result.case_results.map((item) => (
            <tr key={item.fixture_id}>
              <td><strong>{item.fixture_id}</strong><span>{item.scenario}</span></td>
              <td>{item.score}</td>
              <td><ResultStatus value={item.passed ? "passed" : "failed"} /></td>
              <td>{item.error_code || item.failed_criteria.join(", ") || "无"}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <small>外部模型调用：0 · 自动状态转换：否</small>
    </div>
  );
}

function Problem({ state }: { state: { status?: number; message?: string; correlationId?: string } }) {
  return (
    <div className={styles.errorResult} role="alert">
      <strong>{state.status ? `${state.status} · ` : ""}{state.message || "操作失败。"}</strong>
      {state.correlationId ? <small>关联 ID：{state.correlationId}</small> : null}
    </div>
  );
}

function ResultStatus({ value }: { value: string }) {
  return <span className={`${styles.statusPill} ${styles[`status_${value}`] || ""}`}>{value === "passed" ? "通过" : value === "failed" ? "失败" : value}</span>;
}
