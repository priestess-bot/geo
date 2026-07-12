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


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "infra/docker-compose.yml"
PRODUCTION_COMPOSE = ROOT / "infra/docker-compose.production.yml"
MC_IMAGE = "minio/mc:RELEASE.2025-02-21T16-00-46Z"


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
    secrets_dir = Path(tempfile.mkdtemp(prefix="geno-object-store-secrets-"))

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
    env = os.environ.copy()
    for name, value in values.items():
        path = secrets_dir / name
        _write_secret(path, value)
        env[host_variables[name]] = str(path)
    env.update(
        {
            "COMPOSE_PROJECT_NAME": args.project_name,
            "GENO_MINIO_ENCRYPTED_VOLUME_NAME": volume_name,
            "GENO_MINIO_HOST_PORT": str(minio_port),
            "GENO_MINIO_CONSOLE_HOST_PORT": str(console_port),
            "OBJECT_STORE_BACKUP_PREFIX": "production/smoke-environment/",
            "OBJECT_STORE_BACKUP_SMOKE_PREFIX": f"smoke/{run_id}/",
            "OBJECT_STORE_RESTORE_PREFIX": f"restore-smoke/{run_id}/",
            "OBJECT_STORE_RETENTION_PREFIX": f"retention-approved/{run_id}/",
            "MINIO_BOOTSTRAP_ENABLE_EPHEMERAL": "1",
            "GENO_CONNECTOR_SECRET_MASTER_KEY": secrets.token_urlsafe(32),
            "GENO_REPORT_ARTIFACT_SIGNING_SECRET": secrets.token_urlsafe(32),
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
        consumer_receipt = _read_receipt_volume(
            args.project_name, "consumer-roundtrip.json", env=env, secrets_=secret_values
        )
        receipt_paths = {
            "bootstrap": artifact_dir / "bootstrap.json",
            "backup_restore": artifact_dir / "backup-restore.json",
            "consumer_roundtrip": artifact_dir / "consumer-roundtrip.json",
        }
        for name, payload in (
            ("bootstrap", bootstrap_receipt),
            ("backup_restore", backup_receipt),
            ("consumer_roundtrip", consumer_receipt),
        ):
            receipt_paths[name].write_text(
                json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
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
            print(
                json.dumps(
                    {
                        "status": "pass",
                        "scope": "policy_only_unencrypted_test_volume",
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
                _compose_command(args.project_name, "down", "--remove-orphans"),
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
