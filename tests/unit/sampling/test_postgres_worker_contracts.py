from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
from uuid import uuid4

import pytest

from geo_core.model_gateway import canonical_json_hash
from geo_core.model_gateway.contracts import (
    ModelAudience,
    ModelCaptureMethod,
    ModelGatewayResult,
)
from geo_core.model_gateway.location import (
    EffectiveModelLocation,
    ModelLocationControl,
    RequestedModelLocation,
)
from geo_core.jobs.postgres import WorkerLease
from geo_core.sampling import (
    SURFACE_PARSER_RELEASES,
    SurfaceArtifactCaptureKind,
    SurfaceParseSummary,
    parse_surface_artifact,
)
from geo_core.sampling.postgres_worker_contracts import (
    ManualSamplingWorkerSpec,
    WorkflowCSamplingSpecError,
    parse_provider_sampling_spec,
    parse_sampling_worker_source,
)
from geo_core.sampling.postgres_worker_evidence import (
    build_manual_commit,
    build_provider_commit,
)
from geo_core.sampling.postgres_worker_repository import (
    ManualSamplingExecutionState,
    PostgresWorkflowCSamplingRepository,
    SamplingExecutionState,
)


NOW = datetime(2026, 7, 23, tzinfo=UTC)
HASH = "a" * 64
PROJECT_ID = uuid4()
RUN_ID = uuid4()
TASK_ID = uuid4()
ATTEMPT_ID = uuid4()


def test_provider_spec_requires_one_secret_free_frozen_shape() -> None:
    payload = _provider_payload()
    parsed = parse_provider_sampling_spec(payload)

    assert parsed.question_text == "Which provider should I choose?"
    assert parsed.prompt.purpose == "sampling.provider"

    payload["credential"] = "not-allowed"
    with pytest.raises(WorkflowCSamplingSpecError, match="keys"):
        parse_provider_sampling_spec(payload)


def test_provider_commit_drops_answer_text_from_persisted_evidence() -> None:
    source = parse_sampling_worker_source(_suite_payload())
    spec = parse_provider_sampling_spec(_provider_payload())
    result = _provider_result(answer="Call Jane at jane@example.com")

    commit = build_provider_commit(
        project_id=PROJECT_ID,
        spec=spec,
        task_key=HASH,
        question_id="q-1",
        question_version="v1",
        source=source,
        result=result,
        model_attempt_id=uuid4(),
        output_hash=canonical_json_hash(result.output),
        observed_at=NOW,
    )

    persisted = repr(dict(commit.evidence))
    assert "jane@example.com" not in persisted
    assert commit.evidence_status == "complete"
    assert commit.actual_location_hash == HASH_FOR_LOCATION


def test_worker_source_accepts_only_the_frozen_suite_envelope_shape() -> None:
    payload = {
        "schema_version": 1,
        "suite": _suite_payload(),
        "frozen_by": "operator",
        "frozen_at": NOW.isoformat(),
    }

    source = parse_sampling_worker_source(payload)

    assert source.source.platform == "openai"
    assert source.questions == {
        ("q-1", "v1"): "7a1a7782307dda3f58a1a137d81046e73237d8279448ddffa5f75d26092680f8"
    }
    payload["unexpected"] = True
    with pytest.raises(WorkflowCSamplingSpecError, match="envelope"):
        parse_sampling_worker_source(payload)


def test_manual_commit_requires_uncontrolled_source_and_withholds_raw_reference() -> None:
    source = parse_sampling_worker_source(_manual_suite_payload())
    spec = ManualSamplingWorkerSpec(
        manual_import_id=uuid4(),
        run_id=RUN_ID,
        task_id=TASK_ID,
        attempt_id=ATTEMPT_ID,
        artifact_manifest_id=uuid4(),
        artifact_manifest_hash=HASH,
        artifact_content_hash="b" * 64,
        governance_policy_hash="c" * 64,
        capture_session_id=uuid4(),
        task_version=1,
        attempt_version=1,
    )

    commit = build_manual_commit(
        project_id=PROJECT_ID,
        spec=spec,
        task_key=HASH,
        source=source,
        manifest_uri="s3://geo-restricted-workflow-c-artifacts/path/manifest.json",
        observed_at=NOW,
    )

    raw = commit.evidence["raw_artifact"]
    assert isinstance(raw, dict)
    assert raw["manifest_reference"] == f"withheld://manual-evidence/raw/{'b' * 64}"
    assert commit.evidence["usage_audience"] == "internal_worker"


