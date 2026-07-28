"""Internal API facade for PostgreSQL-backed Recommendations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

import psycopg

from geo_core.access.models import AccessPrincipal
from geo_core.project_scope import set_project_scope
from geo_core.recommendations.application import RecommendationApplication
from geo_core.recommendations.application_support import (
    RecommendationNotFound,
    require_project_role,
)
from geo_core.recommendations.generation_admission import (
    RecommendationGenerationSelection,
)
from geo_core.recommendations.generation_contracts import (
    GenerationExecution,
    RecommendationGenerationJob,
)
from geo_core.recommendations.models import RecommendationWorkflow
from geo_core.recommendations.postgres.rows import workflow_from_row


_READ_ROLES = frozenset({"owner", "admin", "analyst", "viewer"})


class RecommendationGenerationApiPort(Protocol):
    def enqueue(
        self,
        principal: AccessPrincipal,
        *,
        selection: RecommendationGenerationSelection,
        idempotency_key: str,
        recovery_of_attempt_id: UUID | None = None,
        dify_reconciliation_token: str | None = None,
    ) -> GenerationExecution: ...

    def get(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> GenerationExecution: ...

    def cancel(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> RecommendationGenerationJob: ...


class PostgresRecommendationPage:
    def __init__(
        self,
        *,
        items: tuple[RecommendationWorkflow, ...],
        total: int,
        limit: int,
        offset: int,
    ) -> None:
        self.items = items
        self.total = total
        self.limit = limit
        self.offset = offset


class PsycopgRecommendationApi:
    def __init__(
        self,
        *,
        application: RecommendationApplication,
        generation: RecommendationGenerationApiPort,
        connection_factory: Callable[[], Any],
    ) -> None:
        self._application = application
        self._generation = generation
        self._connect = connection_factory

    def enqueue_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        selection: RecommendationGenerationSelection,
        idempotency_key: str,
        recovery_of_attempt_id: UUID | None = None,
        dify_reconciliation_token: str | None = None,
    ) -> GenerationExecution:
        return self._generation.enqueue(
            principal,
            selection=selection,
            idempotency_key=idempotency_key,
            recovery_of_attempt_id=recovery_of_attempt_id,
            dify_reconciliation_token=dify_reconciliation_token,
        )

    def get_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
    ) -> GenerationExecution:
        return self._generation.get(
            principal,
            project_id=project_id,
            job_id=job_id,
        )

    def cancel_generation_job(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> RecommendationGenerationJob:
        return self._generation.cancel(
            principal,
            project_id=project_id,
            job_id=job_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def get_recommendation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        recommendation_id: UUID,
    ) -> RecommendationWorkflow:
        require_project_role(principal, project_id, allowed=_READ_ROLES)
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                _WORKFLOW_SELECT
                + """ WHERE current.project_id = %s
                           AND current.recommendation_id = %s
                       ORDER BY current.version DESC LIMIT 1""",
                (project_id, recommendation_id),
            ).fetchone()
            connection.rollback()
            if row is None:
                raise RecommendationNotFound(
                    "Recommendation does not exist in the project scope"
                )
            return workflow_from_row(row)
        except psycopg.Error as error:
            connection.rollback()
            raise RecommendationNotFound(
                "Recommendation could not be read in the project scope"
            ) from error
        finally:
            connection.close()

    def list_recommendations(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> PostgresRecommendationPage:
        require_project_role(principal, project_id, allowed=_READ_ROLES)
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            total_row = connection.execute(
                """SELECT count(DISTINCT recommendation_id) AS count
                   FROM recommendation_workflow_versions WHERE project_id = %s""",
                (project_id,),
            ).fetchone()
            rows = connection.execute(
                _WORKFLOW_SELECT
                + """ WHERE current.project_id = %s
                         AND NOT EXISTS (
                           SELECT 1 FROM recommendation_workflow_versions AS newer
                           WHERE newer.project_id = current.project_id
                             AND newer.recommendation_id = current.recommendation_id
                             AND newer.version > current.version
                         )
                       ORDER BY current.created_at DESC, current.recommendation_id DESC
                       LIMIT %s OFFSET %s""",
                (project_id, limit, offset),
            ).fetchall()
            connection.rollback()
            return PostgresRecommendationPage(
                items=tuple(workflow_from_row(row) for row in rows),
                total=int(total_row["count"]),
                limit=limit,
                offset=offset,
            )
        except psycopg.Error as error:
            connection.rollback()
            raise RecommendationNotFound(
                "Recommendations could not be listed in the project scope"
            ) from error
        finally:
            connection.close()

    def __getattr__(self, name: str) -> Callable[..., object]:
        return getattr(self._application, name)


_WORKFLOW_SELECT = """SELECT current.project_id, current.recommendation_id,
                              current.version, current.status,
                              current.recommendation_type,
                              current.proposed_draft_kind,
                              current.evidence_graph_hash,
                              current.input_fingerprint, current.valid_until,
                              current.created_by, current.workflow_payload,
                              current.workflow_payload_hash
                       FROM recommendation_workflow_versions AS current"""


__all__ = [
    "PostgresRecommendationPage",
    "PsycopgRecommendationApi",
    "RecommendationGenerationApiPort",
]
