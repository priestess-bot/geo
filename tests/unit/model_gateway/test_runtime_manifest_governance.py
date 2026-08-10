from __future__ import annotations

from copy import deepcopy

import pytest

from geo_core.model_gateway.runtime_catalog import runtime_options_for_manifest
from geo_core.model_gateway.runtime_manifest import RuntimeManifestError, parse_runtime_manifest
from geo_core.model_gateway.runtime_manifest_schema import (
    runtime_manifest_json_schema,
    runtime_manifest_six_provider_template,
)


def test_six_provider_template_is_strictly_parseable_and_freezes_au_microsoft_agent() -> None:
    manifest = parse_runtime_manifest(runtime_manifest_six_provider_template())

    assert {item.adapter_release.provider for item in manifest.provider_runtimes} == {
        "deepseek",
        "openai",
        "kimi",
        "gemini",
        "perplexity",
        "microsoft",
    }
    microsoft = next(
        item for item in manifest.provider_runtimes if item.adapter_release.provider == "microsoft"
    )
    assert microsoft.microsoft_agent_reference is not None
    assert microsoft.microsoft_agent_reference.market == "en-AU"
    assert microsoft.microsoft_agent_reference.language == "en"
    options = runtime_options_for_manifest(manifest)
    assert len(options) == 6
    assert len({item.option_hash for item in options}) == 6


def test_runtime_manifest_rejects_retired_serpapi_provider() -> None:
    document = deepcopy(runtime_manifest_six_provider_template())
    providers = document["provider_runtimes"]
    models = document["model_releases"]
    policy = document["project_policy"]
    assert isinstance(providers, list)
    assert isinstance(models, list)
    assert isinstance(policy, dict)
    serp_provider = deepcopy(providers[1])
    assert isinstance(serp_provider, dict)
    serp_provider.update(
        {
            "provider": "serpapi",
            "adapter_release_id": "serpapi-approved-v1",
            "allowed_search_modes": ["google_search"],
            "secret_reference_id": "94000000-0000-0000-0000-000000000007",
        }
    )
    providers.append(serp_provider)
    serp_model = deepcopy(models[1])
    assert isinstance(serp_model, dict)
    serp_model.update(
        {
            "provider": "serpapi",
            "adapter_release_id": "serpapi-approved-v1",
            "model_release_id": "serpapi-google-search-v1",
            "configured_model": "google-ai-overview",
        }
    )
    models.append(serp_model)
    allowed_providers = policy["allowed_providers"]
    allowed_adapters = policy["allowed_adapter_release_ids"]
    assert isinstance(allowed_providers, list)
    assert isinstance(allowed_adapters, list)
    allowed_providers.append("serpapi")
    allowed_adapters.append("serpapi-approved-v1")

    with pytest.raises(RuntimeManifestError):
        parse_runtime_manifest(document)


def test_runtime_manifest_rejects_self_approval() -> None:
    document = runtime_manifest_six_provider_template()
    document["approved_by"] = document["prepared_by"]

    with pytest.raises(RuntimeManifestError, match="maker and checker"):
        parse_runtime_manifest(document)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("approval_evidence_reference", "evidence:unresolvable", "credential-free"),
        ("approval_evidence_sha256", "not-a-hash", "SHA-256"),
    ),
)
def test_runtime_manifest_rejects_unverifiable_approval_evidence(
    field: str, value: str, message: str
) -> None:
    document = runtime_manifest_six_provider_template()
    document[field] = value

    with pytest.raises(RuntimeManifestError, match=message):
        parse_runtime_manifest(document)


def test_runtime_manifest_rejects_unverifiable_release_evidence() -> None:
    document = runtime_manifest_six_provider_template()
    providers = document["provider_runtimes"]
    assert isinstance(providers, list)
    provider = providers[0]
    assert isinstance(provider, dict)
    provider["capability_evidence_reference"] = "fixture:capability"

    with pytest.raises(RuntimeManifestError, match="credential-free"):
        parse_runtime_manifest(document)


def test_runtime_manifest_schema_and_parser_are_closed_to_unknown_fields() -> None:
    schema = runtime_manifest_json_schema()
    definitions = schema["$defs"]
    assert schema["additionalProperties"] is False
    assert isinstance(definitions, dict)
    assert all(
        definitions[name]["additionalProperties"] is False
        for name in (
            "capabilities",
            "data_policy",
            "microsoft",
            "provider_runtime",
            "model_release",
            "project_policy",
        )
    )
    document = deepcopy(runtime_manifest_six_provider_template())
    document["unreviewed_extension"] = True
    with pytest.raises(RuntimeManifestError, match="frozen schema"):
        parse_runtime_manifest(document)
