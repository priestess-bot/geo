from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geno_core.market import BROADER_PLATFORM_REGISTRY_VERSION  # noqa: E402
from scripts.build_au_broader_platform_registry import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    compute_broader_platform_registry_hash,
)


REQUIRED_FIELDS = (
    "registry_version",
    "generated_at",
    "status",
    "broader_platform_registry_ready",
    "paths",
    "market_profile",
    "summary",
    "candidate_platforms",
    "stage_policy",
    "recommended_sequence",
    "current_boundary",
    "broader_platform_registry_hash",
)

EXPECTED_CANDIDATE_IDS = (
    "gemini_ai_search",
    "bing_copilot_search",
    "claude_web_search",
    "youtube_search_reviews",
    "reddit_au_threads",
    "productreview_au_reviews",
)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _validate_candidate(candidate: dict[str, Any], errors: list[str]) -> None:
    candidate_id = str(candidate.get("id", ""))
    for field in (
        "id",
        "platform",
        "surface",
        "build_stage",
        "platform_role",
        "default_weight",
        "enabled",
        "priority",
        "access_methods",
        "adapter_status",
        "required_environment",
        "evidence_requirements",
        "scoring_policy",
        "source_signal_types",
        "next_work_item",
        "market_profile_registered",
        "market_profile_config",
    ):
        if field not in candidate:
            errors.append(f"candidate_field_missing:{candidate_id}:{field}")
    if candidate.get("build_stage") not in {"P1", "P2"}:
        errors.append(f"candidate_build_stage_invalid:{candidate_id}")
    if candidate.get("platform_role") not in {"ai_answer_platform", "source_platform"}:
        errors.append(f"candidate_platform_role_invalid:{candidate_id}")
    if candidate.get("enabled") is not False:
        errors.append(f"candidate_must_be_disabled:{candidate_id}")
    if float(candidate.get("default_weight") or 0.0) != 0.0:
        errors.append(f"candidate_weight_must_be_zero:{candidate_id}")
    if candidate.get("adapter_status") != "planned_not_implemented":
        errors.append(f"candidate_adapter_status_invalid:{candidate_id}")
    if candidate.get("market_profile_registered") is not True:
        errors.append(f"candidate_not_registered_in_market_profile:{candidate_id}")
    if not _as_list(candidate.get("access_methods")):
        errors.append(f"candidate_access_methods_empty:{candidate_id}")
    if not _as_list(candidate.get("evidence_requirements")):
        errors.append(f"candidate_evidence_requirements_empty:{candidate_id}")
    if not _as_list(candidate.get("source_signal_types")):
        errors.append(f"candidate_source_signal_types_empty:{candidate_id}")


def verify_au_broader_platform_registry(registry: Any, *, path: Path | None = None) -> dict[str, Any]:
    if not isinstance(registry, dict):
        return {
            "status": "fail",
            "errors": ["broader_platform_registry_not_json_object"],
            "hash_valid": False,
            "broader_platform_registry_ready": False,
        }

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in registry:
            errors.append(f"field_missing:{field}")
    if registry.get("registry_version") != BROADER_PLATFORM_REGISTRY_VERSION:
        errors.append("registry_version_invalid")

    expected_hash = registry.get("broader_platform_registry_hash")
    computed_hash = compute_broader_platform_registry_hash(registry)
    hash_valid = isinstance(expected_hash, str) and expected_hash == computed_hash
    if not hash_valid:
        errors.append("broader_platform_registry_hash_mismatch")

    summary = _as_dict(registry.get("summary"))
    market_profile = _as_dict(registry.get("market_profile"))
    candidates = [_as_dict(item) for item in _as_list(registry.get("candidate_platforms"))]
    candidate_ids = [str(item.get("id", "")) for item in candidates]
    if tuple(candidate_ids) != EXPECTED_CANDIDATE_IDS:
        errors.append("candidate_ids_or_order_invalid")
    if summary.get("candidate_count") != len(candidates):
        errors.append("summary_candidate_count_mismatch")
    if summary.get("registered_candidate_count") != len(candidates):
        errors.append("summary_registered_candidate_count_mismatch")
    if summary.get("enabled_candidate_count") != 0:
        errors.append("summary_enabled_candidate_count_mismatch")
    if summary.get("disabled_candidate_count") != len(candidates):
        errors.append("summary_disabled_candidate_count_mismatch")
    if set(_as_list(summary.get("p0a_enabled_platform_surfaces"))) != {"chatgpt:chatgpt_search", "perplexity:sonar"}:
        errors.append("p0a_enabled_platform_surfaces_changed")
    if set(_as_list(summary.get("p0b_platform_surfaces"))) != {"google:google_aio", "google:google_ai_mode"}:
        errors.append("p0b_platform_surfaces_changed")
    if market_profile.get("market_code") != "AU":
        errors.append("market_profile_market_code_invalid")
    if market_profile.get("locale") != "en-AU":
        errors.append("market_profile_locale_invalid")

    for candidate in candidates:
        _validate_candidate(candidate, errors)

    ready = not errors and registry.get("broader_platform_registry_ready") is True
    return {
        "status": "pass" if ready else "fail",
        "errors": errors,
        "path": str(path) if path else "",
        "registry_version": registry.get("registry_version", ""),
        "broader_platform_registry_hash": expected_hash,
        "computed_broader_platform_registry_hash": computed_hash,
        "hash_valid": hash_valid,
        "broader_platform_registry_ready": registry.get("broader_platform_registry_ready") is True,
        "candidate_count": len(candidates),
        "enabled_candidate_count": summary.get("enabled_candidate_count", 0),
        "disabled_candidate_count": summary.get("disabled_candidate_count", 0),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the AU broader platform registry JSON.")
    parser.add_argument(
        "path",
        nargs="?",
        default=os.environ.get("GENO_AU_BROADER_PLATFORM_REGISTRY_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result = {
            "status": "fail",
            "errors": ["file_missing"],
            "path": str(path),
            "hash_valid": False,
            "broader_platform_registry_ready": False,
        }
    except json.JSONDecodeError as exc:
        result = {
            "status": "fail",
            "errors": [f"json_invalid:{exc.msg}"],
            "path": str(path),
            "hash_valid": False,
            "broader_platform_registry_ready": False,
        }
    else:
        result = verify_au_broader_platform_registry(payload, path=path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
