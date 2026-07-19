"""Version-aware canonical source-stratum verification for F027 exports."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence, cast

from geo_core.monitoring.source_contract import (
    LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
    SOURCE_CONTRACT_VERSION,
)
from geo_core.project_exports.errors import ProjectExportVerificationError


def verify_source_stratum(value: Mapping[str, object]) -> None:
    version = _text(value["source_contract_version"], "source contract version")
    if version not in {
        LEGACY_SOURCE_STRATUM_CONTRACT_VERSION,
        SOURCE_CONTRACT_VERSION,
    }:
        raise ProjectExportVerificationError("protocol source stratum contract is unsupported")
    platform = _text(value["platform"], "source platform")
    surface = _text(value["surface"], "source surface")
    platform_detail = _nullable_text(value["platform_detail"], "platform detail")
    surface_detail = _nullable_text(value["surface_detail"], "surface detail")
    if version == LEGACY_SOURCE_STRATUM_CONTRACT_VERSION:
        if platform_detail is not None or surface_detail is not None:
            raise ProjectExportVerificationError("legacy source stratum cannot carry detail fields")
    elif (platform == "other") != (platform_detail is not None) or (
        (surface == "other") != (surface_detail is not None)
    ):
        raise ProjectExportVerificationError(
            "source stratum OTHER details do not match platform and surface"
        )
    if not isinstance(value["search_enabled"], bool):
        raise ProjectExportVerificationError("source stratum search_enabled must be boolean")
    for model_name in ("configured_model", "reported_model"):
        model = _mapping(value[model_name], model_name)
        if set(model) != {"state", "value"}:
            raise ProjectExportVerificationError(
                f"{model_name} does not match the public field whitelist"
            )
        _text(model["state"], f"{model_name} state")
        _nullable_text(model["value"], f"{model_name} value")
    if _sha(value["source_stratum_hash"]) != canonical_hash(source_stratum_value(value)):
        raise ProjectExportVerificationError("protocol source stratum hash cannot be reproduced")


def source_strata_inventory_hash(values: Sequence[Mapping[str, object]]) -> str:
    canonical_values = [source_stratum_value(value) for value in values]
    return canonical_hash(sorted(canonical_values, key=canonical_hash))


def source_stratum_value(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "capture_method": value["capture_method"],
        "platform": value["platform"],
        "surface": value["surface"],
        "surface_kind": value["surface_kind"],
        "engine": value["engine"],
        "configured_model": value["configured_model"],
        "reported_model": value["reported_model"],
        "locale": value["locale"],
        "region": value["region"],
        "language": value["language"],
        "device": value["device"],
        "client_kind": value["client_kind"],
        "search_enabled": value["search_enabled"],
        "search_mode": value["search_mode"],
    }
    if value["source_contract_version"] == SOURCE_CONTRACT_VERSION:
        result["platform_detail"] = value["platform_detail"]
        result["surface_detail"] = value["surface_detail"]
    return result


def canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProjectExportVerificationError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectExportVerificationError(f"{label} must be non-empty text")
    return value


def _nullable_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _sha(value: object) -> str:
    result = _text(value, "source stratum hash")
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ProjectExportVerificationError("source stratum hash must be a lowercase SHA-256")
    return result
