"use client";

import { useActionState } from "react";

import {
  approveManualEvidenceAction,
  importManualEvidenceAction,
  rejectManualEvidenceAction
} from "./samplingActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import {
  initialWorkflowCActionState,
  type ManualEvidenceImport,
  type SamplingTask
} from "./workflowCTypes";
import styles from "./WorkflowCAlerts.module.css";

export function ManualEvidenceCommands({
  actorId,
  canOperate,
  canReview,
  capturedAt,
  commandKey,
  imports,
  projectId,
  runId,
  tasks
}: {
  actorId: string;
  canOperate: boolean;
  canReview: boolean;
  capturedAt: string;
  commandKey: string;
  imports: ManualEvidenceImport[];
  projectId: string;
  runId: string | null;
  tasks: SamplingTask[];
}) {
  const [importState, importAction, importPending] = useActionState(importManualEvidenceAction, initialWorkflowCActionState);
  const [approveState, approveAction, approvePending] = useActionState(approveManualEvidenceAction, initialWorkflowCActionState);
  const [rejectState, rejectAction, rejectPending] = useActionState(rejectManualEvidenceAction, initialWorkflowCActionState);
  const manualTasks = tasks.filter((task) => task.capture_method === "manual_ui" && task.status === "planned");
  const pending = imports.filter((item) => item.status === "pending_review");
  const uploadDisabled = !canOperate || importPending || !runId || !manualTasks.length;

  return (
    <section className={styles.commandBand} aria-labelledby="manual-evidence-heading">
      <div className={styles.sectionHeading}>
        <div><p>Governed import</p><h3 id="manual-evidence-heading">手工 UI 证据</h3></div>
        <span>{pending.length} pending review</span>
      </div>
      <form action={importAction} className={styles.commandForm}>
        <input name="project_id" type="hidden" value={projectId} />
        <input name="run_id" type="hidden" value={runId || ""} />
        <input name="idempotency_key" type="hidden" value={`${commandKey}-import`} />
        <label><span>待采集 Task</span><select disabled={uploadDisabled} name="task_ref" required><option value="">选择 Task</option>{manualTasks.map((task) => <option key={task.id} value={`${task.id}:${task.version}`}>{task.question_id} · repeat {task.repetition}</option>)}</select></label>
        <label><span>证据类型</span><select disabled={uploadDisabled} name="evidence_kind"><option value="screenshot">Screenshot</option><option value="html_export">HTML export</option><option value="transcript_export">Transcript export</option></select></label>
        <label><span>文件</span><input accept=".html,.htm,.json,.txt,image/jpeg,image/png,image/webp" disabled={uploadDisabled} name="artifact" required type="file" /></label>
        <label><span>截图已脱敏</span><input disabled={uploadDisabled} name="pre_redacted_attestation" type="checkbox" /></label>
        <label><span>设备</span><select disabled={uploadDisabled} name="device"><option value="desktop">Desktop</option><option value="mobile">Mobile</option><option value="tablet">Tablet</option></select></label>
        <label><span>Locale</span><input defaultValue="en-AU" disabled={uploadDisabled} maxLength={100} name="locale" required /></label>
        <label><span>采集时间</span><input defaultValue={capturedAt} disabled={uploadDisabled} name="captured_at" required type="datetime-local" /></label>
        <button disabled={uploadDisabled} type="submit">{importPending ? "导入中..." : "导入并提交复核"}</button>
      </form>
      <WorkflowCActionFeedback state={importState} />

      {pending.map((item) => {
        const makerCannotReview = item.submitted_by === actorId;
        const reviewDisabled = !canReview || makerCannotReview;
        return (
          <div className={styles.commandGrid} key={item.id}>
            <form action={approveAction} className={styles.commandForm}>
              <ReviewIdentity commandKey={`${commandKey}-approve-${item.id}`} item={item} projectId={projectId} />
              <strong>{item.evidence_kind} · {item.locale}</strong>
              <code>{item.artifact_manifest_hash}</code>
              <label><span>批准原因</span><input disabled={reviewDisabled || approvePending} maxLength={1000} name="reason" required /></label>
              <button disabled={reviewDisabled || approvePending} type="submit">批准并入队</button>
            </form>
            <form action={rejectAction} className={styles.commandForm}>
              <ReviewIdentity commandKey={`${commandKey}-reject-${item.id}`} item={item} projectId={projectId} />
              <strong>{item.submitted_by}</strong>
              <code>{item.artifact_content_hash}</code>
              <label><span>拒绝原因</span><input disabled={reviewDisabled || rejectPending} maxLength={1000} name="reason" required /></label>
              <button disabled={reviewDisabled || rejectPending} type="submit">拒绝</button>
            </form>
          </div>
        );
      })}
      <WorkflowCActionFeedback state={approveState} />
      <WorkflowCActionFeedback state={rejectState} />
    </section>
  );
}

function ReviewIdentity({ commandKey, item, projectId }: { commandKey: string; item: ManualEvidenceImport; projectId: string }) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="import_id" type="hidden" value={item.id} /><input name="expected_version" type="hidden" value={item.aggregate_version} /><input name="idempotency_key" type="hidden" value={commandKey} /></>;
}
