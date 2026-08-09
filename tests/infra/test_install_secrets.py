from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "deploy/install.sh"


def _write_keyring(path: Path, *, synthetic: bool = False) -> subprocess.CompletedProcess[str]:
    command = (
        f"source {INSTALLER}; "
        f"write_keyring {path} {'1' if synthetic else '0'}"
    )
    return subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_write_keyring_is_idempotent_and_preserves_ciphertext_keys(tmp_path: Path) -> None:
    path = tmp_path / "secret-store-keyring.json"
    first = _write_keyring(path)
    assert first.returncode == 0, first.stderr
    original = path.read_bytes()

    second = _write_keyring(path)
    assert second.returncode == 0, second.stderr
    assert path.read_bytes() == original
    payload = json.loads(original)
    assert str(payload["active_version"]) in payload["keys"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_write_keyring_rejects_existing_world_readable_secret(tmp_path: Path) -> None:
    path = tmp_path / "secret-store-keyring.json"
    assert _write_keyring(path).returncode == 0
    path.chmod(0o644)

    result = _write_keyring(path)

    assert result.returncode != 0
    assert "must not grant group or other access" in result.stderr


def test_write_keyring_rejects_invalid_existing_material_without_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "synthetic-keyring.json"
    path.write_text('{"schema_version": 1, "active_version": "1", "keys": {"1": "bad"}}\n')
    path.chmod(0o600)
    original = path.read_bytes()

    result = _write_keyring(path, synthetic=True)

    assert result.returncode != 0
    assert path.read_bytes() == original
    assert "not valid base64" in result.stderr


def test_prepare_only_is_documented_and_stops_before_runtime_configuration() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "--prepare-only" in installer
    assert "no Dify or GEO services were started or configured" in installer
    assert installer.index("if (( prepare_only )); then") < installer.index(
        '"${INSTALL_ROOT}/scripts/bootstrap_dify_runtime.sh" up'
    )

    result = subprocess.run(
        [str(INSTALLER), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--prepare-only" in result.stdout


def test_write_env_preserves_existing_database_identity_bindings(tmp_path: Path) -> None:
    env_path = tmp_path / "geo-stack.env"
    secret_root = tmp_path / "secrets"
    state_file = tmp_path / "dify-state.json"
    deepseek_file = tmp_path / "deepseek-key"
    existing = {
        "GEO_ADMIN_ACTOR_ID": "a0000000-0000-4000-8000-000000000001",
        "GEO_ADMIN_TENANT_ID": "a0000000-0000-4000-8000-000000000002",
        "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID": (
            "a0000000-0000-4000-8000-000000000003"
        ),
    }
    env_path.write_text(
        "GEO_RELEASE_COMMIT=old\n"
        + "".join(f"{key}={value}\n" for key, value in existing.items()),
        encoding="utf-8",
    )
    command = (
        f"source {INSTALLER}; "
        f"ENV_FILE={env_path}; RELEASE_SHA={'b' * 40}; SECRET_ROOT={secret_root}; "
        f"STATE_FILE={state_file}; DEEPSEEK_KEY_FILE={deepseek_file}; write_env"
    )

    result = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    configured = dict(
        line.split("=", 1)
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert configured["GEO_RELEASE_COMMIT"] == "b" * 40
    for key, value in existing.items():
        assert configured[key] == value
