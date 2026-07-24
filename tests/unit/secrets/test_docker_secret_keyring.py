import base64
import json
from pathlib import Path

import pytest

from geo_core.secrets import (
    EnvelopeCipher,
    SecretConfigurationError,
    load_master_keyring_from_docker_secret,
)


KEY_V1 = bytes(range(32))
KEY_V2 = bytes(reversed(range(32)))


def test_loads_versioned_history_from_strict_owner_only_docker_secret(tmp_path: Path) -> None:
    secret_file = tmp_path / "master-keyring"
    _write_keyring(secret_file)

    keyring = load_master_keyring_from_docker_secret(secret_file)
    cipher = EnvelopeCipher(keyring)

    assert keyring.active_version == 2
    assert keyring.versions == (1, 2)
    cipher.verify_canary_set(cipher.create_all_canaries())
    assert KEY_V1.hex() not in repr(keyring)
    assert KEY_V2.hex() not in repr(keyring)


def test_owner_read_only_mode_is_accepted(tmp_path: Path) -> None:
    secret_file = tmp_path / "master-keyring"
    _write_keyring(secret_file)
    secret_file.chmod(0o400)

    assert load_master_keyring_from_docker_secret(secret_file).active_version == 2


def test_missing_keyring_fails_closed_without_environment_fallback(tmp_path: Path) -> None:
    with pytest.raises(SecretConfigurationError, match="unavailable"):
        load_master_keyring_from_docker_secret(tmp_path / "missing")


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o700, 0o777])
def test_group_or_world_permissions_are_rejected(tmp_path: Path, mode: int) -> None:
    secret_file = tmp_path / "master-keyring"
    _write_keyring(secret_file)
    secret_file.chmod(mode)

    with pytest.raises(SecretConfigurationError, match="too broad"):
        load_master_keyring_from_docker_secret(secret_file)


def test_symlink_is_rejected_even_when_target_permissions_are_safe(tmp_path: Path) -> None:
    target = tmp_path / "target"
    link = tmp_path / "master-keyring"
    _write_keyring(target)
    link.symlink_to(target)

    with pytest.raises(SecretConfigurationError, match="regular file"):
        load_master_keyring_from_docker_secret(link)


@pytest.mark.parametrize(
    "contents",
    [
        "not-json-ACTUAL-SENSITIVE-TEXT",
        '{"format":"geo-master-keyring-v1","active_version":1,"keys":{}}',
        '{"format":"geo-master-keyring-v1","active_version":1,"active_version":2,"keys":{}}',
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "active_version": 1,
                "keys": {"1": "not-base64-ACTUAL-SENSITIVE-TEXT"},
            }
        ),
    ],
)
def test_malformed_keyring_fails_without_echoing_file_contents(
    tmp_path: Path,
    contents: str,
) -> None:
    secret_file = tmp_path / "master-keyring"
    secret_file.write_text(contents, encoding="utf-8")
    secret_file.chmod(0o600)

    with pytest.raises(SecretConfigurationError) as caught:
        load_master_keyring_from_docker_secret(secret_file)

    assert "ACTUAL-SENSITIVE-TEXT" not in str(caught.value)


def _write_keyring(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "active_version": 2,
                "keys": {
                    "1": base64.b64encode(KEY_V1).decode("ascii"),
                    "2": base64.b64encode(KEY_V2).decode("ascii"),
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
