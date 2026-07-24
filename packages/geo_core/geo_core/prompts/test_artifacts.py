"""Canonical Prompt test artifacts and approval-time integrity verification."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Protocol, cast
from uuid import UUID

from geo_core.object_store import RetrievedObject, StoredObject
from geo_core.prompts.bootstrap_evaluation import evaluate_prompt_test_set
from geo_core.prompts.program import ProgramTestEvidence, PromptProgramRelease
from geo_core.prompts.program_contracts import _canonical_hash
from geo_core.prompts.test_execution_application import _exact_test_spec
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_ARTIFACT_SCHEMA,
    PromptTestArtifactReceipt,
    PromptTestExecutionError,
    PromptTestRunResult,
)


class PromptTestObjectStore(Protocol):
    def put_object(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        expected_hash: str,
    ) -> StoredObject: ...

    def get_s3_uri(self, *, uri: str, expected_hash: str | None = None) -> RetrievedObject: ...


class S3PromptTestArtifactStore:
    def __init__(self, store: PromptTestObjectStore) -> None:
        self._store = store

    def persist(self, result: PromptTestRunResult) -> PromptTestArtifactReceipt:
        content = canonical_artifact_bytes(result.artifact_value())
        content_hash = hashlib.sha256(content).hexdigest()
        task = result.task
        stored = self._store.put_object(
            key=(
                f"prompt-program-tests/{task.project_id}/{task.release_id}/"
                f"{task.job_id}/{content_hash}.json"
            ),
            content=content,
            content_type="application/json",
            expected_hash=content_hash,
        )
        if stored.content_hash != content_hash:
            raise PromptTestExecutionError("Prompt test artifact store changed content hash")
        return PromptTestArtifactReceipt(uri=stored.uri, content_hash=content_hash)


class S3PromptTestEvidenceVerifier:
    """Re-read and re-evaluate terminal evidence before approval."""

    def __init__(self, store: PromptTestObjectStore) -> None:
        self._store = store

    def verify(
        self,
        *,
        release: PromptProgramRelease,
        evidence: ProgramTestEvidence,
    ) -> None:
        if (
            evidence.project_id != release.project_id
            or evidence.release_id != release.id
            or evidence.release_hash != release.release_hash
            or evidence.test_set_id != release.test_set_id
            or evidence.test_set_version != release.test_set_version
        ):
            raise PromptTestExecutionError(
                "Prompt test evidence does not match the exact Release"
            )
        try:
            retrieved = self._store.get_s3_uri(
                uri=evidence.output_artifact_ref,
                expected_hash=evidence.output_hash,
            )
            if (
                retrieved.content_hash != evidence.output_hash
                or hashlib.sha256(retrieved.content).hexdigest()
                != evidence.output_hash
            ):
                raise PromptTestExecutionError(
                    "Prompt test artifact content hash does not match evidence"
                )
            document = json.loads(retrieved.content)
            if canonical_artifact_bytes(document) != retrieved.content:
                raise PromptTestExecutionError("Prompt test artifact is not canonical JSON")
            _verify_document(release=release, document=_object(document, "artifact"))
        except PromptTestExecutionError:
            raise
        except Exception as error:
            raise PromptTestExecutionError(
                "Prompt test artifact is unavailable or invalid"
            ) from error


def canonical_artifact_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PromptTestExecutionError("Prompt test artifact is not canonical JSON") from error


def _verify_document(
    *, release: PromptProgramRelease, document: Mapping[str, object]
) -> None:
    _exact_keys(
        document,
        {
            "schema_version",
            "project_id",
            "job_id",
            "program_id",
            "release_id",
            "release_version",
            "release_hash",
            "test_set_id",
            "test_set_version",
            "test_set_hash",
            "spec_hash",
            "catalog_hash",
            "task_input_hash",
            "model",
            "cases",
            "evaluation",
            "result_hash",
        },
        "Prompt test artifact",
    )
    spec = _exact_test_spec(
        release=release,
        test_set_id=_uuid(document["test_set_id"], "TestSet"),
        test_set_version=_integer(document["test_set_version"], "TestSet version"),
        test_set_hash=_hash(document["test_set_hash"], "TestSet"),
    )
    expected_identity = {
        "schema_version": PROMPT_TEST_ARTIFACT_SCHEMA,
        "project_id": str(release.project_id),
        "program_id": str(release.program_id),
        "release_id": str(release.id),
        "release_version": release.version,
        "release_hash": release.release_hash,
        "test_set_id": str(release.test_set_id),
        "test_set_version": release.test_set_version,
        "test_set_hash": release.test_set_hash,
        "spec_hash": spec.spec_hash,
    }
    if any(document[key] != value for key, value in expected_identity.items()):
        raise PromptTestExecutionError("Prompt test artifact identity changed")
    _uuid(document["job_id"], "Prompt test Job")
    task_input_hash = _hash(document["task_input_hash"], "Prompt test input")
    _hash(document["catalog_hash"], "Prompt catalog")
    _object(document["model"], "Model selection")

    raw_cases = _list(document["cases"], "Prompt test cases")
    if len(raw_cases) != len(spec.fixtures):
        raise PromptTestExecutionError("Prompt test artifact case count changed")
    outputs: dict[str, Mapping[str, object]] = {}
    call_lineage: list[dict[str, str]] = []
    for fixture, raw_case in zip(spec.fixtures, raw_cases, strict=True):
        case = _object(raw_case, "Prompt test case")
        _exact_keys(
            case,
            {"fixture_id", "fixture_hash", "model_call_id", "response_hash", "output"},
            "Prompt test case",
        )
        if case["fixture_id"] != fixture.fixture_id or case["fixture_hash"] != fixture.fixture_hash:
            raise PromptTestExecutionError("Prompt test artifact fixture identity changed")
        model_call_id = _uuid(case["model_call_id"], "model call")
        response_hash = _hash(case["response_hash"], "model response")
        output = _object(case["output"], "model output")
        outputs[fixture.fixture_id] = output
        call_lineage.append(
            {
                "fixture_id": fixture.fixture_id,
                "fixture_hash": fixture.fixture_hash,
                "model_call_id": str(model_call_id),
                "response_hash": response_hash,
            }
        )
    evaluation = evaluate_prompt_test_set(spec, outputs)
    if not evaluation.passed:
        raise PromptTestExecutionError("Prompt test artifact did not pass frozen criteria")
    stored_evaluation = _object(document["evaluation"], "Prompt test evaluation")
    _exact_keys(
        stored_evaluation,
        {"result_hash", "score", "passed", "case_results"},
        "Prompt test evaluation",
    )
    expected_evaluation = {
        "result_hash": evaluation.result_hash,
        "score": evaluation.score,
        "passed": evaluation.passed,
        "case_results": [item.canonical_value() for item in evaluation.case_results],
    }
    if stored_evaluation != expected_evaluation:
        raise PromptTestExecutionError("Prompt test artifact evaluation was not recomputed")
    result_hash = _canonical_hash(
        {
            "task_input_hash": task_input_hash,
            "evaluation_result_hash": evaluation.result_hash,
            "model_calls": call_lineage,
        }
    )
    if document["result_hash"] != result_hash:
        raise PromptTestExecutionError("Prompt test artifact result hash changed")


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PromptTestExecutionError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise PromptTestExecutionError(f"{label} must be an array")
    return value


def _exact_keys(value: Mapping[str, object], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise PromptTestExecutionError(f"{label} fields do not match the frozen schema")


def _uuid(value: object, label: str) -> UUID:
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PromptTestExecutionError(f"{label} identity is invalid") from error
    if parsed.int == 0:
        raise PromptTestExecutionError(f"{label} identity is invalid")
    return parsed


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PromptTestExecutionError(f"{label} must be positive")
    return value


def _hash(value: object, label: str) -> str:
    rendered = str(value)
    if len(rendered) != 64 or any(
        character not in "0123456789abcdef" for character in rendered
    ):
        raise PromptTestExecutionError(f"{label} hash is invalid")
    return rendered


__all__ = [
    "PromptTestObjectStore",
    "S3PromptTestArtifactStore",
    "S3PromptTestEvidenceVerifier",
    "canonical_artifact_bytes",
]
