from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from geno_core.models import (
    ActionRecommendation,
    AnswerAnalysis,
    AuditEvent,
    CitationGraphResult,
    CollectionFailureRecord,
    ContentDraft,
    IntegrationConnector,
    LocalizedKnowledgeFact,
    ManualDistributionRecord,
    ProjectBootstrap,
    RawEvidenceRecord,
    ReportExport,
    RetestComparison,
    RetestSchedule,
    RuntimeCitationGraph,
    RuntimeCitationGraphNode,
    RuntimeCitationGraphPage,
    RuntimeEvidencePage,
    RuntimeEvidenceRun,
    RuntimeReportExport,
    RuntimeReportExportPage,
    RuntimeScoreSnapshot,
    RuntimeScoreSnapshotPage,
    RuntimeScoreSnapshotRun,
    ScoreContribution,
    TraceabilityBundle,
    VisibilityScoreSnapshot,
)


class DbCursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Any: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> Any: ...

    def __enter__(self) -> "DbCursor": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class DbConnection(Protocol):
    def cursor(self) -> DbCursor: ...

    def commit(self) -> None: ...


def _json_compatible(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _json_payload(value: object) -> object:
    if is_dataclass(value):
        value = asdict(value)
    payload = _json_compatible(value)
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return payload
    return Jsonb(payload)


def _uuid_array(values: tuple[str, ...] | list[str]) -> list[object]:
    converted: list[object] = []
    for value in values:
        try:
            converted.append(UUID(str(value)))
        except (TypeError, ValueError):
            converted.append(str(value))
    return converted


def _uuid(value: str | None) -> object | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return str(value)


def _datetime(value: datetime | None) -> datetime | None:
    return value


def _row_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return {key: _json_compatible(value) for key, value in row.items()}
    return {column: _json_compatible(row[index]) for index, column in enumerate(columns)}


def _rows_dict(rows: Any, columns: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(_row_dict(row, columns) for row in rows)


def _stable_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("geno", kind, *(str(part) for part in parts)))))


ANSWER_RUN_COLUMNS = (
    "id",
    "project_id",
    "prompt_question_id",
    "platform",
    "surface",
    "access_method",
    "market_code",
    "city",
    "language",
    "device",
    "answer_present",
    "surface_triggered",
    "sample_index",
    "sample_size",
    "model_or_surface",
    "account_state",
    "collector_backend_id",
    "collector_version",
    "collected_at",
    "status",
)
ANSWER_RUN_READ_COLUMNS = ANSWER_RUN_COLUMNS + (
    "prompt_text",
    "prompt_intent_type",
    "prompt_priority",
    "prompt_version",
)
RAW_ANSWER_COLUMNS = ("id", "answer_run_id", "answer_text", "raw_payload", "raw_payload_hash", "created_at")
CITATION_COLUMNS = ("id", "answer_run_id", "url", "domain", "position", "source_type", "created_at")
ASSET_COLUMNS = ("id", "answer_run_id", "asset_type", "url", "content_hash", "created_at")
COLLECTOR_LOG_COLUMNS = (
    "id",
    "answer_run_id",
    "collector_backend_id",
    "event_type",
    "payload",
    "created_at",
)
COLLECTION_COST_COLUMNS = (
    "id",
    "answer_run_id",
    "project_id",
    "collector_backend_id",
    "llm_provider",
    "llm_tokens",
    "llm_cost",
    "proxy_or_vendor_cost",
    "compute_cost",
    "total_cost",
    "created_at",
)
VISIBILITY_SCORE_SNAPSHOT_COLUMNS = (
    "id",
    "project_id",
    "scope_type",
    "scope_value",
    "formula_version",
    "platform_weights_snapshot",
    "final_score",
    "trigger_rate",
    "mention_rate",
    "recommendation_rate",
    "answer_run_ids",
    "created_at",
    "dispersion",
)
SCORE_CONTRIBUTION_COLUMNS = (
    "id",
    "score_snapshot_id",
    "component_name",
    "component_score",
    "weight",
    "weighted_contribution",
    "denominator",
    "evidence_answer_run_ids",
    "positive_evidence_summary",
    "negative_evidence_summary",
    "confidence_note",
    "created_at",
)
ANSWER_ANALYSIS_READ_COLUMNS = (
    "id",
    "answer_run_id",
    "parser_engine_id",
    "analysis_version",
    "payload",
    "confidence",
    "created_at",
)
SOURCE_GRAPH_COLUMNS = (
    "id",
    "project_id",
    "source_url",
    "source_domain",
    "source_type",
    "topic",
    "source_gap_type",
    "answer_run_ids",
    "citation_count",
    "created_at",
)
SOURCE_GRAPH_EVIDENCE_COLUMNS = (
    "id",
    "source_graph_id",
    "answer_run_id",
    "answer_citation_id",
    "relation_type",
    "created_at",
)
SOURCE_GAP_COLUMNS = (
    "id",
    "project_id",
    "source_type",
    "gap_type",
    "observed_count",
    "expected_weight",
    "recommendation",
    "created_at",
)
COMPETITOR_BENCHMARK_COLUMNS = (
    "id",
    "project_id",
    "competitor_name",
    "metric_scope",
    "payload",
    "answer_run_ids",
    "created_at",
)
REPORT_EXPORT_COLUMNS = (
    "id",
    "project_id",
    "market_code",
    "report_version",
    "report_type",
    "score_snapshot_ids",
    "answer_run_ids",
    "prompt_version",
    "scoring_formula_version",
    "platform_weights_snapshot",
    "sample_size",
    "window_start",
    "window_end",
    "methodology_hash",
    "markdown_url",
    "pdf_url",
    "csv_url",
    "exported_by",
    "exported_at",
)
AUDIT_EVENT_COLUMNS = (
    "id",
    "event_type",
    "project_id",
    "actor_type",
    "actor_id",
    "target_type",
    "target_id",
    "before_hash",
    "after_hash",
    "input_refs",
    "output_refs",
    "method_version",
    "reason",
    "created_at",
)


