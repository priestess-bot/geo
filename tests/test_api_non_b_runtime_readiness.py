from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast

from fastapi.testclient import TestClient
import pytest

from geo_api import app_factory
from geo_api.app_factory import ApiSettings, create_api_app
from geo_api.foundation_services import FoundationServices
from geo_api.non_b_runtime_readiness import (
    NonBRuntimeBindings,
    ProductionInternalRuntimeReadiness,
    RuntimeBinding,
    bind_runtime,
)
from geo_api.runtime_readiness import ReadinessFailure, ReadinessResult
from geo_api.workflow_c_runtime import WorkflowCApi


EXPECTED_RUNTIME_CODES = (
    "prompt_program_runtime_not_durable",
    "secret_store_runtime_not_durable",
    "synthetic_lab_runtime_not_durable",
    "workflow_c_runtime_not_durable",
    "recommendation_runtime_not_durable",
    "model_gateway_runtime_not_durable",
)
CONFIGURED_SERVICES = cast(FoundationServices, object())


class _Ready:
    async def check(self) -> ReadinessResult:
        return ReadinessResult()


class _PostgresUnavailable:
    async def check(self) -> ReadinessResult:
        return ReadinessResult(failures=(ReadinessFailure("postgres", "postgres_unavailable"),))


@dataclass(frozen=True)
class _TaggedRuntime:
    persistence: str


class _UntrustedRuntime:
    @property
    def persistence(self) -> str:
        raise RuntimeError("credential-and-classification-detail-must-not-leak")


def _durable_bindings() -> NonBRuntimeBindings:
    durable = RuntimeBinding[object](
        value=_TaggedRuntime(persistence="durable"),
        persistence="durable",
    )
    return NonBRuntimeBindings(
        prompt_program=durable,
        secret_store=durable,
        synthetic_lab=durable,
        workflow_c=durable,
        recommendation=durable,
        model_gateway=durable,
    )


def _disable_default_non_b_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_factory, "build_prompt_program_application", lambda: None)
    monkeypatch.setattr(app_factory, "build_secret_store_application", lambda: None)
    monkeypatch.setattr(app_factory, "build_synthetic_lab_api", lambda: None)
    monkeypatch.setattr(app_factory, "build_recommendation_api", lambda: None)
    monkeypatch.setattr(app_factory, "build_model_gateway_runtime_api", lambda: None)


def test_runtime_binding_trusts_only_builder_provenance_or_explicit_durable_marker() -> None:
    built = object()

    assert bind_runtime(injected=None, durable_builder=lambda: built) == RuntimeBinding(
        value=built,
        persistence="durable",
    )
    assert bind_runtime(injected=None) == RuntimeBinding(value=None, persistence="absent")
    assert bind_runtime(injected=object()).persistence == "unknown"
    assert (
        bind_runtime(injected=_TaggedRuntime(persistence="memory_test_only")).persistence
        == "memory_test_only"
    )
    assert bind_runtime(injected=_TaggedRuntime(persistence="durable")).persistence == "durable"
    assert bind_runtime(injected=_UntrustedRuntime()).persistence == "unknown"


def test_runtime_readiness_preserves_base_failure_before_runtime_failures() -> None:
    readiness = ProductionInternalRuntimeReadiness(
        _PostgresUnavailable(),
        surface="internal",
        deployment_environment="production",
        bindings=NonBRuntimeBindings.absent(),
    )

    result = asyncio.run(readiness.check())

    assert tuple(failure.code for failure in result.failures) == ("postgres_unavailable",)


def test_runtime_readiness_accepts_a_complete_explicitly_durable_set() -> None:
    readiness = ProductionInternalRuntimeReadiness(
        _Ready(),
        surface="internal",
        deployment_environment=" PRODUCTION ",
        bindings=_durable_bindings(),
    )

    assert asyncio.run(readiness.check()).ready


@pytest.mark.parametrize("deployment_environment", ("production", "staging"))
def test_deployed_internal_ready_reports_all_missing_runtimes_in_stable_order(
    monkeypatch: pytest.MonkeyPatch,
    deployment_environment: str,
) -> None:
    _disable_default_non_b_builders(monkeypatch)
    app = create_api_app(
        surface="internal",
        settings=ApiSettings(deployment_environment=deployment_environment),
        services=CONFIGURED_SERVICES,
        readiness_service=_Ready(),
        prompt_program_application=_UntrustedRuntime(),
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.headers["X-GEO-Readiness-Codes"] == ",".join(EXPECTED_RUNTIME_CODES)
    rendered = response.text + repr(dict(response.headers))
    assert "credential" not in rendered
    assert "_UntrustedRuntime" not in rendered


@pytest.mark.parametrize("deployment_environment", ("production", "staging"))
def test_deployed_internal_ready_accepts_explicit_durable_injections(
    deployment_environment: str,
) -> None:
    durable = _TaggedRuntime(persistence="durable")
    app = create_api_app(
        surface="internal",
        settings=ApiSettings(deployment_environment=deployment_environment),
        services=CONFIGURED_SERVICES,
        readiness_service=_Ready(),
        prompt_program_application=durable,
        secret_store_application=durable,
        synthetic_lab_api=durable,
        recommendation_api=durable,
        workflow_c_api=cast(WorkflowCApi, durable),
        model_gateway_runtime_api=durable,
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.parametrize(
    ("surface", "deployment_environment"),
    (("customer", "production"), ("internal", "development"), ("internal", "test")),
)
def test_non_production_internal_surfaces_do_not_require_non_b_runtimes(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    deployment_environment: str,
) -> None:
    def forbidden_builder() -> None:
        if surface == "customer":
            raise AssertionError("Customer composition must not invoke Internal runtime builders")

    if surface == "customer":
        monkeypatch.setattr(app_factory, "build_prompt_program_application", forbidden_builder)
        monkeypatch.setattr(app_factory, "build_secret_store_application", forbidden_builder)
        monkeypatch.setattr(app_factory, "build_synthetic_lab_api", forbidden_builder)
        monkeypatch.setattr(app_factory, "build_recommendation_api", forbidden_builder)
        monkeypatch.setattr(app_factory, "build_model_gateway_runtime_api", forbidden_builder)
    else:
        _disable_default_non_b_builders(monkeypatch)
    app = create_api_app(
        surface=cast(app_factory.Surface, surface),
        settings=ApiSettings(deployment_environment=deployment_environment),
        services=CONFIGURED_SERVICES,
        readiness_service=_Ready(),
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
