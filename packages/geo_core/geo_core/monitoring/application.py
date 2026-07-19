"""Application service for internal monitoring commands and customer-safe reads."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.application_reporting import (
    MonitoringReportingApplicationMixin,
    require_role as _require_role,
)
from geo_core.monitoring.domain import (
    APPROVER_ROLES,
    CONTRIBUTOR_ROLES,
    READER_ROLES,
    METRIC_METHOD_VERSION,
    STATISTICS_CONTRACT_VERSION,
    Device,
    MeasurementWindow,
    MetricSnapshot,
    MonitoringNotFound,
    MonitoringObservation,
    MonitoringProtocol,
    MonitoringRuleViolation,
    ObservationDraft,
    Platform,
    ProtocolQuery,
    ProtocolStatus,
    QuerySuggestion,
    VerifiedCitationTarget,
    calculate_metric_snapshot,
    protocol_hash,
    select_metric_observations,
    source_strata_inventory_hash,
)
from geo_core.monitoring.artifact_evidence import (
    RawArtifactVerifier,
)
from geo_core.monitoring.ports import MonitoringUnitOfWorkFactory
from geo_core.monitoring.source_contract import (
    PUBLIC_OBSERVATION_CAPTURE_METHODS,
    RawEvidenceKind,
    SourceStratumKey,
)


class MonitoringApplication(MonitoringReportingApplicationMixin):
    """All authority comes from AccessPrincipal; request DTOs carry no actor or tenant."""

    def __init__(
        self,
        unit_of_work_factory: MonitoringUnitOfWorkFactory,
        artifact_verifier: RawArtifactVerifier | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_verifier = artifact_verifier

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
        minimum_valid_repeats: int,
        window_days: int,
        source_strata: tuple[SourceStratumKey, ...],
    ) -> MonitoringProtocol:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        if not name.strip() or not locale.strip():
            raise MonitoringRuleViolation("protocol name and locale are required")
        if not source_strata:
            raise MonitoringRuleViolation("protocol requires at least one source stratum")
        frozen_minimum = max(3, (4 * sample_size + 4) // 5)
        if sample_size < 3 or not (frozen_minimum <= minimum_valid_repeats <= sample_size):
            raise MonitoringRuleViolation(
                "minimum valid repeats must be at least three and 80 percent of samples"
            )
        if any(
            item.capture_method not in PUBLIC_OBSERVATION_CAPTURE_METHODS for item in source_strata
        ):
            raise MonitoringRuleViolation(
                "monitoring protocols only accept manual, provider or proxy strata"
            )
        strata_hash = source_strata_inventory_hash(source_strata)
        with self._unit_of_work_factory(principal) as unit_of_work:
            if not unit_of_work.monitoring.campaign_matches_market(
                project_id=project_id,
                campaign_id=campaign_id,
                market_profile_id=market_profile_id,
            ):
                raise MonitoringNotFound("The campaign does not exist in this project and market.")
            protocol = unit_of_work.monitoring.create_protocol(
                project_id=project_id,
                campaign_id=campaign_id,
                market_profile_id=market_profile_id,
                name=name.strip(),
                platform=platform,
                locale=locale.strip(),
                device=device,
                sample_size=sample_size,
                minimum_valid_repeats=minimum_valid_repeats,
                window_days=window_days,
                statistics_method_version=METRIC_METHOD_VERSION,
                statistics_contract_version=STATISTICS_CONTRACT_VERSION,
                source_strata=source_strata,
                source_strata_hash=strata_hash,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return protocol

    def list_protocols(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[MonitoringProtocol, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_protocols(
                project_id=project_id, campaign_id=campaign_id
            )

    def bind_question_set(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        question_set_id: UUID,
        confirmed_content_hash: str,
    ) -> MonitoringProtocol:
        _require_role(principal, project_id, APPROVER_ROLES)
        if len(confirmed_content_hash) != 64:
            raise MonitoringRuleViolation("QuestionSet content hash must be SHA-256")
        with self._unit_of_work_factory(principal) as unit_of_work:
            result = unit_of_work.monitoring.bind_question_set(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                question_set_id=question_set_id,
                confirmed_content_hash=confirmed_content_hash,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return result

    def suggest_query(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        query_text: str,
        query_kind: str,
        rationale: str,
        query_cluster_key: str,
    ) -> QuerySuggestion:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        if query_kind not in {"recommendation", "comparison", "research", "support"}:
            raise MonitoringRuleViolation("query kind is unsupported")
        if not query_text.strip() or not rationale.strip() or not query_cluster_key.strip():
            raise MonitoringRuleViolation(
                "query text, rationale and query cluster key are required"
            )
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            if protocol.status != ProtocolStatus.DRAFT:
                raise MonitoringRuleViolation("query suggestions require a draft protocol")
            suggestion = unit_of_work.monitoring.create_suggestion(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                query_text=query_text.strip(),
                query_kind=query_kind,
                rationale=rationale.strip(),
                query_cluster_key=query_cluster_key.strip(),
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return suggestion

    def list_suggestions(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
    ) -> tuple[QuerySuggestion, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            return unit_of_work.monitoring.list_suggestions(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
            )

    def list_protocol_queries(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
    ) -> tuple[ProtocolQuery, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            return unit_of_work.monitoring.list_protocol_queries(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
            )

    def list_citation_targets(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
    ) -> tuple[VerifiedCitationTarget, ...]:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            return unit_of_work.monitoring.list_verified_citation_targets(
                project_id=project_id, campaign_id=protocol.campaign_id
            )

    def approve_suggestion(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        suggestion_id: UUID,
    ) -> ProtocolQuery:
        _require_role(principal, project_id, APPROVER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
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
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
    ) -> MonitoringProtocol:
        _require_role(principal, project_id, APPROVER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            if protocol.status != ProtocolStatus.DRAFT:
                raise MonitoringRuleViolation("only draft protocols can be approved")
            approved = unit_of_work.monitoring.approve_protocol(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return approved

    def freeze_protocol(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
    ) -> MonitoringProtocol:
        _require_role(principal, project_id, APPROVER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            if protocol.status != ProtocolStatus.APPROVED:
                raise MonitoringRuleViolation("only approved protocols can be frozen")
            queries = unit_of_work.monitoring.list_protocol_queries(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
            )
            if not queries:
                raise MonitoringRuleViolation("a frozen protocol requires approved queries")
            if not protocol.source_strata or protocol.source_strata_hash is None:
                raise MonitoringRuleViolation(
                    "a frozen protocol requires a source strata inventory"
                )
            if any(not item.query_cluster_key for item in queries):
                raise MonitoringRuleViolation("a frozen protocol requires query cluster snapshots")
            frozen = unit_of_work.monitoring.freeze_protocol(
                project_id=project_id,
                campaign_id=campaign_id,
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
        campaign_id: UUID,
        protocol_id: UUID,
        draft: ObservationDraft,
        idempotency_key: str,
    ) -> MonitoringObservation:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise MonitoringRuleViolation("a bounded idempotency key is required")
        if draft.source.capture_method not in PUBLIC_OBSERVATION_CAPTURE_METHODS:
            raise MonitoringRuleViolation(
                "the public observation command only accepts manual, provider or proxy sources"
            )
        if draft.source.raw_evidence.kind == RawEvidenceKind.ARTIFACT:
            verified_evidence = self.verify_raw_evidence(
                project_id=project_id,
                capture_method=draft.source.capture_method,
                evidence=draft.source.raw_evidence,
            )
            draft = replace(
                draft,
                source=replace(draft.source, raw_evidence=verified_evidence),
            )
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            if protocol.status != ProtocolStatus.FROZEN:
                raise MonitoringRuleViolation("observations require a frozen protocol")
            if draft.sample_index > protocol.sample_size:
                raise MonitoringRuleViolation("sample index exceeds the frozen denominator")
            query = unit_of_work.monitoring.get_protocol_query(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                query_id=draft.monitoring_query_id,
            )
            if query is None:
                raise MonitoringNotFound(
                    "The monitoring query does not belong to this protocol and campaign."
                )
            if draft.eligible and draft.source_stratum_hash not in {
                item.canonical_hash() for item in protocol.source_strata
            }:
                raise MonitoringRuleViolation(
                    "eligible observation source was not frozen into the protocol"
                )
            normalized_citations = unit_of_work.monitoring.resolve_citation_lineage(
                project_id=project_id,
                campaign_id=protocol.campaign_id,
                citations=draft.citations,
            )
            draft = replace(
                draft,
                citations=normalized_citations,
                query_cluster_key=query.query_cluster_key,
            )
            observation = unit_of_work.monitoring.import_observation(
                project_id=project_id,
                protocol_id=protocol_id,
                campaign_id=campaign_id,
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
        campaign_id: UUID,
        protocol_id: UUID,
        window: MeasurementWindow | None = None,
    ) -> tuple[MonitoringObservation, ...]:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            return unit_of_work.monitoring.list_observations(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                window=window,
            )

    def list_campaign_observations(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID | None = None,
        window: MeasurementWindow | None = None,
    ) -> tuple[MonitoringObservation, ...]:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            if protocol_id is not None:
                _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            return unit_of_work.monitoring.list_campaign_observations(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                window=window,
            )

    def compute_metrics(
        self,
        principal: AccessPrincipal,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        window: MeasurementWindow,
        source_stratum_hash: str,
        query_cluster_key: str,
    ) -> MetricSnapshot:
        _require_role(principal, project_id, CONTRIBUTOR_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            protocol = _protocol(unit_of_work.monitoring, project_id, campaign_id, protocol_id)
            source_stratum = next(
                (
                    item
                    for item in protocol.source_strata
                    if item.canonical_hash() == source_stratum_hash
                ),
                None,
            )
            if source_stratum is None:
                raise MonitoringNotFound("The source stratum is not frozen into this protocol.")
            queries = unit_of_work.monitoring.list_protocol_queries(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
            )
            observations = unit_of_work.monitoring.list_observations(
                project_id=project_id,
                campaign_id=campaign_id,
                protocol_id=protocol_id,
                window=window,
            )
            selected_observations = select_metric_observations(
                protocol=protocol,
                queries=queries,
                query_cluster_key=query_cluster_key,
                window=window,
                source_stratum=source_stratum,
                observations=observations,
            )
            snapshot = calculate_metric_snapshot(
                snapshot_id=uuid4(),
                protocol=protocol,
                queries=queries,
                query_cluster_key=query_cluster_key,
                window=window,
                source_stratum=source_stratum,
                observations=selected_observations,
                destination_state=unit_of_work.monitoring.campaign_destination_state(
                    project_id=project_id, campaign_id=protocol.campaign_id
                ),
                computed_at=datetime.now(UTC),
            )
            persisted = unit_of_work.monitoring.create_metric_snapshot(
                snapshot=snapshot,
                observations=selected_observations,
                actor_id=principal.identity_id,
            )
            unit_of_work.commit()
            return persisted

    def list_metrics(
        self, principal: AccessPrincipal, *, project_id: UUID, campaign_id: UUID
    ) -> tuple[MetricSnapshot, ...]:
        _require_role(principal, project_id, READER_ROLES)
        with self._unit_of_work_factory(principal) as unit_of_work:
            return unit_of_work.monitoring.list_metric_snapshots(
                project_id=project_id, campaign_id=campaign_id, latest_only=True
            )


def _protocol(
    repository: object, project_id: UUID, campaign_id: UUID, protocol_id: UUID
) -> MonitoringProtocol:
    get_protocol = getattr(repository, "get_protocol")
    protocol = get_protocol(project_id=project_id, campaign_id=campaign_id, protocol_id=protocol_id)
    if protocol is None:
        raise MonitoringNotFound("The monitoring protocol does not exist in this project.")
    return protocol
