"""Closed JSON Schema for the governed Model Gateway runtime manifest v2."""

from __future__ import annotations

from typing import Any


_SHA256 = "^[0-9a-f]{64}$"
_EVIDENCE_URI = "^(?:https|minio|s3)://[^\\s?#]+(?:#[^\\s]*)?$"
_PROVIDERS = [
    "deepseek",
    "openai",
    "kimi",
    "gemini",
    "perplexity",
    "microsoft",
    "serpapi",
]
_SIX_PROVIDERS = _PROVIDERS[:-1]


def runtime_manifest_json_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}
    uuid = {"type": "string", "format": "uuid"}
    sha256 = {"type": "string", "pattern": _SHA256}
    evidence_uri = {"type": "string", "pattern": _EVIDENCE_URI}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://geo.local/contracts/model-gateway-runtime-manifest-v2.schema.json",
        "title": "GEO Model Gateway Runtime Manifest v2",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "manifest_id",
            "project_id",
            "prepared_by",
            "prepared_at",
            "approved_by",
            "approved_at",
            "approval_evidence_reference",
            "approval_evidence_sha256",
            "provider_runtimes",
            "model_releases",
            "project_policy",
        ],
        "properties": {
            "schema_version": {"const": 2},
            "manifest_id": uuid,
            "project_id": uuid,
            "prepared_by": uuid,
            "prepared_at": {"type": "string", "format": "date-time"},
            "approved_by": uuid,
            "approved_at": {"type": "string", "format": "date-time"},
            "approval_evidence_reference": evidence_uri,
            "approval_evidence_sha256": sha256,
            "provider_runtimes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 7,
                "items": {"$ref": "#/$defs/provider_runtime"},
            },
            "model_releases": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/model_release"},
            },
            "project_policy": {"$ref": "#/$defs/project_policy"},
        },
        "$defs": {
            "capabilities": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "external_training_allowed",
                    "structured_output",
                    "data_retention_days",
                    "policy_reference",
                    "supports_seed",
                    "supports_tools",
                    "supports_search",
                    "supports_citations",
                    "supports_idempotency",
                    "supports_structured_output_with_tools",
                ],
                "properties": {
                    "external_training_allowed": {"type": "boolean"},
                    "structured_output": {"const": True},
                    "data_retention_days": {
                        "anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]
                    },
                    "policy_reference": text,
                    "supports_seed": {"type": "boolean"},
                    "supports_tools": {"type": "boolean"},
                    "supports_search": {"type": "boolean"},
                    "supports_citations": {"type": "boolean"},
                    "supports_idempotency": {"type": "boolean"},
                    "supports_structured_output_with_tools": {"type": "boolean"},
                },
            },
            "data_policy": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "storage",
                    "cache",
                    "display",
                    "redistribution",
                    "retention_days",
                    "terms_reference",
                    "terms_sha256",
                ],
                "properties": {
                    "storage": {"enum": ["allowed", "prohibited"]},
                    "cache": {"enum": ["allowed", "prohibited"]},
                    "display": {"enum": ["allowed", "prohibited"]},
                    "redistribution": {"enum": ["allowed", "prohibited"]},
                    "retention_days": {
                        "anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]
                    },
                    "terms_reference": evidence_uri,
                    "terms_sha256": sha256,
                },
            },
            "microsoft": {
                "type": "object",
                "additionalProperties": False,
                "required": ["endpoint", "agent_name", "agent_version", "market", "language"],
                "properties": {
                    "endpoint": {"type": "string", "format": "uri", "pattern": "^https://"},
                    "agent_name": text,
                    "agent_version": text,
                    "market": {"type": "string", "pattern": "^[a-z]{2,3}-[A-Z]{2}$"},
                    "language": {"type": "string", "pattern": "^[a-z]{2,3}$"},
                },
            },
            "provider_runtime": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "provider",
                    "adapter_release_id",
                    "interface_contract_version",
                    "expected_capture_method",
                    "capabilities",
                    "data_policy",
                    "capability_evidence_reference",
                    "capability_evidence_sha256",
                    "allowed_purposes",
                    "allowed_search_modes",
                    "secret_reference_id",
                    "microsoft",
                ],
                "properties": {
                    "provider": {"enum": _PROVIDERS},
                    "adapter_release_id": text,
                    "interface_contract_version": text,
                    "expected_capture_method": {
                        "enum": ["provider_api", "proxy_grounded_api"]
                    },
                    "capabilities": {"$ref": "#/$defs/capabilities"},
                    "data_policy": {"$ref": "#/$defs/data_policy"},
                    "capability_evidence_reference": evidence_uri,
                    "capability_evidence_sha256": sha256,
                    "allowed_purposes": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": text,
                    },
                    "allowed_search_modes": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"anyOf": [text, {"type": "null"}]},
                    },
                    "secret_reference_id": uuid,
                    "microsoft": {
                        "anyOf": [{"$ref": "#/$defs/microsoft"}, {"type": "null"}]
                    },
                },
                "allOf": [
                    {
                        "if": {
                            "properties": {"provider": {"const": "microsoft"}},
                            "required": ["provider"],
                        },
                        "then": {
                            "properties": {
                                "expected_capture_method": {"const": "proxy_grounded_api"},
                                "microsoft": {"$ref": "#/$defs/microsoft"},
                            }
                        },
                        "else": {
                            "properties": {
                                "expected_capture_method": {"const": "provider_api"},
                                "microsoft": {"type": "null"},
                            }
                        },
                    }
                ],
            },
            "model_release": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "provider",
                    "adapter_release_id",
                    "model_release_id",
                    "configured_model",
                    "reported_model_policy",
                    "allowed_reported_models",
                ],
                "properties": {
                    "provider": {"enum": _PROVIDERS},
                    "adapter_release_id": text,
                    "model_release_id": text,
                    "configured_model": text,
                    "reported_model_policy": {
                        "enum": ["record_only", "require_present", "exact", "allowlist"]
                    },
                    "allowed_reported_models": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": text,
                    },
                },
            },
            "project_policy": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "policy_version_id",
                    "version",
                    "previous_version_id",
                    "external_training_allowed",
                    "structured_output_required",
                    "allowed_providers",
                    "allowed_adapter_release_ids",
                    "maximum_paid_calls",
                    "maximum_concurrent_calls",
                ],
                "properties": {
                    "policy_version_id": uuid,
                    "version": {"type": "integer", "minimum": 1},
                    "previous_version_id": {"anyOf": [uuid, {"type": "null"}]},
                    "external_training_allowed": {"type": "boolean"},
                    "structured_output_required": {"const": True},
                    "allowed_providers": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"enum": _PROVIDERS},
                    },
                    "allowed_adapter_release_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": text,
                    },
                    "maximum_paid_calls": {"type": "integer", "minimum": 1},
                    "maximum_concurrent_calls": {"type": "integer", "minimum": 1},
                },
            },
        },
    }


