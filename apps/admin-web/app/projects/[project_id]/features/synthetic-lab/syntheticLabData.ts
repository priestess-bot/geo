import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isAuthorizationPage,
  isManualImportPreview,
  isManualImportPreviewPage,
  isReviewCasePage,
  isReviewSuitePage,
  isStyleProfilePage,
  isStyleLoginSecretPage,
  isStyleSourcePage,
  isSyntheticJob,
  isSyntheticResourceInventory,
  isSyntheticRuntimeOptions,
  type CollectionAuthorization,
  type ManualImportPreview,
  type ManualImportPreviewSummary,
  type ReviewCase,
  type ReviewSuite,
  type StyleProfile,
  type StyleLoginSecretPage,
  type StyleSource,
  type SyntheticJob,
  type SyntheticLoadProblem,
  type SyntheticPage,
  type SyntheticResourceInventory,
  type SyntheticRuntimeOptions,
  type SyntheticWorkspaceData
} from "./syntheticLabTypes";

type SearchParams = { [key: string]: string | string[] | undefined };
const PAGE_SIZE = 100;

export async function loadSyntheticLabWorkspace(
  projectId: string,
  query: SearchParams
): Promise<SyntheticWorkspaceData> {
  const base = `/v1/projects/${encodeURIComponent(projectId)}/synthetic-lab`;
  const selectedSuiteId = queryValue(query, "synthetic_suite_id") || null;
  const selectedJobId = queryValue(query, "synthetic_job_id") || null;
  const selectedImportPreviewId = queryValue(query, "synthetic_import_preview_id") || null;
  const [authorizations, sources, previews, selectedPreview, inventory, runtimes, loginSecrets, profiles, suites, cases, job] = await Promise.all([
    runtimeRequest<SyntheticPage<CollectionAuthorization>>(`${base}/authorizations`, pageQuery()),
    runtimeRequest<SyntheticPage<StyleSource>>(`${base}/style-sources`, pageQuery()),
    runtimeRequest<SyntheticPage<ManualImportPreviewSummary>>(
      `${base}/sample-import-previews`, pageQuery()
    ),
    selectedImportPreviewId
      ? runtimeRequest<ManualImportPreview>(
        `${base}/sample-import-previews/${encodeURIComponent(selectedImportPreviewId)}`
      )
      : Promise.resolve(null),
    runtimeRequest<SyntheticResourceInventory>(`${base}/resource-inventory`),
    runtimeRequest<SyntheticRuntimeOptions>(
      `/v1/projects/${encodeURIComponent(projectId)}/model-gateway/options`
    ),
    runtimeRequest<StyleLoginSecretPage>(
      `/v1/projects/${encodeURIComponent(projectId)}/secrets`, pageQuery()
    ),
    runtimeRequest<SyntheticPage<StyleProfile>>(`${base}/style-profiles`, pageQuery()),
    runtimeRequest<SyntheticPage<ReviewSuite>>(`${base}/review-suites`, pageQuery()),
    selectedSuiteId
      ? runtimeRequest<SyntheticPage<ReviewCase>>(
        `${base}/review-suites/${encodeURIComponent(selectedSuiteId)}/cases`, pageQuery()
      )
      : Promise.resolve(null),
    selectedJobId
      ? runtimeRequest<SyntheticJob>(`${base}/jobs/${encodeURIComponent(selectedJobId)}`)
      : Promise.resolve(null)
  ]);
  const authorizationValid = authorizations.ok && isAuthorizationPage(authorizations.data);
  const sourcesValid = sources.ok && isStyleSourcePage(sources.data);
  const previewsValid = previews.ok && isManualImportPreviewPage(previews.data);
  const selectedPreviewValid = selectedPreview?.ok && isManualImportPreview(selectedPreview.data);
  const inventoryValid = inventory.ok && isSyntheticResourceInventory(inventory.data);
  const runtimesValid = runtimes.ok && isSyntheticRuntimeOptions(runtimes.data);
  const loginSecretsValid = loginSecrets.ok && isStyleLoginSecretPage(loginSecrets.data);
  const profilesValid = profiles.ok && isStyleProfilePage(profiles.data);
  const suitesValid = suites.ok && isReviewSuitePage(suites.data);
  const casesValid = cases?.ok && isReviewCasePage(cases.data);
  const jobValid = job?.ok && isSyntheticJob(job.data);
  return {
    authorizations: authorizationValid ? authorizations.data : emptyPage(),
    ...(!authorizationValid
      ? { authorizationsProblem: loadProblem(authorizations, "Authorization 列表加载失败。") }
      : {}),
    sources: sourcesValid ? sources.data : emptyPage(),
    ...(!sourcesValid ? { sourcesProblem: loadProblem(sources, "Style Source 列表加载失败。") } : {}),
    importPreviews: previewsValid ? previews.data : emptyPage(),
    ...(!previewsValid
      ? { importPreviewsProblem: loadProblem(previews, "导入预览列表加载失败。") }
      : {}),
    selectedImportPreview: selectedPreviewValid ? selectedPreview.data : null,
    ...(selectedPreview && !selectedPreviewValid
      ? { importPreviewProblem: loadProblem(selectedPreview, "导入预览详情加载失败。") }
      : {}),
    inventory: inventoryValid ? inventory.data : emptyInventory(),
    ...(!inventoryValid
      ? { inventoryProblem: loadProblem(inventory, "Synthetic 资源选项加载失败。") }
      : {}),
    runtimeOptions: runtimesValid ? runtimes.data : emptyRuntimeOptions(),
    ...(!runtimesValid
      ? { runtimeOptionsProblem: loadProblem(runtimes, "已批准模型运行时目录加载失败。") }
      : {}),
    loginSecrets: loginSecretsValid
      ? loginSecrets.data.items.filter((item) => item.status === "active"
        && item.current_version !== null
        && item.purpose.startsWith("style_collection_login."))
      : [],
    ...(!loginSecretsValid
      ? { loginSecretsProblem: loadProblem(loginSecrets, "Style Collection Secret 列表加载失败。") }
      : {}),
    profiles: profilesValid ? profiles.data : emptyPage(),
    ...(!profilesValid ? { profilesProblem: loadProblem(profiles, "Profile 列表加载失败。") } : {}),
    suites: suitesValid ? suites.data : emptyPage(),
    ...(!suitesValid ? { suitesProblem: loadProblem(suites, "Review Suite 列表加载失败。") } : {}),
    selectedSuiteId,
    selectedCases: casesValid ? cases.data : emptyPage(),
    ...(cases && !casesValid ? { casesProblem: loadProblem(cases, "Review Case 列表加载失败。") } : {}),
    selectedJob: jobValid ? job.data : null,
    ...(job && !jobValid ? { jobProblem: loadProblem(job, "Synthetic Job 加载失败。") } : {})
  };
}

