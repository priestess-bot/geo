from __future__ import annotations

from uuid import UUID, uuid4

import psycopg

from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import (
    MetricSnapshot,
    MonitoringObservation,
    MonitoringReport,
)


def assert_exact_customer_url_projection(
    *,
    admin_url: str,
    service: MonitoringApplication,
    principal: AccessPrincipal,
    project_id: UUID,
    campaign_id: UUID,
    other_campaign_id: UUID,
    marker: str,
    verified_url: str,
    verified_submission_id: UUID,
    verified_destination_id: UUID,
    member_observation: MonitoringObservation,
    approved_snapshot: MetricSnapshot,
    latest_report: MonitoringReport,
) -> None:
    non_member_url = f"https://example.com/{marker}/verified-after-approval"
    non_member_submission_id, non_member_observation_id = uuid4(), uuid4()
    with psycopg.connect(admin_url) as admin:
        admin.execute("SET LOCAL session_replication_role = 'replica'")
        admin.execute(
            """
            INSERT INTO publication_submissions
              (id, project_id, publication_request_id, submitted_url,
               idempotency_key, payload_hash, submitted_by,
               status, submitted_at, verified_at, campaign_id,
               opportunity_id, destination_id)
            SELECT %s::uuid, project_id, publication_request_id, %s::text,
                   %s::text, %s::text, submitted_by, 'verified',
                   clock_timestamp(), clock_timestamp(), campaign_id,
                   opportunity_id, destination_id
            FROM publication_submissions
            WHERE id = %s AND project_id = %s
            """,
            (
                non_member_submission_id,
                non_member_url,
                f"non-member-submission-{marker}",
                "7" * 64,
                verified_submission_id,
                project_id,
            ),
        )
        admin.execute(
            """
            INSERT INTO monitoring_observations
            SELECT (jsonb_populate_record(
                NULL::monitoring_observations,
                to_jsonb(observation) || jsonb_build_object(
                    'id', %s::uuid,
                    'sample_index', 4,
                    'idempotency_key', %s::text,
                    'payload_hash', %s::text,
                    'observed_at', clock_timestamp(),
                    'created_at', clock_timestamp()
                )
            )).*
            FROM monitoring_observations observation
            WHERE observation.id = %s AND observation.project_id = %s
            """,
            (
                non_member_observation_id,
                f"non-member-observation-{marker}",
                "8" * 64,
                member_observation.id,
                project_id,
            ),
        )
        admin.execute(
            """
            INSERT INTO monitoring_observation_citations
              (project_id, observation_id, citation_index, url, title,
               destination_id, submission_id, verification_status, verified_at)
            VALUES (%s, %s, 0, %s, 'Post-approval non-member',
                    %s, %s, 'passed', clock_timestamp())
            """,
            (
                project_id,
                non_member_observation_id,
                non_member_url,
                verified_destination_id,
                non_member_submission_id,
            ),
        )
        admin.execute("SET LOCAL session_replication_role = 'origin'")

    customer_urls = service.list_customer_approved_verified_urls(
        principal, project_id=project_id, campaign_id=campaign_id
    )
    assert [item.url for item in customer_urls] == [verified_url]
    assert non_member_url not in {item.url for item in customer_urls}
    assert customer_urls[0].campaign_id == campaign_id
    assert customer_urls[0].observation_count == 1
    assert (
        service.list_customer_approved_verified_urls(
            principal, project_id=project_id, campaign_id=other_campaign_id
        )
        == ()
    )

    legacy_snapshot_id, legacy_report_id = uuid4(), uuid4()
    with psycopg.connect(admin_url) as admin:
        admin.execute("SET LOCAL session_replication_role = 'replica'")
        admin.execute(
            """
            INSERT INTO monitoring_metric_snapshots
            SELECT (jsonb_populate_record(
                NULL::monitoring_metric_snapshots,
                to_jsonb(snapshot) || jsonb_build_object(
                    'id', %s::uuid,
                    'input_hash', %s::text,
                    'computed_at', clock_timestamp(),
                    'observation_membership_version', NULL,
                    'observation_membership_count', NULL,
                    'observation_membership_hash', NULL
                )
            )).*
            FROM monitoring_metric_snapshots snapshot
            WHERE snapshot.id = %s AND snapshot.project_id = %s
            """,
            (legacy_snapshot_id, "6" * 64, approved_snapshot.id, project_id),
        )
        admin.execute(
            """
            INSERT INTO monitoring_reports
            SELECT (jsonb_populate_record(
                NULL::monitoring_reports,
                to_jsonb(report) || jsonb_build_object(
                    'id', %s::uuid,
                    'metric_snapshot_id', %s::uuid,
                    'title', 'Legacy snapshot without exact members',
                    'report_hash', %s::text,
                    'generated_at', clock_timestamp(),
                    'approved_at', clock_timestamp()
                )
            )).*
            FROM monitoring_reports report
            WHERE report.id = %s AND report.project_id = %s
            """,
            (
                legacy_report_id,
                legacy_snapshot_id,
                "5" * 64,
                latest_report.id,
                project_id,
            ),
        )
        admin.execute("SET LOCAL session_replication_role = 'origin'")

    assert (
        service.list_customer_approved_verified_urls(
            principal, project_id=project_id, campaign_id=campaign_id
        )
        == ()
    )
