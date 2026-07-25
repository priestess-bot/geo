from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryRequest,
    RecoveredProviderArtifact,
)
from geo_core.workflow_c_analysis_admission import (
    AnalysisArtifactKind,
    AnalysisInputManifest,
    AnalysisManifestItem,
    canonical_hash,
)
from geo_core.workflow_c_artifacts.reader import RecoveredWorkflowCManualArtifact
from geo_core.workflow_c_job_specs import WorkflowCJobSpec
from geo_core.workflow_c_semantic_materialization import (
    PostgresWorkflowCSemanticInputMaterializer,
    WorkflowCSemanticMaterializationError,
)
from tests.workflow_c_analysis_test_support import metric_protocol_definition_fixture


NOW = datetime(2026, 7, 24, 11, 0, tzinfo=UTC)
PROJECT_ID = UUID("72000000-0000-4000-8000-000000000001")
SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "ordinal": {"type": "integer"},
                    "source_type": {"type": "string"},
                },
                "required": ["url", "title", "ordinal", "source_type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "citations"],
    "additionalProperties": False,
}


def test_manual_manifest_materializes_redacted_answer_and_citations_then_wipes() -> None:
    fixture = _Fixture(artifact_kind=AnalysisArtifactKind.MANUAL)
    payload = bytearray(
        json.dumps(
            {
                "schema_version": 1,
                "source_kind": "json",
                "content": {
                    "answer": "Advinsys Suite is recommended.",
                    "citations": [
                        {
                            "url": "https://example.com",
                            "title": "Verified",
                            "ordinal": 1,
                            "source_type": "official",
                        }
                    ],
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    fixture.manual.recovered = RecoveredWorkflowCManualArtifact(
        artifact_id=fixture.item.artifact_id,
        evidence_kind="transcript_export",
        persisted_content_type="application/vnd.geo.workflow-c-redacted+json",
        manifest_hash=fixture.item.artifact_manifest_hash,
        content_hash=fixture.item.artifact_content_hash,
        payload=payload,
        expires_at=NOW + timedelta(days=1),
    )

    result = fixture.materializer().materialize(lease=fixture.lease, spec=fixture.spec)

    assert len(result.input_set.planned_slots) == 1
    assert result.input_set.observations[0].answer_text == "Advinsys Suite is recommended."
    assert result.input_set.observations[0].citations[0].url == "https://example.com"
    assert result.metadata.warning_ratio == 0
    assert all(byte == 0 for byte in payload)
    assert fixture.provider.requests == []


def test_manual_surface_artifact_materializes_answer_blocks_and_positions() -> None:
    fixture = _Fixture(artifact_kind=AnalysisArtifactKind.MANUAL)
    payload = bytearray(
        json.dumps(
            {
                "schema_version": 1,
                "source_kind": "json",
                "content": {
                    "schema_version": "consumer-surface-artifact-v1",
                    "platform": "google",
                    "surface": "google_ai_overviews",
                    "final_url": "https://www.google.com/search?q=advinsys",
                    "page_ready": True,
                    "surface_markers": ["google_ai_overview_answer"],
                    "ordinary_result_markers": ["ordinary_results_ready"],
                    "answer_blocks": [
                        {"text": "Advinsys Suite is", "locator": "dom://answer/1"},
                        {"text": "recommended.", "locator": "dom://answer/2"},
                    ],
                    "citations": [
                        {
                            "url": "https://example.com",
                            "title": "Verified",
                            "position": 1,
                            "locator": "dom://citation/1",
                        }
                    ],
                    "blocking_state": None,
                    "follow_up_count": 1,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    fixture.manual.recovered = RecoveredWorkflowCManualArtifact(
        artifact_id=fixture.item.artifact_id,
        evidence_kind="transcript_export",
        persisted_content_type="application/vnd.geo.workflow-c-redacted+json",
        manifest_hash=fixture.item.artifact_manifest_hash,
        content_hash=fixture.item.artifact_content_hash,
        payload=payload,
        expires_at=NOW + timedelta(days=1),
    )

    result = fixture.materializer().materialize(lease=fixture.lease, spec=fixture.spec)

    observation = result.input_set.observations[0]
    assert observation.answer_text == "Advinsys Suite is\nrecommended."
    assert observation.citations[0].ordinal == 1
    assert observation.citations[0].url == "https://example.com"
    assert all(byte == 0 for byte in payload)


def test_provider_manifest_uses_source_prompt_and_exact_cross_job_recovery() -> None:
    fixture = _Fixture(artifact_kind=AnalysisArtifactKind.PROVIDER)
    output = {
        "answer": "Advinsys appears before Competitor.",
        "citations": [
            {
                "url": "https://example.com/source",
                "title": "Source",
                "ordinal": 1,
                "source_type": "grounding",
            }
        ],
    }
    output_hash = canonical_hash(output)
    assert fixture.item.output_hash == output_hash
    fixture.provider.recovered = RecoveredProviderArtifact(
        model_call_attempt_id=fixture.item.provider_model_attempt_id,
        artifact_id=uuid4(),
        manifest_hash=fixture.item.artifact_manifest_hash,
        content_hash=fixture.item.artifact_content_hash,
        output_hash=output_hash,
        output=output,
        recovery_receipt_id=uuid4(),
        recovery_receipt_hash="f" * 64,
        recovered_at=NOW,
    )

    result = fixture.materializer().materialize(lease=fixture.lease, spec=fixture.spec)

    observation = result.input_set.observations[0]
    assert observation.answer_text.startswith("Advinsys")
    assert observation.citations[0].source_type == "grounding"
    request = fixture.provider.requests[0]
    assert request.source_model_job_id == fixture.item.source_job_id
    assert request.recovery_job_id == fixture.lease.job_id
    assert request.expected_output_hash == fixture.item.output_hash
    assert request.purpose == "geo_measurement"


def test_expired_analysis_lease_is_rejected_before_artifact_recovery() -> None:
    fixture = _Fixture(artifact_kind=AnalysisArtifactKind.MANUAL)
    fixture.connection.main_row["durable_lease_expires_at"] = NOW

    with pytest.raises(WorkflowCSemanticMaterializationError, match="lease expired"):
        fixture.materializer().materialize(lease=fixture.lease, spec=fixture.spec)

    assert fixture.manual.loads == 0
    assert fixture.provider.requests == []


class _Fixture:
    def __init__(self, *, artifact_kind: AnalysisArtifactKind) -> None:
        definition = metric_protocol_definition_fixture()
        run_id = uuid4()
        task_id = uuid4()
        attempt_id = uuid4()
        source_job_id = uuid4()
        provider_attempt_id = uuid4()
        provider_output = {
            "answer": "Advinsys appears before Competitor.",
            "citations": [
                {
                    "url": "https://example.com/source",
                    "title": "Source",
                    "ordinal": 1,
                    "source_type": "grounding",
                }
            ],
        }
        output_hash = canonical_hash(provider_output)
        self.item = AnalysisManifestItem(
            ordinal=1,
            task_id=task_id,
            task_key="1" * 64,
            question_id="question-1",
            question_version="v1",
            question_cluster="purchase",
            repetition=1,
            observation_id=uuid4(),
            observation_hash="2" * 64,
            observation_status="complete",
            attempt_id=attempt_id,
            source_job_id=source_job_id,
            provider_model_attempt_id=(
                provider_attempt_id
                if artifact_kind is AnalysisArtifactKind.PROVIDER
                else None
            ),
            output_hash=(
                output_hash if artifact_kind is AnalysisArtifactKind.PROVIDER else None
            ),
            artifact_kind=artifact_kind,
            artifact_id=(uuid4() if artifact_kind is AnalysisArtifactKind.MANUAL else None),
            artifact_manifest_hash="3" * 64,
            artifact_content_hash=(
                output_hash
                if artifact_kind is AnalysisArtifactKind.PROVIDER
                else "4" * 64
            ),
            actual_location_hash="5" * 64,
        )
        self.manifest = AnalysisInputManifest(
            id=uuid4(),
            project_id=PROJECT_ID,
            sampling_run_id=run_id,
            sampling_run_version=3,
            sampling_suite_hash="6" * 64,
            metric_protocol_id=uuid4(),
            metric_protocol_hash=definition.protocol_hash,
            fact_snapshot_id=definition.fact_snapshot_id,
            fact_snapshot_hash=definition.fact_snapshot_hash,
            prompt_release_id=definition.prompt_release_id,
            prompt_release_hash=definition.prompt_release_hash,
            corpus_version_id=definition.corpus_version_id,
            corpus_version_hash=definition.corpus_version_hash,
            baseline_snapshot_hash=None,
            source_stratum_hash="7" * 64,
            capture_method=(
                "provider_api"
                if artifact_kind is AnalysisArtifactKind.PROVIDER
                else "manual_ui"
            ),
            stratum=(
                ("provider", "openai" if artifact_kind is AnalysisArtifactKind.PROVIDER else "chatgpt"),
                ("reported_model", "model-v1"),
                ("capture_method", "provider_api" if artifact_kind is AnalysisArtifactKind.PROVIDER else "manual_ui"),
                ("locale", "en-AU"),
                ("region", "AU"),
                ("source_composition_hash", "6" * 64),
                ("sampling_source_stratum_hash", "7" * 64),
                ("question_cluster", "all"),
            ),
            items=(self.item,),
            frozen_by="analysis-operator",
            frozen_at=NOW,
        )
        self.lease = WorkerLease(
            job_id=uuid4(),
            project_id=PROJECT_ID,
            kind="workflow_c.analysis.semantic_metrics",
            worker_id="semantic-worker",
            lease_token=uuid4(),
            fencing_generation=2,
            attempt_count=1,
            max_attempts=3,
        )
        payload = self.manifest.job_payload()
        self.spec = WorkflowCJobSpec(
            project_id=PROJECT_ID,
            job_id=self.lease.job_id,
            kind=self.lease.kind,
            spec_hash=canonical_hash(payload),
            payload=payload,
            created_at=NOW,
        )
        source_row = None
        if artifact_kind is AnalysisArtifactKind.PROVIDER:
            source_payload = _provider_source_payload(
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
            )
            source_row = {
                "job_id": source_job_id,
                "kind": "sampling.provider_execute",
                "spec_hash": canonical_hash(source_payload),
                "spec_payload": source_payload,
                "created_at": NOW,
                "status": "succeeded",
                "input_hash": canonical_hash(source_payload),
            }
        self.connection = _Connection(
            main_row=_manifest_row(
                manifest=self.manifest,
                definition=definition.canonical_value(),
                lease=self.lease,
                spec=self.spec,
            ),
            item_rows=(
                {
                    "ordinal": 1,
                    "payload": self.item.canonical_value()
                    | {"item_hash": self.item.item_hash},
                },
            ),
            source_rows=(() if source_row is None else (source_row,)),
        )
        self.manual = _ManualReader()
        self.provider = _ProviderRecovery()

    def materializer(self) -> PostgresWorkflowCSemanticInputMaterializer:
        return PostgresWorkflowCSemanticInputMaterializer(
            connect=lambda: self.connection,
            manual_artifacts=self.manual,
            provider_artifacts=self.provider,
            clock=lambda: NOW,
        )


def _manifest_row(*, manifest, definition, lease, spec) -> dict[str, object]:
    return {
        "id": manifest.id,
        "project_id": manifest.project_id,
        "manifest_hash": manifest.manifest_hash,
        "sampling_run_id": manifest.sampling_run_id,
        "sampling_run_version": manifest.sampling_run_version,
        "sampling_suite_hash": manifest.sampling_suite_hash,
        "metric_protocol_id": manifest.metric_protocol_id,
        "metric_protocol_hash": manifest.metric_protocol_hash,
        "fact_snapshot_id": manifest.fact_snapshot_id,
        "fact_snapshot_hash": manifest.fact_snapshot_hash,
        "prompt_release_id": manifest.prompt_release_id,
        "prompt_release_hash": manifest.prompt_release_hash,
        "corpus_version_id": manifest.corpus_version_id,
        "corpus_version_hash": manifest.corpus_version_hash,
        "baseline_snapshot_hash": manifest.baseline_snapshot_hash,
        "source_stratum_hash": manifest.source_stratum_hash,
        "capture_method": manifest.capture_method,
        "planned_slot_count": len(manifest.items),
        "observation_count": manifest.observation_count,
        "payload": manifest.canonical_value(),
        "frozen_by": manifest.frozen_by,
        "frozen_at": manifest.frozen_at,
        "protocol_status": "approved",
        "stored_protocol_hash": manifest.metric_protocol_hash,
        "protocol_definition": definition,
        "durable_status": "running",
        "durable_input_hash": spec.spec_hash,
        "durable_lease_token": lease.lease_token,
        "durable_fencing_generation": lease.fencing_generation,
        "durable_lease_expires_at": NOW + timedelta(minutes=5),
        "durable_cancel_requested_at": None,
        "stored_spec_hash": spec.spec_hash,
        "stored_spec_payload": spec.payload,
    }


def _provider_source_payload(*, run_id, task_id, attempt_id) -> dict[str, object]:
    question = "Which suite is recommended?"
    return {
        "schema_version": 1,
        "kind": "sampling.provider_execute",
        "run_id": str(run_id),
        "task_id": str(task_id),
        "attempt_id": str(attempt_id),
        "task_version": 1,
        "attempt_version": 1,
        "question": {
            "text": question,
            "sha256": hashlib.sha256(question.encode()).hexdigest(),
        },
        "runtime_selection_id": str(uuid4()),
        "admitted_by": str(uuid4()),
        "admitted_at": NOW.isoformat(),
        "prompt": {
            "binding_id": str(uuid4()),
            "state_id": str(uuid4()),
            "state_version": 1,
            "release_id": str(uuid4()),
            "release_hash": "8" * 64,
            "purpose": "geo_measurement",
            "bundle_hash": "9" * 64,
            "system_message": "Return structured evidence.",
            "answer_field": "answer",
            "output_schema": SCHEMA,
            "application_output_schema": SCHEMA,
            "temperature": 0.2,
            "max_output_tokens": 512,
            "seed": 1,
            "tool_mode": None,
        },
        "search_mode": "web",
        "deadline_at": None,
    }


class _Cursor:
    def __init__(self, rows) -> None:
        self.rows = tuple(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, *, main_row, item_rows, source_rows) -> None:
        self.main_row = main_row
        self.item_rows = item_rows
        self.source_rows = source_rows
        self.closed = False

    def execute(self, query: str, _parameters=None):
        if "set_config" in query:
            return _Cursor(())
        if "FROM workflow_c_analysis_input_manifests AS manifest" in query:
            return _Cursor((self.main_row,))
        if "FROM workflow_c_analysis_input_manifest_items" in query:
            return _Cursor(self.item_rows)
        if "FROM workflow_c_job_specs AS spec" in query:
            return _Cursor(self.source_rows)
        raise AssertionError(f"unexpected query: {query}")

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _ManualReader:
    def __init__(self) -> None:
        self.recovered = None
        self.loads = 0

    def load(self, _request):
        self.loads += 1
        assert self.recovered is not None
        return self.recovered


class _ProviderRecovery:
    def __init__(self) -> None:
        self.recovered = None
        self.requests: list[ProviderArtifactRecoveryRequest] = []

    def recover_derived(self, request: ProviderArtifactRecoveryRequest):
        self.requests.append(request)
        assert self.recovered is not None
        return self.recovered
