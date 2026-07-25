import { createServer } from "node:http";

const PORT = Number(process.env.GEO_CUSTOMER_FIXTURE_PORT || 3198);
const PROJECT_A = "10000000-0000-4000-8000-000000000001";
const PROJECT_B = "10000000-0000-4000-8000-000000000002";
const CAMPAIGN_A = "20000000-0000-4000-8000-000000000001";
const CAMPAIGN_B = "20000000-0000-4000-8000-000000000002";
const CAMPAIGN_MALICIOUS = "20000000-0000-4000-8000-000000000003";
const CAMPAIGN_FORBIDDEN = "20000000-0000-4000-8000-000000000004";
const CAMPAIGN_UNAVAILABLE = "20000000-0000-4000-8000-000000000005";
const CAMPAIGN_LONG = "20000000-0000-4000-8000-000000000006";
const CAMPAIGN_INVALID_METRIC = "20000000-0000-4000-8000-000000000007";
const CAMPAIGN_INVALID_COUNT = "20000000-0000-4000-8000-000000000008";
const CAMPAIGN_UNRELATED_FORBIDDEN = "20000000-0000-4000-8000-000000000009";
const CAMPAIGN_UNRELATED_UNAVAILABLE = "20000000-0000-4000-8000-000000000010";
const PROTOCOL = "30000000-0000-4000-8000-000000000001";
const SNAPSHOT = "40000000-0000-4000-8000-000000000001";
const REPORT = "50000000-0000-4000-8000-000000000001";
const WORKFLOW_C_REPORT = "50000000-0000-4000-8000-000000000002";
const DESTINATION = "60000000-0000-4000-8000-000000000001";
const QUERY = "90000000-0000-4000-8000-000000000001";
const NOW = "2026-07-19T06:00:00Z";
const HASH = "a".repeat(64);
const requests = [];

const projects = [
  {
    project_id: PROJECT_A,
    display_name: "澳洲增长项目",
    market_code: "AU",
    role: "customer",
    status: "active"
  },
  {
    project_id: PROJECT_B,
    display_name: "新西兰待启动项目",
    market_code: "NZ",
    role: "viewer",
    status: "active"
  }
];

const campaigns = [
  {
    id: CAMPAIGN_A,
    project_id: PROJECT_A,
    name: "机器人吸尘器基线",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 1,
    latest_approved_at: NOW
  },
  {
    id: CAMPAIGN_B,
    project_id: PROJECT_A,
    name: "新品发布观察",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  },
  {
    id: CAMPAIGN_MALICIOUS,
    project_id: PROJECT_A,
    name: "异常投影隔离",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  },
  {
    id: CAMPAIGN_FORBIDDEN,
    project_id: PROJECT_A,
    name: "权限隔离验证",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  },
  {
    id: CAMPAIGN_UNAVAILABLE,
    project_id: PROJECT_A,
    name: "服务降级验证",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  },
  {
    id: CAMPAIGN_LONG,
    project_id: PROJECT_A,
    name: "长内容布局验证",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  },
  {
    id: CAMPAIGN_INVALID_METRIC,
    project_id: PROJECT_A,
    name: "越界指标隔离",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  },
  {
    id: CAMPAIGN_INVALID_COUNT,
    project_id: PROJECT_A,
    name: "非整数 Count 隔离",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  },
  {
    id: CAMPAIGN_UNRELATED_FORBIDDEN,
    project_id: PROJECT_A,
    name: "无关模块权限隔离",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  },
  {
    id: CAMPAIGN_UNRELATED_UNAVAILABLE,
    project_id: PROJECT_A,
    name: "无关模块服务隔离",
    objective: "recommendation_influence",
    status: "active",
    approved_report_count: 0,
    latest_approved_at: null
  }
];

