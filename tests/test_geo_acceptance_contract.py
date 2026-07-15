from pathlib import Path

import pytest

from geo_core.model_gateway import ModelCallBudget, ModelGatewayRequest, ModelPolicy
from scripts.run_geo_acceptance import (
    AcceptanceConfig,
    CHANNELS,
    DeterministicGateway,
    PRODUCT_URL,
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


def test_live_deepseek_requires_an_explicit_readable_key_file(tmp_path: Path) -> None:
    config = AcceptanceConfig(
        app_database_url="postgresql://app",
        worker_database_url="postgresql://worker",
        run_id="validation",
        output_path=tmp_path / "result.json",
        live_deepseek=True,
    )
    with pytest.raises(ValueError, match="requires --deepseek-key-file"):
        config.validate()

    missing = AcceptanceConfig(
        app_database_url="postgresql://app",
        worker_database_url="postgresql://worker",
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
