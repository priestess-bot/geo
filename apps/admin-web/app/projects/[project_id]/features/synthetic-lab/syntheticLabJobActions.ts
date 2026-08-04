"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  commandFailure,
  commandKey,
  channelField,
  field,
  hashField,
  integerField,
  invalid,
  requiredField,
  safeState,
  syntheticBase,
  syntheticHref,
  upstreamInvalid,
  UUID_PATTERN,
  uuidField,
  verifySyntheticActor
} from "./syntheticLabActionSupport";
import {
  isStyleCollectionAdmission,
  isSyntheticReviewResult,
  isSyntheticJob,
  type StyleCollectionAdmission,
  type SyntheticActionState,
  type SyntheticJob,
  type SyntheticJobRefreshState,
  type SyntheticReviewResult
} from "./syntheticLabTypes";

const CONTRIBUTORS = ["owner", "admin", "analyst"] as const;

export async function enqueueStyleProfileBuildAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const profileVersionId = uuidField(formData, "profile_version_id");
  const factSnapshotId = uuidField(formData, "fact_snapshot_id");
  const runtimeSelectionId = uuidField(formData, "runtime_selection_id");
  const key = commandKey(formData);
  if (!profileVersionId || !factSnapshotId || !runtimeSelectionId
      || !key) {
    return invalid("风格画像、事实快照、模型运行时或幂等键无效。");
  }
  return enqueueExecution(projectId, key, "profile-build", {
    profile_version_id: profileVersionId,
    fact_snapshot_id: factSnapshotId,
    runtime_selection_id: runtimeSelectionId
  }, "风格画像构建已冻结输入并排队。");
}

export async function enqueueReviewCaseRunAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const suiteVersionId = uuidField(formData, "suite_version_id");
  const caseId = uuidField(formData, "case_id");
  const runtimeSelectionId = uuidField(formData, "runtime_selection_id");
  const threshold = Number(field(formData, "style_pass_threshold"));
  const key = commandKey(formData);
  if (!suiteVersionId || !caseId || !runtimeSelectionId || !key
      || !Number.isFinite(threshold) || threshold < 0 || threshold > 5) {
    return invalid("冻结套件、测评用例、模型运行时、风格阈值或幂等键无效。");
  }
  return enqueueExecution(projectId, key, "generation", {
    suite_version_id: suiteVersionId,
    case_id: caseId,
    runtime_selection_id: runtimeSelectionId,
    style_pass_threshold: threshold
  }, "目标仿真文案任务已创建，系统将自动完成生成、冲突检查和必要修订。");
}

export async function enqueueDirectGenerationAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const channel = channelField(formData);
  const subjectEntityId = uuidField(formData, "subject_entity_id");
  const goal = requiredField(formData, "generation_goal", 4000);
  const runtimeSelectionId = uuidField(formData, "runtime_selection_id");
  const styleVersionId = uuidField(formData, "channel_style_version_id");
  const styleHash = hashField(formData, "channel_style_hash");
  const knowledgeHash = hashField(formData, "knowledge_snapshot_hash");
  const threshold = Number(field(formData, "style_pass_threshold"));
  const includeCompetitor = field(formData, "include_competitor_context") === "true";
  const key = commandKey(formData);
  if (!channel || !subjectEntityId || !goal || !runtimeSelectionId || !styleVersionId
      || !styleHash || !knowledgeHash || !key || !Number.isFinite(threshold)
      || threshold < 0 || threshold > 5) {
    return invalid("请选择产品、渠道风格和模型，并填写 4000 字以内的生成目标。");
  }
  return enqueueExecution(projectId, key, "direct-generation", {
    channel,
    subject_entity_id: subjectEntityId,
    generation_goal: goal,
    runtime_selection_id: runtimeSelectionId,
    channel_style_version_id: styleVersionId,
    channel_style_hash: styleHash,
    knowledge_snapshot_hash: knowledgeHash,
    style_pass_threshold: threshold,
    include_competitor_context: includeCompetitor
  }, "生成任务已开始；本页会自动更新生成、冲突检查和修订结果。");
}

export async function refreshSyntheticJobAction(
  projectId: string,
  jobId: string
): Promise<SyntheticJobRefreshState> {
  if (!UUID_PATTERN.test(projectId) || !UUID_PATTERN.test(jobId)) {
    return { ok: false, status: 422, message: "项目或任务 ID 无效。" };
  }
  const base = syntheticBase(projectId);
  const job = await runtimeRequest<SyntheticJob>(
    `${base}/jobs/${encodeURIComponent(jobId)}`
  );
  if (!job.ok) {
    return {
      ok: false,
      status: job.status,
      message: job.error || "任务状态读取失败。",
      correlationId: job.problem.correlation_id
    };
  }
  if (!isSyntheticJob(job.data)) {
    return { ok: false, status: 502, message: "任务状态响应无法识别。" };
  }
  if (job.data.status !== "succeeded") return { ok: true, job: job.data };
  const result = await runtimeRequest<SyntheticReviewResult>(
    `${base}/jobs/${encodeURIComponent(jobId)}/result`
  );
  if (!result.ok) {
    return {
      ok: false,
      job: job.data,
      status: result.status,
      message: result.error || "结果读取失败。",
      correlationId: result.problem.correlation_id
    };
  }
  if (!isSyntheticReviewResult(result.data)) {
    return { ok: false, job: job.data, status: 502, message: "生成结果响应无法识别。" };
  }
  return { ok: true, job: job.data, result: result.data };
}

export async function enqueueCandidateCorpusAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const reviewJobIds = formData.getAll("review_job_ids")
    .map((value) => String(value).trim());
  const key = commandKey(formData);
  if (!key || reviewJobIds.length === 0
      || new Set(reviewJobIds).size !== reviewJobIds.length
      || !reviewJobIds.every((value) => UUID_PATTERN.test(value))) {
    return invalid("测评任务列表或幂等键无效。");
  }
  return enqueueExecution(projectId, key, "corpus", {
    role: "new_candidate_corpus",
    review_job_ids: reviewJobIds,
    source_corpus_job_id: null
  }, "候选语料已冻结测评追溯链并排队。");
}

export async function enqueueApprovedCorpusAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, ["owner", "admin"]);
  if (!access.ok) return access.state;
  const sourceCorpusJobId = uuidField(formData, "source_corpus_job_id");
  const key = commandKey(formData);
  if (!sourceCorpusJobId || !key) {
    return invalid("候选语料或幂等键无效。");
  }
  return enqueueExecution(projectId, key, "corpus", {
    role: "current_approved_corpus",
    review_job_ids: [],
    source_corpus_job_id: sourceCorpusJobId
  }, "语料人工批准已排队；服务端将执行双人复核校验。");
}

export async function enqueueOfflineExperimentAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const questionSetId = uuidField(formData, "question_set_id");
  const currentCorpusJobId = uuidField(formData, "current_corpus_job_id");
  const candidateCorpusJobId = uuidField(formData, "candidate_corpus_job_id");
  const runtimeSelectionId = uuidField(formData, "runtime_selection_id");
  const ratio = Number(field(formData, "minimum_valid_pair_ratio"));
  const key = commandKey(formData);
  if (!questionSetId || !currentCorpusJobId || !candidateCorpusJobId
      || currentCorpusJobId === candidateCorpusJobId || !runtimeSelectionId || !key
      || !Number.isFinite(ratio) || ratio <= 0 || ratio > 1) {
    return invalid("问题集、语料、模型运行时、有效配对比例或幂等键无效。");
  }
  return enqueueExecution(projectId, key, "offline-experiment", {
    question_set_id: questionSetId,
    current_corpus_job_id: currentCorpusJobId,
    candidate_corpus_job_id: candidateCorpusJobId,
    runtime_selection_id: runtimeSelectionId,
    minimum_valid_pair_ratio: ratio
  }, "三臂配对离线实验已冻结并排队。");
}

export async function admitStyleCollectionAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const sourceRevisionId = uuidField(formData, "style_source_revision_id");
  const adapterRelease = requiredField(formData, "adapter_release", 200);
  const secretValue = field(formData, "login_secret_reference_id");
  const secretReferenceId = secretValue ? uuidField(formData, "login_secret_reference_id") : null;
  const key = commandKey(formData);
  if (!sourceRevisionId || !adapterRelease || (secretValue && !secretReferenceId) || !key) {
    return invalid("风格来源、适配器、密钥引用或幂等键无效。");
  }
  const response = await runtimeRequest<StyleCollectionAdmission>(
    `${syntheticBase(projectId)}/jobs/style-collection`,
    {
      method: "POST",
      idempotencyKey: key,
      body: {
        style_source_revision_id: sourceRevisionId,
        adapter_release: adapterRelease,
        login_secret_reference_id: secretReferenceId
      }
    }
  );
  if (!response.ok) return commandFailure(response);
  if (!isStyleCollectionAdmission(response.data)) {
    return upstreamInvalid("风格样本采集准入响应不安全或无法识别。");
  }
  if (response.data.disposition !== "accepted" || !response.data.job) {
    return safeState({
      kind: response.data.disposition === "b_track" ? "success" : "error",
      message: `采集未排队：${response.data.reason_code}`
    });
  }
  revalidateProject(projectId);
  return safeState({
    kind: "success",
    message: "风格样本采集已通过授权和在线验证门禁，任务已排队。",
    nextHref: syntheticHref(projectId, {
      synthetic_view: "results",
      synthetic_job_id: response.data.job.id
    }),
    job: response.data.job
  });
}

async function enqueueExecution(
  projectId: string,
  key: string,
  route: "profile-build" | "generation" | "direct-generation" | "corpus" | "offline-experiment",
  body: Record<string, unknown>,
  message: string
): Promise<SyntheticActionState> {
  const response = await runtimeRequest<SyntheticJob>(
    `${syntheticBase(projectId)}/jobs/${route}`,
    { method: "POST", idempotencyKey: key, body }
  );
  if (!response.ok) return commandFailure(response);
  if (!isSyntheticJob(response.data)) return upstreamInvalid("Synthetic execution 响应不安全或无法识别。");
  revalidateProject(projectId);
  return safeState({
    kind: "success",
    message,
    nextHref: syntheticHref(projectId, {
      synthetic_view: "generate",
      synthetic_job_id: response.data.id
    }),
    job: response.data
  });
}

export async function cancelSyntheticJobAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const jobId = uuidField(formData, "job_id");
  const expectedVersion = integerField(formData, "expected_version", 1);
  const key = commandKey(formData);
  if (!jobId || expectedVersion === null || !key) {
    return invalid("Job ID、版本或 Idempotency-Key 无效。");
  }
  const response = await runtimeRequest<SyntheticJob>(
    `${syntheticBase(projectId)}/jobs/${encodeURIComponent(jobId)}/cancel`,
    {
      method: "POST",
      idempotencyKey: key,
      body: { expected_version: expectedVersion }
    }
  );
  if (!response.ok) return commandFailure(response);
  if (!isSyntheticJob(response.data)) return upstreamInvalid("Job 取消响应不安全或无法识别。");
  revalidateProject(projectId);
  return safeState({ kind: "success", message: "任务取消已记录。", job: response.data });
}

function revalidateProject(projectId: string): void {
  revalidatePath(`/projects/${projectId}`);
}
