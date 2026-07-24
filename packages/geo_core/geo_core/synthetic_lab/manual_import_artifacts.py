"""Encrypted temporary uploads and anonymized sample objects for manual imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Any, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from geo_core.synthetic_lab.artifact_keyring import SyntheticArtifactKeyring
from geo_core.synthetic_lab.domain import SyntheticLabContractError, _require_hash, _require_uuid
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier


_PREFIX = b"GEO-SYNTHETIC-MANUAL-IMPORT-V1\x00"
_KDF_SALT = b"geo-synthetic-manual-import-v1\x00"
MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE = (
    "application/vnd.geo.synthetic-manual-import+encrypted"
)


class ManualImportArtifactKind(StrEnum):
    TEMPORARY_UPLOAD = "temporary_upload"
    ANONYMIZED_SAMPLE = "anonymized_sample"


class ManualImportObjectStore(Protocol):
    def put_object(
        self, *, key: str, content: bytes, content_type: str, expected_hash: str
    ) -> Any: ...

    def get_s3_uri(self, *, uri: str, expected_hash: str) -> Any: ...

    def delete_s3_uri(self, *, uri: str) -> bool: ...


@dataclass(frozen=True, kw_only=True)
class ManualImportArtifactRef:
    project_id: UUID
    artifact_id: UUID
    kind: ManualImportArtifactKind
    uri: str
    object_hash: str
    plaintext_hash: str
    key_version: str
    byte_size: int
    algorithm: str = "AES-256-GCM/HKDF-project-artifact/v1"

    def __post_init__(self) -> None:
        _require_uuid(self.project_id, "manual import artifact Project")
        _require_uuid(self.artifact_id, "manual import artifact")
        object.__setattr__(self, "kind", ManualImportArtifactKind(self.kind))
        if not self.uri.startswith("s3://"):
            raise SyntheticLabContractError("manual import artifact requires an S3 URI")
        _require_hash(self.object_hash, "manual import encrypted object")
        _require_hash(self.plaintext_hash, "manual import artifact plaintext")
        if not self.key_version or self.byte_size < 1:
            raise SyntheticLabContractError("manual import artifact metadata is invalid")
        if self.algorithm != "AES-256-GCM/HKDF-project-artifact/v1":
            raise SyntheticLabContractError("manual import artifact algorithm changed")


class EncryptedManualImportArtifactStore:
    def __init__(
        self,
        *,
        object_store: ManualImportObjectStore,
        keyring: SyntheticArtifactKeyring,
    ) -> None:
        self._objects = object_store
        self._keyring = keyring

    def put(
        self,
        *,
        project_id: UUID,
        artifact_id: UUID,
        kind: ManualImportArtifactKind,
        payload: bytearray,
    ) -> ManualImportArtifactRef:
        _require_uuid(project_id, "manual import artifact Project")
        _require_uuid(artifact_id, "manual import artifact")
        if not isinstance(payload, bytearray) or not payload:
            raise SyntheticLabContractError("manual import artifact payload must be mutable")
        kind = ManualImportArtifactKind(kind)
        plaintext_hash = hashlib.sha256(payload).hexdigest()
        key_version, root = self._keyring.resolve(
            project_id=project_id,
            storage_tier=_storage_tier(kind),
        )
        header = _header(key_version, plaintext_hash)
        key = _derived_key(
            root.reveal_bytes(),
            project_id=project_id,
            artifact_id=artifact_id,
            kind=kind,
            plaintext_hash=plaintext_hash,
        )
        try:
            nonce = hashlib.sha256(
                b"nonce\x00" + project_id.bytes + artifact_id.bytes + kind.value.encode()
                + bytes.fromhex(plaintext_hash)
            ).digest()[:12]
            envelope = header + nonce + AESGCM(bytes(key)).encrypt(
                nonce,
                bytes(payload),
                _aad(header, project_id, artifact_id, kind),
            )
        finally:
            _wipe(key)
            _wipe(payload)
        object_hash = hashlib.sha256(envelope).hexdigest()
        stored = self._objects.put_object(
            key=(
                f"synthetic-lab/manual-import/{kind.value}/{project_id}/"
                f"{artifact_id}/{object_hash}.bin"
            ),
            content=envelope,
            content_type=MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE,
            expected_hash=object_hash,
        )
        uri = getattr(stored, "uri", None)
        if not isinstance(uri, str):
            raise SyntheticLabContractError("manual import object store returned no S3 URI")
        self._objects.get_s3_uri(uri=uri, expected_hash=object_hash)
        return ManualImportArtifactRef(
            project_id=project_id,
            artifact_id=artifact_id,
            kind=kind,
            uri=uri,
            object_hash=object_hash,
            plaintext_hash=plaintext_hash,
            key_version=key_version,
            byte_size=len(envelope),
        )

    def load(self, reference: ManualImportArtifactRef) -> bytearray:
        retrieved = self._objects.get_s3_uri(
            uri=reference.uri,
            expected_hash=reference.object_hash,
        )
        envelope = getattr(retrieved, "content", None)
        if not isinstance(envelope, bytes):
            raise SyntheticLabContractError("manual import object payload is unavailable")
        version, plaintext_hash, header, encrypted = _parse_envelope(envelope)
        if version != reference.key_version or plaintext_hash != reference.plaintext_hash:
            raise SyntheticLabContractError("manual import artifact header changed")
        _version, root = self._keyring.resolve_version(
            project_id=reference.project_id,
            storage_tier=_storage_tier(reference.kind),
            version=version,
        )
        key = _derived_key(
            root.reveal_bytes(),
            project_id=reference.project_id,
            artifact_id=reference.artifact_id,
            kind=reference.kind,
            plaintext_hash=plaintext_hash,
        )
        try:
            try:
                plaintext = AESGCM(bytes(key)).decrypt(
                    encrypted[:12],
                    encrypted[12:],
                    _aad(header, reference.project_id, reference.artifact_id, reference.kind),
                )
            except InvalidTag as error:
                raise SyntheticLabContractError(
                    "manual import artifact authentication failed"
                ) from error
        finally:
            _wipe(key)
        if hashlib.sha256(plaintext).hexdigest() != plaintext_hash:
            raise SyntheticLabContractError("manual import artifact plaintext changed")
        return bytearray(plaintext)

    def delete(self, reference: ManualImportArtifactRef) -> None:
        self._objects.delete_s3_uri(uri=reference.uri)


def _storage_tier(kind: ManualImportArtifactKind) -> ArtifactStorageTier:
    if kind is ManualImportArtifactKind.TEMPORARY_UPLOAD:
        return ArtifactStorageTier.ENCRYPTED_RAW
    return ArtifactStorageTier.DERIVED_PROJECT


def _header(version: str, plaintext_hash: str) -> bytes:
    return _PREFIX + version.encode("ascii") + b"\x00" + plaintext_hash.encode("ascii") + b"\x00"


def _parse_envelope(envelope: bytes) -> tuple[str, str, bytes, bytes]:
    if not envelope.startswith(_PREFIX):
        raise SyntheticLabContractError("manual import artifact envelope is invalid")
    offset = len(_PREFIX)
    version_end = envelope.find(b"\x00", offset)
    hash_end = envelope.find(b"\x00", version_end + 1)
    if version_end <= offset or hash_end <= version_end or len(envelope) <= hash_end + 29:
        raise SyntheticLabContractError("manual import artifact envelope is truncated")
    try:
        version = envelope[offset:version_end].decode("ascii")
        plaintext_hash = envelope[version_end + 1 : hash_end].decode("ascii")
    except UnicodeDecodeError as error:
        raise SyntheticLabContractError("manual import artifact header is invalid") from error
    _require_hash(plaintext_hash, "manual import artifact plaintext")
    return version, plaintext_hash, envelope[: hash_end + 1], envelope[hash_end + 1 :]


def _derived_key(
    root_key: bytes,
    *,
    project_id: UUID,
    artifact_id: UUID,
    kind: ManualImportArtifactKind,
    plaintext_hash: str,
) -> bytearray:
    return bytearray(
        HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_KDF_SALT,
            info=(
                project_id.bytes + artifact_id.bytes + kind.value.encode("ascii")
                + bytes.fromhex(plaintext_hash)
            ),
        ).derive(root_key)
    )


def _aad(
    header: bytes,
    project_id: UUID,
    artifact_id: UUID,
    kind: ManualImportArtifactKind,
) -> bytes:
    return header + project_id.bytes + artifact_id.bytes + kind.value.encode("ascii")


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = [
    "EncryptedManualImportArtifactStore",
    "MANUAL_IMPORT_ENCRYPTED_MEDIA_TYPE",
    "ManualImportArtifactKind",
    "ManualImportArtifactRef",
    "ManualImportObjectStore",
]
