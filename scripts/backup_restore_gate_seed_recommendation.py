"""Recommendation artifact key-canary fixture for the authenticated restore Gate."""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from geo_core.recommendations.artifact_keyring_postgres import (
    synchronize_recommendation_artifact_key_canaries,
)
from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from scripts.backup_restore_gate_seed_common import RestoreGateSeedError


def seed_recommendation_artifact_key_canaries(
    *, database_url: str, keyring_path: Path
) -> dict[str, object]:
    """Create two independently-restorable Recommendation artifact key canaries.

    The gate intentionally does not manufacture a Recommendation generation run.
    It proves keyring recovery even when no approved Recommendation task artifact
    is eligible to exist yet; production restores additionally verify a real task
    whenever active lineage is present.
    """

    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        versions = synchronize_recommendation_artifact_key_canaries(
            connection, cipher=cipher
        )
        connection.commit()
    if versions != (1, 2):
        raise RestoreGateSeedError(
            "Recommendation artifact seed key-canary coverage is incomplete"
        )
    return {
        "active_master_key_version": cipher.active_master_key_version,
        "artifact_lineage_count": 0,
        "master_key_version_count": len(versions),
        "representative_artifact_verified": False,
    }


__all__ = ["seed_recommendation_artifact_key_canaries"]
