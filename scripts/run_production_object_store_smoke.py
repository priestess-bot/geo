from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verify_production_object_store import APPLICATION_CONSUMERS


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "infra/docker-compose.yml"
PRODUCTION_COMPOSE = ROOT / "infra/docker-compose.production.yml"
MC_IMAGE = "minio/mc:RELEASE.2025-02-21T16-00-46Z"
NATIVE_CONSUMER_PROBE = """
import hashlib
import json
import os
import socket

from geo_core.runtime import build_object_store_from_env

consumer = os.environ["OBJECT_STORE_CONSUMER_NAME"]
run_id = os.environ["OBJECT_STORE_SMOKE_RUN_ID"]
if os.environ.get("OBJECT_STORE_ACCESS_KEY") or os.environ.get("OBJECT_STORE_SECRET_KEY"):
    raise RuntimeError("native consumer received direct object-store credentials")
if not os.environ.get("OBJECT_STORE_ACCESS_KEY_FILE") or not os.environ.get("OBJECT_STORE_SECRET_KEY_FILE"):
    raise RuntimeError("native consumer is missing file-backed object-store credentials")
store = build_object_store_from_env()
if store.auto_create_bucket:
    raise RuntimeError("native consumer bucket auto-creation is enabled")
payload = f"geo native consumer={consumer} run={run_id}\\n".encode("utf-8")
content_hash = hashlib.sha256(payload).hexdigest()
key = f"production-readiness/{run_id}/native/{consumer}.txt"
stored = store.put_object(
    key=key,
    content=payload,
    content_type="text/plain; charset=utf-8",
    expected_hash=content_hash,
)
if not store.head_object(key=key):
    raise RuntimeError("native consumer HEAD object failed")
restored = store.get_object(key=key, expected_hash=stored.content_hash)
print(json.dumps({
    "status": "pass",
    "service_name": consumer,
    "container_id": socket.gethostname(),
    "sha256": restored.content_hash,
    "credential_fingerprint": hashlib.sha256(store.access_key.encode("utf-8")).hexdigest(),
    "execution_path": "geo_core.runtime.build_object_store_from_env",
    "credential_source": "OBJECT_STORE_ACCESS_KEY_FILE",
    "auto_create_bucket": store.auto_create_bucket,
}, sort_keys=True))
"""


