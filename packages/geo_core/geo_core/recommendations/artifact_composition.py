"""Explicit production composition for Recommendation task artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from os import PathLike
from typing import Any

from geo_core.recommendations.artifact_keyring_postgres import (
    synchronize_recommendation_artifact_key_canaries,
)
from geo_core.recommendations.generation_artifacts import (
    EncryptedRecommendationTaskArtifactStore,
    RecommendationTaskObjectStore,
)
from geo_core.secrets import (
    EnvelopeCipher,
    load_master_keyring_from_docker_secret,
)


@dataclass(frozen=True)
class RecommendationArtifactComposition:
    artifacts: EncryptedRecommendationTaskArtifactStore
    cipher: EnvelopeCipher
    verified_master_key_versions: tuple[int, ...]


def build_recommendation_artifact_composition(
    *,
    connection_factory: Callable[[], Any],
    object_store: RecommendationTaskObjectStore,
    keyring_path: str | PathLike[str],
) -> RecommendationArtifactComposition:
    """Load one independent keyring and fail before worker readiness on canary drift."""

    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    connection = connection_factory()
    try:
        versions = synchronize_recommendation_artifact_key_canaries(
            connection,
            cipher=cipher,
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return RecommendationArtifactComposition(
        artifacts=EncryptedRecommendationTaskArtifactStore(
            object_store=object_store,
            cipher=cipher,
        ),
        cipher=cipher,
        verified_master_key_versions=versions,
    )


__all__ = [
    "RecommendationArtifactComposition",
    "build_recommendation_artifact_composition",
]
