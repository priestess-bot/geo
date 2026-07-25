"use client";

import { useActionState, useState } from "react";

import {
  createWorkflowCReportAction,
  transitionWorkflowCReportAction
} from "./workflowCReportActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import {
  workflowCReportMetricKeys,
  type WorkflowCReport
} from "./workflowCControlTypes";
import type { SemanticMetricSnapshot } from "./workflowCTypes";
import { initialWorkflowCActionState } from "./workflowCTypes";
import alertStyles from "./WorkflowCAlerts.module.css";
import styles from "./WorkflowCControls.module.css";

export type WorkflowCReportCommandKeys = Readonly<{
  create: string;
  transition: string;
}>;

export function WorkflowCReportCommands({
  canManage,
  commandKeys,
  currentIdentityId,
  projectId,
  reports,
  snapshots
}: {
  canManage: boolean;
  commandKeys: WorkflowCReportCommandKeys;
  currentIdentityId: string | null;
  projectId: string;
  reports: WorkflowCReport[];
  snapshots: SemanticMetricSnapshot[];
}) {
  const [createState, createAction, createPending] = useActionState(
    createWorkflowCReportAction,
    initialWorkflowCActionState
  );
  const [transitionState, transitionAction, transitionPending] = useActionState(
    transitionWorkflowCReportAction,
    initialWorkflowCActionState
  );
  const createDisabled = !canManage || createPending || !snapshots.length;
  return (
    <>
      <section>
        <header className={styles.controlHeading}>
          <div><p>Approved projection</p><h2>报告草稿</h2></div>
          <span>{canManage ? "owner / admin" : "只读"}</span>
        </header>
        <form action={createAction} className={`${alertStyles.commandForm} ${styles.reportForm}`}>
          <input name="project_id" type="hidden" value={projectId} />
          <input name="idempotency_key" type="hidden" value={commandKeys.create} />
          <label><span>Campaign ID</span><input disabled={createDisabled} name="campaign_id" required /></label>
          <label><span>Monitoring Report ID</span><input disabled={createDisabled} name="monitoring_report_id" required /></label>
          <label><span>Monitoring Report SHA-256</span><input disabled={createDisabled} maxLength={64} minLength={64} name="monitoring_report_hash" required /></label>
          <label>
            <span>Semantic Snapshot</span>
            <select disabled={createDisabled} name="semantic_snapshot_hash" required>
              <option value="">选择</option>
              {snapshots.map((item) => <option key={item.snapshot_hash} value={item.snapshot_hash}>{short(item.snapshot_hash)} · {formatTime(item.computed_at)}</option>)}
            </select>
          </label>
          <label>
            <span>Source kind</span>
            <select disabled={createDisabled} name="source_kind" required>
              <option value="provider_api">Provider API</option>
              <option value="proxy_grounded_api">Proxy grounded API</option>
            </select>
          </label>
          <label><span>Headline</span><input disabled={createDisabled} maxLength={200} name="headline" required /></label>
          <label className={styles.wideField}><span>Summary</span><textarea disabled={createDisabled} maxLength={2_000} name="summary" rows={3} /></label>
          <label className={styles.wideField}><span>Methodology</span><textarea disabled={createDisabled} maxLength={2_000} name="methodology" rows={3} /></label>
          <label className={styles.wideField}><span>Warnings</span><textarea disabled={createDisabled} maxLength={10_000} name="warnings" rows={3} /></label>
          <div className={`${styles.metricRows} ${styles.wideField}`}>
            {[1, 2, 3].map((index) => (
              <ReportMetricRow disabled={createDisabled} index={index} key={index} />
            ))}
          </div>
          <button className={styles.wideField} disabled={createDisabled} type="submit">
            {createPending ? "创建中..." : "创建报告草稿"}
          </button>
        </form>
        <WorkflowCActionFeedback state={createState} />
      </section>

      <section>
        <header className={styles.controlHeading}>
          <div><p>Maker-checker</p><h2>报告状态变更</h2></div>
          <span>{reports.length} reports</span>
        </header>
        <div className={styles.lifecycleList}>
          {reports.map((report) => (
            <ReportLifecycle
              action={transitionAction}
              canManage={canManage}
              commandKey={commandKeys.transition}
              currentIdentityId={currentIdentityId}
              key={report.report_id}
              pending={transitionPending}
              projectId={projectId}
              report={report}
            />
          ))}
        </div>
        <WorkflowCActionFeedback state={transitionState} />
      </section>
    </>
  );
}

