"""psycopg adapter for governed monitoring and customer-safe projections."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import json
from types import TracebackType
from typing import Any, Literal, TypeAlias, cast
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from geo_core.access.models import AccessPrincipal
from geo_core.monitoring.domain import (
    CitationDraft,
    MeasurementWindow,
    MonitoringConflict,
    MonitoringObservation,
    MonitoringPersistenceUnavailable,
    ObservationDraft,
    ResultStatus,
    VerificationStatus,
)
from geo_core.monitoring.ports import MonitoringRepository, MonitoringUnitOfWork
from geo_core.monitoring.postgres_mappers import (
    citation_from_row as _citation,
)
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    ObservationPlatform,
    ObservationRunParameters,
    ObservationSource,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
    SearchMode,
    SurfaceKind,
)
from geo_core.monitoring.postgres_lineage import MonitoringLineageMixin
from geo_core.monitoring.postgres_customer_projection import (
    MonitoringCustomerProjectionMixin,
)
from geo_core.monitoring.postgres_official_reports import MonitoringOfficialReportsMixin
from geo_core.monitoring.postgres_protocols import MonitoringProtocolsMixin
from geo_core.monitoring.postgres_reporting import MonitoringReportingMixin


Connection: TypeAlias = psycopg.Connection[dict[str, Any]]
ConnectionFactory = Callable[[], Connection]


def _failure(operation: str, error: psycopg.Error) -> RuntimeError:
    if isinstance(error, UniqueViolation):
        return MonitoringConflict(f"The {operation} conflicts with an immutable record.")
    return MonitoringPersistenceUnavailable(f"PostgreSQL could not {operation}.")


def _observation_source_from_row(row: Mapping[str, Any]) -> ObservationSource:
    capture_method = CaptureMethod(str(row.get("capture_method", "unknown")))
    evidence_kind = RawEvidenceKind(str(row.get("raw_evidence_kind", "legacy_unknown")))
    configured_value = cast(str | None, row.get("configured_model"))
    reported_value = cast(str | None, row.get("provider_reported_model"))
    if capture_method == CaptureMethod.UNKNOWN:
        legacy_result = cast(Mapping[str, object], row.get("raw_result") or {})
        return ObservationSource.legacy_unknown(
            raw_evidence=RawEvidence(
                RawEvidenceKind.LEGACY_UNKNOWN,
                answer=cast(str | None, row.get("raw_answer")),
                inline_response=legacy_result or None,
                artifact_uri=cast(str | None, row.get("artifact_uri")),
                artifact_hash=cast(str | None, row.get("artifact_hash")),
            ),
            configured_model=configured_value or "legacy-unreported",
            reported_model=reported_value,
        )
    if evidence_kind == RawEvidenceKind.ANSWER:
        evidence = RawEvidence(evidence_kind, answer=cast(str | None, row.get("raw_answer")))
    elif evidence_kind == RawEvidenceKind.INLINE_RESPONSE:
        evidence = RawEvidence(
            evidence_kind,
            inline_response=cast(Mapping[str, object], row.get("raw_result") or {}),
        )
    elif evidence_kind == RawEvidenceKind.ARTIFACT:
        evidence = RawEvidence(
            evidence_kind,
            artifact_uri=cast(str | None, row.get("artifact_uri")),
            artifact_hash=cast(str | None, row.get("artifact_hash")),
            artifact_verified=True,
        )
    else:
        evidence = RawEvidence(RawEvidenceKind.LEGACY_UNKNOWN)
    return ObservationSource(
        capture_method=capture_method,
        platform=ObservationPlatform(str(row["platform"])),
        surface=ObservationSurface(str(row["surface"])),
        surface_kind=SurfaceKind(str(row["surface_kind"])),
        platform_detail=cast(str | None, row.get("platform_detail")),
        surface_detail=cast(str | None, row.get("surface_detail")),
        configured_model=ModelIdentity(
            ModelIdentityState(str(row["configured_model_state"])), configured_value
        ),
        reported_model=ModelIdentity(
            ModelIdentityState(str(row["provider_reported_model_state"])),
            reported_value,
        ),
        run=ObservationRunParameters(
            engine=cast(str | None, row.get("engine")),
            locale=cast(str | None, row.get("locale")),
            region=cast(str | None, row.get("region")),
            language=cast(str | None, row.get("language")),
            device=(
                ObservationDevice(str(row["observation_device"]))
                if row.get("observation_device")
                else None
            ),
            client_kind=(ClientKind(str(row["client_kind"])) if row.get("client_kind") else None),
            search_enabled=cast(bool | None, row.get("search_enabled")),
            search_mode=(SearchMode(str(row["search_mode"])) if row.get("search_mode") else None),
            prompt_text=cast(str | None, row.get("prompt_text")),
            follow_up_prompts=tuple(row.get("follow_up_prompts") or ()),
            adapter_name=cast(str | None, row.get("adapter_name")),
            adapter_version=cast(str | None, row.get("adapter_version")),
            provider_request_id=cast(str | None, row.get("provider_request_id")),
        ),
        raw_evidence=evidence,
        citations_captured=bool(row.get("citations_captured", False)),
        source_contract_version=str(row.get("source_contract_version") or "legacy-v1"),
        source_job_id=cast(UUID | None, row.get("source_job_id")),
        model_call_log_id=cast(UUID | None, row.get("model_call_log_id")),
        test_only=bool(row.get("test_only", False)),
        publication_eligible=bool(row.get("publication_eligible", False)),
    )


class PsycopgMonitoringRepository(
    MonitoringProtocolsMixin,
    MonitoringCustomerProjectionMixin,
    MonitoringLineageMixin,
    MonitoringReportingMixin,
    MonitoringOfficialReportsMixin,
):
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def import_observation(self, **values: Any) -> MonitoringObservation:
        draft = cast(ObservationDraft, values["draft"])
        existing = self._optional(
            """
            SELECT * FROM monitoring_observations
            WHERE project_id = %s AND campaign_id = %s AND (
                idempotency_key = %s OR
                (protocol_id = %s AND monitoring_query_id = %s
                 AND measurement_window = %s AND source_stratum_hash = %s
                 AND sample_index = %s)
            )
            ORDER BY (idempotency_key = %s) DESC LIMIT 1
            """,
            (
                values["project_id"],
                values["campaign_id"],
                values["idempotency_key"],
                values["protocol_id"],
                draft.monitoring_query_id,
                draft.measurement_window.value,
                draft.source_stratum_hash,
                draft.sample_index,
                values["idempotency_key"],
            ),
            "check the immutable observation slot",
        )
        if existing is not None:
            if existing["payload_hash"] != values["payload_hash"]:
                raise MonitoringConflict(
                    "The idempotency key or sample slot already has different content."
                )
            return self._observation(existing, replayed=True)
        raw_citations = [
            {
                "url": item.url,
                "title": item.title,
                "verification_status": item.verification_status.value,
            }
            for item in draft.citations
        ]
        source = draft.source
        run = source.run
        evidence = source.raw_evidence
        insert_values = {
            **values,
            "monitoring_query_id": draft.monitoring_query_id,
            "measurement_window": draft.measurement_window.value,
            "sample_index": draft.sample_index,
            "result_status": draft.result_status.value,
            "eligibility_requested": draft.requested_eligible,
            "eligible": draft.eligible,
            "ineligible_reasons": list(draft.ineligible_reasons),
            "url_verification_status": draft.url_verification_status.value,
            "recommendation_present": draft.recommendation_present,
            "primary_product_mentioned": draft.primary_product_mentioned,
            "competitor_mentioned": draft.competitor_mentioned,
            "raw_answer": draft.raw_answer,
            "raw_result": Jsonb(dict(draft.raw_result)),
            "raw_citations": Jsonb(raw_citations),
            "artifact_uri": draft.artifact_uri,
            "artifact_hash": draft.artifact_hash,
            "configured_model": draft.configured_model,
            "provider_reported_model": draft.provider_reported_model,
            "ui_surface": draft.ui_surface,
            "ui_metadata": Jsonb(dict(draft.ui_metadata)),
            "confounding_factors": list(draft.confounding_factors),
            "observed_at": draft.observed_at,
            "capture_method": source.capture_method.value,
            "platform": source.platform.value,
            "platform_detail": source.platform_detail,
            "surface": source.surface.value,
            "surface_kind": source.surface_kind.value,
            "surface_detail": source.surface_detail,
            "engine": run.engine,
            "configured_model_state": source.configured_model.state.value,
            "provider_reported_model_state": source.reported_model.state.value,
            "locale": run.locale,
            "region": run.region,
            "language": run.language,
            "observation_device": run.device.value if run.device else None,
            "client_kind": run.client_kind.value if run.client_kind else None,
            "search_enabled": run.search_enabled,
            "search_mode": run.search_mode.value if run.search_mode else None,
            "prompt_text": run.prompt_text,
            "follow_up_prompts": Jsonb(list(run.follow_up_prompts)),
            "adapter_name": run.adapter_name,
            "adapter_version": run.adapter_version,
            "provider_request_id": run.provider_request_id,
            "raw_evidence_kind": evidence.kind.value,
            "citations_captured": source.citations_captured,
            "source_contract_version": source.source_contract_version,
            "source_stratum_hash": draft.source_stratum_hash,
            "query_cluster_key": draft.query_cluster_key,
            "source_job_id": source.source_job_id,
            "model_call_log_id": source.model_call_log_id,
            "test_only": source.test_only,
            "publication_eligible": source.publication_eligible,
        }
        row = self._one(
            """
            INSERT INTO monitoring_observations
              (project_id, protocol_id, campaign_id, monitoring_query_id, measurement_window,
               sample_index, result_status, eligibility_requested, eligible, ineligible_reasons,
               url_verification_status, recommendation_present,
               primary_product_mentioned, competitor_mentioned, raw_answer,
               raw_result, raw_citations, artifact_uri, artifact_hash,
               configured_model, provider_reported_model, ui_surface, ui_metadata,
               confounding_factors, observed_at, capture_method, platform, platform_detail,
               surface, surface_kind, surface_detail, engine, configured_model_state,
               provider_reported_model_state, locale, region, language, observation_device,
               client_kind, search_enabled, search_mode, prompt_text, follow_up_prompts,
               adapter_name, adapter_version, provider_request_id, raw_evidence_kind,
               citations_captured, source_contract_version, source_stratum_hash,
               query_cluster_key, source_job_id, model_call_log_id, test_only,
               publication_eligible, imported_by, idempotency_key, payload_hash)
            VALUES
              (%(project_id)s, %(protocol_id)s, %(campaign_id)s, %(monitoring_query_id)s,
               %(measurement_window)s, %(sample_index)s, %(result_status)s,
               %(eligibility_requested)s, %(eligible)s, %(ineligible_reasons)s,
               %(url_verification_status)s, %(recommendation_present)s,
               %(primary_product_mentioned)s, %(competitor_mentioned)s, %(raw_answer)s,
               %(raw_result)s, %(raw_citations)s, %(artifact_uri)s, %(artifact_hash)s,
               %(configured_model)s, %(provider_reported_model)s, %(ui_surface)s,
               %(ui_metadata)s, %(confounding_factors)s, %(observed_at)s,
               %(capture_method)s, %(platform)s, %(platform_detail)s, %(surface)s,
               %(surface_kind)s, %(surface_detail)s, %(engine)s,
               %(configured_model_state)s, %(provider_reported_model_state)s,
               %(locale)s, %(region)s, %(language)s, %(observation_device)s,
               %(client_kind)s, %(search_enabled)s, %(search_mode)s, %(prompt_text)s,
               %(follow_up_prompts)s, %(adapter_name)s, %(adapter_version)s,
               %(provider_request_id)s, %(raw_evidence_kind)s, %(citations_captured)s,
               %(source_contract_version)s, %(source_stratum_hash)s,
               %(query_cluster_key)s, %(source_job_id)s, %(model_call_log_id)s,
               %(test_only)s, %(publication_eligible)s, %(actor_id)s,
               %(idempotency_key)s, %(payload_hash)s)
            RETURNING *
            """,
            insert_values,
            "import the monitoring observation",
        )
        for index, citation in enumerate(draft.citations):
            self._one(
                """
                INSERT INTO monitoring_observation_citations
                  (project_id, observation_id, citation_index, url, title,
                   destination_id, submission_id, verification_status, verified_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    values["project_id"],
                    row["id"],
                    index,
                    citation.url,
                    citation.title,
                    citation.destination_id,
                    citation.submission_id,
                    citation.verification_status.value,
                    citation.verified_at,
                ),
                "import the observation citation",
            )
        return self._observation(row, replayed=False)

    def list_observations(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID,
        window: MeasurementWindow | None,
    ) -> tuple[MonitoringObservation, ...]:
        condition = "AND measurement_window = %s" if window else ""
        parameters: tuple[object, ...] = (
            (project_id, campaign_id, protocol_id, window.value)
            if window
            else (project_id, campaign_id, protocol_id)
        )
        rows = self._many(
            f"""SELECT * FROM monitoring_observations
                WHERE project_id = %s AND campaign_id = %s AND protocol_id = %s {condition}
                ORDER BY measurement_window, monitoring_query_id,
                         source_stratum_hash, sample_index""",
            parameters,
            "list monitoring observations",
        )
        return tuple(self._observation(row, replayed=False) for row in rows)

    def list_campaign_observations(
        self,
        *,
        project_id: UUID,
        campaign_id: UUID,
        protocol_id: UUID | None,
        window: MeasurementWindow | None,
    ) -> tuple[MonitoringObservation, ...]:
        conditions: list[str] = []
        parameters: list[object] = [project_id, campaign_id]
        if protocol_id is not None:
            conditions.append("AND protocol_id = %s")
            parameters.append(protocol_id)
        if window is not None:
            conditions.append("AND measurement_window = %s")
            parameters.append(window.value)
        rows = self._many(
            f"""SELECT * FROM monitoring_observations
                WHERE project_id = %s AND campaign_id = %s {' '.join(conditions)}
                ORDER BY protocol_id, measurement_window, monitoring_query_id,
                         source_stratum_hash, sample_index""",
            tuple(parameters),
            "list campaign monitoring observations",
        )
        return tuple(self._observation(row, replayed=False) for row in rows)

    def campaign_destination_state(self, *, project_id: UUID, campaign_id: UUID):
        from geo_core.monitoring.domain import CampaignDestinationState

        rows = self._many(
            """
            SELECT o.destination_id, o.status, d.policy_status,
                   EXISTS (
                       SELECT 1
                       FROM publication_requests r
                       JOIN publication_submissions s
                         ON s.publication_request_id = r.id AND s.project_id = r.project_id
                       JOIN placement_package_versions pv
                         ON pv.id = r.package_version_id AND pv.project_id = r.project_id
                       JOIN placement_packages pp
                         ON pp.id = pv.package_id AND pp.project_id = pv.project_id
                       JOIN placement_opportunities source_opportunity
                         ON source_opportunity.id = pp.opportunity_id
                        AND source_opportunity.project_id = pp.project_id
                       WHERE r.project_id = o.project_id
                         AND r.destination_id = o.destination_id
                         AND s.status = 'verified'
                         AND source_opportunity.campaign_id = %s
                   ) AS verified
            FROM placement_opportunities o
            JOIN publication_destinations d
              ON d.id = o.destination_id AND d.project_id = o.project_id
            WHERE o.project_id = %s AND o.campaign_id = %s
              AND o.status <> 'cancelled'
            """,
            (campaign_id, project_id, campaign_id),
            "read campaign destination state",
        )
        selected = frozenset(cast(UUID, row["destination_id"]) for row in rows)
        qualified = frozenset(
            cast(UUID, row["destination_id"])
            for row in rows
            if row["policy_status"] == "approved"
            and row["status"] in {"qualified", "briefing", "in_progress", "completed"}
        )
        verified = frozenset(cast(UUID, row["destination_id"]) for row in rows if row["verified"])
        return CampaignDestinationState(selected, qualified, verified)

    def _observation(self, row: Mapping[str, Any], *, replayed: bool) -> MonitoringObservation:
        citation_rows = self._many(
            """
            SELECT c.*, EXISTS (
                SELECT 1
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
                WHERE s.id = c.submission_id AND s.project_id = c.project_id
                  AND s.status = 'verified' AND s.submitted_url = c.url
                  AND r.destination_id = c.destination_id
                  AND opportunity.campaign_id = %s
            ) AS verified_placement
            FROM monitoring_observation_citations c
            WHERE c.project_id = %s AND c.observation_id = %s
            ORDER BY c.citation_index
            """,
            (row["campaign_id"], row["project_id"], row["id"]),
            "read observation citations",
        )
        citations = tuple(_citation(item) for item in citation_rows)
        draft_citations = tuple(
            CitationDraft(
                url=item.url,
                title=item.title,
                verification_status=item.verification_status,
                verified_at=cast(datetime | None, citation_rows[index]["verified_at"]),
                destination_id=item.destination_id,
                submission_id=item.submission_id,
            )
            for index, item in enumerate(citations)
        )
        source = _observation_source_from_row(row)
        draft = ObservationDraft(
            monitoring_query_id=cast(UUID, row["monitoring_query_id"]),
            measurement_window=MeasurementWindow(str(row["measurement_window"])),
            sample_index=int(row["sample_index"]),
            result_status=ResultStatus(str(row["result_status"])),
            requested_eligible=bool(row.get("eligibility_requested", False)),
            eligible=bool(row["eligible"]),
            ineligible_reasons=tuple(row["ineligible_reasons"]),
            url_verification_status=VerificationStatus(str(row["url_verification_status"])),
            recommendation_present=bool(row["recommendation_present"]),
            primary_product_mentioned=bool(row["primary_product_mentioned"]),
            competitor_mentioned=bool(row["competitor_mentioned"]),
            raw_answer=cast(str | None, row["raw_answer"]),
            raw_result=cast(Mapping[str, object], row["raw_result"]),
            citations=draft_citations,
            artifact_uri=cast(str | None, row["artifact_uri"]),
            artifact_hash=cast(str | None, row["artifact_hash"]),
            configured_model=cast(str | None, row["configured_model"]),
            provider_reported_model=cast(str | None, row["provider_reported_model"]),
            ui_surface=str(row["ui_surface"]),
            ui_metadata=cast(Mapping[str, object], row["ui_metadata"]),
            confounding_factors=tuple(row["confounding_factors"]),
            observed_at=cast(datetime, row["observed_at"]),
            source=source,
            query_cluster_key=cast(str | None, row.get("query_cluster_key")),
        )
        return MonitoringObservation(
            id=cast(UUID, row["id"]),
            project_id=cast(UUID, row["project_id"]),
            protocol_id=cast(UUID, row["protocol_id"]),
            campaign_id=cast(UUID, row["campaign_id"]),
            draft=draft,
            payload_hash=str(row["payload_hash"]),
            citations=citations,
            captured_by=cast(UUID, row["imported_by"]),
            created_at=cast(datetime, row["created_at"]),
            replayed=replayed,
        )

    def _one(self, query: str, parameters: Any, operation: str) -> dict[str, Any]:
        row = self._optional(query, parameters, operation)
        if row is None:
            raise MonitoringPersistenceUnavailable(
                f"PostgreSQL did not return a row while attempting to {operation}."
            )
        return row

    def _optional(self, query: str, parameters: Any, operation: str) -> dict[str, Any] | None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, parameters)
                return cursor.fetchone()
        except psycopg.Error as error:
            raise _failure(operation, error) from error

    def _many(self, query: str, parameters: Any, operation: str) -> list[dict[str, Any]]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(query, parameters)
                return list(cursor.fetchall())
        except psycopg.Error as error:
            raise _failure(operation, error) from error


