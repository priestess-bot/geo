"""Initialize or verify the Workflow C artifact keyring during staging migration.

The shared Worker is intentionally read-only for this global keyring.  An
operator-controlled migration step provisions its immutable canaries before
the Worker begins to consume durable jobs.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from geo_core.workflow_c_artifacts.postgres import (
    synchronize_workflow_c_artifact_master_keys,
)


def bootstrap(*, database_url: str, keyring_path: str | Path) -> tuple[int, ...]:
    """Synchronize canaries transactionally without exposing key material."""

    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        try:
            versions = synchronize_workflow_c_artifact_master_keys(connection, cipher)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    return versions


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    versions = bootstrap(
        database_url=_required("GEO_DATABASE_URL"),
        keyring_path=_required("GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE"),
    )
    print(f"Workflow C artifact keyring bootstrap verified {len(versions)} key version(s).")


if __name__ == "__main__":
    main()
