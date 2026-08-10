from geo_api.app_factory import create_api_app


def test_consumer_browser_capture_is_admin_only_and_replaces_legacy_search_routes() -> None:
    internal = create_api_app(surface="internal").openapi()["paths"]
    customer = create_api_app(surface="customer").openapi()["paths"]
    browser_paths = {
        "/v1/projects/{project_id}/browser-capture/bootstrap",
        "/v1/projects/{project_id}/browser-capture/readiness",
        "/v1/projects/{project_id}/browser-capture/lokiproxy-pool",
        "/v1/projects/{project_id}/browser-capture/session-profile-setup",
        "/v1/projects/{project_id}/browser-capture/sampling-options",
        "/v1/projects/{project_id}/browser-capture/sampling-suite-inputs",
    }
    retired_paths = {
        "/v1/search/google-ai-overview",
        "/v1/search/google-raw",
        "/v1/search/bing-copilot",
        "/v1/search/bing-copilot-raw",
        "/v1/projects/{project_id}/browser-capture/egress-endpoints",
        "/v1/projects/{project_id}/browser-capture/egress-endpoints/{endpoint_id}/approve",
    }

    assert browser_paths <= set(internal)
    assert browser_paths.isdisjoint(customer)
    assert retired_paths.isdisjoint(internal)
    assert retired_paths.isdisjoint(customer)
