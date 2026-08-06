import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";

import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isMetricProtocolPage,
  isStatisticalProtocolPage,
  isWorkflowCReportPage
} from "./workflowCControlTypeGuards";
import type {
  MetricProtocolPage,
  StatisticalProtocolPage,
  WorkflowCReportPage
} from "./workflowCControlTypes";
import {
  isProjectMemberListResponse,
  type ProjectMemberListResponse
} from "../../memberTypes";
import {
  isAdmissionPolicyPage,
  isAdmissionRuntimeOptionPage,
  isAlertPage,
  isComparisonFamily,
  isComparisonFamilyPage,
  isDriftReport,
  isDriftReportPage,
  isManualEvidenceImportPage,
  isNotificationPage,
  isSamplingRunDetail,
  isSamplingRunPage,
  isSamplingSuite,
  isSamplingSuiteInputOptionPage,
  isSamplingSuitePage,
  isSemanticMetricSnapshot,
  isSemanticMetricSnapshotPage,
  isSurfaceParserReleasePage
} from "./workflowCTypeGuards";
import {
  workflowViews,
  type AdmissionPolicyPage,
  type AdmissionRuntimeOptionPage,
  type AlertPage,
  type ComparisonFamily,
  type ComparisonFamilyPage,
  type DriftReport,
  type DriftReportPage,
  type ManualEvidenceImportPage,
  type LoadProblem,
  type NotificationProjection,
  type Resource,
  type SamplingRunDetail,
  type SamplingRunPage,
  type SamplingSuite,
  type SamplingSuiteInputOptionPage,
  type SamplingSuitePage,
  type SemanticMetricSnapshot,
  type SemanticMetricSnapshotPage,
  type SurfaceParserReleasePage,
  type WorkflowCWorkspaceData,
  type WorkflowView
} from "./workflowCTypes";
import {
  loadQuestionWorkspace,
  questionSteps,
  type QuestionStep
} from "./questionWorkspaceData";

type SearchParams = { [key: string]: string | string[] | undefined };
type Selection = WorkflowCWorkspaceData["selection"];

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HASH_PATTERN = /^[0-9a-f]{64}$/;

