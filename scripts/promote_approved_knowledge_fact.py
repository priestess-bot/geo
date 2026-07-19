#!/usr/bin/env python3
"""Promote one approved knowledge fact into governed, immutable Evidence."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.provision_advinsys_project import Api  # noqa: E402


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--api-url", default="http://localhost:8000")
    value.add_argument("--actor-id", default="30000000-0000-4000-8000-000000000003")
    value.add_argument("--tenant-id", default="10000000-0000-4000-8000-000000000001")
    value.add_argument("--project-id", required=True)
    value.add_argument("--fact-id", required=True)
    value.add_argument("--title")
    value.add_argument("--subject-entity-id")
    value.add_argument(
        "--subject-role",
        choices=("primary_brand", "competitor", "market", "product", "neutral"),
        required=True,
    )
    value.add_argument(
        "--usage-rights",
        choices=("owned", "licensed", "public_reference"),
        required=True,
    )
    value.add_argument(
        "--confidentiality",
        choices=("public", "internal", "confidential"),
        default="public",
    )
    value.add_argument("--public-disclosure", action="store_true")
    value.add_argument("--public-source-url")
    value.add_argument("--public-source-title")
    value.add_argument("--citation-label")
    value.add_argument("--quotation-allowed", action="store_true")
    value.add_argument("--attribution-required", action="store_true")
    value.add_argument("--dry-run", action="store_true")
    value.add_argument("--receipt", type=Path)
    return value


def promote(api: Api, args: argparse.Namespace) -> dict[str, Any]:
    proposal_path = (
        f"/v1/projects/{args.project_id}/knowledge/fact-candidates/"
        f"{args.fact_id}/evidence-proposal"
    )
    proposal = api.request("GET", proposal_path)
    if args.subject_role == "neutral" and args.subject_entity_id:
        raise ValueError("neutral Evidence cannot bind a subject entity")
    if args.subject_role != "neutral" and not args.subject_entity_id:
        raise ValueError("non-neutral Evidence requires --subject-entity-id")
    public_url = args.public_source_url or proposal["defaults"].get("source_url")
    public_title = args.public_source_title or proposal["defaults"]["source_title"]
    citation_label = args.citation_label or proposal["defaults"]["citation_label"]
    payload = {
        "title": args.title or proposal["defaults"]["title"],
        "subject_entity_id": args.subject_entity_id,
        "subject_role": args.subject_role,
        "usage_rights": args.usage_rights,
        "confidentiality": args.confidentiality,
        "public_citation": {
            "disclosure_allowed": args.public_disclosure,
            "source_url": public_url,
            "source_title": public_title,
            "label": citation_label,
            "quotation_allowed": args.quotation_allowed,
            "attribution_required": args.attribution_required,
        },
    }
    if args.dry_run:
        return {
            "receipt_version": 2,
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": "dry_run",
            "project_id": args.project_id,
            "fact_id": args.fact_id,
            "proposal": proposal,
            "request": payload,
        }
    result = api.request(
        "POST",
        proposal_path.removesuffix("-proposal"),
        payload,
        key=f"knowledge-fact-evidence:{args.project_id}:{args.fact_id}",
    )
    evidence = result["evidence"]
    lineage = result["lineage"]
    return {
        "receipt_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "actual",
        "project_id": args.project_id,
        "fact_id": args.fact_id,
        "outcome": result["outcome"],
        "created": result["outcome"] == "created",
        "reused": result["outcome"] == "existing",
        "evidence_id": evidence["id"],
        "source_id": lineage["knowledge_source_id"],
        "snapshot_sha256": lineage["evidence_snapshot_hash"],
        "eligible_for_generation": evidence["eligible_for_generation"],
        "eligible_for_publication": evidence["eligible_for_publication"],
        "lineage": lineage,
    }


def main() -> int:
    args = parser().parse_args()
    try:
        result = promote(Api(args.api_url, args.actor_id, args.tenant_id), args)
    except (RuntimeError, ValueError) as error:
        print(f"Evidence promotion failed: {error}")
        return 1
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
