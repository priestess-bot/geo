"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  alertResult,
  commandFailure,
  field,
  invalid,
  invalidUpstream,
  isAlertCommandResponse,
  normalizedDate,
  parseAlertCommand,
  verifyWorkflowCActor,
  type AlertCommandResponse
} from "./workflowCActionSupport";
import type { WorkflowCActionState } from "./workflowCTypes";

const CONTRIBUTORS = ["owner", "admin", "analyst"] as const;

export async function acknowledgeWorkflowCAlertAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(formData, "acknowledge", "Alert 已确认。");
}

export async function suppressWorkflowCAlertAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const suppressedUntil = normalizedDate(field(formData, "suppressed_until"));
  if (!suppressedUntil) return invalid("抑制截止时间无效。");
  return transition(formData, "suppress", "Alert 已按时限抑制。", {
    suppressed_until: suppressedUntil
  });
}

export async function unsuppressWorkflowCAlertAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(formData, "unsuppress", "Alert 抑制已解除。");
}

export async function resolveWorkflowCAlertAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(formData, "resolve", "Alert 已解决并保留完整处置记录。");
}

async function transition(
  formData: FormData,
  command: "acknowledge" | "suppress" | "unsuppress" | "resolve",
  successMessage: string,
  extra: Record<string, unknown> = {}
): Promise<WorkflowCActionState> {
  const parsed = parseAlertCommand(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyWorkflowCActor(parsed.value.projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<AlertCommandResponse>(
    alertCommandPath(parsed.value.projectId, parsed.value.alertId, command),
    {
      method: "POST",
      idempotencyKey: parsed.value.idempotencyKey,
      body: {
        expected_version: parsed.value.expectedVersion,
        reason: parsed.value.reason,
        ...extra
      }
    }
  );
  if (!response.ok) return commandFailure(response, "Alert 状态变更失败。");
  if (!isAlertCommandResponse(response.data)) {
    return invalidUpstream("Alert 接口返回了无法识别的响应。");
  }
  revalidatePath(`/projects/${parsed.value.projectId}/workflow-c`);
  return {
    kind: "success",
    message: response.data.replayed ? "已恢复原处置结果。" : successMessage,
    alert: alertResult(response.data)
  };
}

function alertCommandPath(projectId: string, alertId: string, command: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/alerts/`
    + `${encodeURIComponent(alertId)}/${command}`;
}
