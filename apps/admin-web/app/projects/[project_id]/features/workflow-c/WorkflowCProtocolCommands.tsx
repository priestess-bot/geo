"use client";

import { useActionState } from "react";

import {
  createMetricProtocolAction,
  createStatisticalProtocolAction,
  transitionMetricProtocolAction,
  transitionStatisticalProtocolAction
} from "./workflowCProtocolActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import type { MetricProtocol, StatisticalProtocol } from "./workflowCControlTypes";
import { initialWorkflowCActionState } from "./workflowCTypes";
import alertStyles from "./WorkflowCAlerts.module.css";
import styles from "./WorkflowCControls.module.css";

export type WorkflowCProtocolCommandKeys = Readonly<{
  metricCreate: string;
  statisticalCreate: string;
  metricTransition: string;
  statisticalTransition: string;
}>;

export function WorkflowCProtocolCommands({
  actorId,
  canManage,
  commandKeys,
  metricProtocols,
  projectId,
  statisticalProtocols
}: {
  actorId: string;
  canManage: boolean;
  commandKeys: WorkflowCProtocolCommandKeys;
  metricProtocols: MetricProtocol[];
  projectId: string;
  statisticalProtocols: StatisticalProtocol[];
}) {
  const [metricCreateState, metricCreateAction, metricCreatePending] = useActionState(
    createMetricProtocolAction,
    initialWorkflowCActionState
  );
  const [statCreateState, statCreateAction, statCreatePending] = useActionState(
    createStatisticalProtocolAction,
    initialWorkflowCActionState
  );
  const [metricTransitionState, metricTransitionAction, metricTransitionPending] = useActionState(
    transitionMetricProtocolAction,
    initialWorkflowCActionState
  );
  const [statTransitionState, statTransitionAction, statTransitionPending] = useActionState(
    transitionStatisticalProtocolAction,
    initialWorkflowCActionState
  );

  return (
    <section>
      <header className={styles.controlHeading}>
        <div><p>协议控制</p><h2>创建与状态变更</h2></div>
        <span>{canManage ? "负责人 / 管理员" : "只读"}</span>
      </header>
      <div className={styles.createGrid}>
        <MetricProtocolCreateForm
          action={metricCreateAction}
          commandKey={commandKeys.metricCreate}
          disabled={!canManage || metricCreatePending}
          pending={metricCreatePending}
          projectId={projectId}
          supersedes={metricProtocols}
        />
        <ComparisonProtocolCreateForm
          action={statCreateAction}
          commandKey={`${commandKeys.statisticalCreate}-comparison`}
          disabled={!canManage || statCreatePending}
          pending={statCreatePending}
          projectId={projectId}
          supersedes={statisticalProtocols.filter((item) => item.kind === "comparison_plan")}
        />
        <DriftProtocolCreateForm
          action={statCreateAction}
          commandKey={`${commandKeys.statisticalCreate}-drift`}
          disabled={!canManage || statCreatePending}
          pending={statCreatePending}
          projectId={projectId}
          supersedes={statisticalProtocols.filter((item) => item.kind === "drift_protocol")}
        />
      </div>
      <WorkflowCActionFeedback state={metricCreateState} />
      <WorkflowCActionFeedback state={statCreateState} />

      <div className={styles.lifecycleList}>
        {metricProtocols.map((protocol) => (
          <ProtocolLifecycle
            action={metricTransitionAction}
            actorId={actorId}
            canManage={canManage}
            commandKey={commandKeys.metricTransition}
            key={protocol.id}
            label="指标协议"
            pending={metricTransitionPending}
            projectId={projectId}
            protocol={protocol}
          />
        ))}
        {statisticalProtocols.map((protocol) => (
          <ProtocolLifecycle
            action={statTransitionAction}
            actorId={actorId}
            canManage={canManage}
            commandKey={commandKeys.statisticalTransition}
            key={protocol.id}
            label={protocol.kind === "comparison_plan" ? "比较协议" : "漂移协议"}
            pending={statTransitionPending}
            projectId={projectId}
            protocol={protocol}
          />
        ))}
      </div>
      <WorkflowCActionFeedback state={metricTransitionState} />
      <WorkflowCActionFeedback state={statTransitionState} />
    </section>
  );
}

type CreateFormProps = Readonly<{
  action: (payload: FormData) => void;
  commandKey: string;
  disabled: boolean;
  pending: boolean;
  projectId: string;
  supersedes: Array<MetricProtocol | StatisticalProtocol>;
}>;

