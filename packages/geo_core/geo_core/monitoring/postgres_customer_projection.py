"""PostgreSQL reads for the Customer Campaign reporting projection."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from geo_core.monitoring.customer_projection import (
    ApprovedReportSnapshot,
    CustomerCampaign,
)
from geo_core.monitoring.domain import VerifiedUrl
from geo_core.monitoring.postgres_mappers import metric_from_row, report_from_row


class MonitoringCustomerProjectionMixin:
    """Queries run under the Monitoring Unit of Work's RLS transaction."""

    def list_customer_campaigns(
        self, *, project_id: UUID
    ) -> tuple[CustomerCampaign, ...]:
        rows = self._many(  # type: ignore[attr-defined]
            """
            SELECT campaign.id, campaign.project_id, campaign.name,
                   campaign.objective, campaign.status,
                   count(report.id)::integer AS approved_report_count,
                   max(report.approved_at) AS latest_approved_at
            FROM geo_campaigns campaign
            LEFT JOIN monitoring_reports report
              ON report.project_id = campaign.project_id
             AND report.campaign_id = campaign.id
             AND report.status = 'approved'
            WHERE campaign.project_id = %s
            GROUP BY campaign.id, campaign.project_id, campaign.name,
                     campaign.objective, campaign.status, campaign.created_at
            ORDER BY campaign.created_at DESC, campaign.id DESC
            """,
            (project_id,),
            "list customer campaigns",
        )
        return tuple(_campaign(row) for row in rows)

    def get_customer_campaign(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> CustomerCampaign | None:
        row = self._optional(  # type: ignore[attr-defined]
            """
            SELECT campaign.id, campaign.project_id, campaign.name,
                   campaign.objective, campaign.status,
                   count(report.id)::integer AS approved_report_count,
                   max(report.approved_at) AS latest_approved_at
            FROM geo_campaigns campaign
            LEFT JOIN monitoring_reports report
              ON report.project_id = campaign.project_id
             AND report.campaign_id = campaign.id
             AND report.status = 'approved'
            WHERE campaign.project_id = %s AND campaign.id = %s
            GROUP BY campaign.id, campaign.project_id, campaign.name,
                     campaign.objective, campaign.status
            """,
            (project_id, campaign_id),
            "read customer campaign",
        )
        return _campaign(row) if row else None

    def list_customer_approved_report_snapshots(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[ApprovedReportSnapshot, ...]:
        rows = self._many(  # type: ignore[attr-defined]
            """
            SELECT *
            FROM (
                SELECT DISTINCT ON (
                    report.campaign_id,
                    report.protocol_id,
                    snapshot.measurement_window,
                    snapshot.source_stratum_hash,
                    snapshot.query_cluster_key
                )
                    snapshot.*,
                    report.id AS approved_report_id,
                    report.project_id AS approved_report_project_id,
                    report.protocol_id AS approved_report_protocol_id,
                    report.campaign_id AS approved_report_campaign_id,
                    report.metric_snapshot_id AS approved_report_snapshot_id,
                    report.title AS approved_report_title,
                    report.body AS approved_report_body,
                    report.methodology_statement AS approved_report_methodology,
                    report.report_hash AS approved_report_hash,
                    report.status AS approved_report_status,
                    report.generated_at AS approved_report_generated_at,
                    report.approved_at AS approved_report_approved_at,
                    report.approved_at,
                    report.id AS ordering_report_id
                FROM monitoring_reports report
                JOIN monitoring_metric_snapshots snapshot
                  ON snapshot.project_id = report.project_id
                 AND snapshot.campaign_id = report.campaign_id
                 AND snapshot.protocol_id = report.protocol_id
                 AND snapshot.id = report.metric_snapshot_id
                WHERE report.project_id = %s
                  AND report.campaign_id = %s
                  AND report.status = 'approved'
                  AND report.approved_at IS NOT NULL
                ORDER BY report.campaign_id, report.protocol_id,
                         snapshot.measurement_window,
                         snapshot.source_stratum_hash NULLS FIRST,
                         snapshot.query_cluster_key NULLS FIRST,
                         report.approved_at DESC,
                         snapshot.computed_at DESC,
                         report.id DESC
            ) latest
            ORDER BY approved_at DESC, computed_at DESC, ordering_report_id DESC
            """,
            (project_id, campaign_id),
            "list approved customer report snapshots",
        )
        return tuple(_approved_snapshot(row) for row in rows)

    def list_customer_approved_verified_urls(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[VerifiedUrl, ...]:
        rows = self._many(  # type: ignore[attr-defined]
            """
            WITH ranked AS (
                SELECT report.project_id, report.campaign_id, report.protocol_id,
                       snapshot.id AS snapshot_id,
                       snapshot.measurement_window, snapshot.source_stratum_hash,
                       snapshot.query_cluster_key, snapshot.verified_destination_ids,
                       snapshot.observation_membership_version,
                       row_number() OVER (
                           PARTITION BY report.campaign_id, report.protocol_id,
                                        snapshot.measurement_window,
                                        snapshot.source_stratum_hash,
                                        snapshot.query_cluster_key
                           ORDER BY report.approved_at DESC,
                                    snapshot.computed_at DESC,
                                    report.id DESC
                       ) AS position
                FROM monitoring_reports report
                JOIN monitoring_metric_snapshots snapshot
                  ON snapshot.project_id = report.project_id
                 AND snapshot.campaign_id = report.campaign_id
                 AND snapshot.protocol_id = report.protocol_id
                 AND snapshot.id = report.metric_snapshot_id
                WHERE report.project_id = %s
                  AND report.campaign_id = %s
                  AND report.status = 'approved'
                  AND report.approved_at IS NOT NULL
            ), approved_scope AS (
                SELECT * FROM ranked
                WHERE position = 1
                  AND observation_membership_version
                        = 'metric-observation-membership-v1'
                  AND verified_destination_ids IS NOT NULL
                  AND cardinality(verified_destination_ids) > 0
            )
            SELECT scope.campaign_id,
                   array_agg(DISTINCT scope.protocol_id ORDER BY scope.protocol_id)
                     AS protocol_ids,
                   submission.submitted_url AS url,
                   max(destination.destination_key) AS title,
                   request.destination_id,
                   min(submission.verified_at) AS first_verified_at,
                   count(DISTINCT observation.id)::integer AS observation_count
            FROM approved_scope scope
            JOIN monitoring_metric_snapshot_observations member
              ON member.snapshot_id = scope.snapshot_id
             AND member.project_id = scope.project_id
             AND member.campaign_id = scope.campaign_id
             AND member.protocol_id = scope.protocol_id
            JOIN monitoring_observations observation
              ON observation.id = member.observation_id
             AND observation.project_id = member.project_id
             AND observation.campaign_id = member.campaign_id
             AND observation.protocol_id = member.protocol_id
             AND observation.payload_hash = member.payload_hash
             AND observation.measurement_window = scope.measurement_window
             AND observation.source_stratum_hash
                   IS NOT DISTINCT FROM scope.source_stratum_hash
             AND observation.query_cluster_key
                   IS NOT DISTINCT FROM scope.query_cluster_key
             AND observation.result_status = 'succeeded'
             AND observation.eligible
             AND observation.capture_method IN (
                 'manual_ui', 'provider_api', 'proxy_grounded_api'
             )
             AND observation.url_verification_status = 'passed'
            JOIN monitoring_observation_citations citation
              ON citation.observation_id = observation.id
             AND citation.project_id = observation.project_id
             AND citation.verification_status = 'passed'
             AND citation.submission_id IS NOT NULL
            JOIN publication_submissions submission
              ON submission.id = citation.submission_id
             AND submission.project_id = citation.project_id
             AND submission.campaign_id = scope.campaign_id
             AND submission.destination_id = citation.destination_id
             AND submission.status = 'verified'
             AND submission.verified_at IS NOT NULL
             AND submission.submitted_url IS NOT NULL
             AND submission.submitted_url = citation.url
            JOIN publication_requests request
              ON request.id = submission.publication_request_id
             AND request.project_id = submission.project_id
             AND request.campaign_id = submission.campaign_id
             AND request.opportunity_id = submission.opportunity_id
             AND request.destination_id = submission.destination_id
             AND request.destination_id = ANY(scope.verified_destination_ids)
            JOIN publication_destinations destination
              ON destination.id = request.destination_id
             AND destination.project_id = request.project_id
            GROUP BY scope.campaign_id, submission.submitted_url,
                     request.destination_id
            ORDER BY first_verified_at DESC, submission.submitted_url
            """,
            (project_id, campaign_id),
            "list approved customer verified URLs",
        )
        return tuple(_verified_url(row) for row in rows)


def _campaign(row: Mapping[str, Any]) -> CustomerCampaign:
    return CustomerCampaign(
        id=cast(UUID, row["id"]),
        project_id=cast(UUID, row["project_id"]),
        name=str(row["name"]),
        objective=str(row["objective"]),
        status=str(row["status"]),
        approved_report_count=int(row["approved_report_count"]),
        latest_approved_at=cast(datetime | None, row["latest_approved_at"]),
    )


def _approved_snapshot(row: Mapping[str, Any]) -> ApprovedReportSnapshot:
    return ApprovedReportSnapshot(
        report=report_from_row(
            {
                "id": row["approved_report_id"],
                "project_id": row["approved_report_project_id"],
                "protocol_id": row["approved_report_protocol_id"],
                "campaign_id": row["approved_report_campaign_id"],
                "metric_snapshot_id": row["approved_report_snapshot_id"],
                "title": row["approved_report_title"],
                "body": row["approved_report_body"],
                "methodology_statement": row["approved_report_methodology"],
                "report_hash": row["approved_report_hash"],
                "status": row["approved_report_status"],
                "generated_at": row["approved_report_generated_at"],
                "approved_at": row["approved_report_approved_at"],
            }
        ),
        snapshot=metric_from_row(row),
    )


def _verified_url(row: Mapping[str, Any]) -> VerifiedUrl:
    return VerifiedUrl(
        campaign_id=cast(UUID, row["campaign_id"]),
        protocol_ids=tuple(cast(list[UUID], row["protocol_ids"])),
        url=str(row["url"]),
        title=str(row["title"]) if row["title"] else None,
        destination_id=cast(UUID | None, row["destination_id"]),
        first_verified_at=cast(datetime, row["first_verified_at"]),
        observation_count=int(row["observation_count"]),
    )
