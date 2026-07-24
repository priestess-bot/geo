"use client";

import { useActionState } from "react";

import {
  acknowledgeWorkflowCAlertAction,
  resolveWorkflowCAlertAction,
  suppressWorkflowCAlertAction,
  unsuppressWorkflowCAlertAction
} from "./workflowCActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import {
  initialWorkflowCActionState,
  type AlertRecord
} from "./workflowCTypes";
import styles from "./WorkflowCAlerts.module.css";

export type AlertCommandKeys = Readonly<{
  acknowledge: string;
  suppress: string;
  unsuppress: string;
  resolve: string;
}>;

export function AlertCommands({
  alert,
  canAct,
  commandKeys,
  projectId,
  suppressionDefault
}: {
  alert: AlertRecord;
  canAct: boolean;
  commandKeys: AlertCommandKeys;
  projectId: string;
  suppressionDefault: string;
}) {
  const [ackState, ackAction, ackPending] = useActionState(
    acknowledgeWorkflowCAlertAction,
    initialWorkflowCActionState
  );
  const [suppressState, suppressAction, suppressPending] = useActionState(
    suppressWorkflowCAlertAction,
    initialWorkflowCActionState
  );
  const [unsuppressState, unsuppressAction, unsuppressPending] = useActionState(
    unsuppressWorkflowCAlertAction,
    initialWorkflowCActionState
  );
  const [resolveState, resolveAction, resolvePending] = useActionState(
    resolveWorkflowCAlertAction,
    initialWorkflowCActionState
  );
  const open = alert.status === "open";
  const suppressed = alert.status === "suppressed";
  const active = alert.status !== "resolved";

  return (
    <section className={styles.commandBand} aria-labelledby="alert-command-heading">
      <div className={styles.sectionHeading}>
        <div><p>Disposition</p><h3 id="alert-command-heading">处置 Alert</h3></div>
        <span>{canAct ? "可处置" : "只读"}</span>
      </div>
      <div className={styles.commandGrid}>
        <CommandForm
          action={ackAction}
          alert={alert}
          button="确认"
          commandKey={commandKeys.acknowledge}
          disabled={!canAct || !open || ackPending}
          pending={ackPending}
          projectId={projectId}
        />
        <form action={suppressAction} className={styles.commandForm}>
          <HiddenFields alert={alert} commandKey={commandKeys.suppress} projectId={projectId} />
          <label><span>抑制原因</span><input disabled={!canAct || !active || suppressed || suppressPending} maxLength={1000} name="reason" required /></label>
          <label><span>抑制至</span><input defaultValue={suppressionDefault} disabled={!canAct || !active || suppressed || suppressPending} name="suppressed_until" required type="datetime-local" /></label>
          <button disabled={!canAct || !active || suppressed || suppressPending} type="submit">
            {suppressPending ? "提交中..." : "抑制"}
          </button>
        </form>
        <CommandForm
          action={unsuppressAction}
          alert={alert}
          button="解除抑制"
          commandKey={commandKeys.unsuppress}
          disabled={!canAct || !suppressed || unsuppressPending}
          pending={unsuppressPending}
          projectId={projectId}
        />
        <CommandForm
          action={resolveAction}
          alert={alert}
          button="解决"
          commandKey={commandKeys.resolve}
          disabled={!canAct || !active || resolvePending}
          pending={resolvePending}
          projectId={projectId}
        />
      </div>
      <WorkflowCActionFeedback state={ackState} />
      <WorkflowCActionFeedback state={suppressState} />
      <WorkflowCActionFeedback state={unsuppressState} />
      <WorkflowCActionFeedback state={resolveState} />
    </section>
  );
}

function CommandForm({
  action,
  alert,
  button,
  commandKey,
  disabled,
  pending,
  projectId
}: {
  action: (payload: FormData) => void;
  alert: AlertRecord;
  button: string;
  commandKey: string;
  disabled: boolean;
  pending: boolean;
  projectId: string;
}) {
  return (
    <form action={action} className={styles.commandForm}>
      <HiddenFields alert={alert} commandKey={commandKey} projectId={projectId} />
      <label><span>处置原因</span><input disabled={disabled} maxLength={1000} name="reason" required /></label>
      <button disabled={disabled} type="submit">{pending ? "提交中..." : button}</button>
    </form>
  );
}

function HiddenFields({
  alert,
  commandKey,
  projectId
}: {
  alert: AlertRecord;
  commandKey: string;
  projectId: string;
}) {
  return (
    <>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="alert_id" type="hidden" value={alert.id} />
      <input name="expected_version" type="hidden" value={alert.version} />
      <input name="idempotency_key" type="hidden" value={commandKey} />
    </>
  );
}
