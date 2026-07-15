from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from geo_core.audit import build_audit_event, hash_payload
from geo_core.knowledge import CONTENT_REVIEW_PENDING_STATUS, KNOWLEDGE_FACT_APPROVED_STATUS
from geo_core.models import (
    AuditEvent,
    ContentDraft,
    LocalizedKnowledgeFact,
)


DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
DEEPSEEK_DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_API_KEY_FILE_ENV = "GEO_DEEPSEEK_API_KEY_FILE"
KNOWLEDGE_APPLICATION_PIPELINE_VERSION = "knowledge_application_haystack_adapter_v1"
KNOWLEDGE_CRAWLER_ADAPTER_VERSION = "crawl4ai_adapter_v1"
KNOWLEDGE_FACT_EXTRACTION_PROMPT_VERSION = "knowledge_fact_extraction_v1"
GEO_CONTENT_DRAFT_PROMPT_VERSION = "geo_content_draft_v1"
GEO_FAQ_CANDIDATE_PROMPT_VERSION = "geo_faq_candidate_v1"
GEO_PROMPT_CANDIDATE_PROMPT_VERSION = "geo_prompt_candidate_v1"

DOCUMENT_STATUS_QUEUED = "queued"
DOCUMENT_STATUS_CRAWLING = "crawling"
DOCUMENT_STATUS_CRAWLED = "crawled"
DOCUMENT_STATUS_EXTRACTING = "extracting"
DOCUMENT_STATUS_EXTRACTED = "extracted"
DOCUMENT_STATUS_FAILED = "failed"
DOCUMENT_STATUS_ARCHIVED = "archived"

PROMPT_CANDIDATE_PENDING = "pending_review"
PROMPT_CANDIDATE_APPROVED = "approved"
PROMPT_CANDIDATE_REJECTED = "rejected"
PROMPT_CANDIDATE_IMPORTED = "imported"
PROMPT_CANDIDATE_ARCHIVED = "archived"

FAQ_CANDIDATE_PENDING = "pending_review"

PRIVATE_HOST_ERROR = "blocked_private_network"
UNSUPPORTED_URL_ERROR = "unsupported_url"
CONTENT_TOO_LARGE_ERROR = "content_too_large"
UNSUPPORTED_CONTENT_TYPE_ERROR = "unsupported_content_type"
CRAWL_PARSE_FAILED_ERROR = "crawl_parse_failed"


@dataclass(frozen=True)
class CrawlResult:
    source_url: str
    normalized_url: str
    title: str
    markdown: str
    status_code: int
    content_type: str
    content_hash: str
    byte_size: int
    adapter_version: str = KNOWLEDGE_CRAWLER_ADAPTER_VERSION


@dataclass(frozen=True)
class KnowledgeExtractionResult:
    facts: tuple[LocalizedKnowledgeFact, ...]
    audit_event: AuditEvent
    raw_output_hash: str


@dataclass(frozen=True)
class KnowledgeApplicationArtifacts:
    content_drafts: tuple[ContentDraft, ...]
    prompt_candidates: tuple[dict[str, Any], ...]
    faq_candidates: tuple[dict[str, Any], ...]
    audit_event: AuditEvent
    raw_output_hash: str


def stable_knowledge_id(kind: str, *parts: object) -> str:
    payload = ":".join(str(part) for part in parts)
    return str(uuid5(NAMESPACE_URL, f"geo:{kind}:{payload}"))


def load_deepseek_api_key(*, api_key: str | None = None, key_file: str | Path | None = None) -> str | None:
    explicit_key = (api_key or "").strip()
    if explicit_key:
        return explicit_key
    env_key = os.getenv(DEEPSEEK_API_KEY_ENV, "").strip()
    if env_key:
        return env_key
    configured_key_file = key_file or os.getenv(DEEPSEEK_API_KEY_FILE_ENV, "").strip()
    candidate_paths = []
    if configured_key_file:
        candidate_paths.append(Path(configured_key_file))
    candidate_paths.append(Path(__file__).resolve().parents[3] / "deepseek_api_key.txt")
    for path in candidate_paths:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return None


