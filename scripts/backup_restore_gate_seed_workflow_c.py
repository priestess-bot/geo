"""Workflow C artifact-key canary fixture for authenticated restore gates."""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from geo_core.workflow_c_artifacts.postgres import (
    synchronize_workflow_c_artifact_master_keys,
)


def seed_workflow_c_artifact_key_canaries(
    *,
    database_url: str,
    keyring_path: Path,
) -> dict[str, int]:
    """Persist every independent Workflow C key canary before backup.

    No manual-UI artifact is fabricated here: the domain's empty-state restore
    verifier is itself meaningful only after its current key history has been
    restored. The restricted bucket is nevertheless created by the Gate so the
    archive proves that all artifact domains participate in the restore set.
    """

    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        versions = synchronize_workflow_c_artifact_master_keys(connection, cipher)
        row = connection.execute(
            """SELECT count(*) AS count
               FROM workflow_c_artifact_master_key_versions
               WHERE status <> 'retired'"""
        ).fetchone()
    if row is None or int(row["count"]) != len(versions):
        raise RuntimeError("Workflow C artifact key canary coverage is incomplete")
    return {"master_key_version_count": len(versions)}


__all__ = ["seed_workflow_c_artifact_key_canaries"]
