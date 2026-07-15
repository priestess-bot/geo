"""Metric, report and customer projection queries for the monitoring repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from geo_core.monitoring.domain import (
    REPORT_METHODOLOGY,
    MetricSnapshot,
    MonitoringNotFound,
    MonitoringReport,
    VerifiedUrl,
)
from geo_core.monitoring.postgres_mappers import metric_from_row, report_from_row


class MonitoringReportingMixin:
    """Composes with a repository that provides `_one`, `_optional` and `_many`."""

    _one: Any
    _optional: Any
    _many: Any

    def create_metric_snapshot(
        self, *, snapshot: MetricSnapshot, actor_id: UUID
    ) -> MetricSnapshot:
        existing = self._optional(
            """SELECT * FROM monitoring_metric_snapshots
               WHERE project_id = %s AND protocol_id = %s
                 AND measurement_window = %s AND input_hash = %s""",
            (
                snapshot.project_id,
                snapshot.protocol_id,
                snapshot.measurement_window.value,
                snapshot.input_hash,
            ),
            "check the metric snapshot input",
        )
        if existing:
            return metric_from_row(existing)
        row = self._one(
            """
            INSERT INTO monitoring_metric_snapshots
              (id, project_id, protocol_id, campaign_id, measurement_window,
               expected_sample_count,
               eligible_sample_count, recommendation_share, product_mention_share,
               placement_citation_share, qualified_destination_coverage,
               verified_placement_coverage, competitive_delta, status,
               confounded_reasons, input_hash, method_version, computed_by, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                snapshot.id,
                snapshot.project_id,
                snapshot.protocol_id,
                snapshot.campaign_id,
                snapshot.measurement_window.value,
                snapshot.expected_sample_count,
                snapshot.eligible_sample_count,
                snapshot.recommendation_share,
                snapshot.product_mention_share,
                snapshot.placement_citation_share,
                snapshot.qualified_destination_coverage,
                snapshot.verified_placement_coverage,
                snapshot.competitive_delta,
                snapshot.status,
                list(snapshot.confounded_reasons),
                snapshot.input_hash,
                snapshot.method_version,
                actor_id,
                snapshot.computed_at,
            ),
            "persist the metric snapshot",
        )
        return metric_from_row(row)

    def get_metric_snapshot(
        self, *, project_id: UUID, snapshot_id: UUID
    ) -> MetricSnapshot | None:
        row = self._optional(
            "SELECT * FROM monitoring_metric_snapshots WHERE project_id = %s AND id = %s",
            (project_id, snapshot_id),
            "read the metric snapshot",
        )
        return metric_from_row(row) if row else None

    def list_metric_snapshots(
        self, *, project_id: UUID, latest_only: bool
    ) -> tuple[MetricSnapshot, ...]:
        distinct = "DISTINCT ON (protocol_id, measurement_window)" if latest_only else ""
        rows = self._many(
            f"""SELECT {distinct} * FROM monitoring_metric_snapshots
                WHERE project_id = %s
                ORDER BY protocol_id, measurement_window, computed_at DESC, id DESC""",
            (project_id,),
            "list metric snapshots",
        )
        return tuple(metric_from_row(row) for row in rows)

    def create_report(self, **values: Any) -> MonitoringReport:
        snapshot = cast(MetricSnapshot, values["snapshot"])
        existing = self._optional(
            "SELECT * FROM monitoring_reports WHERE project_id = %s AND report_hash = %s",
            (values["project_id"], values["report_hash"]),
            "check the report hash",
        )
        if existing:
            return report_from_row(existing)
        row = self._one(
            """
            INSERT INTO monitoring_reports
              (project_id, protocol_id, campaign_id, metric_snapshot_id, title, body,
               methodology_statement, report_hash, generated_by)
            VALUES (%(project_id)s, %(protocol_id)s, %(campaign_id)s,
                    %(metric_snapshot_id)s, %(title)s, %(body)s, %(methodology)s,
                    %(report_hash)s, %(actor_id)s)
            RETURNING *
            """,
            {
                **values,
                "campaign_id": snapshot.campaign_id,
                "metric_snapshot_id": snapshot.id,
                "methodology": REPORT_METHODOLOGY,
            },
            "generate the monitoring report",
        )
        return report_from_row(row)

    def approve_report(self, **values: Any) -> MonitoringReport:
        row = self._optional(
            """
            UPDATE monitoring_reports
            SET status = 'approved', approved_by = %(actor_id)s,
                approved_at = clock_timestamp()
            WHERE project_id = %(project_id)s AND id = %(report_id)s AND status = 'draft'
            RETURNING *
            """,
            values,
            "approve the monitoring report",
        )
        if row is None:
            existing = self._optional(
                "SELECT * FROM monitoring_reports WHERE project_id = %s AND id = %s",
                (values["project_id"], values["report_id"]),
                "read the monitoring report",
            )
            if existing and existing["status"] == "approved":
                return report_from_row(existing)
            raise MonitoringNotFound("The draft monitoring report does not exist.")
        return report_from_row(row)

    def list_reports(
        self, *, project_id: UUID, approved_only: bool
    ) -> tuple[MonitoringReport, ...]:
        condition = "AND status = 'approved'" if approved_only else ""
        rows = self._many(
            f"""SELECT * FROM monitoring_reports WHERE project_id = %s {condition}
                ORDER BY generated_at DESC, id DESC""",
            (project_id,),
            "list monitoring reports",
        )
        return tuple(report_from_row(row) for row in rows)

    def list_verified_urls(self, *, project_id: UUID) -> tuple[VerifiedUrl, ...]:
        rows = self._many(
            """
            SELECT source_opportunity.campaign_id,
                   array_agg(DISTINCT protocol.id ORDER BY protocol.id) AS protocol_ids,
                   s.submitted_url AS url, max(d.destination_key) AS title,
                   r.destination_id, min(s.verified_at) AS first_verified_at,
                   count(DISTINCT observed.id)::integer AS observation_count
            FROM publication_submissions s
            JOIN publication_requests r
              ON r.id = s.publication_request_id AND r.project_id = s.project_id
            JOIN publication_destinations d
              ON d.id = r.destination_id AND d.project_id = r.project_id
            JOIN placement_package_versions pv
              ON pv.id = r.package_version_id AND pv.project_id = r.project_id
            JOIN placement_packages package
              ON package.id = pv.package_id AND package.project_id = pv.project_id
            JOIN placement_opportunities source_opportunity
              ON source_opportunity.id = package.opportunity_id
             AND source_opportunity.project_id = package.project_id
            JOIN monitoring_protocols protocol
              ON protocol.campaign_id = source_opportunity.campaign_id
             AND protocol.project_id = source_opportunity.project_id
             AND protocol.status = 'frozen'
            LEFT JOIN monitoring_observation_citations citation
              ON citation.submission_id = s.id AND citation.project_id = s.project_id
             AND citation.verification_status = 'passed'
             AND citation.url = s.submitted_url
             AND citation.destination_id = r.destination_id
            LEFT JOIN monitoring_observations observed
              ON observed.id = citation.observation_id
             AND observed.project_id = citation.project_id
             AND observed.campaign_id = source_opportunity.campaign_id
             AND observed.result_status = 'succeeded' AND observed.eligible
             AND observed.url_verification_status = 'passed'
            WHERE s.project_id = %s AND s.status = 'verified'
              AND s.submitted_url IS NOT NULL
            GROUP BY source_opportunity.campaign_id, s.submitted_url, r.destination_id
            ORDER BY first_verified_at DESC, s.submitted_url
            """,
            (project_id,),
            "list verified customer URLs",
        )
        return tuple(
            VerifiedUrl(
                campaign_id=cast(UUID, row["campaign_id"]),
                protocol_ids=tuple(cast(list[UUID], row["protocol_ids"])),
                url=str(row["url"]),
                title=str(row["title"]) if row["title"] else None,
                destination_id=cast(UUID | None, row["destination_id"]),
                first_verified_at=cast(datetime, row["first_verified_at"]),
                observation_count=int(row["observation_count"]),
            )
            for row in rows
        )
