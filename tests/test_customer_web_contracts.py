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
    chrome = read("apps/customer-web/app/_components/PortalChrome.tsx")

    assert "invitation_id" in home
    assert "loadSessionPortal" in home
    assert "Promise.all" in runtime
    assert "{ Cookie:" in runtime
    assert "GEO_SESSION_COOKIE" in runtime
    for method in (
        "listProjects",
        "listGeoCampaigns",
        "getGeoCampaignReadModel",
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

    assert "CustomerProblemDetails" in runtime
    assert "CustomerProblemDetails" in types
    assert "project.role" in chrome
    assert "session.projects" in chrome
    assert "SummaryView" in module
    assert "MetricsView" in module
    assert "PlacementsView" in module
    assert "ReportsView" in module
    assert "已批准报告" in views
    assert "暂无验证通过的公开投放 URL" in views
    assert "Record<string, unknown>" not in types
    assert "JSON.stringify" not in module
    assert "<pre>" not in module

    combined = "\n".join((runtime, client, types, views, module))
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
    loading = read("apps/customer-web/app/loading.tsx")

    assert 'identity.problem.status === 401' in runtime
    assert 'problem.status === 403' in views
    assert "resourceProblems(model)" in module
    assert "Promise.all" in runtime
    assert "暂无验证通过的公开投放 URL" in views
    assert "暂无已批准报告" in views
    assert "aria-busy" in loading


def test_customer_frontend_files_stay_within_module_budget() -> None:
    for relative in (
        "apps/customer-web/app/page.tsx",
        "apps/customer-web/app/runtime.ts",
        "apps/customer-web/app/portal/[module]/page.tsx",
        "apps/customer-web/app/_components/GeoViews.tsx",
        "apps/customer-web/app/_components/PortalChrome.tsx",
        "packages/web/api-client/src/customer.ts",
        "packages/web/types/src/customer.ts",
    ):
        assert len(read(relative).splitlines()) < 600, relative