const metric = {
  id: SNAPSHOT,
  project_id: PROJECT_A,
  protocol_id: PROTOCOL,
  campaign_id: CAMPAIGN_A,
  measurement_window: "t28",
  capture_method: "manual_ui",
  source_stratum: {
    source_contract_version: "geo-observation-source-v3",
    capture_method: "manual_ui",
    platform: "openai",
    platform_detail: null,
    surface: "chatgpt_search",
    surface_kind: "consumer_ui",
    surface_detail: null,
    engine: "chatgpt",
    configured_model: { state: "disclosed", value: "gpt-search" },
    reported_model: { state: "disclosed", value: "gpt-search" },
    locale: "en-AU",
    region: "AU",
    language: "en",
    device: "desktop",
    client_kind: "browser",
    search_enabled: true,
    search_mode: "live_web"
  },
  source_stratum_hash: HASH,
  statistics_contract_version: "geo-observation-statistics-v2",
  query_cluster_key: "recommendation",
  analysis_stratum_hash: "b".repeat(64),
  minimum_valid_repeats: 3,
  expected_sample_count: 10,
  sampled_sample_count: 10,
  eligible_sample_count: 9,
  invalid_sample_count: 1,
  missing_sample_count: 0,
  sampling_completion_ratio: 1,
  valid_completion_ratio: 0.9,
  query_count: 1,
  sufficient_query_count: 1,
  invalid_reason_counts: { invalid_response: 1 },
  declared_confounding_factors: [],
  query_results: [{
    monitoring_query_id: QUERY,
    query_text_snapshot: "best robot vacuum",
    query_cluster_key: "recommendation",
    expected_sample_count: 10,
    sampled_sample_count: 10,
    valid_sample_count: 9,
    invalid_sample_count: 1,
    missing_sample_count: 0,
    meets_threshold: true,
    invalid_reason_counts: { invalid_response: 1 },
    confounding_factors: [],
    recommendation: { numerator: 6, denominator: 9, share: 0.67, ci_low: 0.35, ci_high: 0.88 },
    product_mention: { numerator: 7, denominator: 9, share: 0.78, ci_low: 0.45, ci_high: 0.94 },
    placement_citation: { numerator: 4, denominator: 9, share: 0.44, ci_low: 0.19, ci_high: 0.73 },
    competitor: { numerator: 5, denominator: 9, share: 0.56, ci_low: 0.27, ci_high: 0.81 },
    competitive_delta: 0.12
  }],
  recommendation_share: 0.67,
  recommendation_ci_low: 0.35,
  recommendation_ci_high: 0.88,
  product_mention_share: 0.78,
  product_mention_ci_low: 0.45,
  product_mention_ci_high: 0.94,
  placement_citation_share: 0.44,
  placement_citation_ci_low: 0.19,
  placement_citation_ci_high: 0.73,
  recommendation_query_min: 0.67,
  recommendation_query_max: 0.67,
  product_mention_query_min: 0.78,
  product_mention_query_max: 0.78,
  placement_citation_query_min: 0.44,
  placement_citation_query_max: 0.44,
  worst_query_id: QUERY,
  selected_destination_ids: [DESTINATION],
  qualified_destination_ids: [DESTINATION],
  verified_destination_ids: [DESTINATION],
  qualified_destination_coverage: 1,
  verified_placement_coverage: 1,
  competitive_delta: 0.12,
  status: "complete",
  confounded_reasons: [],
  method_version: "geo-observation-statistics-v2",
  input_hash: "c".repeat(64),
  result_hash: "d".repeat(64),
  observation_membership_version: "metric-observation-membership-v1",
  observation_membership_hash: "e".repeat(64),
  observation_membership_count: 10,
  computed_at: NOW
};

const report = {
  id: REPORT,
  project_id: PROJECT_A,
  protocol_id: PROTOCOL,
  campaign_id: CAMPAIGN_A,
  metric_snapshot_id: SNAPSHOT,
  title: "T+28 已批准测量报告",
  body: "该窗口的推荐表现保持稳定，投放引用已通过公开地址验证。",
  methodology_statement: "Observational monitoring only; results are non-causal.",
  report_hash: HASH,
  status: "approved",
  generated_at: NOW,
  approved_at: NOW
};

