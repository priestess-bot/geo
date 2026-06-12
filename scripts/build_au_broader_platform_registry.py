from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geno_core.market import build_au_broader_platform_registry as build_core_au_broader_platform_registry  # noqa: E402


DEFAULT_OUTPUT_PATH = "docs/runtime_preflight/au-broader-platform-registry-latest.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_broader_platform_registry_hash(registry: dict[str, Any]) -> str:
    payload = dict(registry)
    payload.pop("broader_platform_registry_hash", None)
    return hashlib.sha256(_stable_bytes(payload)).hexdigest()


def build_au_broader_platform_registry(
    *,
    output_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    registry = build_core_au_broader_platform_registry()
    registry.update(
        {
            "generated_at": generated_at or _utc_now_iso(),
            "status": "pass",
            "broader_platform_registry_ready": True,
            "paths": {
                "output": str(output_path or DEFAULT_OUTPUT_PATH),
            },
        }
    )
    registry["broader_platform_registry_hash"] = compute_broader_platform_registry_hash(registry)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return registry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the AU broader platform registry JSON.")
    parser.add_argument(
        "--output-path",
        default=os.environ.get("GENO_AU_BROADER_PLATFORM_REGISTRY_OUTPUT_PATH", DEFAULT_OUTPUT_PATH),
        help="Path to write the AU broader platform registry JSON.",
    )
    parser.add_argument("--generated-at", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path)
    registry = build_au_broader_platform_registry(output_path=output_path, generated_at=args.generated_at)
    print(json.dumps(registry, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