def normalize_knowledge_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(UNSUPPORTED_URL_ERROR)
    if not parsed.hostname:
        raise ValueError(UNSUPPORTED_URL_ERROR)
    hostname = parsed.hostname.lower()
    if _is_private_hostname(hostname):
        raise ValueError(PRIVATE_HOST_ERROR)
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{hostname}{path}{query}"


def crawl_public_knowledge_url(
    *,
    source_url: str,
    max_bytes: int = 2_000_000,
    timeout_seconds: float = 20.0,
    http_get: Any | None = None,
) -> CrawlResult:
    normalized_url = normalize_knowledge_url(source_url)
    getter = http_get or _default_http_get
    payload = getter(normalized_url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    content_type = str(payload.get("content_type") or "text/html").split(";", 1)[0].strip().lower()
    if content_type not in {"text/html", "text/plain", "text/markdown"}:
        raise ValueError(UNSUPPORTED_CONTENT_TYPE_ERROR)
    body = bytes(payload.get("body") or b"")
    if len(body) > max_bytes:
        raise ValueError(CONTENT_TOO_LARGE_ERROR)
    text = body.decode(str(payload.get("charset") or "utf-8"), errors="replace")
    if content_type == "text/html":
        parsed = _html_to_markdown(text)
        markdown = parsed["markdown"]
        title = parsed["title"] or normalized_url
    else:
        markdown = _clean_text(text)
        title = normalized_url
    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return CrawlResult(
        source_url=source_url,
        normalized_url=normalized_url,
        title=title,
        markdown=markdown,
        status_code=int(payload.get("status_code") or 200),
        content_type=content_type,
        content_hash=content_hash,
        byte_size=len(body),
    )


def extract_knowledge_facts_from_document(
    *,
    project_id: str,
    document_id: str,
    document_version_id: str,
    raw_text: str,
    source_url: str | None,
    market_code: str,
    target_brand: str,
    category: str,
    extracted_by: str,
    max_facts: int = 20,
    auto_approve: bool = False,
    model: str = DEEPSEEK_DEFAULT_MODEL,
    model_facts: tuple[dict[str, Any], ...] | None = None,
) -> KnowledgeExtractionResult:
    text = _clean_text(raw_text)
    model_fact_rows = tuple(model_facts or ())
    sentences = _candidate_sentences(text) if not model_fact_rows else []
    now = datetime.now(UTC)
    facts: list[LocalizedKnowledgeFact] = []
    source_rows = model_fact_rows[: max(1, min(max_facts, 50))] or tuple(
        {"object_value": sentence, "fact_type": _classify_fact_type(sentence)}
        for sentence in sentences[: max(1, min(max_facts, 50))]
    )
    for index, row in enumerate(source_rows, start=1):
        sentence = _clean_text(str(row.get("object_value") or row.get("claim") or ""))
        if not sentence:
            continue
        fact_type = str(row.get("fact_type") or _classify_fact_type(sentence)).strip() or "brand_claim"
        subject_value = str(row.get("subject") or "").strip()
        subject = subject_value or (
            target_brand if target_brand and target_brand.lower() in sentence.lower() else (target_brand or category or "brand")
        )
        predicate = str(row.get("predicate") or _predicate_for_fact_type(fact_type)).strip() or "states"
        confidence = _clamp_float(row.get("confidence"), default=0.82, minimum=0.0, maximum=1.0)
        facts.append(
            LocalizedKnowledgeFact(
                id=stable_knowledge_id(
                    "knowledge-fact-extract",
                    project_id,
                    document_version_id,
                    fact_type,
                    index,
                    sentence,
                ),
                project_id=project_id,
                market_code=market_code or "AU",
                fact_type=fact_type,
                subject=subject,
                predicate=predicate,
                object_value=sentence[:1000],
                city=str(row.get("city")).strip() if row.get("city") else None,
                evidence_source_id=None,
                confidence=confidence,
                status=KNOWLEDGE_FACT_APPROVED_STATUS if auto_approve else "pending_review",
                valid_from=now,
                valid_until=None,
            )
        )
    raw_output = {
        "model": model,
        "prompt_version": KNOWLEDGE_FACT_EXTRACTION_PROMPT_VERSION,
        "fact_count": len(facts),
        "document_id": document_id,
        "document_version_id": document_version_id,
        "model_fact_count": len(model_fact_rows),
    }
    raw_output_hash = hash_payload(raw_output)
    audit_event = build_audit_event(
        event_type="knowledge.fact_extracted",
        project_id=project_id,
        actor_type="worker",
        actor_id=extracted_by,
        target_type="knowledge_document",
        target_id=document_id,
        before=None,
        after=raw_output,
        input_refs={"knowledge_document_ids": [document_id], "source_urls": [source_url] if source_url else []},
        output_refs={"knowledge_fact_ids": [fact.id for fact in facts]},
        method_version=KNOWLEDGE_FACT_EXTRACTION_PROMPT_VERSION,
        reason="extract reviewable knowledge facts from approved source document",
    )
    return KnowledgeExtractionResult(facts=tuple(facts), audit_event=audit_event, raw_output_hash=raw_output_hash)


def build_knowledge_application_artifacts(
    *,
    project_id: str,
    target_brand: str,
    category: str,
    market_code: str,
    facts: tuple[dict[str, Any], ...],
    prompts: tuple[dict[str, Any], ...],
    action: dict[str, Any] | None,
    generation_type: str,
    content_type: str,
    target_platform: str,
    intent_type: str | None,
    city: str | None,
    competitor: str | None,
    quantity: int,
    requested_by: str,
    generation_job_id: str,
    model: str = DEEPSEEK_DEFAULT_MODEL,
    model_output: dict[str, Any] | None = None,
) -> KnowledgeApplicationArtifacts:
    approved_facts = tuple(fact for fact in facts if str(fact.get("status") or "") == KNOWLEDGE_FACT_APPROVED_STATUS)
    fact_ids = tuple(str(fact.get("id")) for fact in approved_facts if fact.get("id"))
    prompt_records = _select_prompts(prompts=prompts, intent_type=intent_type, city=city, limit=max(quantity, 5))
    output_quantity = max(1, min(quantity, 50))
    content_drafts: list[ContentDraft] = []
    prompt_candidates: list[dict[str, Any]] = []
    faq_candidates: list[dict[str, Any]] = []
    now = datetime.now(UTC)

    if generation_type in {"content_draft", "all"}:
        draft = _build_content_draft(
            project_id=project_id,
            target_brand=target_brand,
            category=category,
            facts=approved_facts,
            prompts=prompt_records,
            action=action,
            content_type=content_type,
            target_platform=target_platform,
            city=city,
            generation_job_id=generation_job_id,
            requested_by=requested_by,
            created_at=now,
            model_output=model_output,
        )
        content_drafts.append(draft)
    if generation_type in {"faq_candidates", "all"}:
        faq_candidates.extend(
            _build_faq_candidates(
                project_id=project_id,
                target_brand=target_brand,
                category=category,
                market_code=market_code,
                facts=approved_facts,
                prompts=prompt_records,
                generation_job_id=generation_job_id,
                quantity=output_quantity,
                city=city,
                model=model,
                model_output=model_output,
            )
        )
    if generation_type in {"prompt_candidates", "all"}:
        prompt_candidates.extend(
            _build_prompt_candidates(
                project_id=project_id,
                target_brand=target_brand,
                category=category,
                market_code=market_code,
                facts=approved_facts,
                prompts=prompts,
                generation_job_id=generation_job_id,
                quantity=output_quantity,
                intent_type=intent_type,
                city=city,
                competitor=competitor,
                model=model,
                model_output=model_output,
            )
        )

    raw_output = {
        "pipeline": KNOWLEDGE_APPLICATION_PIPELINE_VERSION,
        "model": model,
        "generation_type": generation_type,
        "content_type": content_type,
        "content_draft_count": len(content_drafts),
        "faq_candidate_count": len(faq_candidates),
        "prompt_candidate_count": len(prompt_candidates),
        "knowledge_fact_ids": fact_ids,
        "model_output_hash": hash_payload(model_output) if model_output else None,
    }
    raw_output_hash = hash_payload(raw_output)
    audit_event = build_audit_event(
        event_type="knowledge.application_generated",
        project_id=project_id,
        actor_type="worker",
        actor_id=requested_by,
        target_type="knowledge_generation_job",
        target_id=generation_job_id,
        before=None,
        after=raw_output,
        input_refs={
            "knowledge_fact_ids": list(fact_ids),
            "prompt_question_ids": [str(prompt.get("id")) for prompt in prompt_records if prompt.get("id")],
        },
        output_refs={
            "content_draft_ids": [draft.id for draft in content_drafts],
            "prompt_candidate_ids": [str(candidate["id"]) for candidate in prompt_candidates],
            "faq_candidate_ids": [str(candidate["id"]) for candidate in faq_candidates],
        },
        method_version=KNOWLEDGE_APPLICATION_PIPELINE_VERSION,
        reason="generate reviewable GEO content, FAQ, and prompt candidates from approved knowledge",
    )
    return KnowledgeApplicationArtifacts(
        content_drafts=tuple(content_drafts),
        prompt_candidates=tuple(prompt_candidates),
        faq_candidates=tuple(faq_candidates),
        audit_event=audit_event,
        raw_output_hash=raw_output_hash,
    )


def deepseek_extract_knowledge_facts(
    *,
    api_key: str,
    raw_text: str,
    target_brand: str,
    category: str,
    market_code: str,
    max_facts: int,
    requested_fact_kinds: tuple[str, ...] = ("brand", "competitor", "market", "source"),
    model: str = DEEPSEEK_DEFAULT_MODEL,
    endpoint: str = DEEPSEEK_DEFAULT_ENDPOINT,
    timeout_seconds: float = 45.0,
    http_post: Any | None = None,
) -> tuple[dict[str, Any], ...]:
    payload = _deepseek_chat_json(
        api_key=api_key,
        model=model,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        http_post=http_post,
        system_prompt=(
            "You extract reviewable GEO knowledge facts. Return strict JSON only. "
            "Do not invent facts. Use short claims grounded in the supplied document. "
            "When the source supports them, cover every requested fact_kind at least once."
        ),
        user_payload={
            "task": "extract_knowledge_facts",
            "schema": {
                "facts": [
                    {
                        "fact_kind": "brand|competitor|market|source",
                        "fact_type": (
                            "brand_identity|product_line|selling_point|shipping_policy|returns_policy|pricing_policy|"
                            "warranty|customer_support|review_source|certification|local_market_claim|"
                            "competitor_identity|competitor_product_line|competitor_selling_point|competitor_pricing|"
                            "competitor_channel|competitor_review_source|competitor_weakness|comparison_dimension|"
                            "market_requirement|city_context|local_policy|consumer_concern|seasonality|language_variant|"
                            "source_authority|source_type|publication_date|citation_availability|source_gap"
                        ),
                        "subject": "brand or entity",
                        "predicate": "short predicate",
                        "object_value": "one grounded claim",
                        "city": "optional city or null",
                        "confidence": 0.0,
                    }
                ]
            },
            "target_brand": target_brand,
            "category": category,
            "market_code": market_code,
            "max_facts": max(1, min(max_facts, 50)),
            "requested_fact_kinds": [
                value for value in requested_fact_kinds if value in {"brand", "competitor", "market", "source"}
            ],
            "document_text": raw_text[:12000],
        },
    )
    facts = payload.get("facts")
    if not isinstance(facts, list):
        raise ValueError("deepseek knowledge extraction response missing facts list")
    return tuple(_model_object(item) for item in facts[: max(1, min(max_facts, 50))])


def deepseek_generate_knowledge_application(
    *,
    api_key: str,
    target_brand: str,
    category: str,
    market_code: str,
    facts: tuple[dict[str, Any], ...],
    prompts: tuple[dict[str, Any], ...],
    generation_type: str,
    content_type: str,
    target_platform: str,
    intent_type: str | None,
    city: str | None,
    competitor: str | None,
    quantity: int,
    template_instruction: str | None = None,
    output_schema: dict[str, Any] | None = None,
    target_audience: str | None = None,
    forbidden_claims: tuple[str, ...] = (),
    target_action: dict[str, Any] | None = None,
    model: str = DEEPSEEK_DEFAULT_MODEL,
    endpoint: str = DEEPSEEK_DEFAULT_ENDPOINT,
    timeout_seconds: float = 60.0,
    http_post: Any | None = None,
) -> dict[str, Any]:
    payload = _deepseek_chat_json(
        api_key=api_key,
        model=model,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        http_post=http_post,
        system_prompt=(
            "You generate GEO content assets from approved knowledge. Return strict JSON only. "
            "Every claim must be supported by the provided fact ids. Do not expose secrets. "
            + (template_instruction or "")
        ),
        user_payload={
            "task": "generate_geo_knowledge_application",
            "schema": output_schema or {
                "content_markdown": "grounded draft markdown",
                "faq_candidates": [{"question": "string", "answer_markdown": "string"}],
                "prompt_candidates": [{"text": "string"}],
            },
            "target_brand": target_brand,
            "category": category,
            "market_code": market_code,
            "generation_type": generation_type,
            "content_type": content_type,
            "target_platform": target_platform,
            "intent_type": intent_type,
            "city": city,
            "competitor": competitor,
            "target_audience": target_audience,
            "forbidden_claims": list(forbidden_claims),
            "target_action": target_action or {},
            "quantity": max(1, min(quantity, 50)),
            "approved_facts": [schema_guard_payload(fact) for fact in facts[:50]],
            "existing_prompts": [schema_guard_payload(prompt) for prompt in prompts[:50]],
        },
    )
    return {
        "content_markdown": str(payload.get("content_markdown") or "").strip(),
        "claims": _model_items(payload.get("claims")),
        "faq_candidates": _model_items(payload.get("faq_candidates")),
        "prompt_candidates": _model_items(payload.get("prompt_candidates")),
        "model": model,
        "endpoint": endpoint,
        "response_hash": hash_payload(payload),
    }


def _default_http_get(url: str, *, timeout_seconds: float, max_bytes: int) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "GEO-Knowledge-Crawler/1.0"}, method="GET")
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - URL is validated before fetch.
        body = response.read(max_bytes + 1)
        return {
            "body": body,
            "status_code": response.status,
            "content_type": response.headers.get("content-type", "text/html"),
            "charset": response.headers.get_content_charset() or "utf-8",
        }


