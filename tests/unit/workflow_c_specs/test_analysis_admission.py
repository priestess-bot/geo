from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from geo_core.workflow_c_analysis_admission import (
    AnalysisArtifactKind,
    AnalysisInputManifest,
    AnalysisManifestItem,
    WorkflowCAnalysisAdmissionError,
    analysis_input_manifest,
    approve_metric_protocol,
    manifest_id,
    metric_protocol_definition,
    new_metric_protocol,
    submit_metric_protocol,
)
from tests.workflow_c_analysis_test_support import metric_protocol_definition_fixture


NOW = datetime(2026, 7, 24, tzinfo=UTC)
PROJECT_ID = UUID("71000000-0000-4000-8000-000000000001")


def test_metric_protocol_round_trips_canonically_and_enforces_maker_checker() -> None:
    definition = metric_protocol_definition_fixture()
    decoded = metric_protocol_definition(definition.canonical_value())
    protocol = new_metric_protocol(
        project_id=PROJECT_ID,
        definition=decoded,
        actor_id="protocol-maker",
        idempotency_key="metric-v1",
        occurred_at=NOW,
    )
    submitted = submit_metric_protocol(
        protocol, actor_id="protocol-maker", occurred_at=NOW + timedelta(minutes=1)
    )

    assert decoded.protocol_hash == definition.protocol_hash
    assert submitted.aggregate_version == 2
    with pytest.raises(WorkflowCAnalysisAdmissionError, match="maker cannot approve"):
        approve_metric_protocol(
            submitted,
            actor_id="protocol-maker",
            reason="self approval",
            occurred_at=NOW + timedelta(minutes=2),
        )

    approved = approve_metric_protocol(
        submitted,
        actor_id="protocol-checker",
        reason="fixed regression suite passed",
        occurred_at=NOW + timedelta(minutes=2),
    )
    assert approved.status.value == "approved"
    assert approved.aggregate_version == 3
    assert approved.approved_by == "protocol-checker"


def test_metric_protocol_rejects_prompt_or_corpus_lineage_mismatch() -> None:
    value = metric_protocol_definition_fixture().canonical_value()
    value["prompt_release_hash"] = "0" * 64
    with pytest.raises(WorkflowCAnalysisAdmissionError, match="Prompt Release differs"):
        metric_protocol_definition(value)

    value = metric_protocol_definition_fixture().canonical_value()
    value["corpus_version_hash"] = "1" * 64
    with pytest.raises(WorkflowCAnalysisAdmissionError, match="approved corpus differs"):
        metric_protocol_definition(value)


def test_manifest_and_v2_job_are_secret_free_and_denominator_stable() -> None:
    definition = metric_protocol_definition_fixture()
    item = AnalysisManifestItem(
        ordinal=1,
        task_id=uuid4(),
        task_key="1" * 64,
        question_id="question-1",
        question_version="v1",
        question_cluster="purchase",
        repetition=1,
        observation_id=uuid4(),
        observation_hash="2" * 64,
        observation_status="complete",
        attempt_id=uuid4(),
        source_job_id=uuid4(),
        provider_model_attempt_id=uuid4(),
        output_hash="3" * 64,
        artifact_kind=AnalysisArtifactKind.PROVIDER,
        artifact_id=None,
        artifact_manifest_hash="4" * 64,
        artifact_content_hash="3" * 64,
        actual_location_hash="5" * 64,
    )
    frozen_id = manifest_id(PROJECT_ID, "semantic-analysis-one")
    manifest = AnalysisInputManifest(
        id=frozen_id,
        project_id=PROJECT_ID,
        sampling_run_id=uuid4(),
        sampling_run_version=4,
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
        capture_method="provider_api",
        stratum=(("capture_method", "provider_api"), ("locale", "en-AU")),
        items=(item,),
        frozen_by="analysis-operator",
        frozen_at=NOW,
    )

    assert manifest.observation_count == 1
    assert manifest.job_payload() == {
        "schema_version": 2,
        "kind": "workflow_c.analysis.semantic_metrics",
        "semantic_metrics": {
            "manifest_id": str(frozen_id),
            "manifest_hash": manifest.manifest_hash,
        },
    }
    rendered = str(manifest.canonical_value()) + str(manifest.job_payload())
    assert "answer_text" not in rendered
    assert "credential" not in rendered

    restored = analysis_input_manifest(
        manifest_id=manifest.id,
        frozen_by=manifest.frozen_by,
        frozen_at=manifest.frozen_at,
        value=manifest.canonical_value(),
    )
    assert restored == manifest

    corrupt = manifest.canonical_value()
    corrupt["items"][0]["item_hash"] = "0" * 64
    with pytest.raises(WorkflowCAnalysisAdmissionError, match="item hash is corrupt"):
        analysis_input_manifest(
            manifest_id=manifest.id,
            frozen_by=manifest.frozen_by,
            frozen_at=manifest.frozen_at,
            value=corrupt,
        )
