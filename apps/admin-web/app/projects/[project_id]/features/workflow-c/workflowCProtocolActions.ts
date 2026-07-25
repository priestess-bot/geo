"use server";

import { revalidatePath } from "next/cache";

import { lines, runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  commandFailure,
  field,
  invalid,
  invalidUpstream,
  UUID_PATTERN,
  verifyWorkflowCActor
} from "./workflowCActionSupport";
import {
  isMetricProtocol,
  isStatisticalProtocol
} from "./workflowCControlTypeGuards";
import type {
  MetricProtocol,
  StatisticalProtocol
} from "./workflowCControlTypes";
import type { WorkflowCActionState } from "./workflowCTypes";

const MANAGERS = ["owner", "admin"] as const;

export async function createMetricProtocolAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const parsed = metricCreateFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyWorkflowCActor(parsed.projectId, MANAGERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<MetricProtocol>(
    protocolCollection(parsed.projectId, "metric-protocols"),
    {
      method: "POST",
      idempotencyKey: parsed.idempotencyKey,
      body: {
        definition: parsed.definition,
        ...(parsed.supersedes ? { supersedes_protocol_id: parsed.supersedes } : {})
      }
    }
  );
  return result(response, isMetricProtocol, parsed.projectId, "Metric Protocol 草稿已创建。");
}

export async function createStatisticalProtocolAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  const parsed = statisticalCreateFields(formData);
  if (!parsed.ok) return parsed.state;
  const access = await verifyWorkflowCActor(parsed.projectId, MANAGERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<StatisticalProtocol>(
    protocolCollection(parsed.projectId, "statistical-protocols"),
    {
      method: "POST",
      idempotencyKey: parsed.idempotencyKey,
      body: {
        definition: parsed.definition,
        ...(parsed.supersedes ? { supersedes_protocol_id: parsed.supersedes } : {})
      }
    }
  );
  return result(
    response,
    isStatisticalProtocol,
    parsed.projectId,
    "Statistical Protocol 草稿已创建。"
  );
}

export async function transitionMetricProtocolAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(formData, "metric-protocols", isMetricProtocol, "Metric Protocol");
}

export async function transitionStatisticalProtocolAction(
  _previous: WorkflowCActionState,
  formData: FormData
): Promise<WorkflowCActionState> {
  return transition(
    formData,
    "statistical-protocols",
    isStatisticalProtocol,
    "Statistical Protocol"
  );
}

type ProtocolCollection = "metric-protocols" | "statistical-protocols";
type ProtocolOperation = "submit" | "approve" | "retire";

async function transition<T>(
  formData: FormData,
  collection: ProtocolCollection,
  guard: (value: unknown) => value is T,
  label: string
): Promise<WorkflowCActionState> {
  const projectId = field(formData, "project_id");
  const protocolId = field(formData, "protocol_id");
  const operation = field(formData, "operation") as ProtocolOperation;
  const expectedVersion = positiveInteger(field(formData, "expected_aggregate_version"));
  const idempotencyKey = field(formData, "idempotency_key");
  const reason = field(formData, "reason");
  if (!UUID_PATTERN.test(projectId) || !UUID_PATTERN.test(protocolId)) {
    return invalid("项目或 Protocol ID 无效。");
  }
  if (!["submit", "approve", "retire"].includes(operation)) {
    return invalid("Protocol 操作无效。");
  }
  if (expectedVersion === null || !validIdempotencyKey(idempotencyKey)) {
    return invalid("Protocol 版本或 Idempotency-Key 无效。");
  }
  if (operation !== "submit" && (!reason || reason.length > 2_000)) {
    return invalid("决策原因不能为空且不能超过 2000 字符。");
  }
  const access = await verifyWorkflowCActor(projectId, MANAGERS);
  if (!access.ok) return access.state;
  const response = await runtimeRequest<T>(
    `${protocolCollection(projectId, collection)}/${encodeURIComponent(protocolId)}/${operation}`,
    {
      method: "POST",
      idempotencyKey,
      body: {
        expected_aggregate_version: expectedVersion,
        ...(operation === "submit" ? {} : { reason })
      }
    }
  );
  return result(response, guard, projectId, `${label} 已${operationLabel(operation)}。`);
}

