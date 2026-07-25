"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  commandFailure,
  commandKey,
  field,
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
  isSyntheticJob,
  type StyleCollectionAdmission,
  type SyntheticActionState,
  type SyntheticJob
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
    return invalid("Profile、Fact snapshot、模型运行时或 Idempotency-Key 无效。");
  }
  return enqueueExecution(projectId, key, "profile-build", {
    profile_version_id: profileVersionId,
    fact_snapshot_id: factSnapshotId,
    runtime_selection_id: runtimeSelectionId
  }, "Style Profile build 已冻结输入并排队。");
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
    return invalid("Frozen Suite、Case、模型运行时、风格阈值或 Idempotency-Key 无效。");
  }
  return enqueueExecution(projectId, key, "generation", {
    suite_version_id: suiteVersionId,
    case_id: caseId,
    runtime_selection_id: runtimeSelectionId,
    style_pass_threshold: threshold
  }, "Review Case 已冻结证据、Prompt 与模型运行时并排队。");
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
    return invalid("Review Job 列表或 Idempotency-Key 无效。");
  }
  return enqueueExecution(projectId, key, "corpus", {
    role: "new_candidate_corpus",
    review_job_ids: reviewJobIds,
    source_corpus_job_id: null
  }, "候选 Corpus 已冻结 Review lineage 并排队。");
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
    return invalid("候选 Corpus 或 Idempotency-Key 无效。");
  }
  return enqueueExecution(projectId, key, "corpus", {
    role: "current_approved_corpus",
    review_job_ids: [],
    source_corpus_job_id: sourceCorpusJobId
  }, "Corpus 人工批准已排队；服务端将执行 maker-checker 校验。");
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
    return invalid("QuestionSet、Corpus、模型运行时、有效配对比例或 Idempotency-Key 无效。");
  }
  return enqueueExecution(projectId, key, "offline-experiment", {
    question_set_id: questionSetId,
    current_corpus_job_id: currentCorpusJobId,
    candidate_corpus_job_id: candidateCorpusJobId,
    runtime_selection_id: runtimeSelectionId,
    minimum_valid_pair_ratio: ratio
  }, "三臂配对 Offline Experiment 已冻结并排队。");
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
    return invalid("Style Source、adapter、Secret Reference 或 Idempotency-Key 无效。");
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
    return upstreamInvalid("Style Collection admission 响应不安全或无法识别。");
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
    message: "Style Collection 已通过授权与 live canary 门禁并排队。",
    nextHref: syntheticHref(projectId, { synthetic_job_id: response.data.job.id }),
    job: response.data.job
  });
}

async function enqueueExecution(
  projectId: string,
  key: string,
  route: "profile-build" | "generation" | "corpus" | "offline-experiment",
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
    nextHref: syntheticHref(projectId, { synthetic_job_id: response.data.id }),
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