class PostgresEvidenceRepository:
    """DB-API style repository for the GENO runtime evidence chain."""

    def __init__(self, connection: DbConnection) -> None:
        self.connection = connection

    def list_runtime_evidence_runs(
        self,
        *,
        project_id: str | None = None,
        platform: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeEvidencePage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("ar.project_id = %s")
            params.append(_uuid(project_id))
        if platform:
            filters.append("ar.platform = %s")
            params.append(platform)
        if status:
            filters.append("ar.status = %s")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM answer_runs ar {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version
                FROM answer_runs ar
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                {where_clause}
                ORDER BY ar.collected_at DESC, ar.id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            answer_runs = _rows_dict(cursor.fetchall(), ANSWER_RUN_READ_COLUMNS)
            records: list[RuntimeEvidenceRun] = []
            for answer_run in answer_runs:
                answer_run_id = str(answer_run["id"])
                records.append(self._load_runtime_evidence_run(cursor=cursor, answer_run=answer_run, answer_run_id=answer_run_id))
        return RuntimeEvidencePage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=tuple(records),
        )

    def list_runtime_score_snapshots(
        self,
        *,
        project_id: str | None = None,
        scope_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeScoreSnapshotPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if scope_type:
            filters.append("scope_type = %s")
            params.append(scope_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM visibility_score_snapshots {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
                FROM visibility_score_snapshots
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            snapshots = _rows_dict(cursor.fetchall(), VISIBILITY_SCORE_SNAPSHOT_COLUMNS)
            records = tuple(
                self._load_runtime_score_snapshot(
                    cursor=cursor,
                    snapshot=snapshot,
                    snapshot_id=str(snapshot["id"]),
                )
                for snapshot in snapshots
            )
        return RuntimeScoreSnapshotPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def list_runtime_citation_graphs(
        self,
        *,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeCitationGraphPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        params: list[object] = []
        where_clause = ""
        if project_id:
            where_clause = "WHERE project_id = %s"
            params.append(_uuid(project_id))

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(DISTINCT project_id) FROM source_graphs {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT project_id
                FROM source_graphs
                {where_clause}
                GROUP BY project_id
                ORDER BY max(created_at) DESC, project_id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            project_rows = cursor.fetchall()
            project_ids = tuple(str(row["project_id"] if isinstance(row, dict) else row[0]) for row in project_rows)
            records = tuple(
                self._load_runtime_citation_graph(cursor=cursor, project_id=graph_project_id)
                for graph_project_id in project_ids
            )
        return RuntimeCitationGraphPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def list_runtime_report_exports(
        self,
        *,
        project_id: str | None = None,
        report_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeReportExportPage:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        filters: list[str] = []
        params: list[object] = []
        if project_id:
            filters.append("project_id = %s")
            params.append(_uuid(project_id))
        if report_type:
            filters.append("report_type = %s")
            params.append(report_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM report_exports {where_clause}", tuple(params))
            total_row = cursor.fetchone()
            total_count = int(total_row[0] if not isinstance(total_row, dict) else total_row["count"])
            cursor.execute(
                f"""
                SELECT {", ".join(REPORT_EXPORT_COLUMNS)}
                FROM report_exports
                {where_clause}
                ORDER BY exported_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            reports = _rows_dict(cursor.fetchall(), REPORT_EXPORT_COLUMNS)
            records = tuple(
                self._load_runtime_report_export(cursor=cursor, report_export=report)
                for report in reports
            )
        return RuntimeReportExportPage(
            total_count=total_count,
            limit=limit,
            offset=offset,
            records=records,
        )

    def _load_runtime_report_export(
        self,
        *,
        cursor: DbCursor,
        report_export: dict[str, Any],
    ) -> RuntimeReportExport:
        score_snapshots: list[dict[str, Any]] = []
        for score_snapshot_id in tuple(str(value) for value in report_export["score_snapshot_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(VISIBILITY_SCORE_SNAPSHOT_COLUMNS)}
                FROM visibility_score_snapshots
                WHERE id = %s
                LIMIT 1
                """,
                (_uuid(score_snapshot_id),),
            )
            snapshot_row = cursor.fetchone()
            if snapshot_row:
                score_snapshots.append(_row_dict(snapshot_row, VISIBILITY_SCORE_SNAPSHOT_COLUMNS))
        answer_runs: list[dict[str, Any]] = []
        for answer_run_id in tuple(str(value) for value in report_export["answer_run_ids"]):
            cursor.execute(
                f"""
                SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                       pq.text AS prompt_text,
                       pq.intent_type AS prompt_intent_type,
                       pq.priority AS prompt_priority,
                       pq.prompt_version AS prompt_version
                FROM report_evidence re
                JOIN answer_runs ar ON ar.id = re.answer_run_id
                LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                WHERE re.report_export_id = %s AND re.answer_run_id = %s
                ORDER BY re.created_at ASC
                LIMIT 1
                """,
                (_uuid(str(report_export["id"])), _uuid(answer_run_id)),
            )
            answer_run_row = cursor.fetchone()
            if answer_run_row:
                answer_runs.append(_row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS))
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("report_export", str(report_export["id"])),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        cursor.execute("SELECT count(*) FROM source_graphs WHERE project_id = %s", (_uuid(str(report_export["project_id"])),))
        graph_count_row = cursor.fetchone()
        graph_count = int(graph_count_row[0] if not isinstance(graph_count_row, dict) else graph_count_row["count"])
        citation_graph = (
            self._load_runtime_citation_graph(cursor=cursor, project_id=str(report_export["project_id"]))
            if graph_count > 0
            else None
        )
        return RuntimeReportExport(
            report_export=report_export,
            score_snapshots=tuple(score_snapshots),
            answer_runs=tuple(answer_runs),
            citation_graph=citation_graph,
            audit_events=audit_events,
        )

    def _load_runtime_citation_graph(self, *, cursor: DbCursor, project_id: str) -> RuntimeCitationGraph:
        cursor.execute(
            f"""
            SELECT {", ".join(SOURCE_GRAPH_COLUMNS)}
            FROM source_graphs
            WHERE project_id = %s
            ORDER BY citation_count DESC, source_domain ASC, source_type ASC
            """,
            (_uuid(project_id),),
        )
        nodes = _rows_dict(cursor.fetchall(), SOURCE_GRAPH_COLUMNS)
        runtime_nodes: list[RuntimeCitationGraphNode] = []
        for node in nodes:
            answer_run_ids = tuple(str(answer_run_id) for answer_run_id in node["answer_run_ids"])
            answer_runs: list[dict[str, Any]] = []
            for answer_run_id in answer_run_ids:
                cursor.execute(
                    f"""
                    SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                           pq.text AS prompt_text,
                           pq.intent_type AS prompt_intent_type,
                           pq.priority AS prompt_priority,
                           pq.prompt_version AS prompt_version
                    FROM answer_runs ar
                    LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
                    WHERE ar.id = %s
                    LIMIT 1
                    """,
                    (_uuid(answer_run_id),),
                )
                answer_run_row = cursor.fetchone()
                if answer_run_row:
                    answer_runs.append(_row_dict(answer_run_row, ANSWER_RUN_READ_COLUMNS))
            runtime_nodes.append(
                RuntimeCitationGraphNode(
                    node=node,
                    answer_runs=tuple(answer_runs),
                )
            )
        cursor.execute(
            f"""
            SELECT sge.id AS id,
                   sge.source_graph_id AS source_graph_id,
                   sge.answer_run_id AS answer_run_id,
                   sge.answer_citation_id AS answer_citation_id,
                   sge.relation_type AS relation_type,
                   sge.created_at AS created_at
            FROM source_graph_evidence sge
            JOIN source_graphs sg ON sg.id = sge.source_graph_id
            WHERE sg.project_id = %s
            ORDER BY sge.created_at ASC, sge.id ASC
            """,
            (_uuid(project_id),),
        )
        evidence_links = _rows_dict(cursor.fetchall(), SOURCE_GRAPH_EVIDENCE_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(SOURCE_GAP_COLUMNS)}
            FROM source_gaps
            WHERE project_id = %s
            ORDER BY expected_weight DESC, source_type ASC, gap_type ASC
            """,
            (_uuid(project_id),),
        )
        source_gaps = _rows_dict(cursor.fetchall(), SOURCE_GAP_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COMPETITOR_BENCHMARK_COLUMNS)}
            FROM competitor_benchmarks
            WHERE project_id = %s
            ORDER BY competitor_name ASC
            """,
            (_uuid(project_id),),
        )
        competitor_benchmarks = _rows_dict(cursor.fetchall(), COMPETITOR_BENCHMARK_COLUMNS)
        return RuntimeCitationGraph(
            project_id=project_id,
            nodes=tuple(runtime_nodes),
            evidence_links=evidence_links,
            source_gaps=source_gaps,
            competitor_benchmarks=competitor_benchmarks,
        )

    def _load_runtime_score_snapshot(
        self,
        *,
        cursor: DbCursor,
        snapshot: dict[str, Any],
        snapshot_id: str,
    ) -> RuntimeScoreSnapshot:
        cursor.execute(
            f"""
            SELECT {", ".join(SCORE_CONTRIBUTION_COLUMNS)}
            FROM score_contributions
            WHERE score_snapshot_id = %s
            ORDER BY component_name ASC, created_at ASC
            """,
            (_uuid(snapshot_id),),
        )
        contributions = _rows_dict(cursor.fetchall(), SCORE_CONTRIBUTION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                   pq.text AS prompt_text,
                   pq.intent_type AS prompt_intent_type,
                   pq.priority AS prompt_priority,
                   pq.prompt_version AS prompt_version
            FROM score_snapshot_runs ssr
            JOIN answer_runs ar ON ar.id = ssr.answer_run_id
            LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id
            WHERE ssr.score_snapshot_id = %s
            GROUP BY {", ".join(f"ar.{column}" for column in ANSWER_RUN_COLUMNS)},
                     pq.text, pq.intent_type, pq.priority, pq.prompt_version
            ORDER BY ar.collected_at ASC, ar.id ASC
            """,
            (_uuid(snapshot_id),),
        )
        answer_runs = _rows_dict(cursor.fetchall(), ANSWER_RUN_READ_COLUMNS)
        runtime_answer_runs: list[RuntimeScoreSnapshotRun] = []
        for answer_run in answer_runs:
            answer_run_id = str(answer_run["id"])
            cursor.execute(
                f"""
                SELECT {", ".join(ANSWER_ANALYSIS_READ_COLUMNS)}
                FROM answer_analyses
                WHERE answer_run_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (_uuid(answer_run_id),),
            )
            analysis_row = cursor.fetchone()
            runtime_answer_runs.append(
                RuntimeScoreSnapshotRun(
                    answer_run=answer_run,
                    analysis=_row_dict(analysis_row, ANSWER_ANALYSIS_READ_COLUMNS) if analysis_row else None,
                )
            )
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("visibility_score_snapshot", snapshot_id),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeScoreSnapshot(
            snapshot=snapshot,
            contributions=contributions,
            answer_runs=tuple(runtime_answer_runs),
            audit_events=audit_events,
        )

    def _load_runtime_evidence_run(
        self,
        *,
        cursor: DbCursor,
        answer_run: dict[str, Any],
        answer_run_id: str,
    ) -> RuntimeEvidenceRun:
        cursor.execute(
            f"""
            SELECT {", ".join(RAW_ANSWER_COLUMNS)}
            FROM raw_answers
            WHERE answer_run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_uuid(answer_run_id),),
        )
        raw_answer_row = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT {", ".join(CITATION_COLUMNS)}
            FROM answer_citations
            WHERE answer_run_id = %s
            ORDER BY position ASC, created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        citations = _rows_dict(cursor.fetchall(), CITATION_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(ASSET_COLUMNS)}
            FROM evidence_assets
            WHERE answer_run_id = %s
            ORDER BY asset_type ASC, created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        assets = _rows_dict(cursor.fetchall(), ASSET_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COLLECTOR_LOG_COLUMNS)}
            FROM collector_logs
            WHERE answer_run_id = %s
            ORDER BY created_at ASC
            """,
            (_uuid(answer_run_id),),
        )
        logs = _rows_dict(cursor.fetchall(), COLLECTOR_LOG_COLUMNS)
        cursor.execute(
            f"""
            SELECT {", ".join(COLLECTION_COST_COLUMNS)}
            FROM collection_costs
            WHERE answer_run_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_uuid(answer_run_id),),
        )
        cost_row = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT {", ".join(AUDIT_EVENT_COLUMNS)}
            FROM audit_events
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at ASC
            """,
            ("answer_run", answer_run_id),
        )
        audit_events = _rows_dict(cursor.fetchall(), AUDIT_EVENT_COLUMNS)
        return RuntimeEvidenceRun(
            answer_run=answer_run,
            raw_answer=_row_dict(raw_answer_row, RAW_ANSWER_COLUMNS) if raw_answer_row else None,
            citations=citations,
            evidence_assets=assets,
            collector_logs=logs,
            collection_cost=_row_dict(cost_row, COLLECTION_COST_COLUMNS) if cost_row else None,
            audit_events=audit_events,
        )

    def save_project_bootstrap(self, bootstrap: ProjectBootstrap) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_profiles (id, market_code, payload)
                VALUES (%s, %s, %s)
                ON CONFLICT (market_code) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    _uuid(_stable_id("market-profile", bootstrap.market_profile.market_code)),
                    bootstrap.market_profile.market_code,
                    _json_payload(bootstrap.market_profile),
                ),
            )
            cursor.execute(
                """
                INSERT INTO industry_profiles (id, market_code, industry_code, payload)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    _uuid(
                        _stable_id(
                            "industry-profile",
                            bootstrap.industry_profile.market_code,
                            bootstrap.industry_profile.industry_code,
                        )
                    ),
                    bootstrap.industry_profile.market_code,
                    bootstrap.industry_profile.industry_code,
                    _json_payload(bootstrap.industry_profile),
                ),
            )
            cursor.execute(
                """
                INSERT INTO tenants (id, name, slug, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug
                """,
                (
                    _uuid(bootstrap.tenant.id),
                    bootstrap.tenant.name,
                    bootstrap.tenant.slug,
                    _datetime(bootstrap.tenant.created_at),
                ),
            )
            cursor.execute(
                """
                INSERT INTO projects (
                  id, tenant_id, name, market_code, industry_code, target_brand, category,
                  prompt_version, status, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  market_code = EXCLUDED.market_code,
                  industry_code = EXCLUDED.industry_code,
                  target_brand = EXCLUDED.target_brand,
                  category = EXCLUDED.category,
                  prompt_version = EXCLUDED.prompt_version,
                  status = EXCLUDED.status
                """,
                (
                    _uuid(bootstrap.project.id),
                    _uuid(bootstrap.project.tenant_id),
                    bootstrap.project.name,
                    bootstrap.project.market_code,
                    bootstrap.project.industry_code,
                    bootstrap.project.target_brand,
                    bootstrap.project.category,
                    bootstrap.project.prompt_version,
                    bootstrap.project.status,
                    _datetime(bootstrap.project.created_at),
                ),
            )
            for member in bootstrap.members:
                cursor.execute(
                    """
                    INSERT INTO project_members (id, project_id, user_id, role, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role
                    """,
                    (
                        _uuid(member.id),
                        _uuid(member.project_id),
                        member.user_id,
                        member.role,
                        _datetime(member.created_at),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO brand_entities (
                  id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  canonical_name = EXCLUDED.canonical_name,
                  official_domains = EXCLUDED.official_domains,
                  parent_company = EXCLUDED.parent_company,
                  product_lines = EXCLUDED.product_lines,
                  status = EXCLUDED.status
                """,
                (
                    _uuid(bootstrap.brand.id),
                    _uuid(bootstrap.brand.project_id),
                    bootstrap.brand.canonical_name,
                    _json_payload(bootstrap.brand.official_domains),
                    bootstrap.brand.parent_company,
                    _json_payload(bootstrap.brand.product_lines),
                    bootstrap.brand.status,
                ),
            )
            for competitor in bootstrap.competitors:
                cursor.execute(
                    """
                    INSERT INTO competitor_entities (
                      id, project_id, canonical_name, official_domains, parent_company, product_lines, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      canonical_name = EXCLUDED.canonical_name,
                      official_domains = EXCLUDED.official_domains,
                      parent_company = EXCLUDED.parent_company,
                      product_lines = EXCLUDED.product_lines,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(competitor.id),
                        _uuid(competitor.project_id),
                        competitor.canonical_name,
                        _json_payload(competitor.official_domains),
                        competitor.parent_company,
                        _json_payload(competitor.product_lines),
                        competitor.status,
                    ),
                )
            for prompt in bootstrap.prompt_questions:
                cursor.execute(
                    """
                    INSERT INTO prompt_questions (
                      id, project_id, market_code, industry_code, text, intent_type, city,
                      language, target_brand, competitors, priority, intent_weight,
                      prompt_version, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      text = EXCLUDED.text,
                      intent_type = EXCLUDED.intent_type,
                      city = EXCLUDED.city,
                      language = EXCLUDED.language,
                      target_brand = EXCLUDED.target_brand,
                      competitors = EXCLUDED.competitors,
                      priority = EXCLUDED.priority,
                      intent_weight = EXCLUDED.intent_weight,
                      prompt_version = EXCLUDED.prompt_version,
                      status = EXCLUDED.status
                    """,
                    (
                        _uuid(prompt.id),
                        _uuid(prompt.project_id),
                        prompt.market_code,
                        prompt.industry_code,
                        prompt.text,
                        prompt.intent_type,
                        prompt.city,
                        prompt.language,
                        prompt.target_brand,
                        _json_payload(prompt.competitors),
                        prompt.priority,
                        prompt.intent_weight,
                        prompt.prompt_version,
                        prompt.status,
                    ),
                )
            self.save_audit_events(bootstrap.audit_events, cursor=cursor)
        self.connection.commit()

    def save_raw_evidence_records(self, records: tuple[RawEvidenceRecord, ...]) -> None:
        with self.connection.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO answer_runs (
                      id, project_id, prompt_question_id, platform, surface, access_method,
                      market_code, city, language, device, answer_present, surface_triggered,
                      sample_index, sample_size, model_or_surface, account_state,
                      collector_backend_id, collector_version, collected_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.answer_run.id),
                        _uuid(record.answer_run.project_id),
                        _uuid(record.answer_run.prompt_question_id),
                        record.answer_run.platform,
                        record.answer_run.surface,
                        record.answer_run.access_method,
                        record.answer_run.market_code,
                        record.answer_run.city,
                        record.answer_run.language,
                        record.answer_run.device,
                        record.answer_run.answer_present,
                        record.answer_run.surface_triggered,
                        record.answer_run.sample_index,
                        record.answer_run.sample_size,
                        record.answer_run.model_or_surface,
                        record.answer_run.account_state,
                        record.answer_run.collector_backend_id,
                        record.answer_run.collector_version,
                        _datetime(record.answer_run.collected_at),
                        record.answer_run.status,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO raw_answers (id, answer_run_id, answer_text, raw_payload, raw_payload_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.raw_answer.id),
                        _uuid(record.raw_answer.answer_run_id),
                        record.raw_answer.answer_text,
                        _json_payload(record.raw_answer.raw_payload),
                        record.raw_answer.raw_payload_hash,
                    ),
                )
                for citation in record.citations:
                    cursor.execute(
                        """
                        INSERT INTO answer_citations (id, answer_run_id, url, domain, position, source_type)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(citation.id),
                            _uuid(citation.answer_run_id),
                            citation.url,
                            citation.domain,
                            citation.position,
                            citation.source_type,
                        ),
                    )
                for asset in record.evidence_assets:
                    cursor.execute(
                        """
                        INSERT INTO evidence_assets (id, answer_run_id, asset_type, url, content_hash)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(asset.id),
                            _uuid(asset.answer_run_id),
                            asset.asset_type,
                            asset.url,
                            asset.content_hash,
                        ),
                    )
                for log in record.collector_logs:
                    cursor.execute(
                        """
                        INSERT INTO collector_logs (
                          id, answer_run_id, collector_backend_id, event_type, payload, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(log.id),
                            _uuid(log.answer_run_id),
                            log.collector_backend_id,
                            log.event_type,
                            _json_payload(log.payload),
                            _datetime(log.created_at),
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO collection_costs (
                      id, answer_run_id, project_id, collector_backend_id, llm_provider, llm_tokens,
                      llm_cost, proxy_or_vendor_cost, compute_cost, total_cost, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.collection_cost.id),
                        _uuid(record.collection_cost.answer_run_id),
                        _uuid(record.collection_cost.project_id),
                        record.collection_cost.collector_backend_id,
                        record.collection_cost.llm_provider,
                        record.collection_cost.llm_tokens,
                        record.collection_cost.llm_cost,
                        record.collection_cost.proxy_or_vendor_cost,
                        record.collection_cost.compute_cost,
                        record.collection_cost.total_cost,
                        _datetime(record.collection_cost.created_at),
                    ),
                )
                self.save_audit_events(record.audit_events, cursor=cursor)
        self.connection.commit()

    def save_collection_failure_records(self, records: tuple[CollectionFailureRecord, ...]) -> None:
        with self.connection.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO answer_runs (
                      id, project_id, prompt_question_id, platform, surface, access_method,
                      market_code, city, language, device, answer_present, surface_triggered,
                      sample_index, sample_size, model_or_surface, account_state,
                      collector_backend_id, collector_version, collected_at, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.answer_run.id),
                        _uuid(record.answer_run.project_id),
                        _uuid(record.answer_run.prompt_question_id),
                        record.answer_run.platform,
                        record.answer_run.surface,
                        record.answer_run.access_method,
                        record.answer_run.market_code,
                        record.answer_run.city,
                        record.answer_run.language,
                        record.answer_run.device,
                        record.answer_run.answer_present,
                        record.answer_run.surface_triggered,
                        record.answer_run.sample_index,
                        record.answer_run.sample_size,
                        record.answer_run.model_or_surface,
                        record.answer_run.account_state,
                        record.answer_run.collector_backend_id,
                        record.answer_run.collector_version,
                        _datetime(record.answer_run.collected_at),
                        record.answer_run.status,
                    ),
                )
                for log in record.collector_logs:
                    cursor.execute(
                        """
                        INSERT INTO collector_logs (
                          id, answer_run_id, collector_backend_id, event_type, payload, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(log.id),
                            _uuid(log.answer_run_id),
                            log.collector_backend_id,
                            log.event_type,
                            _json_payload(log.payload),
                            _datetime(log.created_at),
                        ),
                    )
                cursor.execute(
                    """
                    INSERT INTO collection_costs (
                      id, answer_run_id, project_id, collector_backend_id, llm_provider, llm_tokens,
                      llm_cost, proxy_or_vendor_cost, compute_cost, total_cost, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.collection_cost.id),
                        _uuid(record.collection_cost.answer_run_id),
                        _uuid(record.collection_cost.project_id),
                        record.collection_cost.collector_backend_id,
                        record.collection_cost.llm_provider,
                        record.collection_cost.llm_tokens,
                        record.collection_cost.llm_cost,
                        record.collection_cost.proxy_or_vendor_cost,
                        record.collection_cost.compute_cost,
                        record.collection_cost.total_cost,
                        _datetime(record.collection_cost.created_at),
                    ),
                )
                self.save_audit_events(record.audit_events, cursor=cursor)
        self.connection.commit()

    def save_answer_analyses(self, analyses: tuple[AnswerAnalysis, ...]) -> None:
        with self.connection.cursor() as cursor:
            for analysis in analyses:
                cursor.execute(
                    """
                    INSERT INTO answer_analyses (
                      id, answer_run_id, parser_engine_id, analysis_version, payload, confidence
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(analysis.id),
                        _uuid(analysis.answer_run_id),
                        analysis.parser_engine_id,
                        analysis.analysis_version,
                        _json_payload(analysis),
                        analysis.confidence,
                    ),
                )
        self.connection.commit()

    def save_score_snapshot(
        self,
        snapshot: VisibilityScoreSnapshot,
        contributions: tuple[ScoreContribution, ...],
        audit_event: AuditEvent,
    ) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO visibility_score_snapshots (
                  id, project_id, scope_type, scope_value, formula_version, platform_weights_snapshot,
                  final_score, trigger_rate, mention_rate, recommendation_rate, answer_run_ids,
                  created_at, dispersion
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(snapshot.id),
                    _uuid(snapshot.project_id),
                    snapshot.scope_type,
                    snapshot.scope_value,
                    snapshot.formula_version,
                    _json_payload(snapshot.platform_weights_snapshot),
                    snapshot.final_score,
                    snapshot.trigger_rate,
                    snapshot.mention_rate,
                    snapshot.recommendation_rate,
                    _uuid_array(snapshot.answer_run_ids),
                    _datetime(snapshot.created_at),
                    snapshot.dispersion,
                ),
            )
            for contribution in contributions:
                cursor.execute(
                    """
                    INSERT INTO score_contributions (
                      id, score_snapshot_id, component_name, component_score, weight,
                      weighted_contribution, denominator, evidence_answer_run_ids,
                      positive_evidence_summary, negative_evidence_summary, confidence_note,
                      created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(contribution.id),
                        _uuid(contribution.score_snapshot_id),
                        contribution.component_name,
                        contribution.component_score,
                        contribution.weight,
                        contribution.weighted_contribution,
                        contribution.denominator,
                        _uuid_array(contribution.evidence_answer_run_ids),
                        contribution.positive_evidence_summary,
                        contribution.negative_evidence_summary,
                        contribution.confidence_note,
                        _datetime(contribution.created_at),
                    ),
                )
                for answer_run_id in contribution.evidence_answer_run_ids:
                    cursor.execute(
                        """
                        INSERT INTO score_snapshot_runs (id, score_snapshot_id, answer_run_id, contribution_role)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            _uuid(_stable_id("score-snapshot-run", snapshot.id, answer_run_id, contribution.component_name)),
                            _uuid(snapshot.id),
                            _uuid(answer_run_id),
                            contribution.component_name,
                        ),
                    )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_citation_graph(self, project_id: str, graph: CitationGraphResult) -> None:
        with self.connection.cursor() as cursor:
            for node in graph.nodes:
                cursor.execute(
                    """
                    INSERT INTO source_graphs (
                      id, project_id, source_url, source_domain, source_type, topic,
                      source_gap_type, answer_run_ids, citation_count
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(node.id),
                        _uuid(node.project_id),
                        node.source_url,
                        node.source_domain,
                        node.source_type,
                        node.topic,
                        node.source_gap_type,
                        _uuid_array(node.answer_run_ids),
                        node.citation_count,
                    ),
                )
            for evidence in graph.evidence_links:
                cursor.execute(
                    """
                    INSERT INTO source_graph_evidence (
                      id, source_graph_id, answer_run_id, answer_citation_id, relation_type
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(evidence.id),
                        _uuid(evidence.source_graph_id),
                        _uuid(evidence.answer_run_id),
                        _uuid(evidence.answer_citation_id),
                        evidence.relation_type,
                    ),
                )
            for gap in graph.source_gaps:
                cursor.execute(
                    """
                    INSERT INTO source_gaps (
                      id, project_id, source_type, gap_type, observed_count,
                      expected_weight, recommendation
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, source_type, gap_type) DO UPDATE SET
                      observed_count = EXCLUDED.observed_count,
                      expected_weight = EXCLUDED.expected_weight,
                      recommendation = EXCLUDED.recommendation
                    """,
                    (
                        _uuid(_stable_id("source-gap", project_id, gap.source_type, gap.gap_type)),
                        _uuid(project_id),
                        gap.source_type,
                        gap.gap_type,
                        gap.observed_count,
                        gap.expected_weight,
                        gap.recommendation,
                    ),
                )
            for benchmark in graph.competitor_benchmarks:
                cursor.execute(
                    """
                    INSERT INTO competitor_benchmarks (
                      id, project_id, competitor_name, metric_scope, payload, answer_run_ids
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(benchmark.id),
                        _uuid(benchmark.project_id),
                        benchmark.competitor_name,
                        "project",
                        _json_payload(benchmark),
                        _uuid_array(benchmark.answer_run_ids),
                    ),
                )
        self.connection.commit()

    def save_report_export(self, report_export: ReportExport, audit_event: AuditEvent) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO report_exports (
                  id, project_id, market_code, report_version, report_type, score_snapshot_ids,
                  answer_run_ids, prompt_version, scoring_formula_version, platform_weights_snapshot,
                  sample_size, window_start, window_end, methodology_hash, markdown_url, pdf_url,
                  csv_url, exported_by, exported_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(report_export.id),
                    _uuid(report_export.project_id),
                    report_export.market_code,
                    report_export.report_version,
                    report_export.report_type,
                    _uuid_array(report_export.score_snapshot_ids),
                    _uuid_array(report_export.answer_run_ids),
                    report_export.prompt_version,
                    report_export.scoring_formula_version,
                    _json_payload(report_export.platform_weights_snapshot),
                    report_export.sample_size,
                    _datetime(report_export.window_start),
                    _datetime(report_export.window_end),
                    report_export.methodology_hash,
                    report_export.markdown_url,
                    report_export.pdf_url,
                    report_export.csv_url,
                    report_export.exported_by,
                    _datetime(report_export.exported_at),
                ),
            )
            for answer_run_id in report_export.answer_run_ids:
                cursor.execute(
                    """
                    INSERT INTO report_evidence (id, report_export_id, answer_run_id, evidence_role)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(_stable_id("report-evidence", report_export.id, answer_run_id, "raw_evidence")),
                        _uuid(report_export.id),
                        _uuid(answer_run_id),
                        "raw_evidence",
                    ),
                )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_action_plan(
        self,
        *,
        actions: tuple[ActionRecommendation, ...],
        schedule: RetestSchedule,
        comparison: RetestComparison | None,
        audit_events: tuple[AuditEvent, ...],
    ) -> None:
        with self.connection.cursor() as cursor:
            for action in actions:
                cursor.execute(
                    """
                    INSERT INTO action_recommendations (
                      id, project_id, title, description, priority, status, owner_id,
                      source_gap_type, evidence_answer_run_ids, related_source_types,
                      next_check_date, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(action.id),
                        _uuid(action.project_id),
                        action.title,
                        action.description,
                        action.priority,
                        action.status,
                        action.owner_id,
                        action.source_gap_type,
                        _uuid_array(action.evidence_answer_run_ids),
                        list(action.related_source_types),
                        _datetime(action.next_check_date),
                        _datetime(action.created_at),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO retest_schedules (
                  id, project_id, prompt_version, sample_size, offsets_days,
                  scheduled_dates, answer_run_ids, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(schedule.id),
                    _uuid(schedule.project_id),
                    schedule.prompt_version,
                    schedule.sample_size,
                    list(schedule.offsets_days),
                    list(schedule.scheduled_dates),
                    _uuid_array(schedule.answer_run_ids),
                    _datetime(schedule.created_at),
                ),
            )
            if comparison:
                cursor.execute(
                    """
                    INSERT INTO retest_comparisons (
                      id, project_id, baseline_score, retest_score, score_delta,
                      baseline_answer_run_ids, retest_answer_run_ids, trend, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(comparison.id),
                        _uuid(comparison.project_id),
                        comparison.baseline_score,
                        comparison.retest_score,
                        comparison.score_delta,
                        _uuid_array(comparison.baseline_answer_run_ids),
                        _uuid_array(comparison.retest_answer_run_ids),
                        comparison.trend,
                        _datetime(comparison.created_at),
                    ),
                )
            self.save_audit_events(audit_events, cursor=cursor)
        self.connection.commit()

    def save_content_engine(
        self,
        *,
        facts: tuple[LocalizedKnowledgeFact, ...],
        drafts: tuple[ContentDraft, ...],
        connectors: tuple[IntegrationConnector, ...],
        distribution_records: tuple[ManualDistributionRecord, ...],
        audit_event: AuditEvent,
    ) -> None:
        with self.connection.cursor() as cursor:
            for fact in facts:
                cursor.execute(
                    """
                    INSERT INTO localized_knowledge_facts (
                      id, project_id, market_code, fact_type, subject, predicate, object_value,
                      city, evidence_source_id, confidence, status, valid_from, valid_until
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(fact.id),
                        _uuid(fact.project_id),
                        fact.market_code,
                        fact.fact_type,
                        fact.subject,
                        fact.predicate,
                        fact.object_value,
                        fact.city,
                        _uuid(fact.evidence_source_id),
                        fact.confidence,
                        fact.status,
                        _datetime(fact.valid_from),
                        _datetime(fact.valid_until),
                    ),
                )
            for draft in drafts:
                cursor.execute(
                    """
                    INSERT INTO content_drafts (
                      id, project_id, title, content_type, content_template_id, target_question_ids,
                      target_city, target_platform, target_source_type, used_knowledge_fact_ids,
                      source_gap_types, source_action_id, evidence_answer_run_ids,
                      draft_markdown, review_status, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(draft.id),
                        _uuid(draft.project_id),
                        draft.title,
                        draft.content_type,
                        draft.content_template_id,
                        _uuid_array(draft.target_question_ids),
                        draft.target_city,
                        draft.target_platform,
                        draft.target_source_type,
                        _uuid_array(draft.used_knowledge_fact_ids),
                        list(draft.source_gap_types),
                        _uuid(draft.source_action_id),
                        _uuid_array(draft.evidence_answer_run_ids),
                        draft.draft_markdown,
                        draft.review_status,
                        draft.created_by,
                        _datetime(draft.created_at),
                    ),
                )
            for connector in connectors:
                cursor.execute(
                    """
                    INSERT INTO integration_connectors (
                      id, project_id, provider, connection_status, capabilities, auth_mode, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(connector.id),
                        _uuid(connector.project_id),
                        connector.provider,
                        connector.connection_status,
                        list(connector.capabilities),
                        connector.auth_mode,
                        _datetime(connector.created_at),
                    ),
                )
            for record in distribution_records:
                cursor.execute(
                    """
                    INSERT INTO manual_distribution_records (
                      id, project_id, content_draft_id, platform, target_url, status,
                      submitted_at, checked_at, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(record.id),
                        _uuid(record.project_id),
                        _uuid(record.content_draft_id),
                        record.platform,
                        record.target_url,
                        record.status,
                        _datetime(record.submitted_at),
                        _datetime(record.checked_at),
                        record.notes,
                    ),
                )
            self.save_audit_events((audit_event,), cursor=cursor)
        self.connection.commit()

    def save_traceability_bundle(self, bundle: TraceabilityBundle) -> None:
        with self.connection.cursor() as cursor:
            for link in bundle.evidence_links:
                cursor.execute(
                    """
                    INSERT INTO evidence_links (
                      id, project_id, source_type, source_id, target_type, target_id,
                      relation_type, answer_run_ids
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(link.id),
                        _uuid(link.project_id),
                        link.source_type,
                        _uuid(link.source_id),
                        link.target_type,
                        _uuid(link.target_id),
                        link.relation_type,
                        _uuid_array(link.answer_run_ids),
                    ),
                )
            cursor.execute(
                """
                INSERT INTO traceability_bundles (
                  id, project_id, subject_type, subject_id, report_export_ids,
                  score_snapshot_ids, score_contribution_ids, answer_run_ids, raw_answer_ids,
                  answer_citation_ids, evidence_asset_ids, source_graph_ids, source_gap_types,
                  action_recommendation_ids, content_draft_ids, audit_event_ids,
                  explanation_summary
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    _uuid(bundle.id),
                    _uuid(bundle.project_id),
                    bundle.subject_type,
                    _uuid(bundle.subject_id),
                    _uuid_array(bundle.report_export_ids),
                    _uuid_array(bundle.score_snapshot_ids),
                    _uuid_array(bundle.score_contribution_ids),
                    _uuid_array(bundle.answer_run_ids),
                    _uuid_array(bundle.raw_answer_ids),
                    _uuid_array(bundle.answer_citation_ids),
                    _uuid_array(bundle.evidence_asset_ids),
                    _uuid_array(bundle.source_graph_ids),
                    list(bundle.source_gap_types),
                    _uuid_array(bundle.action_recommendation_ids),
                    _uuid_array(bundle.content_draft_ids),
                    _uuid_array(bundle.audit_event_ids),
                    bundle.explanation_summary,
                ),
            )
        self.connection.commit()

    def save_audit_events(self, events: tuple[AuditEvent, ...], *, cursor: DbCursor | None = None) -> None:
        owns_cursor = cursor is None
        if cursor is None:
            cursor = self.connection.cursor().__enter__()
        try:
            for event in events:
                cursor.execute(
                    """
                    INSERT INTO audit_events (
                      id, event_type, project_id, actor_type, actor_id, target_type, target_id,
                      before_hash, after_hash, input_refs, output_refs, method_version, reason,
                      created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        _uuid(event.id),
                        event.event_type,
                        _uuid(event.project_id),
                        event.actor_type,
                        event.actor_id,
                        event.target_type,
                        event.target_id,
                        event.before_hash,
                        event.after_hash,
                        _json_payload(event.input_refs),
                        _json_payload(event.output_refs),
                        event.method_version,
                        event.reason,
                        _datetime(event.created_at),
                    ),
                )
        finally:
            if owns_cursor:
                assert cursor is not None
                cursor.__exit__(None, None, None)
                self.connection.commit()