function MetricProtocolCreateForm({
  action,
  commandKey,
  disabled,
  pending,
  projectId,
  supersedes
}: CreateFormProps) {
  return (
    <form action={action} className={alertStyles.commandForm}>
      <CreateHidden commandKey={commandKey} projectId={projectId} />
      <input name="protocol_kind" type="hidden" value="metric_protocol" />
      <label><span>主主体键</span><input disabled={disabled} name="primary_subject_key" required /></label>
      <label><span>品牌别名</span><textarea disabled={disabled} name="brand_aliases" required rows={2} /></label>
      <label><span>产品别名</span><textarea disabled={disabled} name="product_aliases" required rows={2} /></label>
      <label><span>竞品键</span><input disabled={disabled} name="competitor_key" /></label>
      <label><span>竞品别名</span><textarea disabled={disabled} name="competitor_aliases" rows={2} /></label>
      <label><span>已验证 URL</span><textarea disabled={disabled} name="verified_urls" required rows={2} /></label>
      <label><span>问题聚类 · ID|聚类</span><textarea disabled={disabled} name="question_clusters" required rows={2} /></label>
      <label><span>Prompt 发布版本 ID</span><input disabled={disabled} name="prompt_release_id" required /></label>
      <label><span>Prompt 发布版本 SHA-256</span><input disabled={disabled} maxLength={64} minLength={64} name="prompt_release_hash" required /></label>
      <label><span>评审版本</span><input defaultValue="metric-judge-v1" disabled={disabled} name="judge_version" required /></label>
      <label><span>评审模型标识</span><input disabled={disabled} name="model_identity" required /></label>
      <label><span>事实快照 ID</span><input disabled={disabled} name="fact_snapshot_id" required /></label>
      <label><span>事实快照 SHA-256</span><input disabled={disabled} maxLength={64} minLength={64} name="fact_snapshot_hash" required /></label>
      <label><span>语料版本 ID</span><input disabled={disabled} name="corpus_version_id" required /></label>
      <label><span>语料版本</span><input disabled={disabled} name="approved_corpus_version" required /></label>
      <label><span>语料版本 SHA-256</span><input disabled={disabled} maxLength={64} minLength={64} name="corpus_version_hash" required /></label>
      <label><span>最小有效完成度</span><input defaultValue="0.8" disabled={disabled} max="1" min="0.8" name="minimum_valid_completion" required step="0.01" type="number" /></label>
      <SupersedesSelect disabled={disabled} items={supersedes} />
      <button disabled={disabled} type="submit">{pending ? "创建中..." : "创建指标协议"}</button>
    </form>
  );
}

function ComparisonProtocolCreateForm({ action, commandKey, disabled, pending, projectId, supersedes }: CreateFormProps) {
  return (
    <form action={action} className={alertStyles.commandForm}>
      <CreateHidden commandKey={commandKey} projectId={projectId} />
      <input name="protocol_kind" type="hidden" value="comparison_plan" />
      <label><span>比较族</span><input disabled={disabled} name="family" required /></label>
      <label><span>问题聚类</span><textarea disabled={disabled} name="question_clusters" required rows={3} /></label>
      <NumberField defaultValue="0.05" disabled={disabled} label="显著性水平" max="0.99" min="0.01" name="alpha" />
      <NumberField defaultValue="0.05" disabled={disabled} label="实际差异阈值" min="0" name="delta" />
      <NumberField defaultValue="0.8" disabled={disabled} label="目标功效" max="1" min="0.8" name="target_power" />
      <NumberField defaultValue="0.1" disabled={disabled} label="精度" min="0.01" name="precision" />
      <NumberField defaultValue="3" disabled={disabled} label="最小配对数" min="1" name="min_pairs" step="1" />
      <label><span>功效计划 SHA-256</span><input disabled={disabled} maxLength={64} minLength={64} name="power_plan_hash" required /></label>
      <NumberField defaultValue="0.9" disabled={disabled} label="先验设计功效" max="1" min="0" name="a_priori_design_power" />
      <NumberField defaultValue="0.8" disabled={disabled} label="最小完成比例" max="1" min="0.8" name="minimum_completion_ratio" />
      <NumberField defaultValue="10000" disabled={disabled} label="Bootstrap 迭代次数" min="100" name="bootstrap_iterations" step="1" />
      <SupersedesSelect disabled={disabled} items={supersedes} />
      <button disabled={disabled} type="submit">{pending ? "创建中..." : "创建比较协议"}</button>
    </form>
  );
}

