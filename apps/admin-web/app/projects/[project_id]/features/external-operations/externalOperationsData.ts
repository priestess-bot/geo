import { runtimeRequest, type RuntimeResult } from "../../../../runtime";
import type {
  AttributionInventory, BrowserInventory, ConnectorInventory, ExternalOperationsData,
  BrowserAdmissionPolicy, ExternalReport, LoadProblem
} from "./externalOperationsTypes";

const EMPTY_CONNECTORS: ConnectorInventory = {
  definitions: [], connections: [], scopes: [], runs: [], connection_tests: []
};
const EMPTY_BROWSER: BrowserInventory = {
  surface_releases: [], egress_endpoints: [], profiles: [], egress_tests: [],
  drift_events: [], tasks: [], sessions: []
};
const EMPTY_ATTRIBUTION: AttributionInventory = {
  policies: [], collectors: [], counts: {}, snapshots: []
};

export async function loadExternalOperations(projectId: string): Promise<ExternalOperationsData> {
  const base = `/v1/projects/${encodeURIComponent(projectId)}`;
  const [connectors, browser, reports, attribution, policies, operationalAlertInputs] = await Promise.all([
    runtimeRequest<ConnectorInventory>(`${base}/connectors`),
    runtimeRequest<BrowserInventory>(`${base}/browser-capture`),
    runtimeRequest<ExternalReport[]>(`${base}/external-data/reports`),
    runtimeRequest<AttributionInventory>(`${base}/attribution`),
    runtimeRequest<{ items: BrowserAdmissionPolicy[] }>(`${base}/sampling/admission-policies`),
    runtimeRequest<ExternalOperationsData["operationalAlertInputs"]>(
      `${base}/external-data/operational-alert-inputs`
    )
  ]);
  return {
    connectors: validConnectorInventory(connectors) ? connectors.data : EMPTY_CONNECTORS,
    browser: validBrowserInventory(browser) ? browser.data : EMPTY_BROWSER,
    browserAdmissionPolicies: validPolicyPage(policies) ? policies.data.items : [],
    reports: validReports(reports) ? reports.data : [],
    operationalAlertInputs: validReports(operationalAlertInputs) ? operationalAlertInputs.data : [],
    attribution: validAttribution(attribution) ? attribution.data : EMPTY_ATTRIBUTION,
    problems: {
      ...(!validConnectorInventory(connectors) ? { connectors: problem(connectors) } : {}),
      ...(!validBrowserInventory(browser) ? { browser: problem(browser) } : {}),
      ...(!validPolicyPage(policies) ? { browserPolicies: problem(policies) } : {}),
      ...(!validReports(reports) ? { reports: problem(reports) } : {}),
      ...(!validReports(operationalAlertInputs) ? { alerts: problem(operationalAlertInputs) } : {}),
      ...(!validAttribution(attribution) ? { attribution: problem(attribution) } : {})
    }
  };
}

function validPolicyPage(
  result: RuntimeResult<{ items: BrowserAdmissionPolicy[] }>
): result is Extract<RuntimeResult<{ items: BrowserAdmissionPolicy[] }>, { ok: true }> {
  return result.ok && record(result.data) && Array.isArray(result.data.items);
}

function validConnectorInventory(result: RuntimeResult<ConnectorInventory>): result is Extract<
  RuntimeResult<ConnectorInventory>, { ok: true }
> {
  return result.ok && record(result.data)
    && ["definitions", "connections", "scopes", "runs", "connection_tests"]
    .every((key) => Array.isArray(result.data[key as keyof ConnectorInventory]));
}

function validBrowserInventory(result: RuntimeResult<BrowserInventory>): result is Extract<
  RuntimeResult<BrowserInventory>, { ok: true }
> {
  return result.ok && record(result.data)
    && Array.isArray(result.data.surface_releases) && Array.isArray(result.data.egress_endpoints)
    && Array.isArray(result.data.egress_tests)
    && Array.isArray(result.data.drift_events)
    && Array.isArray(result.data.profiles) && Array.isArray(result.data.tasks)
    && Array.isArray(result.data.sessions);
}

function validReports<T>(result: RuntimeResult<T[]>): result is Extract<
  RuntimeResult<T[]>, { ok: true }
> {
  return result.ok && Array.isArray(result.data);
}

function validAttribution(result: RuntimeResult<AttributionInventory>): result is Extract<
  RuntimeResult<AttributionInventory>, { ok: true }
> {
  return result.ok && record(result.data) && Array.isArray(result.data.policies)
    && Array.isArray(result.data.collectors) && record(result.data.counts)
    && Array.isArray(result.data.snapshots);
}

function problem(result: RuntimeResult<unknown>): LoadProblem {
  if (!result.ok) return {
    ...(result.status === undefined ? {} : { status: result.status }),
    detail: result.error,
    ...(result.problem.correlation_id ? { correlationId: result.problem.correlation_id } : {})
  };
  return { status: 502, detail: "接口返回了无法识别的数据结构。" };
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
