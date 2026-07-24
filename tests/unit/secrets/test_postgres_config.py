import base64
import json
from pathlib import Path

import pytest

from geo_core.secrets import SecretConfigurationError
from geo_core.secrets.postgres_config import (
    MASTER_KEYRING_ENV,
    REQUEST_HASH_KEY_ENV,
    load_postgres_crypto_config,
)


def test_unconfigured_postgres_secret_store_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MASTER_KEYRING_ENV, raising=False)
    monkeypatch.delenv(REQUEST_HASH_KEY_ENV, raising=False)
    assert load_postgres_crypto_config() is None


def test_postgres_secret_files_must_be_configured_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(MASTER_KEYRING_ENV, str(tmp_path / "keyring"))
    monkeypatch.delenv(REQUEST_HASH_KEY_ENV, raising=False)
    with pytest.raises(SecretConfigurationError, match="configured together"):
        load_postgres_crypto_config()


def test_postgres_secret_hash_key_rejects_bad_permissions_and_format(
    tmp_path: Path,
) -> None:
    keyring = _keyring(tmp_path / "keyring")
    request_key = tmp_path / "request-key"
    request_key.write_text("not-base64", encoding="ascii")
    request_key.chmod(0o644)
    with pytest.raises(SecretConfigurationError, match="security policy"):
        load_postgres_crypto_config(
            master_keyring_path=keyring,
            request_hash_key_path=request_key,
        )
    request_key.chmod(0o600)
    with pytest.raises(SecretConfigurationError, match="format is invalid"):
        load_postgres_crypto_config(
            master_keyring_path=keyring,
            request_hash_key_path=request_key,
        )


def test_valid_postgres_secret_files_load_without_rendering_key_material(
    tmp_path: Path,
) -> None:
    keyring = _keyring(tmp_path / "keyring")
    request_key = tmp_path / "request-key"
    request_key.write_text(base64.b64encode(b"H" * 32).decode("ascii"), encoding="ascii")
    request_key.chmod(0o600)
    config = load_postgres_crypto_config(
        master_keyring_path=keyring,
        request_hash_key_path=request_key,
    )
    assert config is not None
    assert config.keyring.versions == (1,)
    assert repr(config) == "SecretPostgresCryptoConfig([REDACTED])"
    assert (b"H" * 32).hex() not in repr(config)


def _keyring(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "active_version": 1,
                "keys": {"1": base64.b64encode(b"K" * 32).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path
