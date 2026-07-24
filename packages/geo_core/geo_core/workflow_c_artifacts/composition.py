"""Production composition for the independent Workflow C artifact domain."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from os import PathLike
from pathlib import Path
from typing import Any

from geo_core.object_store import S3CompatibleObjectStore
from geo_core.workflow_c_artifacts.postgres import (
    PostgresWorkflowCArtifactKeyVault,
    PostgresWorkflowCManualArtifactRepository,
    synchronize_workflow_c_artifact_master_keys,
    verify_workflow_c_artifact_keyring_canary_rows,
    verify_workflow_c_artifact_keyring_canaries,
)
from geo_core.sampling.manual_artifact_storage import (
    IndependentWorkflowCArtifactEncryptor,
    MinioWorkflowCManualArtifactWriter,
)
from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from geo_core.workflow_c_artifacts.reader import PostgresWorkflowCManualArtifactReader
from geo_core.workflow_c_artifacts.lifecycle import (
    WorkflowCArtifactMaintenanceService,
)
from geo_core.workflow_c_artifacts.postgres_lifecycle import (
    PostgresWorkflowCArtifactLifecycleRepository,
)


WORKFLOW_C_RESTRICTED_BUCKET = "geo-restricted-workflow-c-artifacts"


@dataclass(frozen=True)
class WorkflowCArtifactComposition:
    writer: MinioWorkflowCManualArtifactWriter
    cipher: EnvelopeCipher
    object_store: S3CompatibleObjectStore
    verified_master_key_versions: tuple[int, ...]


@dataclass(frozen=True)
class WorkflowCArtifactReaderComposition:
    reader: PostgresWorkflowCManualArtifactReader
    cipher: EnvelopeCipher
    object_store: S3CompatibleObjectStore
    verified_master_key_versions: tuple[int, ...]


@dataclass(frozen=True)
class WorkflowCArtifactMaintenanceComposition:
    service: WorkflowCArtifactMaintenanceService
    object_store: S3CompatibleObjectStore


def build_workflow_c_artifact_composition(
    *,
    connection_factory: Callable[[], Any],
    keyring_path: str | PathLike[str],
    environment: Mapping[str, str] | None = None,
    retention_days: int = 90,
) -> WorkflowCArtifactComposition:
    """Fail readiness unless canaries and the restricted object principal are valid."""

    values = os.environ if environment is None else environment
    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    connection = connection_factory()
    try:
        versions = synchronize_workflow_c_artifact_master_keys(connection, cipher)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    store = build_workflow_c_artifact_object_store(values)
    vault = PostgresWorkflowCArtifactKeyVault(
        connect=connection_factory,
        cipher=cipher,
        synchronize=False,
    )
    return WorkflowCArtifactComposition(
        writer=MinioWorkflowCManualArtifactWriter(
            object_store=store,
            encryptor=IndependentWorkflowCArtifactEncryptor(vault),
            repository=PostgresWorkflowCManualArtifactRepository(
                connect=connection_factory
            ),
            retention_days=retention_days,
        ),
        cipher=cipher,
        object_store=store,
        verified_master_key_versions=versions,
    )


def build_workflow_c_artifact_api_writer_composition(
    *,
    connection_factory: Callable[[], Any],
    keyring_path: str | PathLike[str],
    environment: Mapping[str, str] | None = None,
    retention_days: int = 90,
) -> WorkflowCArtifactComposition:
    """Build the restricted App writer without master-key-table read rights.

    The Worker registers and synchronizes canaries.  The App verifies them
    through a read-only SECURITY DEFINER projection, then uses existing
    project-RLS rights for DEKs and governed artifact staging.
    """

    values = os.environ if environment is None else environment
    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    connection = connection_factory()
    try:
        connection.execute("SET TRANSACTION READ ONLY")
        rows = tuple(
            connection.execute(
                """SELECT master_key_version, status, algorithm,
                          canary_nonce, canary_ciphertext, retired_at
                     FROM geo_read_workflow_c_artifact_keyring_canaries()"""
            ).fetchall()
        )
        versions = verify_workflow_c_artifact_keyring_canary_rows(cipher, rows)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    store = build_workflow_c_artifact_object_store(values)
    vault = PostgresWorkflowCArtifactKeyVault(
        connect=connection_factory,
        cipher=cipher,
        synchronize=False,
    )
    return WorkflowCArtifactComposition(
        writer=MinioWorkflowCManualArtifactWriter(
            object_store=store,
            encryptor=IndependentWorkflowCArtifactEncryptor(vault),
            repository=PostgresWorkflowCManualArtifactRepository(
                connect=connection_factory
            ),
            retention_days=retention_days,
        ),
        cipher=cipher,
        object_store=store,
        verified_master_key_versions=versions,
    )


def build_workflow_c_artifact_object_store(
    environment: Mapping[str, str] | None = None,
) -> S3CompatibleObjectStore:
    values = os.environ if environment is None else environment
    return _build_restricted_object_store(
        values=values,
        prefix="GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE",
    )


def build_workflow_c_artifact_reader_composition(
    *,
    connection_factory: Callable[[], Any],
    keyring_path: str | PathLike[str],
    environment: Mapping[str, str] | None = None,
) -> WorkflowCArtifactReaderComposition:
    values = os.environ if environment is None else environment
    cipher = EnvelopeCipher(load_master_keyring_from_docker_secret(keyring_path))
    connection = connection_factory()
    try:
        connection.execute("SET TRANSACTION READ ONLY")
        versions = verify_workflow_c_artifact_keyring_canaries(connection, cipher)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    store = _build_restricted_object_store(
        values=values,
        prefix="GEO_WORKFLOW_C_ARTIFACT_READER",
    )
    return WorkflowCArtifactReaderComposition(
        reader=PostgresWorkflowCManualArtifactReader(
            connect=connection_factory,
            cipher=cipher,
            object_store=store,
        ),
        cipher=cipher,
        object_store=store,
        verified_master_key_versions=versions,
    )


def build_workflow_c_artifact_maintenance_composition(
    *,
    connection_factory: Callable[[], Any],
    worker_id: str,
    environment: Mapping[str, str] | None = None,
    deletion_lease_seconds: int = 120,
    max_deletions: int = 100,
) -> WorkflowCArtifactMaintenanceComposition:
    """Build the deletion-only worker without a decrypt-capable keyring.

    The lifecycle repository invokes a fenced database command which destroys
    the DEK and persists its receipt before this worker can touch MinIO.  This
    process therefore needs only the restricted deleter principal; mounting a
    master keyring here would create an unnecessary post-erasure recovery path.
    """

    values = os.environ if environment is None else environment
    store = _build_restricted_object_store(
        values=values,
        prefix="GEO_WORKFLOW_C_ARTIFACT_DELETER",
    )
    return WorkflowCArtifactMaintenanceComposition(
        service=WorkflowCArtifactMaintenanceService(
            repository=PostgresWorkflowCArtifactLifecycleRepository(
                connect=connection_factory
            ),
            object_store=store,
            worker_id=worker_id,
            deletion_lease_seconds=deletion_lease_seconds,
            max_deletions=max_deletions,
        ),
        object_store=store,
    )
def _build_restricted_object_store(
    *, values: Mapping[str, str], prefix: str
) -> S3CompatibleObjectStore:
    bucket = values.get(f"{prefix}_BUCKET", WORKFLOW_C_RESTRICTED_BUCKET).strip()
    if bucket != WORKFLOW_C_RESTRICTED_BUCKET:
        raise RuntimeError("Workflow C artifact bucket must be the restricted bucket")
    if values.get(f"{prefix}_ACCESS_KEY", "").strip() or values.get(
        f"{prefix}_SECRET_KEY", ""
    ).strip():
        raise RuntimeError("Workflow C object credentials must use Docker Secret files")
    return S3CompatibleObjectStore(
        endpoint=values.get(f"{prefix}_ENDPOINT", "").strip(),
        bucket=bucket,
        access_key=_read_secret_file(values, f"{prefix}_ACCESS_KEY_FILE"),
        secret_key=_read_secret_file(values, f"{prefix}_SECRET_KEY_FILE"),
        region=values.get(f"{prefix}_REGION", "us-east-1").strip(),
        auto_create_bucket=False,
    )


def _read_secret_file(values: Mapping[str, str], field: str) -> str:
    path = values.get(field, "").strip()
    if not path:
        raise RuntimeError(f"{field} is required")
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"{field} cannot be read") from exc
    if not value:
        raise RuntimeError(f"{field} is empty")
    return value


__all__ = [
    "WORKFLOW_C_RESTRICTED_BUCKET",
    "WorkflowCArtifactComposition",
    "WorkflowCArtifactMaintenanceComposition",
    "WorkflowCArtifactReaderComposition",
    "build_workflow_c_artifact_composition",
    "build_workflow_c_artifact_api_writer_composition",
    "build_workflow_c_artifact_maintenance_composition",
    "build_workflow_c_artifact_object_store",
    "build_workflow_c_artifact_reader_composition",
]
