from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "infra/docker-compose.yml"
PRODUCTION_COMPOSE = ROOT / "infra/docker-compose.production.yml"
DEFAULT_ARTIFACT = ROOT / "tmp/production-object-store-credentials/latest.json"

APPLICATION_CONSUMERS = (
    "api",
    "browser-fidelity-scheduler",
    "collector-worker",
    "collector-worker-litellm",
    "knowledge-worker",
    "report-export-worker",
    "runtime-e2e",
    "task-worker-knowledge",
    "task-worker-runtime",
)
OBJECT_STORE_CALLER_SERVICE_MAP = {
    "apps/api/geno_api/main.py": frozenset({"api"}),
    "scripts/run_production_object_store_smoke.py": frozenset(APPLICATION_CONSUMERS),
    "scripts/verify_runtime_e2e.py": frozenset({"runtime-e2e"}),
    "workers/collector_worker/run_collection_slice.py": frozenset(
        {"collector-worker", "collector-worker-litellm"}
    ),
    "workers/knowledge_worker/run_knowledge_pipeline.py": frozenset({"knowledge-worker"}),
    "workers/report_export_worker/run_report_export_jobs.py": frozenset({"report-export-worker"}),
    "workers/task_queue/tasks.py": frozenset({"task-worker-runtime", "task-worker-knowledge"}),
}
GOVERNANCE_SERVICES = frozenset({"minio", "minio-bootstrap", "backup-object-smoke"})
APPLICATION_SECRET_NAMES = frozenset(
    {"object_store_application_access_key", "object_store_application_secret_key"}
)
BACKUP_SECRET_NAMES = frozenset(
    {"object_store_backup_access_key", "object_store_backup_secret_key"}
)
RESTORE_SECRET_NAMES = frozenset(
    {"object_store_restore_access_key", "object_store_restore_secret_key"}
)
ROOT_SECRET_NAMES = frozenset({"minio_root_user", "minio_root_password"})
RETENTION_SECRET_NAMES = frozenset(
    {"object_store_retention_access_key", "object_store_retention_secret_key"}
)
ALL_SECRET_NAMES = (
    ROOT_SECRET_NAMES
    | APPLICATION_SECRET_NAMES
    | BACKUP_SECRET_NAMES
    | RESTORE_SECRET_NAMES
    | RETENTION_SECRET_NAMES
)
SECRET_HOST_ENV = {
    "minio_root_user": "GENO_MINIO_ROOT_USER_SECRET_FILE",
    "minio_root_password": "GENO_MINIO_ROOT_PASSWORD_SECRET_FILE",
    "object_store_application_access_key": "GENO_OBJECT_STORE_APPLICATION_ACCESS_KEY_SECRET_FILE",
    "object_store_application_secret_key": "GENO_OBJECT_STORE_APPLICATION_SECRET_KEY_SECRET_FILE",
    "object_store_backup_access_key": "GENO_OBJECT_STORE_BACKUP_ACCESS_KEY_SECRET_FILE",
    "object_store_backup_secret_key": "GENO_OBJECT_STORE_BACKUP_SECRET_KEY_SECRET_FILE",
    "object_store_restore_access_key": "GENO_OBJECT_STORE_RESTORE_ACCESS_KEY_SECRET_FILE",
    "object_store_restore_secret_key": "GENO_OBJECT_STORE_RESTORE_SECRET_KEY_SECRET_FILE",
    "object_store_retention_access_key": "GENO_OBJECT_STORE_RETENTION_ACCESS_KEY_SECRET_FILE",
    "object_store_retention_secret_key": "GENO_OBJECT_STORE_RETENTION_SECRET_KEY_SECRET_FILE",
}
DEVELOPMENT_CREDENTIALS = frozenset(
    {
        "minio",
        "minio123",
        "geno-application-local",
        "geno-application-local-secret",
        "geno-backup-local",
        "geno-backup-local-secret",
        "geno-restore-local",
        "geno-restore-local-secret",
        "geno-retention-local",
        "geno-retention-local-secret",
    }
)
SENSITIVE_ENV_RE = re.compile(
    r"^(?:MINIO_ROOT_(?:USER|PASSWORD)|OBJECT_STORE_(?:ACCESS_KEY|SECRET_KEY|"
    r"BACKUP_(?:ACCESS_KEY|SECRET_KEY)|RESTORE_(?:ACCESS_KEY|SECRET_KEY)|"
    r"RETENTION_(?:ACCESS_KEY|SECRET_KEY)))(?:_FILE)?$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProductionObjectStoreVerificationError(RuntimeError):
    """Raised when the production object-store contract is incomplete."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _check(checks: list[dict[str, str]], name: str, condition: bool, detail: str) -> None:
    if not condition:
        raise ProductionObjectStoreVerificationError(f"{name}: {detail}")
    checks.append({"name": name, "status": "pass", "detail": detail})


def _config_only_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GENO_CONNECTOR_SECRET_MASTER_KEY": "config-only-connector-sentinel",
            "GENO_REPORT_ARTIFACT_SIGNING_SECRET": "config-only-signing-sentinel",
            "GENO_AUTH_DELIVERY_MASTER_KEY_SECRET_FILE": "/run/geno-config-only/auth-delivery-master-key",
            "GENO_AUTH_DELIVERY_KEY_ID": "config-only-auth-delivery-key",
            "GENO_AUTH_RECOVERY_COOKIE_SECRET_FILE": "/run/geno-config-only/auth-recovery-cookie",
            "ADMIN_WEB_BASE_URL": "https://admin.config-only.example/login",
            "CUSTOMER_WEB_BASE_URL": "https://customer.config-only.example/",
            "GENO_MINIO_ENCRYPTED_VOLUME_NAME": "geno-config-only-encrypted-minio",
            "OBJECT_STORE_BACKUP_PREFIX": "production/config-only/",
            "OBJECT_STORE_BACKUP_SMOKE_PREFIX": "smoke/config-only-run/",
            "OBJECT_STORE_RESTORE_PREFIX": "restore-smoke/config-only-run/",
            "OBJECT_STORE_RETENTION_PREFIX": "retention-approved/config-only-manifest/",
        }
    )
    for variable in SECRET_HOST_ENV.values():
        env[variable] = f"/run/geno-config-only/{variable.lower()}"
    return env


def load_merged_compose(*, config_only: bool) -> dict[str, Any]:
    env = _config_only_env() if config_only else os.environ.copy()
    command = [
        "docker",
        "compose",
        "--profile",
        "*",
        "-f",
        str(BASE_COMPOSE),
        "-f",
        str(PRODUCTION_COMPOSE),
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(command, cwd=ROOT, env=env, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (
            result.stderr.strip().splitlines()[-1]
            if result.stderr.strip()
            else "compose config failed"
        )
        raise ProductionObjectStoreVerificationError(f"merged_compose: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProductionObjectStoreVerificationError("merged_compose: invalid JSON output") from exc


def _service_secret_sources(service: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    for item in service.get("secrets", []):
        if isinstance(item, str):
            sources.add(item)
        elif isinstance(item, dict) and item.get("source"):
            sources.add(str(item["source"]))
    return sources


def _discover_object_store_callers() -> set[str]:
    callers: set[str] = set()
    for directory in ("apps", "scripts", "workers"):
        for path in (ROOT / directory).rglob("*.py"):
            if path.resolve() == Path(__file__).resolve():
                continue
            if "build_object_store_from_env(" in path.read_text(encoding="utf-8"):
                callers.add(path.relative_to(ROOT).as_posix())
    return callers


def verify_merged_compose(config: dict[str, Any]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    services = config.get("services", {})
    _check(
        checks,
        "consumer_inventory",
        set(APPLICATION_CONSUMERS) <= set(services),
        "All consumers exist",
    )

    application_services = {
        name
        for name, service in services.items()
        if _service_secret_sources(service) & APPLICATION_SECRET_NAMES
    }
    _check(
        checks,
        "consumer_inventory_exact",
        application_services == set(APPLICATION_CONSUMERS) | {"minio-bootstrap"},
        "Application credentials are mounted only in runtime consumers and bootstrap",
    )
    discovered_callers = _discover_object_store_callers()
    _check(
        checks,
        "consumer_caller_inventory_exact",
        discovered_callers == set(OBJECT_STORE_CALLER_SERVICE_MAP),
        "Every object-store builder caller is mapped to a production service",
    )
    mapped_consumers = set().union(*OBJECT_STORE_CALLER_SERVICE_MAP.values()) | {
        "browser-fidelity-scheduler"
    }
    _check(
        checks,
        "consumer_caller_service_mapping",
        mapped_consumers == set(APPLICATION_CONSUMERS),
        "Caller-to-service mapping covers the complete runtime inventory",
    )

    expected_tuple = ("http://minio:9000", "geno-reports", "us-east-1")
    for name in APPLICATION_CONSUMERS:
        service = services[name]
        environment = service.get("environment", {})
        actual_tuple = (
            environment.get("OBJECT_STORE_ENDPOINT"),
            environment.get("OBJECT_STORE_BUCKET"),
            environment.get("OBJECT_STORE_REGION"),
        )
        _check(
            checks,
            f"{name}_atomic_config",
            actual_tuple == expected_tuple,
            "Endpoint/bucket/region match",
        )
        _check(
            checks,
            f"{name}_file_credentials",
            environment.get("OBJECT_STORE_ACCESS_KEY", "") == ""
            and environment.get("OBJECT_STORE_SECRET_KEY", "") == ""
            and environment.get("OBJECT_STORE_ACCESS_KEY_FILE")
            == "/run/secrets/object_store_application_access_key"
            and environment.get("OBJECT_STORE_SECRET_KEY_FILE")
            == "/run/secrets/object_store_application_secret_key"
            and _service_secret_sources(service) & APPLICATION_SECRET_NAMES
            == APPLICATION_SECRET_NAMES,
            "Application credentials use the common Compose secret files",
        )
        _check(
            checks,
            f"{name}_auto_create_disabled",
            str(environment.get("OBJECT_STORE_AUTO_CREATE_BUCKET")) == "0",
            "Runtime bucket auto-creation is disabled",
        )
        dependency = service.get("depends_on", {}).get("minio-bootstrap", {})
        _check(
            checks,
            f"{name}_waits_for_bootstrap",
            dependency.get("condition") == "service_completed_successfully",
            "Runtime waits for successful MinIO bootstrap",
        )

    minio = services["minio"]
    bootstrap = services["minio-bootstrap"]
    backup = services["backup-object-smoke"]
    _check(
        checks,
        "root_identity_visibility",
        _service_secret_sources(minio) == ROOT_SECRET_NAMES
        and ROOT_SECRET_NAMES <= _service_secret_sources(bootstrap)
        and all(
            not (_service_secret_sources(service) & ROOT_SECRET_NAMES)
            for name, service in services.items()
            if name not in {"minio", "minio-bootstrap"}
        ),
        "Root credentials are visible only to MinIO and bootstrap",
    )
    _check(
        checks,
        "backup_identity_visibility",
        _service_secret_sources(backup) == BACKUP_SECRET_NAMES | RESTORE_SECRET_NAMES,
        "Backup smoke receives backup and ephemeral restore credentials only",
    )
    _check(
        checks,
        "governance_identity_visibility",
        ALL_SECRET_NAMES <= _service_secret_sources(bootstrap),
        "Bootstrap receives each governance secret needed to provision scoped principals",
    )

    for name, service in services.items():
        if name in set(APPLICATION_CONSUMERS) | GOVERNANCE_SERVICES:
            continue
        environment = service.get("environment", {})
        sensitive_keys = {key for key in environment if SENSITIVE_ENV_RE.match(key)}
        mounted = _service_secret_sources(service) & ALL_SECRET_NAMES
        _check(
            checks,
            f"{name}_no_object_store_secret",
            not sensitive_keys and not mounted,
            "Non-consumer has no object-store credential environment or secret mount",
        )

    serialized = json.dumps(config, sort_keys=True)
    _check(
        checks,
        "no_development_object_store_credentials",
        all(value not in serialized for value in DEVELOPMENT_CREDENTIALS if value != "minio"),
        "Merged production config contains no development object-store credential",
    )
    secrets_config = config.get("secrets", {})
    _check(
        checks,
        "all_secret_files_declared",
        ALL_SECRET_NAMES <= set(secrets_config)
        and all(bool(secrets_config[name].get("file")) for name in ALL_SECRET_NAMES),
        "All object-store identities are supplied through controlled secret files",
    )
    minio_volume = config.get("volumes", {}).get("minio_data", {})
    _check(
        checks,
        "external_encrypted_volume_contract",
        minio_volume.get("external") is True and bool(minio_volume.get("name")),
        "Production MinIO uses a pre-provisioned external volume",
    )

    bootstrap_source = (ROOT / "infra/minio/bootstrap.sh").read_text(encoding="utf-8")
    backup_source = (ROOT / "infra/minio/backup-restore-smoke.sh").read_text(encoding="utf-8")
    _check(
        checks,
        "bucket_creation_is_bootstrap_only",
        "mc mb --ignore-existing" in bootstrap_source
        and "mc mb --ignore-existing" not in backup_source,
        "Only bootstrap creates required buckets",
    )
    _check(
        checks,
        "policies_exclude_admin",
        '"s3:CreateBucket"' not in bootstrap_source
        and '"s3:*"' not in bootstrap_source
        and '"admin:' not in bootstrap_source,
        "Scoped policies contain no CreateBucket, wildcard S3, or admin action",
    )
    return checks


def _load_json_receipt(path: Path, *, name: str) -> dict[str, Any]:
    if not path.is_file():
        raise ProductionObjectStoreVerificationError(f"{name}: receipt file is required")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionObjectStoreVerificationError(f"{name}: invalid JSON receipt") from exc
    if not isinstance(payload, dict):
        raise ProductionObjectStoreVerificationError(f"{name}: receipt must be a JSON object")
    return payload


def _require_fields(payload: dict[str, Any], fields: set[str], *, name: str) -> None:
    missing = sorted(
        field for field in fields if payload.get(field) is None or payload.get(field) == ""
    )
    if missing:
        raise ProductionObjectStoreVerificationError(f"{name}: missing fields {missing}")


def _validate_timestamp(value: Any, *, name: str) -> None:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductionObjectStoreVerificationError(f"{name}: invalid timestamp") from exc


def validate_encryption_receipt(payload: dict[str, Any]) -> None:
    _require_fields(
        payload,
        {
            "volume_id",
            "provider",
            "encryption_enabled",
            "key_alias",
            "policy_version",
            "rotation_owner",
            "recovery_owner",
            "verified_at",
        },
        name="encryption_volume_receipt",
    )
    if payload["encryption_enabled"] is not True:
        raise ProductionObjectStoreVerificationError(
            "encryption_volume_receipt: encryption_enabled must be true"
        )
    _validate_timestamp(payload["verified_at"], name="encryption_volume_receipt.verified_at")


def validate_snapshot_receipt(payload: dict[str, Any]) -> None:
    _require_fields(
        payload,
        {
            "snapshot_id",
            "source_volume_id",
            "new_node_id",
            "new_volume_id",
            "restored_object_hash",
            "verified_at",
        },
        name="snapshot_restore_receipt",
    )
    if payload["source_volume_id"] == payload["new_volume_id"]:
        raise ProductionObjectStoreVerificationError(
            "snapshot_restore_receipt: restore must use a new volume"
        )
    if not SHA256_RE.fullmatch(str(payload["restored_object_hash"])):
        raise ProductionObjectStoreVerificationError(
            "snapshot_restore_receipt: restored_object_hash must be SHA-256"
        )
    _validate_timestamp(payload["verified_at"], name="snapshot_restore_receipt.verified_at")


def validate_bootstrap_receipt(payload: dict[str, Any]) -> None:
    _require_fields(
        payload,
        {
            "schema_version",
            "policy_version",
            "reports_bucket",
            "backup_bucket",
            "policy_hashes",
            "application_readiness_sha256",
            "verified_at",
        },
        name="bootstrap_receipt",
    )
    if payload["schema_version"] != "production-object-store-bootstrap-v1":
        raise ProductionObjectStoreVerificationError("bootstrap_receipt: unsupported schema")
    if not SHA256_RE.fullmatch(str(payload["application_readiness_sha256"])):
        raise ProductionObjectStoreVerificationError("bootstrap_receipt: invalid readiness SHA-256")
    if (
        payload.get("application_delete_denied") is not True
        or payload.get("application_create_bucket_denied") is not True
        or payload.get("application_cross_bucket_denied") is not True
        or payload.get("application_admin_denied") is not True
    ):
        raise ProductionObjectStoreVerificationError(
            "bootstrap_receipt: application negative checks must pass"
        )
    hashes = payload["policy_hashes"]
    if not isinstance(hashes, dict) or set(hashes) != {
        "application",
        "backup",
        "restore",
        "retention",
    }:
        raise ProductionObjectStoreVerificationError("bootstrap_receipt: incomplete policy hashes")
    if not all(SHA256_RE.fullmatch(str(value)) for value in hashes.values()):
        raise ProductionObjectStoreVerificationError("bootstrap_receipt: invalid policy hash")
    _validate_timestamp(payload["verified_at"], name="bootstrap_receipt.verified_at")


def validate_backup_receipt(payload: dict[str, Any]) -> None:
    _require_fields(
        payload,
        {
            "schema_version",
            "source_sha256",
            "backup_sha256",
            "formal_backup_sha256",
            "restored_sha256",
            "negative_checks",
            "verified_at",
        },
        name="backup_restore_receipt",
    )
    hashes = {
        payload["source_sha256"],
        payload["backup_sha256"],
        payload["formal_backup_sha256"],
        payload["restored_sha256"],
    }
    if len(hashes) != 1 or not SHA256_RE.fullmatch(str(payload["source_sha256"])):
        raise ProductionObjectStoreVerificationError(
            "backup_restore_receipt: source/backup/restore hash mismatch"
        )
    negative = payload["negative_checks"]
    expected = {
        "create_bucket_denied",
        "source_write_denied",
        "formal_backup_delete_denied",
        "cross_run_delete_denied",
        "restore_cross_run_write_denied",
    }
    if not isinstance(negative, dict) or any(negative.get(name) is not True for name in expected):
        raise ProductionObjectStoreVerificationError(
            "backup_restore_receipt: policy negative check failed"
        )
    if (
        payload.get("source_object_deleted") is not False
        or payload.get("smoke_cleanup_completed") is not True
    ):
        raise ProductionObjectStoreVerificationError(
            "backup_restore_receipt: unsafe cleanup result"
        )
    if payload.get("formal_backup_put_list_get") is not True:
        raise ProductionObjectStoreVerificationError(
            "backup_restore_receipt: formal backup put/list/get did not pass"
        )
    _validate_timestamp(payload["verified_at"], name="backup_restore_receipt.verified_at")


def validate_ephemeral_cleanup_receipt(payload: dict[str, Any]) -> None:
    _require_fields(
        payload,
        {
            "schema_version",
            "restore_principal_revoked",
            "retention_principal_revoked",
            "verified_at",
        },
        name="ephemeral_cleanup_receipt",
    )
    if payload.get("schema_version") != "production-object-store-ephemeral-cleanup-v1":
        raise ProductionObjectStoreVerificationError(
            "ephemeral_cleanup_receipt: unsupported schema"
        )
    if (
        payload.get("restore_principal_revoked") is not True
        or payload.get("retention_principal_revoked") is not True
    ):
        raise ProductionObjectStoreVerificationError(
            "ephemeral_cleanup_receipt: temporary principal still has access"
        )
    _validate_timestamp(payload["verified_at"], name="ephemeral_cleanup_receipt.verified_at")


def validate_consumer_receipt(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "production-object-store-consumer-roundtrip-v1":
        raise ProductionObjectStoreVerificationError(
            "consumer_roundtrip_receipt: shared-identity or unsupported receipt schema"
        )
    _require_fields(
        payload,
        {
            "schema_version",
            "verification_scope",
            "credential_fingerprint",
            "consumer_roundtrips",
            "verified_at",
        },
        name="consumer_roundtrip_receipt",
    )
    if payload.get("verification_scope") != "compose_service_native_builder":
        raise ProductionObjectStoreVerificationError(
            "consumer_roundtrip_receipt: full Gate requires Compose service native-builder evidence"
        )
    roundtrips = payload["consumer_roundtrips"]
    if not isinstance(roundtrips, dict) or set(roundtrips) != set(APPLICATION_CONSUMERS):
        raise ProductionObjectStoreVerificationError(
            "consumer_roundtrip_receipt: inventory mismatch"
        )
    container_ids: set[str] = set()
    fingerprints: set[str] = set()
    for name, result in roundtrips.items():
        if not isinstance(result, dict) or result.get("status") != "pass":
            raise ProductionObjectStoreVerificationError(
                f"consumer_roundtrip_receipt: {name} failed"
            )
        if not SHA256_RE.fullmatch(str(result.get("sha256", ""))):
            raise ProductionObjectStoreVerificationError(
                f"consumer_roundtrip_receipt: {name} hash invalid"
            )
        if result.get("service_name") != name:
            raise ProductionObjectStoreVerificationError(
                f"consumer_roundtrip_receipt: {name} service binding mismatch"
            )
        if result.get("execution_path") != "geno_core.runtime.build_object_store_from_env":
            raise ProductionObjectStoreVerificationError(
                f"consumer_roundtrip_receipt: {name} did not use the native builder"
            )
        if result.get("credential_source") != "OBJECT_STORE_ACCESS_KEY_FILE":
            raise ProductionObjectStoreVerificationError(
                f"consumer_roundtrip_receipt: {name} did not use file-backed credentials"
            )
        if result.get("auto_create_bucket") is not False:
            raise ProductionObjectStoreVerificationError(
                f"consumer_roundtrip_receipt: {name} auto-create was not disabled"
            )
        container_id = str(result.get("container_id") or "")
        fingerprint = str(result.get("credential_fingerprint") or "")
        if not container_id or not SHA256_RE.fullmatch(fingerprint):
            raise ProductionObjectStoreVerificationError(
                f"consumer_roundtrip_receipt: {name} container/fingerprint evidence invalid"
            )
        container_ids.add(container_id)
        fingerprints.add(fingerprint)
    if not SHA256_RE.fullmatch(str(payload["credential_fingerprint"])):
        raise ProductionObjectStoreVerificationError(
            "consumer_roundtrip_receipt: invalid fingerprint"
        )
    if len(container_ids) != len(APPLICATION_CONSUMERS):
        raise ProductionObjectStoreVerificationError(
            "consumer_roundtrip_receipt: evidence must come from nine distinct service containers"
        )
    if fingerprints != {str(payload["credential_fingerprint"])}:
        raise ProductionObjectStoreVerificationError(
            "consumer_roundtrip_receipt: consumer credential fingerprints differ"
        )
    _validate_timestamp(payload["verified_at"], name="consumer_roundtrip_receipt.verified_at")


def _read_secret_values(config: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for name in sorted(ALL_SECRET_NAMES):
        path = Path(str(config["secrets"][name]["file"]))
        if path.is_symlink() or path.resolve().is_relative_to(ROOT):
            raise ProductionObjectStoreVerificationError(
                f"secret_file: {name} must be a non-repository regular file"
            )
        try:
            file_stat = path.stat()
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ProductionObjectStoreVerificationError(
                f"secret_file: unable to read {name}"
            ) from exc
        if not stat.S_ISREG(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) not in {
            0o400,
            0o600,
        }:
            raise ProductionObjectStoreVerificationError(
                f"secret_file: {name} must be a mode 0400/0600 regular file"
            )
        if not value:
            raise ProductionObjectStoreVerificationError(f"secret_file: {name} is empty")
        if value in DEVELOPMENT_CREDENTIALS:
            raise ProductionObjectStoreVerificationError(
                f"secret_file: {name} uses a development credential"
            )
        values[name] = value
    identity_values = {
        values["minio_root_user"],
        values["object_store_application_access_key"],
        values["object_store_backup_access_key"],
        values["object_store_restore_access_key"],
        values["object_store_retention_access_key"],
    }
    if len(identity_values) != 5:
        raise ProductionObjectStoreVerificationError(
            "secret_file: object-store identities must be distinct"
        )
    if len(set(values.values())) != len(values):
        raise ProductionObjectStoreVerificationError(
            "secret_file: object-store credential values must not be reused"
        )
    return values


def _git_metadata() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return commit, bool(status.strip())


def build_full_artifact(
    args: argparse.Namespace, config: dict[str, Any], checks: list[dict[str, str]]
) -> dict[str, Any]:
    receipt_paths = {
        "bootstrap": Path(args.bootstrap_receipt),
        "backup_restore": Path(args.backup_restore_receipt),
        "consumer_roundtrip": Path(args.consumer_roundtrip_receipt),
        "ephemeral_cleanup": Path(args.ephemeral_cleanup_receipt),
        "encryption_volume": Path(args.encryption_volume_receipt),
        "snapshot_restore": Path(args.snapshot_restore_receipt),
    }
    receipts = {name: _load_json_receipt(path, name=name) for name, path in receipt_paths.items()}
    validate_bootstrap_receipt(receipts["bootstrap"])
    validate_backup_receipt(receipts["backup_restore"])
    validate_consumer_receipt(receipts["consumer_roundtrip"])
    validate_ephemeral_cleanup_receipt(receipts["ephemeral_cleanup"])
    validate_encryption_receipt(receipts["encryption_volume"])
    validate_snapshot_receipt(receipts["snapshot_restore"])
    checks.extend(
        {
            "name": name,
            "status": "pass",
            "detail": detail,
        }
        for name, detail in (
            (
                "bootstrap_live_receipt",
                "Bootstrap policy/versioning/lifecycle and readiness receipt passed",
            ),
            ("backup_restore_live_receipt", "Backup/restore hash and policy negatives passed"),
            ("consumer_roundtrips", "All application consumer roundtrips passed"),
            (
                "ephemeral_principal_revocation",
                "Restore and retention principals were revoked",
            ),
            ("encrypted_volume_receipt", "Infrastructure encrypted-volume receipt passed"),
            ("encrypted_snapshot_restore", "Encrypted snapshot restore on a new volume passed"),
        )
    )

    secret_values = _read_secret_values(config)
    application_fingerprint = _sha256_bytes(
        secret_values["object_store_application_access_key"].encode("utf-8")
    )
    if receipts["consumer_roundtrip"]["credential_fingerprint"] != application_fingerprint:
        raise ProductionObjectStoreVerificationError(
            "consumer_roundtrip_receipt: credential fingerprint mismatch"
        )

    serialized_evidence = json.dumps({"config": config, "receipts": receipts}, sort_keys=True)
    secret_leak_count = sum(serialized_evidence.count(value) for value in secret_values.values())
    if secret_leak_count:
        raise ProductionObjectStoreVerificationError(
            "secret_leak: raw secret found in config or receipt"
        )

    compose_bytes = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    compose_hash = _sha256_bytes(compose_bytes)
    receipt_hashes = {name: _sha256_file(path) for name, path in receipt_paths.items()}
    git_commit, worktree_dirty = _git_metadata()
    started_at = args.started_at or _utc_now()
    finished_at = _utc_now()
    input_hash = _sha256_bytes(
        json.dumps(
            {"merged_compose": compose_hash, "receipts": receipt_hashes},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    artifact: dict[str, Any] = {
        "schema_version": "production-object-store-credentials-v1",
        "run_id": args.run_id or str(uuid.uuid4()),
        "started_at": started_at,
        "finished_at": finished_at,
        "git_commit": git_commit,
        "worktree_dirty": worktree_dirty,
        "environment": args.environment,
        "input_hash": input_hash,
        "status": "pass",
        "merged_compose_sha256": compose_hash,
        "consumer_inventory": list(APPLICATION_CONSUMERS),
        "credential_fingerprint": application_fingerprint,
        "bootstrap_receipt_sha256": receipt_hashes["bootstrap"],
        "consumer_roundtrips": receipts["consumer_roundtrip"]["consumer_roundtrips"],
        "policy_negative": {
            "application_delete_denied": receipts["bootstrap"]["application_delete_denied"],
            "application_create_bucket_denied": receipts["bootstrap"][
                "application_create_bucket_denied"
            ],
            "application_cross_bucket_denied": receipts["bootstrap"][
                "application_cross_bucket_denied"
            ],
            "application_admin_denied": receipts["bootstrap"]["application_admin_denied"],
            "restore_principal_revoked": receipts["ephemeral_cleanup"]["restore_principal_revoked"],
            "retention_principal_revoked": receipts["ephemeral_cleanup"][
                "retention_principal_revoked"
            ],
            **receipts["backup_restore"]["negative_checks"],
        },
        "backup_restore_sha256": receipts["backup_restore"]["restored_sha256"],
        "encryption_volume_receipt_sha256": receipt_hashes["encryption_volume"],
        "snapshot_restore_receipt_sha256": receipt_hashes["snapshot_restore"],
        "secret_leak_count": secret_leak_count,
        "checks": checks,
    }
    artifact["output_hash"] = _sha256_bytes(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify production object-store identity and restore contracts"
    )
    parser.add_argument("--config-only", action="store_true")
    parser.add_argument("--bootstrap-receipt")
    parser.add_argument("--backup-restore-receipt")
    parser.add_argument("--consumer-roundtrip-receipt")
    parser.add_argument("--ephemeral-cleanup-receipt")
    parser.add_argument("--encryption-volume-receipt")
    parser.add_argument("--snapshot-restore-receipt")
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    parser.add_argument("--environment", default="production")
    parser.add_argument("--run-id")
    parser.add_argument("--started-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_merged_compose(config_only=args.config_only)
        checks = verify_merged_compose(config)
        compose_hash = _sha256_bytes(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        if args.config_only:
            report = {
                "schema_version": "production-object-store-config-v1",
                "status": "pass",
                "merged_compose_sha256": compose_hash,
                "consumer_inventory": list(APPLICATION_CONSUMERS),
                "checks": checks,
            }
            print(json.dumps(report, sort_keys=True, indent=2))
            return 0
        required = {
            "--bootstrap-receipt": args.bootstrap_receipt,
            "--backup-restore-receipt": args.backup_restore_receipt,
            "--consumer-roundtrip-receipt": args.consumer_roundtrip_receipt,
            "--ephemeral-cleanup-receipt": args.ephemeral_cleanup_receipt,
            "--encryption-volume-receipt": args.encryption_volume_receipt,
            "--snapshot-restore-receipt": args.snapshot_restore_receipt,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ProductionObjectStoreVerificationError(f"required_receipts: missing {missing}")
        artifact = build_full_artifact(args, config, checks)
        artifact_path = Path(args.artifact)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(artifact, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": "pass",
                    "artifact": str(artifact_path),
                    "output_hash": artifact["output_hash"],
                    "secret_leak_count": artifact["secret_leak_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    except ProductionObjectStoreVerificationError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
