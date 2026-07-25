"use server";

import { revalidatePath } from "next/cache";

import { runtimeRequest } from "../../../../runtime";
import {
  UUID_PATTERN,
  booleanField,
  channelField,
  commandFailure,
  commandKey,
  field,
  integerField,
  invalid,
  lines,
  requiredField,
  safeState,
  syntheticBase,
  syntheticHref,
  upstreamInvalid,
  uuidField,
  verifySyntheticActor
} from "./syntheticLabActionSupport";
import {
  isManualImportPreview,
  isManualImportResult,
  isReviewCase,
  isReviewSuite,
  isStyleProfile,
  isStyleSource,
  type ManualImportPreview,
  type ManualImportResult,
  type ReviewCase,
  type ReviewSuite,
  type StyleProfile,
  type StyleSource,
  type SyntheticActionState
} from "./syntheticLabTypes";

const CONTRIBUTORS = ["owner", "admin", "analyst"] as const;
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

export async function createStyleSourceAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const channel = channelField(formData);
  const accessMode = field(formData, "access_mode");
  const sourceUrlValue = field(formData, "source_url");
  const sourceLabel = requiredField(formData, "source_label", 200);
  const sourceUrl = sourceUrlValue ? safeSourceUrl(sourceUrlValue) : null;
  const expectedVersion = integerField(formData, "expected_version", 0);
  const key = commandKey(formData);
  const manual = accessMode === "manual_import";
  if (!channel || !["public", "authenticated", "manual_import"].includes(accessMode)
    || (manual ? !sourceLabel || Boolean(sourceUrlValue) : !sourceUrl || Boolean(sourceLabel))
    || expectedVersion !== 0 || !key) {
    return invalid("渠道、访问模式以及 URL/手工来源名称组合无效。");
  }
  const response = await runtimeRequest<StyleSource>(`${syntheticBase(projectId)}/style-sources`, {
    method: "POST",
    idempotencyKey: key,
    body: {
      expected_version: 0,
      channel,
      access_mode: accessMode,
      locale: "en-AU",
      source_url: manual ? null : sourceUrl,
      source_label: manual ? sourceLabel : null
    }
  });
  return resourceResult(response, isStyleSource, projectId, "Style Source 已创建。");
}

export async function createManualImportPreviewAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const sourceId = uuidField(formData, "style_source_revision_id");
  const importFormat = field(formData, "import_format");
  const sourceRights = field(formData, "default_source_rights");
  const evidence = requiredField(formData, "rights_evidence_reference", 2000);
  const upload = formData.get("sample_file");
  const key = commandKey(formData);
  if (!sourceId || !["text", "csv", "jsonl"].includes(importFormat)
    || !["owned", "licensed", "public_reference", "authorized_manual_capture"].includes(sourceRights)
    || !evidence || !key || !upload || typeof upload === "string"
    || upload.size < 1 || upload.size > MAX_UPLOAD_BYTES || upload.name.length > 255) {
    return invalid("请选择 5 MiB 以内的 UTF-8 text/CSV/JSONL 文件、手工来源和权利依据。");
  }
  const extension = upload.name.toLowerCase().split(".").pop();
  const validExtension = { text: ["txt", "text"], csv: ["csv"], jsonl: ["jsonl", "ndjson"] }[
    importFormat as "text" | "csv" | "jsonl"
  ].includes(extension || "");
  if (!validExtension) return invalid("文件扩展名与所选格式不一致。");
  const contentBase64 = Buffer.from(await upload.arrayBuffer()).toString("base64");
  const response = await runtimeRequest<ManualImportPreview>(
    `${syntheticBase(projectId)}/sample-import-previews`,
    {
      method: "POST",
      idempotencyKey: key,
      body: {
        expected_version: 0,
        style_source_revision_id: sourceId,
        import_format: importFormat,
        filename: upload.name,
        content_base64: contentBase64,
        default_source_rights: sourceRights,
        rights_evidence_reference: evidence
      }
    }
  );
  if (!response.ok) return commandFailure(response);
  if (!isManualImportPreview(response.data)) {
    return upstreamInvalid("样本导入预览响应不安全或无法识别。");
  }
  revalidateProject(projectId);
  return safeState({
    kind: "success",
    message: `预览已生成：${response.data.selectable_count} 行待复核，${response.data.blocked_count} 行阻断。`,
    importPreview: response.data,
    nextHref: syntheticHref(projectId, { synthetic_import_preview_id: response.data.id })
  });
}

