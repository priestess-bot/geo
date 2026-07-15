"""psycopg adapter for governed monitoring and customer-safe projections."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import json
from types import TracebackType
from typing import Any, Literal, TypeAlias, cast
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.domain import (
    CitationDraft,
    MeasurementWindow,
    MonitoringConflict,
    MonitoringNotFound,
    MonitoringObservation,
    MonitoringPersistenceUnavailable,
    MonitoringProtocol,
    ObservationDraft,
    ProtocolQuery,
    QuerySuggestion,
    ResultStatus,
    VerificationStatus,
)
from geo_core.monitoring.ports import MonitoringRepository, MonitoringUnitOfWork
from geo_core.monitoring.postgres_mappers import (
    citation_from_row as _citation,
    protocol_from_row as _protocol,
    protocol_query_from_row as _protocol_query_from_row,
    suggestion_from_row as _suggestion,
)
from geo_core.monitoring.postgres_lineage import MonitoringLineageMixin
from geo_core.monitoring.postgres_reporting import MonitoringReportingMixin


Connection: TypeAlias = psycopg.Connection[dict[str, Any]]
ConnectionFactory = Callable[[], Connection]


def _failure(operation: str, error: psycopg.Error) -> RuntimeError:
    if isinstance(error, UniqueViolation):
        return MonitoringConflict(f"The {operation} conflicts with an immutable record.")
    return MonitoringPersistenceUnavailable(f"PostgreSQL could not {operation}.")


class PsycopgMonitoringRepository(MonitoringLineageMixin, MonitoringReportingMixin):
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_protocol(self, **values: Any) -> MonitoringProtocol:
        return _protocol(
            self._one(
                """
                INSERT INTO monitoring_protocols
                  (project_id, campaign_id, market_profile_id, name, platform, locale, device,
                   sample_size, window_days, created_by)
                VALUES (%(project_id)s, %(campaign_id)s, %(market_profile_id)s, %(name)s,
                        %(platform)s, %(locale)s, %(device)s, %(sample_size)s,
                        %(window_days)s, %(actor_id)s)
                RETURNING *
                """,
                {**values, "platform": values["platform"].value, "device": values["device"].value},
                "create the monitoring protocol",
            )
        )

    def get_protocol(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> MonitoringProtocol | None:
        row = self._optional(
            "SELECT * FROM monitoring_protocols WHERE project_id = %s AND id = %s",
            (project_id, protocol_id),
            "read the monitoring protocol",
        )
        return _protocol(row) if row else None

    def list_protocols(self, *, project_id: UUID) -> tuple[MonitoringProtocol, ...]:
        rows = self._many(
            """SELECT * FROM monitoring_protocols
               WHERE project_id = %s ORDER BY created_at DESC, id DESC""",
            (project_id,),
            "list monitoring protocols",
        )
        return tuple(_protocol(row) for row in rows)

    def create_suggestion(self, **values: Any) -> QuerySuggestion:
        row = self._one(
            """
            INSERT INTO monitoring_query_suggestions
              (project_id, protocol_id, query_text, query_kind, rationale, suggested_by)
            VALUES (%(project_id)s, %(protocol_id)s, %(query_text)s, %(query_kind)s,
                    %(rationale)s, %(actor_id)s)
            RETURNING *, NULL::uuid AS monitoring_query_id
            """,
            values,
            "create the monitoring query suggestion",
        )
        return _suggestion(row)

    def list_suggestions(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> tuple[QuerySuggestion, ...]:
        rows = self._many(
            """
            SELECT s.*, pq.monitoring_query_id
            FROM monitoring_query_suggestions s
            LEFT JOIN monitoring_protocol_queries pq
              ON pq.suggestion_id = s.id AND pq.project_id = s.project_id
            WHERE s.project_id = %s AND s.protocol_id = %s
            ORDER BY s.created_at, s.id
            """,
            (project_id, protocol_id),
            "list monitoring query suggestions",
        )
        return tuple(_suggestion(row) for row in rows)

    def approve_suggestion(
        self,
        *,
        project_id: UUID,
        protocol: MonitoringProtocol,
        suggestion_id: UUID,
        actor_id: UUID,
    ) -> tuple[QuerySuggestion, ProtocolQuery]:
        row = self._optional(
            """
            SELECT s.*, pq.monitoring_query_id
            FROM monitoring_query_suggestions s
            LEFT JOIN monitoring_protocol_queries pq
              ON pq.suggestion_id = s.id AND pq.project_id = s.project_id
            WHERE s.project_id = %s AND s.protocol_id = %s AND s.id = %s
            FOR UPDATE OF s
            """,
            (project_id, protocol.id, suggestion_id),
            "lock the monitoring query suggestion",
        )
        if row is None:
            raise MonitoringNotFound("The query suggestion does not exist in this project.")
        if row["status"] == "approved" and row["monitoring_query_id"]:
            query = self._protocol_query(project_id, protocol.id, row["monitoring_query_id"])
            return _suggestion(row), query
        if row["status"] != "suggested":
            raise MonitoringConflict("A rejected query suggestion cannot be approved.")
        query_row = self._one(
            """
            INSERT INTO monitoring_queries
              (project_id, market_profile_id, query_text, query_kind, locale)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                project_id,
                protocol.market_profile_id,
                row["query_text"],
                row["query_kind"],
                protocol.locale,
            ),
            "create the approved monitoring query",
        )
        ordinal_row = self._one(
            """SELECT COALESCE(max(ordinal), 0) + 1 AS ordinal
               FROM monitoring_protocol_queries
               WHERE project_id = %s AND protocol_id = %s""",
            (project_id, protocol.id),
            "allocate the monitoring query ordinal",
        )
        membership = self._one(
            """
            INSERT INTO monitoring_protocol_queries
              (project_id, protocol_id, monitoring_query_id, suggestion_id, ordinal,
               query_text_snapshot, query_kind_snapshot, locale_snapshot, approved_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                project_id,
                protocol.id,
                query_row["id"],
                suggestion_id,
                ordinal_row["ordinal"],
                row["query_text"],
                row["query_kind"],
                protocol.locale,
                actor_id,
            ),
            "bind the approved query to the monitoring protocol",
        )
        self._one(
            """
            INSERT INTO campaign_monitoring_queries
              (campaign_id, project_id, monitoring_query_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (campaign_id, monitoring_query_id) DO UPDATE
            SET project_id = EXCLUDED.project_id
            RETURNING monitoring_query_id
            """,
            (protocol.campaign_id, project_id, query_row["id"]),
            "bind the approved query to the campaign",
        )
        decided = self._one(
            """
            UPDATE monitoring_query_suggestions
            SET status = 'approved', decided_by = %s, decided_at = clock_timestamp()
            WHERE project_id = %s AND id = %s
            RETURNING *, %s::uuid AS monitoring_query_id
            """,
            (actor_id, project_id, suggestion_id, query_row["id"]),
            "approve the monitoring query suggestion",
        )
        return _suggestion(decided), _protocol_query_from_row(membership)

    def approve_protocol(self, **values: Any) -> MonitoringProtocol:
        row = self._optional(
            """
            UPDATE monitoring_protocols
            SET status = 'approved', approved_by = %(actor_id)s,
                approved_at = clock_timestamp()
            WHERE project_id = %(project_id)s AND id = %(protocol_id)s AND status = 'draft'
            RETURNING *
            """,
            values,
            "approve the monitoring protocol",
        )
        if row is None:
            raise MonitoringConflict("The monitoring protocol is not an approvable draft.")
        return _protocol(row)

    def freeze_protocol(self, **values: Any) -> MonitoringProtocol:
        row = self._optional(
            """
            UPDATE monitoring_protocols
            SET status = 'frozen', frozen_by = %(actor_id)s,
                frozen_at = clock_timestamp(), protocol_hash = %(protocol_hash)s
            WHERE project_id = %(project_id)s AND id = %(protocol_id)s
              AND status = 'approved'
            RETURNING *
            """,
            values,
            "freeze the monitoring protocol",
        )
        if row is None:
            raise MonitoringConflict("The monitoring protocol is not approved or was frozen.")
        return _protocol(row)

    def import_observation(self, **values: Any) -> MonitoringObservation:
        draft = cast(ObservationDraft, values["draft"])
        existing = self._optional(
            """
            SELECT * FROM monitoring_observations
            WHERE project_id = %s AND (
                idempotency_key = %s OR
                (protocol_id = %s AND monitoring_query_id = %s
                 AND measurement_window = %s AND sample_index = %s)
            )
            ORDER BY (idempotency_key = %s) DESC LIMIT 1
            """,
            (
                values["project_id"],
                values["idempotency_key"],
                values["protocol_id"],
                draft.monitoring_query_id,
                draft.measurement_window.value,
                draft.sample_index,
                values["idempotency_key"],
            ),
            "check the immutable observation slot",
        )
        if existing is not None:
            if existing["payload_hash"] != values["payload_hash"]:
                raise MonitoringConflict(
                    "The idempotency key or sample slot already has different content."
                )
            return self._observation(existing, replayed=True)
        raw_citations = [
            {
                "url": item.url,
                "title": item.title,
                "verification_status": item.verification_status.value,
            }
            for item in draft.citations
        ]
        row = self._one(
            """
            INSERT INTO monitoring_observations
              (project_id, protocol_id, campaign_id, monitoring_query_id, measurement_window,
               sample_index, result_status, eligible, ineligible_reasons,
               url_verification_status, recommendation_present,
               primary_product_mentioned, competitor_mentioned, raw_answer,
               raw_result, raw_citations, artifact_uri, artifact_hash,
               configured_model, provider_reported_model, ui_surface, ui_metadata,
               confounding_factors, observed_at, imported_by, idempotency_key, payload_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                values["project_id"], values["protocol_id"], values["campaign_id"],
                draft.monitoring_query_id,
                draft.measurement_window.value, draft.sample_index, draft.result_status.value,
                draft.eligible, list(draft.ineligible_reasons),
                draft.url_verification_status.value, draft.recommendation_present,
                draft.primary_product_mentioned, draft.competitor_mentioned, draft.raw_answer,
                Jsonb(dict(draft.raw_result)), Jsonb(raw_citations), draft.artifact_uri,
                draft.artifact_hash, draft.configured_model, draft.provider_reported_model,
                draft.ui_surface, Jsonb(dict(draft.ui_metadata)),
                list(draft.confounding_factors), draft.observed_at, values["actor_id"],
                values["idempotency_key"], values["payload_hash"],
            ),
            "import the monitoring observation",
        )
        for index, citation in enumerate(draft.citations):
            self._one(
                """
                INSERT INTO monitoring_observation_citations
                  (project_id, observation_id, citation_index, url, title,
                   destination_id, submission_id, verification_status, verified_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    values["project_id"], row["id"], index, citation.url, citation.title,
                    citation.destination_id, citation.submission_id,
                    citation.verification_status.value, citation.verified_at,
                ),
                "import the observation citation",
            )
        return self._observation(row, replayed=False)

    def list_observations(
        self,
        *,
        project_id: UUID,
        protocol_id: UUID,
        window: MeasurementWindow | None,
    ) -> tuple[MonitoringObservation, ...]:
        condition = "AND measurement_window = %s" if window else ""
        parameters: tuple[object, ...] = (
            (project_id, protocol_id, window.value) if window else (project_id, protocol_id)
        )
        rows = self._many(
            f"""SELECT * FROM monitoring_observations
                WHERE project_id = %s AND protocol_id = %s {condition}
                ORDER BY measurement_window, monitoring_query_id, sample_index""",
            parameters,
            "list monitoring observations",
        )
        return tuple(self._observation(row, replayed=False) for row in rows)

    def campaign_destination_state(self, *, project_id: UUID, campaign_id: UUID):
        from geo_core.monitoring.domain import CampaignDestinationState

        rows = self._many(
            """
            SELECT o.destination_id, o.status, d.policy_status,
                   EXISTS (
                       SELECT 1
                       FROM publication_requests r
                       JOIN publication_submissions s
                         ON s.publication_request_id = r.id AND s.project_id = r.project_id
                       JOIN placement_package_versions pv
                         ON pv.id = r.package_version_id AND pv.project_id = r.project_id
                       JOIN placement_packages pp
                         ON pp.id = pv.package_id AND pp.project_id = pv.project_id
                       JOIN placement_opportunities source_opportunity
                         ON source_opportunity.id = pp.opportunity_id
                        AND source_opportunity.project_id = pp.project_id
                       WHERE r.project_id = o.project_id
                         AND r.destination_id = o.destination_id
                         AND s.status = 'verified'
                         AND source_opportunity.campaign_id = %s
                   ) AS verified
            FROM placement_opportunities o
            JOIN publication_destinations d
              ON d.id = o.destination_id AND d.project_id = o.project_id
            WHERE o.project_id = %s AND o.campaign_id = %s
              AND o.status <> 'cancelled'
            """,
            (campaign_id, project_id, campaign_id),
            "read campaign destination state",
        )
        selected = frozenset(cast(UUID, row["destination_id"]) for row in rows)
        qualified = frozenset(
            cast(UUID, row["destination_id"])
            for row in rows
            if row["policy_status"] == "approved"
            and row["status"] in {"qualified", "briefing", "in_progress", "completed"}
        )
        verified = frozenset(
            cast(UUID, row["destination_id"]) for row in rows if row["verified"]
        )
        return CampaignDestinationState(selected, qualified, verified)

    def _protocol_query(
        self, project_id: UUID, protocol_id: UUID, query_id: UUID
    ) -> ProtocolQuery:
        row = self._optional(
            """SELECT * FROM monitoring_protocol_queries
               WHERE project_id = %s AND protocol_id = %s AND monitoring_query_id = %s""",
            (project_id, protocol_id, query_id),
            "read the approved protocol query",
        )
        if row is None:
            raise MonitoringNotFound("The approved protocol query does not exist.")
        return _protocol_query_from_row(row)

    def _observation(
        self, row: Mapping[str, Any], *, replayed: bool
    ) -> MonitoringObservation:
        citation_rows = self._many(
            """
            SELECT c.*, EXISTS (
                SELECT 1
                FROM publication_submissions s
                JOIN publication_requests r
                  ON r.id = s.publication_request_id AND r.project_id = s.project_id
                JOIN placement_package_versions version
                  ON version.id = r.package_version_id AND version.project_id = r.project_id
                JOIN placement_packages package
                  ON package.id = version.package_id AND package.project_id = version.project_id
                JOIN placement_opportunities opportunity
                  ON opportunity.id = package.opportunity_id
                 AND opportunity.project_id = package.project_id
                WHERE s.id = c.submission_id AND s.project_id = c.project_id
                  AND s.status = 'verified' AND s.submitted_url = c.url
                  AND r.destination_id = c.destination_id
                  AND opportunity.campaign_id = %s
            ) AS verified_placement
            FROM monitoring_observation_citations c
            WHERE c.project_id = %s AND c.observation_id = %s
            ORDER BY c.citation_index
            """,
            (row["campaign_id"], row["project_id"], row["id"]),
            "read observation citations",
        )
        citations = tuple(_citation(item) for item in citation_rows)
        draft_citations = tuple(
            CitationDraft(
                url=item.url,
                title=item.title,
                verification_status=item.verification_status,
                verified_at=cast(datetime | None, citation_rows[index]["verified_at"]),
                destination_id=item.destination_id,
                submission_id=item.submission_id,
            )
            for index, item in enumerate(citations)
        )
        draft = ObservationDraft(
            monitoring_query_id=cast(UUID, row["monitoring_query_id"]),
            measurement_window=MeasurementWindow(str(row["measurement_window"])),
            sample_index=int(row["sample_index"]),
            result_status=ResultStatus(str(row["result_status"])),
            eligible=bool(row["eligible"]),
            ineligible_reasons=tuple(row["ineligible_reasons"]),
            url_verification_status=VerificationStatus(str(row["url_verification_status"])),
            recommendation_present=bool(row["recommendation_present"]),
            primary_product_mentioned=bool(row["primary_product_mentioned"]),
            competitor_mentioned=bool(row["competitor_mentioned"]),
            raw_answer=cast(str | None, row["raw_answer"]),
            raw_result=cast(Mapping[str, object], row["raw_result"]),
            citations=draft_citations,
            artifact_uri=cast(str | None, row["artifact_uri"]),
            artifact_hash=cast(str | None, row["artifact_hash"]),
            configured_model=str(row["configured_model"]),
            provider_reported_model=cast(str | None, row["provider_reported_model"]),
            ui_surface=str(row["ui_surface"]),
            ui_metadata=cast(Mapping[str, object], row["ui_metadata"]),
            confounding_factors=tuple(row["confounding_factors"]),
            observed_at=cast(datetime, row["observed_at"]),
        )
        return MonitoringObservation(
            id=cast(UUID, row["id"]),
            project_id=cast(UUID, row["project_id"]),
            protocol_id=cast(UUID, row["protocol_id"]),
            campaign_id=cast(UUID, row["campaign_id"]),
            draft=draft,
            payload_hash=str(row["payload_hash"]),
            citations=citations,
            created_at=cast(datetime, row["created_at"]),
            replayed=replayed,
        )

    def _one(self, query: str, parameters: Any, operation: str) -> dict[str, Any]:
        row = self._optional(query, parameters, operation)
        if row is None:
            raise MonitoringPersistenceUnavailable(
                f"PostgreSQL did not return a row while attempting to {operation}."
            )
        return row

    def _optional(
        self, query: str, parameters: Any, operation: str
    ) -> dict[str, Any] | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, parameters)
                return cursor.fetchone()
        except psycopg.Error as error:
            raise _failure(operation, error) from error

    def _many(self, query: str, parameters: Any, operation: str) -> list[dict[str, Any]]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, parameters)
                return list(cursor.fetchall())
        except psycopg.Error as error:
            raise _failure(operation, error) from error


class PsycopgMonitoringUnitOfWork:
    monitoring: MonitoringRepository

    def __init__(self, connection_factory: ConnectionFactory, principal: AccessPrincipal) -> None:
        self._connection_factory = connection_factory
        self._principal = principal
        self._connection: Connection | None = None
        self._committed = False

    def __enter__(self) -> "PsycopgMonitoringUnitOfWork":
        try:
            self._connection = self._connection_factory()
            self.connection.execute("SET LOCAL statement_timeout = '10s'")
            self.monitoring = PsycopgMonitoringRepository(self.connection)
            values = {
                "geo.actor_id": str(self._principal.identity_id),
                "geo.identity_id": str(self._principal.identity_id),
                "geo.tenant_id": str(self._principal.tenant_id),
                "geo.project_id": str(self._principal.project_ids[0])
                if self._principal.project_ids
                else "",
                "geo.project_ids": json.dumps([str(item) for item in self._principal.project_ids]),
            }
            with self.connection.cursor() as cursor:
                for name, value in values.items():
                    cursor.execute(
                        sql.SQL("SELECT set_config({}, %s, true)").format(sql.Literal(name)),
                        (value,),
                    )
        except psycopg.Error as error:
            self._close()
            raise _failure("open a monitoring transaction", error) from error
        return self

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("The Monitoring Unit of Work has not been entered.")
        return self._connection

    def commit(self) -> None:
        self.connection.commit()
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        try:
            if self._connection is not None and not self._committed:
                self._connection.rollback()
        finally:
            self._close()
        return False

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class PsycopgMonitoringUnitOfWorkFactory:
    def __init__(self, database_url: str, *, connect_timeout: int = 5) -> None:
        if not database_url.strip():
            raise ValueError("database_url is required")
        self._database_url = database_url.strip()
        self._connect_timeout = connect_timeout

    def __call__(self, principal: AccessPrincipal) -> MonitoringUnitOfWork:
        return PsycopgMonitoringUnitOfWork(self._connect, principal)

    def _connect(self) -> Connection:
        return psycopg.connect(
            self._database_url, connect_timeout=self._connect_timeout, row_factory=dict_row
        )
