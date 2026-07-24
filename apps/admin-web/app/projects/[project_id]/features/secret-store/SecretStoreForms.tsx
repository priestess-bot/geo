"use client";

import { useActionState } from "react";

import {
  activateSecretVersionAction,
  createSecretReferenceAction,
  revokeSecretVersionAction,
  stageSecretRotationAction,
  verifySecretVersionAction
} from "./secretStoreActions";
import { SecretActionFeedback } from "./SecretActionFeedback";
import {
  SECRET_MAX_BYTES,
  SECRET_PURPOSE_GROUPS,
  initialSecretActionState,
  type SecretAuditEvent,
  type SecretReference
} from "./secretStoreTypes";
import styles from "./SecretStore.module.css";

export function CreateSecretReferenceForm({
  canManage,
  idempotencyKey,
  projectId
}: {
  canManage: boolean;
  idempotencyKey: string;
  projectId: string;
}) {
  const [state, action, pending] = useActionState(
    createSecretReferenceAction,
    initialSecretActionState
  );
  return (
    <form action={action} className={styles.writeForm}>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="expected_version" type="hidden" value={0} />
      <input name="idempotency_key" type="hidden" value={idempotencyKey} />
      <fieldset disabled={!canManage || pending}>
        <legend>创建 Secret Reference</legend>
        <div className={styles.createGrid}>
          <label>
            <span>用途</span>
            <select defaultValue="" name="purpose" required>
              <option disabled value="">选择用途</option>
              {SECRET_PURPOSE_GROUPS.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.options.map(([key, label]) => (
                    <option key={key} value={key}>{label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <WriteOnlySecretInput inputKey={state.responseToken || "secret-create-initial"} />
          <button disabled={!canManage || pending} type="submit">{pending ? "创建中..." : "创建 Reference"}</button>
        </div>
      </fieldset>
      <SecretActionFeedback state={state} />
    </form>
  );
}

export function SecretLifecycleForms({
  audits,
  canManage,
  commandKeys,
  projectId,
  reference
}: {
  audits: SecretAuditEvent[];
  canManage: boolean;
  commandKeys: Readonly<{
    activate: string;
    revoke: string;
    rotate: string;
    verify: string;
  }>;
  projectId: string;
  reference: SecretReference;
}) {
  const [verifyState, verifyAction, verifyPending] = useActionState(
    verifySecretVersionAction,
    initialSecretActionState
  );
  const [activateState, activateAction, activatePending] = useActionState(
    activateSecretVersionAction,
    initialSecretActionState
  );
  const [rotationState, rotationAction, rotationPending] = useActionState(
    stageSecretRotationAction,
    initialSecretActionState
  );
  const [revokeState, revokeAction, revokePending] = useActionState(
    revokeSecretVersionAction,
    initialSecretActionState
  );
  const latestActions = new Set(
    audits.filter((item) => item.version === reference.latest_version).map((item) => item.action)
  );
  const hasPending = reference.current_version === null
    || reference.latest_version > reference.current_version;
  const verified = latestActions.has("version_verified");
  const terminal = latestActions.has("version_activated") || latestActions.has("version_revoked");
  const anyPending = verifyPending || activatePending || rotationPending || revokePending;
  const canVerify = canManage && hasPending && !verified && !terminal;
  const canActivate = canManage && hasPending && verified && !terminal;
  const canRotate = canManage
    && reference.current_version !== null
    && reference.latest_version === reference.current_version;
  const canRevoke = canManage && reference.latest_version > 0;

  return (
    <div className={styles.lifecycleStack}>
      <section className={styles.commandBand} aria-labelledby="secret-verify-heading">
        <header><h4 id="secret-verify-heading">Canary 验证与双人激活</h4><span>目标 v{reference.latest_version}</span></header>
        <div className={styles.commandRow}>
          <form action={verifyAction}>
            <TransitionFields commandKey={commandKeys.verify} projectId={projectId} reference={reference} version={reference.latest_version} />
            <button disabled={!canVerify || anyPending} title={canVerify ? "" : "仅未验证的 Pending 版本可验证"} type="submit">
              {verifyPending ? "验证中..." : "验证 Canary"}
            </button>
          </form>
          <form action={activateAction}>
            <TransitionFields commandKey={commandKeys.activate} projectId={projectId} reference={reference} version={reference.latest_version} />
            <button className="secondary" disabled={!canActivate || anyPending} title={canActivate ? "" : "需先验证，并由非创建者激活"} type="submit">
              {activatePending ? "激活中..." : "第二人激活"}
            </button>
          </form>
        </div>
        <SecretActionFeedback state={verifyState} />
        <SecretActionFeedback state={activateState} />
      </section>

      <section className={styles.commandBand} aria-labelledby="secret-rotate-heading">
        <header><h4 id="secret-rotate-heading">Stage Rotation</h4><span>Aggregate v{reference.aggregate_version}</span></header>
        <form action={rotationAction} className={styles.rotationForm}>
          <input name="project_id" type="hidden" value={projectId} />
          <input name="reference_id" type="hidden" value={reference.reference_id} />
          <input name="expected_version" type="hidden" value={reference.aggregate_version} />
          <input name="idempotency_key" type="hidden" value={commandKeys.rotate} />
          <WriteOnlySecretInput
            disabled={!canRotate || anyPending}
            inputKey={rotationState.responseToken || `secret-rotate-${reference.reference_id}`}
          />
          <button disabled={!canRotate || anyPending} title={canRotate ? "" : "需先完成当前 Pending 版本"} type="submit">
            {rotationPending ? "暂存中..." : "暂存新版本"}
          </button>
        </form>
        <SecretActionFeedback state={rotationState} />
      </section>

      <section className={styles.commandBand} aria-labelledby="secret-revoke-heading">
        <header><h4 id="secret-revoke-heading">Revoke Version</h4></header>
        <form action={revokeAction} className={styles.revokeForm}>
          <input name="project_id" type="hidden" value={projectId} />
          <input name="reference_id" type="hidden" value={reference.reference_id} />
          <input name="expected_version" type="hidden" value={reference.aggregate_version} />
          <input name="idempotency_key" type="hidden" value={commandKeys.revoke} />
          <label><span>Secret version</span><input defaultValue={reference.current_version || reference.latest_version} disabled={!canRevoke || anyPending} min={1} name="version" required type="number" /></label>
          <button className="danger" disabled={!canRevoke || anyPending} type="submit">
            {revokePending ? "撤销中..." : "撤销版本"}
          </button>
        </form>
        <SecretActionFeedback state={revokeState} />
      </section>
    </div>
  );
}

function TransitionFields({
  commandKey,
  projectId,
  reference,
  version
}: {
  commandKey: string;
  projectId: string;
  reference: SecretReference;
  version: number;
}) {
  return (
    <>
      <input name="project_id" type="hidden" value={projectId} />
      <input name="reference_id" type="hidden" value={reference.reference_id} />
      <input name="version" type="hidden" value={version} />
      <input name="expected_version" type="hidden" value={reference.aggregate_version} />
      <input name="idempotency_key" type="hidden" value={commandKey} />
    </>
  );
}

function WriteOnlySecretInput({
  disabled = false,
  inputKey
}: {
  disabled?: boolean;
  inputKey: string;
}) {
  return (
    <label>
      <span>SecretValue · write-only · max 64 KiB</span>
      <input
        autoComplete="new-password"
        disabled={disabled}
        key={inputKey}
        maxLength={SECRET_MAX_BYTES}
        name="secret_value"
        required
        spellCheck={false}
        type="password"
      />
    </label>
  );
}
