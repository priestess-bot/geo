from __future__ import annotations

from pathlib import Path

import pytest

from scripts.production_preflight import (
    HTTPS_URL_FIELDS,
    IMAGE_FIELDS,
    INTEGER_BOUNDS,
    REQUIRED_TEXT_FIELDS,
    SECRET_FILE_FIELDS,
    main,
    parse_env_file,
    run_preflight,
)


def _valid_environment(tmp_path: Path) -> dict[str, str]:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    values = {
        field: f"registry.example.com/geo/component:release@sha256:{'a' * 64}"
        for field in IMAGE_FIELDS
    }
    for index, field in enumerate(SECRET_FILE_FIELDS):
        secret = secret_dir / str(index)
        secret.write_text(f"secret-{index}", encoding="utf-8")
        secret.chmod(0o600)
        values[field] = str(secret)
    values.update(
        {
            field: "https://service.example.com/path" for field in HTTPS_URL_FIELDS
        }
    )
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    values.update(
        {
            "GEO_JWT_AUDIENCE": "geo-admin",
            "GEO_ADMIN_OIDC_ALLOWED_ORIGINS": "https://auth.example.com",
            "GEO_RELEASE_VERSION": "2026.07.19-rc1",
            "GEO_BACKUP_ROOT": str(backup_root),
            "GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS": "2",
            "GEO_READINESS_TOTAL_TIMEOUT_SECONDS": "5",
            "GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS": "10",
            "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS": "30",
            "GEO_RUNTIME_QUEUED_STALE_SECONDS": "600",
            "GEO_RUNTIME_OUTBOX_STALE_SECONDS": "300",
            "GEO_RUNTIME_RUNNING_GRACE_SECONDS": "60",
            "GEO_RUNTIME_FAILURE_WINDOW_SECONDS": "86400",
            "GEO_RUNTIME_EXPECTED_TASK_WORKER_INSTANCES": "2",
            "GEO_RUNTIME_EXPECTED_OUTBOX_RELAY_INSTANCES": "1",
        }
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
    assert set(HTTPS_URL_FIELDS) <= values.keys()
    assert set(REQUIRED_TEXT_FIELDS) <= values.keys()
    assert set(INTEGER_BOUNDS) <= values.keys()


def test_production_compose_entrypoint_cannot_bypass_preflight() -> None:
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(encoding="utf-8")

    assert "production-preflight:" in makefile
    assert "production-config: production-preflight" in makefile
    assert "scripts/production_preflight.py --env-file $(PROD_ENV)" in makefile
