"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  commandFailure,
  field,
  invalid,
  invalidUpstream,
  normalizedDate,
  UUID_PATTERN,
  verifyWorkflowCActor
} from "./workflowCActionSupport";
import { isAdmissionPolicy } from "./workflowCTypeGuards";
import type {
  AdmissionPolicy,
  WorkflowCActionState
} from "./workflowCTypes";

const MANAGERS = ["owner", "admin"] as const;

export async function createAdmissionPolicyAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const projectId = field(formData, "project_id");
  const idempotencyKey = field(formData, "idempotency_key");
  const runtimeOptionKey = field(formData, "runtime_authorization_option_key");
  const purpose = field(formData, "purpose");
  const validUntil = normalizedDate(field(formData, "valid_until"));
  const numeric = {
    quota_remaining: positiveInteger(formData, "quota_remaining"),
    daily_task_limit: positiveInteger(formData, "daily_task_limit"),
    minimum_request_interval_seconds: nonNegativeInteger(
      formData,
      "minimum_request_interval_seconds"
    ),
    max_concurrency: positiveInteger(formData, "max_concurrency")
  };
  if (!UUID_PATTERN.test(projectId)) return invalid("项目 ID 无效。");
  if (!validIdempotencyKey(idempotencyKey)) return invalid("Idempotency-Key 无效。");
  if (!runtimeOptionKey || runtimeOptionKey.length > 200) return invalid("Runtime option 无效。");
  if (!purpose || purpose.length > 200) return invalid("授权用途无效。");
  if (!validUntil) return invalid("授权时间无效。");
  if (Object.values(numeric).some((item) => item === null)) {
    return invalid("配额、频率或并发限制无效。");
  }
  const access = await verifyWorkflowCActor(projectId, MANAGERS);
  if (!access.ok) return access.state;
  const supersedes = field(formData, "supersedes_policy_id");
  if (supersedes && !UUID_PATTERN.test(supersedes)) {
    return invalid("被替代 Policy ID 无效。");
  }
  const response = await runtimeRequest<AdmissionPolicy>(
    `/v1/projects/${encodeURIComponent(projectId)}/sampling/admission-policies`,
    {
      method: "POST",
      idempotencyKey,
      body: {
        ...(supersedes ? { supersedes_policy_id: supersedes } : {}),
        runtime_authorization_option_key: runtimeOptionKey,
        purpose,
        valid_until: validUntil,
        ...numeric
      }
    }
  );
  return actionResult(response, projectId, "Admission Policy 草稿已创建。");
}

export async function submitAdmissionPolicyAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(formData, "submit", "Admission Policy 已提交复核。");
}

export async function approveAdmissionPolicyAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(formData, "approve", "Admission Policy 已批准。");
}

export async function assessNoBasisAdmissionPolicyAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(formData, "assess-no-basis", "已记录无自动执行授权依据。");
}

export async function revokeAdmissionPolicyAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(formData, "revoke", "Admission Policy 已撤销。");
}

async function transition(
  formData: FormData,
  operation: "submit" | "approve" | "assess-no-basis" | "revoke",
  successMessage: string
): Promise<WorkflowCActionState> {
  const projectId = field(formData, "project_id");
  const policyId = field(formData, "policy_id");
  const idempotencyKey = field(formData, "idempotency_key");
  const expectedVersion = positiveInteger(formData, "expected_version");
  const reason = field(formData, "reason");
  if (!UUID_PATTERN.test(projectId) || !UUID_PATTERN.test(policyId)) {
    return invalid("项目或 Admission Policy ID 无效。");
  }
  if (!validIdempotencyKey(idempotencyKey) || expectedVersion === null) {
    return invalid("版本或 Idempotency-Key 无效。");
  }
  if (operation !== "submit" && (!reason || reason.length > 1000)) {
    return invalid("决策原因不能为空且不能超过 1000 字符。");
  }
  const access = await verifyWorkflowCActor(projectId, MANAGERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<AdmissionPolicy>(
    `/v1/projects/${encodeURIComponent(projectId)}/sampling/admission-policies/`
      + `${encodeURIComponent(policyId)}/${operation}`,
    {
      method: "POST",
      idempotencyKey,
      body: {
        expected_version: expectedVersion,
        ...(operation === "submit" ? {} : { reason })
      }
    }
  );
  return actionResult(response, projectId, successMessage);
}

function actionResult(
  response: RuntimeResult<AdmissionPolicy>,
  projectId: string,
  successMessage: string
): WorkflowCActionState {
  if (!response.ok) return commandFailure(response, "Admission Policy 状态变更失败。");
  if (!isAdmissionPolicy(response.data)) {
    return invalidUpstream("Admission Policy 接口返回了无法识别的响应。");
  }
  revalidatePath(`/projects/${projectId}/workflow-c`);
  return {
    kind: "success",
    message: successMessage,
    policy: {
      id: response.data.id,
      status: response.data.status,
      version: response.data.aggregate_version
    }
  };
}

function validIdempotencyKey(value: string): boolean {
  return value.length >= 16 && value.length <= 200 && !/[\r\n]/.test(value);
}

function positiveInteger(formData: FormData, name: string): number | null {
  const value = nonNegativeInteger(formData, name);
  return value !== null && value >= 1 ? value : null;
}

function nonNegativeInteger(formData: FormData, name: string): number | null {
  const value = Number(field(formData, name));
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}
