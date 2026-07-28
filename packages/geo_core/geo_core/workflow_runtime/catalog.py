"""Operator catalog for registering, activating and inspecting Dify releases."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.secrets import SecretVersionHandle

from .contracts import (
    CONTEXT_CONTRACT_VERSION,
    DIFY_WORKFLOW_PURPOSES,
    DYNAMIC_JSON_OUTPUT_SCHEMA,
    canonical_json_hash,
    canonical_json_value,
)
from .errors import WorkflowConfigurationError, WorkflowContractError
from .catalog_models import (
    DifyUnresolvedAttempt,
    WorkflowRuntimeCard,
    workflow_runtime_card,
)
from .catalog_published import record_published_snapshot
from .published import PublishedWorkflowSnapshot


class PostgresWorkflowRuntimeCatalog:
    persistence = "durable"

    def __init__(self, database_url: str, *, connect_timeout: int = 5) -> None:
        if not database_url.strip():
            raise ValueError("workflow runtime database URL is required")
        self._database_url = database_url
        self._connect_timeout = connect_timeout

    def list_cards(self, *, project_id: UUID) -> tuple[WorkflowRuntimeCard, ...]:
        with self._connect(project_id) as connection:
            rows = _many(
                connection.execute(
                    """WITH current_bindings AS (
                           SELECT DISTINCT ON (purpose) *
                           FROM dify_workflow_bindings
                           WHERE project_id = %s
                           ORDER BY purpose, binding_version DESC
                       )
                       SELECT release.*, binding.binding_version, binding.activated_at,
                              prompt_release.system_template AS prompt_system_template,
                              prompt_release.user_template AS prompt_user_template,
                              attempt.status AS last_attempt_status,
                              attempt.execution_kind AS last_attempt_kind,
                              attempt.started_at AS last_attempt_at,
                              attempt.error_code AS last_error_code,
                              attempt.error_message AS last_error_message,
                              snapshot.dify_workflow_id AS published_workflow_id,
                              snapshot.workflow_hash AS published_workflow_hash,
                              snapshot.snapshot_hash AS published_snapshot_hash,
                              snapshot.prompt_nodes AS published_prompt_nodes,
                              snapshot.input_variables AS published_input_variables,
                              snapshot.graph_nodes AS published_graph_nodes,
                              snapshot.published_at,
                              snapshot.observed_at,
                              secret.status AS secret_status,
                              prompt_binding.release_id AS current_prompt_release_id,
                              prompt_state.status AS prompt_release_status
                       FROM current_bindings binding
                       JOIN dify_workflow_releases release
                         ON release.id = binding.release_id
                        AND release.project_id = binding.project_id
                       JOIN secret_versions secret
                         ON secret.reference_id = release.api_secret_reference_id
                        AND secret.project_id = release.project_id
                        AND secret.purpose = release.api_secret_purpose
                        AND secret.version = release.api_secret_version
                       JOIN prompt_program_releases prompt_release
                         ON prompt_release.id = release.prompt_release_id
                        AND prompt_release.project_id = release.project_id
                        AND prompt_release.program_id = release.prompt_program_id
                       LEFT JOIN LATERAL (
                           SELECT item.*
                           FROM dify_workflow_execution_attempts item
                           WHERE item.project_id = release.project_id
                             AND item.release_id = release.id
                           ORDER BY item.started_at DESC
                           LIMIT 1
                       ) attempt ON true
                       LEFT JOIN dify_workflow_release_snapshot_pins pin
                         ON pin.project_id = release.project_id
                        AND pin.release_id = release.id
                       LEFT JOIN dify_workflow_published_snapshots snapshot
                         ON snapshot.id = pin.published_snapshot_id
                        AND snapshot.project_id = pin.project_id
                        AND snapshot.release_id = pin.release_id
                       LEFT JOIN LATERAL (
                           SELECT item.release_id
                           FROM prompt_program_bindings item
                           WHERE item.project_id = release.project_id
                             AND item.purpose = release.purpose
                           ORDER BY item.binding_version DESC
                           LIMIT 1
                       ) prompt_binding ON true
                       LEFT JOIN LATERAL (
                           SELECT state.status
                           FROM prompt_program_release_states state
                           WHERE state.project_id = release.project_id
                             AND state.release_id = release.prompt_release_id
                           ORDER BY state.version DESC
                           LIMIT 1
                       ) prompt_state ON true
                       ORDER BY release.purpose""",
                    (project_id,),
                )
            )
            connection.rollback()
        by_purpose = {str(row["purpose"]): row for row in rows}
        return tuple(
            workflow_runtime_card(purpose, by_purpose.get(purpose))
            for purpose in sorted(DIFY_WORKFLOW_PURPOSES)
        )

    def list_unresolved_attempts(self, *, project_id: UUID) -> tuple[DifyUnresolvedAttempt, ...]:
        with self._connect(project_id) as connection:
            rows = _many(
                connection.execute(
                    """SELECT attempt.id AS attempt_id,
                              parent.id AS parent_job_id,
                              child.id AS child_job_id,
                              CASE parent.kind
                                  WHEN 'style.profile.build' THEN 'style_profile'
                                  WHEN 'recommendation.generate' THEN 'recommendation'
                              END AS flow_kind,
                              release.purpose, attempt.status,
                              child.status AS child_job_status,
                              CASE
                                  WHEN child.status IN ('running', 'finalizing')
                                       AND child.lease_expires_at > clock_timestamp()
                                      THEN 'active'
                                  WHEN child.status IN ('running', 'finalizing')
                                      THEN 'lease_expired'
                                  WHEN child.status IN (
                                      'succeeded', 'failed', 'dead_lettered', 'cancelled'
                                  ) THEN 'terminal'
                                  ELSE 'not_leased'
                              END AS lease_state,
                              CASE
                                  WHEN child.status IN ('running', 'finalizing')
                                       AND child.lease_expires_at > clock_timestamp()
                                      THEN 'wait_for_lease_expiry'
                                  ELSE 'verify_provider_then_issue_new_parent_token'
                              END AS required_action,
                              attempt.dify_run_id,
                              attempt.error_code, attempt.error_message,
                              attempt.started_at
                       FROM dify_workflow_execution_attempts attempt
                       JOIN dify_workflow_releases release
                         ON release.id = attempt.release_id
                        AND release.project_id = attempt.project_id
                       JOIN durable_jobs child
                         ON child.id = attempt.job_id
                        AND child.project_id = attempt.project_id
                       JOIN durable_jobs parent
                         ON parent.id = coalesce(child.parent_job_id, child.id)
                        AND parent.project_id = attempt.project_id
                       LEFT JOIN dify_workflow_reconciliation_consumptions consumed
                         ON consumed.project_id = attempt.project_id
                        AND consumed.attempt_id = attempt.id
                       WHERE attempt.project_id = %s
                         AND attempt.execution_kind = 'business'
                         AND (
                              attempt.status = 'running'
                              OR (attempt.status = 'failed'
                                  AND attempt.error_classification = 'unknown_outcome')
                         )
                         AND consumed.attempt_id IS NULL
                         AND (
                              (parent.kind = 'style.profile.build'
                               AND release.purpose = 'synthetic_lab.style_profile')
                              OR (parent.kind = 'recommendation.generate'
                                  AND release.purpose = 'recommendations.recommendation')
                         )
                       ORDER BY attempt.started_at, attempt.id""",
                    (project_id,),
                )
            )
            connection.rollback()
        return tuple(
            DifyUnresolvedAttempt(
                attempt_id=row["attempt_id"],
                parent_job_id=row["parent_job_id"],
                child_job_id=row["child_job_id"],
                flow_kind=str(row["flow_kind"]),
                purpose=str(row["purpose"]),
                status=str(row["status"]),
                child_job_status=str(row["child_job_status"]),
                lease_state=str(row["lease_state"]),
                required_action=str(row["required_action"]),
                provider_run_id=(str(row["dify_run_id"]) if row["dify_run_id"] else None),
                error_code=(str(row["error_code"]) if row["error_code"] else None),
                error_message=(str(row["error_message"]) if row["error_message"] else None),
                started_at=row["started_at"],
            )
            for row in rows
        )

    def record_published_snapshot(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        snapshot: PublishedWorkflowSnapshot,
    ) -> UUID:
        with self._connect(project_id) as connection:
            return record_published_snapshot(
                connection,
                project_id=project_id,
                release_id=release_id,
                snapshot=snapshot,
            )

    def register_release(
        self,
        *,
        project_id: UUID,
        purpose: str,
        prompt_program_id: UUID,
        prompt_release_id: UUID,
        dify_app_id: str,
        dify_workflow_id: str,
        dsl_hash: str,
        registered_workflow_hash: str,
        registered_snapshot_hash: str,
        configured_model: str,
        model_provider: str,
        api_secret_handle: SecretVersionHandle,
        created_by: UUID,
        input_schema: Mapping[str, object] | None = None,
        output_schema: Mapping[str, object] | None = None,
    ) -> UUID:
        if purpose not in DIFY_WORKFLOW_PURPOSES:
            raise WorkflowContractError("Dify workflow purpose is not supported")
        if (
            api_secret_handle.project_id != project_id
            or api_secret_handle.purpose != "workflow_runtime.dify"
        ):
            raise WorkflowContractError("Dify API Secret handle has the wrong scope")
        for label, value in (
            ("Dify app ID", dify_app_id),
            ("Dify workflow ID", dify_workflow_id),
            ("configured model", configured_model),
            ("model provider", model_provider),
        ):
            if not value.strip():
                raise WorkflowContractError(f"{label} is required")
        for label, value in (
            ("Dify DSL hash", dsl_hash),
            ("registered Dify workflow hash", registered_workflow_hash),
            ("registered Dify snapshot hash", registered_snapshot_hash),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise WorkflowContractError(f"{label} must be lowercase SHA-256")
        frozen_input = dict(
            input_schema
            or {
                "type": "object",
                "x-geo-context-contract": CONTEXT_CONTRACT_VERSION,
            }
        )
        frozen_output = dict(output_schema or DYNAMIC_JSON_OUTPUT_SCHEMA)
        input_hash = canonical_json_hash(frozen_input)
        output_hash = canonical_json_hash(frozen_output)
        with self._connect(project_id) as connection:
            try:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"dify-runtime:{project_id}:{purpose}",),
                )
                prompt = _one(
                    connection.execute(
                        """SELECT release.release_hash,
                                  state.status,
                                  binding.release_id AS current_release_id
                           FROM prompt_program_releases release
                           JOIN LATERAL (
                               SELECT item.status
                               FROM prompt_program_release_states item
                               WHERE item.project_id = release.project_id
                                 AND item.release_id = release.id
                               ORDER BY item.version DESC LIMIT 1
                           ) state ON true
                           LEFT JOIN LATERAL (
                               SELECT item.release_id
                               FROM prompt_program_bindings item
                               WHERE item.project_id = release.project_id
                                 AND item.purpose = release.purpose
                               ORDER BY item.binding_version DESC LIMIT 1
                           ) binding ON true
                           WHERE release.project_id = %s AND release.id = %s
                             AND release.program_id = %s AND release.purpose = %s""",
                        (project_id, prompt_release_id, prompt_program_id, purpose),
                    )
                )
                if prompt is None:
                    raise WorkflowConfigurationError(
                        "Prompt Release does not match this Dify purpose"
                    )
                if (
                    prompt["status"] != "frozen"
                    or prompt["current_release_id"] != prompt_release_id
                ):
                    raise WorkflowConfigurationError(
                        "register Dify only against the current frozen Prompt Release"
                    )
                secret = _one(
                    connection.execute(
                        """SELECT status FROM secret_versions
                           WHERE reference_id = %s AND project_id = %s
                             AND purpose = %s AND version = %s""",
                        (
                            api_secret_handle.reference_id,
                            project_id,
                            api_secret_handle.purpose,
                            api_secret_handle.version,
                        ),
                    )
                )
                if secret is None or secret["status"] != "active":
                    raise WorkflowConfigurationError("Dify API Secret version is not active")
                release_value = {
                    "purpose": purpose,
                    "prompt_program_id": str(prompt_program_id),
                    "prompt_release_id": str(prompt_release_id),
                    "prompt_release_hash": str(prompt["release_hash"]),
                    "dify_app_id": dify_app_id.strip(),
                    "dify_workflow_id": dify_workflow_id.strip(),
                    "dsl_hash": dsl_hash,
                    "registered_workflow_hash": registered_workflow_hash,
                    "registered_snapshot_hash": registered_snapshot_hash,
                    "context_contract_version": CONTEXT_CONTRACT_VERSION,
                    "input_schema": canonical_json_value(frozen_input),
                    "output_schema": canonical_json_value(frozen_output),
                    "configured_model": configured_model.strip(),
                    "model_provider": model_provider.strip(),
                    "api_secret_handle": api_secret_handle.as_job_payload(),
                }
                release_hash = canonical_json_hash(release_value)
                existing = _one(
                    connection.execute(
                        """SELECT id FROM dify_workflow_releases
                           WHERE project_id = %s AND purpose = %s AND release_hash = %s""",
                        (project_id, purpose, release_hash),
                    )
                )
                if existing is not None:
                    connection.rollback()
                    return existing["id"]
                version_row = _one(
                    connection.execute(
                        """SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                           FROM dify_workflow_releases
                           WHERE project_id = %s AND purpose = %s""",
                        (project_id, purpose),
                    )
                )
                assert version_row is not None
                release_id = uuid4()
                connection.execute(
                    """INSERT INTO dify_workflow_releases (
                           id, project_id, purpose, version, prompt_program_id,
                           prompt_release_id, prompt_release_hash, dify_app_id,
                           dify_workflow_id, dsl_hash, registered_workflow_hash,
                           registered_snapshot_hash, registered_identity_source,
                           context_contract_version,
                           input_schema, input_schema_hash, output_schema, output_schema_hash,
                           configured_model, model_provider, api_secret_reference_id,
                           api_secret_purpose, api_secret_version, release_hash, created_by
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s
                       )""",
                    (
                        release_id,
                        project_id,
                        purpose,
                        int(version_row["next_version"]),
                        prompt_program_id,
                        prompt_release_id,
                        prompt["release_hash"],
                        dify_app_id.strip(),
                        dify_workflow_id.strip(),
                        dsl_hash,
                        registered_workflow_hash,
                        registered_snapshot_hash,
                        "runtime_enrollment",
                        CONTEXT_CONTRACT_VERSION,
                        Jsonb(frozen_input),
                        input_hash,
                        Jsonb(frozen_output),
                        output_hash,
                        configured_model.strip(),
                        model_provider.strip(),
                        api_secret_handle.reference_id,
                        api_secret_handle.purpose,
                        api_secret_handle.version,
                        release_hash,
                        created_by,
                    ),
                )
                connection.commit()
                return release_id
            except BaseException:
                connection.rollback()
                raise

    def activate_release(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        activated_by: UUID,
        reason: str,
    ) -> UUID:
        if not reason.strip():
            raise WorkflowContractError("Dify activation reason is required")
        with self._connect(project_id) as connection:
            try:
                release = _one(
                    connection.execute(
                        """SELECT id, purpose, release_hash
                           FROM dify_workflow_releases
                           WHERE id = %s AND project_id = %s""",
                        (release_id, project_id),
                    )
                )
                if release is None:
                    raise WorkflowConfigurationError("Dify release was not found")
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"dify-binding:{project_id}:{release['purpose']}",),
                )
                previous = _one(
                    connection.execute(
                        """SELECT id, release_id, binding_version
                           FROM dify_workflow_bindings
                           WHERE project_id = %s AND purpose = %s
                           ORDER BY binding_version DESC LIMIT 1""",
                        (project_id, release["purpose"]),
                    )
                )
                if previous is not None and previous["release_id"] == release_id:
                    connection.rollback()
                    return previous["id"]
                binding_id = uuid4()
                connection.execute(
                    """INSERT INTO dify_workflow_bindings (
                           id, project_id, purpose, release_id, release_hash,
                           binding_version, previous_binding_id, activated_by, reason
                       ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        binding_id,
                        project_id,
                        release["purpose"],
                        release_id,
                        release["release_hash"],
                        1 if previous is None else int(previous["binding_version"]) + 1,
                        None if previous is None else previous["id"],
                        activated_by,
                        reason.strip(),
                    ),
                )
                connection.commit()
                return binding_id
            except BaseException:
                connection.rollback()
                raise

    def authorize_new_parent_after_unknown_outcome(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        authorized_by: UUID,
        provider_outcome: str,
        provider_run_id: str | None,
        evidence_reference: str,
        reason: str,
    ) -> str:
        """Issue a one-time new-parent token without reopening the old Job."""
        with self._connect(project_id) as connection:
            try:
                connection.execute(
                    "SELECT set_config('geo.identity_id', %s, true)",
                    (str(authorized_by),),
                )
                row = _one(
                    connection.execute(
                        """SELECT geo_issue_dify_resubmission_token(
                               %s, %s, %s, %s, %s, %s, %s
                           ) AS resubmission_token""",
                        (
                            project_id,
                            attempt_id,
                            authorized_by,
                            provider_outcome,
                            provider_run_id,
                            evidence_reference,
                            reason,
                        ),
                    )
                )
                if row is None or not row["resubmission_token"]:
                    raise WorkflowConfigurationError(
                        "Dify reconciliation did not issue a resubmission token"
                    )
                connection.commit()
                return str(row["resubmission_token"])
            except BaseException:
                connection.rollback()
                raise

    def _connect(self, project_id: UUID):
        connection = psycopg.connect(
            self._database_url,
            connect_timeout=self._connect_timeout,
            row_factory=dict_row,
        )
        set_project_scope(connection, project_id)
        return connection


def _one(cursor: Any) -> dict[str, Any] | None:
    row = cursor.fetchone()
    return dict(row) if row is not None else None


def _many(cursor: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]
