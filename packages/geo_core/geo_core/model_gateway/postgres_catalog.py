"""Immutable release, project-policy, and Job-admission catalog for Model Gateway."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.ports import (
    ModelCallJobAdmission,
    ModelCallPersistenceError,
    PromptReleaseAdmission,
)
from geo_core.model_gateway.postgres_rows import (
    adapter_release_from_row,
    model_release_from_row,
    project_policy_from_row,
)
from geo_core.model_gateway.postgres_uow import PostgresModelCallUnitOfWorkFactory
from geo_core.model_gateway.releases import (
    AdapterRelease,
    ModelRelease,
    ModelReleaseRegistry,
)
from geo_core.model_gateway.runtime_errors import ModelCallJobAdmissionNotFound
from geo_core.project_scope import set_project_scope
from geo_core.secrets.models import SecretVersionHandle


class PostgresModelGatewayPersistence:
    """Infrastructure-only builder surface; provider clients remain outside this class."""

    def __init__(self, database_url: str, *, connect_timeout: int = 5) -> None:
        normalized = database_url.strip()
        if not normalized:
            raise ValueError("database_url is required")
        self._database_url = normalized
        self._connect_timeout = connect_timeout
        self.uow_factory = PostgresModelCallUnitOfWorkFactory(
            normalized, connect_timeout=connect_timeout
        )

    def register_adapter_release(
        self,
        release: AdapterRelease,
        *,
        registered_by: UUID,
        registered_at: datetime,
    ) -> AdapterRelease:
        with self._connect() as connection:
            existing = connection.execute(
                """SELECT * FROM model_gateway_adapter_releases
                   WHERE provider = %s AND adapter_release_id = %s""",
                (release.provider, release.adapter_release_id),
            ).fetchone()
            if existing is not None:
                loaded = adapter_release_from_row(existing)
                if loaded != release:
                    raise ModelCallPersistenceError(
                        "Model Gateway Adapter Release identity already has different content"
                    )
                return loaded
            capabilities = release.capabilities
            policy = release.data_policy
            try:
                connection.execute(
                    """INSERT INTO model_gateway_adapter_releases(
                           provider, adapter_release_id, release_hash,
                           interface_contract_version, expected_capture_method,
                           external_training_allowed,
                           structured_output, capability_data_retention_days,
                           capability_policy_reference, supports_seed, supports_tools,
                           supports_search, supports_citations, supports_idempotency,
                           supports_structured_output_with_tools,
                           capability_verification, capability_evidence_reference,
                           capability_evidence_sha256,
                           data_storage_decision, data_cache_decision,
                           data_display_decision, data_redistribution_decision,
                           data_policy_retention_days, terms_reference, terms_sha256,
                           data_policy_hash,
                           state, registered_by, registered_at
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        release.provider,
                        release.adapter_release_id,
                        release.release_hash,
                        release.interface_contract_version,
                        release.expected_capture_method.value,
                        capabilities.external_training_allowed,
                        capabilities.structured_output,
                        capabilities.data_retention_days,
                        capabilities.policy_reference,
                        capabilities.supports_seed,
                        capabilities.supports_tools,
                        capabilities.supports_search,
                        capabilities.supports_citations,
                        capabilities.supports_idempotency,
                        capabilities.supports_structured_output_with_tools,
                        capabilities.verification.value,
                        release.capability_evidence_reference,
                        release.capability_evidence_sha256,
                        policy.storage.value,
                        policy.cache.value,
                        policy.display.value,
                        policy.redistribution.value,
                        policy.retention_days,
                        policy.terms_reference,
                        policy.terms_sha256,
                        policy.data_policy_hash,
                        release.state.value,
                        registered_by,
                        registered_at,
                    ),
                )
            except psycopg.Error:
                raise ModelCallPersistenceError(
                    "PostgreSQL rejected the Model Gateway Adapter Release"
                ) from None
        return release

    def register_model_release(
        self,
        release: ModelRelease,
        *,
        registered_by: UUID,
        registered_at: datetime,
    ) -> ModelRelease:
        with self._connect() as connection:
            adapter = connection.execute(
                """SELECT release_hash FROM model_gateway_adapter_releases
                   WHERE provider = %s AND adapter_release_id = %s""",
                (release.provider, release.adapter_release_id),
            ).fetchone()
            if adapter is None:
                raise ModelCallPersistenceError(
                    "Model Gateway Model Release references an unknown Adapter Release"
                )
            existing = connection.execute(
                """SELECT * FROM model_gateway_model_releases
                   WHERE provider = %s AND adapter_release_id = %s
                     AND model_release_id = %s""",
                (
                    release.provider,
                    release.adapter_release_id,
                    release.model_release_id,
                ),
            ).fetchone()
            if existing is not None:
                loaded = model_release_from_row(existing)
                if loaded != release:
                    raise ModelCallPersistenceError(
                        "Model Gateway Model Release identity already has different content"
                    )
                return loaded
            try:
                connection.execute(
                    """INSERT INTO model_gateway_model_releases(
                           provider, adapter_release_id, adapter_release_hash,
                           model_release_id, release_hash, configured_model, state,
                           reported_model_policy, allowed_reported_models,
                           registered_by, registered_at
                       ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        release.provider,
                        release.adapter_release_id,
                        adapter["release_hash"],
                        release.model_release_id,
                        release.release_hash,
                        release.configured_model,
                        release.state.value,
                        release.reported_model_policy.value,
                        list(release.allowed_reported_models),
                        registered_by,
                        registered_at,
                    ),
                )
            except psycopg.Error:
                raise ModelCallPersistenceError(
                    "PostgreSQL rejected the Model Gateway Model Release"
                ) from None
        return release

    def register_project_policy(
        self,
        *,
        project_id: UUID,
        policy: ModelPolicy,
        version: int,
        previous_version_id: UUID | None,
        created_by: UUID,
        created_at: datetime,
    ) -> ModelPolicy:
        if (
            not policy.versioned
            or policy.policy_version_id is None
            or policy.policy_version_hash is None
            or policy.allowed_providers is None
            or policy.allowed_adapter_release_ids is None
            or policy.maximum_paid_calls is None
            or policy.maximum_concurrent_calls is None
        ):
            raise ModelCallPersistenceError(
                "PostgreSQL requires an explicit versioned Model Gateway project policy"
            )
        with self._project_connection(project_id) as connection:
            existing = connection.execute(
                """SELECT * FROM model_gateway_project_policy_versions
                   WHERE project_id = %s AND id = %s""",
                (project_id, policy.policy_version_id),
            ).fetchone()
            if existing is not None:
                loaded = project_policy_from_row(existing)
                if (
                    loaded != policy
                    or existing["version"] != version
                    or existing["previous_version_id"] != previous_version_id
                ):
                    raise ModelCallPersistenceError(
                        "Model Gateway project policy identity already has different content"
                    )
                return loaded
            try:
                connection.execute(
                    """INSERT INTO model_gateway_project_policy_versions(
                           id, project_id, version, previous_version_id, policy_hash,
                           allowed_providers, allowed_adapter_release_ids,
                           external_training_allowed, structured_output_required,
                           maximum_paid_calls_default, maximum_concurrent_calls,
                           created_by, created_at
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        policy.policy_version_id,
                        project_id,
                        version,
                        previous_version_id,
                        policy.policy_version_hash,
                        sorted(policy.allowed_providers),
                        sorted(policy.allowed_adapter_release_ids),
                        policy.external_training_allowed,
                        policy.structured_output_required,
                        policy.maximum_paid_calls,
                        policy.maximum_concurrent_calls,
                        created_by,
                        created_at,
                    ),
                )
            except psycopg.Error:
                raise ModelCallPersistenceError(
                    "PostgreSQL rejected the Model Gateway project policy"
                ) from None
        return policy

    def get_project_policy(
        self,
        *,
        project_id: UUID,
        policy_version_id: UUID,
        policy_version_hash: str,
    ) -> ModelPolicy:
        with self._project_connection(project_id) as connection:
            row = connection.execute(
                """SELECT * FROM model_gateway_project_policy_versions
                   WHERE project_id = %s AND id = %s AND policy_hash = %s""",
                (project_id, policy_version_id, policy_version_hash),
            ).fetchone()
        if row is None:
            raise ModelCallPersistenceError("exact Model Gateway project policy is unavailable")
        return project_policy_from_row(row)

    def load_release_registry(self) -> ModelReleaseRegistry:
        with self._connect() as connection:
            adapter_rows = connection.execute(
                """SELECT * FROM model_gateway_adapter_releases
                   ORDER BY provider, adapter_release_id"""
            ).fetchall()
            model_rows = connection.execute(
                """SELECT * FROM model_gateway_model_releases
                   ORDER BY provider, adapter_release_id, model_release_id"""
            ).fetchall()
        return ModelReleaseRegistry(
            adapter_releases=tuple(adapter_release_from_row(row) for row in adapter_rows),
            model_releases=tuple(model_release_from_row(row) for row in model_rows),
        )

    def load_job_admission(
        self,
        project_id: UUID,
        job_id: UUID,
    ) -> ModelCallJobAdmission:
        """Load one exact project-scoped admission for worker composition."""

        return self._read_job(project_id, job_id)

    def refresh_job_admission_lease(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        job_version: int,
        lease_token: UUID,
        fencing_generation: int,
    ) -> ModelCallJobAdmission:
        """Refresh only retry ownership after PostgreSQL proves the retry is eligible."""

        try:
            with self._project_connection(project_id) as connection:
                connection.execute(
                    """SELECT geo_refresh_model_gateway_job_admission_lease(
                           %s, %s, %s, %s, %s, clock_timestamp()
                       )""",
                    (
                        project_id,
                        job_id,
                        job_version,
                        lease_token,
                        fencing_generation,
                    ),
                )
        except psycopg.Error as exc:
            raise ModelCallPersistenceError(
                "PostgreSQL rejected the Model Gateway retry lease refresh"
            ) from exc
        return self._read_job(project_id, job_id)

    def require_active_provider_secret_handle(
        self,
        project_id: UUID,
        provider: str,
        reference_id: UUID,
    ) -> SecretVersionHandle:
        purpose = f"model_provider.{provider.strip()}"
        if not provider.strip():
            raise ModelCallPersistenceError("Model Gateway Provider Secret is unavailable")
        with self._project_connection(project_id) as connection:
            row = connection.execute(
                """SELECT reference.id AS reference_id, reference.project_id,
                          reference.purpose, version.version
                   FROM secret_references AS reference
                   JOIN secret_versions AS version
                     ON version.reference_id = reference.id
                    AND version.project_id = reference.project_id
                    AND version.purpose = reference.purpose
                    AND version.version = reference.current_version
                   WHERE reference.id = %s AND reference.project_id = %s
                     AND reference.purpose = %s AND version.status = 'active'""",
                (reference_id, project_id, purpose),
            ).fetchone()
        if row is None:
            raise ModelCallPersistenceError("Model Gateway Provider Secret is unavailable")
        return SecretVersionHandle(
            reference_id=row["reference_id"],
            project_id=row["project_id"],
            purpose=row["purpose"],
            version=row["version"],
        )

    def admit_job(
        self,
        job: ModelCallJobAdmission,
        *,
        prompt: PromptReleaseAdmission,
        admitted_by: UUID,
        admitted_at: datetime,
    ) -> ModelCallJobAdmission:
        if (
            prompt.project_id != job.project_id
            or prompt.admission_mode != job.admission_mode
            or prompt.binding_id != job.prompt_binding_id
            or prompt.state_id != job.prompt_state_id
            or prompt.state_version != job.prompt_state_version
            or prompt.release_id != job.prompt_release_id
            or prompt.release_hash != job.prompt_release_hash
            or prompt.purpose != job.purpose
            or prompt.output_schema_hash != job.output_schema_hash
            or prompt.application_output_schema_hash
            != job.application_output_schema_hash
            or prompt.test_set_hash != job.prompt_test_set_hash
            or not prompt.current
        ):
            raise ModelCallPersistenceError(
                "Model Gateway Job admission requires the exact frozen Prompt binding"
            )
        with self._project_connection(job.project_id) as connection:
            durable = connection.execute(
                """SELECT kind, status, lease_token, fencing_generation,
                          cancel_requested_at
                   FROM durable_jobs WHERE project_id = %s AND id = %s""",
                (job.project_id, job.job_id),
            ).fetchone()
            if (
                durable is None
                or durable["kind"] != job.job_kind
                or durable["status"] != job.status.value
                or durable["status"] != "running"
                or durable["lease_token"] != job.lease_token
                or durable["fencing_generation"] != job.fencing_generation
                or durable["cancel_requested_at"] is not None
            ):
                raise ModelCallPersistenceError(
                    "Model Gateway Job admission does not match the active Durable Job lease"
                )
            existing = connection.execute(
                """SELECT job_id FROM model_gateway_job_admissions
                   WHERE project_id = %s AND job_id = %s""",
                (job.project_id, job.job_id),
            ).fetchone()
            if existing is not None:
                loaded = self._read_job(job.project_id, job.job_id)
                if not _same_admission_contract(loaded, job):
                    raise ModelCallPersistenceError(
                        "Model Gateway Job admission already has different frozen content"
                    )
                return loaded
            route = job.route
            try:
                connection.execute(
                    """INSERT INTO model_gateway_job_admissions(
                           job_id, project_id, job_kind, job_version,
                           lease_token, fencing_generation,
                           runtime_manifest_id, runtime_manifest_hash,
                           runtime_option_id, runtime_option_hash, admission_mode,
                           policy_version_id, policy_version_hash, purpose, usage_audience,
                           provider, adapter_release_id, adapter_release_hash,
                           model_release_id, model_release_hash,
                           provider_secret_reference_id, provider_secret_version,
                           provider_secret_handle_hash,
                           prompt_binding_id, prompt_release_id, prompt_release_hash,
                           prompt_frozen_state_id, prompt_state_version,
                           prompt_test_set_hash, prompt_bundle_hash, output_schema_hash,
                           application_output_schema_hash,
                           raw_artifact_policy_hash, raw_artifact_storage_decision,
                           raw_artifact_cache_decision, raw_artifact_display_decision,
                           raw_artifact_redistribution_decision, raw_artifact_retention_days,
                           maximum_paid_calls, maximum_concurrent_calls,
                           paid_calls, reserved_calls, budget_version, next_attempt_number,
                           admitted_by, admitted_at
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        job.job_id,
                        job.project_id,
                        job.job_kind,
                        job.job_version,
                        job.lease_token,
                        job.fencing_generation,
                        job.runtime_manifest_id,
                        job.runtime_manifest_hash,
                        job.runtime_option_id,
                        job.runtime_option_hash,
                        job.admission_mode.value,
                        job.policy_version_id,
                        job.policy_version_hash,
                        job.purpose,
                        job.usage_audience.value,
                        route.provider,
                        route.adapter_release_id,
                        route.adapter_release_hash,
                        route.model_release_id,
                        route.model_release_hash,
                        job.provider_secret_handle.reference_id,
                        job.provider_secret_handle.version,
                        job.provider_secret_handle_hash,
                        job.prompt_binding_id,
                        job.prompt_release_id,
                        job.prompt_release_hash,
                        prompt.state_id,
                        prompt.state_version,
                        prompt.test_set_hash,
                        job.prompt_bundle_hash,
                        job.output_schema_hash,
                        job.application_output_schema_hash,
                        job.raw_artifact_policy_hash,
                        job.raw_artifact_storage_decision,
                        job.raw_artifact_cache_decision,
                        job.raw_artifact_display_decision,
                        job.raw_artifact_redistribution_decision,
                        job.raw_artifact_retention_days,
                        job.maximum_paid_calls,
                        job.maximum_concurrent_calls,
                        job.paid_calls,
                        job.reserved_calls,
                        job.budget_version,
                        job.next_attempt_number,
                        admitted_by,
                        admitted_at,
                    ),
                )
            except psycopg.Error:
                raise ModelCallPersistenceError(
                    "PostgreSQL rejected the Model Gateway Job admission"
                ) from None
        return job

    def _read_job(self, project_id: UUID, job_id: UUID) -> ModelCallJobAdmission:
        with self.uow_factory(project_id=project_id) as unit_of_work:
            job = unit_of_work.calls.get_job(project_id=project_id, job_id=job_id)
        if job is None:
            raise ModelCallJobAdmissionNotFound("Model Gateway Job admission is unavailable")
        return job

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(
            self._database_url,
            connect_timeout=self._connect_timeout,
            row_factory=dict_row,
        )

    def _project_connection(self, project_id: UUID) -> psycopg.Connection[dict[str, Any]]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
        except BaseException:
            connection.close()
            raise
        return connection


def build_model_gateway_persistence(
    database_url: str | None,
    *,
    connect_timeout: int = 5,
) -> PostgresModelGatewayPersistence | None:
    if database_url is None or not database_url.strip():
        return None
    return PostgresModelGatewayPersistence(database_url, connect_timeout=connect_timeout)


def _same_admission_contract(
    stored: ModelCallJobAdmission, requested: ModelCallJobAdmission
) -> bool:
    return all(
        getattr(stored, field_name) == getattr(requested, field_name)
        for field_name in (
            "project_id",
            "job_id",
            "job_kind",
            "job_version",
            "status",
            "lease_token",
            "fencing_generation",
            "runtime_manifest_id",
            "runtime_manifest_hash",
            "runtime_option_id",
            "runtime_option_hash",
            "admission_mode",
            "purpose",
            "usage_audience",
            "route",
            "provider_secret_handle",
            "prompt_binding_id",
            "prompt_release_id",
            "prompt_release_hash",
            "prompt_state_id",
            "prompt_state_version",
            "prompt_test_set_hash",
            "prompt_bundle_hash",
            "output_schema_hash",
            "application_output_schema_hash",
            "policy_version_id",
            "policy_version_hash",
            "maximum_paid_calls",
            "maximum_concurrent_calls",
            "raw_artifact_policy_hash",
            "raw_artifact_storage_decision",
            "raw_artifact_cache_decision",
            "raw_artifact_display_decision",
            "raw_artifact_redistribution_decision",
            "raw_artifact_retention_days",
        )
    )


__all__ = [
    "PostgresModelGatewayPersistence",
    "build_model_gateway_persistence",
]