def test_manual_repository_uses_complete_status_and_empty_ineligible_reasons() -> None:
    source = parse_sampling_worker_source(_manual_suite_payload())
    lease = WorkerLease(
        job_id=uuid4(),
        project_id=PROJECT_ID,
        kind="sampling.manual_import",
        worker_id="sampling-worker",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )
    spec = ManualSamplingWorkerSpec(
        manual_import_id=uuid4(),
        run_id=RUN_ID,
        task_id=TASK_ID,
        attempt_id=ATTEMPT_ID,
        artifact_manifest_id=uuid4(),
        artifact_manifest_hash=HASH,
        artifact_content_hash="b" * 64,
        governance_policy_hash="c" * 64,
        capture_session_id=uuid4(),
        task_version=1,
        attempt_version=1,
    )
    state = ManualSamplingExecutionState(
        sampling=SamplingExecutionState(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            task_id=TASK_ID,
            attempt_id=ATTEMPT_ID,
            durable_job_id=lease.job_id,
            task_key=HASH,
            question_id="q-1",
            question_version="v1",
            task_version=1,
            attempt_version=1,
            source=source,
            run_purpose="sampling.manual_import",
        ),
        manual_import_id=spec.manual_import_id,
        artifact_manifest_id=spec.artifact_manifest_id,
        artifact_manifest_hash=spec.artifact_manifest_hash,
        artifact_content_hash=spec.artifact_content_hash,
        governance_policy_hash=spec.governance_policy_hash,
        capture_session_id=spec.capture_session_id,
        manifest_uri="s3://geo-restricted-workflow-c-artifacts/path/manifest.json",
        evidence_kind="redacted_manual_evidence",
        persisted_content_type="application/json",
    )
    commit = build_manual_commit(
        project_id=PROJECT_ID,
        spec=spec,
        task_key=HASH,
        source=source,
        manifest_uri=state.manifest_uri,
        observed_at=NOW,
    )
    connection = _CommitConnection(commit.observation_id)

    PostgresWorkflowCSamplingRepository(lambda: connection).commit_manual(
        connection=connection,
        lease=lease,
        spec_hash="d" * 64,
        state=state,
        spec=spec,
        commit=commit,
    )

    query, parameters = connection.calls[0]
    assert "geo_commit_workflow_c_manual_sampling" in query
    assert len(parameters) == 24
    assert query.count("%s") == len(parameters)
    assert parameters[18] == "complete"
    assert isinstance(parameters[19], str)
    assert json.loads(parameters[19]) == []


def test_manual_surface_parse_controls_observation_eligibility_without_text() -> None:
    source = parse_sampling_worker_source(_manual_suite_payload())
    spec = ManualSamplingWorkerSpec(
        manual_import_id=uuid4(),
        run_id=RUN_ID,
        task_id=TASK_ID,
        attempt_id=ATTEMPT_ID,
        artifact_manifest_id=uuid4(),
        artifact_manifest_hash=HASH,
        artifact_content_hash="b" * 64,
        governance_policy_hash="c" * 64,
        capture_session_id=uuid4(),
        task_version=1,
        attempt_version=1,
    )
    release = SURFACE_PARSER_RELEASES[0]
    captured = SurfaceParseSummary.from_result(
        parse_surface_artifact(
            release,
            _surface_artifact(release),
            capture_kind=SurfaceArtifactCaptureKind.MANUAL_UI,
        )
    )
    blocked_artifact = _surface_artifact(release)
    blocked_artifact["blocking_state"] = "captcha"
    blocked = SurfaceParseSummary.from_result(
        parse_surface_artifact(
            release,
            blocked_artifact,
            capture_kind=SurfaceArtifactCaptureKind.MANUAL_UI,
        )
    )

    captured_commit = build_manual_commit(
        project_id=PROJECT_ID,
        spec=spec,
        task_key=HASH,
        source=source,
        manifest_uri="s3://geo-restricted-workflow-c-artifacts/path/manifest.json",
        surface_parse=captured,
        observed_at=NOW,
    )
    blocked_commit = build_manual_commit(
        project_id=PROJECT_ID,
        spec=spec,
        task_key=HASH,
        source=source,
        manifest_uri="s3://geo-restricted-workflow-c-artifacts/path/manifest.json",
        surface_parse=blocked,
        observed_at=NOW,
    )

    assert captured_commit.evidence_status == "complete"
    assert captured_commit.ineligible_reasons == ()
    assert blocked_commit.evidence_status == "ineligible"
    assert blocked_commit.ineligible_reasons == (
        "surface_parse:access_blocked:captcha",
    )
    assert "Australian answer" not in repr(dict(captured_commit.evidence))
    surface_lineage = captured_commit.evidence["surface_parse"]
    assert isinstance(surface_lineage, dict)
    assert surface_lineage["summary_hash"] == captured.summary_hash
    assert surface_lineage["automated_capture"] is False
    assert surface_lineage["live_capture_eligible"] is False


class _CommitCursor:
    def __init__(self, observation_id) -> None:
        self._row = {"observation_id": observation_id}

    def fetchone(self) -> dict[str, object]:
        return self._row


class _CommitConnection:
    def __init__(self, observation_id) -> None:
        self._observation_id = observation_id
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> _CommitCursor:
        self.calls.append((query, parameters))
        return _CommitCursor(self._observation_id)


