from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import cast

import pytest

from geo_core.recommendations import artifact_composition
from geo_core.recommendations.generation_artifacts import (
    EncryptedRecommendationTaskArtifactStore,
    RecommendationTaskObjectStore,
)


class _Connection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def test_builder_loads_dedicated_keyring_and_commits_verified_canaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyring = _write_keyring(tmp_path / "recommendation-artifact-keyring.json")
    connection = _Connection()
    observed_versions: list[tuple[int, ...]] = []

    def synchronize(candidate, *, cipher):
        assert candidate is connection
        observed_versions.append(cipher.master_key_versions)
        return cipher.master_key_versions

    monkeypatch.setattr(
        artifact_composition,
        "synchronize_recommendation_artifact_key_canaries",
        synchronize,
    )

    built = artifact_composition.build_recommendation_artifact_composition(
        connection_factory=lambda: connection,
        object_store=cast(RecommendationTaskObjectStore, object()),
        keyring_path=keyring,
    )

    assert isinstance(built.artifacts, EncryptedRecommendationTaskArtifactStore)
    assert built.verified_master_key_versions == (1, 2)
    assert built.cipher.active_master_key_version == 2
    assert observed_versions == [(1, 2)]
    assert (connection.commits, connection.rollbacks, connection.closes) == (1, 0, 1)


def test_builder_rolls_back_and_closes_when_canary_verification_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyring = _write_keyring(tmp_path / "recommendation-artifact-keyring.json")
    connection = _Connection()

    def reject(_candidate, *, cipher):
        assert cipher.active_master_key_version == 2
        raise RuntimeError("canary mismatch")

    monkeypatch.setattr(
        artifact_composition,
        "synchronize_recommendation_artifact_key_canaries",
        reject,
    )

    with pytest.raises(RuntimeError, match="canary mismatch"):
        artifact_composition.build_recommendation_artifact_composition(
            connection_factory=lambda: connection,
            object_store=cast(RecommendationTaskObjectStore, object()),
            keyring_path=keyring,
        )

    assert (connection.commits, connection.rollbacks, connection.closes) == (0, 1, 1)


def _write_keyring(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "active_version": 2,
                "keys": {
                    "1": base64.b64encode(b"r" * 32).decode("ascii"),
                    "2": base64.b64encode(b"R" * 32).decode("ascii"),
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path