def runtime_manifest_six_provider_template() -> dict[str, Any]:
    purposes = [
        "synthetic_lab.generation",
        "synthetic_lab.claim_extraction",
        "synthetic_lab.conflict_check",
        "synthetic_lab.revision",
        "synthetic_lab.style_judge",
        "synthetic_lab.arbiter",
        "monitoring.metric_judge",
        "recommendations.recommendation",
        "prompt_release_test",
    ]
    settings: dict[str, tuple[str, list[str], bool]] = {
        "deepseek": ("provider_api", ["disabled"], False),
        "openai": ("provider_api", ["disabled", "web"], True),
        "kimi": ("provider_api", ["disabled"], False),
        "gemini": ("provider_api", ["disabled", "google_search"], True),
        "perplexity": ("provider_api", ["web"], True),
        "microsoft": ("proxy_grounded_api", ["bing_grounding"], True),
        "serpapi": ("provider_api", ["google_search"], True),
    }
    providers: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    adapters: list[str] = []
    for index, provider in enumerate(_SIX_PROVIDERS, start=1):
        capture_method, search_modes, supports_search = settings[provider]
        adapter_id = f"{provider}-replace-with-approved-adapter-v1"
        model_id = f"{provider}-replace-with-approved-model-v1"
        adapters.append(adapter_id)
        providers.append(
            {
                "provider": provider,
                "adapter_release_id": adapter_id,
                "interface_contract_version": "geo-model-gateway-v1",
                "expected_capture_method": capture_method,
                "capabilities": {
                    "external_training_allowed": False,
                    "structured_output": True,
                    "data_retention_days": 30,
                    "policy_reference": (
                        f"https://evidence.example.invalid/{provider}/policy-reviewed.json"
                    ),
                    "supports_seed": provider in {"deepseek", "gemini"},
                    "supports_tools": supports_search,
                    "supports_search": supports_search,
                    "supports_citations": supports_search,
                    "supports_idempotency": False,
                    "supports_structured_output_with_tools": (
                        provider in {"openai", "gemini", "microsoft"}
                    ),
                },
                "data_policy": {
                    "storage": "allowed",
                    "cache": "prohibited",
                    "display": "allowed",
                    "redistribution": "prohibited",
                    "retention_days": 30,
                    "terms_reference": (
                        f"https://evidence.example.invalid/{provider}/terms-reviewed.json"
                    ),
                    "terms_sha256": f"{index:x}" * 64,
                },
                "capability_evidence_reference": (
                    f"minio://geo-governance/model-gateway/{provider}/capabilities.json"
                ),
                "capability_evidence_sha256": f"{index + 6:x}" * 64,
                "allowed_purposes": purposes,
                "allowed_search_modes": search_modes,
                "secret_reference_id": f"94000000-0000-0000-0000-{index:012d}",
                "microsoft": (
                    {
                        "endpoint": (
                            "https://replace-project.services.ai.azure.com/"
                            "api/projects/geo/openai/v1/responses"
                        ),
                        "agent_name": "replace-with-approved-au-grounding-agent",
                        "agent_version": "1",
                        "market": "en-AU",
                        "language": "en",
                    }
                    if provider == "microsoft"
                    else None
                ),
            }
        )
        models.append(
            {
                "provider": provider,
                "adapter_release_id": adapter_id,
                "model_release_id": model_id,
                "configured_model": f"replace-with-approved-{provider}-model",
                "reported_model_policy": "record_only",
                "allowed_reported_models": [],
            }
        )
    return {
        "schema_version": 2,
        "manifest_id": "91000000-0000-0000-0000-000000000001",
        "project_id": "92000000-0000-0000-0000-000000000001",
        "prepared_by": "93000000-0000-0000-0000-000000000001",
        "prepared_at": "2026-07-23T09:55:00+00:00",
        "approved_by": "93000000-0000-0000-0000-000000000002",
        "approved_at": "2026-07-23T10:00:00+00:00",
        "approval_evidence_reference": (
            "minio://geo-governance/model-gateway/runtime-approval-v2.json"
        ),
        "approval_evidence_sha256": "f" * 64,
        "provider_runtimes": providers,
        "model_releases": models,
        "project_policy": {
            "policy_version_id": "95000000-0000-0000-0000-000000000001",
            "version": 1,
            "previous_version_id": None,
            "external_training_allowed": False,
            "structured_output_required": True,
            "allowed_providers": _SIX_PROVIDERS,
            "allowed_adapter_release_ids": adapters,
            "maximum_paid_calls": 1000,
            "maximum_concurrent_calls": 8,
        },
    }


__all__ = ["runtime_manifest_json_schema", "runtime_manifest_six_provider_template"]
