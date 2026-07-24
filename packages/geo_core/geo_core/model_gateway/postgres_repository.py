"""Project-scoped psycopg repository for audited model calls."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway.contracts import ModelCallBudgetExceeded
from geo_core.model_gateway.location import EffectiveModelLocation, RequestedModelLocation
from geo_core.model_gateway.ports import (
    ModelCallAttempt,
    ModelCallAttemptDraft,
    ModelCallIdempotencyConflict,
    ModelCallJobAdmission,
    ModelCallOutcome,
    ModelCallPersistenceError,
    ModelCallReconciliationRecord,
    ModelCallRepository,
    ModelCallTerminalEvent,
    ModelCallVersionConflict,
    PromptReleaseAdmission,
    StoredModelCallAttempt,
    canonical_json_hash,
)
from geo_core.model_gateway.postgres_rows import (
    attempt_from_row,
    job_admission_from_row,
    prompt_admission_from_row,
    reconciliation_record_from_row,
    terminal_event_from_row,
)


class PsycopgModelCallRepository(ModelCallRepository):
    def __init__(self, connection: Any, *, project_id: UUID) -> None:
        self._connection = connection
        self._project_id = project_id

    def get_job(self, *, project_id: UUID, job_id: UUID) -> ModelCallJobAdmission | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT admission.*, durable.status AS durable_status
               FROM model_gateway_job_admissions AS admission
               JOIN durable_jobs AS durable
                 ON durable.id = admission.job_id
                AND durable.project_id = admission.project_id
               WHERE admission.project_id = %s AND admission.job_id = %s""",
            (project_id, job_id),
        ).fetchone()
        if row is None:
            return None
        return job_admission_from_row(row)

    def get_prompt_release(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        binding_id: UUID,
    ) -> PromptReleaseAdmission | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT 'runtime_frozen'::text AS admission_mode,
                      binding.id AS binding_id, binding.project_id,
                      state.id AS state_id, state.version AS state_version,
                      binding.release_id,
                      binding.release_hash, binding.purpose,
                      release.output_schema, release.application_output_schema,
                      NULL::text AS test_set_hash,
                      state.status AS state_status, true AS current
               FROM prompt_program_bindings AS binding
               JOIN prompt_program_releases AS release
                 ON release.id = binding.release_id
                AND release.project_id = binding.project_id
                AND release.release_hash = binding.release_hash
               JOIN prompt_program_release_states AS state
                 ON state.id = binding.frozen_state_id
                AND state.project_id = binding.project_id
                AND state.release_id = binding.release_id
                AND state.release_hash = binding.release_hash
               WHERE binding.project_id = %s
                 AND binding.release_id = %s AND binding.id = %s
                 AND state.status = 'frozen'""",
            (project_id, release_id, binding_id),
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["output_schema_hash"] = canonical_json_hash(values.pop("output_schema"))
        values["application_output_schema_hash"] = canonical_json_hash(
            values.pop("application_output_schema")
        )
        return prompt_admission_from_row(values)

    def get_prompt_test_release(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        state_id: UUID,
        state_version: int,
        test_set_hash: str,
    ) -> PromptReleaseAdmission | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT 'prompt_release_test'::text AS admission_mode,
                      NULL::uuid AS binding_id, release.project_id,
                      state.id AS state_id, state.version AS state_version,
                      release.id AS release_id, release.release_hash,
                      'prompt_release_test'::text AS purpose,
                      release.output_schema, release.application_output_schema,
                      release.test_set_hash,
                      state.status AS state_status,
                      NOT EXISTS (
                          SELECT 1 FROM prompt_program_release_states AS later
                          WHERE later.project_id = state.project_id
                            AND later.release_id = state.release_id
                            AND later.version > state.version
                      ) AS current
               FROM prompt_program_releases AS release
               JOIN prompt_program_release_states AS state
                 ON state.release_id = release.id
                AND state.project_id = release.project_id
                AND state.release_hash = release.release_hash
               WHERE release.project_id = %s AND release.id = %s
                 AND state.id = %s AND state.version = %s
                 AND release.test_set_hash = %s AND state.status = 'draft'""",
            (project_id, release_id, state_id, state_version, test_set_hash),
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["output_schema_hash"] = canonical_json_hash(values.pop("output_schema"))
        values["application_output_schema_hash"] = canonical_json_hash(
            values.pop("application_output_schema")
        )
        return prompt_admission_from_row(values)

    def get_attempt(self, *, project_id: UUID, attempt_id: UUID) -> ModelCallAttempt | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT * FROM model_gateway_call_attempts
               WHERE project_id = %s AND id = %s""",
            (project_id, attempt_id),
        ).fetchone()
        return attempt_from_row(row) if row is not None else None

    def get_attempt_by_idempotency(
        self, *, project_id: UUID, job_id: UUID, idempotency_key_hash: str
    ) -> ModelCallOutcome | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT * FROM model_gateway_call_attempts
               WHERE project_id = %s AND job_id = %s
                 AND idempotency_key_hash = %s""",
            (project_id, job_id, idempotency_key_hash),
        ).fetchone()
        if row is None:
            return None
        attempt = attempt_from_row(row)
        return ModelCallOutcome(
            attempt,
            self.get_terminal_event(project_id=project_id, attempt_id=attempt.spec.id),
        )

    def get_terminal_event(
        self, *, project_id: UUID, attempt_id: UUID
    ) -> ModelCallTerminalEvent | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT * FROM model_gateway_terminal_events
               WHERE project_id = %s AND attempt_id = %s""",
            (project_id, attempt_id),
        ).fetchone()
        return terminal_event_from_row(row) if row is not None else None

    def get_reconciliation_command(
        self, *, project_id: UUID, idempotency_key_hash: str
    ) -> ModelCallReconciliationRecord | None:
        self._require_scope(project_id)
        row = self._connection.execute(
            """SELECT * FROM model_gateway_reconciliation_commands
               WHERE project_id = %s AND idempotency_key_hash = %s""",
            (project_id, idempotency_key_hash),
        ).fetchone()
        return reconciliation_record_from_row(row) if row is not None else None

    def reserve_attempt(
        self,
        *,
        draft: ModelCallAttemptDraft,
        expected_job_version: int,
        expected_budget_version: int,
        reserved_at: datetime,
    ) -> StoredModelCallAttempt:
        self._require_scope(draft.project_id)
        try:
            self._lock_idempotency(draft)
            existing = self.get_attempt_by_idempotency(
                project_id=draft.project_id,
                job_id=draft.job_id,
                idempotency_key_hash=draft.idempotency_key_hash,
            )
            if existing is not None:
                if existing.attempt.spec.request_hash != draft.request_hash:
                    raise ModelCallIdempotencyConflict(
                        "model-call attempt idempotency key was reused for another request"
                    )
                return StoredModelCallAttempt(existing.attempt, replayed=True)
            job = self.get_job(project_id=draft.project_id, job_id=draft.job_id)
            if job is None:
                raise ModelCallPersistenceError("model-call Job admission does not exist")
            self._validate_reservation(
                draft,
                job=job,
                expected_job_version=expected_job_version,
                expected_budget_version=expected_budget_version,
            )
            attempt = ModelCallAttempt(
                spec=draft,
                attempt_number=job.next_attempt_number,
                reserved_at=reserved_at,
            )
            self._insert_attempt(attempt, expected_budget_version=expected_budget_version)
            updated = self._connection.execute(
                """UPDATE model_gateway_job_admissions
                   SET reserved_calls = reserved_calls + 1,
                       budget_version = budget_version + 1,
                       next_attempt_number = next_attempt_number + 1
                   WHERE project_id = %s AND job_id = %s
                     AND job_version = %s AND budget_version = %s
                     AND paid_calls + reserved_calls < maximum_paid_calls
                     AND reserved_calls < maximum_concurrent_calls
                   RETURNING job_id""",
                (
                    draft.project_id,
                    draft.job_id,
                    expected_job_version,
                    expected_budget_version,
                ),
            ).fetchone()
            if updated is None:
                raise ModelCallVersionConflict("model-call reservation budget CAS failed")
            return StoredModelCallAttempt(attempt, replayed=False)
        except (ModelCallPersistenceError, ModelCallBudgetExceeded):
            raise
        except psycopg.Error as exc:
            raise _map_database_error(exc, operation="reserve") from None

    def append_terminal_event(
        self,
        *,
        event: ModelCallTerminalEvent,
        expected_budget_version: int,
    ) -> None:
        self._require_scope(event.project_id)
        try:
            if self.get_terminal_event(
                project_id=event.project_id, attempt_id=event.attempt_id
            ) is not None:
                raise ModelCallVersionConflict(
                    "model-call attempt already has a terminal event"
                )
            self._insert_terminal(event, expected_budget_version=expected_budget_version)
            updated = self._connection.execute(
                """UPDATE model_gateway_job_admissions
                   SET paid_calls = paid_calls + %s,
                       reserved_calls = reserved_calls - 1,
                       budget_version = budget_version + 1
                   WHERE project_id = %s AND job_id = %s
                     AND budget_version = %s AND reserved_calls > 0
                     AND paid_calls + %s <= maximum_paid_calls
                   RETURNING job_id""",
                (
                    event.paid_call_count,
                    event.project_id,
                    event.job_id,
                    expected_budget_version,
                    event.paid_call_count,
                ),
            ).fetchone()
            if updated is None:
                raise ModelCallVersionConflict("model-call terminal budget CAS failed")
        except (ModelCallPersistenceError, ModelCallBudgetExceeded):
            raise
        except psycopg.Error as exc:
            raise _map_database_error(exc, operation="terminal") from None

    def add_reconciliation_command(
        self, command: ModelCallReconciliationRecord
    ) -> None:
        self._require_scope(command.project_id)
        try:
            self._connection.execute(
                """INSERT INTO model_gateway_reconciliation_commands(
                       id, project_id, attempt_id, idempotency_key_hash,
                       request_hash, expected_budget_version, terminal_event_id,
                       reconciled_by, recorded_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    command.id,
                    command.project_id,
                    command.attempt_id,
                    command.idempotency_key_hash,
                    command.request_hash,
                    command.expected_budget_version,
                    command.terminal_event_id,
                    command.reconciled_by,
                    command.recorded_at,
                ),
            )
        except psycopg.Error as exc:
            raise _map_database_error(exc, operation="reconciliation") from None

    def _lock_idempotency(self, draft: ModelCallAttemptDraft) -> None:
        self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (
                "model-call-idempotency:"
                f"{draft.project_id}:{draft.job_id}:{draft.idempotency_key_hash}",
            ),
        )

    def _validate_reservation(
        self,
        draft: ModelCallAttemptDraft,
        *,
        job: ModelCallJobAdmission,
        expected_job_version: int,
        expected_budget_version: int,
    ) -> None:
        if draft.job_version != expected_job_version or job.job_version != expected_job_version:
            raise ModelCallVersionConflict("model-call Job version CAS failed")
        if job.budget_version != expected_budget_version:
            raise ModelCallVersionConflict("model-call paid budget CAS failed")
        if job.status is not JobStatus.RUNNING:
            raise ModelCallVersionConflict("model-call Job is no longer running")
        if (
            draft.lease_token != job.lease_token
            or draft.fencing_generation != job.fencing_generation
        ):
            raise ModelCallVersionConflict("model-call Job lease or fencing token is stale")
        if job.paid_calls + job.reserved_calls >= job.maximum_paid_calls:
            raise ModelCallBudgetExceeded("job-wide paid model-call budget exhausted")
        if job.reserved_calls >= job.maximum_concurrent_calls:
            raise ModelCallBudgetExceeded("job-wide concurrent model-call budget exhausted")

    def _insert_attempt(
        self, attempt: ModelCallAttempt, *, expected_budget_version: int
    ) -> None:
        draft = attempt.spec
        self._connection.execute(
            """INSERT INTO model_gateway_call_attempts(
                   id, project_id, job_id, attempt_number, expected_budget_version,
                   job_version, runtime_manifest_id, runtime_manifest_hash,
                   runtime_option_id, runtime_option_hash,
                   admission_mode, lease_token, fencing_generation,
                   kind, parent_attempt_id,
                   idempotency_key_hash, request_hash, input_hash,
                   policy_version_id, policy_version_hash, purpose, usage_audience,
                   provider, adapter_release_id, adapter_release_hash,
                   model_release_id, model_release_hash,
                   provider_secret_reference_id, provider_secret_version,
                   provider_secret_handle_hash,
                   prompt_binding_id, prompt_release_id, prompt_release_hash,
                   prompt_state_id, prompt_state_version, prompt_test_set_hash,
                   prompt_test_case_id, prompt_test_case_hash,
                   prompt_bundle_hash, output_schema_hash,
                   application_output_schema_hash,
                   raw_artifact_policy_hash, raw_artifact_storage_decision,
                   raw_artifact_cache_decision, raw_artifact_display_decision,
                   raw_artifact_redistribution_decision,
                   raw_artifact_retention_days, configured_model, search_mode,
                   requested_location_country, requested_location_region,
                   requested_location_locale, requested_location_language,
                   expected_location_control, expected_location_country,
                   expected_location_region, expected_location_locale,
                   expected_location_language, expected_location_evidence_hash,
                   capture_method, reserved_at
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s
               )""",
            (
                draft.id,
                draft.project_id,
                draft.job_id,
                attempt.attempt_number,
                expected_budget_version,
                draft.job_version,
                draft.runtime_manifest_id,
                draft.runtime_manifest_hash,
                draft.runtime_option_id,
                draft.runtime_option_hash,
                draft.admission_mode.value,
                draft.lease_token,
                draft.fencing_generation,
                draft.kind.value,
                draft.parent_attempt_id,
                draft.idempotency_key_hash,
                draft.request_hash,
                draft.input_hash,
                draft.policy_version_id,
                draft.policy_version_hash,
                draft.purpose,
                draft.usage_audience.value,
                draft.route.provider,
                draft.route.adapter_release_id,
                draft.route.adapter_release_hash,
                draft.route.model_release_id,
                draft.route.model_release_hash,
                draft.provider_secret_handle.reference_id,
                draft.provider_secret_handle.version,
                draft.provider_secret_handle_hash,
                draft.prompt_binding_id,
                draft.prompt_release_id,
                draft.prompt_release_hash,
                draft.prompt_state_id,
                draft.prompt_state_version,
                draft.prompt_test_set_hash,
                draft.prompt_test_case_id,
                draft.prompt_test_case_hash,
                draft.prompt_bundle_hash,
                draft.output_schema_hash,
                draft.application_output_schema_hash,
                draft.raw_artifact_policy_hash,
                draft.raw_artifact_storage_decision,
                draft.raw_artifact_cache_decision,
                draft.raw_artifact_display_decision,
                draft.raw_artifact_redistribution_decision,
                draft.raw_artifact_retention_days,
                draft.configured_model,
                draft.search_mode,
                *_requested_location_values(draft.requested_location),
                *_effective_location_values(draft.expected_effective_location),
                draft.capture_method.value if draft.capture_method is not None else None,
                attempt.reserved_at,
            ),
        )

    def _insert_terminal(
        self, event: ModelCallTerminalEvent, *, expected_budget_version: int
    ) -> None:
        lineage = event.lineage
        self._connection.execute(
            """INSERT INTO model_gateway_terminal_events(
                   id, project_id, job_id, attempt_id, expected_budget_version,
                   status, occurred_at, paid_call_count, gateway_call_log_id,
                   configured_model, provider_reported_model, provider_request_id,
                   prompt_tokens, completion_tokens, cost_usd, finish_reason,
                   input_hash, output_hash, response_hash,
                   effective_location_control, effective_location_country,
                   effective_location_region, effective_location_locale,
                   effective_location_language, effective_location_evidence_hash,
                   search_mode, capture_method,
                   citation_count, citation_lineage_hash, search_event_count,
                   search_lineage_hash, usage_details_hash, usage_purpose, usage_audience,
                   raw_artifact_reference_hash, raw_artifact_policy_hash,
                   raw_artifact_storage_decision, raw_artifact_cache_decision,
                   raw_artifact_display_decision, raw_artifact_redistribution_decision,
                   raw_artifact_retention_days,
                   error_classification, error_code, error_retryable,
                   reconciled_by, reconciliation_evidence_ref
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s
               )""",
            (
                event.id,
                event.project_id,
                event.job_id,
                event.attempt_id,
                expected_budget_version,
                event.status.value,
                event.occurred_at,
                event.paid_call_count,
                event.gateway_call_log_id,
                event.configured_model,
                event.provider_reported_model,
                event.provider_request_id,
                event.prompt_tokens,
                event.completion_tokens,
                event.cost_usd,
                event.finish_reason,
                event.input_hash,
                event.output_hash,
                event.response_hash,
                *_effective_location_values(lineage.effective_location),
                lineage.search_mode,
                lineage.capture_method.value if lineage.capture_method is not None else None,
                lineage.citation_count,
                lineage.citation_lineage_hash,
                lineage.search_event_count,
                lineage.search_lineage_hash,
                lineage.usage_details_hash,
                lineage.usage_purpose,
                lineage.usage_audience.value,
                lineage.raw_artifact_reference_hash,
                lineage.raw_artifact_policy_hash,
                lineage.raw_artifact_storage_decision,
                lineage.raw_artifact_cache_decision,
                lineage.raw_artifact_display_decision,
                lineage.raw_artifact_redistribution_decision,
                lineage.raw_artifact_retention_days,
                (
                    event.error_classification.value
                    if event.error_classification is not None
                    else None
                ),
                event.error_code.value if event.error_code is not None else None,
                event.error_retryable,
                event.reconciled_by,
                event.reconciliation_evidence_ref,
            ),
        )

    def _require_scope(self, project_id: UUID) -> None:
        if project_id != self._project_id:
            raise ModelCallPersistenceError("model-call repository project scope mismatch")


def _map_database_error(exc: psycopg.Error, *, operation: str) -> RuntimeError:
    if exc.sqlstate == "53000":
        return ModelCallBudgetExceeded("model-call paid or concurrency budget is exhausted")
    if exc.sqlstate in {"40001", "55000", "23505"}:
        return ModelCallVersionConflict(f"model-call {operation} CAS or append-only guard failed")
    return ModelCallPersistenceError(f"PostgreSQL rejected the model-call {operation}")


def _requested_location_values(
    location: RequestedModelLocation | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if location is None:
        return (None, None, None, None)
    return (location.country_code, location.region_code, location.locale, location.language)


def _effective_location_values(
    location: EffectiveModelLocation | None,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    if location is None:
        return (None, None, None, None, None, None)
    return (
        location.control.value,
        location.country_code,
        location.region_code,
        location.locale,
        location.language,
        location.evidence_hash,
    )


__all__ = ["PsycopgModelCallRepository"]
