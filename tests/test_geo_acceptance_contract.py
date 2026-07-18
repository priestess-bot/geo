from dataclasses import replace
from pathlib import Path

import pytest

from geo_core.model_gateway import ModelCallBudget, ModelGatewayRequest, ModelPolicy
from scripts.geo_acceptance import (
    AcceptanceConfig,
    CHANNELS,
    DeterministicGateway,
    PRODUCT_URL,
)
from scripts.geo_acceptance.monitoring import FOLLOW_UP_WINDOWS
from scripts.geo_acceptance.adapters import adapter_manifest
from scripts.geo_acceptance.isolation import (
    ConnectionKind,
    DatabaseProbe,
    validate_database_probes,
)


def test_acceptance_channel_matrix_is_complete_and_unique() -> None:
    expected = {
        "owned_site",
        "productreview",
        "youtube",
        "reddit",
        "amazon",
        "ozbargain",
        "tiktok",
        "instagram",
        "quora",
    }
    assert {item["channel"] for item in CHANNELS} == expected
    assert len({item["key"] for item in CHANNELS}) == 9
    assert all(item["url"].startswith("https://") for item in CHANNELS)


def test_acceptance_follow_up_windows_are_complete_and_ordered() -> None:
    assert [window.value for window in FOLLOW_UP_WINDOWS] == ["t28", "t56", "t84"]


def test_live_deepseek_requires_an_explicit_readable_key_file(tmp_path: Path) -> None:
    config = AcceptanceConfig(
        app_database_url="postgresql://app",
        worker_database_url="postgresql://worker",
        admin_database_url="postgresql://admin",
        isolation_marker="acceptance-test",
        run_id="validation",
        output_path=tmp_path / "result.json",
        live_deepseek=True,
    )
    with pytest.raises(ValueError, match="requires --deepseek-key-file"):
        config.validate()

    missing = AcceptanceConfig(
        app_database_url="postgresql://app",
        worker_database_url="postgresql://worker",
        admin_database_url="postgresql://admin",
        isolation_marker="acceptance-test",
        run_id="validation",
        output_path=tmp_path / "result.json",
        live_deepseek=True,
        deepseek_key_file=tmp_path / "missing",
    )
    with pytest.raises(ValueError, match="does not exist"):
        missing.validate()


def test_deterministic_gateway_returns_supported_schema_bound_claim() -> None:
    from uuid import uuid4

    evidence_id = uuid4()
    gateway = DeterministicGateway(evidence_id=evidence_id, product_url=PRODUCT_URL)
    budget = ModelCallBudget(1)
    result = gateway.generate(
        ModelGatewayRequest(
            messages=({"role": "user", "content": "controlled"},),
            configured_model="deepseek-v4-flash",
            prompt_bundle_hash="a" * 64,
            project_id=uuid4(),
            purpose="acceptance",
        ),
        policy=ModelPolicy(),
        budget=budget,
    )

    assert budget.consumed_calls == 1
    assert result.cost_usd == 0
    assert result.output["public_citation_refs"] == [str(evidence_id)]
    assert result.output["claims"] == [
        {
            "text": (
                "TerraMow V600 is identified as a Triple-Cam AI Vision Robot Mower "
                "in the robotic lawn mower category."
            ),
            "kind": "factual",
            "support_status": "supported",
            "evidence_item_ids": [str(evidence_id)],
        }
    ]


def test_inline_acceptance_requires_admin_endpoint_and_isolation_marker(tmp_path: Path) -> None:
    config = AcceptanceConfig(
        app_database_url="postgresql://app",
        worker_database_url="postgresql://worker",
        run_id="validation",
        output_path=tmp_path / "result.json",
    )
    with pytest.raises(ValueError, match="requires an admin"):
        config.validate_inline_isolation()

    missing_marker = replace(config, admin_database_url="postgresql://admin")
    with pytest.raises(ValueError, match="isolation_marker"):
        missing_marker.validate_inline_isolation()

    runtime_store = replace(
        missing_marker,
        isolation_marker="acceptance-test",
        runtime_object_store=True,
    )
    with pytest.raises(ValueError, match="process-local memory artifact store"):
        runtime_store.validate_inline_isolation()


