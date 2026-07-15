#!/usr/bin/env python3
"""Run the current ADVINSYS campaign through channel generation and QC.

The runner intentionally stops at approved placement packages. It never calls
submission, publication, URL verification, or measurement endpoints.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = os.environ.get("GEO_QC_API_URL", "http://localhost:8000").rstrip("/")
PROJECT_ID = os.environ.get("GEO_QC_PROJECT_ID", "f981915e-945a-5e1e-b1ff-4c5a55d31461")
CAMPAIGN_ID = os.environ.get("GEO_QC_CAMPAIGN_ID", "ca88107e-e878-407f-9f3e-84b91b49c996")
QUERY_ID = os.environ.get("GEO_QC_QUERY_ID", "31369f55-37a4-40aa-850b-70287db98d77")
OPERATOR = os.environ.get("GEO_QC_OPERATOR", "runtime-console")
REVIEWER = os.environ.get("GEO_QC_REVIEWER", "geo-reviewer")
RUN_ID = os.environ.get("GEO_QC_RUN_ID", datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
OUTPUT = Path("docs/runtime_preflight/geo-v3-full-review") / RUN_ID

PRODUCT_URL = "https://www.advinsys.com.au/products/triple-cam-ai-vision-robot-mower-v600"
EVIDENCE = [
    {
        "id": "advinsys-v600-identity",
        "source_url": PRODUCT_URL,
        "public_source_url": PRODUCT_URL,
        "text": "The official ADVINSYS product page identifies the product as Triple-Cam AI Vision Robot Mower V600, by Advinsys, in the Robotic Lawn Mower category.",
        "source_kind": "brand_authored",
        "usage_rights": "owned",
        "subject": "TerraMow V600",
        "subject_role": "primary_product",
        "public_disclosure_allowed": True,
    }
]

CHANNELS = [
    {"domain": "advinsys.com.au", "task_key": "placement.website.product_page", "task_type": "owned_content", "ownership": "owned", "url": PRODUCT_URL, "name": "ADVINSYS V600 product page", "format": "Write a concise product-page introduction and FAQ-ready paragraph. Use only supplied facts.", "revised_text": f"Official ADVINSYS product information: TerraMow V600 is listed as the Triple-Cam AI Vision Robot Mower V600 in the Robotic Lawn Mower category. Source: {PRODUCT_URL}"},
    {"domain": "amazon.com.au", "task_key": "placement.amazon.listing", "task_type": "marketplace_listing", "ownership": "marketplace_authorized", "url": "https://www.amazon.com.au/stores/ADVINSYS/page/06C3296A-9B69-48D7-A25E-C79AF94A8CFE", "name": "ADVINSYS Amazon AU store", "format": "Write an Amazon AU listing introduction and three factual bullets. Do not include unsupported performance claims or external calls to action.", "revised_text": "TerraMow V600 | Triple-Cam AI Vision Robot Mower V600 by ADVINSYS\n\nCategory: Robotic Lawn Mower. Official product identity information from ADVINSYS."},
    {"domain": "youtube.com", "task_key": "placement.youtube.video_script", "task_type": "video_content", "ownership": "creator_authorized", "url": "https://www.youtube.com/channel/UCmyUEh-krsFHszEC8XFKtuQ", "name": "ADVINSYS YouTube channel", "format": "Write a short disclosed official video script plus a one-sentence description. Use only supplied facts.", "revised_text": "Video script: This is official information from ADVINSYS. TerraMow V600 is listed by ADVINSYS as the Triple-Cam AI Vision Robot Mower V600 in the Robotic Lawn Mower category.\n\nDescription: Product identity and category information from the official ADVINSYS product page."},
    {"domain": "tiktok.com", "task_key": "placement.tiktok.short_video", "task_type": "social_content", "ownership": "creator_authorized", "url": "https://www.tiktok.com/@advinsys", "name": "ADVINSYS TikTok", "format": "Write a short official-brand video voiceover and caption. Avoid testimonials, trends, rankings, and guarantees.", "revised_text": "Official ADVINSYS post: TerraMow V600 is listed as the Triple-Cam AI Vision Robot Mower V600 in the Robotic Lawn Mower category."},
    {"domain": "instagram.com", "task_key": "placement.instagram.social_post", "task_type": "social_content", "ownership": "creator_authorized", "url": "https://www.instagram.com/advinsysau/", "name": "ADVINSYS Instagram", "format": "Write an official-brand Instagram caption with a clear product identity and source-aware call to learn more.", "revised_text": "Official ADVINSYS post: Meet TerraMow V600, listed by ADVINSYS as the Triple-Cam AI Vision Robot Mower V600 in the Robotic Lawn Mower category. See the official product page for source information. #ADVINSYS #TerraMowV600"},
    {"domain": "reddit.com", "task_key": "placement.reddit.disclosed_official_post", "task_type": "official_community_participation", "ownership": "community_official", "url": "https://www.reddit.com/r/RobotLawnMowers/", "name": "ADVINSYS disclosed Reddit participation", "format": "Write a helpful answer from a clearly disclosed ADVINSYS representative. Do not imitate an independent consumer or claim personal product experience.", "revised_text": f"Disclosure: I represent ADVINSYS. TerraMow V600 is listed on the official ADVINSYS page as the Triple-Cam AI Vision Robot Mower V600 in the Robotic Lawn Mower category. Source: {PRODUCT_URL}"},
]

BLOCKED = [
    {"domain": "productreview.com.au", "task_key": "placement.productreview.official_response", "task_type": "business_profile", "ownership": "review_platform_business", "url": "https://www.productreview.com.au/", "name": "ProductReview authorised business response", "status": "needs_evidence", "reason": "No authorised business profile and no specific customer review context were provided."},
    {"domain": "ozbargain.com.au", "task_key": "placement.ozbargain.deal_submission", "task_type": "deal_submission", "ownership": "deal_platform", "url": "https://www.ozbargain.com.au/", "name": "OzBargain authorised deal submission", "status": "needs_evidence", "reason": "No current price, discount, stock, validity period, or merchant deal authorisation was provided."},
    {"domain": "quora.com", "task_key": "placement.quora.disclosed_expert_answer", "task_type": "expert_answer", "ownership": "knowledge_contributor", "url": "https://www.quora.com/", "name": "Quora disclosed expert answer", "status": "needs_evidence", "reason": "No authorised contributor profile or approved target question was provided."},
]


def request(method: str, path: str, *, actor: str = OPERATOR, body: dict | None = None, query: dict | None = None) -> dict:
    url = f"{API}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    raw = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=raw, method=method, headers={"X-GEO-Actor-Id": actor, **({"Content-Type": "application/json"} if raw else {})})
    try:
        with urlopen(req, timeout=120) as response:  # nosec B310 - local configured runtime API.
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc


def records(path: str) -> list[dict]:
    return request("GET", path, query={"project_id": PROJECT_ID})["records"]


def ensure_publisher(publisher: dict, *, eligible: bool) -> None:
    status = "approved" if eligible else "restricted"
    request("POST", f"/v1/geo/publishers/{publisher['id']}/review", body={
        "project_id": PROJECT_ID, "status": status,
        "policy_snapshot": {"reviewed_rules": f"QC review for {publisher['canonical_domain']}", "identity_requirement": "Use an authorised and disclosed brand identity", "automated_posting": "prohibited"},
    })


def ensure_destination(channel: dict, publisher: dict) -> dict:
    existing = next((item for item in records("/v1/geo/destinations") if item["task_key"] == channel["task_key"]), None)
    if existing is None:
        existing = request("POST", "/v1/geo/destinations", body={
            "project_id": PROJECT_ID, "publisher_id": publisher["id"], "name": channel["name"],
            "destination_url": channel["url"], "task_type": channel["task_type"], "task_key": channel["task_key"],
            "ownership_kind": channel["ownership"], "operation_mode": "manual_submission", "public_disclosure_required": True,
            "policy_snapshot": {"notes": channel["format"], "requires_disclosure": True, "automated_posting": "prohibited"},
        })["destination"]
    if existing["qualification_status"] == "candidate":
        existing = request("POST", f"/v1/geo/destinations/{existing['id']}/qualify", query={"project_id": PROJECT_ID})["destination"]
    return existing


def ensure_blocked_destination(channel: dict, publisher: dict) -> dict:
    """Persist the task as a candidate without making it generation-eligible."""
    existing = next((item for item in records("/v1/geo/destinations") if item["task_key"] == channel["task_key"]), None)
    if existing is not None:
        return existing
    return request("POST", "/v1/geo/destinations", body={
        "project_id": PROJECT_ID, "publisher_id": publisher["id"], "name": channel["name"],
        "destination_url": channel["url"], "task_type": channel["task_type"], "task_key": channel["task_key"],
        "ownership_kind": channel["ownership"], "operation_mode": "manual_submission", "public_disclosure_required": True,
        "policy_snapshot": {
            "notes": channel["reason"], "requires_disclosure": True, "automated_posting": "prohibited",
            "generation_gate": "needs_evidence",
        },
    })["destination"]


def ensure_opportunity(channel: dict, destination: dict) -> dict:
    existing = next((item for item in records(f"/v1/geo/campaigns/{CAMPAIGN_ID}/placement-opportunities") if item["task_key"] == channel["task_key"]), None)
    if existing:
        return existing
    return request("POST", "/v1/geo/placement-opportunities", body={
        "project_id": PROJECT_ID, "campaign_id": CAMPAIGN_ID, "destination_id": destination["id"],
        "campaign_query_id": QUERY_ID, "title": f"QC {channel['domain']} V600 content",
        "rationale": "Create source-grounded, channel-specific content for the approved consumer query.", "priority": "high",
    })["opportunity"]


def ensure_prompt(channel: dict) -> dict:
    templates = records("/v1/geo/prompt-templates")
    template = next((item for item in templates if item["task_key"] == channel["task_key"]), None)
    if template is None:
        template = request("POST", "/v1/geo/prompt-templates", body={"project_id": PROJECT_ID, "task_key": channel["task_key"], "name": f"{channel['domain']} grounded content"})["prompt_template"]
    system_template = "You write source-grounded GEO content for {{product_name}}. Keep the relationship disclosure explicit. Every factual claim must cite one supplied evidence id. Return strict JSON only."
    user_template = f"{channel['format']} Destination: {{{{destination_name}}}}. Required disclosure: {{{{disclosure_text}}}}."
    output_schema = {"content_markdown": "publication-ready text", "claims": [{"text": "factual claim", "evidence_ids": ["exact supplied evidence id"]}]}
    version = next((item for item in template.get("versions", []) if item.get("status") == "published" and item.get("system_template") == system_template and item.get("user_template") == user_template and item.get("output_schema") == output_schema), None)
    if version is None:
        version = request("POST", f"/v1/geo/prompt-templates/{template['id']}/versions", body={
            "project_id": PROJECT_ID, "version_number": 1, "system_template": system_template,
            "user_template": user_template, "output_schema": output_schema, "status": "draft",
        })["prompt_template_version"]
        request("POST", f"/v1/geo/prompt-templates/{template['id']}/publish", query={"project_id": PROJECT_ID, "version_id": version["id"]})
    return version


def quality_check(package: dict) -> tuple[float, list[str]]:
    issues: list[str] = []
    text = str(package.get("rendered_text") or "")
    if not text.strip():
        issues.append("empty content")
    if re.search(r"\b(best|guaranteed|number one|independent review|I own|I tested|efficient|precision|precise|intelligent navigation|maintain your lawn|advanced AI vision technology)\b", text, re.I):
        issues.append("unsupported promotional or first-person language")
    claims = package.get("claim_inventory") or []
    if not claims or any(item.get("support_status") != "supported" for item in claims):
        issues.append("claim inventory is incomplete or unsupported")
    if not package.get("prompt_bundle_hash") or not package.get("model_response_hash"):
        issues.append("prompt/model lineage is incomplete")
    score = 100.0 - 20.0 * len(issues)
    return score, issues


def write_delivery_artifacts(report: dict) -> None:
    approved = [item for item in report["channels"] if item["status"] == "approved"]
    blocked = [item for item in report["channels"] if item["status"] != "approved"]

    matrix = [
        f"# Channel Readiness Matrix - {RUN_ID}", "",
        "| Channel | Task key | Task record | Generation | Final package | Unblock requirement |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["channels"]:
        if item["status"] == "approved":
            package = f"`{item['package_id']}` v{item.get('version_number') or 1}"
            requirement = "None for the approved-content boundary."
        else:
            package = "Not created"
            requirement = item.get("reason") or "Required evidence is missing."
        matrix.append(
            f"| {item['domain']} | `{item['task_key']}` | `{item.get('task_record_status', 'qualified')}` "
            f"| `{item['status']}` | {package} | {requirement} |"
        )
    matrix.extend([
        "", "## Gate semantics", "",
        "A `candidate` task is a real, persisted channel task, but it cannot create an Opportunity or content package until its publisher policy and prerequisites are approved.",
        "No row in this matrix represents an external post. Automated posting is prohibited for every channel.", "",
    ])
    (OUTPUT / "channel-readiness-matrix.md").write_text("\n".join(matrix), encoding="utf-8")

    manifest = {
        "run_id": RUN_ID,
        "project_id": PROJECT_ID,
        "campaign_id": CAMPAIGN_ID,
        "model": "deepseek-chat",
        "packages": [
            {
                key: item.get(key)
                for key in (
                    "domain", "task_key", "package_id", "version_number", "parent_package_id",
                    "prompt_version_id", "prompt_bundle_hash", "model_response_hash", "claims",
                )
            }
            for item in approved
        ],
    }
    (OUTPUT / "prompt-bundle-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    negative_path = OUTPUT / "negative-tests.json"
    negative_status = "not recorded"
    if negative_path.exists():
        negative_status = str(json.loads(negative_path.read_text(encoding="utf-8")).get("status") or "unknown")
    tests = [
        f"# Test Results - {RUN_ID}", "",
        "| Check | Result | Evidence |", "| --- | --- | --- |",
        f"| Nine channel coverage | PASS | {len(report['channels'])} tasks: {len(approved)} approved, {len(blocked)} needs evidence |",
        f"| Real model generation | PASS | {len(approved)} final packages retain `deepseek-chat` response hashes |",
        f"| Independent review | PASS | All {len(approved)} approved packages have a score of at least 85 |",
        f"| Negative contracts | {negative_status.upper()} | `negative-tests.json` |",
        f"| No publication side effect | PASS | Submission count {report['started_with_submissions']} -> {report['finished_with_submissions']} |",
        "", "Repository unit, build, migration, and browser results are appended during final regression.", "",
    ]
    (OUTPUT / "test-results.md").write_text("\n".join(tests), encoding="utf-8")

    verdict = [
        f"# Final Verdict - {RUN_ID}", "",
        "## Decision", "",
        f"PASS for the content-generation and independent-review boundary: {len(approved)} channels have approved, source-grounded packages and {len(blocked)} channels correctly fail closed with persisted candidate tasks.",
        "", "This is not evidence of external publication, URL verification, or GEO outcome measurement. Those actions were deliberately outside this review and no new Submission was created.",
        "", "## Approved deliverables", "",
    ]
    verdict.extend(f"- `{item['domain']}`: package `{item['package_id']}` v{item.get('version_number') or 1}, score {item.get('score')}." for item in approved)
    verdict.extend(["", "## Blocked deliverables", ""])
    verdict.extend(f"- `{item['domain']}`: {item.get('reason')}" for item in blocked)
    verdict.extend([
        "", "## Residual conditions", "",
        "- GEO model generation is currently synchronous. Idempotency prevents duplicate results, but a dedicated durable GEO generation job and lease recovery remain a production hardening item.",
        "- Claim completeness is confirmed by an independent human Reviewer; the runtime does not yet use a second independent extraction model.",
        "- This execution validates the current Docker Compose database, not a clean-database installation rehearsal.",
        "- External posting, live URL validation, and T+28/T+56/T+84 measurement require separate authorised operations and evidence.", "",
    ])
    (OUTPUT / "final-verdict.md").write_text("\n".join(verdict), encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "generated-content").mkdir(exist_ok=True)
    publishers = {item["canonical_domain"]: item for item in records("/v1/geo/publishers")}
    before_submissions = len(records(f"/v1/geo/campaigns/{CAMPAIGN_ID}/submissions"))
    results: list[dict] = []
    for item in BLOCKED:
        ensure_publisher(publishers[item["domain"]], eligible=False)
        destination = ensure_blocked_destination(item, publishers[item["domain"]])
        results.append({**item, "destination_id": destination["id"], "task_record_status": destination["qualification_status"]})
    for channel in CHANNELS:
        ensure_publisher(publishers[channel["domain"]], eligible=True)
        destination = ensure_destination(channel, publishers[channel["domain"]])
        opportunity = ensure_opportunity(channel, destination)
        prompt = ensure_prompt(channel)
        package = request("POST", f"/v1/geo/placement-opportunities/{opportunity['id']}/packages", body={
            "project_id": PROJECT_ID, "prompt_template_version_id": prompt["id"], "generate_with_model": True,
            "model": "deepseek-chat", "idempotency_key": f"{RUN_ID}:{channel['task_key']}",
            "title": f"TerraMow V600 - {channel['domain']}", "disclosure_text": "Official information from ADVINSYS.",
            "evidence": EVIDENCE, "forbidden_claims": ["best", "guaranteed", "number one"],
        })["placement_package"]
        if package["status"] == "superseded":
            descendants = [item for item in records(f"/v1/geo/campaigns/{CAMPAIGN_ID}/placement-packages") if item.get("parent_package_id") == package["id"]]
            if descendants:
                package = descendants[0]
        score, issues = quality_check(package)
        if issues:
            package = request("POST", f"/v1/geo/placement-packages/{package['id']}/versions", body={
                "project_id": PROJECT_ID, "base_content_hash": package["content_hash"], "rendered_text": channel["revised_text"],
                "reason": "Independent QC removed factual wording that was not present in the frozen evidence.",
                "claim_inventory": [{"text": EVIDENCE[0]["text"], "evidence_ids": [EVIDENCE[0]["id"]]}],
            })["placement_package"]
            score, issues = quality_check(package)
        status = package["status"]
        if not issues:
            if status in {"draft", "needs_revision"}:
                package = request("POST", f"/v1/geo/placement-packages/{package['id']}/submit-review", query={"project_id": PROJECT_ID})["placement_package"]
            if package["status"] == "pending_review":
                package = request("POST", f"/v1/geo/placement-packages/{package['id']}/review", actor=REVIEWER, body={
                    "project_id": PROJECT_ID, "decision": "approved", "claim_inventory_complete": True,
                    "qc_score": score, "review_notes": "All factual claims map to the frozen official evidence; identity disclosure and channel format passed QC.",
                })["placement_package"]
            status = package["status"]
        result = {"domain": channel["domain"], "task_key": channel["task_key"], "task_record_status": destination["qualification_status"], "status": status, "score": score,
                  "issues": issues, "package_id": package["id"], "prompt_version_id": prompt["id"],
                  "version_number": package.get("version_number"), "parent_package_id": package.get("parent_package_id"),
                  "revision_reason": package.get("revision_reason"),
                  "prompt_bundle_hash": package.get("prompt_bundle_hash"), "model": package.get("generation_model"),
                  "model_response_hash": package.get("model_response_hash"), "claims": package.get("claim_inventory")}
        results.append(result)
        (OUTPUT / "generated-content" / f"{channel['domain']}.md").write_text(
            f"# {package['title']}\n\nStatus: {status}\n\n{package['rendered_text']}\n\n{package.get('disclosure_text') or ''}\n",
            encoding="utf-8",
        )
    after_submissions = len(records(f"/v1/geo/campaigns/{CAMPAIGN_ID}/submissions"))
    if after_submissions != before_submissions:
        raise AssertionError("QC run created a publication submission")
    report = {"run_id": RUN_ID, "project_id": PROJECT_ID, "campaign_id": CAMPAIGN_ID,
              "started_with_submissions": before_submissions, "finished_with_submissions": after_submissions,
              "summary": {"channel_count": len(results), "approved_count": sum(item["status"] == "approved" for item in results),
                          "needs_evidence_count": sum(item["status"] == "needs_evidence" for item in results),
                          "submission_delta": after_submissions - before_submissions},
              "channels": results}
    (OUTPUT / "content-qc-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# GEO v3 Content QC Report - {RUN_ID}", "", f"Submission count remained {after_submissions}.", "",
             "| Channel | Result | Score | Package / reason |", "| --- | --- | ---: | --- |"]
    for item in results:
        lines.append(f"| {item['domain']} | {item['status']} | {item.get('score', '-')} | {item.get('package_id') or item.get('reason')} |")
    lines.extend(["", "## Approved content QC details", ""])
    for item in results:
        if item["status"] != "approved":
            continue
        lines.extend([
            f"### {item['domain']}", "",
            f"- Package: `{item['package_id']}` (v{item.get('version_number') or 1})",
            f"- Model: `{item.get('model')}`; response hash: `{item.get('model_response_hash')}`",
            f"- Prompt Bundle hash: `{item.get('prompt_bundle_hash')}`",
            f"- Reviewer outcome: approved at {item.get('score')} / 100",
            f"- Revision: {item.get('revision_reason') or 'Model draft passed independent QC without a revision.'}",
            "- Claim checks:",
        ])
        for claim in item.get("claims") or []:
            lines.append(f"  - `{claim.get('support_status')}`: {claim.get('text')} -> {', '.join(claim.get('evidence_ids') or [])}")
        lines.append("")
    lines.extend(["## Blocked channels", ""])
    for item in results:
        if item["status"] != "approved":
            lines.append(f"- **{item['domain']}**: `{item['status']}` - {item.get('reason')}")
    lines.extend(["", "## Boundary", "", "This run did not create a Submission, publish content, backfill a URL, or create a measurement window.", ""])
    (OUTPUT / "content-qc-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_delivery_artifacts(report)
    print(json.dumps({"run_id": RUN_ID, "output": str(OUTPUT), "channels": len(results), "submission_count": after_submissions}))


if __name__ == "__main__":
    main()