type CreateFields = Readonly<{
  projectId: string;
  idempotencyKey: string;
  definition: Record<string, unknown>;
  supersedes: string;
}>;

function metricCreateFields(formData: FormData):
  | ({ ok: true } & CreateFields)
  | { ok: false; state: WorkflowCActionState } {
  const common = commonCreateFields(formData);
  if (!common.ok) return common;
  const promptReleaseId = field(formData, "prompt_release_id");
  const promptReleaseHash = field(formData, "prompt_release_hash");
  const factSnapshotId = field(formData, "fact_snapshot_id");
  const factSnapshotHash = field(formData, "fact_snapshot_hash");
  const corpusVersionId = field(formData, "corpus_version_id");
  const corpusVersion = field(formData, "approved_corpus_version");
  const corpusVersionHash = field(formData, "corpus_version_hash");
  const primarySubjectKey = field(formData, "primary_subject_key");
  const modelIdentity = field(formData, "model_identity");
  const minimumCompletion = field(formData, "minimum_valid_completion");
  const brandAliases = lines(formData.get("brand_aliases"));
  const productAliases = lines(formData.get("product_aliases"));
  const verifiedUrls = lines(formData.get("verified_urls"));
  const questionClusters = parseQuestionClusters(formData.get("question_clusters"));
  if (![promptReleaseId, factSnapshotId, corpusVersionId].every((value) => UUID_PATTERN.test(value))) {
    return { ok: false, state: invalid("Prompt、Fact 或 Corpus 版本 ID 无效。") };
  }
  if (![promptReleaseHash, factSnapshotHash, corpusVersionHash].every(sha256)) {
    return { ok: false, state: invalid("Prompt、Fact 或 Corpus SHA-256 无效。") };
  }
  if (!primarySubjectKey || !modelIdentity || !corpusVersion
    || !brandAliases.length || !productAliases.length) {
    return { ok: false, state: invalid("主体、模型身份及品牌/产品别名不能为空。") };
  }
  if (!verifiedUrls.length || verifiedUrls.some((value) => !httpUrl(value))) {
    return { ok: false, state: invalid("至少需要一个有效的 http/https Verified URL。") };
  }
  if (!questionClusters.ok) return questionClusters;
  const completion = Number(minimumCompletion);
  if (!Number.isFinite(completion) || completion < 0.8 || completion > 1) {
    return { ok: false, state: invalid("最低有效完成率必须在 0.8 到 1 之间。") };
  }
  const competitorKey = field(formData, "competitor_key");
  const competitorAliases = lines(formData.get("competitor_aliases"));
  if (Boolean(competitorKey) !== Boolean(competitorAliases.length)) {
    return { ok: false, state: invalid("竞品 key 与竞品别名必须同时填写。") };
  }
  return {
    ok: true,
    ...common.value,
    definition: {
      schema_version: 1,
      metric_suite: {
        definitions: metricDefinitions,
        judge_version: {
          key: "metric-judge",
          version: field(formData, "judge_version") || "metric-judge-v1",
          prompt_release_id: promptReleaseId,
          prompt_release_hash: promptReleaseHash,
          model_identity: modelIdentity,
          schema_version: "metric-judge-output-v1"
        },
        rule_versions: {
          subject: "subject-rule-v1",
          url: "url-rule-v1",
          citation_order: "citation-order-v1",
          denominator: "planned-denominator-v1",
          mention: "mention-rule-v1"
        },
        minimum_valid_completion: minimumCompletion
      },
      subjects: {
        primary_subject_key: primarySubjectKey,
        brand_aliases: brandAliases,
        product_aliases: productAliases,
        competitors: competitorKey ? [[competitorKey, competitorAliases]] : []
      },
      approved_facts: [],
      verified_urls: verifiedUrls,
      approved_corpus_version: corpusVersion,
      approved_corpus_hash: corpusVersionHash,
      baseline_question_scores: [],
      question_clusters: questionClusters.value,
      fact_snapshot_id: factSnapshotId,
      fact_snapshot_hash: factSnapshotHash,
      prompt_release_id: promptReleaseId,
      prompt_release_hash: promptReleaseHash,
      corpus_version_id: corpusVersionId,
      corpus_version_hash: corpusVersionHash
    }
  };
}

