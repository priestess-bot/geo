"""Metric, report and customer projection queries for the monitoring repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, cast
from uuid import UUID

from psycopg.types.json import Jsonb

from geo_core.monitoring.domain import (
    REPORT_METHODOLOGY,
    OBSERVATION_MEMBERSHIP_VERSION,
    MetricObservationMembership,
    MetricSnapshot,
    MonitoringObservation,
    MonitoringNotFound,
    MonitoringReport,
    VerifiedUrl,
    metric_observation_membership,
    observation_membership_hash,
)
from geo_core.monitoring.postgres_mappers import metric_from_row, report_from_row
from geo_core.monitoring.source_contract import SOURCE_CONTRACT_VERSION


class MonitoringReportingMixin:
    """Composes with a repository that provides `_one`, `_optional` and `_many`."""

    _one: Any
    _optional: Any
    _many: Any
    _observation: Any

    def create_metric_snapshot(
        self,
        *,
        snapshot: MetricSnapshot,
        observations: tuple[MonitoringObservation, ...],
        actor_id: UUID,
    ) -> MetricSnapshot:
        if snapshot.source_stratum is None or snapshot.source_stratum_hash is None:
            raise ValueError("new metric snapshots require a typed source stratum")
        if snapshot.source_stratum.source_contract_version != SOURCE_CONTRACT_VERSION:
            raise ValueError("new metric snapshots require source stratum contract v3")
        if snapshot.result_hash is None:
            raise ValueError("new metric snapshots require a canonical result hash")
        memberships = metric_observation_membership(snapshot.id, observations)
        membership_hash = observation_membership_hash(memberships)
        if (
            snapshot.observation_membership_version != OBSERVATION_MEMBERSHIP_VERSION
            or snapshot.observation_membership_count != len(memberships)
            or snapshot.observation_membership_hash != membership_hash
        ):
            raise ValueError("metric observation membership differs from its manifest")
        existing = self._optional(
            """SELECT * FROM monitoring_metric_snapshots
               WHERE project_id = %s AND campaign_id = %s AND protocol_id = %s
                 AND measurement_window = %s AND source_stratum_hash = %s
                 AND query_cluster_key = %s
                 AND input_hash = %s""",
            (
                snapshot.project_id,
                snapshot.campaign_id,
                snapshot.protocol_id,
                snapshot.measurement_window.value,
                snapshot.source_stratum_hash,
                snapshot.query_cluster_key,
                snapshot.input_hash,
            ),
            "check the metric snapshot input",
        )
        if existing:
            persisted = metric_from_row(existing)
            stored = self.list_metric_observation_memberships(
                project_id=snapshot.project_id,
                campaign_id=snapshot.campaign_id,
                snapshot_ids=(persisted.id,),
            )
            if [item.canonical_value() for item in stored] != [
                item.canonical_value() for item in memberships
            ]:
                raise ValueError("stored metric observation membership is inconsistent")
            return persisted
        row = self._one(
            """
            INSERT INTO monitoring_metric_snapshots
              (id, project_id, protocol_id, campaign_id, measurement_window,
               expected_sample_count, sampled_sample_count,
               eligible_sample_count, recommendation_share, product_mention_share,
               placement_citation_share, qualified_destination_coverage,
               verified_placement_coverage, competitive_delta, status,
               confounded_reasons, source_stratum, source_stratum_hash,
               capture_method, source_contract_version, input_hash, method_version,
               computed_by, computed_at, statistics_contract_version,
               query_cluster_key, analysis_stratum_hash, minimum_valid_repeats,
               invalid_sample_count, missing_sample_count,
               sampling_completion_ratio, valid_completion_ratio, query_count,
               sufficient_query_count, invalid_reason_counts,
               declared_confounding_factors, query_results_snapshot,
               recommendation_ci_low, recommendation_ci_high,
               product_mention_ci_low, product_mention_ci_high,
               placement_citation_ci_low, placement_citation_ci_high,
               recommendation_query_min, recommendation_query_max,
               product_mention_query_min, product_mention_query_max,
               placement_citation_query_min, placement_citation_query_max,
               worst_query_id, selected_destination_ids,
               qualified_destination_ids, verified_destination_ids, result_hash,
               observation_membership_version, observation_membership_hash,
               observation_membership_count)
            VALUES
              (%(id)s, %(project_id)s, %(protocol_id)s, %(campaign_id)s,
               %(measurement_window)s, %(expected_sample_count)s,
               %(sampled_sample_count)s, %(eligible_sample_count)s,
               %(recommendation_share)s, %(product_mention_share)s,
               %(placement_citation_share)s, %(qualified_destination_coverage)s,
               %(verified_placement_coverage)s, %(competitive_delta)s, %(status)s,
               %(confounded_reasons)s, %(source_stratum)s, %(source_stratum_hash)s,
               %(capture_method)s, %(source_contract_version)s, %(input_hash)s,
               %(method_version)s, %(actor_id)s, %(computed_at)s,
               %(statistics_contract_version)s, %(query_cluster_key)s,
               %(analysis_stratum_hash)s, %(minimum_valid_repeats)s,
               %(invalid_sample_count)s, %(missing_sample_count)s,
               %(sampling_completion_ratio)s, %(valid_completion_ratio)s,
               %(query_count)s, %(sufficient_query_count)s,
               %(invalid_reason_counts)s, %(declared_confounding_factors)s,
               %(query_results_snapshot)s, %(recommendation_ci_low)s,
               %(recommendation_ci_high)s, %(product_mention_ci_low)s,
               %(product_mention_ci_high)s, %(placement_citation_ci_low)s,
               %(placement_citation_ci_high)s, %(recommendation_query_min)s,
               %(recommendation_query_max)s, %(product_mention_query_min)s,
               %(product_mention_query_max)s, %(placement_citation_query_min)s,
               %(placement_citation_query_max)s, %(worst_query_id)s,
               %(selected_destination_ids)s, %(qualified_destination_ids)s,
               %(verified_destination_ids)s, %(result_hash)s,
               %(observation_membership_version)s, %(observation_membership_hash)s,
               %(observation_membership_count)s)
            RETURNING *
            """,
            {
                **snapshot.__dict__,
                "measurement_window": snapshot.measurement_window.value,
                "confounded_reasons": list(snapshot.confounded_reasons),
                "source_stratum": Jsonb(snapshot.source_stratum.canonical_value()),
                "capture_method": snapshot.source_stratum.capture_method.value,
                "source_contract_version": SOURCE_CONTRACT_VERSION,
                "invalid_reason_counts": Jsonb(dict(snapshot.invalid_reason_counts)),
                "declared_confounding_factors": list(snapshot.declared_confounding_factors),
                "query_results_snapshot": Jsonb(
                    [item.canonical_value() for item in snapshot.query_results]
                ),
                "selected_destination_ids": list(snapshot.selected_destination_ids),
                "qualified_destination_ids": list(snapshot.qualified_destination_ids),
                "verified_destination_ids": list(snapshot.verified_destination_ids),
                "actor_id": actor_id,
            },
            "persist the metric snapshot",
        )
        persisted = metric_from_row(row)
        for member in memberships:
            self._one(
                """
                INSERT INTO monitoring_metric_snapshot_observations
                  (project_id, snapshot_id, campaign_id, protocol_id,
                   observation_id, ordinal, payload_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING observation_id
                """,
                (
                    snapshot.project_id,
                    persisted.id,
                    snapshot.campaign_id,
                    snapshot.protocol_id,
                    member.observation_id,
                    member.ordinal,
                    member.payload_hash,
                ),
                "freeze the metric observation membership",
            )
        return persisted

    def list_metric_observation_memberships(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        snapshot_ids: tuple[UUID, ...],
    ) -> tuple[MetricObservationMembership, ...]:
        if not snapshot_ids:
            return ()
        rows = self._many(
            """
            SELECT member.*
            FROM monitoring_metric_snapshot_observations member
            JOIN monitoring_metric_snapshots snapshot
              ON snapshot.id = member.snapshot_id
             AND snapshot.project_id = member.project_id
            WHERE snapshot.project_id = %s AND snapshot.campaign_id = %s
              AND member.snapshot_id = ANY(%s)
            ORDER BY member.snapshot_id, member.ordinal
            """,
            (project_id, campaign_id, list(snapshot_ids)),
            "list metric observation memberships",
        )
        return tuple(
            MetricObservationMembership(
                snapshot_id=cast(UUID, row["snapshot_id"]),
                observation_id=cast(UUID, row["observation_id"]),
                payload_hash=str(row["payload_hash"]),
                ordinal=int(row["ordinal"]),
            )
            for row in rows
        )

    def list_metric_snapshot_observations(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        snapshot_ids: tuple[UUID, ...],
    ) -> Mapping[UUID, tuple[MonitoringObservation, ...]]:
        if not snapshot_ids:
            return {}
        snapshots = self._many(
            """SELECT id FROM monitoring_metric_snapshots
               WHERE project_id = %s AND campaign_id = %s AND id = ANY(%s)""",
            (project_id, campaign_id, list(snapshot_ids)),
            "read metric snapshots for frozen observations",
        )
        result: dict[UUID, list[MonitoringObservation]] = {
            cast(UUID, row["id"]): [] for row in snapshots
        }
        rows = self._many(
            """
            SELECT member.snapshot_id AS membership_snapshot_id,
                   member.payload_hash AS membership_payload_hash,
                   observation.*
            FROM monitoring_metric_snapshot_observations member
            JOIN monitoring_metric_snapshots snapshot
              ON snapshot.id = member.snapshot_id
             AND snapshot.project_id = member.project_id
            JOIN monitoring_observations observation
              ON observation.id = member.observation_id
             AND observation.project_id = member.project_id
            WHERE snapshot.project_id = %s AND snapshot.campaign_id = %s
              AND member.snapshot_id = ANY(%s)
            ORDER BY member.snapshot_id, member.ordinal
            """,
            (project_id, campaign_id, list(snapshot_ids)),
            "list frozen metric observations",
        )
        for row in rows:
            if row["membership_payload_hash"] != row["payload_hash"]:
                raise ValueError("frozen observation payload hash no longer matches")
            snapshot_id = cast(UUID, row["membership_snapshot_id"])
            result[snapshot_id].append(self._observation(row, replayed=False))
        return {key: tuple(values) for key, values in result.items()}

    def get_metric_snapshot(
        self, *, project_id: UUID, campaign_id: UUID, snapshot_id: UUID
    ) -> MetricSnapshot | None:
        row = self._optional(
            """SELECT * FROM monitoring_metric_snapshots
               WHERE project_id = %s AND campaign_id = %s AND id = %s""",
            (project_id, campaign_id, snapshot_id),
            "read the metric snapshot",
        )
        return metric_from_row(row) if row else None

    def list_metric_snapshots(
        self, *, project_id: UUID, campaign_id: UUID, latest_only: bool
    ) -> tuple[MetricSnapshot, ...]:
        distinct = (
            "DISTINCT ON (protocol_id, measurement_window, source_stratum_hash, "
            "query_cluster_key)"
            if latest_only
            else ""
        )
        rows = self._many(
            f"""SELECT {distinct} * FROM monitoring_metric_snapshots
                WHERE project_id = %s AND campaign_id = %s
                ORDER BY protocol_id, measurement_window, source_stratum_hash,
                         query_cluster_key,
                         computed_at DESC, id DESC""",
            (project_id, campaign_id),
            "list metric snapshots",
        )
        return tuple(metric_from_row(row) for row in rows)

    def create_report(self, **values: Any) -> MonitoringReport:
        snapshot = cast(MetricSnapshot, values["snapshot"])
        existing = self._optional(
            """SELECT * FROM monitoring_reports
               WHERE project_id = %s AND campaign_id = %s AND report_hash = %s""",
            (values["project_id"], values["campaign_id"], values["report_hash"]),
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
            WHERE project_id = %(project_id)s AND campaign_id = %(campaign_id)s
              AND id = %(report_id)s AND status = 'draft'
            RETURNING *
            """,
            values,
            "approve the monitoring report",
        )
        if row is None:
            existing = self._optional(
                """SELECT * FROM monitoring_reports
                   WHERE project_id = %s AND campaign_id = %s AND id = %s""",
                (values["project_id"], values["campaign_id"], values["report_id"]),
                "read the monitoring report",
            )
            if existing and existing["status"] == "approved":
                return report_from_row(existing)
            raise MonitoringNotFound("The draft monitoring report does not exist.")
        return report_from_row(row)

    def list_reports(
        self, *, project_id: UUID, campaign_id: UUID, approved_only: bool
    ) -> tuple[MonitoringReport, ...]:
        condition = "AND status = 'approved'" if approved_only else ""
        rows = self._many(
            f"""SELECT * FROM monitoring_reports
                WHERE project_id = %s AND campaign_id = %s {condition}
                ORDER BY generated_at DESC, id DESC""",
            (project_id, campaign_id),
            "list monitoring reports",
        )
        return tuple(report_from_row(row) for row in rows)

    def list_verified_urls(self, *, project_id: UUID, campaign_id: UUID) -> tuple[VerifiedUrl, ...]:
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
             AND observed.capture_method IN (
                 'manual_ui', 'provider_api', 'proxy_grounded_api'
             )
             AND observed.url_verification_status = 'passed'
            WHERE s.project_id = %s AND s.status = 'verified'
              AND source_opportunity.campaign_id = %s
              AND s.submitted_url IS NOT NULL
            GROUP BY source_opportunity.campaign_id, s.submitted_url, r.destination_id
            ORDER BY first_verified_at DESC, s.submitted_url
            """,
            (project_id, campaign_id),
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