def _default_http_post(
    endpoint: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - DeepSeek endpoint is caller controlled by config.
        body = response.read(2_000_000)
        return {
            "status_code": response.status,
            "body": body,
            "content_type": response.headers.get("content-type", "application/json"),
            "charset": response.headers.get_content_charset() or "utf-8",
        }


def _deepseek_chat_json(
    *,
    api_key: str,
    model: str,
    endpoint: str,
    timeout_seconds: float,
    http_post: Any | None,
    system_prompt: str,
    user_payload: dict[str, Any],
) -> dict[str, Any]:
    normalized_key = api_key.strip()
    if not normalized_key:
        raise ValueError("deepseek api key is required")
    poster = http_post or _default_http_post
    request_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
            ],
            "temperature": 0,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
    last_content_error: ValueError | None = None
    for attempt in range(2):
        if attempt:
            request_payload["messages"] = [
                {
                    "role": "system",
                    "content": system_prompt
                    + " The previous response was invalid. Return exactly one complete JSON object with no prose or fences.",
                },
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
            ]
        response = poster(
            endpoint,
            headers={"Authorization": f"Bearer {normalized_key}", "Content-Type": "application/json"},
            payload=request_payload,
            timeout_seconds=timeout_seconds,
        )
        status_code = int(response.get("status_code") or 0)
        body = bytes(response.get("body") or b"")
        text = body.decode(str(response.get("charset") or "utf-8"), errors="replace")
        if status_code < 200 or status_code >= 300:
            raise ValueError(f"deepseek request failed with status {status_code}")
        try:
            payload = json.loads(text)
        except ValueError as exc:
            last_content_error = ValueError("deepseek response is not valid JSON")
            last_content_error.__cause__ = exc
            continue
        try:
            return _parse_json_object(_deepseek_message_content(payload))
        except ValueError as exc:
            last_content_error = exc
    raise ValueError("deepseek response content is not a JSON object after retry") from last_content_error


