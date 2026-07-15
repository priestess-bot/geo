"""Versioned starter prompts for the supported placement channels."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DefaultPromptDefinition:
    task_key: str
    skill_key: str
    system_template: str
    source: str


DEFAULT_SYSTEM_TEMPLATE = (
    "You create source-grounded GEO placement content for an authorised operator. "
    "Keep brand relationships explicit and follow the frozen destination policy."
)


def _source(channel_instruction: str) -> str:
    return f"""
Create a publication-ready GEO content package for this channel.

Channel brief:
{channel_instruction}

The following blocks are authoritative and were frozen by the workflow.
Brief:
{{{{ brief }}}}

Destination policy:
{{{{ destination_policy }}}}

Evidence:
{{{{ evidence }}}}

Use only facts present in Evidence. Keep the brand, product, competitor and market
subjects distinct. Preserve any required identity or commercial disclosure. Do not
invent rankings, prices, offers, tests, reviews, people or first-person experience.
Return only the JSON object required by the frozen output schema. Every factual claim
must appear in claims with its supporting evidence item IDs. Put all used evidence IDs
in internal_evidence_refs, and put an ID in public_citation_refs only when its frozen
metadata permits public disclosure.
""".strip()


DEFAULT_PROMPT_DEFINITIONS = (
    DefaultPromptDefinition(
        "owned_site",
        "system.placement.owned_site.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Write an official product page, comparison section or FAQ selected by the "
            "Brief. Lead with the consumer question, explain verifiable product fit, use "
            "clear headings, and end with an accurate official-site call to action."
        ),
    ),
    DefaultPromptDefinition(
        "productreview",
        "system.placement.productreview.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Write only an identified merchant profile update or an official response to "
            "the real review context in the Brief. Never write a consumer review or imply "
            "independent ownership or experience. Address the specific concern helpfully."
        ),
    ),
    DefaultPromptDefinition(
        "youtube",
        "system.placement.youtube.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Produce an official video script, title, description, chapter outline and "
            "source-aware call to action. The opening should answer the target consumer "
            "question, while spoken claims remain natural and individually traceable."
        ),
    ),
    DefaultPromptDefinition(
        "reddit",
        "system.placement.reddit.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Draft a useful response for the exact community and thread in the Brief. "
            "State the brand relationship at the start, answer before promoting, follow "
            "the frozen subreddit rules, and avoid pretending to be a customer."
        ),
    ),
    DefaultPromptDefinition(
        "amazon",
        "system.placement.amazon.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Create seller-authorized Amazon AU listing copy: title guidance, concise "
            "feature bullets, description or A+ sections, search terms and compliance "
            "notes. Include only product attributes and offer details in Evidence."
        ),
    ),
    DefaultPromptDefinition(
        "ozbargain",
        "system.placement.ozbargain.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Create a disclosed merchant deal submission for the exact verified offer in "
            "the Brief. State price, dates, eligibility, stock and delivery only when "
            "supported, make the merchant relationship clear, and omit invented savings."
        ),
    ),
    DefaultPromptDefinition(
        "tiktok",
        "system.placement.tiktok.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Create an official or authorized-creator short-video package with hook, shot "
            "list, voiceover, on-screen text, caption and disclosure. Demonstrations and "
            "experience language must stay within the supplied evidence or real description."
        ),
    ),
    DefaultPromptDefinition(
        "instagram",
        "system.placement.instagram.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Create an official or authorized-creator post or reel package with visual "
            "brief, caption, concise factual points, disclosure, alt text and a relevant "
            "call to action. Avoid unsupported lifestyle or experience claims."
        ),
    ),
    DefaultPromptDefinition(
        "quora",
        "system.placement.quora.v1",
        DEFAULT_SYSTEM_TEMPLATE,
        _source(
            "Write a direct expert answer to the exact question in the Brief. Disclose the "
            "brand relationship near the beginning, explain selection criteria before the "
            "product, cite public sources where allowed, and avoid an advertorial tone."
        ),
    ),
)


_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "content_json",
        "rendered_text",
        "claims",
        "internal_evidence_refs",
        "public_citation_refs",
    ],
    "properties": {
        "content_json": {
            "type": "object",
            "description": (
                "Channel-specific structured content including title, body, disclosure, "
                "CTA, links, metadata and submission notes when applicable."
            ),
        },
        "rendered_text": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "text",
                    "kind",
                    "support_status",
                    "evidence_item_ids",
                ],
                "properties": {
                    "text": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["factual", "comparative", "experience", "non_factual"],
                    },
                    "support_status": {
                        "type": "string",
                        "enum": ["supported", "unsupported", "not_applicable"],
                    },
                    "evidence_item_ids": {
                        "type": "array",
                        "items": {"type": "string", "format": "uuid"},
                    },
                },
            },
        },
        "internal_evidence_refs": {
            "type": "array",
            "items": {"type": "string", "format": "uuid"},
        },
        "public_citation_refs": {
            "type": "array",
            "items": {"type": "string", "format": "uuid"},
        },
    },
}


def default_output_schema() -> dict[str, Any]:
    """Return an isolated schema so callers cannot mutate the catalog constant."""
    return deepcopy(_OUTPUT_SCHEMA)
