"""Application service for internal monitoring commands and customer-safe reads."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.domain import (
    APPROVER_ROLES,
    CONTRIBUTOR_ROLES,
    READER_ROLES,
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MonitoringForbidden,
    MonitoringNotFound,
    MonitoringObservation,
    MonitoringProtocol,
    MonitoringReport,
    MonitoringRuleViolation,
    ObservationDraft,
    Platform,
    ProtocolQuery,
    ProtocolStatus,
    QuerySuggestion,
    VerifiedUrl,
    calculate_metric_snapshot,
    protocol_hash,
    render_report,
)
from geo_core.monitoring.ports import MonitoringUnitOfWorkFactory


class MonitoringApplication:
    """All authority comes from AccessPrincipal; request DTOs carry no actor or tenant."""

    def __init__(self, unit_of_work_factory: MonitoringUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def create_protocol(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        market_profile_id: UUID,
        name: str,
        platform: Platform,
        locale: str,
        device: Device,
        sample_size: int,
        window_days: int,
    ) -> MonitoringProtocol:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        if not name.strip() or not locale.strip():
            raise MonitoringRuleViolation("protocol name and locale are required")
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = unit_of_work.monitoring.create_protocol(
                project_id=project_id,
                campaign_id=campaign_id,
                market_profile_id=market_profile_id,
                name=name.strip(),
                platform=platform,
                locale=locale.strip(),
                device=device,
                sample_size=sample_size,
                window_days=window_days,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return protocol

    def list_protocols(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[MonitoringProtocol, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_protocols(project_id=project_id)

    def suggest_query(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        protocol_id: UUID,
        query_text: str,
        query_kind: str,
        rationale: str,
    ) -> QuerySuggestion:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        if query_kind not in {"recommendation", "comparison", "research", "support"}:
            raise MonitoringRuleViolation("query kind is unsupported")
        if not query_text.strip() or not rationale.strip():
            raise MonitoringRuleViolation("query text and rationale are required")
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, protocol_id)
            if protocol.status != ProtocolStatus.DRAFT:
                raise MonitoringRuleViolation("query suggestions require a draft protocol")
            suggestion = unit_of_work.monitoring.create_suggestion(
                project_id=project_id,
                protocol_id=protocol_id,
                query_text=query_text.strip(),
                query_kind=query_kind,
                rationale=rationale.strip(),
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return suggestion

    def list_suggestions(
        self, principal: AccessPrincipal, *, project_id: UUID, protocol_id: UUID
    ) -> tuple[QuerySuggestion, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            _protocol(unit_of_work.monitoring, project_id, protocol_id)
            return unit_of_work.monitoring.list_suggestions(
                project_id=project_id, protocol_id=protocol_id
            )

    def approve_suggestion(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        protocol_id: UUID,
        suggestion_id: UUID,
    ) -> ProtocolQuery:
        _require_role(principal, project_id, APPROVER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, protocol_id)
            if protocol.status != ProtocolStatus.DRAFT:
                raise MonitoringRuleViolation("only draft protocol suggestions can be approved")
            _, query = unit_of_work.monitoring.approve_suggestion(
                project_id=project_id,
                protocol=protocol,
                suggestion_id=suggestion_id,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return query

    def approve_protocol(
        self, principal: AccessPrincipal, *, project_id: UUID, protocol_id: UUID
    ) -> MonitoringProtocol:
        _require_role(principal, project_id, APPROVER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, protocol_id)
            if protocol.status != ProtocolStatus.DRAFT:
                raise MonitoringRuleViolation("only draft protocols can be approved")
            approved = unit_of_work.monitoring.approve_protocol(
                project_id=project_id,
                protocol_id=protocol_id,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return approved

    def freeze_protocol(
        self, principal: AccessPrincipal, *, project_id: UUID, protocol_id: UUID
    ) -> MonitoringProtocol:
        _require_role(principal, project_id, APPROVER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, protocol_id)
            if protocol.status != ProtocolStatus.APPROVED:
                raise MonitoringRuleViolation("only approved protocols can be frozen")
            queries = unit_of_work.monitoring.list_protocol_queries(
                project_id=project_id, protocol_id=protocol_id
            )
            if not queries:
                raise MonitoringRuleViolation("a frozen protocol requires approved queries")
            frozen = unit_of_work.monitoring.freeze_protocol(
                project_id=project_id,
                protocol_id=protocol_id,
                actor_id=principal.identity_id,
                protocol_hash=protocol_hash(protocol, queries),
            )
            unit_of_work.commit()
            return frozen

    def import_observation(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        protocol_id: UUID,
        draft: ObservationDraft,
        idempotency_key: str,
    ) -> MonitoringObservation:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise MonitoringRuleViolation("a bounded idempotency key is required")
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, protocol_id)
            if protocol.status != ProtocolStatus.FROZEN:
                raise MonitoringRuleViolation("observations require a frozen protocol")
            if draft.sample_index > protocol.sample_size:
                raise MonitoringRuleViolation("sample index exceeds the frozen denominator")
            observation = unit_of_work.monitoring.import_observation(
                project_id=project_id,
                protocol_id=protocol_id,
                campaign_id=protocol.campaign_id,
                draft=draft,
                actor_id=principal.identity_id,
                idempotency_key=idempotency_key.strip(),
                payload_hash=draft.payload_hash(),
            )
            unit_of_work.commit()
            return observation

    def list_observations(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        protocol_id: UUID,
        window: MeasurementWindow | None = None,
    ) -> tuple[MonitoringObservation, ...]:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_observations(
                project_id=project_id, protocol_id=protocol_id, window=window
            )

    def compute_metrics(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        protocol_id: UUID,
        window: MeasurementWindow,
    ) -> MetricSnapshot:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, protocol_id)
            queries = unit_of_work.monitoring.list_protocol_queries(
                project_id=project_id, protocol_id=protocol_id
            )
            observations = unit_of_work.monitoring.list_observations(
                project_id=project_id, protocol_id=protocol_id, window=window
            )
            snapshot = calculate_metric_snapshot(
                snapshot_id=uuid4(),
                protocol=protocol,
                query_count=len(queries),
                window=window,
                observations=observations,
                destination_state=unit_of_work.monitoring.campaign_destination_state(
                    project_id=project_id, campaign_id=protocol.campaign_id
                ),
                computed_at=datetime.now(UTC),
            )
            persisted = unit_of_work.monitoring.create_metric_snapshot(
                snapshot=snapshot, actor_id=principal.identity_id
            )
            unit_of_work.commit()
            return persisted

    def list_metrics(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[MetricSnapshot, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_metric_snapshots(
                project_id=project_id, latest_only=True
            )

    def generate_report(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        metric_snapshot_id: UUID,
        title: str,
    ) -> MonitoringReport:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            snapshot = unit_of_work.monitoring.get_metric_snapshot(
                project_id=project_id, snapshot_id=metric_snapshot_id
            )
            if snapshot is None:
                raise MonitoringNotFound("The metric snapshot does not exist in this project.")
            body, report_hash = render_report(snapshot, title)
            report = unit_of_work.monitoring.create_report(
                project_id=project_id,
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
        self, principal: AccessPrincipal, *, project_id: UUID, report_id: UUID
    ) -> MonitoringReport:
        _require_role(principal, project_id, APPROVER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            report = unit_of_work.monitoring.approve_report(
                project_id=project_id,
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
        approved_only: bool,
    ) -> tuple[MonitoringReport, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_reports(
                project_id=project_id, approved_only=approved_only
            )

    def list_verified_urls(
        self, principal: AccessPrincipal, *, project_id: UUID
    ) -> tuple[VerifiedUrl, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_verified_urls(project_id=project_id)


def _require_role(
    principal: AccessPrincipal, project_id: UUID, allowed: frozenset[str]
) -> None:
    for membership in principal.memberships:
        if membership.project_id == project_id and membership.tenant_id == principal.tenant_id:
            if membership.role not in allowed:
                raise MonitoringForbidden("The project role cannot perform this operation.")
            return
    raise MonitoringNotFound("The requested project does not exist in the authenticated scope.")


def _protocol(repository: object, project_id: UUID, protocol_id: UUID) -> MonitoringProtocol:
    get_protocol = getattr(repository, "get_protocol")
    protocol = get_protocol(project_id=project_id, protocol_id=protocol_id)
    if protocol is None:
        raise MonitoringNotFound("The monitoring protocol does not exist in this project.")
    return protocol
