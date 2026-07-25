"use client";

import { useActionState } from "react";

import {
  enqueueComparisonJobAction,
  enqueueDriftJobAction,
  enqueueSemanticMetricsJobAction
} from "./workflowCAnalysisJobActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import type { MetricProtocol, StatisticalProtocol } from "./workflowCControlTypes";
import type { SamplingRun, SemanticMetricSnapshot } from "./workflowCTypes";
import { initialWorkflowCActionState } from "./workflowCTypes";
import alertStyles from "./WorkflowCAlerts.module.css";
import styles from "./WorkflowCControls.module.css";

export type WorkflowCAnalysisJobCommandKeys = Readonly<{
  semantic: string;
  comparison: string;
  drift: string;
}>;

export function WorkflowCAnalysisJobCommands({
  canAnalyze,
  commandKeys,
  metricProtocols,
  projectId,
  runs,
  snapshots,
  statisticalProtocols
}: {
  canAnalyze: boolean;
  commandKeys: WorkflowCAnalysisJobCommandKeys;
  metricProtocols: MetricProtocol[];
  projectId: string;
  runs: SamplingRun[];
  snapshots: SemanticMetricSnapshot[];
  statisticalProtocols: StatisticalProtocol[];
}) {
  const [semanticState, semanticAction, semanticPending] = useActionState(
    enqueueSemanticMetricsJobAction,
    initialWorkflowCActionState
  );
  const [comparisonState, comparisonAction, comparisonPending] = useActionState(
    enqueueComparisonJobAction,
    initialWorkflowCActionState
  );
  const [driftState, driftAction, driftPending] = useActionState(
    enqueueDriftJobAction,
    initialWorkflowCActionState
  );
  const approvedMetrics = metricProtocols.filter((item) => item.status === "approved");
  const comparisons = statisticalProtocols.filter(
    (item) => item.status === "approved" && item.kind === "comparison_plan"
  );
  const drifts = statisticalProtocols.filter(
    (item) => item.status === "approved" && item.kind === "drift_protocol"
  );
  return (
    <section>
      <header className={styles.controlHeading}>
        <div><p>可持久化分析</p><h2>分析任务</h2></div>
        <span>{canAnalyze ? "可入队" : "只读"}</span>
      </header>
      <div className={styles.createGrid}>
        <form action={semanticAction} className={alertStyles.commandForm}>
          <CommonInputs commandKey={commandKeys.semantic} projectId={projectId} />
          <Select label="采样运行" name="sampling_run_id" options={runs.map((item) => ({ label: `${item.status} · ${short(item.id)}`, value: item.id }))} />
          <Select label="已批准指标协议" name="metric_protocol_id" options={approvedMetrics.map(protocolOption)} />
          <button disabled={!canAnalyze || semanticPending || !runs.length || !approvedMetrics.length} type="submit">
            {semanticPending ? "入队中..." : "入队语义指标任务"}
          </button>
        </form>
        <form action={comparisonAction} className={alertStyles.commandForm}>
          <CommonInputs commandKey={commandKeys.comparison} projectId={projectId} />
          <Select label="已批准比较协议" name="comparison_plan_id" options={comparisons.map(protocolOption)} />
          <SnapshotSelect label="基线快照" name="baseline_metric_snapshot_hash" snapshots={snapshots} />
          <SnapshotSelect label="候选快照" name="candidate_metric_snapshot_hash" snapshots={snapshots} />
          <button disabled={!canAnalyze || comparisonPending || !comparisons.length || !snapshots.length} type="submit">
            {comparisonPending ? "入队中..." : "入队比较任务"}
          </button>
        </form>
        <form action={driftAction} className={alertStyles.commandForm}>
          <CommonInputs commandKey={commandKeys.drift} projectId={projectId} />
          <Select label="已批准漂移协议" name="drift_protocol_id" options={drifts.map(protocolOption)} />
          <SnapshotSelect label="漂移基线快照" name="baseline_metric_snapshot_hash" snapshots={snapshots} />
          <SnapshotSelect label="当前快照" name="current_metric_snapshot_hash" snapshots={snapshots} />
          <button disabled={!canAnalyze || driftPending || !drifts.length || !snapshots.length} type="submit">
            {driftPending ? "入队中..." : "入队漂移检测任务"}
          </button>
        </form>
      </div>
      <WorkflowCActionFeedback state={semanticState} />
      <WorkflowCActionFeedback state={comparisonState} />
      <WorkflowCActionFeedback state={driftState} />
    </section>
  );
}

function CommonInputs({ commandKey, projectId }: { commandKey: string; projectId: string }) {
  return (
    <>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="idempotency_key" type="hidden" value={commandKey} />
      <label><span>最大尝试次数</span><input defaultValue="3" max="10" min="1" name="max_attempts" required type="number" /></label>
    </>
  );
}

function SnapshotSelect({ label, name, snapshots }: { label: string; name: string; snapshots: SemanticMetricSnapshot[] }) {
  return <Select label={label} name={name} options={snapshots.map((item) => ({ label: `${formatTime(item.computed_at)} · ${short(item.snapshot_hash)}`, value: item.snapshot_hash }))} />;
}

function Select({ label, name, options }: { label: string; name: string; options: Array<{ label: string; value: string }> }) {
  return (
    <label><span>{label}</span><select name={name} required><option value="">选择</option>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
  );
}

function protocolOption(item: MetricProtocol | StatisticalProtocol) {
  return { label: `v${item.version} · ${short(item.id)}`, value: item.id };
}

function short(value: string): string {
  return `${value.slice(0, 8)}...${value.slice(-5)}`;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
