"use client";

import { useActionState, useRef, useState } from "react";

import {
  acceptKnowledgeQualityRiskAction,
  cancelCollectionAction,
  deleteMemberAction,
  backfillManualDistributionAction,
  createKnowledgeMaintenanceRunAction,
  createKnowledgeFactExtractionAction,
  createKnowledgePipelineAction,
  createKnowledgePromptGenerationAction,
  disableKnowledgeChunkAction,
  createInvitationAction,
  createFidelityCheckAction,
  generateKnowledgeContentAction,
  importApprovedPromptCandidatesAction,
  enqueueReportJobAction,
  enqueueCollectionAction,
  importManualBackfillAction,
  importPromptsAction,
  invitationAction,
  projectStatusAction,
  projectLifecycleAction,
  recordHumanReviewAction,
  revealConnectorSecretAction,
  retryKnowledgePipelineStageAction,
  reviewKnowledgeFactAction,
  reviewKnowledgeFactCandidateAction,
  reviewPromptCandidateAction,
  runFixtureE2EAction,
  saveBrandAssetAction,
  saveCompetitorEntityAction,
  saveLaunchConfigAction,
  saveKnowledgePromptTemplateAction,
  saveMemberAction,
  savePromptAction,
  saveProjectAndBrandAction,
  saveScoreWeightProfileAction,
  saveSavedViewAction,
  submitManualBackfillAction,
  testConnectorAction,
  updateActionRecommendationAction,
  reviewContentDraftAction,
  updateReportJobStatusAction,
  updateReportManagementAction,
  type ProjectActionState
} from "./actions";
import { projectStatusLabel, roleLabel, statusLabel } from "../status";

const initialState: ProjectActionState = { ok: false };
const hydrationControlProps = { suppressHydrationWarning: true };

type RuntimeProjectRecord = {
  project: { id: string; name?: string; target_brand?: string; category?: string; status?: string };
  tenant?: { name?: string };
  brand?: {
    canonical_name?: string;
    official_domains?: string[];
    parent_company?: string | null;
    product_lines?: string[];
    status?: string;
  } | null;
};

type Competitor = {
  id?: string;
  canonical_name?: string;
  official_domains?: string[];
  parent_company?: string | null;
  product_lines?: string[];
  status?: string;
};

type PromptRecord = {
  id?: string;
  project_id?: string;
  market_code?: string;
  industry_code?: string;
  text?: string;
  intent_type?: string;
  city?: string;
  language?: string;
  target_brand?: string;
  competitors?: string[];
  priority?: number;
  intent_weight?: number | string;
  prompt_version?: string;
  status?: string;
};

type RuntimeListRecord = Record<string, unknown>;

type KnowledgeFileInspection = {
  file: File;
  hash: string;
  recommendation: string;
  status: "checking" | "ready" | "blocked";
  note: string;
};

const knowledgeFileSuffixes = new Set([
  "pdf", "docx", "pptx", "xlsx", "csv", "txt", "md", "markdown", "html", "htm",
  "png", "jpg", "jpeg", "webp", "tif", "tiff"
]);

function knowledgeFileRecommendation(file: File): string {
  const suffix = file.name.split(".").pop()?.toLowerCase() || "";
  if (["png", "jpg", "jpeg", "webp", "tif", "tiff"].includes(suffix)) return "MinerU / OCR";
  if (["pdf", "docx", "pptx", "xlsx", "html", "htm"].includes(suffix)) return "Docling（必要时自动降级）";
  return "MarkItDown（必要时自动降级）";
}

function formatFileSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(2)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

async function inspectKnowledgeFile(file: File): Promise<KnowledgeFileInspection> {
  const suffix = file.name.split(".").pop()?.toLowerCase() || "";
  if (!knowledgeFileSuffixes.has(suffix)) {
    return { file, hash: "", recommendation: "不支持", status: "blocked", note: "文件类型不在允许列表中" };
  }
  if (file.size <= 0 || file.size > 50 * 1024 * 1024) {
    return { file, hash: "", recommendation: knowledgeFileRecommendation(file), status: "blocked", note: file.size <= 0 ? "空文件" : "超过 50 MB" };
  }
  let hash = "";
  try {
    const digest = await globalThis.crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    hash = Array.from(new Uint8Array(digest)).map((item) => item.toString(16).padStart(2, "0")).join("");
  } catch {
    hash = "浏览器未提供 SHA-256；服务端仍会校验";
  }
  return {
    file,
    hash,
    recommendation: knowledgeFileRecommendation(file),
    status: "ready",
    note: "客户端预检通过；提交后执行服务端 secret、PII、加密和重复检测"
  };
}

export type KnowledgeFactSearchResult = {
  fact?: Record<string, unknown>;
  chunk?: Record<string, unknown>;
  score?: number;
  fallback_used?: boolean;
  embedding_model?: string;
};

type PageResponse<T = RuntimeListRecord> = {
  total_count: number;
  records: T[];
  limit?: number;
  offset?: number;
};

