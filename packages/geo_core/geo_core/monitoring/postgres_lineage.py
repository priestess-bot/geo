"""Trusted citation target and publication-lineage queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from geo_core.monitoring.domain import (
    CitationDraft,
    MonitoringRuleViolation,
    ProtocolQuery,
    VerificationStatus,
    VerifiedCitationTarget,
)
from geo_core.monitoring.postgres_mappers import protocol_query_from_row


class MonitoringLineageMixin:
    """Composes with a repository that provides `_optional` and `_many`."""

    _optional: Any
    _many: Any

    def list_protocol_queries(
        self, *, project_id: UUID, protocol_id: UUID
    ) -> tuple[ProtocolQuery, ...]:
        rows = self._many(
            """SELECT * FROM monitoring_protocol_queries
               WHERE project_id = %s AND protocol_id = %s ORDER BY ordinal""",
            (project_id, protocol_id),
            "list frozen protocol queries",
        )
        return tuple(protocol_query_from_row(row) for row in rows)

    def list_verified_citation_targets(
        self, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[VerifiedCitationTarget, ...]:
        rows = self._many(
            """
            SELECT s.id AS submission_id, r.destination_id, d.destination_key,
                   d.publication_channel, s.submitted_url AS url, s.verified_at
            FROM publication_submissions s
            JOIN publication_requests r
              ON r.id = s.publication_request_id AND r.project_id = s.project_id
            JOIN publication_destinations d
              ON d.id = r.destination_id AND d.project_id = r.project_id
            JOIN placement_package_versions version
              ON version.id = r.package_version_id AND version.project_id = r.project_id
            JOIN placement_packages package
              ON package.id = version.package_id AND package.project_id = version.project_id
            JOIN placement_opportunities opportunity
              ON opportunity.id = package.opportunity_id
             AND opportunity.project_id = package.project_id
            WHERE s.project_id = %s AND opportunity.campaign_id = %s
              AND s.status = 'verified' AND s.submitted_url IS NOT NULL
              AND s.verified_at IS NOT NULL
            ORDER BY s.verified_at DESC, s.id
            """,
            (project_id, campaign_id),
            "list verified citation targets",
        )
        return tuple(
            VerifiedCitationTarget(
                submission_id=cast(UUID, row["submission_id"]),
                destination_id=cast(UUID, row["destination_id"]),
                destination_key=str(row["destination_key"]),
                publication_channel=str(row["publication_channel"]),
                url=str(row["url"]),
                verified_at=cast(datetime, row["verified_at"]),
            )
            for row in rows
        )

    def resolve_citation_lineage(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        citations: tuple[CitationDraft, ...],
    ) -> tuple[CitationDraft, ...]:
        normalized: list[CitationDraft] = []
        for citation in citations:
            if citation.submission_id is None:
                if (
                    citation.destination_id is not None
                    or citation.verified_at is not None
                    or citation.verification_status == VerificationStatus.PASSED
                ):
                    raise MonitoringRuleViolation(
                        "verified citation metadata requires a verified publication submission"
                    )
                normalized.append(citation)
                continue
            row = self._optional(
                """
                SELECT s.submitted_url AS url, s.verified_at, r.destination_id
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
                WHERE s.project_id = %s AND s.id = %s AND opportunity.campaign_id = %s
                  AND s.status = 'verified' AND s.submitted_url IS NOT NULL
                  AND s.verified_at IS NOT NULL
                FOR SHARE OF s, r
                """,
                (project_id, citation.submission_id, campaign_id),
                "resolve verified citation lineage",
            )
            if row is None:
                raise MonitoringRuleViolation(
                    "citation submission is not verified for this monitoring campaign"
                )
            if citation.url != row["url"]:
                raise MonitoringRuleViolation(
                    "citation URL does not match the verified publication submission"
                )
            destination_id = cast(UUID, row["destination_id"])
            if citation.destination_id not in (None, destination_id):
                raise MonitoringRuleViolation(
                    "citation destination does not match the publication submission"
                )
            normalized.append(
                CitationDraft(
                    url=str(row["url"]),
                    title=citation.title,
                    verification_status=VerificationStatus.PASSED,
                    verified_at=cast(datetime, row["verified_at"]),
                    destination_id=destination_id,
                    submission_id=citation.submission_id,
                )
            )
        return tuple(normalized)
