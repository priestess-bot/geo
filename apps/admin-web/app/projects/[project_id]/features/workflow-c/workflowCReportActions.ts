"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  commandFailure,
  field,
  invalid,
  invalidUpstream,
  UUID_PATTERN,
  verifyWorkflowCActor
} from "./workflowCActionSupport";
import {
  isWorkflowCReport,
  isWorkflowCReportMetricValue
} from "./workflowCControlTypeGuards";
import {
  workflowCReportMetricKeys,
  type WorkflowCReport,
  type WorkflowCReportMetricKey
} from "./workflowCControlTypes";
import type { WorkflowCActionState } from "./workflowCTypes";

const MANAGERS = ["owner", "admin"] as const;
const HASH_PATTERN = /^[0-9a-f]{64}$/;
const metricKeys = new Set<string>(workflowCReportMetricKeys);

export async function createWorkflowCReportAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const projectId = field(formData, "project_id");
  const idempotencyKey = field(formData, "idempotency_key");
  const campaignId = field(formData, "campaign_id");
  const monitoringReportId = field(formData, "monitoring_report_id");
  const monitoringHash = field(formData, "monitoring_report_hash");
  const semanticHash = field(formData, "semantic_snapshot_hash");
  const sourceKind = field(formData, "source_kind");
  const payload = approvedPayload(formData);
  if (!UUID_PATTERN.test(projectId) || !UUID_PATTERN.test(campaignId)
    || !UUID_PATTERN.test(monitoringReportId)) return invalid("项目、Campaign 或 Report ID 无效。");
  if (!HASH_PATTERN.test(monitoringHash) || !HASH_PATTERN.test(semanticHash)) {
    return invalid("Monitoring Report 或 Semantic Snapshot SHA-256 无效。");
  }
  if (sourceKind !== "provider_api" && sourceKind !== "proxy_grounded_api") {
    return invalid("报告来源无效。");
  }
  if (!validIdempotencyKey(idempotencyKey)) return invalid("Idempotency-Key 无效。");
  if (!payload.ok) return payload.state;
  const access = await verifyWorkflowCActor(projectId, MANAGERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<WorkflowCReport>(reportCollection(projectId), {
    method: "POST",
    idempotencyKey,
    body: {
      campaign_id: campaignId,
      monitoring_report_id: monitoringReportId,
      monitoring_report_hash: monitoringHash,
      semantic_snapshot_hash: semanticHash,
      source_kind: sourceKind,
      approved_safe_payload: payload.value
    }
  });
  return reportResult(response, projectId, "Workflow C 报告草稿已创建。");
}

export async function transitionWorkflowCReportAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const projectId = field(formData, "project_id");
  const reportId = field(formData, "report_id");
  const idempotencyKey = field(formData, "idempotency_key");
  const operation = field(formData, "operation");
  const expectedVersion = Number(field(formData, "expected_version"));
  const reason = field(formData, "reason");
  if (!UUID_PATTERN.test(projectId) || !UUID_PATTERN.test(reportId)) {
    return invalid("项目或 Report ID 无效。");
  }
  if (!["submit", "approve", "stale", "revoke"].includes(operation)) {
    return invalid("Report 操作无效。");
  }
  if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 1
    || !validIdempotencyKey(idempotencyKey)) return invalid("Report 版本或 Idempotency-Key 无效。");
  if (operation !== "submit" && (!reason || reason.length > 500)) {
    return invalid("决策原因不能为空且不能超过 500 字符。");
  }
  const access = await verifyWorkflowCActor(projectId, MANAGERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<WorkflowCReport>(
    `${reportCollection(projectId)}/${encodeURIComponent(reportId)}/${operation}`,
    {
      method: "POST",
      idempotencyKey,
      body: {
        expected_version: expectedVersion,
        ...(operation === "submit" ? {} : { reason })
      }
    }
  );
  return reportResult(response, projectId, `Workflow C 报告已${reportOperationLabel(operation)}。`);
}

function approvedPayload(formData: FormData):
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; state: WorkflowCActionState } {
  const headline = field(formData, "headline");
  const summary = field(formData, "summary");
  const methodology = field(formData, "methodology");
  if (!headline || headline.length > 200) {
    return { ok: false, state: invalid("报告标题不能为空且不能超过 200 字符。") };
  }
  if (summary.length > 2_000 || methodology.length > 2_000) {
    return { ok: false, state: invalid("摘要或方法说明不能超过 2000 字符。") };
  }
  const warnings = String(formData.get("warnings") || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (warnings.length > 20 || warnings.some((item) => item.length > 500)) {
    return { ok: false, state: invalid("Warning 最多 20 条且每条不能超过 500 字符。") };
  }
  const keys = formData.getAll("metric_key").map((item) => String(item).trim());
  const values = formData.getAll("metric_value").map((item) => String(item).trim());
  if (keys.length !== values.length) return { ok: false, state: invalid("Metric 字段不完整。") };
  const metrics: Partial<Record<WorkflowCReportMetricKey, string>> = {};
  for (let index = 0; index < keys.length; index += 1) {
    const key = keys[index];
    const value = values[index];
    if (!key && !value) continue;
    if (!metricKeys.has(key) || !isWorkflowCReportMetricValue(key, value)) {
      return { ok: false, state: invalid("Count Metric 必须是非负整数，signed Metric 必须在 -1 到 1，其余 Metric 必须在 0 到 1。") };
    }
    if (key in metrics) return { ok: false, state: invalid("Metric key 不能重复。") };
    metrics[key as WorkflowCReportMetricKey] = value;
  }
  return {
    ok: true,
    value: {
      headline,
      ...(summary ? { summary } : {}),
      ...(methodology ? { methodology } : {}),
      ...(warnings.length ? { warnings } : {}),
      ...(Object.keys(metrics).length ? { metrics } : {})
    }
  };
}

function reportResult(
  response: RuntimeResult<WorkflowCReport>,
  projectId: string,
  message: string
): WorkflowCActionState {
  if (!response.ok) return commandFailure(response, "Workflow C Report 操作失败。");
  if (!isWorkflowCReport(response.data)) {
    return invalidUpstream("Workflow C Report 接口返回了无法识别的响应。");
  }
  revalidatePath(`/projects/${projectId}/workflow-c`);
  return { kind: "success", message };
}

function reportCollection(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/analysis/reports`;
}

function validIdempotencyKey(value: string): boolean {
  return value.length >= 16 && value.length <= 200 && !/[\r\n]/.test(value);
}

function reportOperationLabel(operation: string): string {
  if (operation === "submit") return "提交复核";
  if (operation === "approve") return "批准";
  if (operation === "stale") return "标记失效";
  return "撤销";
}
