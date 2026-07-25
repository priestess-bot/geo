"use client";

import { useActionState, useState } from "react";

import {
  createAuthorizationAction,
  decideStyleProfileAction,
  decideAuthorizationAction,
  freezeReviewSuiteAction,
  freezeStyleProfileAction,
  reassessAuthorizationAction,
  submitStyleProfileAction,
  revokeAuthorizationAction
} from "./syntheticLabGovernanceActions";
import { SyntheticActionFeedback } from "./SyntheticActionFeedback";
import {
  initialSyntheticActionState,
  type CollectionAuthorization,
  type ReviewCase,
  type ReviewSuite,
  type StyleProfile,
  syntheticChannels
} from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

export function CreateAuthorizationForm({
  canCreate,
  commandKey,
  projectId
}: {
  canCreate: boolean;
  commandKey: string;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(
    createAuthorizationAction, initialSyntheticActionState
  );
  return (
    <form action={action} className={styles.compactForm}>
      <CommonHidden idempotencyKey={commandKey} projectId={projectId} />
      <label><span>Channel</span><select name="channel">{syntheticChannels.map((channel) => <option key={channel} value={channel}>{channel}</option>)}</select></label>
      <label className={styles.grow}><span>Adapter release</span><input maxLength={200} name="adapter_release" required /></label>
      <button disabled={!canCreate || pending} type="submit">{pending ? "创建中..." : "创建待评估记录"}</button>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

export function AuthorizationCommands({
  authorization,
  canApprove,
  canReassess,
  commandKeys,
  projectId
}: {
  authorization: CollectionAuthorization;
  canApprove: boolean;
  canReassess: boolean;
  commandKeys: { decide: string; reassess: string; revoke: string };
  projectId: string;
}) {
  const [decisionState, decisionAction, decisionPending] = useActionState(
    decideAuthorizationAction, initialSyntheticActionState
  );
  const [revokeState, revokeAction, revokePending] = useActionState(
    revokeAuthorizationAction, initialSyntheticActionState
  );
  const [reassessState, reassessAction, reassessPending] = useActionState(
    reassessAuthorizationAction, initialSyntheticActionState
  );
  const [decision, setDecision] = useState("");
  const approvalSelected = decision === "approved";
  const decisionOpen = authorization.effective_state === "not_assessed";
  const reassessable = ["assessed_no_basis", "revoked", "expired"]
    .includes(authorization.effective_state);
  return (
    <details className={styles.inlineDetails}>
      <summary>决策、撤销与重评</summary>
      <form action={decisionAction} className={styles.writeForm}>
        <CommonHidden idempotencyKey={commandKeys.decide} projectId={projectId} />
        <input name="authorization_id" type="hidden" value={authorization.id} />
        <input name="expected_version" type="hidden" value={authorization.version_number} />
        <fieldset disabled={!canApprove || decisionPending || !decisionOpen}>
          <legend>{authorization.channel} · {authorization.adapter_release}</legend>
          <div className={styles.formGridThree}>
            <label><span>Decision</span><select aria-label="Authorization 决策" name="decision" onChange={(event) => setDecision(event.target.value)} required value={decision}><option disabled value="">请选择决定</option><option value="approved">approved</option><option value="assessed_no_basis">assessed_no_basis</option></select></label>
            <label><span>证据引用</span><input disabled={!approvalSelected} maxLength={2000} name="evidence_reference" required={approvalSelected} /></label>
            <label><span>允许用途</span><span><input disabled={!approvalSelected} name="allowed_purposes" required={approvalSelected} type="checkbox" value="style_collection" /> 自动风格采集</span></label>
            <label><span>Requests / period</span><input disabled={!approvalSelected} min={1} name="max_requests_per_period" required={approvalSelected} type="number" /></label>
            <label><span>Period seconds</span><input disabled={!approvalSelected} min={1} name="period_seconds" required={approvalSelected} type="number" /></label>
            <label><span>Max concurrency</span><input disabled={!approvalSelected} min={1} name="max_concurrency" required={approvalSelected} type="number" /></label>
            <label><span>Expires at</span><input disabled={!approvalSelected} name="expires_at" required={approvalSelected} type="datetime-local" /></label>
            <label className={styles.spanTwo}><span>决策理由</span><input maxLength={2000} name="decision_reason" required /></label>
            <button disabled={!canApprove || decisionPending || !decisionOpen || !decision} type="submit">{decisionPending ? "记录中..." : "记录授权决策"}</button>
          </div>
          <p className={styles.formNote} role="status">{authorizationDecisionNote(decision)}</p>
        </fieldset>
        <SyntheticActionFeedback state={decisionState} />
      </form>
      <form action={revokeAction} className={styles.compactForm}>
        <CommonHidden idempotencyKey={commandKeys.revoke} projectId={projectId} />
        <input name="authorization_id" type="hidden" value={authorization.id} />
        <input name="expected_version" type="hidden" value={authorization.version_number} />
        <label><span>撤销理由</span><input maxLength={2000} name="decision_reason" required /></label>
        <button className="danger" disabled={!canApprove || revokePending || authorization.state !== "approved"} type="submit">{revokePending ? "撤销中..." : "撤销授权"}</button>
        <SyntheticActionFeedback state={revokeState} />
      </form>
      <form action={reassessAction} className={styles.compactForm}>
        <CommonHidden idempotencyKey={commandKeys.reassess} projectId={projectId} />
        <input name="authorization_id" type="hidden" value={authorization.id} />
        <input name="expected_version" type="hidden" value={authorization.version_number} />
        <label><span>重评理由</span><input maxLength={2000} name="reassessment_reason" required /></label>
        <button disabled={!canReassess || reassessPending || !reassessable} type="submit">
          {reassessPending ? "开启中..." : "开启重评版本"}
        </button>
        <SyntheticActionFeedback state={reassessState} />
      </form>
    </details>
  );
}

export function ProfileCommands({
  canApprove,
  canContribute,
  commandKeys,
  profile,
  projectId
}: {
  canApprove: boolean;
  canContribute: boolean;
  commandKeys: { decision: string; freeze: string; submit: string };
  profile: StyleProfile;
  projectId: string;
}) {
  const [submitState, submitAction, submitPending] = useActionState(submitStyleProfileAction, initialSyntheticActionState);
  const [decisionState, decisionAction, decisionPending] = useActionState(decideStyleProfileAction, initialSyntheticActionState);
  const [freezeState, freezeAction, freezePending] = useActionState(freezeStyleProfileAction, initialSyntheticActionState);
  const [decision, setDecision] = useState("");
  return (
    <div className={styles.actionStack}>
      <form action={submitAction} className={styles.compactForm}>
        <CommonHidden idempotencyKey={commandKeys.submit} projectId={projectId} />
        <input name="profile_version_id" type="hidden" value={profile.id} />
        <input name="expected_version" type="hidden" value={profile.state_version} />
        <button disabled={!canContribute || submitPending || profile.status !== "draft"} type="submit">{submitPending ? "提交中..." : "提交审批"}</button>
        <SyntheticActionFeedback state={submitState} />
      </form>
      <form action={decisionAction} className={styles.compactForm}>
        <CommonHidden idempotencyKey={commandKeys.decision} projectId={projectId} />
        <input name="profile_version_id" type="hidden" value={profile.id} />
        <input name="expected_version" type="hidden" value={profile.state_version} />
        <select aria-label="Profile 审批决定" disabled={!canApprove || decisionPending || profile.status !== "in_review"} name="decision" onChange={(event) => setDecision(event.target.value)} required value={decision}><option disabled value="">请选择决定</option><option value="approve">批准</option><option value="reject">拒绝</option></select>
        <button disabled={!canApprove || decisionPending || profile.status !== "in_review" || !decision} type="submit">{decisionPending ? "记录中..." : "记录决定"}</button>
        <p className={styles.formNote} role="status">{!canApprove ? "当前项目角色没有 Profile 审批权限。" : decision ? "服务端将再次验证审批角色与独立复核条件。" : "尚未选择 Profile 审批决定。"}</p>
        <SyntheticActionFeedback state={decisionState} />
      </form>
      <details className={styles.inlineDetails}>
        <summary>冻结批准版本</summary>
        <form action={freezeAction} className={styles.writeForm}>
          <CommonHidden idempotencyKey={commandKeys.freeze} projectId={projectId} />
          <input name="profile_version_id" type="hidden" value={profile.id} />
          <input name="expected_version" type="hidden" value={profile.state_version} />
          <p className={styles.formNote}>冻结时由服务端复核创建 Profile 时保存的样本 manifest、已完成 build 与审批状态。</p>
          <button disabled={!canApprove || freezePending || profile.status !== "approved"} type="submit">{freezePending ? "冻结中..." : "冻结 Profile"}</button>
          <SyntheticActionFeedback state={freezeState} />
        </form>
      </details>
    </div>
  );
}

export function FreezeSuiteForm({
  canApprove,
  cases,
  commandKey,
  projectId,
  suite
}: {
  canApprove: boolean;
  cases: ReviewCase[];
  commandKey: string;
  projectId: string;
  suite: ReviewSuite;
}) {
  const [state, action, pending] = useActionState(freezeReviewSuiteAction, initialSyntheticActionState);
  return (
    <form action={action} className={styles.compactForm}>
      <CommonHidden idempotencyKey={commandKey} projectId={projectId} />
      <input name="suite_version_id" type="hidden" value={suite.id} />
      <input name="expected_version" type="hidden" value={suite.state_version} />
      <span className={styles.grow}>{cases.length} 个当前 Case</span>
      <button disabled={!canApprove || pending || suite.status === "frozen" || cases.length === 0} type="submit">{pending ? "冻结中..." : "冻结 Suite"}</button>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

function CommonHidden({ idempotencyKey, projectId }: { idempotencyKey: string; projectId: string }) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="idempotency_key" type="hidden" value={idempotencyKey} /></>;
}

function authorizationDecisionNote(decision: string): string {
  if (decision === "approved") {
    return "批准需要完整证据、采集用途、请求配额、周期、并发与失效时间。";
  }
  if (decision === "assessed_no_basis") return "无依据决定不会授予任何采集用途或配额。";
  return "尚未选择授权决定；当前表单不会授予采集权限。";
}