def _deepseek_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("deepseek response missing choices")
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    raise ValueError("deepseek response missing message content")


def _parse_json_object(text: str) -> dict[str, Any]:
    normalized = text.strip()
    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:json)?", "", normalized, flags=re.IGNORECASE).strip()
        normalized = re.sub(r"```$", "", normalized).strip()
    if not normalized.startswith("{"):
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start >= 0 and end > start:
            normalized = normalized[start : end + 1]
    payload = json.loads(normalized)
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object")
    return payload


def _is_private_hostname(hostname: str) -> bool:
    if hostname in {"localhost", "metadata.google.internal"}:
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local or address.is_multicast


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)


def _html_to_markdown(html: str) -> dict[str, str]:
    parser = _HTMLTextParser()
    try:
        parser.feed(html)
    except Exception as exc:  # pragma: no cover - defensive parser guard.
        raise ValueError(CRAWL_PARSE_FAILED_ERROR) from exc
    return {"title": _clean_text(" ".join(parser.title_parts)), "markdown": _clean_text(" ".join(parser.text_parts))}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _candidate_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?。！？])\s+", text)
    candidates = []
    for piece in pieces:
        normalized = _clean_text(piece)
        if len(normalized) >= 24:
            candidates.append(normalized)
    if not candidates and text:
        candidates.append(_clean_text(text)[:1000])
    return candidates


