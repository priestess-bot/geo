from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_customer_web_uses_only_stable_read_only_geo_resources() -> None:
    home = read("apps/customer-web/app/page.tsx")
    runtime = read("apps/customer-web/app/runtime.ts")
    module = read("apps/customer-web/app/portal/[module]/page.tsx")
    client = read("packages/web/api-client/src/customer.ts")
    types = read("packages/web/types/src/customer.ts")
    views = read("apps/customer-web/app/_components/GeoViews.tsx")
    workflow_c_views = read("apps/customer-web/app/_components/WorkflowCReports.tsx")
    chrome = read("apps/customer-web/app/_components/PortalChrome.tsx")
    styles = read("apps/customer-web/app/globals.css")
    workflow_c_contract = read(
        "packages/web/api-client/src/customer-workflow-c-contract.ts"
    )

    assert "invitation_id" in home
    assert "loadSessionPortal" in home
    assert "Promise.all" in runtime
    assert "{ Cookie:" in runtime
    assert "GEO_SESSION_COOKIE" in runtime
    for method in (
        "listProjects",
        "listGeoCampaigns",
        "getGeoCampaignReadModel",
        "listWorkflowCApprovedReports",
    ):
        assert method in runtime
        assert method in client
    for compatibility_method in (
        "getGeoSummary",
        "listGeoMetrics",
        "listMeasurementWindows",
        "listVerifiedUrls",
        "listApprovedReports",
    ):
        assert compatibility_method in client
        assert compatibility_method not in runtime
    for stable_path in (
        '"/v1/projects"',
        '"summary"',
        '"metrics"',
        '"measurement-windows"',
        '"verified-urls"',
        '"reports"',
    ):
        assert stable_path in client
    assert "/geo/campaigns" in client
    assert "/read-model" in client
    assert '"workflow-c-reports"' in client

    assert "CustomerProblemDetails" in runtime
    assert "CustomerProblemDetails" in types
    assert "project.role" in chrome
    assert "session.projects" in chrome
    assert "SummaryView" in module
    assert "MetricsView" in module
    assert "PlacementsView" in module
    assert "ReportsView" in module
    assert "loadCustomerWorkflowCReports" in module
    assert "resourceProblems(model, workflowCReports)" in module
    assert "moduleUsesWorkflowCReports(rawModule)" in module
    assert "Promise.all([modelPromise, workflowCReportsPromise])" in module
    assert 'module === "summary" || module === "reports"' in module
    assert "已批准报告" in views
    assert "已批准跨引擎报告" in workflow_c_views
    assert "report.report_hash" in workflow_c_views
    assert "report.semantic_snapshot_hash" not in workflow_c_views
    assert 'aria-label="已批准 Workflow C 报告"' in workflow_c_views
    assert "aria-labelledby={titleId}" in workflow_c_views
    assert '<time dateTime={report.approved_at}>' in workflow_c_views
    assert '<caption className="srOnly">' in workflow_c_views
    assert 'scope="col"' in workflow_c_views
    assert 'aria-label="报告注意事项"' in workflow_c_views
    assert ".workflowCReportItem h3" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "word-break: break-all" in styles
    assert "CUSTOMER_WORKFLOW_C_METRIC_KEYS" in workflow_c_contract
    assert "COUNT_METRIC_KEYS" in workflow_c_contract
    assert "SIGNED_METRIC_KEYS" in workflow_c_contract
    assert "decimalTextIsInteger" in workflow_c_contract
    assert "decimalAbsoluteAtMostOne" in workflow_c_contract
    assert "Number(value)" not in workflow_c_contract
    assert "hasExactKeys" in workflow_c_contract
    assert "customerWorkflowCReportPageGuard" in workflow_c_contract
    assert "item.project_id === projectId" in workflow_c_contract
    assert "item.campaign_id === campaignId" in workflow_c_contract
    assert "暂无验证通过的公开投放 URL" in views
    assert "Record<string, unknown>" not in types
    assert "JSON.stringify" not in module
    assert "<pre>" not in module

    combined = "\n".join(
        (runtime, client, types, views, workflow_c_views, workflow_c_contract, module)
    )
    for forbidden in (
        "/v1/geo/customer-summary",
        "/v1/visibility-scores/runtime",
        "/v1/evidence-runs/runtime",
        "/v1/collection-runs/runtime",
        "/v1/citation-graphs/runtime",
        "/v1/reports/runtime",
        "/v1/report-export-jobs/runtime",
        "/v1/action-plans/runtime",
        "/v1/traceability/runtime",
        "X-GEO-Actor-Id",
        "X-GEO-Session-Token",
        "Session-Actor",
        "raw_observation",
        "internal_evidence",
        "prompt_bundle",
        "unapproved_report",
    ):
        assert forbidden not in combined
    assert not (ROOT / "apps/customer-web/app/api/report-artifact/route.ts").exists()


def test_customer_pages_cover_auth_empty_partial_failure_and_loading_states() -> None:
    runtime = read("apps/customer-web/app/runtime.ts")
    module = read("apps/customer-web/app/portal/[module]/page.tsx")
    views = read("apps/customer-web/app/_components/GeoViews.tsx")
    workflow_c_views = read("apps/customer-web/app/_components/WorkflowCReports.tsx")
    loading = read("apps/customer-web/app/loading.tsx")

    assert 'identity.problem.status === 401' in runtime
    assert 'problem.status === 403' in views
    assert "resourceProblems(model, workflowCReports)" in module
    assert "Promise.all" in runtime
    assert "暂无验证通过的公开投放 URL" in views
    assert "暂无已批准报告" in views
    assert "Workflow C 报告暂不可用" in workflow_c_views
    assert "aria-busy" in loading


def test_customer_frontend_files_stay_within_module_budget() -> None:
    for relative in (
        "apps/customer-web/app/page.tsx",
        "apps/customer-web/app/runtime.ts",
        "apps/customer-web/app/portal/[module]/page.tsx",
        "apps/customer-web/app/_components/GeoViews.tsx",
        "apps/customer-web/app/_components/WorkflowCReports.tsx",
        "apps/customer-web/app/_components/PortalChrome.tsx",
        "packages/web/api-client/src/customer.ts",
        "packages/web/api-client/src/customer-workflow-c-contract.ts",
        "packages/web/types/src/customer.ts",
    ):
        assert len(read(relative).splitlines()) < 600, relative