export async function approveManualImportPreviewAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const previewId = uuidField(formData, "preview_id");
  const selectedRows = formData.getAll("selected_row_numbers")
    .map((value) => Number(String(value)))
    .filter((value) => Number.isSafeInteger(value) && value > 0);
  const key = commandKey(formData);
  if (!previewId || !key || selectedRows.length < 1
    || selectedRows.length !== new Set(selectedRows).size
    || !booleanField(formData, "au_english_verified")
    || !booleanField(formData, "anonymization_verified")) {
    return invalid("请选择可批准行，并完成澳洲英文与匿名化明审确认。");
  }
  const previewResponse = await runtimeRequest<ManualImportPreview>(
    `${syntheticBase(projectId)}/sample-import-previews/${encodeURIComponent(previewId)}`
  );
  if (!previewResponse.ok) return commandFailure(previewResponse);
  if (!isManualImportPreview(previewResponse.data)
    || previewResponse.data.project_id !== projectId) {
    return upstreamInvalid("样本导入预览响应不安全或无法识别。");
  }
  if (previewResponse.data.submitted_by === access.actorIdentityId) {
    return safeState({
      kind: "error",
      status: 403,
      message: "独立复核失败：提交者不能批准自己的导入预览。"
    });
  }
  if (previewResponse.data.status !== "pending") {
    return invalid("仅待复核的导入预览可以批准。");
  }
  const selectableRows = new Set(
    previewResponse.data.rows.filter((row) => row.selectable).map((row) => row.row_number)
  );
  if (selectedRows.some((rowNumber) => !selectableRows.has(rowNumber))) {
    return invalid("所选行包含不可批准或已阻断的样本。");
  }
  const response = await runtimeRequest<ManualImportResult>(
    `${syntheticBase(projectId)}/sample-import-previews/${encodeURIComponent(previewId)}/approve`,
    {
      method: "POST",
      idempotencyKey: key,
      body: {
        expected_version: 1,
        selected_row_numbers: selectedRows,
        au_english_verified: true,
        anonymization_verified: true
      }
    }
  );
  if (!response.ok) return commandFailure(response);
  if (!isManualImportResult(response.data)) return upstreamInvalid("样本批准响应无法识别。");
  revalidateProject(projectId);
  return safeState({
    kind: "success",
    message: `导入已批准：接受 ${response.data.accepted_count}，拒绝 ${response.data.rejected_count}。`,
    importResult: response.data
  });
}

export async function createStyleProfileAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const channel = channelField(formData);
  const promptBindingId = uuidField(formData, "prompt_binding_id");
  const sampleIds = formData.getAll("approved_sample_ids").map(String);
  const expectedVersion = integerField(formData, "expected_version", 0);
  const key = commandKey(formData);
  if (!channel || !promptBindingId || expectedVersion !== 0 || !key || sampleIds.length < 1
    || sampleIds.length > 10_000 || sampleIds.some((value) => !UUID_PATTERN.test(value))
    || sampleIds.length !== new Set(sampleIds).size) {
    return invalid("请选择同渠道的批准样本和当前冻结 Style Profile Prompt。");
  }
  const response = await runtimeRequest<StyleProfile>(`${syntheticBase(projectId)}/style-profiles`, {
    method: "POST",
    idempotencyKey: key,
    body: {
      expected_version: 0,
      channel,
      locale: "en-AU",
      prompt_binding_id: promptBindingId,
      approved_sample_ids: sampleIds
    }
  });
  return resourceResult(response, isStyleProfile, projectId, "Style Profile draft 已创建。");
}

