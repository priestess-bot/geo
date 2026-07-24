"""Deterministically encrypted object artifacts for Synthetic child-call tasks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Protocol
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from geo_core.synthetic_lab.artifact_keyring import SyntheticArtifactKeyring
from geo_core.synthetic_lab.child_model_calls import SyntheticChildModelCallTask
from geo_core.synthetic_lab.domain import SyntheticLabContractError, _require_hash, _require_uuid
from geo_core.synthetic_lab.postgres_codec import decode_object, encode_object
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier


_PREFIX = b"GEO-SYNTHETIC-CHILD-TASK-V1\x00"
_KDF_SALT = b"geo-synthetic-child-task-v1\x00"
_CONTENT_TYPE = "application/vnd.geo.synthetic-child-task+encrypted"


class ChildTaskObjectStore(Protocol):
    def put_object(
        self, *, key: str, content: bytes, content_type: str, expected_hash: str
    ) -> Any: ...

    def get_s3_uri(self, *, uri: str, expected_hash: str) -> Any: ...


@dataclass(frozen=True)
class SyntheticChildTaskArtifactRef:
    uri: str
    artifact_hash: str

    def __post_init__(self) -> None:
        if not self.uri.startswith("s3://"):
            raise SyntheticLabContractError("child task artifact requires an S3 URI")
        _require_hash(self.artifact_hash, "child task artifact")


class SyntheticChildTaskArtifactStore(Protocol):
    def put(self, task: SyntheticChildModelCallTask) -> SyntheticChildTaskArtifactRef: ...

    def load(
        self,
        reference: SyntheticChildTaskArtifactRef,
        *,
        project_id: UUID,
        child_job_id: UUID,
        expected_input_hash: str,
    ) -> SyntheticChildModelCallTask: ...


class EncryptedSyntheticChildTaskArtifactStore:
    """Store task content outside Jobs using deterministic per-content encryption."""

    def __init__(
        self,
        *,
        object_store: ChildTaskObjectStore,
        keyring: SyntheticArtifactKeyring,
    ) -> None:
        self._objects = object_store
        self._keyring = keyring

    def put(self, task: SyntheticChildModelCallTask) -> SyntheticChildTaskArtifactRef:
        plaintext = bytearray(_serialize_task(task))
        try:
            envelope = self._encrypt(task, plaintext)
        finally:
            _wipe(plaintext)
        artifact_hash = hashlib.sha256(envelope).hexdigest()
        key = (
            f"synthetic-lab/child-tasks/{task.project_id}/"
            f"{task.child_job_id}/{artifact_hash}.bin"
        )
        stored = self._objects.put_object(
            key=key,
            content=envelope,
            content_type=_CONTENT_TYPE,
            expected_hash=artifact_hash,
        )
        uri = getattr(stored, "uri", None)
        if not isinstance(uri, str):
            raise SyntheticLabContractError("child task object store returned no S3 URI")
        return SyntheticChildTaskArtifactRef(uri=uri, artifact_hash=artifact_hash)

    def load(
        self,
        reference: SyntheticChildTaskArtifactRef,
        *,
        project_id: UUID,
        child_job_id: UUID,
        expected_input_hash: str,
    ) -> SyntheticChildModelCallTask:
        _require_uuid(project_id, "child task artifact Project")
        _require_uuid(child_job_id, "child task artifact Job")
        _require_hash(expected_input_hash, "child task expected input")
        retrieved = self._objects.get_s3_uri(
            uri=reference.uri,
            expected_hash=reference.artifact_hash,
        )
        payload = getattr(retrieved, "content", None)
        if not isinstance(payload, bytes):
            raise SyntheticLabContractError("child task object payload is unavailable")
        plaintext = bytearray(
            self._decrypt(
                payload,
                project_id=project_id,
                child_job_id=child_job_id,
                expected_input_hash=expected_input_hash,
            )
        )
        try:
            task = _deserialize_task(bytes(plaintext))
        finally:
            _wipe(plaintext)
        if (
            task.project_id != project_id
            or task.child_job_id != child_job_id
            or task.input_hash != expected_input_hash
        ):
            raise SyntheticLabContractError("child task artifact lineage changed")
        return task

    def _encrypt(self, task: SyntheticChildModelCallTask, plaintext: bytearray) -> bytes:
        plaintext_hash = hashlib.sha256(plaintext).hexdigest()
        version, secret = self._keyring.resolve(
            project_id=task.project_id,
            storage_tier=ArtifactStorageTier.ENCRYPTED_RAW,
        )
        header = _header(version, plaintext_hash)
        key = _derived_key(
            secret.reveal_bytes(),
            project_id=task.project_id,
            child_job_id=task.child_job_id,
            plaintext_hash=plaintext_hash,
        )
        try:
            nonce = hashlib.sha256(
                b"nonce\x00" + task.child_job_id.bytes + bytes.fromhex(plaintext_hash)
            ).digest()[:12]
            ciphertext = AESGCM(bytes(key)).encrypt(
                nonce,
                bytes(plaintext),
                _aad(header, task.project_id, task.child_job_id, task.input_hash),
            )
            return header + nonce + ciphertext
        finally:
            _wipe(key)

    def _decrypt(
        self,
        envelope: bytes,
        *,
        project_id: UUID,
        child_job_id: UUID,
        expected_input_hash: str,
    ) -> bytes:
        version, plaintext_hash, header, encrypted = _parse_envelope(envelope)
        _version, secret = self._keyring.resolve_version(
            project_id=project_id,
            storage_tier=ArtifactStorageTier.ENCRYPTED_RAW,
            version=version,
        )
        key = _derived_key(
            secret.reveal_bytes(),
            project_id=project_id,
            child_job_id=child_job_id,
            plaintext_hash=plaintext_hash,
        )
        try:
            try:
                plaintext = AESGCM(bytes(key)).decrypt(
                    encrypted[:12],
                    encrypted[12:],
                    _aad(header, project_id, child_job_id, expected_input_hash),
                )
            except InvalidTag as error:
                raise SyntheticLabContractError(
                    "child task artifact authentication failed"
                ) from error
        finally:
            _wipe(key)
        if hashlib.sha256(plaintext).hexdigest() != plaintext_hash:
            raise SyntheticLabContractError("child task plaintext hash changed")
        return plaintext


def _serialize_task(task: SyntheticChildModelCallTask) -> bytes:
    type_name, payload, _payload_hash = encode_object(task)
    return json.dumps(
        {"schema_version": 1, "type": type_name, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _deserialize_task(payload: bytes) -> SyntheticChildModelCallTask:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyntheticLabContractError("child task artifact JSON is invalid") from error
    if not isinstance(document, dict) or set(document) != {"schema_version", "type", "payload"}:
        raise SyntheticLabContractError("child task artifact schema changed")
    if document["schema_version"] != 1 or not isinstance(document["type"], str):
        raise SyntheticLabContractError("child task artifact version changed")
    if not isinstance(document["payload"], dict):
        raise SyntheticLabContractError("child task artifact payload changed")
    task = decode_object(document["type"], document["payload"])
    if not isinstance(task, SyntheticChildModelCallTask):
        raise SyntheticLabContractError("child task artifact type changed")
    return task


def _header(version: str, plaintext_hash: str) -> bytes:
    return _PREFIX + version.encode("ascii") + b"\x00" + plaintext_hash.encode("ascii") + b"\x00"


def _parse_envelope(envelope: bytes) -> tuple[str, str, bytes, bytes]:
    if not envelope.startswith(_PREFIX):
        raise SyntheticLabContractError("child task artifact envelope is invalid")
    offset = len(_PREFIX)
    version_end = envelope.find(b"\x00", offset)
    hash_end = envelope.find(b"\x00", version_end + 1)
    if version_end <= offset or hash_end <= version_end or len(envelope) <= hash_end + 29:
        raise SyntheticLabContractError("child task artifact envelope is truncated")
    try:
        version = envelope[offset:version_end].decode("ascii")
        plaintext_hash = envelope[version_end + 1 : hash_end].decode("ascii")
    except UnicodeDecodeError as error:
        raise SyntheticLabContractError("child task artifact header is invalid") from error
    _require_hash(plaintext_hash, "child task plaintext")
    return version, plaintext_hash, envelope[: hash_end + 1], envelope[hash_end + 1 :]


def _derived_key(
    root_key: bytes,
    *,
    project_id: UUID,
    child_job_id: UUID,
    plaintext_hash: str,
) -> bytearray:
    return bytearray(
        HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_KDF_SALT,
            info=project_id.bytes + child_job_id.bytes + bytes.fromhex(plaintext_hash),
        ).derive(root_key)
    )


def _aad(header: bytes, project_id: UUID, child_job_id: UUID, input_hash: str) -> bytes:
    return header + project_id.bytes + child_job_id.bytes + bytes.fromhex(input_hash)


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "ChildTaskObjectStore",
    "EncryptedSyntheticChildTaskArtifactStore",
    "SyntheticChildTaskArtifactRef",
    "SyntheticChildTaskArtifactStore",
]
