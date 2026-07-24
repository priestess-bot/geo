from __future__ import annotations

import json
import subprocess
import sys
from time import sleep
from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from geo_api.app_factory import ApiSettings, REQUEST_ID_HEADER, create_api_app
from geo_api.foundation_services import FoundationServices, UnavailableFoundationServices
from geo_api import runtime_readiness
from geo_api.runtime_readiness import (
    DependencyProbe,
    ReadinessChecker,
    Surface,
    readiness_checker_from_environment,
)
from geo_api.workflow_c_runtime import WorkflowCApi


FORBIDDEN_PATH_TERMS = ("runtime", "p0a", "p0b", "fixture", "/au/", "-au/")
CONFIGURED_FOUNDATION_SERVICES = cast(FoundationServices, object())


class _DurableInternalRuntime:
    persistence = "durable"


DURABLE_INTERNAL_RUNTIME = _DurableInternalRuntime()


def _passing_readiness(surface: Surface) -> ReadinessChecker:
    if surface == "customer":
        return ReadinessChecker(
            surface="customer",
            probes=(DependencyProbe("postgres", lambda: None),),
        )
    return ReadinessChecker(
        surface="internal",
        probes=(
            DependencyProbe("postgres", lambda: None),
            DependencyProbe("valkey", lambda: None),
            DependencyProbe("object_store", lambda: None),
        ),
    )


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
        "/v1/auth/invitations/preflight",
        "/v1/projects",
    }
    assert shared <= internal_paths
    assert shared <= customer_paths
    assert {"/v1/jobs", "/v1/jobs/{job_id}"} <= internal_paths
    assert "/v1/jobs" not in customer_paths
    assert "/v1/jobs/{job_id}" not in customer_paths
    assert "/v1/auth/invitations/redeem" not in internal_paths
    assert "/v1/auth/invitations/redeem" in customer_paths
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
    app = create_api_app(surface="customer", services=UnavailableFoundationServices())
    with TestClient(app) as client:
        response = client.get("/v1/projects", headers={REQUEST_ID_HEADER: "request-123"})

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers[REQUEST_ID_HEADER] == "request-123"
    assert response.json() == {
        "type": "urn:geo:problem:service-unavailable",
        "title": "Service Unavailable",
        "status": 503,
        "detail": "The access application service is not configured.",
        "instance": "/v1/projects",
        "request_id": "request-123",
    }


def test_readiness_reports_missing_postgres_configuration() -> None:
    readiness = readiness_checker_from_environment(surface="customer", environment={})
    app = create_api_app(
        surface="customer",
        services=UnavailableFoundationServices(),
        readiness_service=readiness,
    )
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["type"] == "urn:geo:problem:not-ready"
    assert response.headers["X-GEO-Readiness-Codes"] == "postgres_not_configured"


