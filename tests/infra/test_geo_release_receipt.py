from __future__ import annotations

import json
from pathlib import Path

from scripts import geo_release_receipt


ROOT = Path(__file__).resolve().parents[2]


def test_read_release_commit_ignores_all_other_env_values(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        "SECRET_VALUE=must-never-appear\n"
        "GEO_RELEASE_COMMIT=0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )

    assert geo_release_receipt.read_release_commit(env_file) == (
        "0123456789abcdef0123456789abcdef01234567"
    )


def test_receipt_without_runtime_is_non_secret_and_reviewable(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        "SECRET_VALUE=must-never-appear\n"
        "GEO_RELEASE_COMMIT=0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )
    payload = geo_release_receipt.build_receipt(
        repo_root=ROOT,
        mode="internal",
        project="geo-receipt-test-project-that-does-not-exist",
        dify_project="geo-receipt-test-dify-that-does-not-exist",
        env_file=env_file,
        compose_files=(ROOT / "infra/docker-compose.yml",),
    )

    serialized = json.dumps(payload)
    assert payload["schema_version"] == "geo-release-receipt-v2"
    assert payload["containers"] == []
    assert payload["dify_containers"] == []
    assert payload["runtime_release_matches_source"] is False
    assert payload["missing_release_tracked_services"]
    assert payload["missing_dify_services"]
    assert payload["all_runtime_images_content_addressed"] is False
    assert "must-never-appear" not in serialized
    assert payload["compose_files"][0]["sha256"]


def test_write_receipt_is_private_and_atomic(tmp_path: Path) -> None:
    destination = tmp_path / "receipts" / "release.json"
    geo_release_receipt.write_receipt(destination, {"schema_version": "test"})

    assert json.loads(destination.read_text(encoding="utf-8"))["schema_version"] == "test"
    assert destination.stat().st_mode & 0o777 == 0o600


def test_release_match_requires_every_tracked_service_and_commit() -> None:
    commit = "a" * 40
    containers = [
        {"service": "internal-api", "release_commit": commit},
        {"service": "admin-web", "release_commit": commit},
        {"service": "postgres", "release_commit": None},
    ]
    complete = geo_release_receipt.release_match_summary(
        containers,
        tracked_services=("internal-api", "admin-web"),
        source_commit=commit,
        declared_release=commit,
    )
    assert complete["runtime_release_matches_source"] is True
    assert complete["missing_release_commit_services"] == []

    missing = geo_release_receipt.release_match_summary(
        containers[:1],
        tracked_services=("internal-api", "admin-web"),
        source_commit=commit,
        declared_release=commit,
    )
    assert missing["runtime_release_matches_source"] is False
    assert missing["missing_release_tracked_services"] == ["admin-web"]
