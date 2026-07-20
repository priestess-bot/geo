from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts.geo_staging_smoke import StagingSmokeConfig, main, run_staging_smoke
from scripts.verify_geo_acceptance_report import verify_report


ROOT = Path(__file__).resolve().parents[1]


def test_inline_report_requires_truthful_mode_adapters_fingerprint_and_boundaries() -> None:
    valid = {
        "execution_mode": "inline_isolated",
        "run_id": "inline-test",
        "adapters": [{"name": "deterministic"}],
        "environment_fingerprint": {"sha256": "a" * 64},
        "boundaries": {
            "production_worker_relay_topology_validated": False,
            "external_publication_performed": False,
        },
    }
    verify_report(valid)
    for field, replacement in (
        ("execution_mode", "production"),
        ("adapters", []),
        ("environment_fingerprint", {}),
    ):
        invalid = {**valid, field: replacement}
        with pytest.raises(ValueError):
            verify_report(invalid)
    invalid_boundaries = {
        **valid,
        "boundaries": {
            **valid["boundaries"],
            "production_worker_relay_topology_validated": True,
        },
    }
    with pytest.raises(ValueError):
        verify_report(invalid_boundaries)


def test_inline_make_gate_rejects_all_missing_database_identity_inputs() -> None:
    environment = os.environ.copy()
    names = (
        "GEO_ACCEPTANCE_APP_DATABASE_URL",
        "GEO_ACCEPTANCE_WORKER_DATABASE_URL",
        "GEO_ACCEPTANCE_ADMIN_DATABASE_URL",
        "GEO_ACCEPTANCE_ISOLATION_MARKER",
    )
    for name in names:
        environment.pop(name, None)
    result = subprocess.run(
        ["make", "--silent", "geo-acceptance-inline"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert all(f"{name} is required" in output for name in names)


def test_staging_script_refuses_before_configuration_or_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = {"called": False}

    def forbidden(_: StagingSmokeConfig) -> dict[str, object]:
        sentinel["called"] = True
        raise AssertionError("external check must not run")

    monkeypatch.delenv("GEO_RUN_STAGING_SMOKE", raising=False)
    monkeypatch.delenv("GEO_CONFIRM_STAGING_PAID_MODEL_CALL", raising=False)
    monkeypatch.setattr("scripts.geo_staging_smoke.run_staging_smoke", forbidden)
    assert main([]) == 2
    assert sentinel["called"] is False


def test_f001_stage_01_make_target_requires_both_opt_ins_without_leaking_values() -> None:
    environment = os.environ.copy()
    environment.pop("GEO_RUN_STAGING_SMOKE", None)
    environment.pop("GEO_CONFIRM_STAGING_PAID_MODEL_CALL", None)
    environment["GEO_STAGING_OIDC_AUDIENCE"] = "secret-audience-must-not-leak"
    result = subprocess.run(
        ["make", "--silent", "geo-staging-smoke"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "GEO_RUN_STAGING_SMOKE=1" in output
    assert "secret-audience-must-not-leak" not in output


def test_staging_configuration_rejects_group_readable_secret_files(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token"
    key_file = tmp_path / "key"
    token_file.write_text("token", encoding="utf-8")
    key_file.write_text("key", encoding="utf-8")
    token_file.chmod(0o644)
    key_file.chmod(0o600)
    values = {
        "GEO_STAGING_OIDC_DISCOVERY_URL": (
            "https://id.example/.well-known/openid-configuration"
        ),
        "GEO_STAGING_OIDC_ISSUER": "https://id.example/",
        "GEO_STAGING_OIDC_AUDIENCE": "geo",
        "GEO_STAGING_OIDC_TOKEN_FILE": str(token_file),
        "GEO_STAGING_KNOWLEDGE_URL": "https://knowledge.example/product",
        "GEO_STAGING_PUBLICATION_URL": "https://publication.example/review",
        "GEO_STAGING_PUBLICATION_EXPECTED_TEXT": "approved review",
        "GEO_DEEPSEEK_API_KEY_FILE": str(key_file),
    }
    with pytest.raises(ValueError, match="GEO_STAGING_OIDC_TOKEN_FILE"):
        StagingSmokeConfig.from_environment(values)


def test_staging_smoke_writes_separate_redacted_evidence_with_four_checks(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token"
    key_file = tmp_path / "key"
    token_file.write_text("oidc-secret-must-not-leak", encoding="utf-8")
    key_file.write_text("model-secret-must-not-leak", encoding="utf-8")
    output = tmp_path / "staging-smoke.json"
    config = StagingSmokeConfig(
        run_id="staging-smoke-test",
        output_path=output,
        oidc_discovery_url="https://id.example/.well-known/openid-configuration",
        oidc_issuer="https://id.example/",
        oidc_audience="geo",
        oidc_token_file=token_file,
        knowledge_url="https://knowledge.example/product",
        publication_url="https://publication.example/review",
        publication_expected_text="approved review",
        deepseek_key_file=key_file,
        configured_model="deepseek-chat",
        model_endpoint="https://api.deepseek.com/chat/completions",
    )
    result = run_staging_smoke(
        config,
        oidc_check=lambda _: {"status": "passed", "token_verified": True},
        knowledge_check=lambda _: {"status": "passed", "content_sha256": "a" * 64},
        model_check=lambda _: {"status": "passed", "call_count": 1},
        publication_check=lambda _: {"status": "passed", "metadata_hash": "b" * 64},
    )
    assert result["execution_mode"] == "staging_external"
    assert set(result["checks"]) == {
        "oidc_jwks",
        "knowledge_url",
        "model",
        "publication_url",
    }
    assert result["boundaries"] == {
        "external_calls_performed": True,
        "paid_model_call_budget": 1,
        "inline_acceptance": False,
        "production_worker_relay_topology_validated": False,
    }
    rendered = output.read_text(encoding="utf-8")
    assert "oidc-secret-must-not-leak" not in rendered
    assert "model-secret-must-not-leak" not in rendered


@pytest.mark.parametrize(
    ("stats", "expected_error"),
    [
        ({"expected": 0, "skipped": 0, "unexpected": 0, "flaky": 0}, "zero tests"),
        ({"expected": 1, "skipped": 1, "unexpected": 0, "flaky": 0}, "were skipped"),
    ],
)
def test_required_browser_report_rejects_zero_collection_and_skip(
    tmp_path: Path,
    stats: dict[str, int],
    expected_error: str,
) -> None:
    report = tmp_path / "playwright.json"
    report.write_text(json.dumps({"stats": stats}), encoding="utf-8")
    result = subprocess.run(
        [
            "node",
            "scripts/run-required-browser-tests.mjs",
            "--verify-report",
            str(report),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert expected_error in result.stderr
