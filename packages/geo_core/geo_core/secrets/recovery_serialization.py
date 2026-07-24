"""Strict canonical serialization for authenticated keyring snapshots."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable
from datetime import datetime
import hmac
import json
from typing import Any, Mapping
from uuid import UUID

from .crypto import MasterKeyring
from .errors import (
    SecretConfigurationError,
    SecretContractError,
    SecretSnapshotIntegrityError,
)
from .models import EncryptedSecretVersion, MasterKeyCanary, SecretVersionHandle
from .recovery_contracts import (
    KEYRING_COMMIT_FORMAT,
    KEYRING_PAYLOAD_FORMAT,
    AuthenticatedKeyringSnapshot,
    KeyringSnapshotManifest,
    RepresentativeCanaryDescriptor,
    RepresentativeSecretCanary,
    _canonical_datetime,
    _canonical_json,
    _encode_base64,
)


def parse_snapshot_manifest(raw: bytes) -> KeyringSnapshotManifest:
    try:
        payload = _load_json_object(raw)
        expected = {
            "format",
            "snapshot_id",
            "created_at",
            "algorithm",
            "escrow_key_id",
            "storage_domain",
            "data_backup_reference",
            "active_key_version",
            "key_versions",
            "canary_versions",
            "representative_canaries",
            "nonce",
            "ciphertext_size",
            "ciphertext_sha256",
        }
        if set(payload) != expected:
            raise ValueError
        created_at = datetime.fromisoformat(_required_string(payload, "created_at"))
        if _canonical_datetime(created_at) != payload["created_at"]:
            raise ValueError
        representatives_raw = payload["representative_canaries"]
        if not isinstance(representatives_raw, list):
            raise ValueError
        descriptors: list[RepresentativeCanaryDescriptor] = []
        for item in representatives_raw:
            if not isinstance(item, dict) or set(item) != {"id", "kind", "master_key_version"}:
                raise ValueError
            descriptors.append(
                RepresentativeCanaryDescriptor(
                    id=UUID(_required_string(item, "id")),
                    kind=_required_string(item, "kind"),
                    master_key_version=_required_int(item, "master_key_version"),
                )
            )
        return KeyringSnapshotManifest(
            snapshot_id=UUID(_required_string(payload, "snapshot_id")),
            created_at=created_at,
            escrow_key_id=_required_string(payload, "escrow_key_id"),
            data_backup_reference=_required_string(payload, "data_backup_reference"),
            active_key_version=_required_int(payload, "active_key_version"),
            key_versions=_int_tuple(payload, "key_versions"),
            canary_versions=_int_tuple(payload, "canary_versions"),
            representative_canaries=tuple(descriptors),
            nonce=_decode_base64(_required_string(payload, "nonce")),
            ciphertext_size=_required_int(payload, "ciphertext_size"),
            ciphertext_sha256=_required_string(payload, "ciphertext_sha256"),
            format=_required_string(payload, "format"),
            algorithm=_required_string(payload, "algorithm"),
            storage_domain=_required_string(payload, "storage_domain"),
        )
    except (ValueError, TypeError, binascii.Error, SecretContractError):
        raise SecretSnapshotIntegrityError("keyring snapshot manifest is invalid") from None


def snapshot_commit_bytes(snapshot: AuthenticatedKeyringSnapshot) -> bytes:
    return _canonical_json(
        {
            "format": KEYRING_COMMIT_FORMAT,
            "snapshot_id": str(snapshot.manifest.snapshot_id),
            "manifest_sha256": snapshot.manifest.manifest_sha256,
            "ciphertext_sha256": snapshot.manifest.ciphertext_sha256,
        }
    )


def verify_snapshot_commit(
    *,
    snapshot_id: UUID,
    manifest: KeyringSnapshotManifest,
    raw: bytes,
) -> None:
    try:
        payload = _load_json_object(raw)
        if set(payload) != {
            "format",
            "snapshot_id",
            "manifest_sha256",
            "ciphertext_sha256",
        }:
            raise ValueError
        if (
            payload["format"] != KEYRING_COMMIT_FORMAT
            or payload["snapshot_id"] != str(snapshot_id)
            or not hmac.compare_digest(
                _required_string(payload, "manifest_sha256"),
                manifest.manifest_sha256,
            )
            or not hmac.compare_digest(
                _required_string(payload, "ciphertext_sha256"),
                manifest.ciphertext_sha256,
            )
        ):
            raise ValueError
        if not hmac.compare_digest(raw, snapshot_commit_bytes_for(manifest)):
            raise ValueError
    except (ValueError, TypeError):
        raise SecretSnapshotIntegrityError("keyring snapshot commit is invalid") from None


def snapshot_commit_bytes_for(manifest: KeyringSnapshotManifest) -> bytes:
    return _canonical_json(
        {
            "format": KEYRING_COMMIT_FORMAT,
            "snapshot_id": str(manifest.snapshot_id),
            "manifest_sha256": manifest.manifest_sha256,
            "ciphertext_sha256": manifest.ciphertext_sha256,
        }
    )


def encode_keyring_payload(
    *,
    keyring: MasterKeyring,
    master_canaries: tuple[MasterKeyCanary, ...],
    representative_canaries: tuple[RepresentativeSecretCanary, ...],
) -> bytes:
    return _canonical_json(
        {
            "format": KEYRING_PAYLOAD_FORMAT,
            "active_key_version": keyring.active_version,
            "keys": [
                {"version": version, "material": _encode_base64(material)}
                for version, material in keyring._items_for_escrow()
            ],
            "master_key_canaries": [_encode_master_canary(item) for item in master_canaries],
            "representative_secret_canaries": [
                _encode_representative_canary(item) for item in representative_canaries
            ],
        }
    )


def decode_keyring_payload(
    raw: bytes,
) -> tuple[
    MasterKeyring,
    tuple[MasterKeyCanary, ...],
    tuple[RepresentativeSecretCanary, ...],
]:
    try:
        payload = _load_json_object(raw)
        if set(payload) != {
            "format",
            "active_key_version",
            "keys",
            "master_key_canaries",
            "representative_secret_canaries",
        } or payload["format"] != KEYRING_PAYLOAD_FORMAT:
            raise ValueError
        keys_raw = _required_list(payload, "keys")
        keys: dict[int, bytes] = {}
        for item in keys_raw:
            if not isinstance(item, dict) or set(item) != {"version", "material"}:
                raise ValueError
            version = _required_int(item, "version")
            if version in keys:
                raise ValueError
            keys[version] = _decode_base64(_required_string(item, "material"))
        keyring = MasterKeyring(
            keys=keys,
            active_version=_required_int(payload, "active_key_version"),
        )
        master_canaries = tuple(
            _decode_master_canary(item)
            for item in _required_list(payload, "master_key_canaries")
        )
        representatives = _ordered_representatives(
            _decode_representative_canary(item)
            for item in _required_list(payload, "representative_secret_canaries")
        )
        return keyring, master_canaries, representatives
    except (ValueError, TypeError, binascii.Error, SecretConfigurationError, SecretContractError):
        raise SecretSnapshotIntegrityError("keyring snapshot payload is invalid") from None


def _encode_master_canary(canary: MasterKeyCanary) -> dict[str, object]:
    return {
        "master_key_version": canary.master_key_version,
        "algorithm": canary.algorithm,
        "nonce": _encode_base64(canary.nonce),
        "ciphertext": _encode_base64(canary.ciphertext),
    }


def _decode_master_canary(value: object) -> MasterKeyCanary:
    if not isinstance(value, dict) or set(value) != {
        "master_key_version",
        "algorithm",
        "nonce",
        "ciphertext",
    }:
        raise ValueError
    return MasterKeyCanary(
        master_key_version=_required_int(value, "master_key_version"),
        algorithm=_required_string(value, "algorithm"),
        nonce=_decode_base64(_required_string(value, "nonce")),
        ciphertext=_decode_base64(_required_string(value, "ciphertext")),
    )


def _encode_representative_canary(canary: RepresentativeSecretCanary) -> dict[str, object]:
    envelope = canary.envelope
    handle = envelope.handle
    return {
        "id": str(canary.id),
        "kind": canary.kind,
        "envelope": {
            "reference_id": str(handle.reference_id),
            "project_id": str(handle.project_id),
            "purpose": handle.purpose,
            "version": handle.version,
            "ciphertext": _encode_base64(envelope.ciphertext),
            "data_nonce": _encode_base64(envelope.data_nonce),
            "wrapped_data_key": _encode_base64(envelope.wrapped_data_key),
            "wrap_nonce": _encode_base64(envelope.wrap_nonce),
            "master_key_version": envelope.master_key_version,
            "created_at": _canonical_datetime(envelope.created_at),
            "algorithm": envelope.algorithm,
        },
    }


def _decode_representative_canary(value: object) -> RepresentativeSecretCanary:
    if not isinstance(value, dict) or set(value) != {"id", "kind", "envelope"}:
        raise ValueError
    envelope_raw = value["envelope"]
    if not isinstance(envelope_raw, dict) or set(envelope_raw) != {
        "reference_id",
        "project_id",
        "purpose",
        "version",
        "ciphertext",
        "data_nonce",
        "wrapped_data_key",
        "wrap_nonce",
        "master_key_version",
        "created_at",
        "algorithm",
    }:
        raise ValueError
    created_at = datetime.fromisoformat(_required_string(envelope_raw, "created_at"))
    if _canonical_datetime(created_at) != envelope_raw["created_at"]:
        raise ValueError
    handle = SecretVersionHandle(
        reference_id=UUID(_required_string(envelope_raw, "reference_id")),
        project_id=UUID(_required_string(envelope_raw, "project_id")),
        purpose=_required_string(envelope_raw, "purpose"),
        version=_required_int(envelope_raw, "version"),
    )
    envelope = EncryptedSecretVersion(
        handle=handle,
        ciphertext=_decode_base64(_required_string(envelope_raw, "ciphertext")),
        data_nonce=_decode_base64(_required_string(envelope_raw, "data_nonce")),
        wrapped_data_key=_decode_base64(_required_string(envelope_raw, "wrapped_data_key")),
        wrap_nonce=_decode_base64(_required_string(envelope_raw, "wrap_nonce")),
        master_key_version=_required_int(envelope_raw, "master_key_version"),
        created_at=created_at,
        algorithm=_required_string(envelope_raw, "algorithm"),
    )
    return RepresentativeSecretCanary(
        id=UUID(_required_string(value, "id")),
        kind=_required_string(value, "kind"),
        envelope=envelope,
    )


def _ordered_representatives(
    values: Iterable[RepresentativeSecretCanary],
) -> tuple[RepresentativeSecretCanary, ...]:
    ordered = tuple(sorted(values, key=lambda item: (item.kind, str(item.id))))
    keys = tuple((item.kind, item.id) for item in ordered)
    if not ordered or len(keys) != len(set(keys)):
        raise SecretConfigurationError("representative secret canaries must be unique")
    return ordered


def _load_json_object(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError
    return item


def _required_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError
    return item


def _required_list(value: Mapping[str, object], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ValueError
    return item


def _int_tuple(value: Mapping[str, object], key: str) -> tuple[int, ...]:
    return tuple(_required_int({"value": item}, "value") for item in _required_list(value, key))


def _decode_base64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)