export async function loadWorkflowCWorkspace(
  projectId: string,
  query: SearchParams
): Promise<WorkflowCWorkspaceData> {
  const rawSelection = selectionFromQuery(query);
  const selection = validSelection(rawSelection);
  const activeView = normalizeView(queryValue(query, "workflow_view"));
  const base = `/v1/projects/${encodeURIComponent(projectId)}`;

  const questionWorkspaceRequest = activeView === "questions"
    ? loadQuestionWorkspace(projectId, selection)
    : Promise.resolve(null);

  const identityRequest = runtimeRequest<AuthIdentity>("/v1/auth/me");
  const membersRequest = runtimeRequest<ProjectMemberListResponse>(`${base}/members`, {
    query: { limit: 100, offset: 0 }
  });
  const alertsRequest = runtimeRequest<AlertPage>(`${base}/alerts`);
  const admissionPoliciesRequest = runtimeRequest<AdmissionPolicyPage>(
    `${base}/sampling/admission-policies`
  );
  const admissionRuntimeOptionsRequest = runtimeRequest<AdmissionRuntimeOptionPage>(
    `${base}/sampling/admission-options`
  );
  const suiteInputOptionsRequest = runtimeRequest<SamplingSuiteInputOptionPage>(
    `${base}/sampling/suite-input-options`
  );
  const suitesRequest = runtimeRequest<SamplingSuitePage>(`${base}/sampling/suites`);
  const runsRequest = runtimeRequest<SamplingRunPage>(`${base}/sampling/runs`);
  const metricSnapshotsRequest = runtimeRequest<SemanticMetricSnapshotPage>(
    `${base}/analysis/semantic-metrics`
  );
  const metricProtocolsRequest = runtimeRequest<MetricProtocolPage>(
    `${base}/analysis/metric-protocols`
  );
  const statisticalProtocolsRequest = runtimeRequest<StatisticalProtocolPage>(
    `${base}/analysis/statistical-protocols`
  );
  const comparisonFamiliesRequest = runtimeRequest<ComparisonFamilyPage>(
    `${base}/analysis/comparisons`
  );
  const driftReportsRequest = runtimeRequest<DriftReportPage>(`${base}/analysis/drift`);
  const manualEvidenceRequest = runtimeRequest<ManualEvidenceImportPage>(
    `${base}/sampling/manual-evidence-imports`
  );
  const surfaceParserReleasesRequest = runtimeRequest<SurfaceParserReleasePage>(
    `${base}/sampling/surface-parser-releases`
  );
  const workflowCReportsRequest = runtimeRequest<WorkflowCReportPage>(
    `${base}/analysis/reports`
  );
  const suiteRequest = selection.suiteId
    ? runtimeRequest<SamplingSuite>(`${base}/sampling/suites/${encodeURIComponent(selection.suiteId)}`)
    : Promise.resolve(null);
  const runRequest = selection.runId
    ? runtimeRequest<SamplingRunDetail>(`${base}/sampling/runs/${encodeURIComponent(selection.runId)}`)
    : Promise.resolve(null);
  const metricsRequest = selection.snapshotHash
    ? runtimeRequest<SemanticMetricSnapshot>(`${base}/analysis/semantic-metrics/${selection.snapshotHash}`)
    : Promise.resolve(null);
  const comparisonRequest = selection.familyHash
    ? runtimeRequest<ComparisonFamily>(`${base}/analysis/comparisons/${selection.familyHash}`)
    : Promise.resolve(null);
  const driftRequest = selection.driftHash
    ? runtimeRequest<DriftReport>(`${base}/analysis/drift/${selection.driftHash}`)
    : Promise.resolve(null);
  const requestedNotifications = selection.alertId
    ? runtimeRequest<NotificationProjection[]>(`${base}/alerts/${encodeURIComponent(selection.alertId)}/notifications`)
    : Promise.resolve(null);

  const [
    identity,
    members,
    alerts,
    admissionPolicies,
    admissionRuntimeOptions,
    suiteInputOptions,
    suites,
    runs,
    metricSnapshots,
    metricProtocols,
    statisticalProtocols,
    comparisonFamilies,
    driftReports,
    manualEvidence,
    surfaceParserReleases,
    workflowCReports,
    suite,
    run,
    metrics,
    comparisons,
    drift,
    notificationResponse,
    questionWorkspace
  ] = await Promise.all([
    identityRequest,
    membersRequest,
    alertsRequest,
    admissionPoliciesRequest,
    admissionRuntimeOptionsRequest,
    suiteInputOptionsRequest,
    suitesRequest,
    runsRequest,
    metricSnapshotsRequest,
    metricProtocolsRequest,
    statisticalProtocolsRequest,
    comparisonFamiliesRequest,
    driftReportsRequest,
    manualEvidenceRequest,
    surfaceParserReleasesRequest,
    workflowCReportsRequest,
    suiteRequest,
    runRequest,
    metricsRequest,
    comparisonRequest,
    driftRequest,
    requestedNotifications,
    questionWorkspaceRequest
  ]);

  const identityValid = identity.ok && isAuthIdentity(identity.data);
  const membersValid = members.ok && isProjectMemberListResponse(members.data);
  const actorId = identityValid ? identity.data.actor_id : "";
  const membership = membersValid
    ? members.data.items.find(
      (item) => item.status === "active" && item.subject === actorId
    )
    : undefined;
  const alertResource = resource(alerts, isAlertPage, "Alert inbox 加载失败。");
  const selectedAlertId = selection.alertId
    || alertResource.data?.items[0]?.id;
  let notifications = notificationResponse;
  if (!notifications && selectedAlertId) {
    notifications = await runtimeRequest<NotificationProjection[]>(
      `${base}/alerts/${encodeURIComponent(selectedAlertId)}/notifications`
    );
  }
  const runResource = optionalResource(
    run,
    Boolean(rawSelection.runId),
    Boolean(selection.runId),
    isSamplingRunDetail,
    "Sampling Run 加载失败。"
  );
  const suiteResource = optionalResource(
    suite,
    Boolean(rawSelection.suiteId),
    Boolean(selection.suiteId),
    isSamplingSuite,
    "Sampling Suite 加载失败。"
  );

  return {
    actorId,
    currentIdentityId: membership?.identity_id || null,
    currentRole: membership?.role || null,
    activeView,
    selection: {
      ...selection,
      ...(questionWorkspace?.selection.campaignId
        ? { campaignId: questionWorkspace.selection.campaignId }
        : {}),
      ...(questionWorkspace?.selection.questionGenerationJobId
        ? { questionGenerationJobId: questionWorkspace.selection.questionGenerationJobId }
        : {}),
      ...(selectedAlertId ? { alertId: selectedAlertId } : {})
    },
    questionWorkspace,
    suite: runResource.data
      ? { data: runResource.data.suite }
      : suiteResource,
    run: runResource,
    metrics: optionalResource(
      metrics,
      Boolean(rawSelection.snapshotHash),
      Boolean(selection.snapshotHash),
      isSemanticMetricSnapshot,
      "Semantic Metric Snapshot 加载失败。"
    ),
    metricSnapshots: resource(
      metricSnapshots,
      isSemanticMetricSnapshotPage,
      "Semantic Metric Snapshot inventory 加载失败。"
    ),
    metricProtocols: resource(
      metricProtocols,
      isMetricProtocolPage,
      "Metric Protocol inventory 加载失败。"
    ),
    statisticalProtocols: resource(
      statisticalProtocols,
      isStatisticalProtocolPage,
      "Statistical Protocol inventory 加载失败。"
    ),
    comparisons: optionalResource(
      comparisons,
      Boolean(rawSelection.familyHash),
      Boolean(selection.familyHash),
      isComparisonFamily,
      "Comparison Family 加载失败。"
    ),
    comparisonFamilies: resource(
      comparisonFamilies,
      isComparisonFamilyPage,
      "Comparison Family inventory 加载失败。"
    ),
    drift: optionalResource(
      drift,
      Boolean(rawSelection.driftHash),
      Boolean(selection.driftHash),
      isDriftReport,
      "Drift Report 加载失败。"
    ),
    driftReports: resource(driftReports, isDriftReportPage, "Drift Report inventory 加载失败。"),
    alerts: alertResource,
    admissionPolicies: resource(
      admissionPolicies,
      isAdmissionPolicyPage,
      "Sampling Admission Policy 加载失败。"
    ),
    admissionRuntimeOptions: resource(
      admissionRuntimeOptions,
      isAdmissionRuntimeOptionPage,
      "Sampling runtime authorization options 加载失败。"
    ),
    suiteInputOptions: resource(
      suiteInputOptions,
      isSamplingSuiteInputOptionPage,
      "Sampling Suite options 加载失败。"
    ),
    suites: resource(suites, isSamplingSuitePage, "Sampling Suite inventory 加载失败。"),
    runs: resource(runs, isSamplingRunPage, "Sampling Run inventory 加载失败。"),
    manualEvidence: resource(
      manualEvidence,
      isManualEvidenceImportPage,
      "Manual evidence inventory 加载失败。"
    ),
    surfaceParserReleases: resource(
      surfaceParserReleases,
      isSurfaceParserReleasePage,
      "Consumer surface parser releases 加载失败。"
    ),
    workflowCReports: resource(
      workflowCReports,
      isWorkflowCReportPage,
      "Workflow C Report inventory 加载失败。"
    ),
    notifications: selectedAlertId
      ? resource(notifications, isNotificationPage, "通知投影加载失败。")
      : { data: [] },
    ...(!identityValid || !membersValid || !membership
      ? {
        alerts: {
          ...alertResource,
          problem: accessProblem(identity, members, membership)
        },
        admissionPolicies: {
          data: null,
          problem: accessProblem(identity, members, membership)
        },
        admissionRuntimeOptions: { data: null, problem: accessProblem(identity, members, membership) },
        suiteInputOptions: { data: null, problem: accessProblem(identity, members, membership) },
        suites: { data: null, problem: accessProblem(identity, members, membership) },
        runs: { data: null, problem: accessProblem(identity, members, membership) },
        metricSnapshots: { data: null, problem: accessProblem(identity, members, membership) },
        metricProtocols: { data: null, problem: accessProblem(identity, members, membership) },
        statisticalProtocols: { data: null, problem: accessProblem(identity, members, membership) },
        comparisonFamilies: { data: null, problem: accessProblem(identity, members, membership) },
        driftReports: { data: null, problem: accessProblem(identity, members, membership) },
        manualEvidence: { data: null, problem: accessProblem(identity, members, membership) },
        surfaceParserReleases: {
          data: null,
          problem: accessProblem(identity, members, membership)
        },
        workflowCReports: { data: null, problem: accessProblem(identity, members, membership) }
      }
      : {})
  };
}

