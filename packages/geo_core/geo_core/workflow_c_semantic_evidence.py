"""Citation and answer-block validation for semantic evidence."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from geo_core.semantic_metrics import CitationInput
from geo_core.semantic_metrics.rules import canonical_url
from geo_core.workflow_c_semantic_materialization_contracts import (
    WorkflowCSemanticMaterializationError,
)


def _citations(slot_id: str, value: object) -> tuple[CitationInput, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise WorkflowCSemanticMaterializationError("semantic citations must be an array")
    citations: list[CitationInput] = []
    for index, raw in enumerate(value, start=1):
        url_value: object
        title_value: object
        source_type_value: object
        ordinal_value: object
        if isinstance(raw, str):
            url_value = raw
            title_value = raw
            source_type_value = "web"
            ordinal_value = index
        else:
            item = _mapping(raw, "semantic citation")
            url_value = item.get("url")
            title_value = item.get("visible_title", item.get("title", url_value))
            source_type_value = item.get(
                "source_type", item.get("citation_type", item.get("type", "web"))
            )
            ordinal_value = item.get("ordinal", item.get("position", index))
        if (
            not isinstance(url_value, str)
            or not isinstance(title_value, str)
            or not isinstance(source_type_value, str)
            or not isinstance(ordinal_value, int)
            or isinstance(ordinal_value, bool)
        ):
            raise WorkflowCSemanticMaterializationError("semantic citation is malformed")
        canonical_url(url_value)
        citations.append(
            CitationInput(
                id=f"{slot_id}:citation:{index}",
                ordinal=ordinal_value,
                url=url_value,
                visible_title=title_value or (urlsplit(url_value).hostname or url_value),
                source_type=source_type_value,
            )
        )
    return tuple(citations)


def _surface_answer(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    blocks: list[str] = []
    for raw in value:
        item = _mapping(raw, "manual surface answer block")
        if set(item) != {"text", "locator"}:
            raise WorkflowCSemanticMaterializationError(
                "manual surface answer block is invalid"
            )
        text = item.get("text")
        locator = item.get("locator")
        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(locator, str)
            or not locator.strip()
        ):
            raise WorkflowCSemanticMaterializationError(
                "manual surface answer block is invalid"
            )
        blocks.append(text.strip())
    return "\n".join(blocks)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise WorkflowCSemanticMaterializationError(f"{label} must be an object")
    return value
