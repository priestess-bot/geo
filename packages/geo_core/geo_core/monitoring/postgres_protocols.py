"""Protocol and approved-query persistence for the monitoring repository."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from psycopg.types.json import Jsonb

from geo_core.monitoring.domain import (
    MonitoringConflict,
    MonitoringNotFound,
    MonitoringProtocol,
    MonitoringRuleViolation,
    ProtocolQuery,
    QuerySuggestion,
)
from geo_core.monitoring.postgres_mappers import (
    protocol_from_row as _protocol,
    protocol_query_from_row as _protocol_query_from_row,
    suggestion_from_row as _suggestion,
)
from geo_core.monitoring.source_contract import SourceStratumKey


class MonitoringProtocolsMixin:
    _one: Any
    _optional: Any
    _many: Any

    def campaign_matches_market(
        self, *, project_id: UUID, campaign_id: UUID, market_profile_id: UUID
    ) -> bool:
        return (
            self._optional(
                """SELECT id FROM geo_campaigns
                   WHERE project_id = %s AND id = %s AND market_profile_id = %s""",
                (project_id, campaign_id, market_profile_id),
                "validate the monitoring campaign market",
            )
            is not None
        )

    def create_protocol(self, **values: Any) -> MonitoringProtocol:
        return _protocol(
            self._one(
                """
                INSERT INTO monitoring_protocols
                  (project_id, campaign_id, market_profile_id, name, platform, locale, device,
                   sample_size, minimum_valid_repeats, window_days,
                   statistics_method_version, statistics_contract_version,
                   source_strata_snapshot, source_strata_hash, created_by)
                VALUES (%(project_id)s, %(campaign_id)s, %(market_profile_id)s, %(name)s,
                        %(platform)s, %(locale)s, %(device)s, %(sample_size)s,
                        %(minimum_valid_repeats)s, %(window_days)s,
                        %(statistics_method_version)s, %(statistics_contract_version)s,
                        %(source_strata_snapshot)s,
                        %(source_strata_hash)s, %(actor_id)s)
                RETURNING *
                """,
                {
                    **values,
                    "platform": values["platform"].value,
                    "device": values["device"].value,
                    "source_strata_snapshot": Jsonb(
                        [
                            item.canonical_value()
                            for item in cast(tuple[SourceStratumKey, ...], values["source_strata"])
                        ]
                    ),
                },
                "create the monitoring protocol",
            )
        )

    def get_protocol(
        self, *, project_id: UUID, campaign_id: UUID, protocol_id: UUID
    ) -> MonitoringProtocol | None:
        row = self._optional(
            """SELECT * FROM monitoring_protocols
               WHERE project_id = %s AND campaign_id = %s AND id = %s""",
            (project_id, campaign_id, protocol_id),
            "read the monitoring protocol",
        )
        return _protocol(row) if row else None

    def list_protocols(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[MonitoringProtocol, ...]:
        rows = self._many(
            """SELECT * FROM monitoring_protocols
               WHERE project_id = %s AND campaign_id = %s
               ORDER BY created_at DESC, id DESC""",
            (project_id, campaign_id),
            "list monitoring protocols",
        )
        return tuple(_protocol(row) for row in rows)

    def bind_question_set(self, **values: Any) -> MonitoringProtocol:
        protocol = self._optional(
            """SELECT * FROM monitoring_protocols
               WHERE id = %(protocol_id)s AND project_id = %(project_id)s
                 AND campaign_id = %(campaign_id)s
               FOR UPDATE""",
            values,
            "lock the QuestionSet monitoring protocol",
        )
        if protocol is None:
            raise MonitoringNotFound("The monitoring protocol does not exist.")
        if protocol.get("question_set_id") is not None:
            if (
                protocol["question_set_id"] == values["question_set_id"]
                and protocol["question_set_hash"] == values["confirmed_content_hash"]
            ):
                return _protocol(protocol)
            raise MonitoringConflict("The monitoring protocol already has a QuestionSet binding.")
        question_set = self._optional(
            """SELECT id, content_hash FROM knowledge_question_sets
               WHERE id = %(question_set_id)s AND project_id = %(project_id)s
                 AND campaign_id = %(campaign_id)s
                 AND content_hash = %(confirmed_content_hash)s AND status = 'frozen'
               FOR SHARE""",
            values,
            "lock the frozen QuestionSet",
        )
        if protocol["status"] != "draft" or question_set is None:
            raise MonitoringConflict("A draft protocol can bind only the exact frozen QuestionSet.")
        items = self._many(
            """SELECT item.id, item.question_candidate_id, item.ordinal,
                      item.query_text_snapshot, item.query_kind_snapshot,
                      item.query_cluster_key,
                      geo_question_candidate_sources_current(
                          item.question_candidate_id
                      ) AS sources_current
               FROM knowledge_question_set_items AS item
               WHERE item.question_set_id = %(question_set_id)s
                 AND item.project_id = %(project_id)s
                 AND item.campaign_id = %(campaign_id)s
               ORDER BY item.ordinal""",
            values,
            "read the frozen QuestionSet items",
        )
        if not items:
            raise MonitoringConflict("The frozen QuestionSet has no items.")
        if any(not item["sources_current"] for item in items):
            raise MonitoringConflict(
                "The frozen QuestionSet has stale Knowledge sources and cannot be bound."
            )
        bound = self._one(
            """UPDATE monitoring_protocols
               SET question_set_id = %(question_set_id)s,
                   question_set_hash = %(confirmed_content_hash)s,
                   question_set_bound_by = %(actor_id)s,
                   question_set_bound_at = clock_timestamp()
               WHERE id = %(protocol_id)s AND project_id = %(project_id)s
                 AND campaign_id = %(campaign_id)s
               RETURNING *""",
            values,
            "bind the frozen QuestionSet",
        )
        for item in items:
            suggestion = self._one(
                """INSERT INTO monitoring_query_suggestions
                     (project_id, protocol_id, query_text, query_kind, rationale,
                      status, query_cluster_key, suggested_by, decided_by, decided_at,
                      question_set_item_id, question_candidate_id)
                   VALUES (%s, %s, %s, %s, %s, 'approved', %s, %s, %s,
                           clock_timestamp(), %s, %s)
                   RETURNING id""",
                (
                    values["project_id"],
                    values["protocol_id"],
                    item["query_text_snapshot"],
                    item["query_kind_snapshot"],
                    "Frozen QuestionSet projection",
                    item["query_cluster_key"],
                    values["actor_id"],
                    values["actor_id"],
                    item["id"],
                    item["question_candidate_id"],
                ),
                "project a QuestionSet suggestion",
            )
            query = self._one(
                """INSERT INTO monitoring_queries
                     (project_id, market_profile_id, query_text, query_kind, locale)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (
                    values["project_id"],
                    protocol["market_profile_id"],
                    item["query_text_snapshot"],
                    item["query_kind_snapshot"],
                    protocol["locale"],
                ),
                "create a QuestionSet monitoring query",
            )
            self._one(
                """INSERT INTO campaign_monitoring_queries
                     (campaign_id, project_id, monitoring_query_id)
                   VALUES (%s, %s, %s) RETURNING monitoring_query_id""",
                (values["campaign_id"], values["project_id"], query["id"]),
                "bind a QuestionSet query to the campaign",
            )
            self._one(
                """INSERT INTO monitoring_protocol_queries
                     (project_id, protocol_id, monitoring_query_id, suggestion_id,
                      ordinal, query_text_snapshot, query_kind_snapshot,
                      locale_snapshot, query_cluster_key, approved_by,
                      question_set_item_id, question_candidate_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    values["project_id"],
                    values["protocol_id"],
                    query["id"],
                    suggestion["id"],
                    item["ordinal"],
                    item["query_text_snapshot"],
                    item["query_kind_snapshot"],
                    protocol["locale"],
                    item["query_cluster_key"],
                    values["actor_id"],
                    item["id"],
                    item["question_candidate_id"],
                ),
                "bind a QuestionSet query to the protocol",
            )
        return _protocol(bound)

    def create_suggestion(self, **values: Any) -> QuerySuggestion:
        row = self._one(
            """
            INSERT INTO monitoring_query_suggestions
              (project_id, protocol_id, query_text, query_kind, rationale,
               query_cluster_key, suggested_by)
            SELECT protocol.project_id, protocol.id, %(query_text)s, %(query_kind)s,
                   %(rationale)s, %(query_cluster_key)s, %(actor_id)s
            FROM monitoring_protocols protocol
            WHERE protocol.project_id = %(project_id)s
              AND protocol.campaign_id = %(campaign_id)s
              AND protocol.id = %(protocol_id)s
            RETURNING *, NULL::uuid AS monitoring_query_id
            """,
            values,
            "create the monitoring query suggestion",
        )
        return _suggestion(row)

    def list_suggestions(
        self, *, project_id: UUID, campaign_id: UUID, protocol_id: UUID
    ) -> tuple[QuerySuggestion, ...]:
        rows = self._many(
            """
            SELECT s.*, pq.monitoring_query_id
            FROM monitoring_query_suggestions s
            LEFT JOIN monitoring_protocol_queries pq
              ON pq.suggestion_id = s.id AND pq.project_id = s.project_id
            JOIN monitoring_protocols protocol
              ON protocol.id = s.protocol_id AND protocol.project_id = s.project_id
            WHERE s.project_id = %s AND protocol.campaign_id = %s AND s.protocol_id = %s
            ORDER BY s.created_at, s.id
            """,
            (project_id, campaign_id, protocol_id),
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
        if not row["query_cluster_key"]:
            raise MonitoringRuleViolation(
                "legacy query suggestions without a query cluster key cannot be approved; "
                "create a new suggestion with an explicit cluster key"
            )
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
               query_text_snapshot, query_kind_snapshot, locale_snapshot,
               query_cluster_key, approved_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                row["query_cluster_key"],
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
            WHERE project_id = %(project_id)s AND campaign_id = %(campaign_id)s
              AND id = %(protocol_id)s AND status = 'draft'
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
            WHERE project_id = %(project_id)s AND campaign_id = %(campaign_id)s
              AND id = %(protocol_id)s
              AND status = 'approved'
            RETURNING *
            """,
            values,
            "freeze the monitoring protocol",
        )
        if row is None:
            raise MonitoringConflict("The monitoring protocol is not approved or was frozen.")
        return _protocol(row)

    def _protocol_query(self, project_id: UUID, protocol_id: UUID, query_id: UUID) -> ProtocolQuery:
        row = self._optional(
            """SELECT * FROM monitoring_protocol_queries
               WHERE project_id = %s AND protocol_id = %s AND monitoring_query_id = %s""",
            (project_id, protocol_id, query_id),
            "read the approved protocol query",
        )
        if row is None:
            raise MonitoringNotFound("The approved protocol query does not exist.")
        return _protocol_query_from_row(row)
