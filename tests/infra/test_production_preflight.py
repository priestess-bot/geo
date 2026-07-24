from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
import scripts.production_preflight as production_preflight

from scripts.production_preflight import (
    CONFIG_FILE_FIELDS,
    HTTPS_URL_FIELDS,
    IMAGE_FIELDS,
    INTEGER_BOUNDS,
    REQUIRED_TEXT_FIELDS,
    SECRET_FILE_FIELDS,
    main,
    parse_env_file,
    run_preflight,
)


@pytest.fixture(autouse=True)
def _host_security_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        production_preflight,
        "_application_secret_owner",
        lambda: (os.geteuid(), os.getegid()),
    )
    monkeypatch.setattr(production_preflight, "_filesystem_type", lambda path: "tmpfs")


def _valid_environment(tmp_path: Path) -> dict[str, str]:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(parents=True)
    values = {
        field: f"registry.example.com/geo/component:release@sha256:{'a' * 64}"
        for field in IMAGE_FIELDS
    }
    for index, field in enumerate(SECRET_FILE_FIELDS):
        secret = secret_dir / str(index)
        secret.write_text(f"secret-{index}", encoding="utf-8")
        secret.chmod(0o600)
        values[field] = str(secret)
    backup_key = base64.b64encode(b"B" * 32).decode("ascii")
    secret_key = base64.b64encode(b"S" * 32).decode("ascii")
    provider_key = base64.b64encode(b"P" * 32).decode("ascii")
    recommendation_key = base64.b64encode(b"R" * 32).decode("ascii")
    workflow_c_key = base64.b64encode(b"W" * 32).decode("ascii")
    synthetic_key = base64.b64encode(b"Y" * 32).decode("ascii")
    Path(values["GEO_BACKUP_KEYRING_FILE"]).write_text(
        json.dumps(
            {
                "active_version": 1,
                "format": "geo-backup-keyring-v1",
                "keys": [
                    {"key": backup_key, "status": "encrypt_decrypt", "version": 1}
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="ascii",
    )
    Path(values["GEO_SECRET_STORE_MASTER_KEYRING_FILE"]).write_text(
        json.dumps(
            {
                "active_version": 1,
                "format": "geo-master-keyring-v1",
                "keys": {"1": secret_key},
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="ascii",
    )
    Path(values["GEO_PROVIDER_ARTIFACT_KEYRING_FILE"]).write_text(
        json.dumps(
            {
                "active_version": 1,
                "format": "geo-master-keyring-v1",
                "keys": {"1": provider_key},
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="ascii",
    )
    Path(values["GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"]).write_text(
        json.dumps(
            {
                "active_version": "1",
                "keys": {"1": synthetic_key},
                "schema_version": 1,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="ascii",
    )
    Path(values["GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE"]).write_text(
        json.dumps(
            {
                "active_version": 1,
                "format": "geo-master-keyring-v1",
                "keys": {"1": recommendation_key},
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="ascii",
    )
    Path(values["GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE"]).write_text(
        json.dumps(
            {
                "active_version": 1,
                "format": "geo-master-keyring-v1",
                "keys": {"1": workflow_c_key},
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="ascii",
    )
    Path(values["GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"]).write_text(
        base64.b64encode(b"H" * 32).decode("ascii"),
        encoding="ascii",
    )
    values.update(
        {
            field: "https://service.example.com/path" for field in HTTPS_URL_FIELDS
        }
    )
    backup_root = tmp_path / "backups"
    backup_root.mkdir(mode=0o700)
    backup_root.chmod(0o700)
    restore_tmpfs_root = tmp_path / "restore-tmpfs"
    restore_tmpfs_root.mkdir(mode=0o700)
    restore_tmpfs_root.chmod(0o700)
    registry_source = (
        Path(__file__).resolve().parents[2] / "infra" / "style-adapter-registry.v1.json"
    )
    registry = tmp_path / "style-adapter-registry.v1.json"
    registry.write_bytes(registry_source.read_bytes())
    registry.chmod(0o444)
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    registry_hosts = {
        host
        for adapter in registry_payload["adapters"]
        for host in adapter["allowed_resource_hosts"]
    }
    values.update(
        {
            "GEO_JWT_AUDIENCE": "geo-admin",
            "GEO_ADMIN_OIDC_ALLOWED_ORIGINS": "https://auth.example.com",
            "GEO_RELEASE_VERSION": "2026.07.19-rc1",
            "GEO_BACKUP_ROOT": str(backup_root),
            "GEO_BACKUP_MINIO_STAGING_SIZE": "8g",
            "GEO_RESTORE_TMPFS_ROOT": str(restore_tmpfs_root),
            "GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS": "2",
            "GEO_READINESS_TOTAL_TIMEOUT_SECONDS": "5",
            "GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS": "10",
            "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS": "30",
            "GEO_RUNTIME_QUEUED_STALE_SECONDS": "600",
            "GEO_RUNTIME_OUTBOX_STALE_SECONDS": "300",
            "GEO_RUNTIME_RUNNING_GRACE_SECONDS": "60",
            "GEO_RUNTIME_FAILURE_WINDOW_SECONDS": "86400",
            "GEO_RUNTIME_EXPECTED_TASK_WORKER_INSTANCES": "4",
            "GEO_RUNTIME_EXPECTED_OUTBOX_RELAY_INSTANCES": "1",
            "GEO_RUNTIME_EXPECTED_STYLE_BROWSER_WORKER_INSTANCES": "1",
            "GEO_RUNTIME_EXPECTED_SYNTHETIC_ARTIFACT_MAINTENANCE_WORKER_INSTANCES": "1",
            "GEO_RUNTIME_EXPECTED_WORKFLOW_C_MAINTENANCE_WORKER_INSTANCES": "1",
            "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID": "d9e70000-0000-0000-0000-000000000001",
            "GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID": "d9e70000-0000-0000-0000-000000000002",
            "GEO_RESTORE_PROBE_SERVICE_IDENTITY_ID": "d9e70000-0000-0000-0000-000000000003",
            "GEO_RESTORE_SECRET_REFERENCE_ID": "d9e70000-0000-0000-0000-000000000004",
            "GEO_RESTORE_SECRET_PROJECT_ID": "d9e70000-0000-0000-0000-000000000005",
            "GEO_RESTORE_SECRET_PURPOSE": "restore_probe.canary",
            "GEO_RESTORE_SECRET_VERSION": "1",
            "GEO_RESTORE_SECRET_IDEMPOTENCY_KEY": "restore-probe-frozen-resolve-v1",
            "GEO_WORKFLOW_C_ARTIFACT_MAINTENANCE_JOB_LEASE_SECONDS": "300",
            "GEO_WORKFLOW_C_ARTIFACT_STAGED_GRACE_SECONDS": "900",
            "GEO_WORKFLOW_C_ARTIFACT_DELETION_LEASE_SECONDS": "120",
            "GEO_WORKFLOW_C_ARTIFACT_MAX_DELETIONS_PER_JOB": "100",
            "GEO_SYNTHETIC_ARTIFACT_MAINTENANCE_POLL_SECONDS": "60",
            "GEO_SYNTHETIC_ARTIFACT_MAINTENANCE_JOB_LEASE_SECONDS": "300",
            "GEO_SYNTHETIC_ARTIFACT_EXPIRY_BATCH_SIZE": "100",
            "GEO_SYNTHETIC_ARTIFACT_DELETION_LEASE_SECONDS": "120",
            "GEO_SYNTHETIC_ARTIFACT_MAX_DELETIONS_PER_JOB": "100",
            "GEO_STYLE_ROBOTS_TIMEOUT_SECONDS": "10",
            "GEO_STYLE_COLLECTION_COMPOSITION_FACTORY": (
                "geo_style_worker.composition:"
                "build_style_collection_dispatcher"
            ),
            "GEO_STYLE_ALLOWED_EGRESS_HOSTS": (
                ",".join(sorted(registry_hosts | {"approved.example", "robots-approved.example"}))
            ),
            "GEO_STYLE_CHROMIUM_EXECUTABLE": (
                "/ms-playwright/chromium-1234/chrome-linux/headless_shell"
            ),
            "GEO_STYLE_ADAPTER_REGISTRY_FILE": str(registry),
            "GEO_STYLE_ADAPTER_REGISTRY_SHA256": hashlib.sha256(
                registry.read_bytes()
            ).hexdigest(),
            "GEO_ALERT_SMTP_UPSTREAM_HOST": "smtp.example.com",
            "GEO_ALERT_SMTP_UPSTREAM_ALLOWED_HOSTS": "smtp.example.com",
            "GEO_ALERT_SMTP_UPSTREAM_PORT": "587",
            "GEO_ALERT_SMTP_TLS_MODE": "starttls",
            "GEO_ALERT_SMTP_SENDER": "geo-alerts@example.com",
            "GEO_ALERT_SMTP_RECIPIENTS": "geo-ops@example.com",
            "GEO_ALERT_WEBHOOK_ALLOWED_HOSTS": "alerts.intranet.example",
        }
    )
    values["GEO_ALERT_WEBHOOK_ENDPOINT"] = (
        "https://alerts.intranet.example/hooks/geo"
    )
    return values


def _write_environment(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )


def _issue_pairs(path: Path) -> set[tuple[str, str]]:
    return {(issue.code, issue.field) for issue in run_preflight(path)}


def test_preflight_accepts_complete_digest_pinned_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_path = tmp_path / "production.env"
    _write_environment(env_path, _valid_environment(tmp_path))

    assert main(["--env-file", str(env_path)]) == 0
    output = capsys.readouterr().out
    assert output == "OK code=PRODUCTION_PREFLIGHT_PASSED field=CONFIG\n"
    assert str(tmp_path) not in output


@pytest.mark.parametrize(
    ("field", "replacement", "expected_code"),
    [
        ("GEO_API_IMAGE", "registry.example.com/geo/api:latest", "IMAGE_NOT_DIGEST_PINNED"),
        ("GEO_RELEASE_VERSION", "replace-with-release", "RELEASE_VERSION_INVALID"),
        ("GEO_OIDC_DISCOVERY_URL", "http://identity.example.com/oidc", "URL_NOT_HTTPS"),
        ("GEO_READINESS_TOTAL_TIMEOUT_SECONDS", "2", "READINESS_TOTAL_NOT_GREATER"),
        (
            "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS",
            "10",
            "HEARTBEAT_STALE_NOT_GREATER",
        ),
        ("GEO_RUNTIME_FAILURE_WINDOW_SECONDS", "forever", "THRESHOLD_NOT_INTEGER"),
        (
            "GEO_RUNTIME_EXPECTED_TASK_WORKER_INSTANCES",
            "0",
            "THRESHOLD_OUT_OF_RANGE",
        ),
        (
            "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID",
            "not-a-uuid",
            "SERVICE_IDENTITY_UUID_INVALID",
        ),
        ("GEO_BACKUP_MINIO_STAGING_SIZE", "8g,exec", "MEMORY_SIZE_INVALID"),
        (
            "GEO_RUNTIME_EXPECTED_STYLE_BROWSER_WORKER_INSTANCES",
            "2",
            "THRESHOLD_OUT_OF_RANGE",
        ),
        (
            "GEO_STYLE_COLLECTION_COMPOSITION_FACTORY",
            "untrusted.module:factory",
            "STYLE_FACTORY_INVALID",
        ),
        (
            "GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID",
            "not-a-uuid",
            "STYLE_SERVICE_IDENTITY_INVALID",
        ),
        (
            "GEO_STYLE_ALLOWED_EGRESS_HOSTS",
            "*.example.com,localhost",
            "STYLE_EGRESS_ALLOWLIST_INVALID",
        ),
        (
            "GEO_STYLE_CHROMIUM_EXECUTABLE",
            "/usr/bin/chromium",
            "STYLE_CHROMIUM_PATH_INVALID",
        ),
        (
            "GEO_ALERT_SMTP_UPSTREAM_ALLOWED_HOSTS",
            "*.example.com,localhost",
            "ALERT_SMTP_ALLOWLIST_INVALID",
        ),
        (
            "GEO_ALERT_WEBHOOK_ENDPOINT",
            "https://forged.example.com/hook",
            "ALERT_WEBHOOK_ENDPOINT_INVALID",
        ),
    ],
)
def test_preflight_rejects_invalid_configuration_matrix(
    tmp_path: Path, field: str, replacement: str, expected_code: str
) -> None:
    values = _valid_environment(tmp_path)
    values[field] = replacement
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    assert (expected_code, field) in _issue_pairs(env_path)


def test_preflight_rejects_missing_empty_and_overbroad_secret_files(tmp_path: Path) -> None:
    values = _valid_environment(tmp_path)
    missing_field = "GEO_DEEPSEEK_API_KEY_FILE"
    empty_field = "GEO_AUTH_TOKEN_SECRET_FILE"
    permission_field = "GEO_DATABASE_URL_FILE"
    Path(values[missing_field]).unlink()
    Path(values[empty_field]).write_bytes(b"")
    Path(values[permission_field]).chmod(0o640)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    issues = _issue_pairs(env_path)
    assert ("SECRET_FILE_NOT_FOUND", missing_field) in issues
    assert ("SECRET_FILE_EMPTY", empty_field) in issues
    assert ("SECRET_FILE_PERMISSIONS", permission_field) in issues

    Path(values[permission_field]).chmod(0o200)
    assert ("SECRET_FILE_PERMISSIONS", permission_field) in _issue_pairs(env_path)


@pytest.mark.parametrize("content", (b"   ", b"\n\r\n\t"))
def test_preflight_rejects_whitespace_only_secret_without_rendering_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: bytes,
) -> None:
    values = _valid_environment(tmp_path)
    field = "GEO_DEEPSEEK_API_KEY_FILE"
    Path(values[field]).write_bytes(content)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    assert main(["--env-file", str(env_path)]) == 2
    output = capsys.readouterr().out
    assert f"ERROR code=SECRET_FILE_EMPTY field={field}" in output
    assert repr(content) not in output


def test_preflight_reads_secret_files_with_a_fixed_upper_bound(tmp_path: Path) -> None:
    values = _valid_environment(tmp_path)
    field = "GEO_DEEPSEEK_API_KEY_FILE"
    Path(values[field]).write_bytes(b"x" * 65_537)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    assert ("SECRET_FILE_TOO_LARGE", field) in _issue_pairs(env_path)


def test_preflight_rejects_keyring_symlinks_format_and_path_collisions(tmp_path: Path) -> None:
    values = _valid_environment(tmp_path)
    backup_keyring = Path(values["GEO_BACKUP_KEYRING_FILE"])
    backup_keyring.write_text("BACKUP-KEY-CANARY-MUST-NOT-LEAK", encoding="ascii")
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)
    assert (
        "SECRET_CONTENT_INVALID",
        "GEO_BACKUP_KEYRING_FILE",
    ) in _issue_pairs(env_path)

    values = _valid_environment(tmp_path / "symlink-case")
    keyring = Path(values["GEO_BACKUP_KEYRING_FILE"])
    link = keyring.with_name("backup-keyring-link")
    link.symlink_to(keyring)
    values["GEO_BACKUP_KEYRING_FILE"] = str(link)
    env_path = tmp_path / "symlink.env"
    _write_environment(env_path, values)
    assert ("SECRET_FILE_NOT_REGULAR", "GEO_BACKUP_KEYRING_FILE") in _issue_pairs(
        env_path
    )

    values = _valid_environment(tmp_path / "collision-case")
    values["GEO_BACKUP_KEYRING_FILE"] = values["GEO_SECRET_STORE_MASTER_KEYRING_FILE"]
    env_path = tmp_path / "collision.env"
    _write_environment(env_path, values)
    assert ("SECRET_PATH_COLLISION", "GEO_BACKUP_KEYRING_FILE") in _issue_pairs(env_path)


def test_preflight_rejects_artifact_keyring_format_and_request_hash_key(
    tmp_path: Path,
) -> None:
    values = _valid_environment(tmp_path)
    Path(values["GEO_PROVIDER_ARTIFACT_KEYRING_FILE"]).write_text(
        '{"format":"wrong","active_version":1,"keys":{"1":"invalid"}}',
        encoding="ascii",
    )
    Path(values["GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"]).write_text(
        base64.b64encode(b"short").decode("ascii"),
        encoding="ascii",
    )
    Path(values["GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"]).write_text(
        json.dumps(
            {
                "active_version": "v1",
                "keys": {"v1": base64.b64encode(b"Y" * 32).decode("ascii")},
                "schema_version": 1,
            }
        ),
        encoding="ascii",
    )
    Path(values["GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE"]).write_text(
        '{"format":"wrong","active_version":1,"keys":{"1":"invalid"}}',
        encoding="ascii",
    )
    Path(values["GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE"]).write_text(
        '{"format":"wrong","active_version":1,"keys":{"1":"invalid"}}',
        encoding="ascii",
    )
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    issues = _issue_pairs(env_path)
    assert (
        "SECRET_CONTENT_INVALID",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
    ) in issues
    assert (
        "SECRET_CONTENT_INVALID",
        "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE",
    ) in issues
    assert (
        "SECRET_CONTENT_INVALID",
        "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE",
    ) in issues
    assert (
        "SECRET_CONTENT_INVALID",
        "GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE",
    ) in issues
    assert (
        "SECRET_CONTENT_INVALID",
        "GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE",
    ) in issues


def test_preflight_requires_0600_for_every_application_keyring(
    tmp_path: Path,
) -> None:
    values = _valid_environment(tmp_path)
    for field in (
        "GEO_SECRET_STORE_MASTER_KEYRING_FILE",
        "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
        "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE",
        "GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE",
    ):
        Path(values[field]).chmod(0o400)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    issues = _issue_pairs(env_path)
    for field in (
        "GEO_SECRET_STORE_MASTER_KEYRING_FILE",
        "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
        "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE",
        "GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE",
    ):
        assert ("SECRET_FILE_PERMISSIONS", field) in issues


def test_preflight_rejects_keyring_hardlinks_and_exact_content_reuse(
    tmp_path: Path,
) -> None:
    values = _valid_environment(tmp_path)
    provider = Path(values["GEO_PROVIDER_ARTIFACT_KEYRING_FILE"])
    synthetic = Path(values["GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"])
    provider.unlink()
    os.link(synthetic, provider)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    issues = _issue_pairs(env_path)
    for field in (
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
        "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE",
    ):
        assert ("SECRET_INODE_COLLISION", field) in issues
        assert ("SECRET_CONTENT_REUSED", field) in issues


def test_preflight_rejects_reformatted_reuse_of_key_material(tmp_path: Path) -> None:
    values = _valid_environment(tmp_path)
    provider = Path(values["GEO_PROVIDER_ARTIFACT_KEYRING_FILE"])
    synthetic = Path(values["GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"])
    synthetic_payload = json.loads(synthetic.read_text(encoding="ascii"))
    provider.write_text(
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "keys": {"1": synthetic_payload["keys"]["1"]},
                "active_version": 1,
            },
            indent=2,
            sort_keys=False,
        ),
        encoding="ascii",
    )
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    issues = _issue_pairs(env_path)
    assert (
        "SECRET_KEY_MATERIAL_REUSED",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
    ) in issues
    assert (
        "SECRET_KEY_MATERIAL_REUSED",
        "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE",
    ) in issues
    assert (
        "SECRET_CONTENT_REUSED",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
    ) not in issues


def test_preflight_isolates_restore_password_from_every_key_domain(
    tmp_path: Path,
) -> None:
    values = _valid_environment(tmp_path)
    restore_password = Path(values["GEO_RESTORE_SMOKE_PASSWORD_FILE"])
    restore_password.write_text(base64.b64encode(b"P" * 32).decode("ascii"), encoding="ascii")
    restore_password.chmod(0o600)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    issues = _issue_pairs(env_path)
    assert (
        "SECRET_KEY_MATERIAL_REUSED",
        "GEO_RESTORE_SMOKE_PASSWORD_FILE",
    ) in issues
    assert (
        "SECRET_KEY_MATERIAL_REUSED",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
    ) in issues


def test_preflight_rejects_style_registry_permissions_digest_and_schema(
    tmp_path: Path,
) -> None:
    values = _valid_environment(tmp_path)
    registry = Path(values["GEO_STYLE_ADAPTER_REGISTRY_FILE"])
    registry.chmod(0o644)
    values["GEO_STYLE_ADAPTER_REGISTRY_SHA256"] = "0" * 64
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    issues = _issue_pairs(env_path)
    assert (
        "STYLE_REGISTRY_FILE_PERMISSIONS",
        "GEO_STYLE_ADAPTER_REGISTRY_FILE",
    ) in issues
    assert (
        "STYLE_REGISTRY_DIGEST_MISMATCH",
        "GEO_STYLE_ADAPTER_REGISTRY_SHA256",
    ) in issues

    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["adapters"] = [
        item for item in payload["adapters"] if item["channel"] != "quora"
    ]
    registry.write_text(json.dumps(payload), encoding="utf-8")
    registry.chmod(0o444)
    values["GEO_STYLE_ADAPTER_REGISTRY_SHA256"] = hashlib.sha256(
        registry.read_bytes()
    ).hexdigest()
    _write_environment(env_path, values)
    assert (
        "STYLE_REGISTRY_CONTENT_INVALID",
        "GEO_STYLE_ADAPTER_REGISTRY_FILE",
    ) in _issue_pairs(env_path)


def test_preflight_rejects_style_registry_symlink(tmp_path: Path) -> None:
    values = _valid_environment(tmp_path)
    registry = Path(values["GEO_STYLE_ADAPTER_REGISTRY_FILE"])
    link = registry.with_name("style-adapter-registry-link.json")
    link.symlink_to(registry)
    values["GEO_STYLE_ADAPTER_REGISTRY_FILE"] = str(link)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    assert (
        "STYLE_REGISTRY_FILE_NOT_REGULAR",
        "GEO_STYLE_ADAPTER_REGISTRY_FILE",
    ) in _issue_pairs(env_path)


def test_preflight_requires_registry_resource_hosts_in_global_egress_allowlist(
    tmp_path: Path,
) -> None:
    values = _valid_environment(tmp_path)
    values["GEO_STYLE_ALLOWED_EGRESS_HOSTS"] = values[
        "GEO_STYLE_ALLOWED_EGRESS_HOSTS"
    ].replace(",www.redditstatic.com", "")
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    assert (
        "STYLE_REGISTRY_EGRESS_NOT_ALLOWED",
        "GEO_STYLE_ALLOWED_EGRESS_HOSTS",
    ) in _issue_pairs(env_path)


def test_preflight_rejects_keys_inside_backup_root_and_non_0700_root(tmp_path: Path) -> None:
    values = _valid_environment(tmp_path)
    backup_root = Path(values["GEO_BACKUP_ROOT"])
    inside = backup_root / "backup-keyring.json"
    inside.write_bytes(Path(values["GEO_BACKUP_KEYRING_FILE"]).read_bytes())
    inside.chmod(0o600)
    values["GEO_BACKUP_KEYRING_FILE"] = str(inside)
    backup_root.chmod(0o750)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    issues = _issue_pairs(env_path)
    assert ("SECRET_INSIDE_BACKUP_ROOT", "GEO_BACKUP_KEYRING_FILE") in issues
    assert ("DIRECTORY_PERMISSIONS", "GEO_BACKUP_ROOT") in issues


def test_preflight_rejects_non_tmpfs_restore_root_and_path_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = _valid_environment(tmp_path)
    monkeypatch.setattr(production_preflight, "_filesystem_type", lambda path: "ext4")
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    assert ("DIRECTORY_NOT_TMPFS", "GEO_RESTORE_TMPFS_ROOT") in _issue_pairs(env_path)

    monkeypatch.setattr(production_preflight, "_filesystem_type", lambda path: "tmpfs")
    values["GEO_RESTORE_TMPFS_ROOT"] = values["GEO_BACKUP_ROOT"]
    _write_environment(env_path, values)
    assert ("DIRECTORY_PATH_COLLISION", "GEO_RESTORE_TMPFS_ROOT") in _issue_pairs(
        env_path
    )


def test_preflight_rejects_backup_and_application_key_owner_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host_euid = os.geteuid()
    host_egid = os.getegid()
    values = _valid_environment(tmp_path)
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    monkeypatch.setattr(
        production_preflight,
        "_application_secret_owner",
        lambda: (host_euid + 1000, host_egid + 1000),
    )
    issues = _issue_pairs(env_path)
    assert (
        "SECRET_FILE_OWNER",
        "GEO_SECRET_STORE_MASTER_KEYRING_FILE",
    ) in issues
    assert (
        "SECRET_FILE_OWNER",
        "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE",
    ) in issues
    assert (
        "SECRET_FILE_OWNER",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
    ) in issues
    assert (
        "SECRET_FILE_OWNER",
        "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE",
    ) in issues
    assert (
        "SECRET_FILE_OWNER",
        "GEO_STYLE_BROWSER_WORKER_DATABASE_URL_FILE",
    ) in issues
    assert (
        "SECRET_FILE_OWNER",
        "GEO_RESTORE_SMOKE_PASSWORD_FILE",
    ) in issues

    monkeypatch.setattr(
        production_preflight,
        "_application_secret_owner",
        lambda: (host_euid, host_egid),
    )
    monkeypatch.setattr(production_preflight.os, "geteuid", lambda: host_euid + 1000)
    assert ("SECRET_FILE_OWNER", "GEO_BACKUP_KEYRING_FILE") in _issue_pairs(env_path)


def test_application_secret_owner_matches_api_container_identity() -> None:
    assert production_preflight.APPLICATION_SECRET_UID == 10001
    assert production_preflight.APPLICATION_SECRET_GID == 10001


def test_preflight_rejects_missing_required_configuration(tmp_path: Path) -> None:
    values = _valid_environment(tmp_path)
    del values["GEO_JWT_AUDIENCE"]
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    assert ("CONFIG_REQUIRED", "GEO_JWT_AUDIENCE") in _issue_pairs(env_path)


def test_preflight_reports_only_stable_codes_and_field_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    values = _valid_environment(tmp_path)
    sensitive_value = "do-not-leak-this-audience"
    sensitive_path = "do-not-leak-this-secret-path"
    values["GEO_JWT_AUDIENCE"] = sensitive_value
    values["GEO_DEEPSEEK_API_KEY_FILE"] = sensitive_path
    values["GEO_API_IMAGE"] = "replace-this-image"
    env_path = tmp_path / "production.env"
    _write_environment(env_path, values)

    assert main(["--env-file", str(env_path)]) == 2
    output = capsys.readouterr().out
    assert sensitive_value not in output
    assert sensitive_path not in output
    assert "replace-this-image" not in output
    assert "field=GEO_DEEPSEEK_API_KEY_FILE" in output
    assert "field=GEO_API_IMAGE" in output


def test_env_parser_does_not_evaluate_shell_and_rejects_duplicate_keys(tmp_path: Path) -> None:
    touched = tmp_path / "must-not-exist"
    env_path = tmp_path / "production.env"
    env_path.write_text(
        f"GEO_JWT_AUDIENCE=$(touch {touched})\n"
        "GEO_JWT_AUDIENCE=duplicate\n",
        encoding="utf-8",
    )

    values, issues = parse_env_file(env_path)

    assert values["GEO_JWT_AUDIENCE"].startswith("$(touch ")
    assert not touched.exists()
    assert [(issue.code, issue.field) for issue in issues] == [
        ("ENV_KEY_DUPLICATE", "GEO_JWT_AUDIENCE")
    ]


def test_production_example_covers_every_preflight_field() -> None:
    example_path = Path(__file__).resolve().parents[2] / "infra" / "production.env.example"
    values, issues = parse_env_file(example_path)

    assert not issues
    assert set(IMAGE_FIELDS) <= values.keys()
    assert set(SECRET_FILE_FIELDS) <= values.keys()
    assert set(CONFIG_FILE_FIELDS) <= values.keys()
    assert set(HTTPS_URL_FIELDS) <= values.keys()
    assert set(REQUIRED_TEXT_FIELDS) <= values.keys()
    assert set(INTEGER_BOUNDS) <= values.keys()

    registry = example_path.with_name("style-adapter-registry.v1.json")
    assert values["GEO_STYLE_ADAPTER_REGISTRY_SHA256"] == hashlib.sha256(
        registry.read_bytes()
    ).hexdigest()
    payload = json.loads(registry.read_text(encoding="utf-8"))
    authenticated = [
        item
        for item in payload["adapters"]
        if item["channel"] == "reddit"
        and item["adapter_release"] == "authenticated-v1"
    ]
    assert len(authenticated) == 1
    assert authenticated[0]["login_flow"]["login_url"] == (
        "https://www.reddit.com/login/"
    )
    assert authenticated[0]["admission_state"] == "reviewed_fixture"
    assert "www.reddit.com" in authenticated[0]["allowed_resource_hosts"]
    assert {
        item["admission_state"] for item in payload["adapters"]
    } == {"reviewed_fixture"}


def test_production_compose_entrypoint_cannot_bypass_preflight() -> None:
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(encoding="utf-8")

    assert "production-preflight:" in makefile
    assert "production-config: production-preflight" in makefile
    assert "scripts/production_preflight.py --env-file $(PROD_ENV)" in makefile
