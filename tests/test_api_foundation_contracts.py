from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from geo_api.app_factory import ApiSettings, REQUEST_ID_HEADER, create_api_app


FORBIDDEN_PATH_TERMS = ("runtime", "p0a", "p0b", "fixture", "/au/", "-au/")


def _paths(app: object) -> set[str]:
    return set(app.openapi()["paths"])


def test_internal_and_customer_openapi_are_isolated_and_stable() -> None:
    internal = create_api_app(surface="internal", settings=ApiSettings(dev_tools_enabled=False))
    customer = create_api_app(surface="customer", settings=ApiSettings(dev_tools_enabled=False))
    internal_paths = _paths(internal)
    customer_paths = _paths(customer)

    shared = {
        "/health",
        "/ready",
        "/v1/auth/me",
        "/v1/auth/logout",
        "/v1/projects",
        "/v1/jobs",
        "/v1/jobs/{job_id}",
    }
    assert shared <= internal_paths
    assert shared <= customer_paths
    assert "/v1/engineering/status" in internal_paths
    assert "/v1/engineering/work-items" in internal_paths
    assert "/v1/engineering/reconciliations" in internal_paths
    assert "/v1/engineering/health-probes" in internal_paths
    assert "/v1/engineering/events" in internal_paths
    assert "/v1/integrations/github/events" in internal_paths
    assert not any(path.startswith("/v1/engineering") for path in customer_paths)
    assert not any(path.startswith("/v1/dev-tools") for path in customer_paths)

    for path in internal_paths | customer_paths:
        normalized = path.lower()
        assert not any(term in normalized for term in FORBIDDEN_PATH_TERMS), path


def test_problem_details_and_request_id_are_consistent() -> None:
    app = create_api_app(surface="customer")
    with TestClient(app) as client:
        response = client.get("/v1/projects", headers={REQUEST_ID_HEADER: "request-123"})

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers[REQUEST_ID_HEADER] == "request-123"
    assert response.json() == {
        "type": "urn:geo:problem:service-unavailable",
        "title": "Service Unavailable",
        "status": 503,
        "detail": "The application service for this operation is not connected.",
        "instance": "/v1/projects",
        "request_id": "request-123",
    }


def test_validation_errors_use_problem_details() -> None:
    app = create_api_app(surface="customer")
    with TestClient(app) as client:
        response = client.get("/v1/projects?limit=0")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:geo:problem:validation-error"
    assert response.json()["errors"][0]["location"] == ["query", "limit"]


def test_dev_tools_registration_is_internal_and_fail_closed() -> None:
    disabled = create_api_app(surface="internal", settings=ApiSettings(dev_tools_enabled=False))
    enabled = create_api_app(surface="internal", settings=ApiSettings(dev_tools_enabled=True))
    customer = create_api_app(surface="customer", settings=ApiSettings(dev_tools_enabled=True))

    with TestClient(disabled) as client:
        response = client.get("/v1/dev-tools/status")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
    assert "/v1/dev-tools/status" in _paths(enabled)
    assert "/v1/dev-tools/status" not in _paths(customer)


def test_job_accepted_contract_is_typed_in_internal_openapi() -> None:
    app = create_api_app(surface="internal")
    document = app.openapi()
    operation = document["paths"]["/v1/engineering/reconciliations"]["post"]
    response_schema = operation["responses"]["202"]["content"]["application/json"]["schema"]

    assert response_schema["$ref"].endswith("/JobAccepted")
    job_schema = document["components"]["schemas"]["JobAccepted"]
    assert set(job_schema["required"]) == {"job_id", "status", "status_url"}
    assert json.dumps(document).count("JobAccepted") >= 2

    error_content = document["paths"]["/v1/projects"]["get"]["responses"]["503"]["content"]
    assert "application/problem+json" in error_content
    assert error_content["application/problem+json"]["schema"]["$ref"].endswith(
        "/ProblemDetails"
    )


def test_engineering_work_items_default_to_unknown_empty_projection() -> None:
    app = create_api_app(surface="internal")
    with TestClient(app) as client:
        response = client.get("/v1/engineering/work-items")

    assert response.status_code == 200
    assert response.json() == {"items": [], "observed_at": None}
    schema = app.openapi()["components"]["schemas"]["EngineeringWorkItem"]
    assert set(schema["required"]) == {
        "id",
        "title",
        "axes",
        "blockers",
        "observed_at",
        "freshness",
    }


def test_job_not_found_uses_problem_contract_with_generated_request_id() -> None:
    class MissingJobServices:
        def get_job(self, *, job_id: object) -> None:
            return None

    app = create_api_app(surface="customer", services=MissingJobServices())  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.get(f"/v1/jobs/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["type"] == "urn:geo:problem:job-not-found"
    assert response.headers[REQUEST_ID_HEADER] == response.json()["request_id"]


def test_new_api_modules_do_not_import_scripts_workers_or_legacy_main() -> None:
    from pathlib import Path

    api_root = Path("apps/api/geo_api")
    sources = "\n".join(
        (api_root / name).read_text(encoding="utf-8")
        for name in (
            "app_factory.py",
            "contracts.py",
            "customer_app.py",
            "foundation_services.py",
            "internal_app.py",
            "problems.py",
            "stable_routes.py",
        )
    )
    assert "from scripts" not in sources
    assert "import scripts" not in sources
    assert "from workers" not in sources
    assert "import workers" not in sources
    assert "geo_api.main" not in sources


def test_docker_defaults_to_internal_application() -> None:
    from pathlib import Path

    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")
    assert '"geo_api.internal_app:app"' in dockerfile
    assert '"geo_api.main:app"' not in dockerfile
