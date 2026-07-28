#!/usr/bin/env python3
"""Provision the persistent ADVINSYS Australia reference project through stable APIs."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_MANIFEST = Path("docs/target_company/advinsys-geo-project.json")
STANDARD_CHANNELS = {
    "owned_site", "productreview", "youtube", "reddit", "amazon",
    "ozbargain", "tiktok", "instagram", "quora",
}

ENTITY_FIELDS = ("canonical_name", "canonical_url", "attributes")


def entity_request(item: dict[str, Any], *, entity_type: str) -> dict[str, object]:
    """Keep manifest-only fields such as monitoring queries out of Catalog requests."""
    return {
        "entity_type": entity_type,
        **{name: item[name] for name in ENTITY_FIELDS if name in item},
    }


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("target manifest schema_version must be 1")
    project = manifest.get("project")
    products = manifest.get("products")
    destinations = manifest.get("destinations")
    if not isinstance(project, dict) or not project.get("name"):
        raise ValueError("target manifest project.name is required")
    if not isinstance(products, list) or not products:
        raise ValueError("target manifest must contain products")
    if not isinstance(destinations, list):
        raise ValueError("target manifest destinations must be a list")
    channels = {item.get("publication_channel") for item in destinations}
    if channels != STANDARD_CHANNELS or len(destinations) != 9:
        raise ValueError("target manifest must define each of the nine standard channels once")
    names = [item.get("canonical_name") for item in products]
    if len(names) != len(set(names)):
        raise ValueError("target manifest product names must be unique")
    return manifest


class Api:
    def __init__(self, base_url: str, actor_id: str, tenant_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "X-GEO-Actor-ID": actor_id,
            "X-GEO-Tenant-ID": tenant_id,
        }

    def request(
        self, method: str, path: str, body: dict[str, object] | None = None, *, key: str = ""
    ) -> Any:
        headers = dict(self.headers)
        if key:
            headers["Idempotency-Key"] = key
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"null")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed ({error.code}): {detail}") from error


def provision(api: Api, manifest: dict[str, Any], repository_root: Path) -> dict[str, object]:
    project_config = manifest["project"]
    project_name = project_config["name"]
    brand_config = project_config["brand"]
    market_config = project_config["market"]
    products = manifest["products"]
    destinations = manifest["destinations"]
    evidence_seeds = manifest["evidence_seeds"]
    projects = api.request("GET", "/v1/projects")["items"]
    project = next((item for item in projects if item["name"] == project_name), None)
    if project is None:
        project = api.request("POST", "/v1/projects", {"name": project_name})
    project_id = project["id"]

    entities = api.request("GET", f"/v1/projects/{project_id}/entities?limit=500")
    by_name = {item["canonical_name"]: item for item in entities}
    brand = by_name.get(brand_config["canonical_name"]) or api.request(
        "POST",
        f"/v1/projects/{project_id}/entities",
        entity_request(brand_config, entity_type="brand"),
    )
    product_rows: list[dict[str, Any]] = []
    for product in products:
        row = by_name.get(product["canonical_name"])
        if row is None:
            row = api.request(
                "POST",
                f"/v1/projects/{project_id}/entities",
                entity_request(product, entity_type="product"),
            )
        product_rows.append(row)

    markets = api.request("GET", f"/v1/projects/{project_id}/market-profiles?limit=500")
    market = next(
        (
            item for item in markets
            if item["market_code"] == market_config["market_code"]
            and item["locale"] == market_config["locale"]
        ),
        None,
    ) or api.request(
        "POST",
        f"/v1/projects/{project_id}/market-profiles",
        market_config,
    )

    destination_rows = api.request("GET", f"/v1/projects/{project_id}/geo/destinations")
    by_key = {item["destination_key"]: item for item in destination_rows}
    configured_destinations: list[dict[str, Any]] = []
    for item in destinations:
        channel = item["publication_channel"]
        destination_key = item["destination_key"]
        url = item["canonical_url"]
        policy = item["policy_status"]
        requirement = item["requirement"]
        destination = by_key.get(destination_key) or api.request(
            "POST",
            f"/v1/projects/{project_id}/geo/destinations",
            {
                "publication_channel": channel,
                "destination_key": destination_key,
                "operation_mode": "manual",
                "destination_account_id": (
                    destination_key if item["account_authority"] == "declared_official" else None
                ),
                "canonical_url": url,
            },
        )
        reviews = api.request(
            "GET",
            f"/v1/projects/{project_id}/geo/destinations/{destination['id']}/policy-reviews",
        )
        if not reviews:
            host = destination["canonical_host"]
            api.request(
                "POST",
                f"/v1/projects/{project_id}/geo/destinations/{destination['id']}/policy-reviews",
                {
                    "status": policy,
                    "rules": {"manual_submission_only": True, "requirement": requirement},
                    "identity_requirements": {
                        "brand_relationship_disclosed": channel != "owned_site"
                    },
                    "disclosure_requirements": {
                        "commercial_relationship_disclosure": channel
                        in {"productreview", "reddit", "ozbargain", "quora"}
                    },
                    "allowed_hosts": [host],
                },
            )
        configured_destinations.append(destination)

    campaigns = api.request("GET", f"/v1/projects/{project_id}/geo/campaigns")
    campaign_by_name = {item["name"]: item for item in campaigns}
    campaign_rows: list[dict[str, Any]] = []
    destination_ids = [item["id"] for item in configured_destinations]
    for product in product_rows:
        name = f"{product['canonical_name']} AU Recommendation"
        campaign = campaign_by_name.get(name)
        if campaign is None:
            created = api.request(
                "POST",
                f"/v1/projects/{project_id}/geo/campaigns",
                {
                    "market_profile_id": market["id"],
                    "primary_product_entity_id": product["id"],
                    "name": name,
                    "objective": "recommendation_influence",
                    "destination_ids": destination_ids,
                    "opportunity_rationale": (
                        "Prepare an evidence-backed, policy-gated placement task for this product "
                        "and destination. Restricted destinations remain visible but blocked."
                    ),
                },
            )
            campaign = created["campaign"]
        existing_queries = api.request(
            "GET", f"/v1/projects/{project_id}/geo/campaigns/{campaign['id']}/monitoring-queries"
        )
        existing_text = {item["query_text"] for item in existing_queries}
        product_config = next(
            item for item in products if item["canonical_name"] == product["canonical_name"]
        )
        for query in product_config["queries"]:
            if query["text"] not in existing_text:
                api.request(
                    "POST",
                    f"/v1/projects/{project_id}/geo/campaigns/{campaign['id']}/monitoring-queries",
                    {
                        "market_profile_id": market["id"],
                        "query_text": query["text"],
                        "query_kind": query["kind"],
                        "locale": market_config["locale"],
                    },
                )
        campaign_rows.append(campaign)

    sources = api.request("GET", f"/v1/projects/{project_id}/knowledge/sources")
    source_titles = {item["title"] for item in sources}
    for source in manifest["knowledge_sources"]:
        title = source["title"]
        if title in source_titles:
            continue
        if source["source_kind"] == "url":
            api.request(
                "POST",
                f"/v1/projects/{project_id}/knowledge/sources",
                {
                    "source_kind": "url",
                    "title": title,
                    "source_url": source["source_url"],
                    "media_type": source["media_type"],
                },
                key=_key(project_id, title),
            )
        elif source["source_kind"] == "text_file":
            target_file = repository_root / source["source_path"]
            api.request(
                "POST",
                f"/v1/projects/{project_id}/knowledge/sources",
                {
                    "source_kind": "text",
                    "title": title,
                    "filename": target_file.name,
                    "media_type": source["media_type"],
                    "content_text": target_file.read_text(encoding="utf-8"),
                },
                key=_key(project_id, title),
            )
        else:
            raise ValueError(f"unsupported knowledge source kind: {source['source_kind']}")

    api.request("PUT", f"/v1/projects/{project_id}/geo/prompt-catalog/defaults")

    source_rows = _wait_for_official_sources(api, project_id, evidence_seeds)
    evidence = api.request("GET", f"/v1/projects/{project_id}/evidence-items?limit=500")
    evidence_hashes = {item["snapshot"]["sha256"] for item in evidence}
    entity_by_name = {
        brand["canonical_name"]: brand,
        **{item["canonical_name"]: item for item in product_rows},
    }
    for seed in evidence_seeds:
        title = seed["source_title"]
        statement = seed["statement"]
        subject_name = seed["subject_name"]
        subject_role = seed["subject_role"]
        snapshot_hash = hashlib.sha256(statement.encode()).hexdigest()
        if snapshot_hash in evidence_hashes:
            continue
        source = source_rows[title]
        api.request(
            "POST",
            f"/v1/projects/{project_id}/evidence-items",
            {
                "item_type": "citation",
                "source_id": source["id"],
                "subject_entity_id": entity_by_name[subject_name]["id"],
                "subject_role": subject_role,
                "locator": {"source_url": source["source_url"]},
                "snapshot": {"kind": "text", "text": statement, "sha256": snapshot_hash},
                "source_revision": {
                    "kind": "content_hash",
                    "value": source["content_hash"],
                },
                "usage_rights": "owned",
                "confidentiality": "public",
                "public_citation": {
                    "disclosure_allowed": True,
                    "source_url": source["source_url"],
                    "source_title": title,
                    "label": "Official ADVINSYS source",
                    "quotation_allowed": False,
                    "attribution_required": True,
                },
            },
        )

    return {
        "project_id": project_id,
        "project_name": project_name,
        "brand_id": brand["id"],
        "market_profile_id": market["id"],
        "product_ids": [item["id"] for item in product_rows],
        "destination_count": len(configured_destinations),
        "campaign_count": len(campaign_rows),
        "opportunity_count": len(campaign_rows) * len(configured_destinations),
        "knowledge_source_count": len(manifest["knowledge_sources"]),
        "evidence_count": len(evidence_seeds),
        "prompt_catalog_installed": True,
    }


def _key(project_id: str, title: str) -> str:
    digest = hashlib.sha256(f"{project_id}:{title}".encode()).hexdigest()[:24]
    return f"advinsys-bootstrap:{digest}"


def _wait_for_official_sources(
    api: Api, project_id: str, evidence_seeds: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    for _ in range(60):
        rows = api.request("GET", f"/v1/projects/{project_id}/knowledge/sources")
        by_title = {item["title"]: item for item in rows}
        required = {
            item["source_title"]: by_title.get(item["source_title"])
            for item in evidence_seeds
        }
        if all(item and item["status"] == "ready" and item["content_hash"] for item in required.values()):
            return {title: item for title, item in required.items() if item is not None}
        failed = [title for title, item in required.items() if item and item["status"] == "failed"]
        if failed:
            raise RuntimeError(f"official knowledge sources failed: {', '.join(failed)}")
        time.sleep(1)
    raise RuntimeError("official knowledge sources did not become ready within 60 seconds")


def expected_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_name": manifest["project"]["name"],
        "product_count": len(manifest["products"]),
        "destination_count": len(manifest["destinations"]),
        "optional_destination_count": len(manifest.get("optional_destinations", [])),
        "campaign_count": len(manifest["products"]),
        "opportunity_count": len(manifest["products"]) * len(manifest["destinations"]),
        "monitoring_query_count": sum(len(item["queries"]) for item in manifest["products"]),
        "knowledge_source_count": len(manifest["knowledge_sources"]),
        "evidence_seed_count": len(manifest["evidence_seeds"]),
    }


def verify(api: Api, manifest: dict[str, Any]) -> dict[str, object]:
    expected = expected_summary(manifest)
    projects = api.request("GET", "/v1/projects")["items"]
    project = next((item for item in projects if item["name"] == expected["project_name"]), None)
    if project is None:
        return {**expected, "ok": False, "missing": ["project"], "project_id": None}
    project_id = project["id"]
    entities = api.request("GET", f"/v1/projects/{project_id}/entities?limit=500")
    markets = api.request("GET", f"/v1/projects/{project_id}/market-profiles?limit=500")
    destinations = api.request("GET", f"/v1/projects/{project_id}/geo/destinations")
    campaigns = api.request("GET", f"/v1/projects/{project_id}/geo/campaigns")
    sources = api.request("GET", f"/v1/projects/{project_id}/knowledge/sources")
    evidence = api.request("GET", f"/v1/projects/{project_id}/evidence-items?limit=500")
    expected_names = {
        manifest["project"]["brand"]["canonical_name"],
        *(item["canonical_name"] for item in manifest["products"]),
    }
    expected_keys = {item["destination_key"] for item in manifest["destinations"]}
    expected_sources = {item["title"] for item in manifest["knowledge_sources"]}
    expected_hashes = {
        hashlib.sha256(item["statement"].encode()).hexdigest()
        for item in manifest["evidence_seeds"]
    }
    actual_opportunities = 0
    for campaign in campaigns:
        rows = api.request(
            "GET", f"/v1/projects/{project_id}/geo/campaigns/{campaign['id']}/opportunities"
        )
        actual_opportunities += len(rows)
    checks = {
        "entities": expected_names <= {item["canonical_name"] for item in entities},
        "market": any(
            item["market_code"] == manifest["project"]["market"]["market_code"]
            and item["locale"] == manifest["project"]["market"]["locale"]
            for item in markets
        ),
        "destinations": expected_keys <= {item["destination_key"] for item in destinations},
        "campaigns": len(campaigns) >= expected["campaign_count"],
        "opportunities": actual_opportunities >= expected["opportunity_count"],
        "knowledge_sources": expected_sources <= {item["title"] for item in sources},
        "knowledge_sources_ready": all(
            item["status"] == "ready" for item in sources if item["title"] in expected_sources
        ),
        "evidence_seeds": expected_hashes <= {
            item["snapshot"]["sha256"] for item in evidence
        },
    }
    return {
        **expected,
        "project_id": project_id,
        "checks": checks,
        "actual": {
            "entity_count": len(entities),
            "market_count": len(markets),
            "destination_count": len(destinations),
            "campaign_count": len(campaigns),
            "opportunity_count": actual_opportunities,
            "knowledge_source_count": len(sources),
            "evidence_count": len(evidence),
        },
        "ok": all(checks.values()),
    }


def receipt(action: str, manifest_path: Path, result: dict[str, object]) -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {
        "receipt_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "actual",
        "action": action,
        "manifest": str(manifest_path),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "git_commit": commit,
        "result": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--actor-id", default="30000000-0000-4000-8000-000000000003")
    parser.add_argument("--tenant-id", default="10000000-0000-4000-8000-000000000001")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, type=Path)
    parser.add_argument("--mode", choices=("actual",), default="actual")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--verify-only", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    action_name = "dry_run" if args.dry_run else "verify" if args.verify_only else "apply"
    if action_name == "dry_run":
        result = {**expected_summary(manifest), "ok": True, "mutated": False}
    else:
        api = Api(args.api_url, args.actor_id, args.tenant_id)
        if action_name == "apply":
            provision(api, manifest, Path(__file__).resolve().parents[1])
        result = verify(api, manifest)
        if not result["ok"]:
            raise RuntimeError(f"ADVINSYS verification failed: {result}")
    output = receipt(action_name, manifest_path, result)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
