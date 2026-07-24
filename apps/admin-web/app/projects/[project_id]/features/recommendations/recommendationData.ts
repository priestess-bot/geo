import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isRecommendationPage,
  isRecommendationWorkflow
} from "./recommendationTypeGuards";
import {
  isRecommendationModelRuntimeOptions,
  isRecommendationPromptBindingPage,
  type RecommendationGenerationCatalog,
  type RecommendationModelRuntimeOptions,
  type RecommendationPromptBindingPage
} from "./recommendationGenerationTypes";
import {
  recommendationStatuses,
  recommendationTypes,
  type RecommendationFilters,
  type RecommendationLoadProblem,
  type RecommendationPage,
  type RecommendationWorkflow,
  type RecommendationWorkspaceData
} from "./recommendationTypes";

export type RecommendationSearchParams = {
  [key: string]: string | string[] | undefined;
};

const LIST_LIMIT = 200;
const emptyPage: RecommendationPage = { items: [], total: 0, limit: LIST_LIMIT, offset: 0 };

export async function loadRecommendationWorkspace(
  projectId: string,
  query: RecommendationSearchParams
): Promise<RecommendationWorkspaceData> {
  const filters = recommendationFilters(query);
  const requestedId = queryValue(query, "recommendation_id");
  const base = recommendationBase(projectId);
  const [listResponse, generationCatalog] = await Promise.all([
    runtimeRequest<RecommendationPage>(base, {
      query: { limit: LIST_LIMIT, offset: 0 }
    }),
    loadGenerationCatalog(projectId)
  ]);
  if (!listResponse.ok || !isRecommendationPage(listResponse.data)) {
    const selectedResult = requestedId
      ? await loadSelected(base, requestedId)
      : { selected: null };
    return {
      page: emptyPage,
      sourceTotal: 0,
      filters,
      generationCatalog,
      listProblem: loadProblem(listResponse, "Recommendation 列表加载失败。"),
      ...selectedResult
    };
  }

  const source = listResponse.data;
  const items = source.items.filter((workflow) => matches(workflow, filters));
  const requestedInSource = requestedId
    ? source.items.find((item) => item.recommendation.id === requestedId) || null
    : null;
  let selected: RecommendationWorkflow | null = requestedInSource || items[0] || null;
  let selectedProblem: RecommendationLoadProblem | undefined;
  if (requestedId && !requestedInSource) {
    const result = await loadSelected(base, requestedId);
    selected = result.selected;
    selectedProblem = result.selectedProblem;
  }
  return {
    page: { items, total: items.length, limit: LIST_LIMIT, offset: 0 },
    sourceTotal: source.total,
    filters,
    generationCatalog,
    selected,
    ...(selectedProblem ? { selectedProblem } : {})
  };
}

async function loadGenerationCatalog(
  projectId: string
): Promise<RecommendationGenerationCatalog> {
  const root = `/v1/projects/${encodeURIComponent(projectId)}`;
  const bindings = `${root}/prompt-program-bindings`;
  const [recommendationResponse, arbiterResponse, runtimeResponse] = await Promise.all([
    runtimeRequest<RecommendationPromptBindingPage>(bindings, {
      query: { program_kind: "recommendation", limit: 100, offset: 0 }
    }),
    runtimeRequest<RecommendationPromptBindingPage>(bindings, {
      query: { program_kind: "arbiter", limit: 100, offset: 0 }
    }),
    runtimeRequest<RecommendationModelRuntimeOptions>(
      `${root}/model-gateway/options`
    )
  ]);
  const recommendationValid = recommendationResponse.ok
    && isRecommendationPromptBindingPage(recommendationResponse.data);
  const arbiterValid = arbiterResponse.ok
    && isRecommendationPromptBindingPage(arbiterResponse.data);
  const runtimeValid = runtimeResponse.ok
    && isRecommendationModelRuntimeOptions(runtimeResponse.data);
  return {
    recommendationPrompts: recommendationValid ? recommendationResponse.data.items : [],
    arbiterPrompts: arbiterValid ? arbiterResponse.data.items : [],
    runtimes: runtimeValid ? runtimeResponse.data.items : [],
    ...(!recommendationValid
      ? { recommendationPromptProblem: catalogProblem(recommendationResponse, "Recommendation Prompt 目录不可用。") }
      : {}),
    ...(!arbiterValid
      ? { arbiterPromptProblem: catalogProblem(arbiterResponse, "Arbiter Prompt 目录不可用。") }
      : {}),
    ...(!runtimeValid
      ? { runtimeProblem: catalogProblem(runtimeResponse, "已批准模型运行时目录不可用。") }
      : {})
  };
}

function catalogProblem(response: RuntimeResult<unknown>, fallback: string): string {
  if (!response.ok) return response.error || fallback;
  return "目录接口返回了无法识别的响应。";
}

export function recommendationFilters(
  query: RecommendationSearchParams
): RecommendationFilters {
  const requestedStatus = queryValue(query, "recommendation_status");
  const requestedType = queryValue(query, "recommendation_type");
  return {
    status: recommendationStatuses.find((value) => value === requestedStatus) || "all",
    type: recommendationTypes.find((value) => value === requestedType) || "all"
  };
}

export function recommendationHref(
  projectId: string,
  recommendationId?: string,
  filters?: RecommendationFilters
): string {
  const params = new URLSearchParams({ tab: "recommendations" });
  if (recommendationId) params.set("recommendation_id", recommendationId);
  if (filters?.status && filters.status !== "all") {
    params.set("recommendation_status", filters.status);
  }
  if (filters?.type && filters.type !== "all") {
    params.set("recommendation_type", filters.type);
  }
  return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
}

export function recommendationBase(projectId: string): string {
  return `/v1/projects/${encodeURIComponent(projectId)}/recommendations`;
}

async function loadSelected(
  base: string,
  recommendationId: string
): Promise<{
  selected: RecommendationWorkflow | null;
  selectedProblem?: RecommendationLoadProblem;
}> {
  const response = await runtimeRequest<RecommendationWorkflow>(
    `${base}/${encodeURIComponent(recommendationId)}`
  );
  if (response.ok && isRecommendationWorkflow(response.data)) {
    return { selected: response.data };
  }
  return {
    selected: null,
    selectedProblem: loadProblem(response, "所选 Recommendation 加载失败。")
  };
}

function matches(
  workflow: RecommendationWorkflow,
  filters: RecommendationFilters
): boolean {
  const recommendation = workflow.recommendation;
  return (filters.status === "all" || recommendation.status === filters.status)
    && (filters.type === "all" || recommendation.recommendation_type === filters.type);
}

function loadProblem(
  response: RuntimeResult<unknown>,
  fallback: string
): RecommendationLoadProblem {
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
    detail: "Recommendation 接口返回了无法识别的响应。",
    ...(response.response.correlationId
      ? { correlationId: response.response.correlationId }
      : {})
  };
}

function queryValue(
  query: RecommendationSearchParams,
  key: string
): string | undefined {
  const value = query[key];
  return Array.isArray(value) ? value[0] : value;
}
