"""Stable internal observation CSV projection shared with the project exporter."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import io
import json
from typing import Iterable

from geo_core.csv_security import neutralize_spreadsheet_formula
from geo_core.monitoring.domain import MonitoringObservation
from geo_core.monitoring.source_contract import CaptureMethod


OBSERVATION_EXPORT_SCHEMA = "geo-observation-export-row-v1"


@dataclass(frozen=True)
class ObservationExportRow:
    schema_version: str
    observation_id: str
    project_id: str
    campaign_id: str
    protocol_id: str
    monitoring_query_id: str
    query_cluster_key: str
    measurement_window: str
    sample_index: int
    result_status: str
    requested_eligible: bool
    eligible: bool
    ineligible_reasons_json: str
    capture_method: str
    source_badge: str
    platform: str
    platform_detail: str
    surface: str
    surface_kind: str
    surface_detail: str
    engine: str
    configured_model_state: str
    configured_model: str
    reported_model_state: str
    reported_model: str
    locale: str
    region: str
    language: str
    device: str
    client_kind: str
    search_enabled: str
    search_mode: str
    adapter_name: str
    adapter_version: str
    provider_request_id: str
    raw_evidence_kind: str
    raw_answer: str
    artifact_uri: str
    artifact_hash: str
    citation_count: int
    citations_json: str
    recommendation_present: bool
    primary_product_mentioned: bool
    competitor_mentioned: bool
    observed_at: str
    captured_by: str
    source_contract_version: str
    source_stratum_hash: str
    payload_hash: str
    created_at: str


SOURCE_LABELS = {
    CaptureMethod.OFFICIAL_REPORT_IMPORT: "Official report import",
    CaptureMethod.MANUAL_UI: "Manual consumer UI",
    CaptureMethod.PROVIDER_API: "Provider API",
    CaptureMethod.PROXY_GROUNDED_API: "Proxy grounded API",
    CaptureMethod.SYNTHETIC: "Synthetic benchmark - test only",
    CaptureMethod.UNKNOWN: "Legacy unknown - ineligible",
}


def observation_export_row(item: MonitoringObservation) -> ObservationExportRow:
    draft = item.draft
    source = draft.source
    run = source.run
    evidence = source.raw_evidence
    citations = [
        {
            "citation_index": value.citation_index,
            "url": value.url,
            "title": value.title,
            "verification_status": value.verification_status.value,
            "destination_id": str(value.destination_id) if value.destination_id else None,
            "submission_id": str(value.submission_id) if value.submission_id else None,
            "verified_placement": value.verified_placement,
        }
        for value in sorted(item.citations, key=lambda citation: citation.citation_index)
    ]
    return ObservationExportRow(
        schema_version=OBSERVATION_EXPORT_SCHEMA,
        observation_id=str(item.id),
        project_id=str(item.project_id),
        campaign_id=str(item.campaign_id),
        protocol_id=str(item.protocol_id),
        monitoring_query_id=str(draft.monitoring_query_id),
        query_cluster_key=draft.query_cluster_key or "",
        measurement_window=draft.measurement_window.value,
        sample_index=draft.sample_index,
        result_status=draft.result_status.value,
        requested_eligible=draft.requested_eligible,
        eligible=draft.eligible,
        ineligible_reasons_json=_json(list(draft.ineligible_reasons)),
        capture_method=source.capture_method.value,
        source_badge=SOURCE_LABELS[source.capture_method],
        platform=source.platform.value,
        platform_detail=source.platform_detail or "",
        surface=source.surface.value,
        surface_kind=source.surface_kind.value,
        surface_detail=source.surface_detail or "",
        engine=run.engine or "",
        configured_model_state=source.configured_model.state.value,
        configured_model=source.configured_model.value or "",
        reported_model_state=source.reported_model.state.value,
        reported_model=source.reported_model.value or "",
        locale=run.locale or "",
        region=run.region or "",
        language=run.language or "",
        device=run.device.value if run.device else "",
        client_kind=run.client_kind.value if run.client_kind else "",
        search_enabled=(
            "" if run.search_enabled is None else str(run.search_enabled).lower()
        ),
        search_mode=run.search_mode.value if run.search_mode else "",
        adapter_name=run.adapter_name or "",
        adapter_version=run.adapter_version or "",
        provider_request_id=run.provider_request_id or "",
        raw_evidence_kind=evidence.kind.value,
        raw_answer=evidence.answer or "",
        artifact_uri=evidence.artifact_uri or "",
        artifact_hash=evidence.artifact_hash or "",
        citation_count=len(citations),
        citations_json=_json(citations),
        recommendation_present=draft.recommendation_present,
        primary_product_mentioned=draft.primary_product_mentioned,
        competitor_mentioned=draft.competitor_mentioned,
        observed_at=_time(draft.observed_at),
        captured_by=str(item.captured_by),
        source_contract_version=source.source_contract_version,
        source_stratum_hash=(
            ""
            if source.capture_method == CaptureMethod.UNKNOWN
            else draft.source_stratum_hash
        ),
        payload_hash=item.payload_hash,
        created_at=_time(item.created_at),
    )


def render_observation_csv(observations: Iterable[MonitoringObservation]) -> bytes:
    rows = [observation_export_row(item) for item in observations]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(ObservationExportRow.__dataclass_fields__),
        lineterminator="\r\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(
        {
            key: neutralize_spreadsheet_formula(value) if isinstance(value, str) else value
            for key, value in asdict(row).items()
        }
        for row in rows
    )
    return buffer.getvalue().encode("utf-8")


def _json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
