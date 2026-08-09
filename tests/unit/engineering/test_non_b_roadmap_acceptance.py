from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.non_b_roadmap_acceptance as acceptance
from scripts.non_b_roadmap_acceptance import (
    AcceptanceRegisterError,
    DEFAULT_OUTPUT,
    DEFAULT_POLICY,
    build_register,
    export_register,
    verify_register,
)


ROOT = Path(__file__).resolve().parents[3]


def test_classification_resolves_every_roadmap_id_without_local_gaps() -> None:
    register = build_register(policy_path=DEFAULT_POLICY, output=DEFAULT_OUTPUT)

    assert register["summary"] == {
        "all": 330,
        "templates": 13,
        "excluded_b": 49,
        "mixed_atomic": 68,
        "included_non_b": 268,
        "local_gap": 0,
        "ready_for_review": 92,
        "blocked_external": 176,
    }
    checks = {item["check_id"]: item for item in register["checks"]}
    assert checks["C-CONTRACT-02"]["scope_disposition"] == (
        "EXCLUDED_B_FOR_CURRENT_ITERATION"
    )
    assert checks["FND-AUTH-01"]["scope_disposition"] == "MIXED_ATOMIC"
    assert checks["DOD-07"]["acceptance_status"] == "TEMPLATE"
    assert checks["IMPL-WORKFLOW-C-SAMPLING-WORKER-2026-07-23"][
        "acceptance_status"
    ] == "BLOCKED_EXTERNAL"
    migrated = checks["IMPL-DIFY-STYLE-PROFILE-RECOMMENDATION-2026-07-28"]
    assert migrated["acceptance_status"] == "READY_FOR_REVIEW"
    assert any(
        item["path"].endswith("pack-09-dify-style-recommendation-evidence.md")
        for item in migrated["evidence_refs"]
    )
    advinsys = checks["IMPL-ADVINSYS-NONB-PATHS-LOCAL-2026-07-29"]
    assert advinsys["acceptance_status"] == "READY_FOR_REVIEW"
    assert any(
        item["path"].endswith("advinsys-production-path-validation-2026-07-29.md")
        for item in advinsys["evidence_refs"]
    )
    assert checks["IMPL-B-ADVINSYS-VALIDATION-CANARY-2026-07-29"][
        "scope_disposition"
    ] == "EXCLUDED_B_FOR_CURRENT_ITERATION"
    assert all(item["fixture_is_not_live"] is True for item in checks.values())


def test_exported_register_is_source_and_hash_bound(tmp_path: Path) -> None:
    output = tmp_path / "register.json"
    written = export_register(policy_path=DEFAULT_POLICY, output=output)
    verified = verify_register(policy_path=DEFAULT_POLICY, register_path=output)

    assert verified["register_hash"] == written["register_hash"]
    assert verified["check_count"] == 330
    assert len(written["source_identity"]["tree_fingerprint"]) == 64


def test_source_fingerprint_excludes_register_and_is_commit_independent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    source = tmp_path / "source.txt"
    source.write_text("stable source\n", encoding="utf-8")
    output = tmp_path / "register.json"

    def check_output(command: list[str], **kwargs: object) -> bytes:
        calls.append(command)
        del kwargs
        return b"register.json\0source.txt\0"

    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    monkeypatch.setattr(acceptance.subprocess, "check_output", check_output)

    identity = acceptance._source_identity(output=output)

    assert calls == [
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."]
    ]
    assert identity["identity_method"] == "repository-content-v2"
    assert identity["file_count"] == "1"
    assert len(identity["tree_fingerprint"]) == 64

    source.write_text("changed source\n", encoding="utf-8")
    assert acceptance._source_identity(output=output)["tree_fingerprint"] != identity[
        "tree_fingerprint"
    ]


def test_unknown_classification_id_fails_closed(tmp_path: Path) -> None:
    policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    policy["excluded_b_ids"].append("MISSING-ROADMAP-ID")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(AcceptanceRegisterError, match="absent from roadmap"):
        build_register(policy_path=policy_path, output=tmp_path / "register.json")
