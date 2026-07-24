from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.workflow_c_artifacts import composition


class _Cursor:
    def __init__(self, rows: tuple[dict[str, object], ...]) -> None:
        self._rows = rows

    def fetchall(self) -> tuple[dict[str, object], ...]:
        return self._rows


class _Connection:
    def __init__(self, rows: tuple[dict[str, object], ...]) -> None:
        self._rows = rows
        self.queries: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def execute(self, query: str) -> _Cursor:
        self.queries.append(query)
        return _Cursor(self._rows)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def test_api_writer_uses_read_only_canary_rpc_without_keyring_synchronization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyring = _write_keyring(tmp_path / "workflow-c-keyring.json")
    cipher = EnvelopeCipher(MasterKeyring(keys={1: b"A" * 32}, active_version=1))
    canary = cipher.create_canary(1)
    connection = _Connection(
        (
            {
                "master_key_version": 1,
                "status": "encrypt_decrypt",
                "algorithm": canary.algorithm,
                "canary_nonce": canary.nonce,
                "canary_ciphertext": canary.ciphertext,
                "retired_at": None,
            },
        )
    )
    store = object()
    monkeypatch.setattr(
        composition, "build_workflow_c_artifact_object_store", lambda _values: store
    )

    built = composition.build_workflow_c_artifact_api_writer_composition(
        connection_factory=lambda: connection,
        keyring_path=keyring,
    )

    assert built.object_store is store
    assert built.verified_master_key_versions == (1,)
    assert (connection.commits, connection.rollbacks, connection.closes) == (1, 0, 1)
    assert connection.queries[0] == "SET TRANSACTION READ ONLY"
    assert "geo_read_workflow_c_artifact_keyring_canaries()" in connection.queries[1]
    assert "workflow_c_artifact_master_key_versions" not in connection.queries[1]


def test_api_writer_rolls_back_when_canary_rpc_does_not_match_keyring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyring = _write_keyring(tmp_path / "workflow-c-keyring.json")
    connection = _Connection(())
    monkeypatch.setattr(
        composition,
        "build_workflow_c_artifact_object_store",
        lambda _values: pytest.fail("object store must not build after canary rejection"),
    )

    with pytest.raises(Exception, match="keyring does not match"):
        composition.build_workflow_c_artifact_api_writer_composition(
            connection_factory=lambda: connection,
            keyring_path=keyring,
        )

    assert (connection.commits, connection.rollbacks, connection.closes) == (0, 1, 1)


def _write_keyring(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "format": "geo-master-keyring-v1",
                "active_version": 1,
                "keys": {"1": base64.b64encode(b"A" * 32).decode("ascii")},
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path
