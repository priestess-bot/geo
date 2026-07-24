from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest

from geo_core.synthetic_lab.artifact_keyring import (
    ArtifactKeyringConfigurationError,
    load_synthetic_artifact_keyring,
)
from geo_core.synthetic_lab.raw_artifact_governance import ArtifactStorageTier
from geo_style_worker.preflight import _validate_artifact_keyring


def _write_keyring(path, *, active: str = "1", key: bytes = b"k" * 32) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_version": active,
                "keys": {active: base64.b64encode(key).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_keyring_derives_distinct_project_and_tier_keys(tmp_path) -> None:
    path = tmp_path / "synthetic-artifact-keyring.json"
    _write_keyring(path)
    keyring = load_synthetic_artifact_keyring(path)
    first_project = uuid4()

    version, raw = keyring.resolve(
        project_id=first_project,
        storage_tier=ArtifactStorageTier.ENCRYPTED_RAW,
    )
    _, derived = keyring.resolve(
        project_id=first_project,
        storage_tier=ArtifactStorageTier.DERIVED_PROJECT,
    )
    _, other_project = keyring.resolve(
        project_id=uuid4(),
        storage_tier=ArtifactStorageTier.ENCRYPTED_RAW,
    )

    assert version == "1"
    assert len(raw.reveal_bytes()) == 32
    assert raw.reveal_bytes() != derived.reveal_bytes()
    assert raw.reveal_bytes() != other_project.reveal_bytes()
    assert "kkkk" not in repr(keyring)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": 1, "active_version": "v1", "keys": {}},
        {
            "schema_version": 1,
            "active_version": "v1",
            "keys": {"v1": base64.b64encode(b"short").decode("ascii")},
        },
        {"schema_version": 1, "active_version": "v1", "keys": {"v1": "%%%"}},
    ],
)
def test_keyring_rejects_incomplete_or_invalid_material(tmp_path, payload) -> None:
    path = tmp_path / "synthetic-artifact-keyring.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ArtifactKeyringConfigurationError):
        load_synthetic_artifact_keyring(path)


def test_historical_key_versions_remain_resolvable(tmp_path) -> None:
    path = tmp_path / "synthetic-artifact-keyring.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_version": "2",
                "keys": {
                    "1": base64.b64encode(b"a" * 32).decode("ascii"),
                    "2": base64.b64encode(b"b" * 32).decode("ascii"),
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    keyring = load_synthetic_artifact_keyring(path)

    version, secret = keyring.resolve_version(
        project_id=uuid4(),
        storage_tier=ArtifactStorageTier.DERIVED_PROJECT,
        version="1",
    )

    assert version == "1"
    assert len(secret.reveal_bytes()) == 32


def test_missing_keyring_fails_closed(tmp_path) -> None:
    with pytest.raises(ArtifactKeyringConfigurationError, match="cannot be read"):
        load_synthetic_artifact_keyring(tmp_path / "missing.json")


def test_runtime_rejects_artifact_keyring_aliased_to_secret_store_keyring(tmp_path) -> None:
    path = tmp_path / "shared-keyring.json"
    _write_keyring(path)

    with pytest.raises(RuntimeError, match="must be independent"):
        _validate_artifact_keyring(path, path)


def test_keyring_rejects_reused_material_across_versions(tmp_path) -> None:
    material = base64.b64encode(b"same-key-material".ljust(32, b"x")).decode("ascii")
    path = tmp_path / "synthetic-artifact-keyring.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_version": "2",
                "keys": {"1": material, "2": material},
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)

    with pytest.raises(ArtifactKeyringConfigurationError, match="reuse key material"):
        load_synthetic_artifact_keyring(path)
