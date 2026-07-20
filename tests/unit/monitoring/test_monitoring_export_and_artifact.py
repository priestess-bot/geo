from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from geo_core.monitoring.artifact_evidence import (
    RawArtifactVerificationError,
    S3RawArtifactVerifier,
)
from geo_core.monitoring.domain import (
    CitationDraft,
    MeasurementWindow,
    MonitoringObservation,
    ObservationCitation,
    ObservationDraft,
    ResultStatus,
    VerificationStatus,
)
from geo_core.monitoring.exporter import (
    OBSERVATION_EXPORT_SCHEMA,
    ObservationExportRow,
    render_observation_csv,
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
from geo_core.object_store import S3CompatibleObjectStore


NOW = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)


class RecordingRequester:
    def __init__(self, responses: list[tuple[int, Mapping[str, str], bytes]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, Mapping[str, str], bytes]] = []

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append((method, url, headers, body))
        return self.responses.pop(0)


def test_f009_export_01_csv_has_stable_columns_labels_and_rfc4180_escaping() -> None:
    observation = _observation()

    content = render_observation_csv((observation,))
    decoded = content.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(decoded, newline="")))

    assert decoded.endswith("\r\n")
    assert list(rows[0]) == list(ObservationExportRow.__dataclass_fields__)
    assert rows[0]["schema_version"] == OBSERVATION_EXPORT_SCHEMA
    assert rows[0]["source_badge"] == "Manual consumer UI"
    assert rows[0]["raw_answer"] == 'Answer, with "quotes"\nand line'
    assert rows[0]["observed_at"] == "2026-07-19T09:30:00Z"
    assert '""quotes""' in decoded
    assert rows[0]["citations_json"].index("First") < rows[0]["citations_json"].index(
        "Second"
    )


@pytest.mark.parametrize("prefix", ("=", "+", "-", "@", "  ="))
def test_observation_csv_neutralizes_spreadsheet_formulas(prefix: str) -> None:
    observation = _observation(source=_source(f"{prefix}DANGEROUS()"))

    [row] = csv.DictReader(
        io.StringIO(render_observation_csv((observation,)).decode("utf-8"), newline="")
    )

    assert row["raw_answer"] == "'" + f"{prefix}DANGEROUS()".strip()


def test_f009_export_01_legacy_unknown_is_visibly_ineligible() -> None:
    source = ObservationSource.legacy_unknown(
        raw_evidence=RawEvidence(RawEvidenceKind.LEGACY_UNKNOWN, answer="Legacy answer"),
        configured_model="legacy-model",
        reported_model=None,
    )
    observation = _observation(source=source, requested_eligible=False)

    [row] = csv.DictReader(
        io.StringIO(render_observation_csv((observation,)).decode("utf-8"), newline="")
    )

    assert row["capture_method"] == "unknown"
    assert row["source_badge"] == "Legacy unknown - ineligible"
    assert row["eligible"] == "False"
    assert row["source_stratum_hash"] == ""


def test_f009_artifact_01_server_verifies_hash_and_project_prefix() -> None:
    project_id = uuid4()
    content = b'{"raw":"answer"}'
    content_hash = hashlib.sha256(content).hexdigest()
    requester = RecordingRequester([(200, {"Content-Type": "application/json"}, content)])
    verifier = S3RawArtifactVerifier(_store(requester))
    evidence = RawEvidence(
        RawEvidenceKind.ARTIFACT,
        artifact_uri=(
            f"s3://geo-artifacts/observation-artifacts/{project_id}/answer.json"
        ),
        artifact_hash=content_hash,
    )

    verified = verifier.verify(
        project_id=project_id,
        capture_method=CaptureMethod.MANUAL_UI,
        evidence=evidence,
    )

    assert verified.artifact_verified
    assert requester.calls[0][0] == "GET"