class ProductionObjectStoreSmokeError(RuntimeError):
    """Raised when the isolated production object-store smoke fails."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_secret(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    secret_values: tuple[str, ...],
    capture: bool = True,
) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=capture,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if any(value and value in output for value in secret_values):
        command_label = f"{Path(command[0]).name}:{Path(command[-1]).name}"
        raise ProductionObjectStoreSmokeError(
            f"A raw object-store secret appeared in command output ({command_label})"
        )
    if result.returncode != 0:
        detail = output.strip().splitlines()[-1] if output.strip() else "command failed"
        raise ProductionObjectStoreSmokeError(detail)
    return result.stdout or ""


def _compose_command(project_name: str, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project_name,
        "-f",
        str(BASE_COMPOSE),
        "-f",
        str(PRODUCTION_COMPOSE),
        *arguments,
    ]


def _read_receipt_volume(
    project_name: str, filename: str, *, env: dict[str, str], secrets_: tuple[str, ...]
) -> dict[str, Any]:
    output = _run(
        [
            "docker",
            "run",
            "--rm",
            "--volume",
            f"{project_name}_object_store_receipts:/receipts:ro",
            "--entrypoint",
            "cat",
            MC_IMAGE,
            f"/receipts/{filename}",
        ],
        env=env,
        secret_values=secrets_,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProductionObjectStoreSmokeError(f"Invalid {filename} receipt") from exc
    if not isinstance(payload, dict):
        raise ProductionObjectStoreSmokeError(f"Invalid {filename} receipt")
    return payload


def _parse_last_json_object(output: str, *, service_name: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ProductionObjectStoreSmokeError(
        f"Native object-store probe for {service_name} did not return JSON"
    )


def _run_native_consumer_roundtrips(
    *,
    project_name: str,
    run_id: str,
    env: dict[str, str],
    secret_values: tuple[str, ...],
) -> dict[str, Any]:
    _run(
        _compose_command(project_name, "build", *APPLICATION_CONSUMERS),
        env=env,
        secret_values=secret_values,
    )
    roundtrips: dict[str, dict[str, Any]] = {}
    for service_name in APPLICATION_CONSUMERS:
        output = _run(
            _compose_command(
                project_name,
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "python",
                "-e",
                f"OBJECT_STORE_CONSUMER_NAME={service_name}",
                "-e",
                f"OBJECT_STORE_SMOKE_RUN_ID={run_id}",
                service_name,
                "-c",
                NATIVE_CONSUMER_PROBE,
            ),
            env=env,
            secret_values=secret_values,
        )
        result = _parse_last_json_object(output, service_name=service_name)
        if result.get("status") != "pass" or result.get("service_name") != service_name:
            raise ProductionObjectStoreSmokeError(
                f"Native object-store probe for {service_name} returned an invalid result"
            )
        roundtrips[service_name] = result

    fingerprints = {str(result.get("credential_fingerprint")) for result in roundtrips.values()}
    container_ids = {str(result.get("container_id")) for result in roundtrips.values()}
    if len(fingerprints) != 1:
        raise ProductionObjectStoreSmokeError(
            "Native consumer images did not use one application credential fingerprint"
        )
    if len(container_ids) != len(APPLICATION_CONSUMERS):
        raise ProductionObjectStoreSmokeError(
            "Native consumer evidence did not come from distinct service containers"
        )
    return {
        "schema_version": "production-object-store-consumer-roundtrip-v1",
        "verification_scope": "compose_service_native_builder",
        "credential_fingerprint": fingerprints.pop(),
        "consumer_roundtrips": roundtrips,
        "verified_at": _utc_now(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an isolated non-default MinIO policy/restore smoke"
    )
    parser.add_argument("--project-name", default="geo-storage-hardening")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--minio-port", type=int, default=0)
    parser.add_argument("--minio-console-port", type=int, default=0)
    parser.add_argument("--volume-name")
    parser.add_argument("--policy-only", action="store_true")
    parser.add_argument(
        "--native-consumers",
        action="store_true",
        help="Also build and probe every Compose consumer image when using --policy-only.",
    )
    parser.add_argument("--encryption-volume-receipt")
    parser.add_argument("--snapshot-restore-receipt")
    parser.add_argument(
        "--artifact", default=str(ROOT / "tmp/production-object-store-credentials/latest.json")
    )
    parser.add_argument("--keep-stack", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not re_fullmatch_project_name(args.project_name):
        print(
            json.dumps(
                {"status": "fail", "error": "project name must start with geo-storage-hardening"}
            )
        )
        return 1
    if not args.policy_only and (
        not args.encryption_volume_receipt or not args.snapshot_restore_receipt
    ):
        print(
            json.dumps(
                {"status": "fail", "error": "real encryption and snapshot receipts are required"}
            )
        )
        return 1
    if not args.policy_only and not args.volume_name:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "error": "--volume-name must identify the encrypted production volume",
                }
            )
        )
        return 1

    run_id = args.run_id or str(uuid.uuid4())
    minio_port = args.minio_port or _available_port()
    console_port = args.minio_console_port or _available_port()
    while console_port == minio_port:
        console_port = _available_port()
    volume_name = args.volume_name or f"{args.project_name}-policy-{run_id[:8]}"
    owns_volume = args.volume_name is None
    started_at = _utc_now()
    artifact_dir = ROOT / "tmp/production-object-store-smoke" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    secrets_dir = Path(tempfile.mkdtemp(prefix="geo-object-store-secrets-"))

    values = {
        "minio_root_user": f"root-{secrets.token_hex(8)}",
        "minio_root_password": secrets.token_urlsafe(32),
        "object_store_application_access_key": f"app-{secrets.token_hex(8)}",
        "object_store_application_secret_key": secrets.token_urlsafe(32),
        "object_store_backup_access_key": f"backup-{secrets.token_hex(8)}",
        "object_store_backup_secret_key": secrets.token_urlsafe(32),
        "object_store_restore_access_key": f"restore-{secrets.token_hex(8)}",
        "object_store_restore_secret_key": secrets.token_urlsafe(32),
        "object_store_retention_access_key": f"retention-{secrets.token_hex(8)}",
        "object_store_retention_secret_key": secrets.token_urlsafe(32),
    }
    secret_values = tuple(values.values())
    host_variables = {
        "minio_root_user": "GEO_MINIO_ROOT_USER_SECRET_FILE",
        "minio_root_password": "GEO_MINIO_ROOT_PASSWORD_SECRET_FILE",
        "object_store_application_access_key": "GEO_OBJECT_STORE_APPLICATION_ACCESS_KEY_SECRET_FILE",
        "object_store_application_secret_key": "GEO_OBJECT_STORE_APPLICATION_SECRET_KEY_SECRET_FILE",
        "object_store_backup_access_key": "GEO_OBJECT_STORE_BACKUP_ACCESS_KEY_SECRET_FILE",
        "object_store_backup_secret_key": "GEO_OBJECT_STORE_BACKUP_SECRET_KEY_SECRET_FILE",
        "object_store_restore_access_key": "GEO_OBJECT_STORE_RESTORE_ACCESS_KEY_SECRET_FILE",
        "object_store_restore_secret_key": "GEO_OBJECT_STORE_RESTORE_SECRET_KEY_SECRET_FILE",
        "object_store_retention_access_key": "GEO_OBJECT_STORE_RETENTION_ACCESS_KEY_SECRET_FILE",
        "object_store_retention_secret_key": "GEO_OBJECT_STORE_RETENTION_SECRET_KEY_SECRET_FILE",
    }
    env = os.environ.copy()
    for name, value in values.items():
        path = secrets_dir / name
        _write_secret(path, value)
        env[host_variables[name]] = str(path)
    env.update(
        {
            "COMPOSE_PROJECT_NAME": args.project_name,
            "GEO_MINIO_ENCRYPTED_VOLUME_NAME": volume_name,
            "GEO_MINIO_HOST_PORT": str(minio_port),
            "GEO_MINIO_CONSOLE_HOST_PORT": str(console_port),
            "OBJECT_STORE_BACKUP_PREFIX": "production/smoke-environment/",
            "OBJECT_STORE_BACKUP_SMOKE_PREFIX": f"smoke/{run_id}/",
            "OBJECT_STORE_RESTORE_PREFIX": f"restore-smoke/{run_id}/",
            "OBJECT_STORE_RETENTION_PREFIX": f"retention-approved/{run_id}/",
            "MINIO_BOOTSTRAP_ENABLE_EPHEMERAL": "1",
            "GEO_CONNECTOR_SECRET_MASTER_KEY": secrets.token_urlsafe(32),
            "GEO_REPORT_ARTIFACT_SIGNING_SECRET": secrets.token_urlsafe(32),
        }
    )

    try:
        if owns_volume:
            _run(["docker", "volume", "create", volume_name], env=env, secret_values=secret_values)
        _run(
            _compose_command(args.project_name, "up", "-d", "--no-build", "minio"),
            env=env,
            secret_values=secret_values,
        )
        _run(
            _compose_command(args.project_name, "run", "--rm", "--no-deps", "minio-bootstrap"),
            env=env,
            secret_values=secret_values,
        )
        _run(
            _compose_command(
                args.project_name,
                "--profile",
                "backup-smoke",
                "run",
                "--rm",
                "--no-deps",
                "backup-object-smoke",
            ),
            env=env,
            secret_values=secret_values,
        )

        bootstrap_receipt = _read_receipt_volume(
            args.project_name, "bootstrap.json", env=env, secrets_=secret_values
        )
        backup_receipt = _read_receipt_volume(
            args.project_name, "backup-restore.json", env=env, secrets_=secret_values
        )
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                f"{args.project_name}_default",
                "--mount",
                f"type=bind,source={secrets_dir / 'object_store_application_access_key'},target=/run/secrets/object_store_application_access_key,readonly",
                "--mount",
                f"type=bind,source={secrets_dir / 'object_store_application_secret_key'},target=/run/secrets/object_store_application_secret_key,readonly",
                "--volume",
                f"{args.project_name}_object_store_receipts:/receipts",
                "--volume",
                f"{ROOT / 'infra/minio'}:/bootstrap:ro",
                "--env",
                f"OBJECT_STORE_SMOKE_RUN_ID={run_id}",
                "--entrypoint",
                "/bin/sh",
                MC_IMAGE,
                "/bootstrap/application-roundtrip-smoke.sh",
            ],
            env=env,
            secret_values=secret_values,
        )
        shared_identity_receipt = _read_receipt_volume(
            args.project_name,
            "shared-identity-roundtrip.json",
            env=env,
            secrets_=secret_values,
        )
        consumer_receipt = None
        if args.native_consumers or not args.policy_only:
            consumer_receipt = _run_native_consumer_roundtrips(
                project_name=args.project_name,
                run_id=run_id,
                env=env,
                secret_values=secret_values,
            )
        receipt_paths = {
            "bootstrap": artifact_dir / "bootstrap.json",
            "backup_restore": artifact_dir / "backup-restore.json",
            "shared_identity": artifact_dir / "shared-identity-roundtrip.json",
        }
        for name, payload in (
            ("bootstrap", bootstrap_receipt),
            ("backup_restore", backup_receipt),
            ("shared_identity", shared_identity_receipt),
        ):
            receipt_paths[name].write_text(
                json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
        if consumer_receipt is not None:
            receipt_paths["consumer_roundtrip"] = artifact_dir / "consumer-roundtrip.json"
            receipt_paths["consumer_roundtrip"].write_text(
                json.dumps(consumer_receipt, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )

        _run(
            _compose_command(
                args.project_name,
                "run",
                "--rm",
                "--no-deps",
                "-e",
                "MINIO_BOOTSTRAP_ACTION=cleanup-ephemeral",
                "minio-bootstrap",
            ),
            env=env,
            secret_values=secret_values,
        )
        cleanup_receipt = _read_receipt_volume(
            args.project_name, "ephemeral-cleanup.json", env=env, secrets_=secret_values
        )
        receipt_paths["ephemeral_cleanup"] = artifact_dir / "ephemeral-cleanup.json"
        receipt_paths["ephemeral_cleanup"].write_text(
            json.dumps(cleanup_receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        logs = _run(
            _compose_command(args.project_name, "logs", "--no-color", "minio"),
            env=env,
            secret_values=secret_values,
        )
        if any(value in logs for value in secret_values):
            raise ProductionObjectStoreSmokeError("Raw secret found in MinIO logs")

        if args.policy_only:
            scope = (
                "policy_and_native_consumer_images_on_unencrypted_test_volume"
                if consumer_receipt is not None
                else "shared_identity_policy_only_unencrypted_test_volume"
            )
            print(
                json.dumps(
                    {
                        "status": "pass",
                        "scope": scope,
                        "run_id": run_id,
                        "receipts": {name: str(path) for name, path in receipt_paths.items()},
                        "secret_leak_count": 0,
                    },
                    sort_keys=True,
                )
            )
            return 0

        verifier = [
            sys.executable,
            str(ROOT / "scripts/verify_production_object_store.py"),
            "--bootstrap-receipt",
            str(receipt_paths["bootstrap"]),
            "--backup-restore-receipt",
            str(receipt_paths["backup_restore"]),
            "--consumer-roundtrip-receipt",
            str(receipt_paths["consumer_roundtrip"]),
            "--ephemeral-cleanup-receipt",
            str(receipt_paths["ephemeral_cleanup"]),
            "--encryption-volume-receipt",
            str(args.encryption_volume_receipt),
            "--snapshot-restore-receipt",
            str(args.snapshot_restore_receipt),
            "--artifact",
            str(args.artifact),
            "--run-id",
            run_id,
            "--started-at",
            started_at,
        ]
        output = _run(verifier, env=env, secret_values=secret_values)
        print(output.strip())
        return 0
    except ProductionObjectStoreSmokeError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        if not args.keep_stack:
            subprocess.run(
                _compose_command(args.project_name, "down", "--volumes", "--remove-orphans"),
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            if owns_volume:
                subprocess.run(
                    ["docker", "volume", "rm", volume_name],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            subprocess.run(
                ["docker", "volume", "rm", f"{args.project_name}_object_store_receipts"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        shutil.rmtree(secrets_dir, ignore_errors=True)


def re_fullmatch_project_name(value: str) -> bool:
    return bool(value.startswith("geo-storage-hardening") and value.replace("-", "").isalnum())


if __name__ == "__main__":
    raise SystemExit(main())
