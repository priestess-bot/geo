"""Export and verify roadmap evidence manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from pydantic import TypeAdapter, ValidationError

from geo_core.engineering.evidence_manifest import (
    CheckStatus,
    EvidenceManifestError,
    RoadmapEvidenceManifest,
)
from geo_core.engineering.strict_dataclass_payload import (
    close_dataclass_json_schema,
    reject_unknown_dataclass_fields,
)


_ADAPTER = TypeAdapter(RoadmapEvidenceManifest)


def export_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = close_dataclass_json_schema(_ADAPTER.json_schema())
    payload = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def load_manifest(path: Path) -> RoadmapEvidenceManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvidenceManifestError(f"unable to read evidence manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvidenceManifestError(f"invalid evidence manifest JSON: {exc}") from exc
    reject_unknown_dataclass_fields(
        payload,
        RoadmapEvidenceManifest,
        path="manifest",
        error_factory=EvidenceManifestError,
    )
    try:
        manifest = _ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise EvidenceManifestError(f"invalid evidence manifest: {exc}") from exc
    if manifest.manifest_hash is None:
        raise EvidenceManifestError("evidence manifest must include its canonical manifest_hash")
    return manifest


def verify_manifest(path: Path) -> dict[str, object]:
    manifest = load_manifest(path)
    accepted_count = sum(check.status == CheckStatus.ACCEPTED for check in manifest.checks)
    return {
        "manifest_hash": manifest.calculate_hash(),
        "stage": manifest.stage,
        "check_count": len(manifest.checks),
        "accepted_check_count": accepted_count,
        "acceptance_ready": bool(manifest.checks) and accepted_count == len(manifest.checks),
        "included_workstreams": list(manifest.included_workstreams),
        "excluded_workstreams": list(manifest.excluded_workstreams),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    schema = commands.add_parser("export-schema", help="write the stable JSON Schema")
    schema.add_argument("output", type=Path)

    verify = commands.add_parser("verify", help="validate and hash one evidence manifest")
    verify.add_argument("manifest", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "export-schema":
            export_schema(arguments.output)
            return 0
        result = verify_manifest(arguments.manifest)
    except EvidenceManifestError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
