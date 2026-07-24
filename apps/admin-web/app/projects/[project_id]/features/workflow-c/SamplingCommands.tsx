"use client";

import { useActionState } from "react";

import {
  cancelSamplingRunAction,
  createSamplingSuiteAction,
  enqueueSamplingRunAction,
  startSamplingRunAction
} from "./samplingActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import {
  initialWorkflowCActionState,
  type AdmissionPolicy,
  type SamplingRun,
  type SamplingSuite,
  type SamplingSuiteInputOption
} from "./workflowCTypes";
import styles from "./WorkflowCAlerts.module.css";

export type SamplingCommandKeys = Readonly<{
  createSuite: string;
  startRun: string;
  enqueueRun: string;
  cancelRun: string;
}>;

export function SamplingCommands({
  admissionPolicies,
  canOperate,
  commandKeys,
  projectId,
  requestedNotBefore,
  runs,
  selectedRun,
  suiteInputOptions,
  suites
}: {
  admissionPolicies: AdmissionPolicy[];
  canOperate: boolean;
  commandKeys: SamplingCommandKeys;
  projectId: string;
  requestedNotBefore: string;
  runs: SamplingRun[];
  selectedRun: SamplingRun | null;
  suiteInputOptions: SamplingSuiteInputOption[];
  suites: SamplingSuite[];
}) {
  const [suiteState, suiteAction, suitePending] = useActionState(createSamplingSuiteAction, initialWorkflowCActionState);
  const [runState, runAction, runPending] = useActionState(startSamplingRunAction, initialWorkflowCActionState);
  const [enqueueState, enqueueAction, enqueuePending] = useActionState(enqueueSamplingRunAction, initialWorkflowCActionState);
  const [cancelState, cancelAction, cancelPending] = useActionState(cancelSamplingRunAction, initialWorkflowCActionState);
  const suiteDisabled = !canOperate || suitePending || !suiteInputOptions.length;
  const runDisabled = !canOperate || runPending || !suites.length;
  const selectedRunId = selectedRun?.id || runs[0]?.id || "";

  return (
    <section className={styles.commandBand} aria-labelledby="sampling-command-heading">
      <div className={styles.sectionHeading}>
        <div><p>Control plane</p><h3 id="sampling-command-heading">采样操作</h3></div>
        <span>{canOperate ? "owner / admin / analyst" : "只读"}</span>
      </div>
      <div className={styles.commandGrid}>
        <form action={suiteAction} className={styles.commandForm}>
          <CommandIdentity commandKey={commandKeys.createSuite} projectId={projectId} />
          <label><span>冻结输入</span><select disabled={suiteDisabled} name="suite_input_option_key" required><option value="">选择发布输入</option>{suiteInputOptions.map((option) => <option key={option.option_key} value={option.option_key}>{option.display_name} · {option.question_count} questions</option>)}</select></label>
          <label><span>每题重复</span><input defaultValue="10" disabled={suiteDisabled} max="100" min="1" name="repetitions" required type="number" /></label>
          <label><span>统计合同</span><select disabled={suiteDisabled} name="statistics_method_version"><option value="paired-bootstrap-holm-v1">Paired bootstrap + Holm v1</option></select></label>
          <label><span>Run 任务上限</span><input defaultValue="1000" disabled={suiteDisabled} min="1" name="max_planned_tasks" required type="number" /></label>
          <label><span>日任务上限</span><input defaultValue="1000" disabled={suiteDisabled} min="1" name="max_daily_tasks" required type="number" /></label>
          <label><span>最小间隔（秒）</span><input defaultValue="2" disabled={suiteDisabled} min="0" name="minimum_request_interval_seconds" required type="number" /></label>
          <label><span>最大并发</span><input defaultValue="1" disabled={suiteDisabled} min="1" name="max_concurrency" required type="number" /></label>
          <button disabled={suiteDisabled} type="submit">{suitePending ? "冻结中..." : "创建 Suite"}</button>
        </form>

        <form action={runAction} className={styles.commandForm}>
          <CommandIdentity commandKey={commandKeys.startRun} projectId={projectId} />
          <label><span>Sampling Suite</span><select disabled={runDisabled} name="suite_id" required><option value="">选择 Suite</option>{suites.map((suite) => <option key={suite.id} value={suite.id}>{suite.source_stratum.platform} · {suitePurpose(suite, admissionPolicies)} · {suite.planned_task_count} tasks</option>)}</select></label>
          <label><span>授权用途</span><output>由 Suite 的已批准 Admission Policy 冻结</output></label>
          <label><span>最早执行时间</span><input defaultValue={requestedNotBefore} disabled={runDisabled} name="requested_not_before" required type="datetime-local" /></label>
          <button disabled={runDisabled} type="submit">{runPending ? "创建中..." : "启动 Run"}</button>
        </form>

        <form action={enqueueAction} className={styles.commandForm}>
          <CommandIdentity commandKey={commandKeys.enqueueRun} projectId={projectId} />
          <RunSelector disabled={!canOperate || enqueuePending} name="run_id" runs={runs} selectedRunId={selectedRunId} />
          <input name="requested_not_before" type="hidden" value={requestedNotBefore} />
          <label><span>本批最大任务数</span><input defaultValue="1000" disabled={!canOperate || enqueuePending} min="1" name="max_tasks" required type="number" /></label>
          <button disabled={!canOperate || enqueuePending || !selectedRunId} type="submit">{enqueuePending ? "入队中..." : "批量入队"}</button>
        </form>

        <form action={cancelAction} className={styles.commandForm}>
          <CommandIdentity commandKey={commandKeys.cancelRun} projectId={projectId} />
          <RunSelector disabled={!canOperate || cancelPending} name="run_id" runs={runs} selectedRunId={selectedRunId} />
          <button disabled={!canOperate || cancelPending || !selectedRunId} type="submit">{cancelPending ? "取消中..." : "取消 Run"}</button>
        </form>
      </div>
      <WorkflowCActionFeedback state={suiteState} />
      <WorkflowCActionFeedback state={runState} />
      <WorkflowCActionFeedback state={enqueueState} />
      <WorkflowCActionFeedback state={cancelState} />
    </section>
  );
}

function CommandIdentity({ commandKey, projectId }: { commandKey: string; projectId: string }) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="idempotency_key" type="hidden" value={commandKey} /></>;
}

function RunSelector({ disabled, name, runs, selectedRunId }: { disabled: boolean; name: string; runs: SamplingRun[]; selectedRunId: string }) {
  return <label><span>Sampling Run</span><select defaultValue={selectedRunId} disabled={disabled} name={name} required><option value="">选择 Run</option>{runs.map((run) => <option key={run.id} value={run.id}>{run.status} · {shortId(run.id)} · {run.reserved_task_count} tasks</option>)}</select></label>;
}

function shortId(value: string): string {
  return value.length > 13 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

function suitePurpose(suite: SamplingSuite, policies: AdmissionPolicy[]): string {
  const policy = policies.find((item) =>
    item.id === suite.admission_policy_id
    && item.definition_hash === suite.admission_policy_hash
    && item.status === "approved"
  );
  return policy?.authorized_purposes.length === 1
    ? policy.authorized_purposes[0]
    : "purpose unavailable";
}
