from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from geo_core.workflow_runtime import DIFY_WORKFLOW_PURPOSES


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "infra" / "dify" / "workflows"
EXPECTED_PURPOSES = {
    "knowledge.question_generation",
    "knowledge.rag_grounding",
    "placements.generation",
    "placements.simulation",
    "synthetic_lab.generation",
    "synthetic_lab.claim_extraction",
    "synthetic_lab.conflict_check",
    "synthetic_lab.revision",
    "synthetic_lab.style_profile",
    "recommendations.recommendation",
}
EXPECTED_INPUTS = {
    "geo_context_json",
    "geo_context_hash",
    "geo_input_hash",
    "geo_output_schema_json",
    "geo_purpose",
}


def test_dify_workflow_manifest_and_dsl_contracts_are_frozen() -> None:
    manifest = json.loads((WORKFLOWS / "manifest.json").read_text())
    assert manifest["format"] == "geo-dify-workflow-manifest-v1"
    assert manifest["dify_version"] == "1.16.0"
    assert {item["purpose"] for item in manifest["workflows"]} == EXPECTED_PURPOSES
    assert DIFY_WORKFLOW_PURPOSES == EXPECTED_PURPOSES

    for item in manifest["workflows"]:
        path = WORKFLOWS / item["file"]
        body = path.read_bytes()
        assert hashlib.sha256(body).hexdigest() == item["sha256"]
        dsl = yaml.safe_load(body)
        assert dsl["kind"] == "app"
        assert dsl["app"]["mode"] == "workflow"
        assert dsl["version"] == manifest["dsl_version"]
        dependency = dsl["dependencies"][0]["value"]
        assert dependency["marketplace_plugin_unique_identifier"] == manifest["plugin"]
        nodes = dsl["workflow"]["graph"]["nodes"]
        assert {node["data"]["type"] for node in nodes} == {"start", "llm", "end"}
        assert all(node["data"]["type"] != "agent" for node in nodes)
        start = next(node for node in nodes if node["data"]["type"] == "start")
        assert {value["variable"] for value in start["data"]["variables"]} == EXPECTED_INPUTS
        llm = next(node for node in nodes if node["data"]["type"] == "llm")
        assert llm["data"]["model"]["provider"] == "langgenius/deepseek/deepseek"
        assert llm["data"]["model"]["name"] == "deepseek-chat"
        assert llm["data"]["model"]["completion_params"]["response_format"] == "json_object"
        if item["purpose"] == "recommendations.recommendation":
            prompt_text = "\n".join(
                str(prompt["text"]) for prompt in llm["data"]["prompt_template"]
            )
            assert "copied verbatim from the selected evidence summaries" in prompt_text
            assert "never invent or estimate percentages" in prompt_text
        if item["purpose"] == "knowledge.rag_grounding":
            prompt_text = "\n".join(
                str(prompt["text"]) for prompt in llm["data"]["prompt_template"]
            )
            assert "identified by adapter_purpose" in prompt_text
            assert "must exactly match a name also emitted in entities" in prompt_text
            assert "Never use a bare URL as a relation endpoint" in prompt_text
        if item["purpose"] == "placements.simulation":
            prompt_text = "\n".join(
                str(prompt["text"]) for prompt in llm["data"]["prompt_template"]
            )
            assert "task_contract.authenticity_mode is synthetic_testimonial" in prompt_text
            assert "fictional first-person Australian consumer-style review" in prompt_text
            assert "kind=experience, support_status=unsupported" in prompt_text
            assert "do not invent a product-use outcome" in prompt_text
            assert "saved time, freed weekends, handled mowing" in prompt_text
        end = next(node for node in nodes if node["data"]["type"] == "end")
        assert end["data"]["outputs"][0]["variable"] == "result"


def test_dify_overlay_preserves_existing_geo_ports() -> None:
    text = (ROOT / "infra" / "dify" / "compose.geo-runtime.yml").read_text()
    assert "ports:" not in text
    assert "GEO_WORKFLOW_RUNTIME_BACKEND: dify" in text
    assert "http://dify-api:5001" in text


def test_dify_runtime_is_ignored_and_keys_are_not_tracked() -> None:
    assert ".runtime/" in (ROOT / ".gitignore").read_text()
    for path in (ROOT / "infra" / "dify").rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert "api_key=" not in text.lower()
            assert "Bearer app-" not in text
