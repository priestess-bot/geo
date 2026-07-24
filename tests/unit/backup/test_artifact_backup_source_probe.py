from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import geo_worker.artifact_backup_source_probe as source_probe_module
from geo_core.restored_object_reader import VerifiedRestoredObjectReader
from geo_worker.artifact_backup_source_probe import (
    _ReadOnlyVerifiedObjectStore,
    main,
    run_source_probe,
)


def test_offline_source_store_reads_only_hash_verified_backup_objects(
    tmp_path: Path,
) -> None:
    root = tmp_path / "objects"
    root.mkdir(mode=0o700)
    payload = b"authenticated-backup-object"
    path = root / "recommendations" / "payload.bin"
    path.parent.mkdir()
    path.write_bytes(payload)
    expected_hash = hashlib.sha256(payload).hexdigest()
    store = _ReadOnlyVerifiedObjectStore(
        VerifiedRestoredObjectReader(root=root, bucket="geo-artifacts")
    )

    restored = store.get_s3_uri(
        uri="s3://geo-artifacts/recommendations/payload.bin",
        expected_hash=expected_hash,
    )

    assert restored.content == payload
    assert restored.content_hash == expected_hash
    with pytest.raises(RuntimeError, match="read-only"):
        store.put_object(key="x", content=b"x")
    with pytest.raises(RuntimeError, match="read-only"):
        store.delete_s3_uri(uri="s3://geo-artifacts/recommendations/payload.bin")


def test_source_probe_rejects_partial_offline_roots_before_reading_secrets(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="all offline backup object roots"):
        run_source_probe(snapshot_id=None, object_root=tmp_path)


def test_source_probe_debug_output_has_only_safe_error_metadata(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(**_: object) -> dict[str, object]:
        raise ValueError("marker-that-must-not-be-printed")

    monkeypatch.setenv("GEO_RESTORE_GATE_DEBUG", "1")
    monkeypatch.setattr(source_probe_module, "run_source_probe", fail)

    assert main(["--isolated-development-source"]) == 2

    stderr = capsys.readouterr().err
    assert "artifact backup source probe failed" in stderr
    assert "error=ValueError" in stderr
    assert "sqlstate=-" in stderr
    assert "marker-that-must-not-be-printed" not in stderr
