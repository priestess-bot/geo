"""Internal API admission for durable Recommendation generation Jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from geo_core.access.models import AccessPrincipal
from geo_core.project_scope import set_project_scope
from geo_core.model_gateway.runtime_catalog import ApprovedRuntimeCatalog
from geo_core.recommendations.application_support import require_project_role
from geo_core.recommendations.generation_admission import (
    RecommendationGenerationSelection,
)
from geo_core.recommendations.generation_contracts import (
    GenerationExecution,
    RecommendationGenerationConflict,
    RecommendationGenerationJob,
    canonical_hash,
    idempotency_hash,
)
from geo_core.recommendations.postgres.generation_admission import (
    PostgresRecommendationGenerationAdmission,
)
from geo_core.recommendations.postgres.generation_codec import generation_spec_payload
from geo_core.recommendations.postgres.generation_reads import (
    PostgresRecommendationGenerationReads,
)
from geo_core.workflow_runtime.reconciliation import (
    DifyRecoveryBindingError,
    bind_dify_resubmission,
)


_CONTRIBUTOR_ROLES = frozenset({"owner", "admin", "analyst"})
_READER_ROLES = frozenset({"owner", "admin", "analyst", "viewer"})
_MAX_ATTEMPTS = 5


class PsycopgRecommendationGenerationSubmission:
    """Admit only frozen selections through the database's atomic enqueue contract."""

    def __init__(
        self,
        *,
        connection_factory: Callable[[], Any],
        runtime_catalog: ApprovedRuntimeCatalog,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connection_factory
        self._runtime_catalog = runtime_catalog
        self._id_factory = id_factory
        self._clock = clock
        self._reads = PostgresRecommendationGenerationReads(connection_factory)

    def enqueue(
        self,
        principal: AccessPrincipal,
        *,
        selection: RecommendationGenerationSelection,
        idempotency_key: str,
        recovery_of_attempt_id: UUID | None = None,
        dify_reconciliation_token: str | None = None,
    ) -> GenerationExecution:
        require_project_role(principal, selection.project_id, allowed=_CONTRIBUTOR_ROLES)
        key_hash = idempotency_hash(idempotency_key)
        connection = self._connect()
        try:
            set_project_scope(connection, selection.project_id)
            self._lock_idempotency(connection, selection.project_id, key_hash)
            admission = PostgresRecommendationGenerationAdmission(
                connection,
                selection.project_id,
                runtime_catalog=self._runtime_catalog,
            )
            spec = admission.resolve(selection=selection, created_by=str(principal.identity_id))
            existing = connection.execute(
                """SELECT job_id FROM recommendation_generation_specs
                   WHERE project_id = %s AND idempotency_key_hash = %s""",
                (selection.project_id, key_hash),
            ).fetchone()
            job_id = existing["job_id"] if existing is not None else self._id_factory()
            payload = generation_spec_payload(spec)
            result = connection.execute(
                """SELECT job_id, replayed FROM geo_enqueue_recommendation_generation(
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    selection.project_id,
                    job_id,
                    Jsonb(payload),
                    canonical_hash(payload),
                    spec.input_hash,
                    key_hash,
                    spec.valid_until,
                    principal.identity_id,
                    self._clock(),
                    _MAX_ATTEMPTS,
                ),
            ).fetchone()
            if result is None:
                raise RecommendationGenerationConflict(
                    "Recommendation generation enqueue did not return a Job"
                )
            bind_dify_resubmission(
                connection,
                project_id=selection.project_id,
                new_parent_job_id=result["job_id"],
                actor_id=principal.identity_id,
                recovery_of_attempt_id=recovery_of_attempt_id,
                token=dify_reconciliation_token,
            )
            execution = GenerationExecution(
                self._reads.get_in_connection(
                    connection,
                    project_id=selection.project_id,
                    job_id=result["job_id"],
                ),
                self._reads.result_in_connection(
                    connection,
                    project_id=selection.project_id,
                    job_id=result["job_id"],
                ),
                bool(result["replayed"]),
            )
            connection.commit()
            return execution
        except RecommendationGenerationConflict:
            connection.rollback()
            raise
        except DifyRecoveryBindingError as error:
            connection.rollback()
            raise RecommendationGenerationConflict(str(error)) from error
        except psycopg.Error as error:
            connection.rollback()
            raise RecommendationGenerationConflict(
                "PostgreSQL rejected Recommendation generation enqueue"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> GenerationExecution:
        require_project_role(principal, project_id, allowed=_READER_ROLES)
        return self._reads.get(project_id=project_id, job_id=job_id)

    def cancel(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> RecommendationGenerationJob:
        require_project_role(principal, project_id, allowed=_CONTRIBUTOR_ROLES)
        key_hash = idempotency_hash(idempotency_key)
        request_hash = canonical_hash(
            {
                "operation": "cancel",
                "project_id": project_id,
                "job_id": job_id,
                "expected_version": expected_version,
            }
        )
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            self._lock_idempotency(connection, project_id, key_hash)
            result = connection.execute(
                """SELECT job_id, durable_status, cancel_requested, replayed
                   FROM geo_cancel_recommendation_generation(
                       %s, %s, %s, %s, %s, %s
                   )""",
                (
                    project_id,
                    job_id,
                    expected_version,
                    key_hash,
                    request_hash,
                    self._clock(),
                ),
            ).fetchone()
            if result is None or result["job_id"] != job_id:
                raise RecommendationGenerationConflict(
                    "Recommendation generation cancellation did not return its Job"
                )
            job = self._reads.get_in_connection(
                connection,
                project_id=project_id,
                job_id=job_id,
            )
            connection.commit()
            return job
        except RecommendationGenerationConflict:
            connection.rollback()
            raise
        except psycopg.Error as error:
            connection.rollback()
            raise RecommendationGenerationConflict(
                "PostgreSQL rejected Recommendation generation cancellation"
            ) from error
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _lock_idempotency(connection: Any, project_id: UUID, key_hash: str) -> None:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"recommendation-generation:{project_id}:{key_hash}",),
        )


__all__ = ["PsycopgRecommendationGenerationSubmission"]
