"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  commandFailure,
  commandKey,
  field,
  integerField,
  invalid,
  optionalPositiveInteger,
  requiredField,
  safeState,
  syntheticBase,
  upstreamInvalid,
  UUID_PATTERN,
  verifySyntheticActor
} from "./syntheticLabActionSupport";
import {
  isAuthorization,
  isReviewSuite,
  isStyleProfile,
  syntheticChannels,
  type CollectionAuthorization,
  type ReviewSuite,
  type StyleProfile,
  type SyntheticActionState
} from "./syntheticLabTypes";

const APPROVERS = ["owner", "admin"] as const;
const CONTRIBUTORS = ["owner", "admin", "analyst"] as const;

export async function createAuthorizationAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  const channel = field(formData, "channel");
  const adapterRelease = requiredField(formData, "adapter_release", 200);
  const key = commandKey(formData);
  if (!syntheticChannels.includes(channel as (typeof syntheticChannels)[number])
    || !adapterRelease || !key) {
    return invalid("Channel、adapter release 或 Idempotency-Key 无效。");
  }
  const response = await runtimeRequest<CollectionAuthorization>(syntheticBase(projectId) + "/authorizations", {
    method: "POST",
    idempotencyKey: key,
    body: { expected_version: 0, channel, adapter_release: adapterRelease }
  });
  return authorizationResult(response, projectId, "Authorization 待评估记录已创建。");
}

export async function decideAuthorizationAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  const authorizationId = field(formData, "authorization_id");
  const expectedVersion = integerField(formData, "expected_version", 0);
  const decision = field(formData, "decision");
  const reason = requiredField(formData, "decision_reason", 2000);
  const evidenceReference = field(formData, "evidence_reference");
  const allowedPurposes = formData.getAll("allowed_purposes")
    .filter((item): item is string => typeof item === "string");
  const maxRequests = optionalPositiveInteger(formData, "max_requests_per_period");
  const periodSeconds = optionalPositiveInteger(formData, "period_seconds");
  const maxConcurrency = optionalPositiveInteger(formData, "max_concurrency");
  const expiresAt = optionalIsoDate(field(formData, "expires_at"));
  if (!UUID_PATTERN.test(authorizationId) || expectedVersion === null || !reason) {
    return invalid("Authorization、版本或决策理由无效。");
  }
  if (decision !== "approved" && decision !== "assessed_no_basis") {
    return invalid("Authorization 决策无效。");
  }
  if (evidenceReference.length > 2000
    || allowedPurposes.some((purpose) => purpose !== "style_collection")
    || new Set(allowedPurposes).size !== allowedPurposes.length
    || maxRequests === undefined || periodSeconds === undefined || maxConcurrency === undefined
    || expiresAt === undefined) {
    return invalid("证据、用途、限流或失效时间无效。");
  }
  if (decision === "approved" && (!evidenceReference || allowedPurposes.length === 0)) {
    return invalid("批准必须包含证据引用和至少一个允许用途。");
  }
  const key = commandKey(formData);
  if (!key) return invalid("Idempotency-Key 无效，请刷新后重试。");
  const response = await runtimeRequest<CollectionAuthorization>(
    `${syntheticBase(projectId)}/authorizations/${encodeURIComponent(authorizationId)}/decision`,
    {
      method: "POST",
      idempotencyKey: key,
      body: {
        expected_version: expectedVersion,
        decision,
        evidence_reference: evidenceReference || null,
        allowed_purposes: allowedPurposes,
        max_requests_per_period: maxRequests,
        period_seconds: periodSeconds,
        max_concurrency: maxConcurrency,
        expires_at: expiresAt,
        decision_reason: reason
      }
    }
  );
  return authorizationResult(response, projectId, "Authorization 决策已记录。");
}

export async function revokeAuthorizationAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  const authorizationId = field(formData, "authorization_id");
  const expectedVersion = integerField(formData, "expected_version", 1);
  const reason = requiredField(formData, "decision_reason", 2000);
  const key = commandKey(formData);
  if (!UUID_PATTERN.test(authorizationId) || expectedVersion === null || !reason || !key) {
    return invalid("Authorization、版本、撤销理由或 Idempotency-Key 无效。");
  }
  const response = await runtimeRequest<CollectionAuthorization>(
    `${syntheticBase(projectId)}/authorizations/${encodeURIComponent(authorizationId)}/revoke`,
    {
      method: "POST",
      idempotencyKey: key,
      body: { expected_version: expectedVersion, decision_reason: reason }
    }
  );
  return authorizationResult(response, projectId, "Authorization 已撤销。");
}

export async function reassessAuthorizationAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const authorizationId = field(formData, "authorization_id");
  const expectedVersion = integerField(formData, "expected_version", 1);
  const reason = requiredField(formData, "reassessment_reason", 2000);
  const key = commandKey(formData);
  if (!UUID_PATTERN.test(authorizationId) || expectedVersion === null || !reason || !key) {
    return invalid("Authorization、版本、重评理由或 Idempotency-Key 无效。");
  }
  const response = await runtimeRequest<CollectionAuthorization>(
    `${syntheticBase(projectId)}/authorizations/${encodeURIComponent(authorizationId)}/reassess`,
    {
      method: "POST",
      idempotencyKey: key,
      body: {
        expected_version: expectedVersion,
        opened_at: new Date().toISOString(),
        reassessment_reason: reason
      }
    }
  );
  return authorizationResult(response, projectId, "Authorization 重评版本已开启，等待独立审批。");
}

