"use client";

import { useActionState } from "react";

import {
  approveAdmissionPolicyAction,
  assessNoBasisAdmissionPolicyAction,
  createAdmissionPolicyAction,
  revokeAdmissionPolicyAction,
  submitAdmissionPolicyAction
} from "./admissionPolicyActions";
import { WorkflowCActionFeedback } from "./WorkflowCActionFeedback";
import {
  initialWorkflowCActionState,
  type AdmissionPolicy,
  type AdmissionRuntimeOption
} from "./workflowCTypes";
import styles from "./WorkflowCAlerts.module.css";

export type AdmissionPolicyCommandKeys = Readonly<{
  create: string;
  submit: string;
  approve: string;
  assessNoBasis: string;
  revoke: string;
}>;

export function AdmissionPolicyCommands({
  actorId,
  canManage,
  commandKeys,
  policies,
  policy,
  projectId,
  runtimeOptions,
  validUntilDefault
}: {
  actorId: string;
  canManage: boolean;
  commandKeys: AdmissionPolicyCommandKeys;
  policies: AdmissionPolicy[];
  policy: AdmissionPolicy | null;
  projectId: string;
  runtimeOptions: AdmissionRuntimeOption[];
  validUntilDefault: string;
}) {
  const [createState, createAction, createPending] = useActionState(
    createAdmissionPolicyAction,
    initialWorkflowCActionState
  );
  const [submitState, submitAction, submitPending] = useActionState(
    submitAdmissionPolicyAction,
    initialWorkflowCActionState
  );
  const [approveState, approveAction, approvePending] = useActionState(
    approveAdmissionPolicyAction,
    initialWorkflowCActionState
  );
  const [noBasisState, noBasisAction, noBasisPending] = useActionState(
    assessNoBasisAdmissionPolicyAction,
    initialWorkflowCActionState
  );
  const [revokeState, revokeAction, revokePending] = useActionState(
    revokeAdmissionPolicyAction,
    initialWorkflowCActionState
  );
  const canCheck = canManage && Boolean(policy) && policy?.created_by !== actorId;
  const allowedPurposes = Array.from(
    new Set(runtimeOptions.flatMap((option) => option.allowed_purposes))
  ).sort();
  const createDisabled = !canManage || createPending || !runtimeOptions.length;

  return (
    <section className={styles.commandBand} aria-labelledby="admission-command-heading">
      <div className={styles.sectionHeading}>
        <div>
          <p>控制面</p>
          <h3 id="admission-command-heading">授权策略操作</h3>
        </div>
        <span>{canManage ? "所有者 / 管理员" : "只读"}</span>
      </div>
      <form action={createAction} className={styles.commandForm}>
        <input name="project_id" type="hidden" value={projectId} />
        <input name="idempotency_key" type="hidden" value={commandKeys.create} />
        <label>
          <span>已发布运行授权</span>
          <select disabled={createDisabled} name="runtime_authorization_option_key" required>
            <option value="">选择运行授权</option>
            {runtimeOptions.map((option) => (
              <option key={option.option_key} value={option.option_key}>
                {option.display_name} · {option.location_control}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>授权用途</span>
          <select disabled={createDisabled || !allowedPurposes.length} name="purpose" required>
            <option value="">选择用途</option>
            {allowedPurposes.map((purpose) => <option key={purpose} value={purpose}>{purpose}</option>)}
          </select>
        </label>
        <label><span>有效期</span><input defaultValue={validUntilDefault} disabled={createDisabled} name="valid_until" required type="datetime-local" /></label>
        <label><span>总配额</span><input defaultValue="10" disabled={createDisabled} min="1" name="quota_remaining" required type="number" /></label>
        <label><span>日配额</span><input defaultValue="10" disabled={createDisabled} min="1" name="daily_task_limit" required type="number" /></label>
        <label><span>最小间隔（秒）</span><input defaultValue="2" disabled={createDisabled} min="0" name="minimum_request_interval_seconds" required type="number" /></label>
        <label><span>最大并发</span><input defaultValue="1" disabled={createDisabled} min="1" name="max_concurrency" required type="number" /></label>
        <label>
          <span>替代现有策略（可选）</span>
          <select disabled={createDisabled} name="supersedes_policy_id">
            <option value="">不替代</option>
            {policies.map((item) => (
              <option key={item.id} value={item.id}>
                {item.platform} · r{item.revision} · {item.status}
              </option>
            ))}
          </select>
        </label>
        <button disabled={createDisabled} type="submit">
          {createPending ? "创建中..." : "创建草稿"}
        </button>
      </form>
      <WorkflowCActionFeedback state={createState} />

      {policy ? (
        <div className={styles.commandGrid}>
          <TransitionForm
            action={submitAction}
            button="提交复核"
            commandKey={commandKeys.submit}
            disabled={!canManage || policy.status !== "draft" || submitPending}
            pending={submitPending}
            policy={policy}
            projectId={projectId}
          />
          <TransitionForm
            action={approveAction}
            button="批准"
            commandKey={commandKeys.approve}
            disabled={!canCheck || policy.status !== "pending_review" || approvePending}
            pending={approvePending}
            policy={policy}
            projectId={projectId}
            reason
          />
          <TransitionForm
            action={noBasisAction}
            button="记录无依据"
            commandKey={commandKeys.assessNoBasis}
            disabled={!canCheck || policy.status !== "pending_review" || noBasisPending}
            pending={noBasisPending}
            policy={policy}
            projectId={projectId}
            reason
          />
          <TransitionForm
            action={revokeAction}
            button="撤销"
            commandKey={commandKeys.revoke}
            disabled={!canManage || policy.status !== "approved" || revokePending}
            pending={revokePending}
            policy={policy}
            projectId={projectId}
            reason
          />
        </div>
      ) : null}
      <WorkflowCActionFeedback state={submitState} />
      <WorkflowCActionFeedback state={approveState} />
      <WorkflowCActionFeedback state={noBasisState} />
      <WorkflowCActionFeedback state={revokeState} />
    </section>
  );
}

function TransitionForm({
  action,
  button,
  commandKey,
  disabled,
  pending,
  policy,
  projectId,
  reason = false
}: {
  action: (payload: FormData) => void;
  button: string;
  commandKey: string;
  disabled: boolean;
  pending: boolean;
  policy: AdmissionPolicy;
  projectId: string;
  reason?: boolean;
}) {
  return (
    <form action={action} className={styles.commandForm}>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="policy_id" type="hidden" value={policy.id} />
      <input name="expected_version" type="hidden" value={policy.aggregate_version} />
      <input name="idempotency_key" type="hidden" value={commandKey} />
      {reason ? (
        <label><span>决策原因</span><input disabled={disabled} maxLength={1000} name="reason" required /></label>
      ) : null}
      <button disabled={disabled} type="submit">{pending ? "提交中..." : button}</button>
    </form>
  );
}