export function workflowCHref(
  projectId: string,
  selection: Selection,
  view: WorkflowView
): string {
  const params = new URLSearchParams({ workflow_view: view });
  for (const [key, value] of Object.entries({
    suite_id: selection.suiteId,
    run_id: selection.runId,
    metric_snapshot: selection.snapshotHash,
    comparison_family: selection.familyHash,
    drift_report: selection.driftHash,
    alert_id: selection.alertId,
    policy_id: selection.policyId,
    campaign_id: selection.campaignId,
    question_generation_job_id: selection.questionGenerationJobId,
    question_step: selection.questionStep
  })) {
    if (value) params.set(key, value);
  }
  if (selection.embedded) {
    params.set("tab", "measurement");
    return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
  }
  return `/projects/${encodeURIComponent(projectId)}/workflow-c?${params.toString()}`;
}

function selectionFromQuery(query: SearchParams): Selection {
  return {
    embedded: queryValue(query, "tab") === "measurement",
    ...(queryValue(query, "suite_id") ? { suiteId: queryValue(query, "suite_id") } : {}),
    ...(queryValue(query, "run_id") ? { runId: queryValue(query, "run_id") } : {}),
    ...(queryValue(query, "metric_snapshot") ? { snapshotHash: queryValue(query, "metric_snapshot") } : {}),
    ...(queryValue(query, "comparison_family") ? { familyHash: queryValue(query, "comparison_family") } : {}),
    ...(queryValue(query, "drift_report") ? { driftHash: queryValue(query, "drift_report") } : {}),
    ...(queryValue(query, "alert_id") ? { alertId: queryValue(query, "alert_id") } : {}),
    ...(queryValue(query, "policy_id") ? { policyId: queryValue(query, "policy_id") } : {}),
    ...(queryValue(query, "campaign_id") ? { campaignId: queryValue(query, "campaign_id") } : {}),
    ...(queryValue(query, "question_generation_job_id")
      ? { questionGenerationJobId: queryValue(query, "question_generation_job_id") }
      : {}),
    ...(normalizeQuestionStep(queryValue(query, "question_step"))
      ? { questionStep: normalizeQuestionStep(queryValue(query, "question_step")) }
      : {})
  };
}

