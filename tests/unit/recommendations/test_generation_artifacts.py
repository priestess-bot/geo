from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from geo_core.recommendations.generation_artifacts import (
    EncryptedRecommendationTaskArtifactStore,
    RecommendationTaskArtifactError,
)
from geo_core.recommendations.generation_ports import (
    RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    RECOMMENDATION_OUTPUT_SCHEMA,
    structured_generation_input,
)
from geo_core.recommendations.generation_worker_contracts import (
    RecommendationModelRole,
    RecommendationModelTask,
)
from geo_core.secrets import EnvelopeCipher, MasterKeyring

from .generation_test_support import PromptResolverStub, generation_spec


class _Objects:
    def __init__(self) -> None:
        self.values: dict[str, tuple[bytes, str]] = {}
        self.fail_manifest = False

    def uri_for_key(self, key: str) -> str:
        return f"s3://recommendation-artifacts/{key}"

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ):
        payload = content.encode() if isinstance(content, str) else content
        if self.fail_manifest and content_type.endswith("+json"):
            raise RecommendationTaskArtifactError("manifest write failed")
        digest = hashlib.sha256(payload).hexdigest()
        assert expected_hash is None or digest == expected_hash
        self.values[key] = (payload, content_type)
        return SimpleNamespace(
            uri=self.uri_for_key(key),
            bucket="recommendation-artifacts",
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=None,
        )

    def delete_s3_uri(self, *, uri: str) -> bool:
        prefix = "s3://recommendation-artifacts/"
        self.values.pop(uri.removeprefix(prefix), None)
        return True

    def get_s3_uri(self, *, uri: str, expected_hash: str | None = None):
        prefix = "s3://recommendation-artifacts/"
        assert uri.startswith(prefix)
        key = uri.removeprefix(prefix)
        payload, content_type = self.values[key]
        digest = hashlib.sha256(payload).hexdigest()
        if expected_hash is not None and digest != expected_hash:
            raise RecommendationTaskArtifactError("object hash changed")
        return SimpleNamespace(
            content=payload,
            bucket="recommendation-artifacts",
            key=key,
            content_type=content_type,
            content_hash=digest,
            etag=None,
        )


def test_model_task_artifact_encrypts_prompt_body_and_round_trips() -> None:
    task = _task()
    objects = _Objects()
    store = _store(objects)

    reference = store.put(task)
    loaded = store.load(
        reference,
        project_id=task.project_id,
        child_job_id=task.child_job_id,
        expected_parent_input_hash=task.parent_input_hash,
    )

    assert loaded == task
    assert reference.uri.endswith(".json")
    assert reference.byte_size > 0
    persisted = b"".join(value[0] for value in objects.values.values())
    assert b"Approved summary" not in persisted
    assert b"Run recommendation" not in persisted
    assert b"recommendations.recommendation" not in persisted


def test_model_task_artifact_rejects_wrong_parent_hash_and_manifest_tamper() -> None:
    task = _task()
    objects = _Objects()
    store = _store(objects)
    reference = store.put(task)

    with pytest.raises(RecommendationTaskArtifactError, match="manifest lineage"):
        store.load(
            reference,
            project_id=task.project_id,
            child_job_id=task.child_job_id,
            expected_parent_input_hash="0" * 64,
        )

    manifest_key = reference.uri.removeprefix("s3://recommendation-artifacts/")
    content, content_type = objects.values[manifest_key]
    objects.values[manifest_key] = (content + b" ", content_type)
    with pytest.raises(RecommendationTaskArtifactError, match="object hash"):
        store.load(
            reference,
            project_id=task.project_id,
            child_job_id=task.child_job_id,
            expected_parent_input_hash=task.parent_input_hash,
        )


def test_model_task_artifact_removes_payload_when_manifest_write_fails() -> None:
    objects = _Objects()
    objects.fail_manifest = True

    with pytest.raises(RecommendationTaskArtifactError, match="manifest write"):
        _store(objects).put(_task())

    assert objects.values == {}


def test_artifact_plan_supports_crypto_erase_then_idempotent_ciphertext_delete() -> None:
    task = _task()
    objects = _Objects()
    store = _store(objects)
    plan = store.plan(task)

    assert store.plan(task) == plan
    reference = store.put(task, plan=plan)
    target = store.inspect_for_deletion(
        reference,
        project_id=task.project_id,
        child_job_id=task.child_job_id,
        expected_parent_input_hash=task.parent_input_hash,
    )

    assert target.payload_uri == plan.payload_uri
    assert target.expires_at == task.artifact_expires_at
    assert len(target.tombstone_hash) == 64
    erase_receipt = store.crypto_erase(target)
    assert len(erase_receipt) == 64
    assert plan.manifest_key not in objects.values
    assert plan.payload_key in objects.values
    delete_receipt = store.delete_ciphertext(target)
    assert len(delete_receipt) == 64
    assert objects.values == {}
    assert store.delete_ciphertext(target) == delete_receipt


def test_expired_task_artifact_fails_closed_before_decryption() -> None:
    task = _task()
    objects = _Objects()
    now = [datetime(2026, 7, 23, 12, 0, tzinfo=UTC)]
    store = EncryptedRecommendationTaskArtifactStore(
        object_store=objects,
        cipher=EnvelopeCipher(
            MasterKeyring(keys={1: b"r" * 32}, active_version=1),
            random_bytes=lambda size: bytes(range(1, size + 1)),
        ),
        clock=lambda: now[0],
    )
    reference = store.put(task)
    now[0] = task.artifact_expires_at

    with pytest.raises(RecommendationTaskArtifactError, match="expired"):
        store.load(
            reference,
            project_id=task.project_id,
            child_job_id=task.child_job_id,
            expected_parent_input_hash=task.parent_input_hash,
        )


def _store(objects: _Objects) -> EncryptedRecommendationTaskArtifactStore:
    return EncryptedRecommendationTaskArtifactStore(
        object_store=objects,
        cipher=EnvelopeCipher(
            MasterKeyring(keys={1: b"r" * 32}, active_version=1),
            random_bytes=lambda size: bytes(range(1, size + 1)),
        ),
        clock=lambda: datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
    )


def _task() -> RecommendationModelTask:
    spec = generation_spec()
    prompt = PromptResolverStub().resolve(
        binding=spec.prompt_binding,
        route=spec.route,
        configured_model=spec.configured_model,
        model_policy=spec.model_policy,
        capture_method=spec.capture_method,
        search_mode=spec.search_mode,
        structured_input=structured_generation_input(spec.evidence),
        output_schema=RECOMMENDATION_OUTPUT_SCHEMA,
        application_output_schema=RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    )
    return RecommendationModelTask(
        child_job_id=uuid4(),
        parent_job_id=uuid4(),
        project_id=spec.project_id,
        parent_input_hash=spec.input_hash,
        role=RecommendationModelRole.PRIMARY,
        runtime_selection_id=spec.runtime_selection_id,
        runtime_manifest_id=spec.runtime_manifest_id,
        runtime_manifest_hash=spec.runtime_manifest_hash,
        runtime_option_id=spec.runtime_option_id,
        runtime_option_hash=spec.runtime_option_hash,
        prompt=prompt,
        admitted_by=uuid4(),
        artifact_expires_at=spec.valid_until,
    )
