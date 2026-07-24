"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  field,
  idempotencyKey,
  invalid,
  invalidUpstream,
  nonNegativeIntegerField,
  positiveIntegerField,
  safeState,
  secretBase,
  secretCommandFailure,
  secretHref,
  secretInput,
  UUID_PATTERN,
  verifySecretActor
} from "./secretStoreActionSupport";
import {
  isSecretVersionMetadata,
  isGovernedSecretPurpose,
  type SecretActionState,
  type SecretVersionMetadata
} from "./secretStoreTypes";

export async function createSecretReferenceAction(
  _previous: SecretActionState,
  formData: FormData
): Promise<SecretActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySecretActor(projectId);
  if (!access.ok) return access.state;
  const purpose = field(formData, "purpose");
  const expectedVersion = nonNegativeIntegerField(formData, "expected_version");
  const secret = secretInput(formData);
  if (!isGovernedSecretPurpose(purpose) || expectedVersion !== 0) {
    return invalid("用途或初始版本无效。");
  }
  if (!secret.ok) return secret.state;
  const key = idempotencyKey(formData);
  if (!key) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<SecretVersionMetadata>(secretBase(projectId), {
    method: "POST",
    idempotencyKey: key,
    body: {
      purpose,
      secret_value: secret.value,
      expected_version: expectedVersion
    }
  });
  if (!response.ok) return secretCommandFailure(response);
  if (!isSecretVersionMetadata(response.data)) {
    return invalidUpstream("Secret Store 返回了不安全或无法识别的元数据响应。");
  }
  revalidateProject(projectId);
  return safeState({
    kind: "success",
    message: response.data.replayed ? "已恢复原创建结果。" : "Secret Reference 已创建，v1 等待验证。",
    nextHref: secretHref(projectId, response.data.reference_id),
    version: response.data
  });
}

export async function stageSecretRotationAction(
  _previous: SecretActionState,
  formData: FormData
): Promise<SecretActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySecretActor(projectId);
  if (!access.ok) return access.state;
  const referenceId = field(formData, "reference_id");
  const expectedVersion = positiveIntegerField(formData, "expected_version");
  const secret = secretInput(formData);
  if (!UUID_PATTERN.test(referenceId) || expectedVersion === null) {
    return invalid("Reference 或 Aggregate version 无效。");
  }
  if (!secret.ok) return secret.state;
  const key = idempotencyKey(formData);
  if (!key) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<SecretVersionMetadata>(
    `${secretBase(projectId)}/${encodeURIComponent(referenceId)}/versions`,
    {
      method: "POST",
      idempotencyKey: key,
      body: { secret_value: secret.value, expected_version: expectedVersion }
    }
  );
  if (!response.ok) return secretCommandFailure(response);
  if (!isSecretVersionMetadata(response.data)) {
    return invalidUpstream("Secret Store 返回了不安全或无法识别的元数据响应。");
  }
  revalidateProject(projectId);
  return safeState({
    kind: "success",
    message: response.data.replayed ? "已恢复原 Rotation 结果。" : `Rotation v${response.data.version} 已暂存。`,
    version: response.data
  });
}

export async function verifySecretVersionAction(
  _previous: SecretActionState,
  formData: FormData
): Promise<SecretActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySecretActor(projectId);
  if (!access.ok) return access.state;
  return transitionVersion(formData, projectId, "verify", "Secret Version canary 已验证。");
}

export async function activateSecretVersionAction(
  _previous: SecretActionState,
  formData: FormData
): Promise<SecretActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySecretActor(projectId);
  if (!access.ok) return access.state;
  return transitionVersion(formData, projectId, "activate", "第二位操作人已激活 Secret Version。");
}

export async function revokeSecretVersionAction(
  _previous: SecretActionState,
  formData: FormData
): Promise<SecretActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySecretActor(projectId);
  if (!access.ok) return access.state;
  return transitionVersion(formData, projectId, "revoke", "Secret Version 已撤销。");
}

async function transitionVersion(
  formData: FormData,
  projectId: string,
  command: "verify" | "activate" | "revoke",
  successMessage: string
): Promise<SecretActionState> {
  const referenceId = field(formData, "reference_id");
  const version = positiveIntegerField(formData, "version");
  const expectedVersion = positiveIntegerField(formData, "expected_version");
  if (!UUID_PATTERN.test(referenceId) || version === null || expectedVersion === null) {
    return invalid("Reference、Secret version 或 Aggregate version 无效。");
  }
  const key = idempotencyKey(formData);
  if (!key) return invalid("Idempotency-Key 无效，请刷新页面后重试。");
  const response = await runtimeRequest<SecretVersionMetadata>(
    `${secretBase(projectId)}/${encodeURIComponent(referenceId)}/versions/${version}/${command}`,
    {
      method: "POST",
      idempotencyKey: key,
      body: { expected_version: expectedVersion }
    }
  );
  if (!response.ok) return secretCommandFailure(response);
  if (!isSecretVersionMetadata(response.data)) {
    return invalidUpstream("Secret Store 返回了不安全或无法识别的元数据响应。");
  }
  revalidateProject(projectId);
  return safeState({
    kind: "success",
    message: response.data.replayed ? "已恢复原生命周期结果。" : successMessage,
    version: response.data
  });
}

function revalidateProject(projectId: string): void {
  revalidatePath(`/projects/${projectId}`);
}
