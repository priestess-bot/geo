"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  commandFailure,
  field,
  invalid,
  normalizedDate,
  UUID_PATTERN,
  verifyWorkflowCActor
} from "./workflowCActionSupport";
import {
  isAdmissionPolicyPage,
  isSamplingRunDetail,
  isSamplingSuite,
  isSamplingSuitePage
} from "./workflowCTypeGuards";
import type {
  AdmissionPolicyPage,
  SamplingRunDetail,
  SamplingSuite,
  SamplingSuitePage,
  WorkflowCActionState
} from "./workflowCTypes";

const OPERATORS = ["owner", "admin", "analyst"] as const;
const MANAGERS = ["owner", "admin"] as const;
const EVIDENCE_KINDS = new Set(["screenshot", "html_export", "transcript_export"]);
const DEVICES = new Set(["desktop", "mobile", "tablet"]);

export async function createSamplingSuiteAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const optionKey = field(formData, "suite_input_option_key");
  const statisticsMethod = field(formData, "statistics_method_version");
  const numbers = {
    repetitions: positiveInteger(formData, "repetitions"),
    max_planned_tasks: positiveInteger(formData, "max_planned_tasks"),
    max_daily_tasks: positiveInteger(formData, "max_daily_tasks"),
    minimum_request_interval_seconds: nonNegativeInteger(
      formData,
      "minimum_request_interval_seconds"
    ),
    max_concurrency: positiveInteger(formData, "max_concurrency")
  };
  if (!optionKey || optionKey.length > 200 || !statisticsMethod || statisticsMethod.length > 200) {
    return invalid("Suite 输入选项或统计方法无效。");
  }
  if (Object.values(numbers).some((value) => value === null)) {
    return invalid("重复数、任务上限、频率或并发设置无效。");
  }
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<SamplingSuite>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/sampling/suites`,
    {
      method: "POST",
      idempotencyKey: command.idempotencyKey,
      body: {
        suite_input_option_key: optionKey,
        statistics_method_version: statisticsMethod,
        ...numbers
      }
    }
  );
  if (!response.ok) return commandFailure(response, "Sampling Suite 创建失败。");
  if (!isSamplingSuite(response.data)) return invalid("Sampling Suite 响应无效。");
  revalidate(command.projectId);
  return { kind: "success", message: `Sampling Suite ${response.data.id} 已冻结。` };
}

export async function startSamplingRunAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const suiteId = field(formData, "suite_id");
  const requestedNotBefore = normalizedDate(field(formData, "requested_not_before"));
  if (!UUID_PATTERN.test(suiteId) || !requestedNotBefore) {
    return invalid("Suite 或计划时间无效。");
  }
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const base = `/v1/projects/${encodeURIComponent(command.projectId)}/sampling`;
  const [suiteInventory, policyInventory] = await Promise.all([
    runtimeRequest<SamplingSuitePage>(`${base}/suites`),
    runtimeRequest<AdmissionPolicyPage>(`${base}/admission-policies`)
  ]);
  if (!suiteInventory.ok || !isSamplingSuitePage(suiteInventory.data)) {
    return invalid("Sampling Suite inventory 无法校验。");
  }
  if (!policyInventory.ok || !isAdmissionPolicyPage(policyInventory.data)) {
    return invalid("Admission Policy inventory 无法校验。");
  }
  const suite = suiteInventory.data.items.find((item) => item.id === suiteId);
  const policy = suite
    ? policyInventory.data.items.find((item) =>
      item.id === suite.admission_policy_id
      && item.definition_hash === suite.admission_policy_hash
      && item.status === "approved"
      && item.effective_authorization_state === "approved"
    )
    : undefined;
  const purposes = policy?.authorized_purposes || [];
  if (!suite || purposes.length !== 1 || !purposes[0] || purposes[0].length > 200) {
    return invalid("Suite 没有唯一且当前有效的已批准授权用途。");
  }
  const response = await runtimeRequest<SamplingRunDetail>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/sampling/suites/`
      + `${encodeURIComponent(suiteId)}/runs`,
    {
      method: "POST",
      idempotencyKey: command.idempotencyKey,
      body: { purpose: purposes[0], requested_not_before: requestedNotBefore }
    }
  );
  if (!response.ok) return commandFailure(response, "Sampling Run 启动失败。");
  if (!isSamplingRunDetail(response.data)) return invalid("Sampling Run 响应无效。");
  revalidate(command.projectId);
  return { kind: "success", message: `Sampling Run ${response.data.run.id} 已创建并预留分母。` };
}

export async function enqueueSamplingRunAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const runId = field(formData, "run_id");
  const requestedNotBefore = normalizedDate(field(formData, "requested_not_before"));
  const maxTasks = positiveInteger(formData, "max_tasks");
  if (!UUID_PATTERN.test(runId) || !requestedNotBefore || maxTasks === null) {
    return invalid("Run、计划时间或最大任务数无效。");
  }
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/sampling/runs/`
      + `${encodeURIComponent(runId)}/enqueue-ready`,
    {
      method: "POST",
      idempotencyKey: command.idempotencyKey,
      body: { requested_not_before: requestedNotBefore, max_tasks: maxTasks }
    }
  );
  if (!response.ok) return commandFailure(response, "Sampling Run 批量入队失败。");
  revalidate(command.projectId);
  return { kind: "success", message: "符合条件的 Sampling Tasks 已按冻结频率批量入队。" };
}

export async function cancelSamplingRunAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const runId = field(formData, "run_id");
  if (!UUID_PATTERN.test(runId)) return invalid("Sampling Run 无效。");
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/sampling/runs/`
      + `${encodeURIComponent(runId)}/cancel`,
    { method: "POST", idempotencyKey: command.idempotencyKey }
  );
  if (!response.ok) return commandFailure(response, "Sampling Run 取消失败。");
  revalidate(command.projectId);
  return { kind: "success", message: "Sampling Run 已请求取消，未入队预留已释放。" };
}

