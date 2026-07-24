from __future__ import annotations

from pathlib import Path

import pytest

from scripts import scan_backup_plaintext_artifacts as scanner


SAFE_FILES = {
    "COMMITTED": b'{"backup_id":"safe"}\n',
    "manifest.json": b'{"schema_version":"geo-backup-manifest-v3"}\n',
    "manifest.sig": b'{"algorithm":"HMAC-SHA-256"}\n',
    "minio.tar.enc": b"encrypted-minio",
    "postgres.sql.gz.enc": b"encrypted-postgres",
}


def test_authenticated_bundle_and_receipt_pass_without_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _backup_run(tmp_path)
    bundle = _secure_directory(run / "bundle")
    for name, content in SAFE_FILES.items():
        _secure_file(bundle / name, content)
    _secure_file(run / "receipt.json", b'{"status":"passed"}\n')

    assert scanner.scan_backup_artifacts((run,)) == ()
    assert scanner.main([str(run)]) == 0
    output = capsys.readouterr().out
    assert "BACKUP_PLAINTEXT_SCAN_PASSED" in output
    assert "ERROR" not in output


def test_plaintext_and_unexpected_files_fail_without_leaking_object_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _backup_run(tmp_path)
    _secure_file(
        run / "postgres.sql.gz",
        b"\x1f\x8bprivate-database-canary",
        mode=0o644,
    )
    tar_head = bytearray(512)
    tar_head[257:262] = b"ustar"
    _secure_file(run / "minio.tar", bytes(tar_head))
    sensitive_name = "customer-object-private-name.json"
    sensitive_content = "private-object-content-canary"
    _secure_file(run / sensitive_name, sensitive_content.encode("ascii"))

    findings = scanner.scan_backup_artifacts((run,))

    assert len(findings) == 1
    assert findings[0].file_count == 3
    assert set(findings[0].categories) == {
        "gzip_plaintext",
        "permissions",
        "plaintext_backup_name",
        "tar_plaintext",
        "unexpected_backup_file",
    }
    assert scanner.main([str(run)]) == 2
    output = capsys.readouterr().out
    assert "BACKUP_PLAINTEXT_OR_WEAK_ARTIFACT" in output
    assert sensitive_name not in output
    assert sensitive_content not in output


def test_disclosed_legacy_root_is_aggregated_and_requires_explicit_allowance(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _backup_run(tmp_path)
    _secure_file(run / "postgres.sql.gz", b"legacy", mode=0o664)
    nested = _secure_directory(run / "minio" / "restored")
    _secure_file(nested / "private-object.json", b"legacy-object", mode=0o644)
    monkeypatch.setattr(scanner, "DISCLOSED_LEGACY_ROOTS", (run,))

    findings = scanner.scan_backup_artifacts((run,))

    assert len(findings) == 1
    assert findings[0].directory == run.absolute()
    assert findings[0].file_count == 2
    assert findings[0].disclosed_legacy is True
    assert scanner.main([str(run)]) == 3
    blocked_output = capsys.readouterr().out
    assert "PREEXISTING_BACKUP_PLAINTEXT" in blocked_output
    assert "private-object.json" not in blocked_output

    assert scanner.main(["--allow-disclosed-legacy", str(run)]) == 0
    allowed_output = capsys.readouterr().out
    assert "disclosed_legacy_directories=1" in allowed_output


def test_weak_permissions_symlink_and_missing_root_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _backup_run(tmp_path)
    _secure_file(run / "manifest.json", b"{}", mode=0o644)
    (run / "linked-artifact").symlink_to(run / "manifest.json")

    findings = scanner.scan_backup_artifacts((run,))

    assert len(findings) == 1
    assert set(findings[0].categories) == {"permissions", "symlink"}
    missing = tmp_path / "backup-restore-missing"
    assert scanner.main([str(missing)]) == 2
    assert "unsafe_root" in capsys.readouterr().out


def test_unrelated_evidence_files_are_outside_backup_scanner_scope(
    tmp_path: Path,
) -> None:
    artifacts = _secure_directory(tmp_path / "artifacts")
    browser = _secure_directory(artifacts / "browser-live")
    _secure_file(browser / "capture.json", b"{}", mode=0o644)

    assert scanner.scan_backup_artifacts((artifacts,)) == ()


def _backup_run(tmp_path: Path) -> Path:
    parent = _secure_directory(tmp_path / "backup-restore-smoke-authenticated")
    return _secure_directory(parent / "run-1")


def _secure_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _secure_file(path: Path, content: bytes, *, mode: int = 0o600) -> Path:
    path.write_bytes(content)
    path.chmod(mode)
    return path