export function InvitationForm({
  projectId,
  defaultEmail,
  pendingInvitations
}: {
  projectId: string;
  defaultEmail?: string;
  pendingInvitations?: RuntimeListRecord[];
}) {
  const [state, formAction, pending] = useActionState(createInvitationAction, initialState);
  const pendingViewerInvitations = (pendingInvitations || [])
    .map((record) => objectValue(record.invitation))
    .filter((invitation) => stringValue(invitation.status) === "pending" && (stringValue(invitation.role) || "viewer") === "viewer");
  return (
    <form
      className="inlineForm"
      action={formAction}
      onSubmit={(event) => {
        const form = event.currentTarget;
        const formData = new FormData(form);
        const email = stringValue(formData.get("email")).trim().toLowerCase();
        const replaceInput = form.elements.namedItem("replace_existing_pending") as HTMLInputElement | null;
        const oldIdsInput = form.elements.namedItem("existing_pending_invitation_ids") as HTMLInputElement | null;
        const existing = pendingViewerInvitations.filter(
          (invitation) => stringValue(invitation.email).trim().toLowerCase() === email
        );
        if (replaceInput) {
          replaceInput.value = "0";
        }
        if (oldIdsInput) {
          oldIdsInput.value = "";
        }
        if (!existing.length) {
          return;
        }
        const oldInvitationIds = existing.map((invitation) => stringValue(invitation.id)).filter(Boolean);
        const confirmed = window.confirm(
          [
            `客户 ${email} 已有 ${existing.length} 个待处理邀请。`,
            "生成新邀请会先让旧邀请失效，旧 invitation token 将无法再使用。",
            `将失效的旧邀请：${oldInvitationIds.join(", ") || "未读取到 ID"}`,
            "确认让旧邀请失效并生成新的邀请？"
          ].join("\n")
        );
        if (!confirmed) {
          event.preventDefault();
          return;
        }
        if (replaceInput) {
          replaceInput.value = "1";
        }
        if (oldIdsInput) {
          oldIdsInput.value = oldInvitationIds.join(",");
        }
      }}
    >
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="replace_existing_pending" value="0" />
      <input {...hydrationControlProps} type="hidden" name="existing_pending_invitation_ids" value="" />
      <label><span>客户邮箱</span><input {...hydrationControlProps} name="email" type="email" defaultValue={defaultEmail || ""} placeholder="customer@example.com" required /></label>
      <button type="submit" disabled={pending}>{pending ? "创建中..." : "创建邀请"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function ProjectLifecycleForm({ projectId, status }: { projectId: string; status?: string }) {
  const [state, formAction, pending] = useActionState(projectLifecycleAction, initialState);
  const isArchived = status === "archived";
  return (
    <form className="inlineForm compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="action" value={isArchived ? "restore" : "archive"} />
      <button
        type="submit"
        className={isArchived ? undefined : "danger"}
        disabled={pending}
        onClick={(event) => {
          if (!isArchived && !window.confirm("确认归档这个项目？归档不会物理删除数据，可在 archived 筛选中恢复。")) {
            event.preventDefault();
          }
        }}
      >
        {pending ? "处理中..." : isArchived ? "恢复为暂停中" : "归档项目"}
      </button>
      <ActionState state={state} />
    </form>
  );
}

export function ProjectStatusControls({
  category,
  competitorCount,
  connectorReady,
  primaryDomain,
  projectId,
  promptCount,
  status,
  targetBrand
}: {
  category?: string;
  competitorCount: number;
  connectorReady: boolean;
  primaryDomain?: string;
  projectId: string;
  promptCount: number;
  status?: string;
  targetBrand?: string;
}) {
  const [state, formAction, pending] = useActionState(projectStatusAction, initialState);
  const normalized = String(status || "").toLowerCase();
  const blockers = activationBlockers({
    category,
    competitorCount,
    connectorReady,
    primaryDomain,
    promptCount,
    targetBrand
  });
  const canActivate = blockers.length === 0 && normalized !== "archived";
  return (
    <div className="projectStatusControls">
      <div>
        <span className="muted">项目状态</span>
        <strong>{projectStatusLabel(status)}</strong>
      </div>
      {blockers.length ? (
        <p className="muted">启动条件未满足：{blockers.join("、")}</p>
      ) : (
        <p className="muted">启动条件已满足，可以切换到运行中。</p>
      )}
      <form className="statusActionGroup" action={formAction}>
        <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
        <input {...hydrationControlProps} type="hidden" name="activation_blockers" value={blockers.join("\n")} />
        <button type="submit" name="action" value="activate" disabled={pending || !canActivate || normalized === "active"}>
          {pending ? "处理中..." : "启动"}
        </button>
        <button type="submit" name="action" value="pause" className="secondary" disabled={pending || normalized === "paused" || normalized === "archived"}>
          暂停
        </button>
        <button
          type="submit"
          name="action"
          value={normalized === "archived" ? "restore" : "archive"}
          className={normalized === "archived" ? "secondary" : "danger"}
          disabled={pending}
          onClick={(event) => {
            if (normalized !== "archived" && !window.confirm("确认归档这个项目？归档后不会删除数据，可恢复为暂停中。")) {
              event.preventDefault();
            }
          }}
        >
          {normalized === "archived" ? "恢复为暂停中" : "归档项目"}
        </button>
      </form>
      <ActionState state={state} />
    </div>
  );
}

export function FixtureE2EForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(runFixtureE2EAction, initialState);
  return (
    <form className="configForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>Prompt 数量</span><input {...hydrationControlProps} name="prompt_limit" type="number" min={1} max={10} defaultValue={1} required /></label>
      <label><span>城市</span><input {...hydrationControlProps} name="cities" defaultValue="Global" required /></label>
      <label>
        <span>样本数</span>
        <select {...hydrationControlProps} name="sample_size" defaultValue="3">
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
        </select>
      </label>
      <input {...hydrationControlProps} type="hidden" name="persist_analysis" value="1" />
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "运行中..." : "运行本地全流程测试"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function CollectionJobPanel({
  jobs,
  projectId,
  projectStatus
}: {
  jobs: PageResponse;
  projectId: string;
  projectStatus: string;
}) {
  const [state, formAction, pending] = useActionState(enqueueCollectionAction, initialState);
  const canRun = projectStatus === "active";
  return (
    <div className="opsWorkbench">
      <form className="configForm" action={formAction}>
        <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
        <label><span>Prompt 上限</span><input {...hydrationControlProps} name="prompt_limit" type="number" min={1} max={200} defaultValue={10} required /></label>
        <label><span>每条 Prompt 样本数</span><input {...hydrationControlProps} name="sample_size" type="number" min={1} max={20} defaultValue={1} required /></label>
        <label><span>城市</span><input {...hydrationControlProps} name="cities" placeholder="留空则使用启用 Prompt 的城市" /></label>
        <div className="formActions">
          <button type="submit" disabled={pending || !canRun}>{pending ? "入队中..." : "运行正式采集"}</button>
        </div>
        {!canRun ? <p className="notice error">项目必须处于运行中才能创建正式采集任务。</p> : null}
        <ActionState state={state} />
      </form>
      <div className="summaryList">
        {jobs.records.length ? jobs.records.map((job, index) => (
          <div className="summaryListRow" key={`${stringValue(job.id) || "collection-job"}-${index}`}>
            <div>
              <strong>{shortValue(stringValue(job.id))} · {statusLabel(stringValue(job.status))}</strong>
              <p className="muted">
                Prompt {stringValue(job.prompt_limit) || "0"} · 样本 {stringValue(job.sample_size) || "0"} · 尝试 {stringValue(job.attempt_count) || "0"}/{stringValue(job.max_attempts) || "0"}
              </p>
              {stringValue(job.last_error_message) ? <p className="muted errorText">{shortValue(stringValue(job.last_error_message), 180)}</p> : null}
            </div>
            {stringValue(job.status) === "queued" ? <CollectionJobCancelForm jobId={stringValue(job.id)} projectId={projectId} /> : null}
          </div>
        )) : <p className="muted emptyState">暂无正式采集任务。</p>}
      </div>
    </div>
  );
}

function CollectionJobCancelForm({ jobId, projectId }: { jobId: string; projectId: string }) {
  const [state, formAction, pending] = useActionState(cancelCollectionAction, initialState);
  return (
    <form className="inlineForm compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="collection_job_id" value={jobId} />
      <button className="danger" type="submit" disabled={pending}>{pending ? "取消中..." : "取消"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function ProjectBasicsForm({ record }: { record: RuntimeProjectRecord }) {
  const [state, formAction, pending] = useActionState(saveProjectAndBrandAction, initialState);
  const brandStatus = record.brand?.status || "active";
  return (
    <form className="configForm singleColumn projectBrandForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={record.project.id} />
      <input {...hydrationControlProps} type="hidden" name="brand_status" value={brandStatus} />
      <label><span>租户名称</span><input {...hydrationControlProps} name="tenant_name" defaultValue={record.tenant?.name || ""} required /></label>
      <label><span>项目名称</span><input {...hydrationControlProps} name="name" defaultValue={record.project.name || ""} required /></label>
      <label><span>目标品牌</span><input {...hydrationControlProps} name="target_brand" defaultValue={record.project.target_brand || ""} required /></label>
      <label><span>品类</span><input {...hydrationControlProps} name="category" defaultValue={record.project.category || ""} required /></label>
      <label><span>品牌名称</span><input {...hydrationControlProps} name="canonical_name" defaultValue={record.brand?.canonical_name || record.project.target_brand || ""} required /></label>
      <label><span>官网域名</span><textarea {...hydrationControlProps} name="official_domains" defaultValue={(record.brand?.official_domains || []).join("\n")} /></label>
      <label><span>母公司</span><input {...hydrationControlProps} name="parent_company" defaultValue={record.brand?.parent_company || ""} /></label>
      <label><span>产品线</span><textarea {...hydrationControlProps} name="product_lines" defaultValue={(record.brand?.product_lines || []).join("\n")} /></label>
      <div className="readonlyField">
        <span>状态</span>
        <strong>项目 {projectStatusLabel(record.project.status)} · 品牌 {statusLabel(brandStatus)}</strong>
      </div>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存项目与品牌"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function LaunchConfigForm({
  projectId,
  launch,
  competitors,
  scoreConfig,
  scoreFormulas,
  scoreProfiles
}: {
  projectId: string;
  launch: Record<string, unknown>;
  competitors: Competitor[];
  scoreConfig: Record<string, unknown> | null;
  scoreFormulas: Array<Record<string, unknown>>;
  scoreProfiles: Array<{ score_weight_profile?: Record<string, unknown> }>;
}) {
  const [state, formAction, pending] = useActionState(saveLaunchConfigAction, initialState);
  const [testState, testFormAction, testPending] = useActionState(testConnectorAction, initialState);
  const [profileState, profileFormAction, profilePending] = useActionState(saveScoreWeightProfileAction, initialState);
  const profileRecords = scoreProfiles.map((record) => objectValue(record.score_weight_profile));
  const competitorDomains = Array.isArray(launch.competitor_domains)
    ? launch.competitor_domains.join("\n")
    : competitors.flatMap((item) => item.official_domains || []).join("\n");
  const schedule = objectValue(launch.schedule);
  const connectors = objectValue(launch.external_connectors);
  const openaiConnector = objectValue(connectors.openai);
  const perplexityConnector = objectValue(connectors.perplexity);
  const googleConnector = objectValue(connectors.google_ai_mode);
  const scoringProfile = stringValue(launch.scoring_profile) || stringValue(scoreConfig?.formula_version) || "visibility_v1.0";
  const selectedProfile = profileRecords.find((profile) => stringValue(profile.profile_key) === scoringProfile)
    || profileRecords.find((profile) => stringValue(profile.profile_key) === "visibility_v1.0")
    || {};
  const profileWeights = objectValue(selectedProfile.weights) || {};
  const selectedFormula = scoreFormulas.find((formula) => stringValue(formula.formula_version) === stringValue(selectedProfile.base_formula_version));
  const selectedWeights = Object.keys(profileWeights).length
      ? profileWeights
      : selectedFormula?.weights;
  return (
    <form className="configForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="provider" value="" />
      <input {...hydrationControlProps} type="hidden" name="competitor_domains_snapshot" value={competitorDomains} />
      <input {...hydrationControlProps} type="hidden" name="status" value={stringValue(launch.status) || "draft"} />
      <label><span>客户邮箱</span><input {...hydrationControlProps} name="customer_email" type="email" defaultValue={stringValue(launch.customer_email)} required /></label>
      <label><span>主域名</span><input {...hydrationControlProps} name="primary_domain" defaultValue={stringValue(launch.primary_domain)} required /></label>
      <label><span>Locale</span><input {...hydrationControlProps} name="locale" defaultValue={stringValue(launch.locale) || "en"} required /></label>
      <label><span>国家代码</span><input {...hydrationControlProps} name="country_code" defaultValue={stringValue(launch.country_code) || "GLOBAL"} required /></label>
      <label><span>时区</span><input {...hydrationControlProps} name="timezone" defaultValue={stringValue(launch.timezone) || "UTC"} required /></label>
      <label>
        <span>采集模式</span>
        <select {...hydrationControlProps} name="collection_mode" defaultValue={stringValue(launch.collection_mode) || "api"}>
          <option value="api">真实 API</option>
          <option value="manual">手工补录</option>
        </select>
      </label>
      <div className="readonlyField"><span>配置状态</span><strong>{statusLabel(stringValue(launch.status) || "draft")}</strong></div>
      <section className="wideField configBlock">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">评分配置</p>
            <h3>评分方案</h3>
          </div>
        </div>
        <p className="muted">
          评分方案决定报告和项目看板如何合成总分。默认方案和自定义方案在同一个下拉框中选择；调整默认方案说明或权重时，请另存为新的自定义方案。
        </p>
        <label>
          <span>当前评分方案</span>
          <select {...hydrationControlProps} name="scoring_profile" defaultValue={scoringProfile}>
            {profileRecords.map((profile) => {
              const key = stringValue(profile.profile_key);
              return <option value={key} key={key}>{stringValue(profile.name) || key}</option>;
            })}
          </select>
        </label>
        <div className="readonlyField">
          <span>当前说明</span>
          <strong>{stringValue(selectedProfile.description) || stringValue(selectedFormula?.description) || "未填写说明"}</strong>
        </div>
        <ScoreWeightEditor
          baseFormulaVersion={stringValue(selectedProfile.base_formula_version) || "visibility_v1.0"}
          formAction={profileFormAction}
          pending={profilePending}
          projectId={projectId}
          profile={selectedProfile}
          weights={selectedWeights}
        />
        <ActionState state={profileState} />
      </section>
      <section className="wideField configBlock">
        <div className="sectionTitle">
          <div>
            <p className="eyebrow">连接器配置</p>
            <h3>采集与回答源</h3>
          </div>
        </div>
        <p className="muted formIntro">API key 在当前页明文输入，便于配置时检查；已保存 key 可由项目管理员点击临时显示。测试按钮会写入最新测试结果，并更新连接状态。</p>
        <div className="connectorGrid">
          <ConnectorConfigCard
            connector={openaiConnector}
            envDefault="OPENAI_API_KEY"
            keyPrefix="connector_openai"
            modeDefault="official_api"
            modelDefault="gpt-4.1-mini"
            name="OpenAI 连接器"
            provider="openai"
            statusDefault="not_configured"
            testAction={testFormAction}
            testPending={testPending}
          />
          <ConnectorConfigCard
            connector={perplexityConnector}
            envDefault="PERPLEXITY_API_KEY"
            keyPrefix="connector_perplexity"
            modeDefault="official_api"
            modelDefault="sonar"
            name="Perplexity 连接器"
            provider="perplexity"
            statusDefault="not_configured"
            testAction={testFormAction}
            testPending={testPending}
          />
          <ConnectorConfigCard
            connector={googleConnector}
            envDefault="GOOGLE_MANUAL_BACKFILL"
            keyPrefix="connector_google_ai_mode"
            modeDefault="manual_backfill"
            modelDefault="google_ai_mode"
            name="Google AI Mode"
            provider="google_ai_mode"
            statusDefault="manual_ready"
            testAction={testFormAction}
            testPending={testPending}
          />
        </div>
        <ActionState state={testState} />
      </section>
      <details className="advancedField">
        <summary>高级配置：调度</summary>
        <div className="formGrid">
          <label>
            <span>调度频率</span>
            <select {...hydrationControlProps} name="schedule_cadence" defaultValue={stringValue(schedule.cadence) || "weekly"}>
              <option value="daily">每日</option>
              <option value="weekly">每周</option>
              <option value="monthly">每月</option>
            </select>
          </label>
          <label>
            <span>运行日</span>
            <select {...hydrationControlProps} name="schedule_weekday" defaultValue={stringValue(schedule.weekday) || "monday"}>
              <option value="monday">周一</option>
              <option value="tuesday">周二</option>
              <option value="wednesday">周三</option>
              <option value="thursday">周四</option>
              <option value="friday">周五</option>
              <option value="saturday">周六</option>
              <option value="sunday">周日</option>
            </select>
          </label>
        </div>
      </details>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存启动配置"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function ConnectorConfigCard({
  connector,
  envDefault,
  keyPrefix,
  modeDefault,
  modelDefault,
  name,
  provider,
  statusDefault,
  testAction,
  testPending
}: {
  connector: Record<string, unknown>;
  envDefault: string;
  keyPrefix: string;
  modeDefault: string;
  modelDefault: string;
  name: string;
  provider: string;
  statusDefault: string;
  testAction: (payload: FormData) => void;
  testPending: boolean;
}) {
  const status = stringValue(connector.status) || statusDefault;
  const initialMode = stringValue(connector.mode) || modeDefault;
  const [mode, setMode] = useState(initialMode);
  const [revealState, revealFormAction, revealPending] = useActionState(revealConnectorSecretAction, initialState);
  const model = stringValue(connector.model) || modelDefault;
  const modelOptions = connectorModelOptions(provider, mode);
  const modelValue = modelOptions.some((option) => option.value === model) ? model : modelOptions[0]?.value || modelDefault;
  return (
    <div className="connectorCard">
      <div className="sectionTitle">
        <h3>{name}</h3>
        <span className="statusPill">{statusLabel(status)}</span>
      </div>
      <input {...hydrationControlProps} type="hidden" name={`${keyPrefix}_status`} value={status} />
      <input {...hydrationControlProps} type="hidden" name={`${keyPrefix}_secret_ref`} value={stringValue(connector.secret_ref)} />
      <div className="readonlyField">
        <span>连接状态</span>
        <strong>{statusLabel(status)}</strong>
      </div>
      <label>
        <span>运行模式</span>
        <select
          {...hydrationControlProps}
          name={`${keyPrefix}_mode`}
          value={mode}
          onChange={(event) => setMode(event.target.value)}
        >
          {connectorModeOptions(provider).map((option) => (
            <option value={option.value} key={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
      <label>
        <span>模型 / 服务</span>
        <select {...hydrationControlProps} key={`${keyPrefix}-${mode}`} name={`${keyPrefix}_model`} defaultValue={modelValue}>
          {modelOptions.map((option) => (
            <option value={option.value} key={option.value}>{option.label}</option>
          ))}
        </select>
      </label>
      <label><span>API key</span><input {...hydrationControlProps} name={`${keyPrefix}_raw_secret`} type="text" placeholder="可直接输入和检查；保存后普通页面不自动回显" /></label>
      <label><span>环境变量</span><input {...hydrationControlProps} name={`${keyPrefix}_env_var`} defaultValue={stringValue(connector.env_var) || envDefault} /></label>
      <label className="wideField"><span>备注</span><textarea {...hydrationControlProps} name={`${keyPrefix}_notes`} defaultValue={stringValue(connector.notes)} placeholder="记录测试状态、账号范围或手工采集说明。" /></label>
      <div className="actionRow">
        <button
          type="submit"
          className="secondary"
          formAction={testAction}
          disabled={testPending}
          onClick={(event) => {
            const input = event.currentTarget.form?.querySelector<HTMLInputElement>("input[name='provider']");
            if (input) {
              input.value = provider;
            }
          }}
        >
          {testPending ? "测试中..." : "测试连接"}
        </button>
        <button
          type="submit"
          className="secondary"
          formAction={revealFormAction}
          disabled={revealPending || !stringValue(connector.secret_ref)}
          onClick={(event) => {
            const input = event.currentTarget.form?.querySelector<HTMLInputElement>("input[name='provider']");
            if (input) {
              input.value = provider;
            }
          }}
        >
          {revealPending ? "显示中..." : "显示已保存 API key"}
        </button>
      </div>
      <ActionState state={revealState} />
    </div>
  );
}

export function CompetitorEditor({ projectId, competitors }: { projectId: string; competitors: Competitor[] }) {
  const [draftCount, setDraftCount] = useState(0);
  const drafts = Array.from({ length: draftCount }, (_, index) => index);
  return (
    <div className="stack">
      {competitors.map((competitor, index) => (
        <details className="accordionItem" key={`${index}-${competitor.id || competitor.canonical_name}`}>
          <summary>
            <span>竞品 {index + 1} - {competitor.canonical_name || "未命名竞品"}</span>
            <small>{statusLabel(competitor.status)}</small>
          </summary>
          <CompetitorForm competitor={competitor} projectId={projectId} />
          {competitor.id ? <CompetitorStatusActions competitor={competitor} projectId={projectId} /> : null}
        </details>
      ))}
      {drafts.map((draftIndex) => (
        <details className="accordionItem addItem" key={`draft-${draftIndex}`} open>
          <summary>
            <span>竞品 {competitors.length + draftIndex + 1} - 未命名竞品</span>
            <small>待填写</small>
          </summary>
          <CompetitorForm projectId={projectId} />
        </details>
      ))}
      <div className="actionRow">
        <button type="button" className="secondary" onClick={() => setDraftCount((count) => count + 1)}>
          新增竞品
        </button>
      </div>
    </div>
  );
}

function CompetitorForm({ projectId, competitor }: { projectId: string; competitor?: Competitor }) {
  const [state, formAction, pending] = useActionState(saveCompetitorEntityAction, initialState);
  const isNew = !competitor?.id;
  return (
    <form className="configForm compactConfig" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="competitor_id" value={competitor?.id || ""} />
      <label><span>{isNew ? "新增竞品名称" : "竞品名称"}</span><input {...hydrationControlProps} name="canonical_name" defaultValue={competitor?.canonical_name || ""} required /></label>
      <label><span>域名</span><textarea {...hydrationControlProps} name="official_domains" defaultValue={(competitor?.official_domains || []).join("\n")} /></label>
      <label><span>母公司</span><input {...hydrationControlProps} name="parent_company" defaultValue={competitor?.parent_company || ""} /></label>
      <label><span>产品线</span><textarea {...hydrationControlProps} name="product_lines" defaultValue={(competitor?.product_lines || []).join("\n")} /></label>
      <input {...hydrationControlProps} type="hidden" name="status" value={competitor?.status || "active"} />
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : isNew ? "新增竞品" : "保存竞品"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function CompetitorStatusActions({ projectId, competitor }: { projectId: string; competitor: Competitor }) {
  const [state, formAction, pending] = useActionState(saveCompetitorEntityAction, initialState);
  const status = String(competitor.status || "active").toLowerCase();
  return (
    <form className="competitorStatusActions" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="competitor_id" value={competitor.id || ""} />
      <input {...hydrationControlProps} type="hidden" name="canonical_name" value={competitor.canonical_name || ""} />
      <input {...hydrationControlProps} type="hidden" name="official_domains" value={(competitor.official_domains || []).join("\n")} />
      <input {...hydrationControlProps} type="hidden" name="parent_company" value={competitor.parent_company || ""} />
      <input {...hydrationControlProps} type="hidden" name="product_lines" value={(competitor.product_lines || []).join("\n")} />
      <span className="muted">状态操作</span>
      <button type="submit" name="status" value="active" disabled={pending || status === "active"}>启动</button>
      <button type="submit" name="status" value="paused" className="secondary" disabled={pending || status === "paused"}>暂停</button>
      <button
        type="submit"
        name="status"
        value="archived"
        className="danger"
        disabled={pending || status === "archived"}
        onClick={(event) => {
          if (!window.confirm("确认归档这个竞品？归档后不会物理删除。")) {
            event.preventDefault();
          }
        }}
      >
        归档
      </button>
      <ActionState state={state} />
    </form>
  );
}

export function MemberManagement({ projectId }: { projectId: string }) {
  return (
    <div className="twoCol compact">
      <MemberSaveForm projectId={projectId} />
      <MemberDeleteForm projectId={projectId} />
    </div>
  );
}

export function InvitationList({ invitations, projectId }: { invitations: RuntimeListRecord[]; projectId: string }) {
  if (!invitations.length) {
    return <p className="muted emptyState">暂无邀请记录。</p>;
  }
  const pendingInvitations = invitations.filter((record) => stringValue(objectValue(record.invitation).status) === "pending");
  const inactiveInvitations = invitations.filter((record) => stringValue(objectValue(record.invitation).status) !== "pending");
  const renderInvitation = (record: RuntimeListRecord, mode: "active" | "history", index: number) => {
    const invitation = objectValue(record.invitation);
    const invitationId = stringValue(invitation.id);
    const status = stringValue(invitation.status);
    return (
      <div className="summaryListRow" key={`${mode}-${index}-${invitationId || stringValue(invitation.email)}`}>
        <div>
          <strong>{stringValue(invitation.email) || "未知邮箱"}</strong>
          <p className="muted">
            {roleLabel(stringValue(invitation.role) || "viewer")} · {statusLabel(status)} · {stringValue(invitation.created_at) || "无创建时间"}
          </p>
          <p className="muted">邀请 ID：{invitationId || "无"} · token hash：{shortValue(stringValue(invitation.invite_token_hash)) || "未生成"}</p>
        </div>
        {mode === "active" && invitationId ? <InvitationActionForm invitationId={invitationId} projectId={projectId} /> : null}
      </div>
    );
  };
  return (
    <div className="invitationListStack">
      <section>
        <p className="eyebrow">当前可用邀请</p>
        {pendingInvitations.length ? (
          <div className="summaryList activeInvitationList">
            {pendingInvitations.map((record, index) => renderInvitation(record, "active", index))}
          </div>
        ) : (
          <p className="muted emptyState">暂无待处理邀请。</p>
        )}
      </section>
      {inactiveInvitations.length ? (
        <details className="historyPanel" open>
          <summary>
            <span>历史 / 已失效邀请</span>
            <small>{inactiveInvitations.length} 条</small>
          </summary>
          <div className="summaryList inactiveInvitationList">
            {inactiveInvitations.map((record, index) => renderInvitation(record, "history", index))}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function InvitationActionForm({ invitationId, projectId }: { invitationId: string; projectId: string }) {
  const [state, formAction, pending] = useActionState(invitationAction, initialState);
  return (
    <form className="inlineForm compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="invitation_id" value={invitationId} />
      <input {...hydrationControlProps} type="hidden" name="action" value="revoke" />
      <button type="submit" className="danger" disabled={pending}>{pending ? "撤销中..." : "撤销邀请"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function MemberList({ members }: { members: RuntimeListRecord[] }) {
  if (!members.length) {
    return <p className="muted emptyState">暂无成员记录。</p>;
  }
  return (
    <div className="summaryList">
      {members.map((record, index) => {
        const member = objectValue(record.member);
        const memberId = stringValue(member.id) || stringValue(record.id) || stringValue(member.user_id);
        return (
          <div className="summaryListRow" key={`${index}-${memberId}`}>
            <div>
              <strong>{stringValue(member.user_id) || "未知用户"}</strong>
              <p className="muted">{roleLabel(stringValue(member.role) || "viewer")} · {stringValue(member.created_at) || "无创建时间"}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function PromptEditor({ projectId, prompt }: { projectId: string; prompt: PromptRecord }) {
  const [editing, setEditing] = useState(false);
  const [state, formAction, pending] = useActionState(savePromptAction, initialState);
  return (
    <div className="promptRow">
      <div className="promptSummary">
        <strong>{prompt.text || "未命名 Prompt"}</strong>
        <span>{prompt.intent_type || "未设置"}</span>
        <span>{prompt.city || "未设置"}</span>
        <span>{statusLabel(prompt.status)}</span>
        <span>{String(prompt.priority ?? "")}</span>
        <button type="button" className="secondary" onClick={() => setEditing((value) => !value)}>
          {editing ? "收起" : "修改"}
        </button>
      </div>
      {editing ? (
        <form className="configForm compactConfig" action={formAction}>
          <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
          <input {...hydrationControlProps} type="hidden" name="prompt_id" value={prompt.id || ""} />
          <label className="wideField"><span>Prompt 文本</span><textarea {...hydrationControlProps} name="text" defaultValue={prompt.text || ""} required /></label>
          <label><span>Intent</span><input {...hydrationControlProps} name="intent_type" defaultValue={prompt.intent_type || "brand_awareness"} required /></label>
          <label><span>城市</span><input {...hydrationControlProps} name="city" defaultValue={prompt.city || "Global"} required /></label>
          <label><span>语言</span><input {...hydrationControlProps} name="language" defaultValue={prompt.language || "en"} required /></label>
          <label><span>目标品牌</span><input {...hydrationControlProps} name="target_brand" defaultValue={prompt.target_brand || ""} required /></label>
          <label><span>优先级</span><input {...hydrationControlProps} name="priority" type="number" min={0} defaultValue={String(prompt.priority ?? 1)} required /></label>
          <label><span>Intent 权重</span><input {...hydrationControlProps} name="intent_weight" type="number" min={0.01} step={0.01} defaultValue={String(prompt.intent_weight ?? 1)} required /></label>
          <label><span>Prompt 版本</span><input {...hydrationControlProps} name="prompt_version" defaultValue={prompt.prompt_version || "au_dtc_ecommerce_v1"} required /></label>
          <label className="wideField"><span>竞品名称</span><textarea {...hydrationControlProps} name="competitors" defaultValue={(prompt.competitors || []).join("\n")} /></label>
          <label>
            <span>状态</span>
            <select {...hydrationControlProps} name="status" defaultValue={prompt.status || "active"}>
              <option value="active">运行中</option>
              <option value="paused">已暂停</option>
              <option value="archived">已归档</option>
            </select>
          </label>
          <div className="formActions">
            <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存 Prompt"}</button>
          </div>
          <ActionState state={state} />
        </form>
      ) : null}
    </div>
  );
}

function MemberSaveForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(saveMemberAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>用户 ID / 邮箱</span><input {...hydrationControlProps} name="user_id" placeholder="customer@example.com" required /></label>
      <label>
        <span>角色</span>
        <select {...hydrationControlProps} name="role" defaultValue="viewer">
          <option value="owner">负责人</option>
          <option value="admin">管理员</option>
          <option value="analyst">分析师</option>
          <option value="viewer">客户查看者</option>
        </select>
      </label>
      <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存成员"}</button>
      <ActionState state={state} />
    </form>
  );
}

function MemberDeleteForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(deleteMemberAction, initialState);
  return (
    <form className="inlineForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <label><span>用户 ID / 邮箱</span><input {...hydrationControlProps} name="user_id" placeholder="customer@example.com" required /></label>
      <button type="submit" className="danger" disabled={pending}>{pending ? "删除中..." : "删除成员"}</button>
      <ActionState state={state} />
    </form>
  );
}

export function PromptImportForm({ projectId, promptLimit }: { projectId: string; promptLimit: number }) {
  const [state, formAction, pending] = useActionState(importPromptsAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="prompt_limit" value={String(promptLimit)} />
      {state.error ? <p className="muted errorText">{state.error}</p> : null}
      <label><span>最大导入行数</span><input {...hydrationControlProps} name="max_rows" type="number" min={1} max={200} defaultValue={100} /></label>
      <label>
        <span>CSV 内容</span>
        <textarea
          {...hydrationControlProps}
          name="csv_content"
          placeholder={"text,intent_type,city,language,priority\nIs the brand visible in AI answers?,brand_awareness,Global,en,10"}
          required
        />
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "导入中..." : "导入 Prompt CSV"}</button>
      </div>
      {!state.error ? <ActionState state={state} /> : null}
    </form>
  );
}

function knowledgeApplicationData(application: Record<string, unknown>) {
  return {
    documents: arrayValue(application.knowledge_documents),
    facts: arrayValue(application.knowledge_facts),
    jobs: arrayValue(application.generation_jobs),
    promptTemplates: arrayValue(application.prompt_templates),
    promptCandidates: arrayValue(application.prompt_candidates),
    faqCandidates: arrayValue(application.faq_candidates),
    contentDrafts: arrayValue(application.content_drafts).map((item) => objectValue(objectValue(item).draft || item)),
  };
}

export function KnowledgeDocumentImportPanel({
  application,
  defaultLocale,
  defaultMarketCode,
  importedCount,
  pipeline,
  projectId
}: {
  application: Record<string, unknown>;
  defaultLocale: string;
  defaultMarketCode: string;
  importedCount: string;
  pipeline: Record<string, { total_count: number; records: Record<string, unknown>[] }>;
  projectId: string;
}) {
  const { documents, jobs } = knowledgeApplicationData(application);
  const pipelineRuns = pipeline.pipelineRuns?.records || [];
  const importJobs = pipeline.importJobs?.records || [];
  return (
    <section className="detailPanel unframedPanel knowledgePanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">知识库导入</p>
          <h2>来源导入、解析和事实抽取</h2>
        </div>
      </div>
      <p className="muted formIntro">
        所有来源统一进入生产 Pipeline。系统按文件能力矩阵选择 Docling、MinerU、Unstructured、Apache Tika 或 MarkItDown，URL 使用 Crawl4AI；随后完成 Chunk、BGE-M3、Qdrant、事实候选和质量门禁。
      </p>
      {importedCount ? (
        <div className="notice success">
          <p>知识事实已导入：{importedCount} 条。可以切换到“检索”验证，也可以进入“质检”审核。</p>
        </div>
      ) : null}
      <div className="knowledgePipeline">
        <div><span>1</span><strong>来源预检</strong><p>阻断私有 URL、空文件和超限内容。</p></div>
        <div><span>2</span><strong>解析/OCR/表格</strong><p>Docling、MinerU、Unstructured、Tika、MarkItDown 统一输出契约。</p></div>
        <div><span>3</span><strong>Chunk + BGE-M3</strong><p>生成可视化 chunk，写入真实 Qdrant。</p></div>
        <div><span>4</span><strong>事实/Prompt/文案</strong><p>DeepSeek v4 Flash 生成候选，必须人工审核和证据追踪。</p></div>
      </div>
      <KnowledgePipelineCreateForm
        defaultLocale={defaultLocale}
        defaultMarketCode={defaultMarketCode}
        projectId={projectId}
      />
      <div className="twoCol compact">
        <RecordList
          title="最新 Pipeline"
          emptyText="暂无 pipeline。"
          records={pipelineRuns}
          pick={(run) => [
            `${knowledgePipelineRunTypeLabel(stringValue(run.run_type))} · ${shortValue(stringValue(run.id))}`,
            `${statusLabel(stringValue(run.status))} · ${stringValue(run.entry_source) || "mixed"} · ${stringValue(run.updated_at) || "无更新时间"}`
          ]}
        />
        <RecordList
          title="导入任务"
          emptyText="暂无导入任务。"
          records={importJobs}
          pick={(job) => [
            `${knowledgeSourceTypeLabel(stringValue(job.source_mode))} · ${shortValue(stringValue(job.id))}`,
            `${statusLabel(stringValue(job.status))} · attempts ${stringValue(job.attempt_count) || "0"}`
          ]}
        />
      </div>
      <RecordList
        title="知识来源资产"
        emptyText="暂无知识来源资产。"
        records={documents}
        pick={(document) => [
          stringValue(document.title) || stringValue(document.source_uri) || shortValue(stringValue(document.id)),
          `${statusLabel(stringValue(document.status))} · ${knowledgeSourceTypeLabel(stringValue(document.asset_type))} · ${shortValue(stringValue(document.id))}`
        ]}
      />
      <RecordList
        title="最近解析/生成任务"
        emptyText="暂无解析或抽取任务。"
        records={jobs}
        pick={(job) => [
          `${knowledgeJobTypeLabel(stringValue(job.job_type))} · ${shortValue(stringValue(job.id))}`,
          `${statusLabel(stringValue(job.status))} · ${stringValue(job.generation_model) || "deepseek-v4-flash"}`
        ]}
      />
    </section>
  );
}

export function KnowledgePipelineCreateForm({
  defaultLocale,
  defaultMarketCode,
  projectId
}: {
  defaultLocale: string;
  defaultMarketCode: string;
  projectId: string;
}) {
  const [state, formAction, pending] = useActionState(createKnowledgePipelineAction, initialState);
  const [sourceMode, setSourceMode] = useState("pasted_text");
  const [fileQueue, setFileQueue] = useState<KnowledgeFileInspection[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const updateFileQueue = async (files: File[]) => {
    setFileQueue(files.map((file) => ({
      file,
      hash: "",
      recommendation: knowledgeFileRecommendation(file),
      status: "checking",
      note: "正在计算文件指纹"
    })));
    setFileQueue(await Promise.all(files.map(inspectKnowledgeFile)));
  };
  const removeQueuedFile = (indexToRemove: number) => {
    const input = fileInputRef.current;
    if (!input) return;
    const dataTransfer = new DataTransfer();
    Array.from(input.files || []).forEach((file, index) => {
      if (index !== indexToRemove) dataTransfer.items.add(file);
    });
    input.files = dataTransfer.files;
    void updateFileQueue(Array.from(dataTransfer.files));
  };
  return (
    <div className="detailPanel">
      <p className="eyebrow">生产流水线</p>
      <h3>创建完整知识库 Pipeline</h3>
      <p className="muted">创建后会自动入队并启动：导入、解析、chunk、embedding、事实抽取、Prompt/文案生成和质量门禁会由 knowledge-worker 推进。</p>
      <form className="configForm singleColumn" action={formAction}>
        <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
        <input {...hydrationControlProps} type="hidden" name="run_type" value="full_ingestion" />
        {state.error ? <p className="muted errorText">{state.error}</p> : null}
        <div className="twoCol compact noTopMargin">
          <label>
            <span>来源类型</span>
            <select {...hydrationControlProps} name="source_mode" defaultValue="pasted_text" onChange={(event) => setSourceMode(event.target.value)}>
              <option value="pasted_text">粘贴文本</option>
              <option value="file">上传文件</option>
              <option value="csv">CSV</option>
              <option value="url">单个公网 URL</option>
              <option value="url_batch">多个公网 URL</option>
              <option value="site_crawl">站点深度抓取</option>
              <option value="sitemap">Sitemap 抓取</option>
            </select>
          </label>
          <div className="notice"><p>此入口固定创建完整导入。重新解析、切分、索引和事实刷新请在“处理任务”中从历史 Pipeline 创建版本化重跑。</p></div>
        </div>
        <div className="threeCol compact noTopMargin">
          <label><span>市场</span><input {...hydrationControlProps} name="market_code" defaultValue={defaultMarketCode || "GLOBAL"} /></label>
          <label><span>语言区域</span><input {...hydrationControlProps} name="locale" defaultValue={defaultLocale || "en"} /></label>
          <label><span>城市</span><input {...hydrationControlProps} name="city" placeholder="可选，例如 Shanghai" /></label>
        </div>
        {["url", "url_batch", "site_crawl", "sitemap"].includes(sourceMode) ? (
          <>
            <label className="wideField">
              <span>{sourceMode === "url" ? "URL" : sourceMode === "sitemap" ? "Sitemap URL" : "URL（每行一个）"}</span>
              <textarea {...hydrationControlProps} name="source_urls" placeholder="https://example.com/faq" required />
            </label>
            <div className="threeCol compact noTopMargin">
              <label><span>最大页面</span><input {...hydrationControlProps} type="number" name="max_pages" min={1} max={500} defaultValue={sourceMode === "url" ? 1 : 50} /></label>
              <label><span>抓取深度</span><input {...hydrationControlProps} type="number" name="depth_limit" min={0} max={5} defaultValue={sourceMode === "site_crawl" ? 2 : 0} /></label>
              <label><span>遵守 robots.txt</span><select {...hydrationControlProps} name="respect_robots" defaultValue="1"><option value="1">是</option><option value="0">否（仅经授权站点）</option></select></label>
            </div>
            <div className="twoCol compact noTopMargin">
              <label><span>包含规则</span><textarea {...hydrationControlProps} name="include_patterns" placeholder="每行一个 glob，例如 https://example.com/help/*" /></label>
              <label><span>排除规则</span><textarea {...hydrationControlProps} name="exclude_patterns" placeholder="每行一个 glob，例如 */login*" /></label>
            </div>
          </>
        ) : sourceMode === "file" ? (
          <>
            <div className="twoCol compact noTopMargin">
              <label>
                <span>解析策略</span>
                <select {...hydrationControlProps} name="adapter_engine" defaultValue="auto">
                  <option value="auto">自动选择</option>
                  <option value="docling">Docling</option>
                  <option value="mineru">MinerU</option>
                  <option value="unstructured">Unstructured</option>
                  <option value="tika">Apache Tika</option>
                  <option value="markitdown">MarkItDown</option>
                </select>
              </label>
              <label><span>文件标题</span><input {...hydrationControlProps} name="title" defaultValue="知识库文件导入" /></label>
            </div>
            <label className="knowledgeDropzone">
              <span>拖入或选择文件</span>
              <small>单次最多 20 个，每个不超过 50 MB；服务端会再次执行安全预检和去重。</small>
              <input
                {...hydrationControlProps}
                ref={fileInputRef}
                type="file"
                name="source_files"
                multiple
                required
                accept=".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.html,.htm,.png,.jpg,.jpeg,.webp,.tif,.tiff"
                onChange={(event) => void updateFileQueue(Array.from(event.currentTarget.files || []))}
              />
            </label>
            <div className="knowledgeFileQueue" aria-live="polite">
              {fileQueue.map((inspection, index) => (
                <div className="knowledgeFileQueueRow" key={`${inspection.file.name}-${inspection.file.size}-${inspection.file.lastModified}`}>
                  <div>
                    <strong>{inspection.file.name}</strong>
                    <p>{formatFileSize(inspection.file.size)} · {inspection.file.type || "未知 MIME"} · {inspection.recommendation}</p>
                    <small>{inspection.note}</small>
                    {inspection.hash ? <code title={inspection.hash}>SHA-256 {inspection.hash.slice(0, 16)}...</code> : null}
                  </div>
                  <div className="knowledgeFileQueueStatus">
                    <span className={`statusPill ${inspection.status === "blocked" ? "dangerPill" : ""}`}>
                      {inspection.status === "checking" ? "检查中" : inspection.status === "ready" ? "待上传" : "已阻断"}
                    </span>
                    <button type="button" className="secondary" onClick={() => removeQueuedFile(index)} aria-label={`移除 ${inspection.file.name}`}>移除</button>
                  </div>
                </div>
              ))}
              {!fileQueue.length ? <p className="muted">尚未选择文件。</p> : null}
            </div>
          </>
        ) : (
          <>
            <label><span>标题</span><input {...hydrationControlProps} name="title" defaultValue="知识库导入" /></label>
            <label>
              <span>{sourceMode === "csv" ? "CSV 内容" : "文本内容"}</span>
              <textarea {...hydrationControlProps} name={sourceMode === "csv" ? "csv_content" : "source_text"} placeholder="粘贴产品、服务、FAQ、竞品或市场事实。" />
            </label>
          </>
        )}
        <div className="formActions">
          <button
            type="submit"
            disabled={pending || (sourceMode === "file" && (fileQueue.length === 0 || fileQueue.some((file) => file.status !== "ready")))}
          >
            {pending ? "启动中..." : "创建并启动 Pipeline"}
          </button>
        </div>
        {!state.error ? <ActionState state={state} /> : null}
      </form>
    </div>
  );
}

export function KnowledgeDashboardPanel({
  application,
  searchPage
}: {
  application: Record<string, unknown>;
  searchPage: { total_count?: number; embedding_model?: string };
}) {
  const { documents, facts, jobs, promptCandidates, faqCandidates, contentDrafts } = knowledgeApplicationData(application);
  const approvedFacts = facts.filter((fact) => stringValue(fact.status) === "active");
  const pendingFacts = facts.filter((fact) => ["pending_review", "pending"].includes(stringValue(fact.status) || stringValue(fact.review_status)));
  const failedJobs = jobs.filter((job) => stringValue(job.status) === "failed");
  return (
    <section className="detailPanel unframedPanel knowledgePanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">知识库看板</p>
          <h2>覆盖、质量和应用状态</h2>
        </div>
      </div>
      <div className="metricGrid compact">
        <MetricCard label="知识来源" value={documents.length} />
        <MetricCard label="知识事实" value={facts.length} />
        <MetricCard label="已批准事实" value={approvedFacts.length} />
        <MetricCard label="待质检事实" value={pendingFacts.length} />
        <MetricCard label="生成任务" value={jobs.length} />
        <MetricCard label="Prompt 候选" value={promptCandidates.length} />
      </div>
      <div className="twoCol compact">
        <div className="detailPanel">
          <p className="eyebrow">检索健康度</p>
          <h3>已批准知识索引</h3>
          <SummaryGrid rows={[
            ["最近检索匹配", String(searchPage.total_count || 0)],
            ["Embedding", stringValue(searchPage.embedding_model) || "BAAI/bge-m3"],
            ["失败任务", String(failedJobs.length)],
            ["Prompt 可用来源", approvedFacts.length ? "已具备" : "缺少已批准知识"]
          ]} />
        </div>
        <RecordList
          title="知识来源"
          emptyText="暂无知识来源。"
          records={documents}
          pick={(document) => [
            stringValue(document.title) || stringValue(document.source_url) || shortValue(stringValue(document.id)),
            `${statusLabel(stringValue(document.status))} · ${knowledgeSourceTypeLabel(stringValue(document.source_type))} · ${stringValue(document.updated_at) || "无更新时间"}`
          ]}
        />
      </div>
      <div className="twoCol compact">
        <RecordList
          title="知识应用任务"
          emptyText="暂无生成任务。"
          records={jobs}
          pick={(job) => [
            `${knowledgeJobTypeLabel(stringValue(job.job_type))} · ${shortValue(stringValue(job.id))}`,
            `${statusLabel(stringValue(job.status))} · ${stringValue(job.generation_prompt_version) || "无模板版本"}`
          ]}
        />
        <RecordList
          title="FAQ 候选"
          emptyText="暂无 FAQ 候选。"
          records={faqCandidates}
          pick={(candidate) => [
            stringValue(candidate.question) || shortValue(stringValue(candidate.id)),
            `${statusLabel(stringValue(candidate.review_status))} · facts ${arrayValue(candidate.used_knowledge_fact_ids).length}`
          ]}
        />
      </div>
      <RecordList
        title="GEO 文案草稿"
        emptyText="暂无知识生成文案草稿。"
        records={contentDrafts}
        pick={(draft) => [
          stringValue(draft.title) || shortValue(stringValue(draft.id)),
          `${statusLabel(stringValue(draft.review_status))} · ${stringValue(draft.content_type)}`
        ]}
      />
    </section>
  );
}

export function KnowledgeQualityPanel({
  application,
  pipeline,
  projectId
}: {
  application: Record<string, unknown>;
  pipeline?: Record<string, { total_count: number; records: Record<string, unknown>[] }>;
  projectId: string;
}) {
  const { facts } = knowledgeApplicationData(application);
  const factCandidates = pipeline?.factCandidates?.records || [];
  const pendingCandidates = factCandidates.filter((fact) => stringValue(fact.status) === "pending_review");
  const pendingFacts = facts.filter((fact) => ["pending_review", "pending"].includes(stringValue(fact.status) || stringValue(fact.review_status)));
  const approvedFacts = facts.filter((fact) => stringValue(fact.status) === "active");
  const lowConfidenceFacts = facts.filter((fact) => {
    const confidence = Number(stringValue(fact.confidence) || "1");
    return Number.isFinite(confidence) && confidence < 0.75;
  });
  const conflictFacts = facts.filter((fact) => /conflict|duplicate|superseded/i.test(`${stringValue(fact.review_status)} ${stringValue(fact.superseded_by_fact_id)}`));
  return (
    <section className="detailPanel unframedPanel knowledgePanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">知识库质检</p>
          <h2>事实审核、去重和风险处理</h2>
        </div>
      </div>
      <p className="muted formIntro">质检通过前，知识事实不会进入 Prompt 生成上下文。这里集中处理待审核、低置信度、重复和冲突事实。</p>
      <div className="metricGrid compact">
        <MetricCard label="待审核候选" value={pendingCandidates.length} />
        <MetricCard label="旧事实待审核" value={pendingFacts.length} />
        <MetricCard label="已批准" value={approvedFacts.length} />
        <MetricCard label="低置信度" value={lowConfidenceFacts.length} />
        <MetricCard label="重复/冲突" value={conflictFacts.length} />
      </div>
      <div className="twoCol compact">
        <KnowledgeFactCandidateReviewForm candidates={factCandidates} projectId={projectId} />
        <EvidenceRecordList
          title="Pipeline 候选事实"
          emptyText="暂无 pipeline 候选事实。"
          records={pendingCandidates.length ? pendingCandidates : factCandidates}
          projectId={projectId}
          pick={(fact) => [
            `${stringValue(fact.fact_type) || "fact"} · ${shortValue(stringValue(fact.id))}`,
            `${statusLabel(stringValue(fact.status))} · ${shortValue(stringValue(fact.object_value), 80)}`
          ]}
        />
      </div>
      <div className="twoCol compact">
        <KnowledgeFactReviewForm facts={facts} projectId={projectId} />
        <EvidenceRecordList
          title="正式知识事实"
          emptyText="暂无正式知识事实。"
          records={pendingFacts.length ? pendingFacts : facts}
          projectId={projectId}
          pick={(fact) => [
            `${stringValue(fact.fact_type) || "fact"} · ${shortValue(stringValue(fact.id))}`,
            `${statusLabel(stringValue(fact.status) || stringValue(fact.review_status))} · ${shortValue(stringValue(fact.object_value), 80)}`
          ]}
        />
      </div>
      <div className="twoCol compact">
        <RecordList
          title="低置信度事实"
          emptyText="暂无低置信度事实。"
          records={lowConfidenceFacts}
          pick={(fact) => [
            `${stringValue(fact.subject) || "未知主体"} · ${stringValue(fact.predicate) || "未知谓词"}`,
            `confidence ${stringValue(fact.confidence) || "无"} · ${shortValue(stringValue(fact.object_value), 80)}`
          ]}
        />
        <RecordList
          title="重复 / 冲突事实"
          emptyText="暂无重复或冲突事实。"
          records={conflictFacts}
          pick={(fact) => [
            `${stringValue(fact.fact_type) || "fact"} · ${shortValue(stringValue(fact.id))}`,
            `${stringValue(fact.review_status) || "needs_review"} · superseded ${shortValue(stringValue(fact.superseded_by_fact_id)) || "无"}`
          ]}
        />
      </div>
    </section>
  );
}

export function KnowledgeQualityRiskAcceptForm({
  gateRuns,
  projectId
}: {
  gateRuns: RuntimeListRecord[];
  projectId: string;
}) {
  const [state, formAction, pending] = useActionState(acceptKnowledgeQualityRiskAction, initialState);
  const eligibleGateRuns = gateRuns.filter((gate) => {
    const gateKey = stringValue(gate.gate_key);
    return ["warning", "blocked"].includes(stringValue(gate.status)) && !["security_gate", "traceability_gate"].includes(gateKey);
  });
  return (
    <form className="configForm singleColumn compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">授权接受风险</p>
      <h3>为非安全类门禁设置临时例外</h3>
      <p className="muted">
        仅项目管理员或内部运营人员可操作。安全门禁和证据追踪门禁不能接受风险；例外到期后需要重新处理问题。
      </p>
      {state.error ? <p className="muted errorText">{state.error}</p> : null}
      <label>
        <span>质量门禁</span>
        <select {...hydrationControlProps} name="quality_gate_run_id" defaultValue="" required>
          <option value="" disabled>选择阻断或警告门禁</option>
          {eligibleGateRuns.map((gate) => (
            <option key={stringValue(gate.id)} value={stringValue(gate.id)}>
              {stringValue(gate.gate_key)} · {statusLabel(stringValue(gate.status))} · {shortValue(stringValue(gate.id))}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>例外到期时间</span>
        <input {...hydrationControlProps} type="datetime-local" name="expires_at" required />
      </label>
      <label>
        <span>接受原因</span>
        <textarea {...hydrationControlProps} name="reason" rows={3} minLength={3} maxLength={1000} required placeholder="说明为什么可以临时接受、影响范围和后续处理责任。" />
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending || eligibleGateRuns.length === 0}>
          {pending ? "提交中..." : "确认接受风险"}
        </button>
      </div>
      {eligibleGateRuns.length === 0 ? <p className="muted">当前没有允许接受风险的门禁。</p> : null}
      {!state.error ? <ActionState state={state} /> : null}
    </form>
  );
}

export function KnowledgeStageRetryForm({
  projectId,
  stages
}: {
  projectId: string;
  stages: RuntimeListRecord[];
}) {
  const [state, formAction, pending] = useActionState(retryKnowledgePipelineStageAction, initialState);
  const retryable = stages.filter((stage) => ["failed", "blocked"].includes(stringValue(stage.status)));
  return (
    <form className="configForm singleColumn compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">失败恢复</p>
      <h3>重试自动处理阶段</h3>
      <label>
        <span>失败阶段</span>
        <select {...hydrationControlProps} name="pipeline_stage_id" defaultValue="" required>
          <option value="" disabled>选择失败或阻断阶段</option>
          {retryable.map((stage) => (
            <option key={stringValue(stage.id)} value={stringValue(stage.id)}>
              {stringValue(stage.stage_key)} · {statusLabel(stringValue(stage.status))}
            </option>
          ))}
        </select>
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending || retryable.length === 0}>{pending ? "重新入队中..." : "重试阶段"}</button>
      </div>
      {retryable.length === 0 ? <p className="muted">当前没有可自动重试的失败阶段。</p> : null}
      <ActionState state={state} />
    </form>
  );
}

export function KnowledgeMaintenanceRunForm({
  projectId,
  runs
}: {
  projectId: string;
  runs: RuntimeListRecord[];
}) {
  const [state, formAction, pending] = useActionState(createKnowledgeMaintenanceRunAction, initialState);
  const sourceRuns = runs.filter((run) => !["draft", "ready", "queued"].includes(stringValue(run.status)));
  return (
    <form className="configForm singleColumn compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="market_code" value="GLOBAL" />
      <input {...hydrationControlProps} type="hidden" name="locale" value="en" />
      <p className="eyebrow">版本化重跑</p>
      <h3>重新解析、切分、索引或抽取</h3>
      <label>
        <span>来源 Pipeline</span>
        <select {...hydrationControlProps} name="source_pipeline_run_id" defaultValue="" required>
          <option value="" disabled>选择历史 Pipeline</option>
          {sourceRuns.map((run) => <option key={stringValue(run.id)} value={stringValue(run.id)}>{shortValue(stringValue(run.id))} · {knowledgePipelineRunTypeLabel(stringValue(run.run_type))} · {statusLabel(stringValue(run.status))}</option>)}
        </select>
      </label>
      <label>
        <span>重跑类型</span>
        <select {...hydrationControlProps} name="run_type" defaultValue="reparse">
          <option value="reparse">重新解析</option>
          <option value="rechunk">重新切分</option>
          <option value="reindex">重新索引</option>
          <option value="fact_refresh">重新抽取事实</option>
          <option value="full_rebuild">完整重建</option>
        </select>
      </label>
      <input {...hydrationControlProps} type="hidden" name="adapter_engine" value="auto" />
      <input {...hydrationControlProps} type="hidden" name="chunk_profile_version" value="geo_chunk_profile_v1" />
      <input {...hydrationControlProps} type="hidden" name="cleaner_profile_version" value="geo_cleaner_v1" />
      <div className="notice"><p>重跑会创建新版本；旧 Parser Run、Chunk、事实候选、Prompt 候选和文案草稿不会被静默覆盖。</p></div>
      <div className="formActions"><button type="submit" disabled={pending || sourceRuns.length === 0}>{pending ? "创建中..." : "创建重跑任务"}</button></div>
      <ActionState state={state} />
    </form>
  );
}

export function KnowledgeChunkControlForm({
  chunks,
  projectId
}: {
  chunks: RuntimeListRecord[];
  projectId: string;
}) {
  const [state, formAction, pending] = useActionState(disableKnowledgeChunkAction, initialState);
  const activeChunks = chunks.filter((chunk) => stringValue(chunk.status) === "active");
  return (
    <form className="configForm singleColumn compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">Chunk 生命周期</p>
      <h3>禁用不应进入检索与生成的片段</h3>
      <label>
        <span>Chunk</span>
        <select {...hydrationControlProps} name="knowledge_chunk_id" defaultValue="" required>
          <option value="" disabled>选择运行中的 Chunk</option>
          {activeChunks.map((chunk) => (
            <option key={stringValue(chunk.id)} value={stringValue(chunk.id)}>
              {shortValue(stringValue(chunk.id))} · {shortValue(stringValue(chunk.text), 70)}
            </option>
          ))}
        </select>
      </label>
      <label><span>禁用原因</span><textarea {...hydrationControlProps} name="reason" minLength={3} required /></label>
      <div className="formActions">
        <button className="danger" type="submit" disabled={pending || activeChunks.length === 0}>{pending ? "禁用中..." : "禁用 Chunk"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function KnowledgeFactExtractionForm({
  assets,
  importJobs,
  projectId,
  runs
}: {
  assets: RuntimeListRecord[];
  importJobs: RuntimeListRecord[];
  projectId: string;
  runs: RuntimeListRecord[];
}) {
  const [state, formAction, pending] = useActionState(createKnowledgeFactExtractionAction, initialState);
  const sourceRuns = runs.filter((run) => !["draft", "ready", "queued", "failed", "cancelled"].includes(stringValue(run.status)));
  return (
    <form className="configForm singleColumn compactForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">事实抽取</p>
      <h3>从可检索 Chunk 生成事实候选</h3>
      <label>
        <span>来源 Pipeline</span>
        <select {...hydrationControlProps} name="source_pipeline_run_id" defaultValue="" required>
          <option value="" disabled>选择已产生 Chunk 的 Pipeline</option>
          {sourceRuns.map((run) => (
            <option key={stringValue(run.id)} value={stringValue(run.id)}>
              {shortValue(stringValue(run.id))} · {knowledgePipelineRunTypeLabel(stringValue(run.run_type))} · {statusLabel(stringValue(run.status))}
            </option>
          ))}
        </select>
      </label>
      <div className="twoCol compact noTopMargin">
        <label>
          <span>限定导入任务</span>
          <select {...hydrationControlProps} name="import_job_id" defaultValue="">
            <option value="">全部导入任务</option>
            {importJobs.map((job) => <option key={stringValue(job.id)} value={stringValue(job.id)}>{shortValue(stringValue(job.id))} · {knowledgeSourceTypeLabel(stringValue(job.source_mode))}</option>)}
          </select>
        </label>
        <label>
          <span>限定来源资产</span>
          <select {...hydrationControlProps} name="source_asset_id" defaultValue="">
            <option value="">全部来源资产</option>
            {assets.map((asset) => <option key={stringValue(asset.id)} value={stringValue(asset.id)}>{stringValue(asset.filename) || stringValue(asset.title) || shortValue(stringValue(asset.id))}</option>)}
          </select>
        </label>
      </div>
      <div className="twoCol compact noTopMargin">
        <label><span>Chunk 类型</span><select {...hydrationControlProps} name="chunk_type" defaultValue=""><option value="">全部</option><option value="text">正文</option><option value="table">表格</option><option value="mixed">混合</option></select></label>
        <label><span>质量标记</span><input {...hydrationControlProps} name="quality_flag" placeholder="可选，例如 chunk_duplicate" /></label>
      </div>
      <label><span>事实类型</span><textarea {...hydrationControlProps} name="fact_kinds" defaultValue={"brand\ncompetitor\nmarket\nsource"} /></label>
      <label><span>最多候选数</span><input {...hydrationControlProps} name="max_facts" type="number" min={1} max={200} defaultValue={20} /></label>
      <div className="notice"><p>只读取 active 且已写入 BGE-M3/Qdrant 的 Chunk。输出进入候选审核，不会直接成为生成可用事实。</p></div>
      <div className="formActions"><button type="submit" disabled={pending || sourceRuns.length === 0}>{pending ? "创建中..." : "开始事实抽取"}</button></div>
      <ActionState state={state} />
    </form>
  );
}

export function KnowledgeContentGenerationForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(generateKnowledgeContentAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">GEO 文案生成</p>
      <h3>从 active 事实生成带证据的草稿</h3>
      <div className="twoCol compact noTopMargin">
        <label>
          <span>文案类型</span>
          <select {...hydrationControlProps} name="content_type" defaultValue="faq">
            <option value="faq">FAQ</option>
            <option value="product_paragraph">产品说明</option>
            <option value="category_paragraph">品类说明</option>
            <option value="competitor_comparison">竞品比较</option>
            <option value="local_guide">本地指南</option>
            <option value="citation_friendly_explanation">引用友好说明</option>
            <option value="customer_service_qa">客服问答</option>
            <option value="evidence_brief">证据补强 Brief</option>
          </select>
        </label>
        <label>
          <span>目标渠道</span>
          <select {...hydrationControlProps} name="target_platform" defaultValue="website">
            <option value="website">网站</option>
            <option value="help_center">帮助中心</option>
            <option value="product_page">产品页</option>
            <option value="editorial">编辑内容</option>
          </select>
        </label>
      </div>
      <div className="threeCol compact noTopMargin">
        <label><span>城市</span><input {...hydrationControlProps} name="target_city" placeholder="可选" /></label>
        <label><span>语气</span><select {...hydrationControlProps} name="tone" defaultValue="clear"><option value="clear">清晰客观</option><option value="professional">专业</option><option value="concise">简洁</option></select></label>
        <label><span>最少引用</span><input {...hydrationControlProps} name="required_citations" type="number" min={1} max={20} defaultValue={1} /></label>
      </div>
      <div className="twoCol compact noTopMargin">
        <label><span>目标受众</span><input {...hydrationControlProps} name="target_audience" defaultValue="正在比较产品和服务的客户" required /></label>
        <label><span>关联行动计划 ID</span><input {...hydrationControlProps} name="source_action_id" placeholder="可选；用于 Action Plan 到文案的追踪" /></label>
      </div>
      <div className="threeCol compact noTopMargin">
        <label><span>关联报告 ID</span><input {...hydrationControlProps} name="source_report_id" placeholder="可选" /></label>
        <label><span>关联复测 ID</span><input {...hydrationControlProps} name="source_retest_id" placeholder="可选" /></label>
        <label><span>信源缺口类型</span><input {...hydrationControlProps} name="source_gap_type" placeholder="可选，例如 weak_citation" /></label>
      </div>
      <label><span>禁止生成的声明</span><textarea {...hydrationControlProps} name="forbidden_claims" placeholder="每行一条；用于限制法律、价格、医疗或未经批准的声明" /></label>
      <input {...hydrationControlProps} type="hidden" name="model" value="deepseek-v4-flash" />
      <input {...hydrationControlProps} type="hidden" name="template_version" value="geo_content_draft_v1" />
      <div className="notice"><p>仅 `active` 正式事实和对应 active Chunk 可进入上下文。生成草稿默认等待人工审核，不能直接发布。</p></div>
      <div className="formActions"><button type="submit" disabled={pending}>{pending ? "创建中..." : "生成 GEO 文案"}</button></div>
      <ActionState state={state} />
    </form>
  );
}

export function PromptGenerationPanel({
  application,
  projectId
}: {
  application: Record<string, unknown>;
  projectId: string;
}) {
  const { documents, facts, jobs, promptCandidates, promptTemplates } = knowledgeApplicationData(application);
  const approvedFacts = facts.filter((fact) => stringValue(fact.status) === "active");
  const promptJobs = jobs.filter((job) => ["prompt_candidates", "all"].includes(stringValue(job.job_type)));
  return (
    <section className="detailPanel unframedPanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">Prompt 生成</p>
          <h2>用已批准知识生成提问 Prompt</h2>
        </div>
      </div>
      <p className="muted formIntro">生成链路只读取已批准知识事实，并记录 prompt_template_id、prompt_template_version 和 knowledge_source_policy。生成结果先进入候选审核，不会直接进入正式采集 Prompt。</p>
      <div className="metricGrid compact">
        <MetricCard label="可用知识事实" value={approvedFacts.length} />
        <MetricCard label="知识来源策略" value="仅已批准知识" />
        <MetricCard label="生成任务" value={promptJobs.length} />
        <MetricCard label="待审核候选" value={promptCandidates.filter((candidate) => stringValue(candidate.review_status) === "pending_review").length} />
        <MetricCard label="已批准候选" value={promptCandidates.filter((candidate) => ["approved", "edited_approved"].includes(stringValue(candidate.review_status))).length} />
      </div>
      <div className="twoCol compact">
        <KnowledgePromptGenerationForm assets={documents} projectId={projectId} templates={promptTemplates} />
        <RecordList
          title="已批准知识输入"
          emptyText="暂无已批准知识。请先到知识库质检中批准事实。"
          records={approvedFacts}
          pick={(fact) => [
            `${stringValue(fact.fact_type) || "fact"} · ${stringValue(fact.subject) || "未知主体"}`,
            `${stringValue(fact.market_code) || "GLOBAL"} · ${stringValue(fact.city) || "global"} · ${shortValue(stringValue(fact.object_value), 80)}`
          ]}
        />
      </div>
      <RecordList
        title="最近 Prompt 生成任务"
        emptyText="暂无 Prompt 生成任务。"
        records={promptJobs}
        pick={(job) => [
          `${knowledgeJobTypeLabel(stringValue(job.job_type))} · ${shortValue(stringValue(job.id))}`,
          `${statusLabel(stringValue(job.status))} · ${stringValue(job.generation_model) || "deepseek-v4-flash"} · ${stringValue(job.generation_prompt_version) || "v1"}`
        ]}
      />
    </section>
  );
}

export function PromptCandidatePanel({
  application,
  projectId
}: {
  application: Record<string, unknown>;
  projectId: string;
}) {
  const { promptCandidates } = knowledgeApplicationData(application);
  return (
    <section className="detailPanel unframedPanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">候选审核</p>
          <h2>审核并导入 Prompt 候选</h2>
        </div>
      </div>
      <div className="twoCol compact">
        <PromptCandidateReviewForm candidates={promptCandidates} projectId={projectId} />
        <PromptCandidateImportForm candidates={promptCandidates} projectId={projectId} />
      </div>
      <EvidenceRecordList
        title="Prompt 候选"
        emptyText="暂无 Prompt 候选。请先使用 Prompt 生成。"
        records={promptCandidates}
        projectId={projectId}
        pick={(candidate) => [
          stringValue(candidate.text) || shortValue(stringValue(candidate.id)),
          `${statusLabel(stringValue(candidate.review_status))} · ${stringValue(candidate.intent_type)} · ${stringValue(candidate.duplicate_state) || "unique"} · facts ${arrayValue(candidate.source_knowledge_fact_ids).length}`
        ]}
      />
    </section>
  );
}

function KnowledgePromptTemplateForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(saveKnowledgePromptTemplateAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">全局模板版本</p>
      <h3>新增或更新 Prompt 生成模板</h3>
      <div className="twoCol compact noTopMargin">
        <label><span>模板 Key</span><input {...hydrationControlProps} name="template_key" placeholder="custom_brand_questions_v1" pattern="[a-z][a-z0-9_]{2,159}" required /></label>
        <label><span>版本</span><input {...hydrationControlProps} name="template_version" defaultValue="v1" required /></label>
      </div>
      <div className="twoCol compact noTopMargin">
        <label><span>模板名称</span><input {...hydrationControlProps} name="name" required /></label>
        <label><span>生命周期</span><select {...hydrationControlProps} name="status" defaultValue="draft"><option value="draft">草稿</option><option value="published">已发布</option><option value="archived">已归档</option></select></label>
      </div>
      <label><span>用途说明</span><textarea {...hydrationControlProps} name="description" rows={3} placeholder="说明适用场景、Intent 和限制。" /></label>
      <label><span>模板正文</span><textarea {...hydrationControlProps} name="template_body" minLength={20} rows={6} required /></label>
      <label><span>System Prompt</span><textarea {...hydrationControlProps} name="system_prompt" minLength={20} rows={6} placeholder="为空时使用模板正文。" /></label>
      <label><span>User Prompt 模板</span><textarea {...hydrationControlProps} name="user_prompt_template" minLength={20} rows={6} placeholder="可引用 project、brand、competitors、approved_facts、active_chunks 等输入。" /></label>
      <label><span>输入变量</span><textarea {...hydrationControlProps} name="input_variables" defaultValue={"project\nbrand\ncompetitors\nmarket\napproved_facts\nactive_chunks\nexisting_prompts"} /></label>
      <label><span>输出 Schema（JSON 对象）</span><textarea {...hydrationControlProps} name="output_schema" rows={8} defaultValue={'{"prompt_candidates":[{"text":"string","intent_type":"string","city":"string|null","source_fact_ids":["uuid"],"source_chunk_ids":["uuid"],"rationale":"string","risk_flags":["string"]}]}'} required /></label>
      <label><span>模型配置（JSON 对象）</span><textarea {...hydrationControlProps} name="model_config" rows={4} defaultValue={'{"model":"deepseek-v4-flash","response_format":"json_object","temperature":0.2}'} required /></label>
      <label><span>评估样例（JSON 数组）</span><textarea {...hydrationControlProps} name="evaluation_set" rows={4} defaultValue="[]" /></label>
      <div className="notice"><p>发布版本不可原地改写。修改已发布版本时必须创建新版本，历史任务继续引用原模板和模型配置。</p></div>
      <div className="formActions"><button type="submit" disabled={pending}>{pending ? "保存中..." : "保存模板版本"}</button></div>
      <ActionState state={state} />
    </form>
  );
}

export function PromptTemplatePanel({ application, projectId }: { application: Record<string, unknown>; projectId: string }) {
  const { jobs, promptTemplates } = knowledgeApplicationData(application);
  return (
    <section className="detailPanel unframedPanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">生成模板</p>
          <h2>本地模板库与 Langfuse 兼容字段</h2>
        </div>
      </div>
      <p className="muted formIntro">这里管理的是“生成提问 Prompt 的提示词模板”，不是正式采集 Prompt。模板跨项目复用并按版本冻结，历史任务不会被新版本静默覆盖。</p>
      <div className="twoCol compact">
        <KnowledgePromptTemplateForm projectId={projectId} />
        <div className="templateGrid">
        {effectivePromptTemplates(promptTemplates).map((template) => (
          <div className="templateCard" key={stringValue(template.id)}>
            <div className="sectionTitle compactTitle">
              <div>
                <p className="eyebrow">{stringValue(template.template_key) || stringValue(template.id)}</p>
                <h3>{stringValue(template.name)}</h3>
              </div>
              <span className="statusPill">{stringValue(template.template_version) || stringValue(template.version)}</span>
            </div>
            <p>{stringValue(template.description) || shortValue(stringValue(template.template_body), 180)}</p>
            <SummaryGrid rows={[
              ["状态", statusLabel(stringValue(template.status) || "draft")],
              ["创建者", stringValue(template.created_by) || "system"],
              ["知识策略", "仅 active 正式事实 + embedded Chunk"],
              ["输出结构", Object.keys(objectValue(template.output_schema)).length ? "已定义 JSON Schema" : "未定义"]
            ]} />
            <details className="historyPanel">
              <summary>查看模板规则</summary>
              <pre>{stringValue(template.system_prompt) || stringValue(template.template_body)}</pre>
            </details>
          </div>
        ))}
        {!effectivePromptTemplates(promptTemplates).length ? (
          <div className="notice"><p>数据库中没有 Prompt 生成模板。请创建并发布第一个模板版本；系统不会用前端假数据替代。</p></div>
        ) : null}
        </div>
      </div>
      <RecordList
        title="模板使用记录"
        emptyText="暂无模板使用记录。"
        records={jobs}
        pick={(job) => {
          const requestPayload = objectValue(job.request_payload);
          return [
            `${stringValue(requestPayload.prompt_template_id) || stringValue(job.generation_prompt_version) || "template"} · ${shortValue(stringValue(job.id))}`,
            `${statusLabel(stringValue(job.status))} · ${stringValue(requestPayload.knowledge_source_policy) || "approved_only"}`
          ];
        }}
      />
    </section>
  );
}

export function PromptImportHistoryPanel({
  application,
  projectId
}: {
  application: Record<string, unknown>;
  projectId: string;
}) {
  const { jobs, promptCandidates } = knowledgeApplicationData(application);
  const importedCandidates = promptCandidates.filter((candidate) => stringValue(candidate.review_status) === "imported" || stringValue(candidate.imported_prompt_id));
  return (
    <section className="detailPanel unframedPanel">
      <div className="sectionTitle">
        <div>
          <p className="eyebrow">导入记录</p>
          <h2>CSV 与候选导入追踪</h2>
        </div>
      </div>
      <div className="twoCol compact">
        <RecordList
          title="候选导入记录"
          emptyText="暂无候选导入记录。"
          records={importedCandidates}
          pick={(candidate) => [
            stringValue(candidate.text) || shortValue(stringValue(candidate.id)),
            `Prompt ${shortValue(stringValue(candidate.imported_prompt_id)) || "未写入"} · ${stringValue(candidate.generation_prompt_version) || "无模板版本"}`
          ]}
        />
        <RecordList
          title="生成任务记录"
          emptyText="暂无生成任务记录。"
          records={jobs}
          pick={(job) => [
            `${knowledgeJobTypeLabel(stringValue(job.job_type))} · ${shortValue(stringValue(job.id))}`,
            `${statusLabel(stringValue(job.status))} · ${stringValue(job.created_at) || "无创建时间"}`
          ]}
        />
      </div>
      <p className="muted formIntro">手工 CSV 导入记录目前通过审计事件和项目 Prompt 数量追踪；候选导入会在 Prompt 候选中保留 imported_prompt_id。</p>
    </section>
  );
}

function KnowledgeFactReviewForm({ facts, projectId }: { facts: RuntimeListRecord[]; projectId: string }) {
  const [state, formAction, pending] = useActionState(reviewKnowledgeFactAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">事实审核</p>
      <h3>批准或拒绝知识事实</h3>
      <label>
        <span>知识事实</span>
        <select {...hydrationControlProps} name="knowledge_fact_id" defaultValue={stringValue(facts[0]?.id)} required>
          {facts.map((fact, index) => (
            <option value={stringValue(fact.id)} key={`${index}-${stringValue(fact.id)}`}>
              {shortValue(stringValue(fact.id))} · {stringValue(fact.fact_type)} · {shortValue(stringValue(fact.object_value), 40)}
            </option>
          ))}
          {!facts.length ? <option value="">暂无知识事实</option> : null}
        </select>
      </label>
      <label>
        <span>审核状态</span>
        <select {...hydrationControlProps} name="review_status" defaultValue="approved">
          <option value="approved">批准</option>
          <option value="rejected">拒绝</option>
          <option value="pending_review">退回复核</option>
          <option value="archived">归档</option>
        </select>
      </label>
      <label><span>决策说明</span><input {...hydrationControlProps} name="decision" defaultValue="knowledge fact approved for generation" /></label>
      <label><span>备注</span><textarea {...hydrationControlProps} name="notes" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !facts.length}>{pending ? "保存中..." : "保存事实审核"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function KnowledgeFactCandidateReviewForm({ candidates, projectId }: { candidates: RuntimeListRecord[]; projectId: string }) {
  const [state, formAction, pending] = useActionState(reviewKnowledgeFactCandidateAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">候选事实审核</p>
      <h3>批准 Pipeline 抽取事实</h3>
      <label>
        <span>候选事实</span>
        <select {...hydrationControlProps} name="fact_candidate_id" defaultValue={stringValue(candidates[0]?.id)} required>
          {candidates.map((fact, index) => (
            <option value={stringValue(fact.id)} key={`${index}-${stringValue(fact.id)}`}>
              {shortValue(stringValue(fact.id))} · {stringValue(fact.fact_type)} · {shortValue(stringValue(fact.object_value), 40)}
            </option>
          ))}
          {!candidates.length ? <option value="">暂无候选事实</option> : null}
        </select>
      </label>
      <label>
        <span>审核状态</span>
        <select {...hydrationControlProps} name="review_status" defaultValue="approved">
          <option value="approved">批准并写入正式事实</option>
          <option value="rejected">拒绝</option>
          <option value="needs_reextract">要求重新抽取</option>
          <option value="merged">合并到已有正式事实</option>
          <option value="superseded">标记为已替代</option>
          <option value="forbidden">禁止使用</option>
          <option value="archived">归档</option>
        </select>
      </label>
      <label><span>合并目标事实 ID</span><input {...hydrationControlProps} name="merged_into_fact_id" placeholder="仅选择“合并”时必填" /></label>
      <label><span>决策说明</span><input {...hydrationControlProps} name="decision" defaultValue="fact candidate approved for generation" /></label>
      <label><span>备注</span><textarea {...hydrationControlProps} name="notes" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !candidates.length}>{pending ? "保存中..." : "保存候选审核"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function KnowledgePromptGenerationForm({
  assets,
  projectId,
  templates
}: {
  assets: RuntimeListRecord[];
  projectId: string;
  templates: RuntimeListRecord[];
}) {
  const [state, formAction, pending] = useActionState(createKnowledgePromptGenerationAction, initialState);
  const publishedTemplates = effectivePromptTemplates(templates).filter((template) => stringValue(template.status) === "published");
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">生成</p>
      <h3>生成提问 Prompt 候选</h3>
      <div className="twoCol compact noTopMargin">
        <label>
          <span>生成模板</span>
          <select {...hydrationControlProps} name="prompt_template_id" defaultValue="" required>
            <option value="" disabled>选择已发布模板版本</option>
            {publishedTemplates.map((template) => (
              <option
                value={`${stringValue(template.template_key)}::${stringValue(template.template_version) || "v1"}`}
                key={`${stringValue(template.template_key)}-${stringValue(template.template_version)}`}
              >
                {stringValue(template.name)} · {stringValue(template.template_version) || "v1"}
              </option>
            ))}
          </select>
        </label>
        <div className="notice"><p>只允许选择已发布的不可变模板版本；没有已发布模板时请先到“生成模板”发布一个版本。</p></div>
      </div>
      <div className="twoCol compact noTopMargin">
        <label>
          <span>目标平台</span>
          <select {...hydrationControlProps} name="target_platform" defaultValue="chatgpt">
            <option value="chatgpt">ChatGPT</option>
            <option value="perplexity">Perplexity</option>
            <option value="google_ai_mode">Google AI Mode</option>
            <option value="platform_neutral">平台中立</option>
          </select>
        </label>
        <label>
          <span>生成数量</span>
          <input {...hydrationControlProps} name="quantity" type="number" min={1} max={50} defaultValue={10} />
        </label>
      </div>
      <div className="twoCol compact noTopMargin">
        <label>
          <span>Intent</span>
          <select {...hydrationControlProps} name="intent_type" defaultValue="brand_visibility">
            <option value="brand_visibility">品牌可见性</option>
            <option value="competitor_comparison">竞品比较</option>
            <option value="purchase_decision">购买决策</option>
            <option value="local_city">本地城市</option>
            <option value="citation_gap">信源缺口</option>
          </select>
        </label>
        <label><span>城市</span><input {...hydrationControlProps} name="city" placeholder="可选，例如 Shanghai" /></label>
      </div>
      <details className="historyPanel">
        <summary>限定生成使用的知识范围</summary>
        <div className="twoCol compact">
          <label><span>事实类型</span><select {...hydrationControlProps} name="source_fact_kind" defaultValue=""><option value="">全部正式事实</option><option value="brand">品牌事实</option><option value="competitor">竞品事实</option><option value="market">市场事实</option><option value="source">信源事实</option></select></label>
          <label><span>竞品主体</span><input {...hydrationControlProps} name="competitor" placeholder="可选；按事实主体匹配" /></label>
          <label><span>事实市场</span><input {...hydrationControlProps} name="source_market_code" placeholder="可选，例如 AU" /></label>
          <label><span>事实城市</span><input {...hydrationControlProps} name="source_city" placeholder="可选" /></label>
          <label><span>来源资产</span><select {...hydrationControlProps} name="source_asset_id" defaultValue=""><option value="">全部来源资产</option>{assets.map((asset) => <option key={stringValue(asset.id)} value={stringValue(asset.id)}>{stringValue(asset.filename) || stringValue(asset.title) || shortValue(stringValue(asset.id))}</option>)}</select></label>
          <label><span>Chunk 类型</span><select {...hydrationControlProps} name="source_chunk_type" defaultValue=""><option value="">全部类型</option><option value="text">正文</option><option value="table">表格</option><option value="mixed">混合</option></select></label>
          <label><span>Chunk 质量标记</span><input {...hydrationControlProps} name="source_quality_flag" placeholder="可选" /></label>
          <label><span>Chunk 包含文本</span><input {...hydrationControlProps} name="source_chunk_query" placeholder="可选" /></label>
        </div>
      </details>
      <input {...hydrationControlProps} type="hidden" name="model" value="deepseek-v4-flash" />
      <div className="notice">
        <p>模型固定为 DeepSeek v4 Flash。输出包含 Prompt、Intent、城市、事实与 Chunk 证据引用；候选必须审核后才能导入正式 Prompt。</p>
      </div>
      <div className="formActions">
        <button type="submit" disabled={pending || publishedTemplates.length === 0}>{pending ? "生成中..." : "生成 Prompt 候选"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function PromptCandidateReviewForm({ candidates, projectId }: { candidates: RuntimeListRecord[]; projectId: string }) {
  const [state, formAction, pending] = useActionState(reviewPromptCandidateAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">Prompt 审核</p>
      <h3>审核候选 Prompt</h3>
      <label>
        <span>候选</span>
        <select {...hydrationControlProps} name="prompt_candidate_id" defaultValue={stringValue(candidates[0]?.id)} required>
          {candidates.map((candidate, index) => (
            <option value={stringValue(candidate.id)} key={`${index}-${stringValue(candidate.id)}`}>
              {shortValue(stringValue(candidate.id))} · {shortValue(stringValue(candidate.text), 60)}
            </option>
          ))}
          {!candidates.length ? <option value="">暂无候选</option> : null}
        </select>
      </label>
      <label><span>编辑后的 Prompt</span><textarea {...hydrationControlProps} name="edited_text" minLength={3} placeholder="仅选择“编辑后批准”时必填；其他状态留空。" /></label>
      <label>
        <span>状态</span>
        <select {...hydrationControlProps} name="review_status" defaultValue="approved">
          <option value="approved">批准</option>
          <option value="edited_approved">编辑后批准</option>
          <option value="rejected">拒绝</option>
          <option value="pending_review">退回复核</option>
          <option value="archived">归档</option>
          <option value="superseded">标记为已替代</option>
        </select>
      </label>
      <label><span>决策说明</span><input {...hydrationControlProps} name="decision" defaultValue="prompt candidate approved" /></label>
      <label><span>备注</span><textarea {...hydrationControlProps} name="notes" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !candidates.length}>{pending ? "保存中..." : "保存 Prompt 审核"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function PromptCandidateImportForm({ candidates, projectId }: { candidates: RuntimeListRecord[]; projectId: string }) {
  const [state, formAction, pending] = useActionState(importApprovedPromptCandidatesAction, initialState);
  const approvedIds = candidates
    .filter((candidate) => ["approved", "edited_approved"].includes(stringValue(candidate.review_status)))
    .map((candidate) => stringValue(candidate.id))
    .filter(Boolean)
    .join("\n");
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">导入</p>
      <h3>导入已批准 Prompt</h3>
      <label><span>候选 ID</span><textarea {...hydrationControlProps} name="prompt_candidate_ids" defaultValue={approvedIds} placeholder="留空则导入全部 approved 候选" /></label>
      <label><span>Prompt version</span><input {...hydrationControlProps} name="prompt_version" placeholder="留空自动生成" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "导入中..." : "导入 Prompt"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function ManualBackfillPanel({ projectId, prompts, evidenceRuns }: { projectId: string; prompts: PageResponse<PromptRecord>; evidenceRuns: PageResponse }) {
  return (
    <div className="opsWorkbench">
      <div className="twoCol compact">
        <ManualBackfillCsvForm projectId={projectId} />
        <ManualBackfillSingleForm prompts={prompts.records} />
      </div>
      <RecordList
        title="最近证据运行"
        emptyText="暂无证据运行。"
        records={evidenceRuns.records}
        pick={(record) => {
          const answer = objectValue(record.answer_run);
          const raw = objectValue(record.raw_answer);
          return [
            stringValue(answer.platform) || stringValue(raw.platform) || "evidence",
            `${statusLabel(stringValue(answer.status))} · ${stringValue(answer.prompt_text) || shortValue(stringValue(answer.id))}`
          ];
        }}
      />
    </div>
  );
}

function ManualBackfillCsvForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(importManualBackfillAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">Google manual backfill</p>
      <h3>批量导入 CSV</h3>
      <label><span>最大行数</span><input {...hydrationControlProps} name="max_rows" type="number" min={1} max={500} defaultValue={120} /></label>
      <label><span>备注</span><input {...hydrationControlProps} name="notes" defaultValue="admin-web-google-manual-backfill" /></label>
      <label>
        <span>CSV 内容</span>
        <textarea
          {...hydrationControlProps}
          name="csv_content"
          placeholder={"prompt_question_id,platform,surface,answer_text,citation_urls,screenshot_url,html_snapshot_url,answer_present,surface_triggered,sample_index,sample_size,device,notes\n00000000-0000-0000-0000-000000000000,google,google_ai_mode,\"Answer text\",\"https://example.com\",s3://bucket/s.png,s3://bucket/page.html,true,true,1,1,desktop,manual proof"}
          required
        />
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "导入中..." : "导入 Google CSV"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function ManualBackfillSingleForm({ prompts }: { prompts: PromptRecord[] }) {
  const [state, formAction, pending] = useActionState(submitManualBackfillAction, initialState);
  const firstPromptId = prompts[0]?.id || "";
  return (
    <form className="configForm singleColumn" action={formAction}>
      <p className="eyebrow">单条补录</p>
      <h3>写入一条回答证据</h3>
      <label>
        <span>Prompt ID</span>
        <select {...hydrationControlProps} name="prompt_question_id" defaultValue={firstPromptId} required>
          {prompts.map((prompt, index) => (
            <option value={prompt.id || ""} key={`${index}-${prompt.id || prompt.text}`}>{shortValue(prompt.id || "")} · {prompt.text || "Prompt"}</option>
          ))}
          {!prompts.length ? <option value="">暂无 Prompt</option> : null}
        </select>
      </label>
      <input {...hydrationControlProps} type="hidden" name="platform" value="google" />
      <input {...hydrationControlProps} type="hidden" name="surface" value="google_ai_mode" />
      <label><span>回答文本</span><textarea {...hydrationControlProps} name="answer_text" required /></label>
      <label><span>Citation URLs</span><textarea {...hydrationControlProps} name="citation_urls" placeholder="每行一个 URL" /></label>
      <label><span>截图 URL</span><input {...hydrationControlProps} name="screenshot_url" placeholder="s3://..." /></label>
      <label><span>HTML snapshot URL</span><input {...hydrationControlProps} name="html_snapshot_url" placeholder="s3://..." /></label>
      <div className="twoCol compact noTopMargin">
        <label><span>样本序号</span><input {...hydrationControlProps} name="sample_index" type="number" min={1} defaultValue={1} /></label>
        <label><span>样本总数</span><input {...hydrationControlProps} name="sample_size" type="number" min={1} defaultValue={1} /></label>
      </div>
      <label><span>设备</span><input {...hydrationControlProps} name="device" defaultValue="desktop" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !prompts.length}>{pending ? "提交中..." : "提交单条补录"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function HumanReviewPanel({ projectId, queue, reviews }: { projectId: string; queue: PageResponse; reviews: PageResponse }) {
  return (
    <div className="opsWorkbench">
      <div className="twoCol compact">
        <HumanReviewForm projectId={projectId} queue={queue.records} />
        <RecordList
          title="最近复核记录"
          emptyText="暂无人工复核。"
          records={reviews.records}
          pick={(record) => {
            const review = objectValue(record.human_review || record);
            return [
              `${stringValue(review.target_type) || "target"} · ${shortValue(stringValue(review.target_id))}`,
              `${statusLabel(stringValue(review.review_status))} · ${stringValue(review.decision) || "无决策"}`
            ];
          }}
        />
      </div>
      <RecordList
        title="复核队列"
        emptyText="当前没有待复核对象。"
        records={queue.records}
        pick={(record) => {
          const item = objectValue(record.queue_item || record);
          return [
            `${stringValue(item.target_type) || "target"} · ${shortValue(stringValue(item.target_id))}`,
            `${statusLabel(stringValue(item.queue_status || item.review_status))} · ${stringValue(item.reason) || stringValue(item.created_at)}`
          ];
        }}
      />
    </div>
  );
}

function HumanReviewForm({ projectId, queue }: { projectId: string; queue: RuntimeListRecord[] }) {
  const [state, formAction, pending] = useActionState(recordHumanReviewAction, initialState);
  const first = objectValue(queue[0]?.queue_item || queue[0] || {});
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">人工复核</p>
      <h3>记录审核决策</h3>
      <label><span>目标类型</span><input {...hydrationControlProps} name="target_type" defaultValue={stringValue(first.target_type) || "answer_analysis" } required /></label>
      <label><span>目标 ID</span><input {...hydrationControlProps} name="target_id" defaultValue={stringValue(first.target_id)} required /></label>
      <label>
        <span>复核状态</span>
        <select {...hydrationControlProps} name="review_status" defaultValue="approved">
          <option value="approved">已通过</option>
          <option value="needs_changes">需要修改</option>
          <option value="rejected">已拒绝</option>
        </select>
      </label>
      <label><span>决策</span><input {...hydrationControlProps} name="decision" placeholder="approve parser output / override recommendation" required /></label>
      <label><span>修正内容</span><textarea {...hydrationControlProps} name="correction" placeholder="结构化修正或说明" /></label>
      <label><span>备注</span><textarea {...hydrationControlProps} name="notes" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存复核"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function ReportCenterPanel({ projectId, reports, jobs }: { projectId: string; reports: PageResponse; jobs: PageResponse }) {
  return (
    <div className="opsWorkbench">
      <div className="twoCol compact">
        <ReportManagementForm projectId={projectId} reports={reports.records} />
        <ReportJobForm projectId={projectId} reports={reports.records} />
      </div>
      <div className="twoCol compact">
        <RecordList
          title="报告"
          emptyText="暂无报告。"
          records={reports.records}
          pick={(record) => {
            const report = objectValue(record.report_export || record);
            return [
              stringValue(report.report_version) || shortValue(stringValue(report.id)),
              `${stringValue(report.report_type) || "runtime"} · ${statusLabel(stringValue(report.management_status || report.status))} · ${stringValue(report.exported_at)}`
            ];
          }}
        />
        <RecordList
          title="报告任务"
          emptyText="暂无报告任务。"
          records={jobs.records}
          pick={(record) => {
            const job = objectValue(record.report_export_job || record);
            return [
              shortValue(stringValue(job.id)) || "job",
              `${statusLabel(stringValue(job.status))} · ${stringValue(job.artifact_type) || "artifact"} · ${stringValue(job.created_at)}`
            ];
          }}
        />
      </div>
      <ReportJobStatusForm projectId={projectId} jobs={jobs.records} />
    </div>
  );
}

function ReportManagementForm({ projectId, reports }: { projectId: string; reports: RuntimeListRecord[] }) {
  const [state, formAction, pending] = useActionState(updateReportManagementAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">报告生命周期</p>
      <h3>审批、发布、撤回</h3>
      <ReportSelect reports={reports} />
      <label>
        <span>状态</span>
        <select {...hydrationControlProps} name="status" defaultValue="published">
          <option value="approved">已审批</option>
          <option value="published">已发布</option>
          <option value="revoked">已撤回</option>
          <option value="internal_review">内部复核</option>
          <option value="client_ready">客户可见</option>
          <option value="archived">已归档</option>
        </select>
      </label>
      <label><span>备注</span><textarea {...hydrationControlProps} name="note" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !reports.length}>{pending ? "更新中..." : "更新报告状态"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function ReportJobForm({ projectId, reports }: { projectId: string; reports: RuntimeListRecord[] }) {
  const [state, formAction, pending] = useActionState(enqueueReportJobAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">报告任务</p>
      <h3>创建导出任务</h3>
      <ReportSelect reports={reports} optional />
      <label>
        <span>Artifact</span>
        <select {...hydrationControlProps} name="artifact_type" defaultValue="pdf">
          <option value="pdf">PDF</option>
          <option value="markdown">Markdown</option>
          <option value="csv">CSV</option>
        </select>
      </label>
      <label><span>模板</span><input {...hydrationControlProps} name="template" defaultValue="standard" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "创建中..." : "创建报告任务"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function ReportJobStatusForm({ projectId, jobs }: { projectId: string; jobs: RuntimeListRecord[] }) {
  const [state, formAction, pending] = useActionState(updateReportJobStatusAction, initialState);
  return (
    <form className="configForm" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow wideField">任务状态回填</p>
      <label>
        <span>任务 ID</span>
        <select {...hydrationControlProps} name="job_id" defaultValue={stringValue(objectValue(jobs[0]?.report_export_job || jobs[0] || {}).id)} required>
          {jobs.map((record, index) => {
            const job = objectValue(record.report_export_job || record);
            return <option value={stringValue(job.id)} key={`${index}-${stringValue(job.id)}`}>{shortValue(stringValue(job.id))} · {statusLabel(stringValue(job.status))}</option>;
          })}
          {!jobs.length ? <option value="">暂无任务</option> : null}
        </select>
      </label>
      <label>
        <span>状态</span>
        <select {...hydrationControlProps} name="status" defaultValue="succeeded">
          <option value="queued">已排队</option>
          <option value="running">运行中</option>
          <option value="succeeded">已完成</option>
          <option value="failed">失败</option>
          <option value="cancelled">已取消</option>
        </select>
      </label>
      <label><span>报告 ID</span><input {...hydrationControlProps} name="report_export_id" /></label>
      <label><span>Artifact URL</span><input {...hydrationControlProps} name="artifact_url" /></label>
      <label className="wideField"><span>错误信息</span><textarea {...hydrationControlProps} name="error_message" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !jobs.length}>{pending ? "更新中..." : "更新任务状态"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function ReportSelect({ reports, optional }: { reports: RuntimeListRecord[]; optional?: boolean }) {
  return (
    <label>
      <span>报告</span>
      <select {...hydrationControlProps} name="report_export_id" required={!optional} defaultValue={stringValue(objectValue(reports[0]?.report_export || reports[0] || {}).id)}>
        {optional ? <option value="">不绑定已有报告</option> : null}
        {reports.map((record, index) => {
          const report = objectValue(record.report_export || record);
          const reportId = stringValue(report.id);
          return <option value={reportId} key={`${index}-${reportId}`}>{shortValue(reportId)} · {stringValue(report.report_version) || stringValue(report.report_type)}</option>;
        })}
        {!reports.length && !optional ? <option value="">暂无报告</option> : null}
      </select>
    </label>
  );
}

export function ActionPlanPanel({ projectId, actions }: { projectId: string; actions: PageResponse }) {
  const actionRows = actions.records.flatMap((record) => {
    const recommendations = Array.isArray(record.action_recommendations) ? record.action_recommendations : [];
    return recommendations.map((item) => objectValue(item));
  });
  const retestRows = actions.records.map((record) => objectValue(record.retest_schedule || {}));
  const comparisonRows = actions.records.flatMap((record) => Array.isArray(record.retest_comparisons) ? record.retest_comparisons.map((item) => objectValue(item)) : []);
  return (
    <div className="opsWorkbench">
      <div className="twoCol compact">
        <ActionRecommendationForm projectId={projectId} actions={actionRows} />
        <RecordList
          title="复测计划"
          emptyText="暂无复测计划。"
          records={retestRows}
          pick={(schedule) => [
            shortValue(stringValue(schedule.id)) || "retest",
            `${stringValue(schedule.prompt_version) || "prompt"} · ${stringValue(schedule.sample_size) || "0"} samples · ${stringValue(schedule.created_at)}`
          ]}
        />
      </div>
      <RecordList
        title="行动建议"
        emptyText="暂无行动建议。"
        records={actionRows}
        pick={(action) => [
          stringValue(action.title) || shortValue(stringValue(action.id)),
          `${statusLabel(stringValue(action.status))} · owner ${stringValue(action.owner_id) || "未分配"} · 客户可见 ${String(Boolean(action.customer_visible))}`
        ]}
      />
      <RecordList
        title="复测对比"
        emptyText="暂无复测对比。"
        records={comparisonRows}
        pick={(comparison) => [
          shortValue(stringValue(comparison.id)) || "comparison",
          `before ${stringValue(comparison.baseline_score)} · after ${stringValue(comparison.retest_score)} · delta ${stringValue(comparison.score_delta)}`
        ]}
      />
    </div>
  );
}

function ActionRecommendationForm({ projectId, actions }: { projectId: string; actions: RuntimeListRecord[] }) {
  const [state, formAction, pending] = useActionState(updateActionRecommendationAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">行动计划</p>
      <h3>更新 owner、状态和客户可见性</h3>
      <label>
        <span>Action</span>
        <select {...hydrationControlProps} name="action_id" defaultValue={stringValue(actions[0]?.id)} required>
          {actions.map((action, index) => (
            <option value={stringValue(action.id)} key={`${index}-${stringValue(action.id)}`}>{shortValue(stringValue(action.id))} · {stringValue(action.title)}</option>
          ))}
          {!actions.length ? <option value="">暂无行动建议</option> : null}
        </select>
      </label>
      <label><span>Owner</span><input {...hydrationControlProps} name="owner_id" placeholder="analyst@example.com" /></label>
      <label>
        <span>状态</span>
        <select {...hydrationControlProps} name="status" defaultValue="in_progress">
          <option value="open">待处理</option>
          <option value="in_progress">进行中</option>
          <option value="done">已完成</option>
          <option value="blocked">阻塞</option>
          <option value="dismissed">已忽略</option>
        </select>
      </label>
      <label>
        <span>客户可见</span>
        <select {...hydrationControlProps} name="customer_visible" defaultValue="0">
          <option value="0">内部可见</option>
          <option value="1">客户可见</option>
        </select>
      </label>
      <label><span>客户说明</span><textarea {...hydrationControlProps} name="visibility_note" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !actions.length}>{pending ? "更新中..." : "更新行动计划"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function ContentWorkbenchPanel({
  content,
  contentDrafts,
  contentGenerationJobs,
  projectId
}: {
  content: PageResponse;
  contentDrafts: RuntimeListRecord[];
  contentGenerationJobs: RuntimeListRecord[];
  projectId: string;
}) {
  const engines = content.records;
  const drafts = contentDrafts.map((item) => objectValue(objectValue(item).draft || item));
  const distributions = engines.flatMap((record) => Array.isArray(record.manual_distribution_records) ? record.manual_distribution_records.map((item) => objectValue(item)) : []);
  return (
    <div className="opsWorkbench">
      <div className="twoCol compact">
        <KnowledgeContentGenerationForm projectId={projectId} />
        <ContentDraftReviewForm drafts={drafts} projectId={projectId} />
      </div>
      <div className="twoCol compact">
        <ManualDistributionBackfillForm distributions={distributions} projectId={projectId} />
        <RecordList
          title="GEO 文案生成任务"
          emptyText="暂无生成任务。"
          records={contentGenerationJobs}
          pick={(job) => [
            `${stringValue(job.content_type) || "content"} · ${shortValue(stringValue(job.id))}`,
            `${statusLabel(stringValue(job.status))} · ${stringValue(job.model) || "deepseek-v4-flash"} · generated ${stringValue(job.generated_count) || "0"}`
          ]}
        />
      </div>
      <div className="twoCol compact">
        <EvidenceRecordList
          title="内容草稿"
          emptyText="暂无内容草稿。"
          records={drafts}
          projectId={projectId}
          pick={(draft) => [
            stringValue(draft.title) || shortValue(stringValue(draft.id)),
            `${statusLabel(stringValue(draft.status) || stringValue(draft.review_status))} · ${stringValue(draft.content_type)} · ${stringValue(draft.target_platform)}`
          ]}
        />
        <RecordList
          title="Distribution 回填"
          emptyText="暂无分发任务。"
          records={distributions}
          pick={(record) => [
            `${stringValue(record.platform) || "manual"} · ${shortValue(stringValue(record.id))}`,
            `${statusLabel(stringValue(record.status))} · ${stringValue(record.target_url) || "等待 URL 回填"}`
          ]}
        />
      </div>
      <div className="detailPanel">
        <p className="eyebrow">已批准文案导出</p>
        <h3>Markdown 交付</h3>
        <div className="recordList">
          {drafts.filter((draft) => ["approved", "exported", "published"].includes(stringValue(draft.status))).map((draft) => (
            <div className="recordRow" key={`export-${stringValue(draft.id)}`}>
              <div>
                <strong>{stringValue(draft.title) || shortValue(stringValue(draft.id))}</strong>
                <p className="muted">{statusLabel(stringValue(draft.status))} · 证据引用 {arrayValue(draft.citation_refs).length}</p>
              </div>
              <a
                className="button secondary"
                href={`/api/knowledge/content-draft?project_id=${encodeURIComponent(projectId)}&content_draft_id=${encodeURIComponent(stringValue(draft.id))}`}
              >
                导出 Markdown
              </a>
            </div>
          ))}
          {!drafts.some((draft) => ["approved", "exported", "published"].includes(stringValue(draft.status))) ? (
            <p className="muted">暂无可导出的已批准文案。</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ContentDraftReviewForm({ drafts, projectId }: { drafts: RuntimeListRecord[]; projectId: string }) {
  const [state, formAction, pending] = useActionState(reviewContentDraftAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">内容审核</p>
      <h3>更新草稿审核状态</h3>
      <label>
        <span>内容草稿</span>
        <select {...hydrationControlProps} name="content_draft_id" defaultValue={stringValue(drafts[0]?.id)} required>
          {drafts.map((draft, index) => (
            <option value={stringValue(draft.id)} key={`${index}-${stringValue(draft.id)}`}>
              {shortValue(stringValue(draft.id))} · {stringValue(draft.title) || "未命名草稿"}
            </option>
          ))}
          {!drafts.length ? <option value="">暂无内容草稿</option> : null}
        </select>
      </label>
      <label>
        <span>审核状态</span>
        <select {...hydrationControlProps} name="review_status" defaultValue="approved">
          <option value="approved">已通过</option>
          <option value="needs_revision">需要修改</option>
          <option value="rejected">已拒绝</option>
          <option value="pending_human_review">退回复核</option>
          <option value="archived">归档</option>
        </select>
      </label>
      <label><span>决策说明</span><input {...hydrationControlProps} name="decision" defaultValue="content draft approved for distribution" /></label>
      <label><span>备注</span><textarea {...hydrationControlProps} name="notes" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !drafts.length}>{pending ? "保存中..." : "保存内容审核"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function ManualDistributionBackfillForm({ distributions, projectId }: { distributions: RuntimeListRecord[]; projectId: string }) {
  const [state, formAction, pending] = useActionState(backfillManualDistributionAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">Distribution 回填</p>
      <h3>回填 URL / proof</h3>
      <label>
        <span>Distribution</span>
        <select {...hydrationControlProps} name="distribution_record_id" defaultValue={stringValue(distributions[0]?.id)} required>
          {distributions.map((record, index) => (
            <option value={stringValue(record.id)} key={`${index}-${stringValue(record.id)}`}>
              {shortValue(stringValue(record.id))} · {statusLabel(stringValue(record.status))}
            </option>
          ))}
          {!distributions.length ? <option value="">暂无分发任务</option> : null}
        </select>
      </label>
      <label><span>目标 URL / proof</span><input {...hydrationControlProps} name="target_url" placeholder="https://..." required /></label>
      <label>
        <span>状态</span>
        <select {...hydrationControlProps} name="status" defaultValue="url_backfilled">
          <option value="url_backfilled">URL 已回填</option>
          <option value="verified">已验证</option>
          <option value="published">已发布</option>
          <option value="blocked">阻塞</option>
        </select>
      </label>
      <label><span>备注</span><textarea {...hydrationControlProps} name="notes" placeholder="发布证明、检查记录或阻塞原因" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending || !distributions.length}>{pending ? "回填中..." : "保存回填"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function BrandAssetsPanel({ projectId, assets, brandKit }: { projectId: string; assets: PageResponse; brandKit: Record<string, unknown> | null }) {
  return (
    <div className="opsWorkbench">
      <div className="twoCol compact">
        <BrandAssetForm projectId={projectId} />
        <div className="detailPanel">
          <p className="eyebrow">Brand Kit</p>
          <h3>{stringValue(brandKit?.client_name) || "未配置 Brand Kit"}</h3>
          <SummaryGrid rows={[
            ["Logo", stringValue(brandKit?.logo_url) || "无"],
            ["Primary", stringValue(brandKit?.primary_color) || "无"],
            ["Secondary", stringValue(brandKit?.secondary_color) || "无"],
            ["Updated", stringValue(brandKit?.updated_at) || "无"]
          ]} />
        </div>
      </div>
      <RecordList
        title="品牌资产"
        emptyText="暂无品牌资产。"
        records={assets.records}
        pick={(record) => {
          const asset = objectValue(record.brand_asset || record.asset || record);
          return [
            `${stringValue(asset.asset_type) || "asset"} · ${stringValue(asset.category) || "uncategorized"}`,
            `${statusLabel(stringValue(asset.status))} · ${stringValue(asset.asset_url) || "无 URL"}`
          ];
        }}
      />
    </div>
  );
}

function BrandAssetForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(saveBrandAssetAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">品牌资产</p>
      <h3>登记 logo / 图片 / 文档资产</h3>
      <label><span>资产 URL</span><input {...hydrationControlProps} name="asset_url" required /></label>
      <label><span>类型</span><input {...hydrationControlProps} name="asset_type" defaultValue="image" required /></label>
      <label><span>分类</span><input {...hydrationControlProps} name="category" defaultValue="brand" required /></label>
      <label><span>预览 URL</span><input {...hydrationControlProps} name="preview_url" /></label>
      <label>
        <span>状态</span>
        <select {...hydrationControlProps} name="status" defaultValue="active">
          <option value="active">运行中</option>
          <option value="pending">待扫描</option>
          <option value="archived">已归档</option>
        </select>
      </label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存品牌资产"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

export function QualityOpsPanel({ projectId, fidelityChecks, alerts, savedViews, reports }: { projectId: string; fidelityChecks: PageResponse; alerts: PageResponse; savedViews: PageResponse; reports: PageResponse }) {
  return (
    <div className="opsWorkbench">
      <div className="twoCol compact">
        <FidelityCheckForm projectId={projectId} reports={reports.records} />
        <SavedViewForm projectId={projectId} />
      </div>
      <div className="twoCol compact">
        <RecordList
          title="Fidelity Checks"
          emptyText="暂无质量检查。"
          records={fidelityChecks.records}
          pick={(record) => {
            const check = objectValue(record.fidelity_check || record);
            return [
              shortValue(stringValue(check.id)) || "check",
              `${statusLabel(stringValue(check.status))} · mismatch ${stringValue(check.mismatch_count) || "0"} · ${stringValue(check.checked_at)}`
            ];
          }}
        />
        <RecordList
          title="Runtime Alerts"
          emptyText="暂无运行告警。"
          records={alerts.records}
          pick={(record) => {
            const alert = objectValue(record.alert || record);
            return [
              stringValue(alert.title) || stringValue(alert.alert_type) || "alert",
              `${stringValue(alert.severity) || "unknown"} · ${stringValue(alert.summary) || stringValue(alert.source_id)}`
            ];
          }}
        />
      </div>
      <RecordList
        title="Saved Views"
        emptyText="暂无保存视图。"
        records={savedViews.records}
        pick={(record) => {
          const view = objectValue(record.saved_view || record);
          return [
            stringValue(view.name) || shortValue(stringValue(view.id)),
            `${stringValue(view.view_type) || "view"} · ${stringValue(view.query_path) || "无路径"}`
          ];
        }}
      />
    </div>
  );
}

function FidelityCheckForm({ projectId, reports }: { projectId: string; reports: RuntimeListRecord[] }) {
  const [state, formAction, pending] = useActionState(createFidelityCheckAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">质量检查</p>
      <h3>创建 API / Browser fidelity check</h3>
      <ReportSelect reports={reports} optional />
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "创建中..." : "创建质量检查"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function SavedViewForm({ projectId }: { projectId: string }) {
  const [state, formAction, pending] = useActionState(saveSavedViewAction, initialState);
  return (
    <form className="configForm singleColumn" action={formAction}>
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <p className="eyebrow">保存视图</p>
      <h3>保存当前工作台入口</h3>
      <label><span>名称</span><input {...hydrationControlProps} name="name" defaultValue="项目状态视图" required /></label>
      <label><span>类型</span><input {...hydrationControlProps} name="view_type" defaultValue="project_detail" required /></label>
      <label><span>目标 tab</span><input {...hydrationControlProps} name="target_tab" defaultValue="status" /></label>
      <label><span>排序</span><input {...hydrationControlProps} name="sort" defaultValue="created_at_desc" /></label>
      <div className="formActions">
        <button type="submit" disabled={pending}>{pending ? "保存中..." : "保存视图"}</button>
      </div>
      <ActionState state={state} />
    </form>
  );
}

function RecordList({
  emptyText,
  pick,
  records,
  title
}: {
  emptyText: string;
  pick: (record: RuntimeListRecord) => [string, string];
  records: RuntimeListRecord[];
  title: string;
}) {
  return (
    <div className="detailPanel">
      <p className="eyebrow">{title}</p>
      <h3>{records.length} 条</h3>
      {records.length ? (
        <div className="summaryList">
          {records.slice(0, 12).map((record, index) => {
            const [label, description] = pick(record);
            return (
              <div className="summaryListRow" key={`${index}-${label}-${description}`}>
                <div>
                  <strong>{label || "未命名"}</strong>
                  <p className="muted">{description || "无详情"}</p>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="muted emptyState">{emptyText}</p>
      )}
    </div>
  );
}

function EvidenceRecordList({
  emptyText,
  pick,
  projectId,
  records,
  title
}: {
  emptyText: string;
  pick: (record: RuntimeListRecord) => [string, string];
  projectId: string;
  records: RuntimeListRecord[];
  title: string;
}) {
  return (
    <div className="detailPanel">
      <p className="eyebrow">{title}</p>
      <h3>{records.length} 条</h3>
      {records.length ? (
        <div className="summaryList">
          {records.slice(0, 12).map((record, index) => {
            const [label, description] = pick(record);
            const chunkId = String(arrayValue(record.source_chunk_ids)[0] || "");
            return (
              <div className="summaryListRow" key={`${index}-${label}-${description}`}>
                <div>
                  <strong>{label || "未命名"}</strong>
                  <p className="muted">{description || "无详情"}</p>
                  <p className="muted">证据 Chunk：{arrayValue(record.source_chunk_ids).length} · 来源资产：{arrayValue(record.source_asset_ids).length}</p>
                </div>
                {chunkId ? (
                  <a className="button secondary" href={`/projects/${projectId}?tab=knowledge&knowledge_tab=trace&trace_chunk_id=${encodeURIComponent(chunkId)}`}>
                    查看证据链
                  </a>
                ) : <span className="statusPill dangerPill">缺少证据</span>}
              </div>
            );
          })}
        </div>
      ) : <p className="muted emptyState">{emptyText}</p>}
    </div>
  );
}

function ActionState({ state }: { state: ProjectActionState }) {
  if (state.error) {
    return <p className="muted errorText">{state.error}</p>;
  }
  if (!state.ok) {
    return null;
  }
  return (
    <div className="actionResult">
      {state.message ? <p>{state.message}</p> : null}
      {state.details?.length ? (
        <div className="summaryTable">
          {state.details.map(([label, value], index) => (
            <div key={`${index}-${label}-${value}`}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {state.rawInviteToken ? <p>raw invite token：<code>{state.rawInviteToken}</code></p> : null}
      {state.inviteUrl ? <a className="button secondary" href={state.inviteUrl}>打开客户邀请入口</a> : null}
    </div>
  );
}

function SummaryGrid({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="summaryGrid compactSummaryGrid">
      {rows.map(([label, value], index) => (
        <div className="summaryItem" key={`${index}-${label}-${value}`}>
          <span>{label}</span>
          <strong>{value || "无"}</strong>
        </div>
      ))}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="metricCard">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ScoreWeightEditor({
  baseFormulaVersion,
  formAction,
  pending,
  profile,
  projectId,
  weights
}: {
  baseFormulaVersion: string;
  formAction: (payload: FormData) => void;
  pending: boolean;
  profile: Record<string, unknown>;
  projectId: string;
  weights: unknown;
}) {
  const entries = Object.entries(objectValue(weights));
  if (!entries.length) {
    return <p className="muted emptyState">当前公式没有返回权重明细。</p>;
  }
  return (
    <div className="scoreWeightEditor">
      <input {...hydrationControlProps} type="hidden" name="project_id" value={projectId} />
      <input {...hydrationControlProps} type="hidden" name="base_formula_version" value={baseFormulaVersion} />
      <div className="twoCol compact">
        <label>
          <span>自定义方案标识</span>
          <input
            {...hydrationControlProps}
            name="profile_key"
            defaultValue={`custom_${stringValue(profile.profile_key) || "score"}`}
            required
          />
        </label>
        <label>
          <span>自定义方案名称</span>
          <input {...hydrationControlProps} name="profile_name" defaultValue={`${stringValue(profile.name) || "评分方案"} 自定义`} required />
        </label>
      </div>
      <label className="wideField">
        <span>说明</span>
        <textarea {...hydrationControlProps} name="profile_description" defaultValue={stringValue(profile.description)} />
      </label>
      <p className="muted">权重保存时会自动归一化为两位小数，并保证合计为 1.00。</p>
      <div className="scoreWeightTable editableScoreWeightTable">
        <div className="scoreWeightHeader">
          <span>评分维度</span>
          <span>权重</span>
          <span>说明</span>
        </div>
        {entries.map(([key, rawValue]) => (
          <div className="scoreWeightRow" key={key}>
            <strong>{scoreWeightLabel(key)}</strong>
            <input {...hydrationControlProps} type="number" step="0.01" min="0" name={`weight_${key}`} defaultValue={formatWeight(rawValue)} />
            <p>{scoreWeightDescription(key)}</p>
          </div>
        ))}
      </div>
      <div className="formActions">
        <button type="submit" formAction={formAction} disabled={pending}>{pending ? "保存中..." : "另存为自定义评分方案"}</button>
      </div>
    </div>
  );
}

function connectorModeOptions(provider: string): Array<{ value: string; label: string }> {
  if (provider === "google_ai_mode") {
    return [
      { value: "manual_backfill", label: "手工补录" },
      { value: "browser_or_serp", label: "浏览器 / SERP 生产路径" },
      { value: "disabled", label: "停用" }
    ];
  }
  return [
    { value: "official_api", label: "官方 API" },
    { value: "deepseek_fallback", label: "DeepSeek v4 Flash 临时代替" },
    { value: "disabled", label: "停用" }
  ];
}

function effectivePromptTemplates(templates: RuntimeListRecord[]): RuntimeListRecord[] {
  return templates;
}

function knowledgeSourceTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    csv: "CSV 文本",
    pasted_text: "粘贴文本",
    file: "上传文件",
    url_batch: "URL 批量",
    site_crawl: "站点抓取",
    url: "公网 URL",
    web_text: "网页/正文文本",
    pdf: "PDF",
    docx: "Word 文档",
    markdown: "Markdown"
  };
  return labels[value] || value || "未知来源";
}

function knowledgeJobTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    crawl: "网页抓取",
    extract_facts: "事实抽取",
    content_draft: "文案生成",
    faq_candidates: "FAQ 候选",
    prompt_candidates: "Prompt 候选",
    all: "综合生成"
  };
  return labels[value] || value || "知识任务";
}

function knowledgePipelineRunTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    full_ingestion: "完整导入",
    reparse: "重新解析",
    rechunk: "重新切分",
    reindex: "重新索引",
    fact_refresh: "刷新事实",
    prompt_generation: "生成 Prompt",
    content_generation: "生成 GEO 文案",
    full_rebuild: "完整重建"
  };
  return labels[value] || value || "Pipeline";
}

function connectorModelOptions(provider: string, mode: string): Array<{ value: string; label: string }> {
  if (mode === "disabled") {
    return [{ value: "disabled", label: "停用" }];
  }
  if (mode === "deepseek_fallback") {
    return [{ value: "deepseek-v4-flash", label: "DeepSeek v4 Flash" }];
  }
  if (provider === "perplexity") {
    return [
      { value: "sonar", label: "Perplexity Sonar" },
      { value: "sonar-pro", label: "Perplexity Sonar Pro" }
    ];
  }
  if (provider === "google_ai_mode") {
    if (mode === "browser_or_serp") {
      return [
        { value: "google_ai_mode_browser", label: "Google AI Mode Browser" },
        { value: "serp_provider", label: "SERP Provider" }
      ];
    }
    return [
      { value: "google_ai_mode_manual_backfill", label: "Google AI Mode 手工补录" }
    ];
  }
  return [
    { value: "gpt-4.1-mini", label: "OpenAI GPT-4.1 mini" },
    { value: "gpt-4o-mini", label: "OpenAI GPT-4o mini" }
  ];
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayValue(value: unknown): RuntimeListRecord[] {
  return Array.isArray(value) ? value.map((item) => objectValue(item)) : [];
}

function weightSummary(value: unknown): string {
  const weights = objectValue(value);
  const entries = Object.entries(weights);
  if (!entries.length) {
    return "未配置";
  }
  const total = entries.reduce((sum, [, weight]) => sum + (typeof weight === "number" ? weight : Number(weight) || 0), 0);
  return `${entries.length} 项 · 合计 ${total.toFixed(2)}`;
}

function scoreWeightLabel(key: string): string {
  const labels: Record<string, string> = {
    MentionScore: "品牌提及",
    RecommendationScore: "推荐强度",
    PositionScore: "答案位置",
    CitationScore: "信源可信度",
    LocalRelevanceScore: "本地相关性",
    SentimentScore: "情绪倾向",
    FreshnessScore: "信息新鲜度",
    CompetitorShareScore: "竞品份额",
    trigger_rate: "触发率",
    brand_mention_rate: "品牌提及",
    recommendation_rate: "推荐状态",
    citation_strength: "信源强度",
    competitor_relative_position: "竞品相对位置",
    competitor_delta: "竞品差距"
  };
  return labels[key] || key;
}

function scoreWeightDescription(key: string): string {
  const descriptions: Record<string, string> = {
    MentionScore: "AI 回答是否明确提到目标品牌，衡量品牌在回答中的基础可见度。",
    RecommendationScore: "AI 是否推荐目标品牌，或把目标品牌作为正向选择呈现。",
    PositionScore: "目标品牌在答案顺序、推荐列表或比较语境中的位置。",
    CitationScore: "回答引用来源的可信度、相关性和可验证性。",
    LocalRelevanceScore: "回答是否匹配目标市场、城市、语言和本地购买场景。",
    SentimentScore: "目标品牌相关描述的正负倾向。",
    FreshnessScore: "答案依据是否足够新，是否反映近期品牌和市场信息。",
    CompetitorShareScore: "目标品牌相对竞品获得的可见度和话语份额。",
    trigger_rate: "AI 是否触发可回答结果，决定样本是否进入有效分析。",
    brand_mention_rate: "答案是否明确提到目标品牌。",
    recommendation_rate: "答案是否推荐目标品牌或给出正向选择。",
    citation_strength: "回答中引用来源的数量、质量和与品牌的相关性。",
    competitor_relative_position: "目标品牌相对竞品在答案中的排序或推荐强弱。"
  };
  return descriptions[key] || "评分维度用于解释该项对 GEO 可见度总分的贡献。";
}

function formatWeight(value: unknown): string {
  const numberValue = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numberValue) ? numberValue.toFixed(2) : String(value || "0");
}

function activationBlockers(input: {
  category?: string;
  competitorCount: number;
  connectorReady: boolean;
  primaryDomain?: string;
  promptCount: number;
  targetBrand?: string;
}): string[] {
  const blockers: string[] = [];
  if (!input.targetBrand) {
    blockers.push("目标品牌未填写");
  }
  if (!input.category) {
    blockers.push("品类未填写");
  }
  if (!input.primaryDomain) {
    blockers.push("主域名未填写");
  }
  if (input.competitorCount < 1) {
    blockers.push("至少需要 1 个竞品");
  }
  if (input.promptCount < 1) {
    blockers.push("至少需要 1 条 Prompt");
  }
  if (!input.connectorReady) {
    blockers.push("至少 1 个连接器需要配置或通过测试");
  }
  return blockers;
}

function shortValue(value: string, maxLength = 14): string {
  if (!value) {
    return "";
  }
  if (value.length <= maxLength) {
    return value;
  }
  const headLength = Math.max(4, maxLength - 7);
  return `${value.slice(0, headLength)}...${value.slice(-4)}`;
}