def _classify_fact_type(sentence: str) -> str:
    lowered = sentence.lower()
    if any(token in lowered for token in ("shipping", "delivery", "dispatch")):
        return "shipping_policy"
    if any(token in lowered for token in ("return", "refund", "exchange")):
        return "returns_policy"
    if any(token in lowered for token in ("price", "pricing", "$", "aud")):
        return "pricing"
    if any(token in lowered for token in ("review", "rating", "testimonial")):
        return "review_proof"
    if any(token in lowered for token in ("support", "contact", "help")):
        return "support_policy"
    return "brand_claim"


def _predicate_for_fact_type(fact_type: str) -> str:
    mapping = {
        "shipping_policy": "has_shipping_policy",
        "returns_policy": "has_returns_policy",
        "pricing": "has_pricing_context",
        "review_proof": "has_review_proof",
        "support_policy": "has_support_policy",
    }
    return mapping.get(fact_type, "states")


def _select_prompts(
    *,
    prompts: tuple[dict[str, Any], ...],
    intent_type: str | None,
    city: str | None,
    limit: int,
) -> tuple[dict[str, Any], ...]:
    selected = []
    for prompt in prompts:
        if intent_type and str(prompt.get("intent_type") or "") != intent_type:
            continue
        if city and str(prompt.get("city") or "") not in {city, "Australia"}:
            continue
        selected.append(prompt)
    return tuple(selected[:limit] or prompts[:limit])