export async function freezeStyleProfileAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  const profileVersionId = field(formData, "profile_version_id");
  const expectedVersion = integerField(formData, "expected_version", 1);
  const approvedSampleIds = formData.getAll("approved_sample_ids").map(String);
  const key = commandKey(formData);
  if (!UUID_PATTERN.test(profileVersionId) || expectedVersion === null
    || approvedSampleIds.length < 200 || approvedSampleIds.length > 10_000
    || approvedSampleIds.some((value) => !UUID_PATTERN.test(value))
    || approvedSampleIds.length !== new Set(approvedSampleIds).size || !key) {
    return invalid("Profile、版本或批准样本选择无效；冻结至少需要 200 个样本。");
  }
  const response = await runtimeRequest<StyleProfile>(
    `${syntheticBase(projectId)}/style-profiles/${encodeURIComponent(profileVersionId)}/freeze`,
    {
      method: "POST",
      idempotencyKey: key,
      body: { expected_version: expectedVersion, approved_sample_ids: approvedSampleIds }
    }
  );
  if (!response.ok) return commandFailure(response);
  if (!isStyleProfile(response.data)) return upstreamInvalid("Profile 冻结响应不安全或无法识别。");
  revalidateProject(projectId);
  return safeState({ kind: "success", message: "Style Profile 已冻结。" });
}

export async function submitStyleProfileAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  return profileLifecycleAction(projectId, formData, {
    endpoint: "submit",
    successMessage: "Style Profile 已提交独立审批。",
    body: (expectedVersion) => ({ expected_version: expectedVersion })
  });
}

export async function decideStyleProfileAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  const decision = field(formData, "decision");
  if (decision !== "approve" && decision !== "reject") {
    return invalid("Profile 审批决定无效。");
  }
  return profileLifecycleAction(projectId, formData, {
    endpoint: "decision",
    successMessage: decision === "approve" ? "Style Profile 已批准。" : "Style Profile 已拒绝。",
    body: (expectedVersion) => ({ expected_version: expectedVersion, decision })
  });
}

export async function freezeReviewSuiteAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, APPROVERS);
  if (!access.ok) return access.state;
  const suiteVersionId = field(formData, "suite_version_id");
  const expectedVersion = integerField(formData, "expected_version", 1);
  const key = commandKey(formData);
  if (!UUID_PATTERN.test(suiteVersionId) || expectedVersion === null || !key) {
    return invalid("Review Suite、版本或 Idempotency-Key 无效。");
  }
  const response = await runtimeRequest<ReviewSuite>(
    `${syntheticBase(projectId)}/review-suites/${encodeURIComponent(suiteVersionId)}/freeze`,
    {
      method: "POST",
      idempotencyKey: key,
      body: { expected_version: expectedVersion }
    }
  );
  if (!response.ok) return commandFailure(response);
  if (!isReviewSuite(response.data)) return upstreamInvalid("Review Suite 冻结响应不安全或无法识别。");
  revalidateProject(projectId);
  return safeState({ kind: "success", message: "Review Suite 已冻结。" });
}

async function authorizationResult(
  response: Awaited<ReturnType<typeof runtimeRequest<CollectionAuthorization>>>,
  projectId: string,
  message: string
): Promise<SyntheticActionState> {
  if (!response.ok) return commandFailure(response);
  if (!isAuthorization(response.data)) return upstreamInvalid("Authorization 响应不安全或无法识别。");
  revalidateProject(projectId);
  return safeState({ kind: "success", message });
}

async function profileLifecycleAction(
  projectId: string,
  formData: FormData,
  options: {
    endpoint: "submit" | "decision";
    successMessage: string;
    body: (expectedVersion: number) => Record<string, unknown>;
  }
): Promise<SyntheticActionState> {
  const profileVersionId = field(formData, "profile_version_id");
  const expectedVersion = integerField(formData, "expected_version", 1);
  const key = commandKey(formData);
  if (!UUID_PATTERN.test(profileVersionId) || expectedVersion === null || !key) {
    return invalid("Profile、版本或 Idempotency-Key 无效。");
  }
  const response = await runtimeRequest<StyleProfile>(
    `${syntheticBase(projectId)}/style-profiles/${encodeURIComponent(profileVersionId)}/${options.endpoint}`,
    {
      method: "POST",
      idempotencyKey: key,
      body: options.body(expectedVersion)
    }
  );
  if (!response.ok) return commandFailure(response);
  if (!isStyleProfile(response.data)) return upstreamInvalid("Profile 审批响应不安全或无法识别。");
  revalidateProject(projectId);
  return safeState({ kind: "success", message: options.successMessage });
}

function optionalIsoDate(value: string): string | null | undefined {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? undefined : parsed.toISOString();
}

function revalidateProject(projectId: string): void {
  revalidatePath(`/projects/${projectId}`);
}