const workflowCReport = {
  id: WORKFLOW_C_REPORT,
  project_id: PROJECT_A,
  campaign_id: CAMPAIGN_A,
  semantic_snapshot_hash: "1".repeat(64),
  report_hash: "2".repeat(64),
  source_kind: "provider_api",
  approved_safe_payload: {
    headline: "跨引擎推荐表现",
    summary: "澳洲英文采样中，产品提及和推荐保持稳定。",
    methodology: "结果来自已批准、满足有效完成度门槛的真实观测。",
    mention_rate: "1.0000",
    metrics: {
      brand_mention: "0.78",
      recommendation: "0.67",
      citation_entailment: "0.89",
      competitor_relative_position: "-1",
      sentiment: "1.0000",
      source_domain_diversity: "4",
      approved_corpus_absorption: "0.7500"
    },
    warnings: ["自动化界面与 Provider API 使用独立分母。"]
  },
  approved_at: NOW
};

const invalidWorkflowCReport = {
  ...workflowCReport,
  id: "50000000-0000-4000-8000-000000000003",
  campaign_id: CAMPAIGN_MALICIOUS,
  approved_safe_payload: {
    headline: "不得进入客户门户",
    access_token: "customer-secret-must-not-render"
  }
};

const longWorkflowCReport = {
  ...workflowCReport,
  id: "50000000-0000-4000-8000-000000000004",
  campaign_id: CAMPAIGN_LONG,
  report_hash: "f".repeat(64),
  approved_safe_payload: {
    headline: "H".repeat(200),
    metrics: { source_domain_diversity: "4" },
    warnings: ["W".repeat(500)]
  }
};

const invalidMetricWorkflowCReport = {
  ...workflowCReport,
  id: "50000000-0000-4000-8000-000000000005",
  campaign_id: CAMPAIGN_INVALID_METRIC,
  approved_safe_payload: {
    headline: "越界指标不得进入客户门户",
    metrics: { brand_mention: `1.${"0".repeat(60)}1` }
  }
};

const invalidCountWorkflowCReport = {
  ...workflowCReport,
  id: "50000000-0000-4000-8000-000000000006",
  campaign_id: CAMPAIGN_INVALID_COUNT,
  approved_safe_payload: {
    headline: "非整数 Count 不得进入客户门户",
    metrics: { source_domain_diversity: `${"9".repeat(61)}.5` }
  }
};

function campaignReadModel(campaignId) {
  const campaign = campaigns.find((item) => item.id === campaignId);
  if (!campaign) return null;
  const approved = campaignId === CAMPAIGN_A
    ? [{ report, snapshot: metric, snapshot_contract: "statistics_v2" }]
    : [];
  const urls = campaignId === CAMPAIGN_A
    ? [{
        campaign_id: CAMPAIGN_A,
        protocol_ids: [PROTOCOL],
        url: "https://example.test/reviews/robot-vacuum",
        title: "机器人吸尘器实测",
        destination_id: DESTINATION,
        first_verified_at: NOW,
        observation_count: 4
      }]
    : [];
  return {
    campaign,
    summary: {
      project_id: PROJECT_A,
      campaign_id: campaign.id,
      campaign_name: campaign.name,
      campaign_objective: campaign.objective,
      campaign_status: campaign.status,
      frozen_protocol_count: approved.length ? 1 : 0,
      measurement_window_count: approved.length,
      verified_url_count: urls.length,
      approved_report_count: campaign.approved_report_count,
      latest_metrics: approved.map((item) => item.snapshot),
      interpretation: "Observational monitoring only; results are non-causal."
    },
    approved_measurements: approved,
    verified_urls: urls
  };
}

function send(response, value, status = 200) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "X-Request-ID": "customer-browser-fixture"
  });
  response.end(JSON.stringify(value));
}

function sendZip(response) {
  response.writeHead(200, {
    "Content-Type": "application/zip",
    "Content-Disposition": `attachment; filename="geo-project-export-${CAMPAIGN_A}.zip"`,
    ETag: "f".repeat(64)
  });
  response.end(Buffer.from("customer-approved-export-zip"));
}

