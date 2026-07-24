"""One-shot verification of every application encryption domain after restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Never
from urllib.parse import quote
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.model_gateway.artifact_restore import verify_provider_artifact_restore
from geo_core.model_gateway.postgres_artifacts import load_provider_artifact_keyring
from geo_core.object_store import RetrievedObject, parse_s3_uri
from geo_core.recommendations.artifact_keyring_postgres import verify_recommendation_artifact_restore
from geo_core.recommendations.generation_artifacts import (
    EncryptedRecommendationTaskArtifactStore,
)
from geo_core.restored_object_reader import (
    VerifiedRestoredObjectReader,
    VerifiedRestoredObjectReaders,
)
from geo_core.secrets import (
    EnvelopeCipher,
    ResolveSecretCommand,
    SecretActorRole,
    SecretPrincipal,
    SecretRequestHasher,
    SecretSurface,
    SecretVersionHandle,
    load_master_keyring_from_docker_secret,
)
from geo_core.secrets.postgres import build_secret_store_postgres_runtime, verify_secret_store_restore
from geo_core.secrets.postgres_config import load_postgres_crypto_config
from geo_core.synthetic_lab.artifact_keyring import load_synthetic_artifact_keyring
from geo_core.synthetic_lab.artifact_keyring_postgres import verify_synthetic_artifact_recovery
from geo_core.workflow_c_artifacts.postgres import verify_workflow_c_artifact_restore
from geo_worker.backup_restore_probe_payload import (
    ApplicationKeyRecoveryError,
    PROBE_SCHEMA as _PROBE_SCHEMA,
    SecretRuntimeRestoreVerification,
    build_probe_payload,
)


_DATABASE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
_MAX_PASSWORD_BYTES = 4096
_RECOMMENDATION_ARTIFACT_BUCKET = "geo-restricted-recommendation-artifacts"
_SYNTHETIC_RAW_BUCKET = "geo-synthetic-style-raw"
_SYNTHETIC_DERIVED_BUCKET = "geo-synthetic-style-derived"

# Kept here for the established probe import surface.
PROBE_SCHEMA = _PROBE_SCHEMA


class _ReadOnlyProviderObjectStore:
    def __init__(self, reader: VerifiedRestoredObjectReader) -> None:
        self._reader = reader

    def get_s3_uri(
        self, *, uri: str, expected_hash: str | None = None
    ) -> RetrievedObject:
        if expected_hash is None:
            raise ApplicationKeyRecoveryError("restore object checksum is required")
        payload = self._reader(uri, expected_hash)
        bucket, key = parse_s3_uri(uri)
        return RetrievedObject(
            content=payload,
            bucket=bucket,
            key=key,
            content_type="application/octet-stream",
            content_hash=hashlib.sha256(payload).hexdigest(),
            etag=None,
        )

    def uri_for_key(self, key: str) -> str:
        del key
        _read_only_rejected()

    def put_object(
        self,
        *,
        key: str,
        content: str | bytes,
        content_type: str,
        expected_hash: str | None = None,
    ) -> Never:
        del key, content, content_type, expected_hash
        _read_only_rejected()

    def delete_s3_uri(self, *, uri: str) -> Never:
        del uri
        _read_only_rejected()


def run_probe(
    *,
    database_url: str,
    secret_store_keyring: Path,
    secret_store_request_hash_key: Path,
    secret_store_service_identity_id: UUID,
    secret_store_frozen_handle: SecretVersionHandle,
    secret_store_resolve_idempotency_key: str,
    provider_artifact_keyring: Path,
    synthetic_artifact_keyring: Path,
    recommendation_artifact_keyring: Path,
    workflow_c_artifact_keyring: Path,
    object_root: Path,
    object_bucket: str,
    recommendation_object_root: Path,
    recommendation_object_bucket: str,
    workflow_c_object_root: Path,
    workflow_c_object_bucket: str,
    synthetic_raw_object_root: Path,
    synthetic_raw_object_bucket: str,
    synthetic_derived_object_root: Path,
    synthetic_derived_object_bucket: str,
) -> dict[str, object]:
    if recommendation_object_bucket != _RECOMMENDATION_ARTIFACT_BUCKET:
        raise ApplicationKeyRecoveryError("Recommendation restore bucket is invalid")
    if recommendation_object_bucket == object_bucket:
        raise ApplicationKeyRecoveryError("Recommendation restore bucket is not isolated")
    reader = VerifiedRestoredObjectReader(root=object_root, bucket=object_bucket)
    provider_keyring = load_provider_artifact_keyring(provider_artifact_keyring)
    if provider_keyring is None:
        raise ApplicationKeyRecoveryError("Provider artifact keyring is unavailable")
    provider_cipher = EnvelopeCipher(provider_keyring)
    synthetic_keyring = load_synthetic_artifact_keyring(synthetic_artifact_keyring)
    if (
        synthetic_raw_object_bucket != _SYNTHETIC_RAW_BUCKET
        or synthetic_derived_object_bucket != _SYNTHETIC_DERIVED_BUCKET
    ):
        raise ApplicationKeyRecoveryError("Synthetic restore bucket identity is invalid")
    synthetic_reader = VerifiedRestoredObjectReaders(
        {
            _SYNTHETIC_RAW_BUCKET: VerifiedRestoredObjectReader(
                root=synthetic_raw_object_root,
                bucket=_SYNTHETIC_RAW_BUCKET,
            ),
            _SYNTHETIC_DERIVED_BUCKET: VerifiedRestoredObjectReader(
                root=synthetic_derived_object_root,
                bucket=_SYNTHETIC_DERIVED_BUCKET,
            ),
        }
    )
    recommendation_cipher = EnvelopeCipher(
        load_master_keyring_from_docker_secret(recommendation_artifact_keyring)
    )
    workflow_c_cipher = EnvelopeCipher(
        load_master_keyring_from_docker_secret(workflow_c_artifact_keyring)
    )
    workflow_c_objects = _ReadOnlyProviderObjectStore(
        VerifiedRestoredObjectReader(
            root=workflow_c_object_root,
            bucket=workflow_c_object_bucket,
        )
    )
    recommendation_objects = _ReadOnlyProviderObjectStore(
        VerifiedRestoredObjectReader(
            root=recommendation_object_root,
            bucket=recommendation_object_bucket,
        )
    )

    secret_result = verify_secret_store_restore(
        database_url=database_url,
        keyring_path=secret_store_keyring,
    )
    secret_runtime = _verify_frozen_secret_runtime(
        database_url=database_url,
        keyring_path=secret_store_keyring,
        request_hash_key_path=secret_store_request_hash_key,
        service_identity_id=secret_store_service_identity_id,
        handle=secret_store_frozen_handle,
        idempotency_key=secret_store_resolve_idempotency_key,
    )
    restored_objects = _ReadOnlyProviderObjectStore(reader)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        provider_result = verify_provider_artifact_restore(
            connection=connection,
            cipher=provider_cipher,
            object_store=restored_objects,
        )
        recommendation_result = verify_recommendation_artifact_restore(
            connection=connection,
            cipher=recommendation_cipher,
            artifacts=EncryptedRecommendationTaskArtifactStore(
                object_store=recommendation_objects,
                cipher=recommendation_cipher,
            ),
        )
        workflow_c_result = verify_workflow_c_artifact_restore(
            connection=connection,
            cipher=workflow_c_cipher,
            object_store=workflow_c_objects,
        )

    def synthetic_connection() -> object:
        connection = psycopg.connect(database_url)
        connection.execute("SET TRANSACTION READ ONLY")
        return connection

    synthetic_result = verify_synthetic_artifact_recovery(
        synthetic_connection,
        synthetic_keyring,
        object_reader=synthetic_reader,
    )
    return build_probe_payload(
        secret_store=secret_result,
        secret_runtime=secret_runtime,
        provider_artifacts=provider_result,
        synthetic_artifacts=synthetic_result,
        recommendation_artifacts=recommendation_result,
        workflow_c_artifacts=workflow_c_result,
    )


def _verify_frozen_secret_runtime(
    *,
    database_url: str,
    keyring_path: Path,
    request_hash_key_path: Path,
    service_identity_id: UUID,
    handle: SecretVersionHandle,
    idempotency_key: str,
) -> SecretRuntimeRestoreVerification:
    """Replay the pre-backup resolution receipt through the actual Postgres runtime.

    A ciphertext-only canary cannot establish that the independent request-HMAC
    survived restore.  The source Gate creates the exact resolve receipt first;
    a changed HMAC derives a different receipt key and is rejected before a
    plaintext value is requested.
    """

    config = load_postgres_crypto_config(
        master_keyring_path=keyring_path,
        request_hash_key_path=request_hash_key_path,
    )
    if config is None:
        raise ApplicationKeyRecoveryError("Secret Store runtime keys are unavailable")
    request_hash = SecretRequestHasher(config.request_hash_key).idempotency_key_hash(
        idempotency_key
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        service = connection.execute(
            "SELECT geo_require_active_service_identity(%s, %s) AS active",
            (service_identity_id, "restore_probe"),
        ).fetchone()
        if service is None or service["active"] is not True:
            raise ApplicationKeyRecoveryError("restore service identity is not active")
        receipt_count = _secret_resolution_receipt_count(
            connection, handle=handle, idempotency_key_hash=request_hash
        )
        audit_count = _secret_resolution_audit_count(
            connection, handle=handle, actor_id=service_identity_id
        )
    if receipt_count != 1 or audit_count != 1:
        raise ApplicationKeyRecoveryError(
            "frozen Secret Store resolution receipt or audit is unavailable"
        )

    runtime = build_secret_store_postgres_runtime(
        database_url=database_url,
        master_keyring_path=keyring_path,
        request_hash_key_path=request_hash_key_path,
    )
    if runtime is None:
        raise ApplicationKeyRecoveryError("Secret Store runtime is unavailable")
    value = runtime.application.resolve(
        ResolveSecretCommand(
            principal=SecretPrincipal(
                actor_id=service_identity_id,
                project_id=handle.project_id,
                role=SecretActorRole.SERVICE,
                surface=SecretSurface.WORKER,
            ),
            handle=handle,
            idempotency_key=idempotency_key,
        )
    )
    del value
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        after_receipts = _secret_resolution_receipt_count(
            connection, handle=handle, idempotency_key_hash=request_hash
        )
        after_audits = _secret_resolution_audit_count(
            connection, handle=handle, actor_id=service_identity_id
        )
    if after_receipts != receipt_count or after_audits != audit_count:
        raise ApplicationKeyRecoveryError("frozen Secret Store resolution did not replay")
    return SecretRuntimeRestoreVerification(
        audit_count=audit_count,
        receipt_count=receipt_count,
    )


def _secret_resolution_receipt_count(
    connection: psycopg.Connection[dict[str, object]],
    *,
    handle: SecretVersionHandle,
    idempotency_key_hash: str,
) -> int:
    row = connection.execute(
        """SELECT count(*) AS total
           FROM secret_command_receipts
           WHERE project_id = %s AND idempotency_key_hash = %s
             AND operation = 'resolve' AND reference_id = %s
             AND purpose = %s AND version = %s""",
        (
            handle.project_id,
            idempotency_key_hash,
            handle.reference_id,
            handle.purpose,
            handle.version,
        ),
    ).fetchone()
    return int(row["total"]) if row else 0


def _secret_resolution_audit_count(
    connection: psycopg.Connection[dict[str, object]],
    *,
    handle: SecretVersionHandle,
    actor_id: UUID,
) -> int:
    row = connection.execute(
        """SELECT count(*) AS total
           FROM secret_audit_events
           WHERE project_id = %s AND reference_id = %s AND purpose = %s
             AND version = %s AND actor_id = %s AND action = 'version_resolved'""",
        (
            handle.project_id,
            handle.reference_id,
            handle.purpose,
            handle.version,
            actor_id,
        ),
    ).fetchone()
    return int(row["total"]) if row else 0


def _database_url(args: argparse.Namespace) -> str:
    for value in (args.database_user, args.database_name):
        if _DATABASE_ID.fullmatch(value) is None:
            raise ApplicationKeyRecoveryError("restore database identity is invalid")
    if _HOST.fullmatch(args.database_host) is None or not 1 <= args.database_port <= 65535:
        raise ApplicationKeyRecoveryError("restore database endpoint is invalid")
    password = _read_password(args.database_password_file)
    return (
        f"postgresql://{quote(args.database_user, safe='')}:{quote(password, safe='')}"
        f"@{args.database_host}:{args.database_port}/{quote(args.database_name, safe='')}"
    )


def _read_password(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ApplicationKeyRecoveryError(
            "restore database credential is unavailable"
        ) from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
            or not 1 <= before.st_size <= _MAX_PASSWORD_BYTES
        ):
            raise ApplicationKeyRecoveryError("restore database credential is invalid")
        raw = os.read(descriptor, _MAX_PASSWORD_BYTES + 1)
        after = os.fstat(descriptor)
        if len(raw) > _MAX_PASSWORD_BYTES or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ApplicationKeyRecoveryError(
                "restore database credential changed while reading"
            )
    finally:
        os.close(descriptor)
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeError:
        raise ApplicationKeyRecoveryError("restore database credential is invalid") from None
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ApplicationKeyRecoveryError("restore database credential is invalid")
    return value


def _read_only_rejected() -> Never:
    raise ApplicationKeyRecoveryError("restore object adapter is read-only")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify restored application key domains.")
    parser.add_argument("--database-password-file", type=Path, required=True)
    parser.add_argument("--database-host", required=True)
    parser.add_argument("--database-port", type=int, default=5432)
    parser.add_argument("--database-user", required=True)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--secret-store-keyring", type=Path, required=True)
    parser.add_argument("--secret-store-request-hash-key", type=Path, required=True)
    parser.add_argument("--secret-store-service-identity-id", type=UUID, required=True)
    parser.add_argument("--secret-store-frozen-reference-id", type=UUID, required=True)
    parser.add_argument("--secret-store-frozen-project-id", type=UUID, required=True)
    parser.add_argument("--secret-store-frozen-purpose", required=True)
    parser.add_argument("--secret-store-frozen-version", type=int, required=True)
    parser.add_argument("--secret-store-resolve-idempotency-key", required=True)
    parser.add_argument("--provider-artifact-keyring", type=Path, required=True)
    parser.add_argument("--synthetic-artifact-keyring", type=Path, required=True)
    parser.add_argument("--recommendation-artifact-keyring", type=Path, required=True)
    parser.add_argument("--workflow-c-artifact-keyring", type=Path, required=True)
    parser.add_argument("--object-root", type=Path, required=True)
    parser.add_argument("--object-bucket", required=True)
    parser.add_argument("--recommendation-object-root", type=Path, required=True)
    parser.add_argument("--recommendation-object-bucket", required=True)
    parser.add_argument("--workflow-c-object-root", type=Path, required=True)
    parser.add_argument("--workflow-c-object-bucket", required=True)
    parser.add_argument("--synthetic-raw-object-root", type=Path, required=True)
    parser.add_argument("--synthetic-raw-object-bucket", required=True)
    parser.add_argument("--synthetic-derived-object-root", type=Path, required=True)
    parser.add_argument("--synthetic-derived-object-bucket", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = run_probe(
            database_url=_database_url(args),
            secret_store_keyring=args.secret_store_keyring,
            secret_store_request_hash_key=args.secret_store_request_hash_key,
            secret_store_service_identity_id=args.secret_store_service_identity_id,
            secret_store_frozen_handle=SecretVersionHandle(
                reference_id=args.secret_store_frozen_reference_id,
                project_id=args.secret_store_frozen_project_id,
                purpose=args.secret_store_frozen_purpose,
                version=args.secret_store_frozen_version,
            ),
            secret_store_resolve_idempotency_key=args.secret_store_resolve_idempotency_key,
            provider_artifact_keyring=args.provider_artifact_keyring,
            synthetic_artifact_keyring=args.synthetic_artifact_keyring,
            recommendation_artifact_keyring=args.recommendation_artifact_keyring,
            workflow_c_artifact_keyring=args.workflow_c_artifact_keyring,
            object_root=args.object_root,
            object_bucket=args.object_bucket,
            recommendation_object_root=args.recommendation_object_root,
            recommendation_object_bucket=args.recommendation_object_bucket,
            workflow_c_object_root=args.workflow_c_object_root,
            workflow_c_object_bucket=args.workflow_c_object_bucket,
            synthetic_raw_object_root=args.synthetic_raw_object_root,
            synthetic_raw_object_bucket=args.synthetic_raw_object_bucket,
            synthetic_derived_object_root=args.synthetic_derived_object_root,
            synthetic_derived_object_bucket=args.synthetic_derived_object_bucket,
        )
    except Exception:
        print("application key recovery probe failed", file=sys.stderr)
        return 2
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
