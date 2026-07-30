"""Fixtures shared by the Recommendation PostgreSQL lifecycle integration test."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

import psycopg

from geo_core.access.models import AccessPrincipal
from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.runtime_catalog import NewModelCallJobSelection
from geo_core.prompts.application import PromptProgramApplication
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.compiler_versions import BOOTSTRAP_COMPILER_VERSION
from geo_core.prompts.postgres import prompt_program_uow_factory
from geo_core.prompts.program import ProgramKind
from geo_core.secrets import SecretVersionHandle
from tests.integration.model_gateway_postgres_fixtures import releases


RECOMMENDATION_RUNTIME_OPTION_ID = UUID("90000000-0000-4000-8000-000000000001")


class RecommendationRuntimeCatalog:
    """Deterministic catalog fixture; provider execution is outside this DB contract."""

    def __init__(self, selection: NewModelCallJobSelection) -> None:
        self._selection = selection

    def resolve_approved_runtime(
        self,
        *,
        project_id: UUID,
        runtime_selection_id: UUID,
        required_purpose: str,
        search_mode: str | None,
    ) -> NewModelCallJobSelection:
        assert project_id == self._selection.provider_secret_handle.project_id
        assert runtime_selection_id == RECOMMENDATION_RUNTIME_OPTION_ID
        assert required_purpose == "recommendations.recommendation"
        assert search_mode is None
        return self._selection


def recommendation_runtime_selection(project_id: UUID) -> NewModelCallJobSelection:
    adapter, model, route = releases()
    return NewModelCallJobSelection(
        runtime_manifest_id=UUID("90000000-0000-4000-8000-000000000002"),
        runtime_manifest_hash=hash_text("recommendation-runtime-manifest"),
        runtime_option_id=RECOMMENDATION_RUNTIME_OPTION_ID,
        runtime_option_hash=hash_text("recommendation-runtime-option"),
        route=route,
        configured_model=model.configured_model,
        policy=ModelPolicy(
            allowed_providers=frozenset({"openai"}),
            allowed_adapter_release_ids=frozenset({route.adapter_release_id}),
        ),
        provider_secret_handle=SecretVersionHandle(
            reference_id=UUID("90000000-0000-4000-8000-000000000003"),
            project_id=project_id,
            purpose="model_provider.openai",
            version=1,
        ),
        adapter_release=adapter,
        allowed_purposes=frozenset({"recommendations.recommendation"}),
        allowed_search_modes=frozenset({None}),
        provider_config_hash=hash_text("recommendation-provider-config"),
    )


def seed_frozen_recommendation_prompt(
    *,
    app_url: str,
    seeded: dict[str, UUID],
    owner: AccessPrincipal,
    reviewer: AccessPrincipal,
) -> UUID:
    factory = prompt_program_uow_factory(lambda: psycopg.connect(app_url))
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)

    def command(operation):
        with factory(seeded["project"]) as unit_of_work:
            result = operation(
                PromptProgramApplication(
                    unit_of_work.prompts,
                    test_evidence_verifier=_PromptEvidenceVerifier(),
                )
            )
            unit_of_work.commit()
            return result

    created = command(
        lambda app: app.create_program(
            owner,
            project_id=seeded["project"],
            program_kind=spec.program_kind,
            purpose=spec.purpose,
            system_template=spec.system_template,
            user_template=spec.user_template,
            schemas=spec.schemas,
            model_policy=spec.model_policy,
            test_set_id=spec.test_set_id,
            test_set_version=1,
            test_set_hash=spec.test_set_hash,
            compiler_version=BOOTSTRAP_COMPILER_VERSION,
            expected_version=0,
            idempotency_key="recommendation-generation-prompt:create",
        )
    )
    command(
        lambda app: app.record_test(
            owner,
            project_id=seeded["project"],
            release_id=created.value.release.id,
            output_artifact_ref="s3://prompt-tests/recommendation-generation.json",
            output_hash=hash_text("recommendation-generation-prompt-output"),
            expected_version=1,
            idempotency_key="recommendation-generation-prompt:test",
        )
    )
    command(
        lambda app: app.approve_release(
            reviewer,
            project_id=seeded["project"],
            release_id=created.value.release.id,
            expected_version=2,
            idempotency_key="recommendation-generation-prompt:approve",
        )
    )
    command(
        lambda app: app.freeze_release(
            reviewer,
            project_id=seeded["project"],
            release_id=created.value.release.id,
            expected_version=3,
            idempotency_key="recommendation-generation-prompt:freeze",
        )
    )
    bound = command(
        lambda app: app.bind_release(
            reviewer,
            project_id=seeded["project"],
            release_id=created.value.release.id,
            purpose="recommendations.recommendation",
            expected_version=0,
            idempotency_key="recommendation-generation-prompt:bind",
        )
    )
    return bound.value.binding.id


class UnusedRecommendationDependency:
    """Fail if an insufficient-evidence parent ever enters a model-call path."""

    def __init__(self, label: str) -> None:
        self._label = label

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unused {self._label} accessed through {name}")


class _PromptEvidenceVerifier:
    def verify(self, *, release, evidence) -> None:
        assert evidence.project_id == release.project_id
        assert evidence.release_id == release.id
        assert evidence.release_hash == release.release_hash
        assert evidence.output_artifact_ref.startswith("s3://prompt-tests/")


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "RecommendationRuntimeCatalog",
    "RECOMMENDATION_RUNTIME_OPTION_ID",
    "UnusedRecommendationDependency",
    "hash_text",
    "recommendation_runtime_selection",
    "seed_frozen_recommendation_prompt",
]