function emptyRuntimeOptions(): SyntheticRuntimeOptions {
  return { current_manifest_id: null, items: [] };
}

function emptyInventory(): SyntheticResourceInventory {
  return {
    synthetic: true,
    test_only: true,
    publication_eligible: false,
    samples: [],
    prompt_bindings: [],
    question_sets: [],
    fact_snapshots: [],
    profiles: [],
    review_jobs: [],
    candidate_corpora: [],
    approved_corpora: []
  };
}

function pageQuery() {
  return { query: { limit: PAGE_SIZE, offset: 0 } } as const;
}

function emptyPage<T>(): SyntheticPage<T> {
  return {
    synthetic: true,
    test_only: true,
    publication_eligible: false,
    items: [],
    total: 0,
    limit: PAGE_SIZE,
    offset: 0
  };
}

function loadProblem(
  response: RuntimeResult<unknown>,
  fallback: string
): SyntheticLoadProblem {
  if (!response.ok) {
    return {
      ...(response.status === undefined ? {} : { status: response.status }),
      detail: response.error || fallback,
      ...(response.problem.correlation_id ? { correlationId: response.problem.correlation_id } : {})
    };
  }
  return {
    status: 502,
    detail: "Synthetic Lab 接口返回了不安全或无法识别的响应。",
    ...(response.response.correlationId ? { correlationId: response.response.correlationId } : {})
  };
}

function queryValue(params: SearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}
