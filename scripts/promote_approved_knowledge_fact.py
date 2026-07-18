#!/usr/bin/env python3
"""Promote one approved knowledge fact into governed, immutable Evidence."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
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
    value.add_argument("--subject-entity-id", required=True)
    value.add_argument(
        "--subject-role",
        choices=("primary_brand", "competitor", "market", "product", "neutral"),
        required=True,
    )
    value.add_argument(
        "--usage-rights",
        choices=("owned", "licensed", "public_domain", "authorised_experience"),
        required=True,
    )
    value.add_argument("--confidentiality", choices=("public", "internal"), default="public")
    value.add_argument("--public-disclosure", action="store_true")
    value.add_argument("--public-source-url")
    value.add_argument("--public-source-title")
    value.add_argument("--citation-label", default="Approved source")
    value.add_argument("--quotation-allowed", action="store_true")
    value.add_argument("--attribution-required", action="store_true")
    value.add_argument("--dry-run", action="store_true")
    value.add_argument("--receipt", type=Path)
    return value


def promote(api: Api, args: argparse.Namespace) -> dict[str, Any]:
    facts = api.request(
        "GET", f"/v1/projects/{args.project_id}/knowledge/fact-candidates"
    )
    fact = next((item for item in facts if item["id"] == args.fact_id), None)
    if fact is None:
        raise ValueError("knowledge fact candidate does not exist in this project")
    if fact["status"] != "approved":
        raise ValueError("knowledge fact must be approved before Evidence promotion")

    entities = api.request("GET", f"/v1/projects/{args.project_id}/entities?limit=500")
    if not any(item["id"] == args.subject_entity_id for item in entities):
        raise ValueError("subject entity does not belong to this project")
    sources = api.request("GET", f"/v1/projects/{args.project_id}/knowledge/sources")
    source = next((item for item in sources if item["id"] == fact["source_id"]), None)
    if source is None or source["status"] != "ready" or not source.get("content_hash"):
        raise ValueError("knowledge source must be ready and content-addressed")

    statement = fact["statement"]
    snapshot_hash = hashlib.sha256(statement.encode()).hexdigest()
    if snapshot_hash != fact["statement_hash"]:
        raise ValueError("fact statement hash does not match its immutable statement")
    if args.public_disclosure:
        if args.confidentiality != "public":
            raise ValueError("public disclosure requires public confidentiality")
        public_url = args.public_source_url or source.get("source_url")
        if not public_url:
            raise ValueError("public disclosure requires a public source URL")
    else:
        public_url = args.public_source_url

    payload = {
        "item_type": "approved_fact",
        "source_id": source["id"],
        "subject_entity_id": args.subject_entity_id,
        "subject_role": args.subject_role,
        "locator": {
            "knowledge_fact_id": fact["id"],
            "chunk_id": fact["chunk_id"],
            "source_url": source.get("source_url"),
        },
        "snapshot": {"kind": "text", "text": statement, "sha256": snapshot_hash},
        "source_revision": {"kind": "content_hash", "value": source["content_hash"]},
        "usage_rights": args.usage_rights,
        "confidentiality": args.confidentiality,
        "public_citation": {
            "disclosure_allowed": args.public_disclosure,
            "source_url": public_url,
            "source_title": args.public_source_title or source["title"],
            "label": args.citation_label,
            "quotation_allowed": args.quotation_allowed,
            "attribution_required": args.attribution_required,
        },
    }
    existing = api.request("GET", f"/v1/projects/{args.project_id}/evidence-items?limit=500")
    evidence = next(
        (item for item in existing if item["snapshot"]["sha256"] == snapshot_hash), None
    )
    created = False
    if evidence is None and not args.dry_run:
        evidence = api.request(
            "POST", f"/v1/projects/{args.project_id}/evidence-items", payload
        )
        created = True
    return {
        "receipt_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "actual",
        "action": "dry_run" if args.dry_run else "promote",
        "project_id": args.project_id,
        "fact_id": args.fact_id,
        "source_id": source["id"],
        "snapshot_sha256": snapshot_hash,
        "created": created,
        "reused": evidence is not None and not created,
        "evidence_id": evidence["id"] if evidence else None,
        "eligible_for_generation": evidence.get("eligible_for_generation") if evidence else None,
        "eligible_for_publication": evidence.get("eligible_for_publication") if evidence else None,
        "payload": payload if args.dry_run else None,
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
