"""Immutable Customer-safe snapshots over Connector and official-report projections."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from geo_core.connectors.contracts import canonical_hash
from geo_core.project_scope import set_project_scope


class ExternalDataError(RuntimeError):
    """External data cannot enter or advance through the approval lifecycle."""


_GSC_FIELDS = (
    "date",
    "query",
    "page",
    "country",
    "device",
    "clicks",
    "impressions",
    "ctr",
    "position",
)
_PROHIBITED_FIELD_PARTS = ("email", "phone", "password", "secret", "token", "actor")


class ExternalDataService:
    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._clock = clock

    def create_connector_report(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        projection_batch_id: UUID,
        actor_id: UUID,
        title: str,
        summary: str,
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            source = connection.execute(
                """SELECT batch.*, run.connection_id, run.scope_id, run.id AS sync_run_id,
                          run.adapter_release, run.window_start, run.window_end,
                          definition.kind, schema.schema_hash,
                          freshness.status AS freshness_status,
                          freshness.observed_watermark
                     FROM connector_projection_batches batch
                     JOIN connector_sync_runs run ON run.project_id = batch.project_id
                                                  AND run.id = batch.sync_run_id
                     JOIN connector_definitions definition
                       ON definition.project_id = run.project_id
                      AND definition.id = run.definition_id
                     JOIN connector_schema_versions schema
                       ON schema.project_id = batch.project_id
                      AND schema.id = batch.schema_version_id
                     JOIN connector_freshness freshness
                       ON freshness.project_id = run.project_id
                      AND freshness.sync_run_id = run.id
                    WHERE batch.project_id = %s AND batch.id = %s
                      AND run.status = 'succeeded'""",
                (project_id, projection_batch_id),
            ).fetchone()
            if source is None:
                raise ExternalDataError("Successful Connector projection was not found")
            if source["kind"] == "google_search_console":
                source_kind = "gsc_connector"
                rows = connection.execute(
                    """SELECT observed_date AS date, query, page, country, device,
                              clicks, impressions, ctr, position
                         FROM connector_gsc_projection_rows
                        WHERE project_id = %s AND projection_batch_id = %s
                        ORDER BY row_index""",
                    (project_id, projection_batch_id),
                ).fetchall()
                payload_rows = [_json_row(row) for row in rows]
            elif source["kind"] == "google_analytics_4":
                source_kind = "ga4_connector"
                rows = connection.execute(
                    """SELECT observed_date AS date, dimensions, metrics
                         FROM connector_ga4_projection_rows
                        WHERE project_id = %s AND projection_batch_id = %s
                        ORDER BY row_index""",
                    (project_id, projection_batch_id),
                ).fetchall()
                payload_rows = [_json_row(row) for row in rows]
            else:
                raise ExternalDataError("Projection is not a GSC or GA4 Connector source")
            if len(payload_rows) != source["row_count"]:
                raise ExternalDataError("Typed rows do not match the frozen Projection Batch")
            period_start, period_end = _period(source, payload_rows)
            payload = {
                "source_kind": source_kind,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "rows": payload_rows,
            }
            lineage = {
                "sync_run_id": str(source["sync_run_id"]),
                "projection_batch_id": str(projection_batch_id),
                "schema_hash": source["schema_hash"],
            }
            return self._persist_draft(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                actor_id=actor_id,
                source_kind=source_kind,
                connection_id=source["connection_id"],
                scope_id=source["scope_id"],
                sync_run_id=source["sync_run_id"],
                projection_batch_id=projection_batch_id,
                official_report_import_id=None,
                period_start=period_start,
                period_end=period_end,
                as_of=source["observed_watermark"] or self._clock(),
                freshness_status=source["freshness_status"],
                schema_release=source["schema_hash"],
                adapter_release=source["adapter_release"],
                row_count=source["row_count"],
                dataset_hash=source["dataset_hash"],
                payload=payload,
                whitelist_version="external-data-customer-v1",
                lineage=lineage,
                title=title,
                summary=summary,
            )

    def create_official_report(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        import_id: UUID,
        actor_id: UUID,
        customer_fields: Sequence[str],
        title: str,
        summary: str,
    ) -> Mapping[str, object]:
        fields = _customer_fields(customer_fields)
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            source = connection.execute(
                """SELECT * FROM monitoring_official_report_imports
                    WHERE project_id = %s AND campaign_id = %s AND id = %s""",
                (project_id, campaign_id, import_id),
            ).fetchone()
            if source is None:
                raise ExternalDataError("Official report import was not found")
            rows = connection.execute(
                """SELECT row_data FROM monitoring_official_report_rows
                    WHERE project_id = %s AND campaign_id = %s AND import_id = %s
                      AND eligible = true ORDER BY row_index""",
                (project_id, campaign_id, import_id),
            ).fetchall()
            payload_rows = [
                {key: row["row_data"].get(key) for key in fields if key in row["row_data"]}
                for row in rows
            ]
            source_kind = (
                "google_official_report"
                if source["surface"] == "google_generative_ai_performance_report"
                else "bing_official_report"
                if source["surface"] == "bing_ai_performance_report"
                else None
            )
            if source_kind is None:
                raise ExternalDataError("Official report surface is not supported")
            payload = {
                "source_kind": source_kind,
                "platform": source["platform"],
                "surface": source["surface"],
                "period_start": source["report_period_start"].isoformat(),
                "period_end": source["report_period_end"].isoformat(),
                "rows": payload_rows,
            }
            return self._persist_draft(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                actor_id=actor_id,
                source_kind=source_kind,
                connection_id=None,
                scope_id=None,
                sync_run_id=None,
                projection_batch_id=None,
                official_report_import_id=import_id,
                period_start=source["report_period_start"],
                period_end=source["report_period_end"],
                as_of=source["imported_at"],
                freshness_status="unknown",
                schema_release=f"{source['parser_name']}:{source['parser_version']}",
                adapter_release=source["contract_version"],
                row_count=len(payload_rows),
                dataset_hash=canonical_hash(payload_rows),
                payload=payload,
                whitelist_version=f"official-fields:{canonical_hash(fields)}",
                lineage={
                    "official_report_import_id": str(import_id),
                    "artifact_hash": source["artifact_hash"],
                    "import_payload_hash": source["payload_hash"],
                },
                title=title,
                summary=summary,
            )

    def create_attribution_report(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        attribution_snapshot_id: UUID,
        actor_id: UUID,
        title: str,
        summary: str,
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            source = connection.execute(
                """SELECT snapshot.*, policy.version AS policy_version,
                          policy.policy_hash
                     FROM attribution_snapshots snapshot
                     JOIN attribution_policies policy
                       ON policy.project_id = snapshot.project_id
                      AND policy.id = snapshot.policy_id
                    WHERE snapshot.project_id = %s AND snapshot.id = %s""",
                (project_id, attribution_snapshot_id),
            ).fetchone()
            if source is None:
                raise ExternalDataError("Attribution Snapshot was not found")
            entries = source["result"].get("entries")
            if not isinstance(entries, list):
                raise ExternalDataError("Attribution Snapshot result is invalid")
            campaign_entries = [
                entry for entry in entries
                if isinstance(entry, Mapping) and _entry_has_campaign(entry, campaign_id)
            ]
            revenue_ids = [
                UUID(str(entry["revenue_id"])) for entry in campaign_entries
                if entry.get("revenue_id")
            ]
            if not revenue_ids:
                raise ExternalDataError("Attribution Snapshot has no revenue for this Campaign")
            period = connection.execute(
                """SELECT min(occurred_at)::date AS period_start,
                          max(occurred_at)::date AS period_end
                     FROM attribution_revenues
                    WHERE project_id = %s AND id = ANY(%s::uuid[])""",
                (project_id, revenue_ids),
            ).fetchone()
            totals: dict[str, float] = {}
            for entry in campaign_entries:
                currency = str(entry.get("currency") or "UNKNOWN")
                totals[currency] = totals.get(currency, 0.0) + float(entry.get("amount") or 0)
            payload = {
                "source_kind": "attribution_snapshot",
                "methodology": source["result"].get("methodology"),
                "policy": source["result"].get("policy"),
                "cutoff_at": source["cutoff_at"].isoformat(),
                "campaign_id": str(campaign_id),
                "summary": {
                    "revenue_count": len(campaign_entries),
                    "revenue_by_currency": totals,
                    "last_click_count": sum(
                        entry.get("last_click") is not None for entry in campaign_entries
                    ),
                    "assisted_revenue_count": sum(
                        bool(entry.get("assisted")) for entry in campaign_entries
                    ),
                },
            }
            return self._persist_draft(
                connection,
                project_id=project_id,
                campaign_id=campaign_id,
                actor_id=actor_id,
                source_kind="attribution_snapshot",
                connection_id=None,
                scope_id=None,
                sync_run_id=None,
                projection_batch_id=None,
                official_report_import_id=None,
                attribution_snapshot_id=attribution_snapshot_id,
                period_start=period["period_start"],
                period_end=period["period_end"],
                as_of=source["cutoff_at"],
                freshness_status="unknown",
                schema_release="attribution-customer-v1",
                adapter_release=f"attribution-policy-v{source['policy_version']}",
                row_count=len(campaign_entries),
                dataset_hash=canonical_hash(campaign_entries),
                payload=payload,
                whitelist_version="attribution-customer-aggregate-v1",
                lineage={
                    "attribution_snapshot_id": str(attribution_snapshot_id),
                    "attribution_result_hash": source["result_hash"],
                    "attribution_policy_hash": source["policy_hash"],
                },
                title=title,
                summary=summary,
            )

    def submit(self, *, project_id: UUID, report_id: UUID) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """UPDATE external_data_reports
                      SET status = 'in_review', submitted_at = %s, version = version + 1
                    WHERE project_id = %s AND id = %s AND status = 'draft'
                RETURNING *""",
                (self._clock(), project_id, report_id),
            ).fetchone()
        if row is None:
            raise ExternalDataError("External Data Report is not a draft")
        return dict(row)

    def decide(
        self,
        *,
        project_id: UUID,
        report_id: UUID,
        snapshot_hash: str,
        decision: str,
        actor_id: UUID,
        reason: str,
        review_evidence: Mapping[str, object],
        idempotency_key: str,
    ) -> Mapping[str, object]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT * FROM geo_decide_external_data_report(
                       %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    project_id,
                    report_id,
                    snapshot_hash,
                    decision,
                    actor_id,
                    reason,
                    Jsonb(dict(review_evidence)),
                    idempotency_key,
                ),
            ).fetchone()
        if row is None:
            raise ExternalDataError("External Data decision returned no report")
        return dict(row)

    def invalidate(
        self,
        *,
        project_id: UUID,
        report_id: UUID,
        snapshot_hash: str,
        decision: str,
        actor_id: UUID,
        reason: str,
        evidence: Mapping[str, object],
        idempotency_key: str,
    ) -> Mapping[str, object]:
        if decision not in {"stale", "revoked"}:
            raise ExternalDataError("External Data invalidation must be stale or revoked")
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT * FROM geo_invalidate_external_data_report(
                       %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    project_id,
                    report_id,
                    snapshot_hash,
                    decision,
                    actor_id,
                    reason,
                    Jsonb(dict(evidence)),
                    idempotency_key,
                ),
            ).fetchone()
        if row is None:
            raise ExternalDataError("External Data invalidation returned no report")
        return dict(row)

    def list_reports(
        self, *, project_id: UUID, campaign_id: UUID | None = None
    ) -> tuple[Mapping[str, object], ...]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT report.*, snapshot.source_kind, snapshot.period_start,
                          snapshot.period_end, snapshot.as_of,
                          snapshot.freshness_status, snapshot.row_count,
                          snapshot.lineage
                     FROM external_data_reports report
                     JOIN external_data_snapshots snapshot
                       ON snapshot.project_id = report.project_id
                      AND snapshot.id = report.snapshot_id
                    WHERE report.project_id = %s
                      AND (%s::uuid IS NULL OR report.campaign_id = %s)
                    ORDER BY report.created_at DESC, report.id DESC""",
                (project_id, campaign_id, campaign_id),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def list_operational_alert_inputs(
        self, *, project_id: UUID, limit: int = 100
    ) -> tuple[Mapping[str, object], ...]:
        bounded_limit = min(max(limit, 1), 500)
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT id, source_kind, source_id, source_version, signal_kind,
                          severity, reason_code, action_path, payload, input_hash,
                          observed_at, created_at
                     FROM external_operational_alert_inputs
                    WHERE project_id = %s
                    ORDER BY observed_at DESC, id DESC
                    LIMIT %s""",
                (project_id, bounded_limit),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def latest(self, *, project_id: UUID, campaign_id: UUID) -> tuple[Mapping[str, object], ...]:
        with self._connect() as connection:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT latest.*, snapshot.source_kind, snapshot.period_start,
                          snapshot.period_end, snapshot.as_of, snapshot.freshness_status,
                          snapshot.row_count, snapshot.customer_payload
                     FROM external_data_customer_latest latest
                     JOIN external_data_snapshots snapshot
                       ON snapshot.project_id = latest.project_id
                      AND snapshot.id = latest.snapshot_id
                    WHERE latest.project_id = %s AND latest.campaign_id = %s
                    ORDER BY latest.partition_key""",
                (project_id, campaign_id),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def _persist_draft(self, connection: Any, **values: object) -> Mapping[str, object]:
        payload = _json_value(values.pop("payload"))
        lineage = _json_value(values.pop("lineage"))
        title = str(values.pop("title")).strip()
        summary = str(values.pop("summary")).strip()
        if not title:
            raise ExternalDataError("External Data Report title is required")
        payload_hash = canonical_hash(payload)
        snapshot_value = {
            key: str(value) if isinstance(value, UUID) else value.isoformat()
            if hasattr(value, "isoformat")
            else value
            for key, value in values.items()
            if key not in {"actor_id"}
        }
        snapshot_hash = canonical_hash(
            {**snapshot_value, "payload_hash": payload_hash, "lineage": lineage}
        )
        snapshot_id, report_id, now = uuid4(), uuid4(), self._clock()
        connection.execute(
            """INSERT INTO external_data_snapshots(
                   id, project_id, campaign_id, source_kind, connection_id, scope_id,
                   sync_run_id, projection_batch_id, official_report_import_id,
                   attribution_snapshot_id,
                   period_start, period_end, as_of, freshness_status, schema_release,
                   adapter_release, row_count, dataset_hash, customer_whitelist_version,
                   customer_payload, customer_payload_hash, lineage, snapshot_hash,
                   created_by, created_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                         %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                snapshot_id,
                values["project_id"], values["campaign_id"], values["source_kind"],
                values["connection_id"], values["scope_id"], values["sync_run_id"],
                values["projection_batch_id"], values["official_report_import_id"],
                values.get("attribution_snapshot_id"),
                values["period_start"], values["period_end"], values["as_of"],
                values["freshness_status"], values["schema_release"],
                values["adapter_release"], values["row_count"], values["dataset_hash"],
                values["whitelist_version"], Jsonb(payload), payload_hash,
                Jsonb(lineage), snapshot_hash, values["actor_id"], now,
            ),
        )
        partition = (
            f"{values['source_kind']}:"
            f"{values['connection_id'] or values['official_report_import_id'] or values.get('attribution_snapshot_id')}:"
            f"{values['period_start']}:{values['period_end']}"
        )
        row = connection.execute(
            """INSERT INTO external_data_reports(
                   id, project_id, campaign_id, snapshot_id, snapshot_hash,
                   partition_key, title, summary, approval_policy_version,
                   approval_rubric_version, customer_schema_version, status,
                   created_by, created_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                         'external-data-approval-v1', 'external-data-rubric-v1',
                         'external-data-customer-v1', 'draft', %s, %s)
               RETURNING *""",
            (
                report_id, values["project_id"], values["campaign_id"], snapshot_id,
                snapshot_hash, partition, title, summary, values["actor_id"], now,
            ),
        ).fetchone()
        return {**dict(row), "snapshot": {"id": snapshot_id, "snapshot_hash": snapshot_hash}}


def _customer_fields(values: Sequence[str]) -> tuple[str, ...]:
    fields = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    if not fields or any(
        any(part in field.casefold() for part in _PROHIBITED_FIELD_PARTS) for field in fields
    ):
        raise ExternalDataError("Official report Customer fields are empty or prohibited")
    return fields


def _entry_has_campaign(entry: Mapping[str, object], campaign_id: UUID) -> bool:
    expected = str(campaign_id)
    candidates = [entry.get("first_click"), entry.get("last_click")]
    assisted = entry.get("assisted")
    if isinstance(assisted, list):
        candidates.extend(assisted)
    return any(
        isinstance(item, Mapping) and item.get("campaign_id") == expected
        for item in candidates
    )


def _json_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        key: _json_value(value)
        for key, value in row.items()
        if value is not None
    }


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _period(source: Mapping[str, object], rows: Sequence[Mapping[str, object]]):
    dates = [value for row in rows if isinstance((value := row.get("date")), date)]
    if dates:
        return min(dates), max(dates)
    start, end = source["window_start"], source["window_end"]
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise ExternalDataError("Projection has no report period")
    return start.date(), end.date()


__all__ = ["ExternalDataError", "ExternalDataService"]