const server = createServer((request, response) => {
  const url = new URL(request.url || "/", `http://127.0.0.1:${PORT}`);
  requests.push({ method: request.method, path: url.pathname, query: url.search });

  if (url.pathname === "/health") return send(response, { status: "ok" });
  if (url.pathname === "/__requests" && request.method === "GET") {
    return send(response, requests);
  }
  if (url.pathname === "/__requests" && request.method === "DELETE") {
    requests.length = 0;
    return send(response, { reset: true });
  }
  if (url.pathname === "/v1/auth/me") {
    return send(response, {
      actor_id: "70000000-0000-4000-8000-000000000001",
      tenant_id: "80000000-0000-4000-8000-000000000001",
      project_ids: [PROJECT_A, PROJECT_B],
      roles: ["customer"]
    });
  }
  if (url.pathname === "/v1/projects") {
    return send(response, {
      items: projects,
      total: projects.length,
      limit: Number(url.searchParams.get("limit") || 100),
      offset: Number(url.searchParams.get("offset") || 0)
    });
  }
  if (
    url.pathname === `/v1/projects/${PROJECT_A}/project-exports/campaigns/${CAMPAIGN_A}/download`
    && request.method === "GET"
  ) {
    return sendZip(response);
  }
  const campaignList = url.pathname.match(/^\/v1\/projects\/([^/]+)\/geo\/campaigns$/);
  if (campaignList) {
    return send(response, campaignList[1] === PROJECT_A ? campaigns : []);
  }
  const workflowCReports = url.pathname.match(
    /^\/v1\/projects\/([^/]+)\/geo\/workflow-c-reports$/
  );
  if (workflowCReports) {
    const campaignId = url.searchParams.get("campaign_id");
    if (campaignId === CAMPAIGN_FORBIDDEN || campaignId === CAMPAIGN_UNRELATED_FORBIDDEN) {
      return send(response, {
        type: "urn:geo:problem:forbidden",
        title: "Forbidden",
        status: 403,
        detail: "Workflow C reports are not authorized for this Campaign.",
        instance: url.pathname,
        request_id: "customer-workflow-c-forbidden"
      }, 403);
    }
    if (campaignId === CAMPAIGN_UNAVAILABLE || campaignId === CAMPAIGN_UNRELATED_UNAVAILABLE) {
      return send(response, {
        type: "urn:geo:problem:service-unavailable",
        title: "Service Unavailable",
        status: 503,
        detail: "Workflow C report storage is temporarily unavailable.",
        instance: url.pathname,
        request_id: "customer-workflow-c-unavailable"
      }, 503);
    }
    const items = workflowCReports[1] !== PROJECT_A
      ? []
      : campaignId === CAMPAIGN_A
        ? [workflowCReport]
        : campaignId === CAMPAIGN_MALICIOUS
          ? [invalidWorkflowCReport]
          : campaignId === CAMPAIGN_LONG
            ? [longWorkflowCReport]
            : campaignId === CAMPAIGN_INVALID_METRIC
              ? [invalidMetricWorkflowCReport]
              : campaignId === CAMPAIGN_INVALID_COUNT
                ? [invalidCountWorkflowCReport]
                : [];
    return send(response, { items, total: items.length });
  }
  const readModel = url.pathname.match(
    /^\/v1\/projects\/([^/]+)\/geo\/campaigns\/([^/]+)\/read-model$/
  );
  if (readModel) {
    const value = readModel[1] === PROJECT_A ? campaignReadModel(readModel[2]) : null;
    return value
      ? send(response, value)
      : send(response, {
          type: "urn:geo:problem:not-found",
          title: "Not Found",
          status: 404,
          detail: "Campaign is not visible.",
          instance: url.pathname,
          request_id: "customer-browser-fixture"
        }, 404);
  }
  return send(response, { detail: "Not Found" }, 404);
});

server.listen(PORT, "127.0.0.1");

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