def _provider_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "sampling.provider_execute",
        "run_id": str(RUN_ID),
        "task_id": str(TASK_ID),
        "attempt_id": str(ATTEMPT_ID),
        "task_version": 1,
        "attempt_version": 1,
        "question": {
            "text": "Which provider should I choose?",
            "sha256": "7a1a7782307dda3f58a1a137d81046e73237d8279448ddffa5f75d26092680f8",
        },
        "runtime_selection_id": str(uuid4()),
        "admitted_by": str(uuid4()),
        "admitted_at": NOW.isoformat(),
        "prompt": {
            "binding_id": str(uuid4()),
            "state_id": str(uuid4()),
            "state_version": 1,
            "release_id": str(uuid4()),
            "release_hash": HASH,
            "purpose": "sampling.provider",
            "bundle_hash": HASH,
            "system_message": "Return a JSON answer.",
            "answer_field": "answer",
            "output_schema": _schema(),
            "application_output_schema": _schema(),
            "temperature": 0.2,
            "max_output_tokens": 256,
            "seed": 7,
            "tool_mode": None,
        },
        "search_mode": "web_search",
        "deadline_at": None,
    }


def _suite_payload() -> dict[str, object]:
    return {
        "source_stratum": {
            "platform": "openai",
            "surface": "grounded_answers",
            "configured_model": "gpt-test",
            "reported_model": "gpt-test",
            "capture_method": "provider_api",
            "adapter_release": "openai-v1",
            "locale": "en-AU",
            "region": "AU",
            "language": "en",
            "search_mode": "web_search",
            "account_cohort": "not_applicable",
            "egress_policy_category": "not_applicable",
            "location_control": "country",
            "location_evidence_hash": HASH,
            "requested_country": "AU",
            "requested_region": None,
            "requested_locale": "en-AU",
            "requested_language": "en",
            "effective_country": "AU",
            "effective_region": None,
            "effective_locale": None,
            "effective_language": None,
        },
        "questions": [
            {
                "question_id": "q-1",
                "question_version": "v1",
                "text_hash": "7a1a7782307dda3f58a1a137d81046e73237d8279448ddffa5f75d26092680f8",
            }
        ],
    }


def _manual_suite_payload() -> dict[str, object]:
    payload = _suite_payload()
    source_value = payload["source_stratum"]
    assert isinstance(source_value, dict)
    source = dict(source_value)
    source.update(
        {
            "platform": "google",
            "surface": "ai_overviews",
            "capture_method": "manual_ui",
            "region": "not_controlled",
            "location_control": "not_controlled",
            "effective_country": None,
        }
    )
    return {"source_stratum": source, "questions": payload["questions"]}


def _surface_artifact(release) -> dict[str, object]:
    return {
        "schema_version": "consumer-surface-artifact-v1",
        "platform": release.platform,
        "surface": release.surface.value,
        "final_url": "https://www.google.com/search?q=fixture",
        "page_ready": True,
        "surface_markers": [release.surface_marker],
        "ordinary_result_markers": ["ordinary_results_ready"],
        "answer_blocks": [
            {"text": "Australian answer", "locator": "dom://answer/1"}
        ],
        "citations": [],
        "blocking_state": None,
        "follow_up_count": 0,
    }


def _provider_result(*, answer: str) -> ModelGatewayResult:
    return ModelGatewayResult(
        output={"answer": answer},
        call_log_id=uuid4(),
        provider_request_id="response-1",
        configured_model="gpt-test",
        provider_reported_model="gpt-test",
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=Decimal("0.001"),
        finish_reason="stop",
        response_hash="d" * 64,
        provider="openai",
        adapter_release_id="openai-v1",
        adapter_release_hash="e" * 64,
        model_release_id="gpt-test",
        model_release_hash="f" * 64,
        raw_artifact_reference="s3://geo-artifacts/raw-manifest",
        raw_artifact_manifest_hash="1" * 64,
        raw_artifact_content_hash="2" * 64,
        raw_artifact_byte_size=10,
        derived_artifact_reference="s3://geo-artifacts/derived-manifest",
        derived_artifact_manifest_hash="3" * 64,
        derived_artifact_content_hash="4" * 64,
        derived_artifact_byte_size=10,
        raw_artifact_policy_hash="5" * 64,
        raw_artifact_storage_decision="allowed",
        raw_artifact_cache_decision="allowed",
        raw_artifact_display_decision="allowed",
        raw_artifact_redistribution_decision="prohibited",
        usage_purpose="sampling.provider",
        usage_audience=ModelAudience.INTERNAL_WORKER,
        capture_method=ModelCaptureMethod.PROVIDER_API,
        search_mode="web_search",
        requested_location=RequestedModelLocation(
            country_code="AU", region_code=None, locale="en-AU", language="en"
        ),
        effective_location=EffectiveModelLocation(
            control=ModelLocationControl.COUNTRY,
            country_code="AU",
            region_code=None,
            locale=None,
            language=None,
            evidence_hash=HASH,
        ),
    )


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }


HASH_FOR_LOCATION = "48be4bf24ea1af7f8561581848b38c45bda812c82ae3566dc4e986b97c37c839"
