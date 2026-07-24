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