function validSelection(value: Selection): Selection {
  return {
    embedded: value.embedded,
    ...(value.suiteId && UUID_PATTERN.test(value.suiteId) ? { suiteId: value.suiteId } : {}),
    ...(value.runId && UUID_PATTERN.test(value.runId) ? { runId: value.runId } : {}),
    ...(value.snapshotHash && HASH_PATTERN.test(value.snapshotHash) ? { snapshotHash: value.snapshotHash } : {}),
    ...(value.familyHash && HASH_PATTERN.test(value.familyHash) ? { familyHash: value.familyHash } : {}),
    ...(value.driftHash && HASH_PATTERN.test(value.driftHash) ? { driftHash: value.driftHash } : {}),
    ...(value.alertId && UUID_PATTERN.test(value.alertId) ? { alertId: value.alertId } : {}),
    ...(value.policyId && UUID_PATTERN.test(value.policyId) ? { policyId: value.policyId } : {}),
    ...(value.campaignId && UUID_PATTERN.test(value.campaignId)
      ? { campaignId: value.campaignId }
      : {}),
    ...(value.questionGenerationJobId && UUID_PATTERN.test(value.questionGenerationJobId)
      ? { questionGenerationJobId: value.questionGenerationJobId }
      : {}),
    ...(value.questionStep ? { questionStep: value.questionStep } : {})
  };
}

function normalizeQuestionStep(value: string | undefined): QuestionStep | undefined {
  return questionSteps.find((step) => step === value);
}

function normalizeView(value: string | undefined): WorkflowView {
  return workflowViews.find((item) => item === value) || "overview";
}

function optionalResource<T>(
  response: RuntimeResult<T> | null,
  requested: boolean,
  validIdentity: boolean,
  guard: (value: unknown) => value is T,
  fallback: string
): Resource<T> {
  if (!requested) return { data: null };
  if (!validIdentity) return { data: null, problem: { status: 422, detail: "资源 ID 格式无效。" } };
  return resource(response, guard, fallback);
}

function resource<T>(
  response: RuntimeResult<T> | null,
  guard: (value: unknown) => value is T,
  fallback: string
): Resource<T> {
  if (!response) return { data: null };
  if (response.ok && guard(response.data)) return { data: response.data };
  if (!response.ok) return { data: null, problem: loadProblem(response, fallback) };
  return { data: null, problem: { status: 502, detail: "接口返回了无法识别的响应。" } };
}

function loadProblem(
  response: Extract<RuntimeResult<unknown>, { ok: false }>,
  fallback: string
): LoadProblem {
  return {
    ...(response.status === undefined ? {} : { status: response.status }),
    detail: response.error || fallback,
    ...(response.problem.correlation_id
      ? { correlationId: response.problem.correlation_id }
      : {})
  };
}

function accessProblem(
  identity: RuntimeResult<AuthIdentity>,
  members: RuntimeResult<ProjectMemberListResponse>,
  membership: ProjectMemberListResponse["items"][number] | undefined
): LoadProblem {
  if (!identity.ok) return loadProblem(identity, "身份验证失败。");
  if (!members.ok) return loadProblem(members, "项目成员验证失败。");
  if (!membership) return { status: 403, detail: "当前身份没有此项目的有效成员关系。" };
  return { status: 502, detail: "身份或成员接口返回了无法识别的响应。" };
}

function queryValue(params: SearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}
