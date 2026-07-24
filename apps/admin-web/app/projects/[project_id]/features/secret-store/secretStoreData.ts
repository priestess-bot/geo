import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import {
  isSecretAuditPage,
  isSecretReference,
  isSecretReferencePage,
  type SecretAuditPage,
  type SecretLoadProblem,
  type SecretReference,
  type SecretReferencePage,
  type SecretWorkspaceData
} from "./secretStoreTypes";

type SearchParams = { [key: string]: string | string[] | undefined };

const REFERENCE_PAGE_SIZE = 20;
const AUDIT_PAGE_SIZE = 50;

export async function loadSecretWorkspace(
  projectId: string,
  query: SearchParams
): Promise<SecretWorkspaceData> {
  const base = `/v1/projects/${encodeURIComponent(projectId)}/secrets`;
  const referenceOffset = (positivePage(queryValue(query, "secret_page")) - 1)
    * REFERENCE_PAGE_SIZE;
  const auditOffset = (positivePage(queryValue(query, "secret_audit_page")) - 1)
    * AUDIT_PAGE_SIZE;
  const requestedReferenceId = queryValue(query, "secret_reference_id");
  let [referencesResponse, auditsResponse, selectedResponse] = await Promise.all([
    runtimeRequest<SecretReferencePage>(base, {
      query: { limit: REFERENCE_PAGE_SIZE, offset: referenceOffset }
    }),
    runtimeRequest<SecretAuditPage>(`${base}/audit-events`, {
      query: { limit: AUDIT_PAGE_SIZE, offset: auditOffset }
    }),
    requestedReferenceId
      ? runtimeRequest<SecretReference>(
        `${base}/${encodeURIComponent(requestedReferenceId)}`
      )
      : Promise.resolve(null)
  ]);

  const referenceFallbackOffset = lastPageOffset(
    referencesResponse,
    referenceOffset,
    REFERENCE_PAGE_SIZE,
    isSecretReferencePage
  );
  const auditFallbackOffset = lastPageOffset(
    auditsResponse,
    auditOffset,
    AUDIT_PAGE_SIZE,
    isSecretAuditPage
  );
  if (referenceFallbackOffset !== null || auditFallbackOffset !== null) {
    [referencesResponse, auditsResponse] = await Promise.all([
      referenceFallbackOffset === null
        ? Promise.resolve(referencesResponse)
        : runtimeRequest<SecretReferencePage>(base, {
          query: { limit: REFERENCE_PAGE_SIZE, offset: referenceFallbackOffset }
        }),
      auditFallbackOffset === null
        ? Promise.resolve(auditsResponse)
        : runtimeRequest<SecretAuditPage>(`${base}/audit-events`, {
          query: { limit: AUDIT_PAGE_SIZE, offset: auditFallbackOffset }
        })
    ]);
  }

  const references = referencesResponse.ok
    && isSecretReferencePage(referencesResponse.data)
    ? referencesResponse.data
    : emptyReferencePage(referenceFallbackOffset ?? referenceOffset);
  const audits = auditsResponse.ok && isSecretAuditPage(auditsResponse.data)
    ? auditsResponse.data
    : emptyAuditPage(auditFallbackOffset ?? auditOffset);
  const referencesValid = referencesResponse.ok
    && isSecretReferencePage(referencesResponse.data);
  const auditsValid = auditsResponse.ok && isSecretAuditPage(auditsResponse.data);
  const listedSelection = requestedReferenceId
    ? references.items.find((item) => item.reference_id === requestedReferenceId) || null
    : references.items[0] || null;
  let selectedReference = listedSelection;
  let selectionProblem: SecretLoadProblem | undefined;
  if (selectedResponse) {
    if (selectedResponse.ok && isSecretReference(selectedResponse.data)) {
      selectedReference = selectedResponse.data;
    } else if (!listedSelection) {
      selectionProblem = loadProblem(selectedResponse, "所选 Secret Reference 加载失败。");
    }
  }
  return {
    references,
    ...(!referencesValid
      ? { referencesProblem: loadProblem(referencesResponse, "Secret Reference 列表加载失败。") }
      : {}),
    audits,
    ...(!auditsValid
      ? { auditsProblem: loadProblem(auditsResponse, "Secret Audit 列表加载失败。") }
      : {}),
    ...(selectionProblem ? { selectionProblem } : {}),
    selectedReference
  };
}

function lastPageOffset<T>(
  response: RuntimeResult<T>,
  requestedOffset: number,
  pageSize: number,
  guard: (value: unknown) => value is T & { items: unknown[]; total: number }
): number | null {
  if (!response.ok || !guard(response.data)) return null;
  if (response.data.total < 1 || response.data.items.length > 0 || requestedOffset < 1) {
    return null;
  }
  return Math.floor((response.data.total - 1) / pageSize) * pageSize;
}

function loadProblem(
  response: RuntimeResult<unknown>,
  fallback: string
): SecretLoadProblem {
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
    detail: "Secret Store 接口返回了无法识别的元数据响应。",
    ...(response.response.correlationId
      ? { correlationId: response.response.correlationId }
      : {})
  };
}

function emptyReferencePage(offset: number): SecretReferencePage {
  return { items: [], total: 0, limit: REFERENCE_PAGE_SIZE, offset };
}

function emptyAuditPage(offset: number): SecretAuditPage {
  return { items: [], total: 0, limit: AUDIT_PAGE_SIZE, offset };
}

function positivePage(value: string | undefined): number {
  const parsed = Number(value || "1");
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1;
}

function queryValue(params: SearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}
