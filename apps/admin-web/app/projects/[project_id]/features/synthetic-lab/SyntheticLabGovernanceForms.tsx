"use client";

import { useActionState } from "react";

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
  type SyntheticResourceOption,
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
  const terminal = ["assessed_no_basis", "revoked", "expired"].includes(authorization.effective_state);
  const reassessable = terminal;
  return (
    <details className={styles.inlineDetails}>
      <summary>决策、撤销与重评</summary>
      <form action={decisionAction} className={styles.writeForm}>
        <CommonHidden idempotencyKey={commandKeys.decide} projectId={projectId} />
        <input name="authorization_id" type="hidden" value={authorization.id} />
        <input name="expected_version" type="hidden" value={authorization.version_number} />
        <fieldset disabled={!canApprove || decisionPending || terminal}>
          <legend>{authorization.channel} · {authorization.adapter_release}</legend>
          <div className={styles.formGridThree}>
            <label><span>Decision</span><select defaultValue="approved" name="decision"><option value="approved">approved</option><option value="assessed_no_basis">assessed_no_basis</option></select></label>
            <label><span>证据引用</span><input maxLength={2000} name="evidence_reference" /></label>
            <label><span>允许用途</span><span><input defaultChecked name="allowed_purposes" type="checkbox" value="style_collection" /> 自动风格采集</span></label>
            <label><span>Requests / period</span><input min={1} name="max_requests_per_period" type="number" /></label>
            <label><span>Period seconds</span><input min={1} name="period_seconds" type="number" /></label>
            <label><span>Max concurrency</span><input min={1} name="max_concurrency" type="number" /></label>
            <label><span>Expires at</span><input name="expires_at" type="datetime-local" /></label>
            <label className={styles.spanTwo}><span>决策理由</span><input maxLength={2000} name="decision_reason" required /></label>
            <button disabled={!canApprove || decisionPending || terminal} type="submit">{decisionPending ? "记录中..." : "记录授权决策"}</button>
          </div>
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
  projectId,
  samples
}: {
  canApprove: boolean;
  canContribute: boolean;
  commandKeys: { decision: string; freeze: string; submit: string };
  profile: StyleProfile;
  projectId: string;
  samples: SyntheticResourceOption[];
}) {
  const [submitState, submitAction, submitPending] = useActionState(submitStyleProfileAction, initialSyntheticActionState);
  const [decisionState, decisionAction, decisionPending] = useActionState(decideStyleProfileAction, initialSyntheticActionState);
  const [freezeState, freezeAction, freezePending] = useActionState(freezeStyleProfileAction, initialSyntheticActionState);
  return (
    <div className={styles.actionStack}>
      <form action={submitAction} className={styles.compactForm}>
        <CommonHidden idempotencyKey={commandKeys.submit} projectId={projectId} />
        <input name="profile_version_id" type="hidden" value={profile.id} />
        <input name="expected_version" type="hidden" value={profile.version_number} />
        <button disabled={!canContribute || submitPending || profile.status !== "draft"} type="submit">{submitPending ? "提交中..." : "提交审批"}</button>
        <SyntheticActionFeedback state={submitState} />
      </form>
      <form action={decisionAction} className={styles.compactForm}>
        <CommonHidden idempotencyKey={commandKeys.decision} projectId={projectId} />
        <input name="profile_version_id" type="hidden" value={profile.id} />
        <input name="expected_version" type="hidden" value={profile.version_number} />
        <select aria-label="Profile 审批决定" defaultValue="approve" name="decision"><option value="approve">批准</option><option value="reject">拒绝</option></select>
        <button disabled={!canApprove || decisionPending || profile.status !== "in_review"} type="submit">{decisionPending ? "记录中..." : "记录决定"}</button>
        <SyntheticActionFeedback state={decisionState} />
      </form>
      <details className={styles.inlineDetails}>
        <summary>冻结批准版本</summary>
        <form action={freezeAction} className={styles.writeForm}>
          <CommonHidden idempotencyKey={commandKeys.freeze} projectId={projectId} />
          <input name="profile_version_id" type="hidden" value={profile.id} />
          <input name="expected_version" type="hidden" value={profile.version_number} />
          <div className={styles.checkRow}>{samples.filter((sample) => sample.channel === profile.channel).map((sample) => <label key={sample.id}><input name="approved_sample_ids" type="checkbox" value={sample.id} /> {sample.label}</label>)}</div>
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
      <input name="expected_version" type="hidden" value={suite.version_number} />
      <span className={styles.grow}>{cases.length} 个当前 Case</span>
      <button disabled={!canApprove || pending || suite.status === "frozen" || cases.length === 0} type="submit">{pending ? "冻结中..." : "冻结 Suite"}</button>
      <SyntheticActionFeedback state={state} />
    </form>
  );
}

function CommonHidden({ idempotencyKey, projectId }: { idempotencyKey: string; projectId: string }) {
  return <><input name="project_id" type="hidden" value={projectId} /><input name="idempotency_key" type="hidden" value={idempotencyKey} /></>;
}
