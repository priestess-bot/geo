"""PostgreSQL implementation of the approved Model Gateway runtime catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelRouteError
from geo_core.model_gateway.ports import ModelCallJobAdmission, ModelCallPersistenceError
from geo_core.model_gateway.postgres_catalog import PostgresModelGatewayPersistence
from geo_core.model_gateway.postgres_rows import (
    adapter_release_from_row,
    model_release_from_row,
    project_policy_from_row,
)
from geo_core.model_gateway.provider_adapters.microsoft import MicrosoftAgentReference
from geo_core.model_gateway.releases import AdapterRelease, ModelRelease, ModelRoute
from geo_core.model_gateway.runtime_catalog import (
    ApprovedRuntimeOption,
    ApprovedRuntimeOptions,
    FrozenRuntimeOption,
    NewModelCallJobSelection,
    RuntimeOptionDefinition,
)
from geo_core.model_gateway.runtime_manifest import ModelGatewayRuntimeManifest
from geo_core.project_scope import set_project_scope
from geo_core.secrets import SecretVersionHandle


class PostgresRuntimeCatalog:
    """Use approved-only resolution for new Jobs and exact lineage for historical Jobs."""

    def __init__(
        self,
        database_url: str,
        *,
        persistence: PostgresModelGatewayPersistence | None = None,
        connect_timeout: int = 5,
    ) -> None:
        normalized = database_url.strip()
        if not normalized:
            raise ValueError("database_url is required")
        self._database_url = normalized
        self._connect_timeout = connect_timeout
        self._persistence = persistence or PostgresModelGatewayPersistence(
            normalized, connect_timeout=connect_timeout
        )
        self.uow_factory = self._persistence.uow_factory

    def register_adapter_release(
        self, release: AdapterRelease, *, registered_by: UUID, registered_at: datetime
    ) -> AdapterRelease:
        return self._persistence.register_adapter_release(
            release, registered_by=registered_by, registered_at=registered_at
        )

    def register_model_release(
        self, release: ModelRelease, *, registered_by: UUID, registered_at: datetime
    ) -> ModelRelease:
        return self._persistence.register_model_release(
            release, registered_by=registered_by, registered_at=registered_at
        )

    def register_project_policy(self, **values: Any):
        return self._persistence.register_project_policy(**values)

    def require_active_provider_secret_handle(
        self, *, project_id: UUID, provider: str, reference_id: UUID
    ) -> SecretVersionHandle:
        return self._persistence.require_active_provider_secret_handle(
            project_id=project_id,
            provider=provider,
            reference_id=reference_id,
        )

    def refresh_job_admission_lease(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        job_version: int,
        lease_token: UUID,
        fencing_generation: int,
    ) -> ModelCallJobAdmission:
        return self._persistence.refresh_job_admission_lease(
            project_id=project_id,
            job_id=job_id,
            job_version=job_version,
            lease_token=lease_token,
            fencing_generation=fencing_generation,
        )

    def register_runtime_manifest_record(
        self,
        *,
        manifest: ModelGatewayRuntimeManifest,
        options: tuple[RuntimeOptionDefinition, ...],
    ) -> None:
        if not options or any(
            option.project_id != manifest.project_id or option.manifest_id != manifest.manifest_id
            for option in options
        ):
            raise ModelCallPersistenceError("runtime manifest options are incomplete")
        policy = manifest.project_policy
        if policy.policy_version_id is None or policy.policy_version_hash is None:
            raise ModelCallPersistenceError("runtime manifest policy is not versioned")
        try:
            with self._project_connection(manifest.project_id) as connection:
                connection.execute(
                    """SELECT geo_register_model_gateway_runtime_manifest(
                           %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s
                       )""",
                    (
                        manifest.manifest_id,
                        manifest.project_id,
                        manifest.manifest_hash,
                        2,
                        policy.policy_version_id,
                        policy.policy_version_hash,
                        manifest.manifest_hash,
                        len(options),
                        manifest.prepared_by,
                        manifest.prepared_at,
                        manifest.approved_by,
                        manifest.approved_at,
                        manifest.approval_evidence_reference,
                        manifest.approval_evidence_sha256,
                    ),
                )
                for option in options:
                    runtime = option.provider_runtime
                    adapter = runtime.adapter_release
                    model = option.model_release
                    agent = runtime.microsoft_agent_reference
                    connection.execute(
                        """SELECT geo_add_model_gateway_runtime_option(
                               %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                           )""",
                        (
                            option.option_id,
                            manifest.project_id,
                            manifest.manifest_id,
                            adapter.provider,
                            adapter.adapter_release_id,
                            adapter.release_hash,
                            model.model_release_id,
                            model.release_hash,
                            runtime.secret_reference_id,
                            runtime.microsoft_endpoint,
                            agent.name if agent is not None else None,
                            agent.version if agent is not None else None,
                            agent.market if agent is not None else None,
                            agent.language if agent is not None else None,
                            option.provider_config_hash,
                            sorted(runtime.allowed_purposes),
                            Jsonb(_ordered_search_modes(runtime.allowed_search_modes)),
                            option.option_hash,
                            manifest.approved_at,
                        ),
                    )
        except psycopg.Error as exc:
            raise ModelCallPersistenceError(
                "PostgreSQL rejected the atomic runtime manifest registration"
            ) from exc

    def retire_manifest(
        self,
        *,
        project_id: UUID,
        manifest_id: UUID,
        retired_by: UUID,
        retired_at: datetime,
    ) -> None:
        try:
            with self._project_connection(project_id) as connection:
                connection.execute(
                    "SELECT geo_retire_model_gateway_runtime_manifest(%s, %s, %s, %s)",
                    (project_id, manifest_id, retired_by, retired_at),
                )
        except psycopg.Error as exc:
            raise ModelCallPersistenceError(
                "PostgreSQL rejected the runtime manifest retirement"
            ) from exc

    def list_approved_runtime_options(self, *, project_id: UUID) -> ApprovedRuntimeOptions:
        with self._project_connection(project_id) as connection:
            rows = connection.execute(
                """SELECT option.id AS selection_id, manifest.id AS manifest_id,
                          option.provider, option.adapter_release_id,
                          option.model_release_id, model.configured_model,
                          adapter.expected_capture_method,
                          option.allowed_purposes, option.allowed_search_modes
                   FROM model_gateway_runtime_options AS option
                   JOIN model_gateway_runtime_manifests AS manifest
                     ON manifest.project_id = option.project_id
                    AND manifest.id = option.manifest_id
                   JOIN model_gateway_model_releases AS model
                     ON model.provider = option.provider
                    AND model.adapter_release_id = option.adapter_release_id
                    AND model.model_release_id = option.model_release_id
                    AND model.release_hash = option.model_release_hash
                   JOIN model_gateway_adapter_releases AS adapter
                     ON adapter.provider = option.provider
                    AND adapter.adapter_release_id = option.adapter_release_id
                    AND adapter.release_hash = option.adapter_release_hash
                   JOIN secret_references AS reference
                     ON reference.id = option.secret_reference_id
                    AND reference.project_id = option.project_id
                    AND reference.purpose = option.secret_purpose
                   JOIN secret_versions AS secret
                     ON secret.reference_id = reference.id
                    AND secret.project_id = reference.project_id
                    AND secret.purpose = reference.purpose
                    AND secret.version = reference.current_version
                   WHERE option.project_id = %s AND manifest.status = 'approved'
                     AND adapter.state = 'approved' AND model.state = 'approved'
                     AND secret.status = 'active'
                   ORDER BY option.provider, option.adapter_release_id,
                            option.model_release_id""",
                (project_id,),
            ).fetchall()
        items = tuple(_approved_option(row) for row in rows)
        current = items[0].manifest_id if items else None
        if any(item.manifest_id != current for item in items):
            raise ModelCallPersistenceError("multiple approved runtime manifests are visible")
        return ApprovedRuntimeOptions(project_id, current, items)

    def resolve_approved_runtime(
        self,
        *,
        project_id: UUID,
        runtime_selection_id: UUID,
        required_purpose: str,
        search_mode: str | None,
    ) -> NewModelCallJobSelection:
        with self._project_connection(project_id) as connection:
            rows = connection.execute(
                "SELECT * FROM geo_resolve_model_gateway_runtime_option(%s, %s, %s, %s)",
                (project_id, runtime_selection_id, required_purpose, search_mode),
            ).fetchall()
            if len(rows) != 1:
                raise ModelRouteError("approved runtime selection is unavailable")
            row = rows[0]
            option = self._load_option_row(
                connection,
                project_id=project_id,
                manifest_id=row["runtime_manifest_id"],
                manifest_hash=row["runtime_manifest_hash"],
                option_id=row["runtime_option_id"],
                option_hash=row["runtime_option_hash"],
                require_approved=True,
            )
            adapter, model, policy = self._load_release_policy(
                connection, row, project_id=project_id
            )
        route = _route(row)
        return NewModelCallJobSelection(
            runtime_manifest_id=row["runtime_manifest_id"],
            runtime_manifest_hash=row["runtime_manifest_hash"],
            runtime_option_id=row["runtime_option_id"],
            runtime_option_hash=row["runtime_option_hash"],
            route=route,
            configured_model=row["configured_model"],
            policy=policy,
            provider_secret_handle=SecretVersionHandle(
                reference_id=row["secret_reference_id"],
                project_id=project_id,
                purpose=f"model_provider.{row['provider']}",
                version=row["secret_version"],
            ),
            adapter_release=adapter,
            allowed_purposes=frozenset(option["allowed_purposes"]),
            allowed_search_modes=frozenset(option["allowed_search_modes"]),
            provider_config_hash=row["provider_config_hash"],
            microsoft_endpoint=row["microsoft_endpoint"],
            microsoft_agent_reference=_microsoft_agent(row),
        )

    def load_frozen_runtime_option(self, *, job: ModelCallJobAdmission) -> FrozenRuntimeOption:
        with self._project_connection(job.project_id) as connection:
            option = self._load_option_row(
                connection,
                project_id=job.project_id,
                manifest_id=job.runtime_manifest_id,
                manifest_hash=job.runtime_manifest_hash,
                option_id=job.runtime_option_id,
                option_hash=job.runtime_option_hash,
                require_approved=False,
            )
            adapter, model, policy = self._load_release_policy(
                connection, option, project_id=job.project_id
            )
        return FrozenRuntimeOption(
            manifest_id=job.runtime_manifest_id,
            manifest_hash=job.runtime_manifest_hash,
            option_id=job.runtime_option_id,
            option_hash=job.runtime_option_hash,
            policy=policy,
            adapter_release=adapter,
            model_release=model,
            secret_reference_id=option["secret_reference_id"],
            allowed_purposes=frozenset(option["allowed_purposes"]),
            allowed_search_modes=frozenset(option["allowed_search_modes"]),
            provider_config_hash=option["provider_config_hash"],
            microsoft_endpoint=option["microsoft_endpoint"],
            microsoft_agent_reference=_microsoft_agent(option),
        )

    def _load_option_row(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        project_id: UUID,
        manifest_id: UUID,
        manifest_hash: str,
        option_id: UUID,
        option_hash: str,
        require_approved: bool,
    ) -> dict[str, Any]:
        status_clause = "AND manifest.status = 'approved'" if require_approved else ""
        row = connection.execute(
            f"""SELECT option.*, manifest.manifest_hash AS runtime_manifest_hash,
                       manifest.policy_version_id, manifest.policy_version_hash
                FROM model_gateway_runtime_options AS option
                JOIN model_gateway_runtime_manifests AS manifest
                  ON manifest.project_id = option.project_id
                 AND manifest.id = option.manifest_id
                WHERE option.project_id = %s AND option.id = %s
                  AND option.manifest_id = %s AND option.option_hash = %s
                  AND manifest.manifest_hash = %s {status_clause}""",
            (project_id, option_id, manifest_id, option_hash, manifest_hash),
        ).fetchone()
        if row is None:
            raise ModelRouteError("frozen runtime option is unavailable")
        return row

    @staticmethod
    def _load_release_policy(connection, row, *, project_id: UUID):
        adapter_row = connection.execute(
            """SELECT * FROM model_gateway_adapter_releases
               WHERE provider = %s AND adapter_release_id = %s
                 AND release_hash = %s""",
            (row["provider"], row["adapter_release_id"], row["adapter_release_hash"]),
        ).fetchone()
        model_row = connection.execute(
            """SELECT * FROM model_gateway_model_releases
               WHERE provider = %s AND adapter_release_id = %s
                 AND model_release_id = %s AND release_hash = %s""",
            (
                row["provider"],
                row["adapter_release_id"],
                row["model_release_id"],
                row["model_release_hash"],
            ),
        ).fetchone()
        policy_row = connection.execute(
            """SELECT * FROM model_gateway_project_policy_versions
               WHERE project_id = %s AND id = %s AND policy_hash = %s""",
            (
                project_id,
                row["policy_version_id"],
                row["policy_version_hash"],
            ),
        ).fetchone()
        if adapter_row is None or model_row is None or policy_row is None:
            raise ModelRouteError("frozen runtime releases or policy are unavailable")
        return (
            adapter_release_from_row(adapter_row),
            model_release_from_row(model_row),
            project_policy_from_row(policy_row),
        )

    def _project_connection(self, project_id: UUID):
        connection = psycopg.connect(
            self._database_url,
            connect_timeout=self._connect_timeout,
            row_factory=dict_row,
        )
        try:
            set_project_scope(connection, project_id)
        except BaseException:
            connection.close()
            raise
        return connection


def _approved_option(row: dict[str, Any]) -> ApprovedRuntimeOption:
    return ApprovedRuntimeOption(
        selection_id=row["selection_id"],
        manifest_id=row["manifest_id"],
        provider=row["provider"],
        adapter_release_id=row["adapter_release_id"],
        model_release_id=row["model_release_id"],
        configured_model=row["configured_model"],
        capture_method=ModelCaptureMethod(row["expected_capture_method"]),
        allowed_purposes=tuple(row["allowed_purposes"]),
        allowed_search_modes=tuple(row["allowed_search_modes"]),
    )


def _route(row: dict[str, Any]) -> ModelRoute:
    return ModelRoute(
        provider=row["provider"],
        adapter_release_id=row["adapter_release_id"],
        adapter_release_hash=row["adapter_release_hash"],
        model_release_id=row["model_release_id"],
        model_release_hash=row["model_release_hash"],
    )


def _microsoft_agent(row: dict[str, Any]) -> MicrosoftAgentReference | None:
    if row["provider"] != "microsoft":
        return None
    return MicrosoftAgentReference(
        name=row["microsoft_agent_name"],
        version=row["microsoft_agent_version"],
        market=row["microsoft_market"],
        language=row["microsoft_language"],
    )


def _ordered_search_modes(values: frozenset[str | None]) -> list[str | None]:
    return sorted(values, key=lambda value: (value is not None, value or ""))


__all__ = ["PostgresRuntimeCatalog"]
