import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isDirectGenerationOptions,
  isSyntheticJob,
  isSyntheticJobPage,
  isSyntheticReviewResult,
  isSyntheticRuntimeOptions,
  type DirectGenerationOptions,
  type SyntheticJob,
  type SyntheticLabView,
  type SyntheticLoadProblem,
  type SyntheticPage,
  type SyntheticResourceInventory,
  type SyntheticReviewResult,
  type SyntheticRuntimeOptions,
  type SyntheticWorkspaceData
} from "./syntheticLabTypes";

type SearchParams = { [key: string]: string | string[] | undefined };
const JOB_PAGE_SIZE = 10;

export async function loadSyntheticLabWorkspace(
  projectId: string,
  query: SearchParams
): Promise<SyntheticWorkspaceData> {
  const base = `/v1/projects/${encodeURIComponent(projectId)}/synthetic-lab`;
  const currentView = normalizeSyntheticView(queryValue(query, "synthetic_view"));
  const selectedJobId = queryValue(query, "synthetic_job_id") || null;
  const requestedRuntimeId = queryValue(query, "synthetic_runtime_id") || null;
  const requestedThreshold = Number(queryValue(query, "synthetic_style_threshold"));
  const jobPage = positivePage(queryValue(query, "synthetic_page"));
  const [directOptions, runtimes, jobs, job] = await Promise.all([
    runtimeRequest<DirectGenerationOptions>(`${base}/direct-generation/options`),
    runtimeRequest<SyntheticRuntimeOptions>(
      `/v1/projects/${encodeURIComponent(projectId)}/model-gateway/options`
    ),
    runtimeRequest<SyntheticPage<SyntheticJob>>(`${base}/jobs`, {
      query: {
        kind: "candidate_generation",
        limit: JOB_PAGE_SIZE,
        offset: (jobPage - 1) * JOB_PAGE_SIZE
      }
    }),
    selectedJobId
      ? runtimeRequest<SyntheticJob>(`${base}/jobs/${encodeURIComponent(selectedJobId)}`)
      : Promise.resolve(null)
  ]);
  const directOptionsValid = directOptions.ok
    && isDirectGenerationOptions(directOptions.data);
  const runtimesValid = runtimes.ok && isSyntheticRuntimeOptions(runtimes.data);
  const jobsValid = jobs.ok && isSyntheticJobPage(jobs.data);
  const jobValid = job?.ok && isSyntheticJob(job.data);
  const shouldLoadResult = Boolean(
    jobValid && job.data.kind === "candidate_generation" && job.data.status === "succeeded"
  );
  const result = selectedJobId && shouldLoadResult
    ? await runtimeRequest<SyntheticReviewResult>(
      `${base}/jobs/${encodeURIComponent(selectedJobId)}/result`
    )
    : null;
  const resultValid = result?.ok && isSyntheticReviewResult(result.data);

  return {
    currentView,
    generationDefaults: {
      caseId: null,
      runtimeId: requestedRuntimeId,
      stylePassThreshold: Number.isFinite(requestedThreshold)
        && requestedThreshold >= 0 && requestedThreshold <= 5
        ? requestedThreshold : 4.2
    },
    directOptions: directOptionsValid ? directOptions.data : emptyDirectOptions(),
    ...(!directOptionsValid
      ? { directOptionsProblem: loadProblem(directOptions, "生成选项加载失败。") }
      : {}),
    jobPage,
    runtimeOptions: runtimesValid ? runtimes.data : emptyRuntimeOptions(),
    ...(!runtimesValid
      ? { runtimeOptionsProblem: loadProblem(runtimes, "模型运行时加载失败。") }
      : {}),
    jobs: jobsValid ? jobs.data : emptyPage(JOB_PAGE_SIZE),
    ...(!jobsValid ? { jobsProblem: loadProblem(jobs, "生成记录加载失败。") } : {}),
    selectedJob: jobValid ? job.data : null,
    ...(job && !jobValid ? { jobProblem: loadProblem(job, "生成任务加载失败。") } : {}),
    selectedResult: resultValid ? result.data : null,
    ...(result && !resultValid
      ? { resultProblem: loadProblem(result, "生成结果加载失败。") }
      : {}),

    // Legacy management data remains available to internal API clients, but is intentionally
    // not fetched by the direct-generation workspace.
    authorizations: emptyPage(),
    sources: emptyPage(),
    importPreviews: emptyPage(),
    selectedImportPreview: null,
    inventory: emptyInventory(),
    loginSecrets: [],
    profiles: emptyPage(),
    suites: emptyPage(),
    selectedSuiteId: null,
    selectedCases: emptyPage()
  };
}

function normalizeSyntheticView(value: string | undefined): SyntheticLabView {
  return value === "style" ? "style" : "generate";
}

function positivePage(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1;
}

function emptyRuntimeOptions(): SyntheticRuntimeOptions {
  return { current_manifest_id: null, items: [] };
}

function emptyDirectOptions(): DirectGenerationOptions {
  return {
    synthetic: true,
    test_only: true,
    publication_eligible: false,
    subjects: [],
    channel_styles: [],
    has_competitor_knowledge: false
  };
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

function emptyPage<T>(limit = 100): SyntheticPage<T> {
  return {
    synthetic: true,
    test_only: true,
    publication_eligible: false,
    items: [],
    total: 0,
    limit,
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
      ...(response.problem.correlation_id
        ? { correlationId: response.problem.correlation_id }
        : {})
    };
  }
  return {
    status: 502,
    detail: "合成测评接口返回了无法识别的响应。",
    ...(response.response.correlationId
      ? { correlationId: response.response.correlationId }
      : {})
  };
}

function queryValue(params: SearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}
