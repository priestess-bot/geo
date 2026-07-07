from __future__ import annotations

import json
from pathlib import Path

from geno_core.knowledge import KNOWLEDGE_FACT_APPROVED_STATUS
from geno_core.knowledge_application import build_knowledge_application_artifacts


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "tmp/promptfoo-knowledge-eval/latest.json"


def build_eval_report() -> dict[str, object]:
    project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
    facts = (
        {
            "id": "06975d61-853b-5a25-ae0e-b62bbfe82c15",
            "project_id": project_id,
            "status": KNOWLEDGE_FACT_APPROVED_STATUS,
            "fact_type": "shipping_policy",
            "subject": "KoalaHome",
            "predicate": "has_shipping_policy",
            "object_value": "KoalaHome offers fast Australian metro delivery over A$99.",
            "city": "Sydney",
        },
        {
            "id": "b6a1e17c-25c5-5b66-9d8d-507967fded52",
            "project_id": project_id,
            "status": "pending_review",
            "fact_type": "unsupported_claim",
            "subject": "KoalaHome",
            "predicate": "states",
            "object_value": "KoalaHome is the best furniture brand in the world.",
            "city": "Sydney",
        },
    )
    prompts = (
        {
            "id": "11111111-1111-5111-8111-111111111111",
            "text": "Does KoalaHome offer fast delivery in Sydney?",
            "intent_type": "shipping",
            "city": "Sydney",
        },
    )
    artifacts = build_knowledge_application_artifacts(
        project_id=project_id,
        target_brand="KoalaHome",
        category="homewares",
        market_code="AU",
        facts=facts,
        prompts=prompts,
        action=None,
        generation_type="all",
        content_type="faq",
        target_platform="chatgpt",
        intent_type="shipping",
        city="Sydney",
        competitor=None,
        quantity=3,
        requested_by="promptfoo-eval",
        generation_job_id="3d8d9288-9056-50a1-b96e-1c38d4bce622",
    )
    draft_text = "\n".join(draft.draft_markdown for draft in artifacts.content_drafts)
    prompt_text = "\n".join(str(candidate["text"]) for candidate in artifacts.prompt_candidates)
    faq_text = "\n".join(str(candidate["answer_markdown"]) for candidate in artifacts.faq_candidates)
    generated_text = "\n".join((draft_text, prompt_text, faq_text))
    checks = [
        {
            "name": "uses_approved_fact",
            "status": "pass"
            if "KoalaHome offers fast Australian metro delivery over A$99." in generated_text
            else "fail",
        },
        {
            "name": "excludes_pending_review_fact",
            "status": "pass" if "best furniture brand in the world" not in generated_text else "fail",
        },
        {
            "name": "all_outputs_reference_source_fact_ids",
            "status": "pass"
            if artifacts.content_drafts[0].used_knowledge_fact_ids
            and all(candidate["source_knowledge_fact_ids"] for candidate in artifacts.prompt_candidates)
            and all(candidate["used_knowledge_fact_ids"] for candidate in artifacts.faq_candidates)
            else "fail",
        },
    ]
    return {
        "provider": "promptfoo-compatible-local-eval",
        "model": "deepseek-v4-flash",
        "status": "passed" if all(check["status"] == "pass" for check in checks) else "failed",
        "checks": checks,
        "summary": {
            "pass": sum(1 for check in checks if check["status"] == "pass"),
            "fail": sum(1 for check in checks if check["status"] == "fail"),
        },
        "artifact_counts": {
            "content_drafts": len(artifacts.content_drafts),
            "prompt_candidates": len(artifacts.prompt_candidates),
            "faq_candidates": len(artifacts.faq_candidates),
        },
        "raw_output_hash": artifacts.raw_output_hash,
    }


def main() -> int:
    report = build_eval_report()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
