from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from geo_api.app_factory import create_api_app
from geo_api.placement_contracts import PromptBundleView as ApiPromptBundleView
from geo_core.placements.domain import PromptBundleView as DomainPromptBundleView


def _api_payload() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "project_id": uuid4(),
        "campaign_id": uuid4(),
        "opportunity_id": uuid4(),
        "destination_id": uuid4(),
        "brief_version_id": uuid4(),
        "evidence_pack_attempt_id": uuid4(),
        "template_release_id": uuid4(),
        "bundle_hash": "a" * 64,
        "storage_key": "content-prompts/legacy.json",
        "artifact_status": "finalized",
        "storage_uri": "s3://geo-test/legacy.json",
        "prompt_release_binding_id": None,
        "prompt_release_binding_version": None,
        "skill_version_id": uuid4(),
        "release_version": 1,
        "release_hash": "b" * 64,
    }


def test_prompt_bundle_read_contract_accepts_exact_or_legacy_binding_lineage() -> None:
    legacy = _api_payload()
    assert ApiPromptBundleView.model_validate(legacy).prompt_release_binding_id is None

    current = {
        **legacy,
        "prompt_release_binding_id": uuid4(),
        "prompt_release_binding_version": 2,
    }
    assert ApiPromptBundleView.model_validate(current).prompt_release_binding_version == 2

    with pytest.raises(ValidationError, match="exact or legacy"):
        ApiPromptBundleView.model_validate({**legacy, "prompt_release_binding_id": uuid4()})


def test_prompt_bundle_domain_projection_rejects_partial_binding_lineage() -> None:
    values = _api_payload()
    legacy = DomainPromptBundleView(**values)
    assert legacy.prompt_release_binding_version is None

    with pytest.raises(ValueError, match="exact or legacy"):
        DomainPromptBundleView(**{**values, "prompt_release_binding_version": 1})


def test_prompt_bundle_openapi_is_nullable_only_on_the_read_contract() -> None:
    schemas = create_api_app(surface="internal").openapi()["components"]["schemas"]
    view = schemas["PromptBundleView"]
    create = schemas["PromptBundleCreate"]

    for field in ("prompt_release_binding_id", "prompt_release_binding_version"):
        assert field in view["required"]
        assert "null" in {option.get("type") for option in view["properties"][field]["anyOf"]}
    create_binding = create["properties"]["prompt_release_binding_id"]
    assert "prompt_release_binding_id" in create["required"]
    assert create_binding.get("type") == "string"
    assert "anyOf" not in create_binding
    assert "prompt_release_binding_version" not in create["properties"]