def _build_content_draft(
    *,
    project_id: str,
    target_brand: str,
    category: str,
    facts: tuple[dict[str, Any], ...],
    prompts: tuple[dict[str, Any], ...],
    action: dict[str, Any] | None,
    content_type: str,
    target_platform: str,
    city: str | None,
    generation_job_id: str,
    requested_by: str,
    created_at: datetime,
    model_output: dict[str, Any] | None,
) -> ContentDraft:
    fact_lines = "\n".join(
        f"- [{fact.get('id')}] {fact.get('subject')} {fact.get('predicate')} {fact.get('object_value')}"
        for fact in facts[:8]
    )
    prompt_lines = "\n".join(f"- {prompt.get('text')}" for prompt in prompts[:5])
    title = f"{target_brand} {content_type.replace('_', ' ')} for GEO"
    model_markdown = str((model_output or {}).get("content_markdown") or "").strip()
    draft_markdown = model_markdown or (
        f"# {title}\n\n"
        f"Target platform: {target_platform}\n\n"
        f"Purpose: improve {target_brand} visibility for {category} questions.\n\n"
        "Target prompts:\n"
        f"{prompt_lines or '- No prompt selected'}\n\n"
        "Grounded claims:\n"
        f"{fact_lines or '- No approved facts available'}\n\n"
        "Reviewer checklist:\n"
        "- Confirm every claim against the linked approved fact.\n"
        "- Remove unsupported superlatives such as best, first, guaranteed, or official unless explicitly proven.\n"
        "- Keep this draft internal until human approval."
    )
    target_question_ids = tuple(str(prompt.get("id")) for prompt in prompts[:5] if prompt.get("id"))
    used_fact_ids = tuple(str(fact.get("id")) for fact in facts[:8] if fact.get("id"))
    if model_markdown and used_fact_ids and "Grounding fact ids" not in draft_markdown:
        draft_markdown = f"{draft_markdown}\n\nGrounding fact ids:\n" + "\n".join(f"- {fact_id}" for fact_id in used_fact_ids)
    return ContentDraft(
        id=stable_knowledge_id("knowledge-content-draft", project_id, generation_job_id, content_type, target_platform),
        project_id=project_id,
        title=title,
        content_type=f"geo_{content_type}",
        content_template_id=GEO_CONTENT_DRAFT_PROMPT_VERSION,
        target_question_ids=target_question_ids,
        target_city=city or "Australia",
        target_platform=target_platform,
        target_source_type="knowledge_application",
        used_knowledge_fact_ids=used_fact_ids,
        source_gap_types=tuple(filter(None, (str(action.get("source_gap_type")) if action else None,))),
        source_action_id=str(action.get("id")) if action and action.get("id") else None,
        evidence_answer_run_ids=tuple(),
        draft_markdown=draft_markdown,
        review_status=CONTENT_REVIEW_PENDING_STATUS,
        created_by=requested_by,
        created_at=created_at,
    )