def test_inline_isolation_accepts_distinct_principals_on_one_marked_database() -> None:
    probes = _database_probes()

    evidence = validate_database_probes(probes, expected_marker="acceptance-test")

    assert len(evidence.sha256) == 64
    assert len(evidence.endpoint_sha256) == 64
    assert len(evidence.database_sha256) == 64
    assert set(evidence.principal_sha256) == {"app", "worker", "admin"}
    assert "geo_app_login" not in str(evidence.as_report())


def test_inline_isolation_refuses_unproven_endpoint_principal_or_marker() -> None:
    probes = _database_probes()
    with pytest.raises(RuntimeError, match="one proven database endpoint"):
        validate_database_probes(
            {
                **probes,
                "worker": replace(
                    probes["worker"], endpoint_identity=("10.0.0.9", 5432)
                ),
            },
            expected_marker="acceptance-test",
        )
    with pytest.raises(RuntimeError, match="distinct database principals"):
        validate_database_probes(
            {
                **probes,
                "worker": replace(probes["worker"], principal="geo_app_login"),
            },
            expected_marker="acceptance-test",
        )
    with pytest.raises(RuntimeError, match="database scope"):
        validate_database_probes(
            {
                **probes,
                "admin": replace(probes["admin"], configured_isolation_marker=None),
            },
            expected_marker="acceptance-test",
        )


def test_inline_adapter_manifest_does_not_claim_worker_relay_topology(tmp_path: Path) -> None:
    config = AcceptanceConfig(
        app_database_url="postgresql://app",
        worker_database_url="postgresql://worker",
        admin_database_url="postgresql://admin",
        isolation_marker="acceptance-test",
        run_id="validation",
        output_path=tmp_path / "result.json",
    )

    adapters = {item["purpose"]: item for item in adapter_manifest(config)}

    assert adapters["job_execution"]["adapter"] == "inline_postgres_dispatcher"
    assert adapters["generation_model"]["adapter"] == "deterministic_gateway"
    assert adapters["worker_relay_topology"]["adapter"] == "not_exercised"


def _database_probes() -> dict[str, DatabaseProbe]:
    return {
        "app": _database_probe(
            kind="app",
            principal="geo_app_login",
            configured_isolation_marker=None,
            is_superuser=False,
            is_database_owner=False,
            is_app_member=True,
            is_worker_member=False,
        ),
        "worker": _database_probe(
            kind="worker",
            principal="geo_worker_login",
            configured_isolation_marker=None,
            is_superuser=False,
            is_database_owner=False,
            is_app_member=False,
            is_worker_member=True,
        ),
        "admin": _database_probe(
            kind="admin",
            principal="geo_database_owner",
            configured_isolation_marker="acceptance-test",
            is_superuser=False,
            is_database_owner=True,
            is_app_member=False,
            is_worker_member=False,
        ),
    }


def _database_probe(
    *,
    kind: ConnectionKind,
    principal: str,
    configured_isolation_marker: str | None,
    is_superuser: bool,
    is_database_owner: bool,
    is_app_member: bool,
    is_worker_member: bool,
) -> DatabaseProbe:
    return DatabaseProbe(
        kind=kind,
        endpoint_identity=("10.0.0.8", 5432),
        database_name="geo_acceptance",
        database_oid=16384,
        server_version_num="170005",
        principal=principal,
        isolation_marker="acceptance-test",
        configured_isolation_marker=configured_isolation_marker,
        is_superuser=is_superuser,
        is_database_owner=is_database_owner,
        is_app_member=is_app_member,
        is_worker_member=is_worker_member,
    )