function statisticalCreateFields(formData: FormData):
  | ({ ok: true } & CreateFields)
  | { ok: false; state: WorkflowCActionState } {
  const common = commonCreateFields(formData);
  if (!common.ok) return common;
  const kind = field(formData, "protocol_kind");
  if (kind === "drift_protocol") {
    const minimumQuestionCount = positiveInteger(field(formData, "minimum_question_count"));
    if (minimumQuestionCount === null) {
      return { ok: false, state: invalid("Drift 最低问题数必须为正整数。") };
    }
    return {
      ok: true,
      ...common.value,
      definition: {
        schema_version: 1,
        kind,
        method_version: "strict-stratum-drift-v1",
        effect_metric: "question_performance",
        minimum_question_count: minimumQuestionCount
      }
    };
  }
  if (kind !== "comparison_plan") {
    return { ok: false, state: invalid("Statistical Protocol kind 无效。") };
  }
  const questionClusters = lines(formData.get("question_clusters"));
  const powerPlanHash = field(formData, "power_plan_hash");
  const numeric = {
    alpha: boundedDecimal(formData, "alpha", 0, 1, false, false),
    delta: boundedDecimal(formData, "delta", 0, Number.POSITIVE_INFINITY, true),
    target_power: boundedDecimal(formData, "target_power", 0.8, 1, true),
    precision: boundedDecimal(formData, "precision", 0, Number.POSITIVE_INFINITY, false),
    a_priori_design_power: boundedDecimal(formData, "a_priori_design_power", 0, 1, true),
    minimum_completion_ratio: boundedDecimal(formData, "minimum_completion_ratio", 0.8, 1, true)
  };
  const minPairs = positiveInteger(field(formData, "min_pairs"));
  const iterations = positiveInteger(field(formData, "bootstrap_iterations"));
  if (!field(formData, "family") || !questionClusters.length || !sha256(powerPlanHash)
    || Object.values(numeric).some((item) => item === null)
    || minPairs === null || iterations === null || iterations < 100) {
    return { ok: false, state: invalid("Comparison 参数、功效计划或问题分组无效。") };
  }
  return {
    ok: true,
    ...common.value,
    definition: {
      schema_version: 1,
      kind,
      family: field(formData, "family"),
      metric_key: "question_performance",
      metric_method_version: "semantic-question-performance-v1",
      question_clusters: questionClusters,
      ...numeric,
      min_pairs: minPairs,
      power_plan_hash: powerPlanHash,
      power_method_version: "a-priori-design-power-v1",
      bootstrap_iterations: iterations,
      bootstrap_method: "paired-bootstrap-percentile-v1",
      correction_method: "holm-v1",
      simultaneous_interval_method: "paired-bootstrap-percentile-bonferroni-family-v1"
    }
  };
}

function commonCreateFields(formData: FormData):
  | {
    ok: true;
    value: Omit<CreateFields, "definition">;
  }
  | { ok: false; state: WorkflowCActionState } {
  const projectId = field(formData, "project_id");
  const idempotencyKey = field(formData, "idempotency_key");
  const supersedes = field(formData, "supersedes_protocol_id");
  if (!UUID_PATTERN.test(projectId)) return { ok: false, state: invalid("项目 ID 无效。") };
  if (!validIdempotencyKey(idempotencyKey)) {
    return { ok: false, state: invalid("Idempotency-Key 无效。") };
  }
  if (supersedes && !UUID_PATTERN.test(supersedes)) {
    return { ok: false, state: invalid("被替代的 Protocol ID 无效。") };
  }
  return { ok: true, value: { projectId, idempotencyKey, supersedes } };
}