export async function importManualEvidenceAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const runId = field(formData, "run_id");
  const [taskId, rawVersion] = field(formData, "task_ref").split(":", 2);
  const expectedTaskVersion = Number(rawVersion);
  const evidenceKind = field(formData, "evidence_kind");
  const surfaceParserReleaseId = field(formData, "surface_parser_release_id");
  const preRedactedAttestation = formData.get("pre_redacted_attestation") === "on";
  const device = field(formData, "device");
  const locale = field(formData, "locale");
  const capturedAt = normalizedDate(field(formData, "captured_at"));
  const artifact = formData.get("artifact");
  if (!UUID_PATTERN.test(runId) || !UUID_PATTERN.test(taskId || "")) {
    return invalid("Manual evidence 的 Run 或 Task 无效。");
  }
  if (!Number.isSafeInteger(expectedTaskVersion) || expectedTaskVersion < 1) {
    return invalid("Task 版本无效，请刷新页面。");
  }
  if (!EVIDENCE_KINDS.has(evidenceKind) || !DEVICES.has(device)) {
    return invalid("证据类型或采集设备无效。");
  }
  if (surfaceParserReleaseId && !UUID_PATTERN.test(surfaceParserReleaseId)) {
    return invalid("Consumer surface parser release 无效。");
  }
  if (!locale || locale.length > 100 || !capturedAt) {
    return invalid("Locale 或采集时间无效。");
  }
  if (!(artifact instanceof File) || artifact.size < 1 || artifact.size > 10 * 1024 * 1024) {
    return invalid("请选择不超过 10 MB 的证据文件。");
  }
  const contentType = artifact.type.toLowerCase();
  const allowedTypes = new Set([
    "application/json",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/html",
    "text/plain"
  ]);
  if (!allowedTypes.has(contentType)) return invalid("证据文件 MIME 类型不受支持。");
  if (surfaceParserReleaseId
    && (evidenceKind !== "transcript_export" || contentType !== "application/json")) {
    return invalid("Consumer surface parser 只接受 JSON transcript export。");
  }
  const access = await verifyWorkflowCActor(command.projectId, OPERATORS);
  if (!access.ok) return access.state;
  const contentBase64 = Buffer.from(await artifact.arrayBuffer()).toString("base64");
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/sampling/runs/`
      + `${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskId || "")}/manual-evidence`,
    {
      method: "POST",
      idempotencyKey: command.idempotencyKey,
      body: {
        expected_task_version: expectedTaskVersion,
        content_base64: contentBase64,
        content_type: contentType,
        governance_policy_option_key: "manual-evidence-redaction-v1",
        evidence_kind: evidenceKind,
        pre_redacted_attestation: preRedactedAttestation,
        device,
        locale,
        captured_at: capturedAt,
        surface_parser_release_id: surfaceParserReleaseId || null
      }
    }
  );
  if (!response.ok) return commandFailure(response, "Manual evidence 导入失败。");
  revalidate(command.projectId);
  return { kind: "success", message: "证据已生成服务端 manifest，并进入待复核队列。" };
}

export async function approveManualEvidenceAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return reviewManualEvidence(formData, "approve");
}

export async function rejectManualEvidenceAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return reviewManualEvidence(formData, "reject");
}

async function reviewManualEvidence(
  formData: FormData,
  decision: "approve" | "reject"
): Promise<WorkflowCActionState> {
  const command = baseCommand(formData);
  if (!command.ok) return command.state;
  const importId = field(formData, "import_id");
  const expectedVersion = positiveInteger(formData, "expected_version");
  const reason = field(formData, "reason");
  if (!UUID_PATTERN.test(importId) || expectedVersion === null) {
    return invalid("Manual evidence 或版本无效。");
  }
  if (!reason || reason.length > 1000) return invalid("复核原因不能为空且最多 1000 字符。");
  const access = await verifyWorkflowCActor(command.projectId, MANAGERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<unknown>(
    `/v1/projects/${encodeURIComponent(command.projectId)}/sampling/`
      + `manual-evidence-imports/${encodeURIComponent(importId)}/${decision}`,
    {
      method: "POST",
      idempotencyKey: command.idempotencyKey,
      body: { expected_version: expectedVersion, reason }
    }
  );
  if (!response.ok) return commandFailure(response, "Manual evidence 复核失败。");
  revalidate(command.projectId);
  return {
    kind: "success",
    message: decision === "approve" ? "Manual evidence 已批准并创建 Attempt。" : "Manual evidence 已拒绝。"
  };
}

function baseCommand(formData: FormData):
  | { ok: true; projectId: string; idempotencyKey: string }
  | { ok: false; state: WorkflowCActionState } {
  const projectId = field(formData, "project_id");
  const idempotencyKey = field(formData, "idempotency_key");
  if (!UUID_PATTERN.test(projectId)) return { ok: false, state: invalid("项目 ID 无效。") };
  if (idempotencyKey.length < 16 || idempotencyKey.length > 200 || /[\r\n]/.test(idempotencyKey)) {
    return { ok: false, state: invalid("Idempotency-Key 无效。") };
  }
  return { ok: true, projectId, idempotencyKey };
}

function positiveInteger(formData: FormData, name: string): number | null {
  const value = nonNegativeInteger(formData, name);
  return value !== null && value >= 1 ? value : null;
}

function nonNegativeInteger(formData: FormData, name: string): number | null {
  const value = Number(field(formData, name));
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function revalidate(projectId: string): void {
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/workflow-c`);
}