function DriftProtocolCreateForm({ action, commandKey, disabled, pending, projectId, supersedes }: CreateFormProps) {
  return (
    <form action={action} className={alertStyles.commandForm}>
      <CreateHidden commandKey={commandKey} projectId={projectId} />
      <input name="protocol_kind" type="hidden" value="drift_protocol" />
      <NumberField defaultValue="3" disabled={disabled} label="最小问题数" min="1" name="minimum_question_count" step="1" />
      <SupersedesSelect disabled={disabled} items={supersedes} />
      <button disabled={disabled} type="submit">{pending ? "创建中..." : "创建漂移协议"}</button>
    </form>
  );
}

function CreateHidden({ commandKey, projectId }: { commandKey: string; projectId: string }) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="idempotency_key" type="hidden" value={commandKey} /></>;
}

function SupersedesSelect({ disabled, items }: { disabled: boolean; items: Array<MetricProtocol | StatisticalProtocol> }) {
  return (
    <label><span>替代版本</span><select disabled={disabled} name="supersedes_protocol_id"><option value="">新系列</option>{items.filter((item) => item.status === "approved" || item.status === "retired").map((item) => <option key={item.id} value={item.id}>v{item.version} · {protocolStatusLabel(item.status)} · {shortId(item.id)}</option>)}</select></label>
  );
}

function NumberField({ defaultValue, disabled, label, max, min, name, step = "0.01" }: { defaultValue: string; disabled: boolean; label: string; max?: string; min: string; name: string; step?: string }) {
  return <label><span>{label}</span><input defaultValue={defaultValue} disabled={disabled} max={max} min={min} name={name} required step={step} type="number" /></label>;
}

function ProtocolLifecycle({
  action,
  actorId,
  canManage,
  commandKey,
  label,
  pending,
  projectId,
  protocol
}: {
  action: (payload: FormData) => void;
  actorId: string;
  canManage: boolean;
  commandKey: string;
  label: string;
  pending: boolean;
  projectId: string;
  protocol: MetricProtocol | StatisticalProtocol;
}) {
  const operations = protocol.status === "draft"
    ? ["submit" as const]
    : protocol.status === "in_review"
      ? ["approve" as const]
      : protocol.status === "approved"
        ? ["retire" as const]
        : [];
  if (!operations.length) return null;
  return (
    <div className={styles.lifecycleRow}>
      <div>
        <strong>{label} · v{protocol.version}</strong>
        <code>{protocol.id}</code>
        <span>{protocolStatusLabel(protocol.status)}</span>
      </div>
      {operations.map((operation) => {
        const makerBlocked = operation === "approve" && protocol.created_by === actorId;
        const disabled = !canManage || pending || makerBlocked;
        return (
          <form action={action} className={styles.inlineCommand} key={operation}>
            <input name="project_id" type="hidden" value={projectId} />
            <input name="protocol_id" type="hidden" value={protocol.id} />
            <input name="expected_aggregate_version" type="hidden" value={protocol.aggregate_version} />
            <input name="operation" type="hidden" value={operation} />
            <input name="idempotency_key" type="hidden" value={`${commandKey}-${operation}-${protocol.id}`} />
            {operation === "approve" || operation === "retire" ? (
              <label>
                <span>{operation === "approve" ? "批准原因" : "退役原因"}</span>
                <input disabled={disabled} maxLength={2_000} name="reason" required />
              </label>
            ) : null}
            <button disabled={disabled} type="submit">
              {makerBlocked ? "需其他审批人" : pending ? "提交中..." : operationLabel(operation)}
            </button>
          </form>
        );
      })}
    </div>
  );
}

function operationLabel(operation: "submit" | "approve" | "retire"): string {
  if (operation === "submit") return "提交复核";
  if (operation === "approve") return "批准协议";
  return "退役协议";
}

function protocolStatusLabel(value: MetricProtocol["status"] | StatisticalProtocol["status"]): string {
  return {
    draft: "草稿",
    in_review: "复核中",
    approved: "已批准",
    retired: "已退役"
  }[value];
}

function shortId(value: string): string {
  return `${value.slice(0, 8)}...${value.slice(-4)}`;
}