export async function createReviewSuiteAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const channel = channelField(formData);
  const suiteName = requiredField(formData, "suite_name", 200);
  const key = commandKey(formData);
  if (!channel || !suiteName || !key) return invalid("Suite 名称或渠道无效。");
  const response = await runtimeRequest<ReviewSuite>(`${syntheticBase(projectId)}/review-suites`, {
    method: "POST",
    idempotencyKey: key,
    body: { expected_version: 0, channel, suite_name: suiteName }
  });
  return resourceResult(response, isReviewSuite, projectId, "Review Suite draft 已创建。");
}

export async function createReviewCaseAction(
  _previous: SyntheticActionState,
  formData: FormData
): Promise<SyntheticActionState> {
  const projectId = field(formData, "project_id");
  const access = await verifySyntheticActor(projectId, CONTRIBUTORS);
  if (!access.ok) return access.state;
  const suiteVersionId = uuidField(formData, "suite_version_id");
  const channel = channelField(formData);
  const caseKey = requiredField(formData, "case_key", 200);
  const ordinal = integerField(formData, "ordinal", 1);
  const mode = field(formData, "mode");
  const persona = requiredField(formData, "persona", 4000);
  const useCase = requiredField(formData, "use_case", 4000);
  const subject = requiredField(formData, "subject", 1000);
  const questionSetVersionId = uuidField(formData, "question_set_version_id");
  const factSnapshotId = uuidField(formData, "fact_snapshot_id");
  const profileVersionId = uuidField(formData, "profile_version_id");
  const creativeValue = field(formData, "creative_reference");
  const creativeReference = creativeValue || null;
  const key = commandKey(formData);
  if (!suiteVersionId || !channel || !caseKey || !/^[a-zA-Z0-9_.:-]+$/.test(caseKey)
    || ordinal === null || !["autonomous_scenario", "guided_scenario"].includes(mode)
    || !persona || !useCase || !subject || !questionSetVersionId || !factSnapshotId
    || !profileVersionId || !key || (mode === "guided_scenario") !== Boolean(creativeReference)) {
    return invalid("场景字段或服务器冻结资源选择无效。");
  }
  const response = await runtimeRequest<ReviewCase>(
    `${syntheticBase(projectId)}/review-suites/${encodeURIComponent(suiteVersionId)}/cases`,
    {
      method: "POST",
      idempotencyKey: key,
      body: {
        expected_version: 0,
        case_key: caseKey,
        ordinal,
        mode,
        channel,
        persona,
        use_case: useCase,
        subject,
        question_set_version_id: questionSetVersionId,
        fact_snapshot_id: factSnapshotId,
        profile_version_id: profileVersionId,
        competitor_scenario: booleanField(formData, "competitor_scenario"),
        expected_risks: lines(formData, "expected_risks").slice(0, 100),
        creative_reference: creativeReference
      }
    }
  );
  return resourceResult(response, isReviewCase, projectId, "Review Case 已创建。");
}

async function resourceResult<T>(
  response: Awaited<ReturnType<typeof runtimeRequest<T>>>,
  guard: (value: unknown) => value is T,
  projectId: string,
  message: string
): Promise<SyntheticActionState> {
  if (!response.ok) return commandFailure(response);
  if (!guard(response.data)) return upstreamInvalid("Synthetic Lab 响应不安全或无法识别。");
  revalidateProject(projectId);
  return safeState({ kind: "success", message });
}

function safeSourceUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password
      || parsed.search || parsed.hash) return null;
    return value;
  } catch {
    return null;
  }
}

function revalidateProject(projectId: string): void {
  revalidatePath(`/projects/${projectId}`);
}
