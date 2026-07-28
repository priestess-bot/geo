from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.geo_acceptance.contracts import AcceptanceConfig, CHANNELS
from scripts.provision_advinsys_project import entity_request, expected_summary, load_manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/target_company/advinsys-geo-project.json"
GUIDE = ROOT / "docs/operations/geo-ui-operator-guide.md"


def test_advinsys_manifest_is_the_complete_nine_channel_source_of_truth() -> None:
    manifest = load_manifest(MANIFEST)
    summary = expected_summary(manifest)
    assert summary == {
        "project_name": "ADVINSYS Australia",
        "product_count": 3,
        "destination_count": 9,
        "optional_destination_count": 1,
        "campaign_count": 3,
        "opportunity_count": 27,
        "monitoring_query_count": 6,
        "knowledge_source_count": 6,
        "evidence_seed_count": 4,
    }
    assert {item["publication_channel"] for item in manifest["destinations"]} == {
        "owned_site", "productreview", "youtube", "reddit", "amazon",
        "ozbargain", "tiktok", "instagram", "quora",
    }
    facebook = manifest["optional_destinations"][0]
    assert facebook["publication_channel"] == "other"
    assert facebook["included_in_standard_kpi"] is False


def test_catalog_entity_request_excludes_manifest_only_query_configuration() -> None:
    manifest = load_manifest(MANIFEST)
    product = manifest["products"][0]

    request = entity_request(product, entity_type="product")

    assert request == {
        "entity_type": "product",
        "canonical_name": product["canonical_name"],
        "canonical_url": product["canonical_url"],
        "attributes": product["attributes"],
    }
    assert "queries" not in request


def test_controlled_acceptance_cannot_claim_a_real_public_url_or_run_in_production() -> None:
    assert CHANNELS[0]["url"] == "https://simulated.advinsys.example/"
    config = AcceptanceConfig("postgresql://app", "postgresql://worker", "run", Path("out"))
    config.validate()
    with pytest.raises(ValueError, match="staging or test"):
        AcceptanceConfig(
            "postgresql://app",
            "postgresql://worker",
            "run",
            Path("out"),
            environment="production",
        ).validate()


def test_standalone_manual_covers_every_delivery_and_recovery_surface() -> None:
    source = GUIDE.read_text(encoding="utf-8")
    required = (
        "本文档是独立操作手册",
        "独立 Staging 仿真环境",
        "六阶段清洗与重处理",
        "Fact 审核与正式 Evidence 提升",
        "27 个投放任务",
        "V600 正式文案生产",
        "Export 与 Publication 边界",
        "TEST ONLY 九渠道 Prompt 预演",
        "客户摘要",
        "客户指标",
        "客户投放",
        "客户报告",
        "备份、恢复、升级和回滚",
        "异常处理矩阵",
        "T+28/T+56/T+84",
        "controlled_simulation=true",
    )
    for phrase in required:
        assert phrase in source
    assert "本文档是 [GEO 全流程操作手册]" not in source
    assert "geo-full-flow-runbook.md" not in source


def test_manual_local_images_exist() -> None:
    source = GUIDE.read_text(encoding="utf-8")
    import re

    paths = re.findall(r"!\[[^]]*\]\(([^)]+)\)", source)
    assert len(paths) >= 20
    missing = [value for value in paths if not (GUIDE.parent / value).resolve().is_file()]
    assert not missing


def test_manifest_is_plain_json_for_non_python_operators() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
