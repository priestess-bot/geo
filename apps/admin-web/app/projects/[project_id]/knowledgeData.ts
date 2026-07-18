import { runtimeRequest, type RuntimeResult } from "../../runtime";
import type {
  KnowledgeChunk, KnowledgeDashboard, KnowledgeFact, KnowledgeFinding, KnowledgeProblem,
  KnowledgeResource, KnowledgeRun, KnowledgeSource, KnowledgeStage, KnowledgeWorkspaceData
} from "./knowledgeTypes";

type Query = { [key: string]: string | string[] | undefined };

export async function loadKnowledgeWorkspace(
  projectId: string,
  queryParams: Query
): Promise<KnowledgeWorkspaceData> {
  const base = `/v1/projects/${encodeURIComponent(projectId)}/knowledge`;
  const activeView = value(queryParams, "knowledge_tab") || "import";
  const query = value(queryParams, "knowledge_query") || "";
  const [sourcesResult, runsResult, chunksResult, factsResult, findingsResult, dashboardResult] = await Promise.all([
    runtimeRequest<KnowledgeSource[]>(`${base}/sources`),
    runtimeRequest<KnowledgeRun[]>(`${base}/pipeline-runs`),
    runtimeRequest<KnowledgeChunk[]>(`${base}/chunks`, { query: { query } }),
    runtimeRequest<KnowledgeFact[]>(`${base}/fact-candidates`),
    runtimeRequest<KnowledgeFinding[]>(`${base}/quality-findings`),
    runtimeRequest<KnowledgeDashboard>(`${base}/dashboard`)
  ]);
  const runs = listResource(runsResult, "处理任务");
  const selectedRunId = value(queryParams, "pipeline_run_id") || runs.data[0]?.id || "";
  const stagesResult = selectedRunId
    ? await runtimeRequest<KnowledgeStage[]>(`${base}/pipeline-runs/${encodeURIComponent(selectedRunId)}/stages`)
    : null;
  return {
    activeView,
    query,
    sources: listResource(sourcesResult, "知识来源"),
    runs,
    stages: stagesResult ? listResource(stagesResult, "处理阶段") : { data: [] },
    chunks: listResource(chunksResult, "Chunk"),
    facts: listResource(factsResult, "事实候选"),
    findings: listResource(findingsResult, "质量发现"),
    dashboard: objectResource(dashboardResult, emptyDashboard(), "知识看板")
  };
}

function listResource<T>(response: RuntimeResult<T[]>, label: string): KnowledgeResource<T[]> {
  if (!response.ok) return { data: [], problem: problem(response, `${label}加载失败。`) };
  return { data: Array.isArray(response.data) ? response.data : [] };
}

function objectResource<T>(
  response: RuntimeResult<T>, empty: T, label: string
): KnowledgeResource<T> {
  if (!response.ok) return { data: empty, problem: problem(response, `${label}加载失败。`) };
  return { data: response.data || empty };
}

function problem(
  response: Extract<RuntimeResult<unknown>, { ok: false }>, fallback: string
): KnowledgeProblem {
  return {
    ...(response.status === undefined ? {} : { status: response.status }),
    detail: response.error || fallback,
    ...(response.problem.correlation_id ? { correlationId: response.problem.correlation_id } : {})
  };
}

function emptyDashboard(): KnowledgeDashboard {
  return { sources: 0, succeeded_runs: 0, failed_runs: 0, active_chunks: 0, pending_facts: 0, open_findings: 0 };
}

function value(query: Query, key: string): string {
  const candidate = query[key];
  return Array.isArray(candidate) ? candidate[0] || "" : candidate || "";
}
