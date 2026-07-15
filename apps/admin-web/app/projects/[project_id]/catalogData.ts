import { runtimeRequest, type RuntimeResult } from "../../runtime";
import type { CatalogProject, ProjectLoadProblem } from "../projectTypes";
import {
  isCatalogEntity,
  isCatalogProject,
  isEvidenceItem,
  isMarketProfile,
  type CatalogEntity,
  type CatalogLoadResult,
  type CatalogResource,
  type EvidenceItem,
  type MarketProfile
} from "./catalogTypes";

export async function loadCatalog(projectId: string): Promise<CatalogLoadResult> {
  const base = `/v1/projects/${encodeURIComponent(projectId)}`;
  const [project, entities, markets, evidence] = await Promise.all([
    runtimeRequest<CatalogProject>(base),
    runtimeRequest<CatalogEntity[]>(`${base}/entities`, { query: { limit: 500, offset: 0 } }),
    runtimeRequest<MarketProfile[]>(`${base}/market-profiles`, { query: { limit: 500, offset: 0 } }),
    runtimeRequest<EvidenceItem[]>(`${base}/evidence-items`, { query: { limit: 500, offset: 0 } })
  ]);
  return {
    project: resource(project, isCatalogProject, null, "项目"),
    entities: listResource(entities, isCatalogEntity, "实体"),
    markets: listResource(markets, isMarketProfile, "市场配置"),
    evidence: listResource(evidence, isEvidenceItem, "证据")
  };
}

function listResource<T>(
  response: RuntimeResult<T[]>,
  guard: (value: unknown) => value is T,
  label: string
): CatalogResource<T[]> {
  if (!response.ok) return { data: [], problem: problem(response, `${label}加载失败。`) };
  if (!Array.isArray(response.data) || !response.data.every(guard)) {
    return {
      data: [],
      problem: malformed(response.response.correlationId, `${label}接口返回了无法识别的响应。`)
    };
  }
  return { data: response.data };
}

function resource<T>(
  response: RuntimeResult<T>,
  guard: (value: unknown) => value is T,
  empty: T,
  label: string
): CatalogResource<T> {
  if (!response.ok) return { data: empty, problem: problem(response, `${label}加载失败。`) };
  if (!guard(response.data)) {
    return {
      data: empty,
      problem: malformed(response.response.correlationId, `${label}接口返回了无法识别的响应。`)
    };
  }
  return { data: response.data };
}

function problem(response: Extract<RuntimeResult<unknown>, { ok: false }>, fallback: string): ProjectLoadProblem {
  return {
    ...(response.status === undefined ? {} : { status: response.status }),
    detail: response.error || fallback,
    ...(response.problem.correlation_id
      ? { correlationId: response.problem.correlation_id }
      : {})
  };
}

function malformed(correlationId: string | undefined, detail: string): ProjectLoadProblem {
  return {
    status: 502,
    detail,
    ...(correlationId ? { correlationId } : {})
  };
}
