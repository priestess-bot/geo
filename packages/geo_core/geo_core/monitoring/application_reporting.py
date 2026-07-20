"""Customer reads, reporting and official-report operations for monitoring."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.artifact_evidence import (
    RawArtifactVerificationError,
    RawArtifactVerifier,
)
from geo_core.monitoring.customer_projection import ApprovedReportSnapshot, CustomerCampaign
from geo_core.monitoring.domain import (
    APPROVER_ROLES,
    CONTRIBUTOR_ROLES,
    READER_ROLES,
    STATISTICS_CONTRACT_VERSION,
    MonitoringForbidden,
    MonitoringNotFound,
    MonitoringReport,
    MonitoringRuleViolation,
    VerifiedUrl,
    render_report,
)
from geo_core.monitoring.official_reports import (
    OfficialReportImport,
    OfficialReportImportDraft,
    OfficialReportRowDraft,
    OfficialReportRuleViolation,
    official_report_payload_hash,
)
from geo_core.monitoring.ports import MonitoringUnitOfWorkFactory
from geo_core.monitoring.source_contract import CaptureMethod, RawEvidence, RawEvidenceKind


class MonitoringReportingApplicationMixin:
    _unit_of_work_factory: MonitoringUnitOfWorkFactory
    _artifact_verifier: RawArtifactVerifier | None

    def list_customer_campaigns(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[CustomerCampaign, ...]:
        require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_customer_campaigns(project_id=project_id)

    def get_customer_campaign(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ) -> CustomerCampaign:
        require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            campaign = unit_of_work.monitoring.get_customer_campaign(
                project_id=project_id, campaign_id=campaign_id
            )
            if campaign is None:
                raise MonitoringNotFound(
                    "The Campaign does not exist in the authenticated project scope."
                )
            return campaign

    def list_customer_approved_report_snapshots(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[ApprovedReportSnapshot, ...]:
        require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            campaign = unit_of_work.monitoring.get_customer_campaign(
                project_id=project_id, campaign_id=campaign_id
            )
            if campaign is None:
                raise MonitoringNotFound(
                    "The Campaign does not exist in the authenticated project scope."
                )
            return unit_of_work.monitoring.list_customer_approved_report_snapshots(
                project_id=project_id, campaign_id=campaign_id
            )

    def list_customer_approved_verified_urls(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[VerifiedUrl, ...]:
        require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            campaign = unit_of_work.monitoring.get_customer_campaign(
                project_id=project_id, campaign_id=campaign_id
            )
            if campaign is None:
                raise MonitoringNotFound(
                    "The Campaign does not exist in the authenticated project scope."
                )
            return unit_of_work.monitoring.list_customer_approved_verified_urls(
                project_id=project_id, campaign_id=campaign_id
            )

    def verify_raw_evidence(
        self,
        *,
        project_id: UUID,
        capture_method: CaptureMethod,
        evidence: RawEvidence,
    ) -> RawEvidence:
        if evidence.kind != RawEvidenceKind.ARTIFACT:
            return evidence
        if self._artifact_verifier is None:
            raise MonitoringRuleViolation("raw artifact verification is unavailable")
        try:
            return self._artifact_verifier.verify(
                project_id=project_id,
                capture_method=capture_method,
                evidence=evidence,
            )
        except RawArtifactVerificationError as error:
            raise MonitoringRuleViolation(str(error)) from error

    def generate_report(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        metric_snapshot_id: UUID,
        title: str,
    ) -> MonitoringReport:
        require_role(principal, project_id, CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            snapshot = unit_of_work.monitoring.get_metric_snapshot(
                project_id=project_id,
                campaign_id=campaign_id,
                snapshot_id=metric_snapshot_id,
            )
            if snapshot is None:
                raise MonitoringNotFound("The metric snapshot does not exist in this project.")
            if snapshot.source_stratum is None or snapshot.source_stratum_hash is None:
                raise MonitoringRuleViolation(
                    "legacy metrics with unknown sources cannot generate a new report"
                )
            if (
                snapshot.statistics_contract_version != STATISTICS_CONTRACT_VERSION
                or snapshot.result_hash is None
                or snapshot.observation_membership_version is None
                or snapshot.observation_membership_hash is None
                or snapshot.observation_membership_count is None
            ):
                raise MonitoringRuleViolation(
                    "unreproducible statistics cannot generate a new report"
                )
            body, report_hash = render_report(snapshot, title)
            report = unit_of_work.monitoring.create_report(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=snapshot.protocol_id,
                snapshot=snapshot,
                title=title.strip(),
                body=body,
                report_hash=report_hash,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return report

    def approve_report(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        report_id: UUID,
    ) -> MonitoringReport:
        require_role(principal, project_id, APPROVER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            report = unit_of_work.monitoring.approve_report(
                project_id=project_id,
                campaign_id=campaign_id,
                report_id=report_id,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return report

    def list_reports(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        approved_only: bool,
    ) -> tuple[MonitoringReport, ...]:
        require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_reports(
                project_id=project_id,
                campaign_id=campaign_id,
                approved_only=approved_only,
            )

    def list_verified_urls(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[VerifiedUrl, ...]:
        require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_verified_urls(
                project_id=project_id, campaign_id=campaign_id
            )

    def import_official_report(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        draft: OfficialReportImportDraft,
        rows: tuple[OfficialReportRowDraft, ...],
        idempotency_key: str,
    ) -> OfficialReportImport:
        require_role(principal, project_id, CONTRIBUTOR_ROLES)
        if draft.campaign_id != campaign_id:
            raise MonitoringRuleViolation("campaign context mismatch")
        if not rows:
            raise MonitoringRuleViolation("official report requires parsed rows")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise MonitoringRuleViolation("a bounded idempotency key is required")
        draft = replace(
            draft,
            artifact=self.verify_raw_evidence(
                project_id=project_id,
                capture_method=CaptureMethod.OFFICIAL_REPORT_IMPORT,
                evidence=draft.artifact,
            ),
        )
        try:
            payload_hash = official_report_payload_hash(draft, rows)
        except OfficialReportRuleViolation as error:
            raise MonitoringRuleViolation(str(error)) from error
        with self._unit_of_work_factory(principal) as unit_of_work:
            if not unit_of_work.monitoring.list_protocols(
                project_id=project_id, campaign_id=campaign_id
            ):
                raise MonitoringNotFound("The official report campaign has no monitoring context.")
            report = unit_of_work.monitoring.import_official_report(
                project_id=project_id,
                draft=draft,
                rows=rows,
                actor_id=principal.identity_id,
                idempotency_key=idempotency_key.strip(),
                payload_hash=payload_hash,
            )
            unit_of_work.commit()
            return report

    def list_official_reports(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
    ) -> tuple[OfficialReportImport, ...]:
        require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_official_reports(
                project_id=project_id, campaign_id=campaign_id
            )


def require_role(principal: AccessPrincipal, project_id: UUID, allowed: frozenset[str]) -> None:
    for membership in principal.memberships:
        if membership.project_id == project_id and membership.tenant_id == principal.tenant_id:
            if membership.role not in allowed:
                raise MonitoringForbidden("The project role cannot perform this operation.")
            return
    raise MonitoringNotFound("The requested project does not exist in the authenticated scope.")
