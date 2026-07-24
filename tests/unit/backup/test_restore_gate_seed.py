from __future__ import annotations

import base64
import json
from pathlib import Path
import stat

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest

from scripts.backup_restore_gate_seed_common import (
    KEYRING_FILES,
    RestoreGateSeedError,
    create_keyrings,
    current_head,
)


ROOT = Path(__file__).resolve().parents[3]


def test_current_head_is_resolved_from_the_single_alembic_graph() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    expected = ScriptDirectory.from_config(config).get_heads()

    assert expected == [current_head()]


def test_keyring_fixture_has_two_versions_and_independent_domains(tmp_path: Path) -> None:
    directory = tmp_path / "keys"
    directory.mkdir(mode=0o700)

    create_keyrings(directory)

    assert {path.name for path in directory.iterdir()} == set(KEYRING_FILES.values())
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in directory.iterdir())
    secret_v1 = _json(directory / KEYRING_FILES["secret_v1"])
    secret = _json(directory / KEYRING_FILES["secret_full"])
    provider = _json(directory / KEYRING_FILES["provider"])
    recommendation = _json(directory / KEYRING_FILES["recommendation"])
    synthetic = _json(directory / KEYRING_FILES["synthetic"])
    workflow_c = _json(directory / KEYRING_FILES["workflow_c"])
    assert secret_v1["active_version"] == 1
    assert (
        secret["active_version"]
        == provider["active_version"]
        == recommendation["active_version"]
        == workflow_c["active_version"]
        == 2
    )
    assert synthetic["active_version"] == "2"
    assert (
        set(secret["keys"])
        == set(provider["keys"])
        == set(recommendation["keys"])
        == set(synthetic["keys"])
        == set(workflow_c["keys"])
        == {
        "1",
        "2",
        }
    )
    assert secret_v1["keys"]["1"] == secret["keys"]["1"]
    domain_material = {
        *(base64.b64decode(value) for value in secret["keys"].values()),
        *(base64.b64decode(value) for value in provider["keys"].values()),
        *(base64.b64decode(value) for value in recommendation["keys"].values()),
        *(base64.b64decode(value) for value in synthetic["keys"].values()),
        *(base64.b64decode(value) for value in workflow_c["keys"].values()),
        base64.b64decode(
            (directory / KEYRING_FILES["request_hash"]).read_text(encoding="ascii")
        ),
    }
    assert len(domain_material) == 11
    assert all(len(value) == 32 for value in domain_material)


def test_keyring_fixture_rejects_weak_or_linked_directory(tmp_path: Path) -> None:
    weak = tmp_path / "weak"
    weak.mkdir(mode=0o755)
    with pytest.raises(RestoreGateSeedError, match="security"):
        create_keyrings(weak)

    secure = tmp_path / "secure"
    secure.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(secure, target_is_directory=True)
    with pytest.raises(RestoreGateSeedError, match="security"):
        create_keyrings(linked)


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    assert isinstance(payload, dict)
    return payload
