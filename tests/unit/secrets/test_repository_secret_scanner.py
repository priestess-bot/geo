from __future__ import annotations

from pathlib import Path

import pytest

from scripts import scan_repository_secrets as scanner


@pytest.mark.parametrize(
    ("name", "content", "category"),
    (
        ("plain.txt", b"AKIA" + b"0123456789ABCDEF", "aws_access_key"),
        ("plain.txt", b"AIza" + b"0123456789abcdefghijklmnopqrstuvwxyz", "google_api_key"),
        ("plain.txt", b"ghp_" + b"0123456789abcdefghijklmnopqrstuvwxyzAB", "github_token"),
        (
            "plain.txt",
            b"sk-proj-" + b"0123456789abcdefghijklmnopqrstuvwxyzABCDE",
            "openai_api_key",
        ),
        ("plain.txt", b"xoxb-" + b"1234567890-abcdefghijklmnopqrstuv", "slack_token"),
        ("plain.txt", b"sk_live_" + b"0123456789abcdefghijklmn", "stripe_live_key"),
        ("plain.txt", b"-----BEGIN " + b"PRIVATE KEY-----", "private_key"),
        ("production.env", b"harmless", "sensitive_file"),
    ),
)
def test_high_confidence_credentials_and_sensitive_files_are_rejected(
    tmp_path: Path,
    name: str,
    content: bytes,
    category: str,
) -> None:
    path = tmp_path / name
    path.write_bytes(content)

    findings = scanner.scan_paths((path,))

    assert len(findings) == 1
    assert category in findings[0].categories


def test_templates_placeholders_binary_and_large_files_do_not_false_positive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = tmp_path / ".env.example"
    template.write_text("PROVIDER_KEY=${PROVIDER_KEY:?required}\n", encoding="utf-8")
    binary = tmp_path / "fixture.bin"
    binary.write_bytes(b"\0AKIA" + b"0123456789ABCDEF")
    large = tmp_path / "large.txt"
    large.write_bytes(b"AKIA" + b"0123456789ABCDEF")
    monkeypatch.setattr(scanner, "_MAX_FILE_BYTES", 4)

    assert scanner.scan_paths((template, binary, large)) == ()


def test_cli_reports_path_and_category_without_echoing_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    token = "ghp_" + "0123456789abcdefghijklmnopqrstuvwxyzAB"
    path = tmp_path / "leaked.txt"
    path.write_text(token, encoding="utf-8")

    assert scanner.main([str(path)]) == 2

    output = capsys.readouterr().out
    assert "REPOSITORY_SECRET_DETECTED" in output
    assert "github_token" in output
    assert token not in output