class PsycopgMonitoringUnitOfWork:
    monitoring: MonitoringRepository

    def __init__(self, connection_factory: ConnectionFactory, principal: AccessPrincipal) -> None:
        self._connection_factory = connection_factory
        self._principal = principal
        self._connection: Connection | None = None
        self._committed = False

    def __enter__(self) -> "PsycopgMonitoringUnitOfWork":
        try:
            self._connection = self._connection_factory()
            self.connection.execute("SET LOCAL statement_timeout = '10s'")
            self.monitoring = PsycopgMonitoringRepository(self.connection)
            values = {
                "geo.actor_id": str(self._principal.identity_id),
                "geo.identity_id": str(self._principal.identity_id),
                "geo.tenant_id": str(self._principal.tenant_id),
                "geo.project_id": str(self._principal.project_ids[0])
                if self._principal.project_ids
                else "",
                "geo.project_ids": json.dumps([str(item) for item in self._principal.project_ids]),
            }
            with self.connection.cursor() as cursor:
                for name, value in values.items():
                    cursor.execute(
                        sql.SQL("SELECT set_config({}, %s, true)").format(sql.Literal(name)),
                        (value,),
                    )
        except psycopg.Error as error:
            self._close()
            raise _failure("open a monitoring transaction", error) from error
        return self

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("The Monitoring Unit of Work has not been entered.")
        return self._connection

    def commit(self) -> None:
        self.connection.commit()
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc, traceback
        try:
            if self._connection is not None and not self._committed:
                self._connection.rollback()
        finally:
            self._close()
        return False

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


class PsycopgMonitoringUnitOfWorkFactory:
    def __init__(self, database_url: str, *, connect_timeout: int = 5) -> None:
        if not database_url.strip():
            raise ValueError("database_url is required")
        self._database_url = database_url.strip()
        self._connect_timeout = connect_timeout

    def __call__(self, principal: AccessPrincipal) -> MonitoringUnitOfWork:
        return PsycopgMonitoringUnitOfWork(self._connect, principal)

    def _connect(self) -> Connection:
        return psycopg.connect(
            self._database_url, connect_timeout=self._connect_timeout, row_factory=dict_row
        )