const metricDefinitions = [
  metricDefinition("brand_mention", "binary_rate"),
  metricDefinition("product_mention", "binary_rate"),
  metricDefinition("recommendation", "binary_rate", "recommendation"),
  metricDefinition("recommendation_strength", "mean_score", "recommendation"),
  metricDefinition("competitor_mention", "binary_rate"),
  metricDefinition("competitor_relative_position", "signed_score"),
  metricDefinition("sentiment", "signed_score", "sentiment"),
  metricDefinition("fact_accuracy", "binary_rate", "fact"),
  metricDefinition("explicit_conflict", "binary_rate", "fact"),
  metricDefinition("subject_mixup", "binary_rate"),
  metricDefinition("key_fact_omission", "binary_rate", "fact"),
  metricDefinition("citation_entailment", "binary_rate", "citation_entailment"),
  metricDefinition("citation_position", "mean_score"),
  metricDefinition("citation_order", "binary_rate"),
  metricDefinition("verified_url_hit", "binary_rate"),
  metricDefinition("source_domain_diversity", "count"),
  metricDefinition("source_type_diversity", "count"),
  metricDefinition("approved_corpus_absorption", "mean_score", "corpus_absorption")
];

function metricDefinition(key: string, valueKind: string, judgeKind: string | null = null) {
  return { key, version: "semantic-metric-v1", value_kind: valueKind, judge_kind: judgeKind };
}

function parseQuestionClusters(value: FormDataEntryValue | null):
  | { ok: true; value: Record<string, string> }
  | { ok: false; state: WorkflowCActionState } {
  const result: Record<string, string> = {};
  const rawLines = String(value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  for (const item of rawLines) {
    const [questionId, cluster, ...extra] = item.split("|").map((part) => part.trim());
    if (!questionId || !cluster || extra.length || questionId in result) {
      return { ok: false, state: invalid("Question cluster 必须逐行使用 question_id|cluster 且 ID 唯一。") };
    }
    result[questionId] = cluster;
  }
  return Object.keys(result).length
    ? { ok: true, value: result }
    : { ok: false, state: invalid("至少需要一个 Question cluster。") };
}

function boundedDecimal(
  formData: FormData,
  name: string,
  minimum: number,
  maximum: number,
  minimumInclusive: boolean,
  maximumInclusive = true
): string | null {
  const raw = field(formData, name);
  const value = Number(raw);
  const lowerValid = minimumInclusive ? value >= minimum : value > minimum;
  const upperValid = maximumInclusive ? value <= maximum : value < maximum;
  return raw && Number.isFinite(value) && lowerValid && upperValid ? raw : null;
}

function sha256(value: string): boolean {
  return /^[0-9a-f]{64}$/.test(value);
}

function httpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function result<T>(
  response: RuntimeResult<T>,
  guard: (value: unknown) => value is T,
  projectId: string,
  successMessage: string
): WorkflowCActionState {
  if (!response.ok) return commandFailure(response, "Protocol 操作失败。");
  if (!guard(response.data)) return invalidUpstream("Protocol 接口返回了无法识别的响应。");
  revalidatePath(`/projects/${projectId}/workflow-c`);
  return { kind: "success", message: successMessage };
}

function protocolCollection(projectId: string, collection: ProtocolCollection): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/analysis/${collection}`;
}

function operationLabel(operation: ProtocolOperation): string {
  if (operation === "submit") return "提交复核";
  if (operation === "approve") return "批准";
  return "退役";
}

function validIdempotencyKey(value: string): boolean {
  return value.length >= 16 && value.length <= 200 && !/[\r\n]/.test(value);
}

function positiveInteger(value: string): number | null {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 1 ? parsed : null;
}