function ReportMetricRow({ disabled, index }: { disabled: boolean; index: number }) {
  const [metricKey, setMetricKey] = useState("");
  const range = metricRange(metricKey);
  return (
    <div>
      <label>
        <span>Metric {index}</span>
        <select disabled={disabled} name="metric_key" onChange={(event) => setMetricKey(event.target.value)} value={metricKey}>
          <option value="">未设置</option>
          {workflowCReportMetricKeys.map((key) => <option key={key} value={key}>{key.replaceAll("_", " ")}</option>)}
        </select>
      </label>
      <label>
        <span>Metric value {index}</span>
        <input disabled={disabled} inputMode="decimal" max={range.max} min={range.min} name="metric_value" step={range.step} type="number" />
        <small>{range.label}</small>
      </label>
    </div>
  );
}

function metricRange(key: string): { min: string; max?: string; step: string; label: string } {
  if (key === "source_domain_diversity" || key === "source_type_diversity") {
    return { min: "0", step: "1", label: "Nonnegative integer count" };
  }
  if (key === "competitor_relative_position" || key === "sentiment") {
    return { min: "-1", max: "1", step: "any", label: "Signed score · -1 to 1" };
  }
  return { min: "0", max: "1", step: "any", label: "Rate / score · 0 to 1" };
}

function ReportLifecycle({
  action,
  canManage,
  commandKey,
  currentIdentityId,
  pending,
  projectId,
  report
}: {
  action: (payload: FormData) => void;
  canManage: boolean;
  commandKey: string;
  currentIdentityId: string | null;
  pending: boolean;
  projectId: string;
  report: WorkflowCReport;
}) {
  const operations = report.status === "draft"
    ? ["submit" as const]
    : report.status === "in_review"
      ? ["approve" as const]
      : report.status === "approved"
        ? ["stale" as const, "revoke" as const]
        : [];
  return (
    <div className={styles.lifecycleRow}>
      <div>
        <strong>{report.approved_safe_payload.headline}</strong>
        <code>{report.report_id}</code>
        <span>{report.status} · v{report.version}</span>
      </div>
      {operations.map((operation) => {
        const makerBlocked = operation === "approve" && currentIdentityId === report.actor_id;
        const disabled = !canManage || pending || makerBlocked;
        return (
          <form action={action} className={styles.inlineCommand} key={operation}>
            <input name="project_id" type="hidden" value={projectId} />
            <input name="report_id" type="hidden" value={report.report_id} />
            <input name="expected_version" type="hidden" value={report.version} />
            <input name="operation" type="hidden" value={operation} />
            <input name="idempotency_key" type="hidden" value={`${commandKey}-${operation}-${report.report_id}`} />
            {operation !== "submit" ? (
              <label><span>决策原因</span><input disabled={disabled} maxLength={500} name="reason" required /></label>
            ) : null}
            <button disabled={disabled} type="submit">
              {makerBlocked ? "需其他审批人" : pending ? "提交中..." : reportOperationLabel(operation)}
            </button>
          </form>
        );
      })}
    </div>
  );
}

function reportOperationLabel(operation: "submit" | "approve" | "stale" | "revoke"): string {
  if (operation === "submit") return "提交报告复核";
  if (operation === "approve") return "批准报告";
  if (operation === "stale") return "标记失效";
  return "撤销报告";
}

function short(value: string): string {
  return `${value.slice(0, 10)}...${value.slice(-5)}`;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN");
}