def test_readiness_fails_closed_when_access_configuration_is_missing() -> None:
    calls: list[str] = []
    readiness = ReadinessChecker(
        surface="customer",
        probes=(DependencyProbe("postgres", lambda: calls.append("postgres")),),
    )
    app = create_api_app(
        surface="customer",
        services=UnavailableFoundationServices(),
        readiness_service=readiness,
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert calls == ["postgres"]
    assert response.status_code == 503
    assert response.json()["type"] == "urn:geo:problem:not-ready"
    assert response.headers["X-GEO-Readiness-Codes"] == "access_configuration_unavailable"


@pytest.mark.parametrize("surface", ["customer", "internal"])
@pytest.mark.parametrize(
    ("token_secret", "sensitive_value"),
    [
        (None, ""),
        ("short-secret-must-not-leak", "short-secret-must-not-leak"),
    ],
)
def test_readiness_rejects_missing_or_short_access_token_secret_without_leaking_it(
    monkeypatch: pytest.MonkeyPatch,
    surface: Surface,
    token_secret: str | None,
    sensitive_value: str,
) -> None:
    monkeypatch.delenv("GEO_DATABASE_URL_FILE", raising=False)
    monkeypatch.delenv("GEO_AUTH_TOKEN_SECRET_FILE", raising=False)
    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://private.invalid/geo")
    monkeypatch.setenv(
        "GEO_AUTH_MODE", "session" if surface == "customer" else "development"
    )
    monkeypatch.setenv("GEO_DEPLOYMENT_ENVIRONMENT", "development")
    if token_secret is None:
        monkeypatch.delenv("GEO_AUTH_TOKEN_SECRET", raising=False)
    else:
        monkeypatch.setenv("GEO_AUTH_TOKEN_SECRET", token_secret)
    readiness = _passing_readiness(surface)
    app = create_api_app(surface=surface, readiness_service=readiness)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.headers["X-GEO-Readiness-Codes"] == (
        "access_configuration_unavailable"
    )
    assert response.json()["type"] == "urn:geo:problem:not-ready"
    if sensitive_value:
        assert sensitive_value not in response.text
        assert sensitive_value not in repr(dict(response.headers))


@pytest.mark.parametrize("surface", ["customer", "internal"])
def test_readiness_accepts_valid_access_configuration(
    monkeypatch: pytest.MonkeyPatch, surface: Surface
) -> None:
    monkeypatch.delenv("GEO_DATABASE_URL_FILE", raising=False)
    monkeypatch.delenv("GEO_AUTH_TOKEN_SECRET_FILE", raising=False)
    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://private.invalid/geo")
    monkeypatch.setenv("GEO_AUTH_TOKEN_SECRET", "access-signing-secret-at-least-32-bytes")
    monkeypatch.setenv(
        "GEO_AUTH_MODE", "session" if surface == "customer" else "development"
    )
    monkeypatch.setenv("GEO_DEPLOYMENT_ENVIRONMENT", "development")
    app = create_api_app(
        surface=surface,
        readiness_service=_passing_readiness(surface),
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.parametrize(
    ("audience", "expected_status"),
    [("", 503), ("geo-admin", 200)],
)
def test_internal_readiness_statically_validates_oidc_configuration_without_remote_calls(
    monkeypatch: pytest.MonkeyPatch,
    audience: str,
    expected_status: int,
) -> None:
    monkeypatch.delenv("GEO_DATABASE_URL_FILE", raising=False)
    monkeypatch.delenv("GEO_AUTH_TOKEN_SECRET_FILE", raising=False)
    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://private.invalid/geo")
    monkeypatch.setenv("GEO_AUTH_TOKEN_SECRET", "access-signing-secret-at-least-32-bytes")
    monkeypatch.setenv("GEO_AUTH_MODE", "oidc")
    monkeypatch.setenv("GEO_DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "GEO_OIDC_DISCOVERY_URL",
        "https://must-not-be-contacted.invalid/.well-known/openid-configuration",
    )
    monkeypatch.setenv("GEO_JWT_ISSUER", "https://identity.example.com/")
    monkeypatch.setenv("GEO_JWT_AUDIENCE", audience)
    app = create_api_app(
        surface="internal",
        readiness_service=_passing_readiness("internal"),
        prompt_program_application=DURABLE_INTERNAL_RUNTIME,
        recommendation_api=DURABLE_INTERNAL_RUNTIME,
        secret_store_application=DURABLE_INTERNAL_RUNTIME,
        synthetic_lab_api=DURABLE_INTERNAL_RUNTIME,
        workflow_c_api=cast(WorkflowCApi, DURABLE_INTERNAL_RUNTIME),
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == expected_status
    if expected_status == 503:
        assert response.headers["X-GEO-Readiness-Codes"] == (
            "access_configuration_unavailable"
        )
    assert "must-not-be-contacted.invalid" not in response.text


def test_dependency_failure_remains_authoritative_when_access_configuration_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_postgres() -> None:
        raise RuntimeError("database-secret-must-not-leak")

    sensitive_value = "short-secret-must-not-leak"
    monkeypatch.setenv("GEO_DATABASE_URL", "postgresql://private.invalid/geo")
    monkeypatch.setenv("GEO_AUTH_TOKEN_SECRET", sensitive_value)
    readiness = ReadinessChecker(
        surface="customer",
        probes=(
            DependencyProbe("postgres", fail_postgres),
        ),
    )
    app = create_api_app(surface="customer", readiness_service=readiness)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.headers["X-GEO-Readiness-Codes"] == "postgres_unavailable"
    rendered = response.text + repr(dict(response.headers))
    assert sensitive_value not in rendered
    assert "database-secret-must-not-leak" not in rendered


def test_health_is_dependency_free_even_when_readiness_is_unavailable() -> None:
    calls: list[str] = []

    def fail_postgres() -> None:
        calls.append("postgres")
        raise RuntimeError("postgresql://user:secret@private.invalid/geo")

    readiness = ReadinessChecker(
        surface="customer",
        probes=(DependencyProbe("postgres", fail_postgres),),
    )
    app = create_api_app(surface="customer", readiness_service=readiness)
    with TestClient(app) as client:
        health = client.get("/health")
        assert calls == []
        unavailable = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert calls == ["postgres"]
    assert unavailable.status_code == 503
    assert unavailable.headers["X-GEO-Readiness-Codes"] == "postgres_unavailable"
    assert "secret" not in unavailable.text
    assert "private.invalid" not in unavailable.text


def test_readiness_surface_matrix_and_request_scoped_probes() -> None:
    calls: list[str] = []

    def probe(name: str) -> None:
        calls.append(name)

    customer_readiness = ReadinessChecker(
        surface="customer",
        probes=(DependencyProbe("postgres", lambda: probe("customer-postgres")),),
    )
    internal_readiness = ReadinessChecker(
        surface="internal",
        probes=(
            DependencyProbe("postgres", lambda: probe("internal-postgres")),
            DependencyProbe("valkey", lambda: probe("internal-valkey")),
            DependencyProbe("object_store", lambda: probe("internal-object-store")),
        ),
    )
    customer = create_api_app(
        surface="customer",
        services=CONFIGURED_FOUNDATION_SERVICES,
        readiness_service=customer_readiness,
    )
    internal = create_api_app(
        surface="internal",
        services=CONFIGURED_FOUNDATION_SERVICES,
        readiness_service=internal_readiness,
    )

    with TestClient(customer) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/ready").status_code == 200
    with TestClient(internal) as client:
        assert client.get("/ready").status_code == 200

    assert calls.count("customer-postgres") == 2
    assert calls.count("internal-postgres") == 1
    assert calls.count("internal-valkey") == 1
    assert calls.count("internal-object-store") == 1


def test_readiness_timeout_is_bounded_and_reported_without_exception_text() -> None:
    def slow_probe() -> None:
        sleep(0.05)
        raise RuntimeError("must-not-leak")

    readiness = ReadinessChecker(
        surface="customer",
        probes=(DependencyProbe("postgres", slow_probe),),
        dependency_timeout_seconds=0.01,
        total_timeout_seconds=0.03,
    )
    app = create_api_app(surface="customer", readiness_service=readiness)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.headers["X-GEO-Readiness-Codes"] == "postgres_timeout"
    assert "must-not-leak" not in response.text


def test_environment_readiness_only_requires_dependencies_for_its_surface() -> None:
    customer = readiness_checker_from_environment(surface="customer", environment={})
    internal = readiness_checker_from_environment(surface="internal", environment={})
    customer_app = create_api_app(surface="customer", readiness_service=customer)
    internal_app = create_api_app(surface="internal", readiness_service=internal)

    with TestClient(customer_app) as client:
        customer_response = client.get("/ready")
    with TestClient(internal_app) as client:
        internal_response = client.get("/ready")

    assert customer_response.headers["X-GEO-Readiness-Codes"] == "postgres_not_configured"
    assert internal_response.headers["X-GEO-Readiness-Codes"] == (
        "postgres_not_configured,valkey_not_configured,object_store_not_configured"
    )
    for excluded in ("oidc", "model", "url"):
        assert excluded not in customer_response.text.lower()
        assert excluded not in internal_response.text.lower()


def test_environment_readiness_parses_bounded_timeouts_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[float] = []

    def postgres_probe(environment: object, timeout_seconds: float) -> object:
        del environment
        captured.append(timeout_seconds)
        return lambda: None

    monkeypatch.setattr(runtime_readiness, "_postgres_probe", postgres_probe)
    checker = readiness_checker_from_environment(
        surface="customer",
        environment={
            "GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS": "3",
            "GEO_READINESS_TOTAL_TIMEOUT_SECONDS": "7",
        },
    )
    app = create_api_app(
        surface="customer",
        services=CONFIGURED_FOUNDATION_SERVICES,
        readiness_service=checker,
    )
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200

    assert captured == [3.0]

    sensitive_value = "not-a-number-do-not-echo"
    with pytest.raises(ValueError) as invalid:
        readiness_checker_from_environment(
            surface="customer",
            environment={"GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS": sensitive_value},
        )
    assert sensitive_value not in str(invalid.value)

    with pytest.raises(ValueError, match="total readiness timeout must exceed"):
        readiness_checker_from_environment(
            surface="customer",
            environment={
                "GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS": "3",
                "GEO_READINESS_TOTAL_TIMEOUT_SECONDS": "3",
            },
        )


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
    assert error_content["application/problem+json"]["schema"]["$ref"].endswith("/ProblemDetails")


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


def test_internal_job_not_found_uses_problem_contract_with_generated_request_id() -> None:
    class MissingJobServices:
        def get_job(self, authentication: object, *, job_id: object) -> None:
            del authentication, job_id
            return None

    app = create_api_app(surface="internal", services=MissingJobServices())  # type: ignore[arg-type]
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
            "oidc.py",
            "problems.py",
            "runtime_readiness.py",
            "stable_routes.py",
        )
    )
    assert "from scripts" not in sources
    assert "import scripts" not in sources
    assert "from workers" not in sources
    assert "import workers" not in sources
    assert "geo_api.main" not in sources

    access_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("packages/geo_core/geo_core/access").glob("*.py")
    )
    for forbidden in ("geo_core.repository", "from scripts", "import scripts", "workers"):
        assert forbidden not in access_sources


def test_access_submodule_import_does_not_load_legacy_runtime() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import geo_core.access.models; "
                "assert 'geo_core.repository' not in sys.modules; "
                "assert 'geo_core.runtime' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_docker_defaults_to_internal_application() -> None:
    from pathlib import Path

    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")
    assert '"geo_api.internal_app:app"' in dockerfile
    assert '"geo_api.main:app"' not in dockerfile