def _build_faq_candidates(
    *,
    project_id: str,
    target_brand: str,
    category: str,
    market_code: str,
    facts: tuple[dict[str, Any], ...],
    prompts: tuple[dict[str, Any], ...],
    generation_job_id: str,
    quantity: int,
    city: str | None,
    model: str,
    model_output: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates = []
    model_candidates = _model_items((model_output or {}).get("faq_candidates"))
    for index, fact in enumerate(facts[:quantity], start=1):
        question = f"What should customers know about {target_brand} {fact.get('fact_type', 'service')}?"
        if index <= len(prompts):
            question = str(prompts[index - 1].get("text") or question)
        model_candidate = model_candidates[index - 1] if index <= len(model_candidates) else {}
        question = str(model_candidate.get("question") or question)
        answer = str(model_candidate.get("answer_markdown") or f"{target_brand} {fact.get('predicate', 'states')} {fact.get('object_value', '')}")
        candidate_id = stable_knowledge_id("faq-candidate", project_id, generation_job_id, index, question)
        candidates.append(
            {
                "id": candidate_id,
                "project_id": project_id,
                "generation_job_id": generation_job_id,
                "question": question[:1000],
                "answer_markdown": answer[:4000],
                "target_prompt_ids": [str(prompts[index - 1].get("id"))] if index <= len(prompts) and prompts[index - 1].get("id") else [],
                "used_knowledge_fact_ids": [str(fact["id"])] if fact.get("id") else [],
                "market_code": market_code,
                "city": city or str(fact.get("city") or "Australia"),
                "language": "en-AU",
                "review_status": FAQ_CANDIDATE_PENDING,
                "generation_model": model,
                "generation_prompt_version": GEO_FAQ_CANDIDATE_PROMPT_VERSION,
                "rationale": f"Grounds a GEO FAQ answer in approved {fact.get('fact_type', 'knowledge')} knowledge.",
            }
        )
    return candidates


def _build_prompt_candidates(
    *,
    project_id: str,
    target_brand: str,
    category: str,
    market_code: str,
    facts: tuple[dict[str, Any], ...],
    prompts: tuple[dict[str, Any], ...],
    generation_job_id: str,
    quantity: int,
    intent_type: str | None,
    city: str | None,
    competitor: str | None,
    model: str,
    model_output: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    existing_texts = {_normalize_prompt_text(str(prompt.get("text") or "")) for prompt in prompts}
    model_candidates = _model_items((model_output or {}).get("prompt_candidates"))
    candidate_templates = [
        "Is {brand} a good {category} option in {city}?",
        "Does {brand} offer reliable {fact_type} for Australian customers?",
        "What makes {brand} different from {competitor}?",
        "Should I choose {brand} for {category} in {city}?",
        "What proof supports {brand} for {category}?",
    ]
    candidates = []
    fact_cycle = facts or ({"id": "", "fact_type": "brand_claim"},)
    for index in range(1, quantity + 1):
        fact = fact_cycle[(index - 1) % len(fact_cycle)]
        template = candidate_templates[(index - 1) % len(candidate_templates)]
        prompt_city = city or str(fact.get("city") or "Australia")
        prompt_text = template.format(
            brand=target_brand,
            category=category,
            city=prompt_city,
            competitor=competitor or "competitors",
            fact_type=str(fact.get("fact_type") or "service"),
        )
        if index <= len(model_candidates):
            prompt_text = str(model_candidates[index - 1].get("text") or prompt_text).strip() or prompt_text
        normalized_text = _normalize_prompt_text(prompt_text)
        duplicate_state = "duplicate" if normalized_text in existing_texts else "unique"
        candidate_id = stable_knowledge_id("prompt-candidate", project_id, generation_job_id, index, prompt_text)
        candidates.append(
            {
                "id": candidate_id,
                "project_id": project_id,
                "generation_job_id": generation_job_id,
                "text": prompt_text,
                "intent_type": intent_type or _intent_for_prompt(prompt_text),
                "market_code": market_code,
                "city": prompt_city,
                "language": "en-AU",
                "target_brand": target_brand,
                "competitors": [competitor] if competitor else [],
                "priority": index,
                "intent_weight": 1.0,
                "source_knowledge_fact_ids": [str(fact["id"])] if fact.get("id") else [],
                "duplicate_state": duplicate_state,
                "review_status": PROMPT_CANDIDATE_PENDING,
                "generation_model": model,
                "generation_prompt_version": GEO_PROMPT_CANDIDATE_PROMPT_VERSION,
                "rationale": f"Tests AI answer coverage for {target_brand} using approved {fact.get('fact_type', 'knowledge')} knowledge.",
            }
        )
    return candidates


def _intent_for_prompt(prompt_text: str) -> str:
    lowered = prompt_text.lower()
    if "different from" in lowered or " vs " in lowered:
        return "competitor_comparison"
    if "proof" in lowered or "support" in lowered:
        return "local_trust"
    if "offer" in lowered or "does " in lowered:
        return "service_coverage"
    return "category_recommendation"


def _normalize_prompt_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _model_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_model_object(item) for item in value if isinstance(item, dict) or isinstance(item, str)]


def _model_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"text": value, "object_value": value}
    return {}


def _clamp_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def schema_guard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
