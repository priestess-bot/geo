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
  isSemanticMetricsJobReceipt,
  isStatisticalAnalysisJobReceipt
} from "./workflowCControlTypeGuards";
import type {
  SemanticMetricsJobReceipt,
  StatisticalAnalysisJobReceipt
} from "./workflowCControlTypes";
import type { WorkflowCActionState } from "./workflowCTypes";

const WRITERS = ["owner", "admin", "analyst"] as const;
const HASH_PATTERN = /^[0-9a-f]{64}$/;

export async function enqueueSemanticMetricsJobAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const common = commonFields(formData);
  if (!common.ok) return common.state;
  const runId = field(formData, "sampling_run_id");
  const protocolId = field(formData, "metric_protocol_id");
  if (!UUID_PATTERN.test(runId) || !UUID_PATTERN.test(protocolId)) {
    return invalid("Sampling Run 或 Metric Protocol ID 无效。");
  }
  const access = await verifyWorkflowCActor(common.projectId, WRITERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<SemanticMetricsJobReceipt>(
    `${analysisBase(common.projectId)}/semantic-metrics/jobs`,
    {
      method: "POST",
      idempotencyKey: common.idempotencyKey,
      body: {
        sampling_run_id: runId,
        metric_protocol_id: protocolId,
        max_attempts: common.maxAttempts
      }
    }
  );
  return jobResult(
    response,
    isSemanticMetricsJobReceipt,
    common.projectId,
    "Semantic Metrics 分析任务已入队。"
  );
}

export async function enqueueComparisonJobAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return enqueueStatistical(formData, "comparisons", "comparison_plan_id", "Comparison");
}

export async function enqueueDriftJobAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return enqueueStatistical(formData, "drift", "drift_protocol_id", "Drift");
}

async function enqueueStatistical(
  formData: FormData,
  path: "comparisons" | "drift",
  protocolField: "comparison_plan_id" | "drift_protocol_id",
  label: string
): Promise<WorkflowCActionState> {
  const common = commonFields(formData);
  if (!common.ok) return common.state;
  const protocolId = field(formData, protocolField);
  const baseline = field(formData, "baseline_metric_snapshot_hash");
  const candidateField = path === "comparisons"
    ? "candidate_metric_snapshot_hash"
    : "current_metric_snapshot_hash";
  const candidate = field(formData, candidateField);
  if (!UUID_PATTERN.test(protocolId) || !HASH_PATTERN.test(baseline) || !HASH_PATTERN.test(candidate)) {
    return invalid(`${label} Protocol 或 Snapshot SHA-256 无效。`);
  }
  const access = await verifyWorkflowCActor(common.projectId, WRITERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<StatisticalAnalysisJobReceipt>(
    `${analysisBase(common.projectId)}/${path}/jobs`,
    {
      method: "POST",
      idempotencyKey: common.idempotencyKey,
      body: {
        [protocolField]: protocolId,
        baseline_metric_snapshot_hash: baseline,
        [candidateField]: candidate,
        max_attempts: common.maxAttempts
      }
    }
  );
  return jobResult(
    response,
    isStatisticalAnalysisJobReceipt,
    common.projectId,
    `${label} 分析任务已入队。`
  );
}

function commonFields(formData: FormData):
  | { ok: true; projectId: string; idempotencyKey: string; maxAttempts: number }
  | { ok: false; state: WorkflowCActionState } {
  const projectId = field(formData, "project_id");
  const idempotencyKey = field(formData, "idempotency_key");
  const maxAttempts = Number(field(formData, "max_attempts"));
  if (!UUID_PATTERN.test(projectId)) return { ok: false, state: invalid("项目 ID 无效。") };
  if (idempotencyKey.length < 16 || idempotencyKey.length > 200 || /[\r\n]/.test(idempotencyKey)) {
    return { ok: false, state: invalid("Idempotency-Key 无效。") };
  }
  if (!Number.isSafeInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 10) {
    return { ok: false, state: invalid("最大尝试次数必须为 1 到 10。") };
  }
  return { ok: true, projectId, idempotencyKey, maxAttempts };
}

function jobResult<T>(
  response: RuntimeResult<T>,
  guard: (value: unknown) => value is T,
  projectId: string,
  message: string
): WorkflowCActionState {
  if (!response.ok) return commandFailure(response, "分析任务入队失败。");
  if (!guard(response.data)) return invalidUpstream("分析任务接口返回了无法识别的响应。");
  revalidatePath(`/projects/${projectId}/workflow-c`);
  return {
    kind: "success",
    message: `${message} Job ${String((response.data as { job_id: string }).job_id)}`
  };
}

function analysisBase(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/analysis`;
}