@pytest.mark.parametrize(
    ("capture_method", "key"),
    [
        (CaptureMethod.MANUAL_UI, "content-simulations/{project}/answer.json"),
        (CaptureMethod.SYNTHETIC, "observation-artifacts/{project}/answer.json"),
        (CaptureMethod.PROVIDER_API, "observation-artifacts/{other}/answer.json"),
    ],
)
def test_f009_artifact_01_rejects_cross_namespace_or_cross_project_artifacts(
    capture_method: CaptureMethod, key: str
) -> None:
    project_id = uuid4()
    requester = RecordingRequester([])
    verifier = S3RawArtifactVerifier(_store(requester))
    uri = "s3://geo-artifacts/" + key.format(project=project_id, other=uuid4())
    evidence = RawEvidence(
        RawEvidenceKind.ARTIFACT, artifact_uri=uri, artifact_hash="a" * 64
    )

    with pytest.raises(RawArtifactVerificationError, match="outside"):
        verifier.verify(
            project_id=project_id,
            capture_method=capture_method,
            evidence=evidence,
        )

    assert requester.calls == []


def _store(requester: RecordingRequester) -> S3CompatibleObjectStore:
    return S3CompatibleObjectStore(
        endpoint="https://objects.example.test",
        bucket="geo-artifacts",
        access_key="test-access",
        secret_key="test-secret",
        requester=requester,
    )


def _source(answer: str) -> ObservationSource:
    return ObservationSource(
        capture_method=CaptureMethod.MANUAL_UI,
        platform=ObservationPlatform.OPENAI,
        surface=ObservationSurface.CHATGPT_SEARCH,
        surface_kind=SurfaceKind.CONSUMER_UI,
        platform_detail=None,
        surface_detail=None,
        configured_model=ModelIdentity(ModelIdentityState.DISCLOSED, "model-v1"),
        reported_model=ModelIdentity(ModelIdentityState.NOT_DISCLOSED),
        run=ObservationRunParameters(
            engine="chatgpt",
            locale="en-AU",
            region="AU",
            language="en",
            device=ObservationDevice.DESKTOP,
            client_kind=ClientKind.BROWSER,
            search_enabled=True,
            search_mode=SearchMode.LIVE_WEB,
            prompt_text="Which product?",
        ),
        raw_evidence=RawEvidence(RawEvidenceKind.ANSWER, answer=answer),
        citations_captured=True,
    )


def _observation(
    *, source: ObservationSource | None = None, requested_eligible: bool = True
) -> MonitoringObservation:
    source = source or _source('Answer, with "quotes"\nand line')
    project_id, campaign_id, protocol_id, query_id = uuid4(), uuid4(), uuid4(), uuid4()
    citations = (
        ObservationCitation(
            uuid4(), 1, "https://example.test/second", "Second",
            VerificationStatus.UNKNOWN, None, None, False,
        ),
        ObservationCitation(
            uuid4(), 0, "https://example.test/first", "First",
            VerificationStatus.UNKNOWN, None, None, False,
        ),
    )
    citation_drafts = tuple(
        CitationDraft(
            citation.url, citation.title, VerificationStatus.UNKNOWN, None
        )
        for citation in citations
    )
    source_reasons = source.eligibility_reasons(result_succeeded=True)
    eligible = requested_eligible and not source_reasons
    draft = ObservationDraft(
        monitoring_query_id=query_id,
        measurement_window=MeasurementWindow.BASELINE,
        sample_index=1,
        result_status=ResultStatus.SUCCEEDED,
        requested_eligible=requested_eligible,
        eligible=eligible,
        ineligible_reasons=() if eligible else tuple(source_reasons),
        url_verification_status=VerificationStatus.UNKNOWN,
        recommendation_present=True,
        primary_product_mentioned=True,
        competitor_mentioned=False,
        raw_answer=source.raw_evidence.answer,
        raw_result=dict(source.raw_evidence.inline_response or {}),
        citations=citation_drafts,
        artifact_uri=source.raw_evidence.artifact_uri,
        artifact_hash=source.raw_evidence.artifact_hash,
        configured_model=source.configured_model.value,
        provider_reported_model=source.reported_model.value,
        ui_surface=source.surface.value,
        ui_metadata={},
        confounding_factors=(),
        observed_at=NOW,
        source=source,
        query_cluster_key="vacuum-recommendations",
    )
    return MonitoringObservation(
        id=uuid4(),
        project_id=project_id,
        protocol_id=protocol_id,
        campaign_id=campaign_id,
        draft=draft,
        payload_hash=draft.payload_hash(),
        citations=citations,
        captured_by=UUID("00000000-0000-0000-0000-000000000001"),
        created_at=NOW,
    )
