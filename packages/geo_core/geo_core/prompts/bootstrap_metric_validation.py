"""Application semantics for the frozen typed Metric Judge batch contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NoReturn, TypeGuard

from geo_core.prompts.bootstrap_validation_errors import PromptOutputRuleViolation


_LABELS = {
    "recommendation": {"yes", "no"},
    "sentiment": {"positive", "neutral", "negative"},
    "fact": {"accurate", "conflict", "omission", "unknown"},
    "citation_entailment": {"entailed", "not_entailed", "unknown"},
    "corpus_absorption": {"absorbed", "not_absorbed", "unknown"},
}


def validate_metric_judge(
    input_value: Mapping[str, object], output: Mapping[str, object]
) -> None:
    metrics = _mapping_items(input_value.get("metrics"), "metric definitions")
    results = _mapping_items(output.get("results"), "metric results")
    by_id = {_text(item.get("metric_id"), "metric ID"): item for item in metrics}
    result_ids = [_text(item.get("metric_id"), "metric result ID") for item in results]
    if len(by_id) != len(metrics) or set(result_ids) != set(by_id) or len(set(result_ids)) != len(results):
        _fail("metric output set does not match the frozen metric definitions")

    answer = _text(input_value.get("answer_text"), "answer text")
    common_refs = {
        _text(item.get("ref"), "input evidence ref")
        for item in _mapping_items(input_value.get("evidence"), "input evidence")
    }
    sources = _locator_sources(input_value, common_refs=common_refs)
    for result in results:
        metric = by_id[_text(result.get("metric_id"), "metric result ID")]
        kind = _text(metric.get("kind"), "metric kind")
        if result.get("kind") != kind:
            _fail("metric result kind differs from its frozen definition")
        label = _text(result.get("label"), "metric label")
        if label not in _LABELS.get(kind, set()):
            _fail("metric label is invalid for the frozen metric kind")
        _validate_score(kind=kind, label=label, score=result.get("score"))

        metric_refs = set(_string_items(metric.get("evidence_refs"), "metric evidence refs"))
        result_refs = set(
            _string_items(result.get("evidence_refs"), "metric result evidence refs")
        )
        if not metric_refs.issubset(common_refs) or not result_refs.issubset(metric_refs):
            _fail("metric result references evidence outside its frozen definition")
        locators = _mapping_items(result.get("evidence_locators"), "metric locators")
        if not locators:
            _fail("every metric result requires typed evidence locators")
        for locator in locators:
            _validate_locator(
                locator,
                answer_length=len(answer),
                result_refs=result_refs,
                sources=sources,
            )


def _locator_sources(
    input_value: Mapping[str, object], *, common_refs: set[str]
) -> dict[tuple[str, str, str | None], Mapping[str, object]]:
    result: dict[tuple[str, str, str | None], Mapping[str, object]] = {}
    for source in _mapping_items(input_value.get("locator_sources"), "locator sources"):
        kind = _text(source.get("kind"), "locator source kind")
        reference = _text(source.get("reference_id"), "locator source reference")
        version, content_hash = source.get("version"), source.get("content_hash")
        if kind == "answer_span" and (
            not _is_text(version) or not _is_hash(content_hash)
        ):
            _fail("answer-span source requires exact version and content hash")
        if kind == "citation" and (version is not None or content_hash is not None):
            _fail("citation source can only freeze its reference identity")
        if kind == "fact" and (not _is_text(version) or content_hash is not None):
            _fail("fact source requires an approved version and no content hash")
        if kind not in {"answer_span", "citation", "fact"}:
            _fail("locator source kind is unsupported")
        key = _locator_identity(kind=kind, reference=reference, version=version)
        evidence_ref = _locator_evidence_ref(
            kind=kind,
            reference=reference,
            version=version,
        )
        if evidence_ref not in common_refs or key in result:
            _fail("locator sources must be unique frozen evidence references")
        result[key] = source
    return result


def _validate_score(*, kind: str, label: str, score: object) -> None:
    if kind in {"fact", "citation_entailment"}:
        if score is not None:
            _fail("fact and citation decisions must not emit a numeric score")
        return
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        _fail("scored metric decisions require a numeric score")
    numeric = float(score)
    if kind in {"recommendation", "corpus_absorption"} and not 0 <= numeric <= 1:
        _fail("recommendation and absorption scores must be between zero and one")
    if kind == "sentiment":
        if not -1 <= numeric <= 1:
            _fail("sentiment score must be between minus one and one")
        if (
            (label == "negative" and numeric >= 0)
            or (label == "neutral" and numeric != 0)
            or (label == "positive" and numeric <= 0)
        ):
            _fail("sentiment score direction differs from its categorical label")


def _validate_locator(
    locator: Mapping[str, object],
    *,
    answer_length: int,
    result_refs: set[str],
    sources: Mapping[tuple[str, str, str | None], Mapping[str, object]],
) -> None:
    kind = _text(locator.get("kind"), "metric locator kind")
    reference = _text(locator.get("reference_id"), "metric locator reference")
    version = locator.get("version")
    source = sources.get(
        _locator_identity(kind=kind, reference=reference, version=version)
    )
    if source is None or _locator_evidence_ref(
        kind=kind,
        reference=reference,
        version=source.get("version"),
    ) not in result_refs:
        _fail("metric locator is outside the frozen result evidence")
    content_hash = locator.get("content_hash")
    start, end = locator.get("start"), locator.get("end")
    quote_hash = locator.get("redacted_quote_hash")
    if kind == "answer_span":
        if version != source.get("version") or content_hash != source.get("content_hash"):
            _fail("answer-span locator changed frozen observation lineage")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or end > answer_length
        ):
            _fail("answer-span locator is outside the frozen answer")
        if quote_hash is not None and not _is_hash(quote_hash):
            _fail("answer-span redacted quote hash is invalid")
        return
    if kind == "citation":
        if any(value is not None for value in (version, content_hash, start, end, quote_hash)):
            _fail("citation locator can only contain its frozen reference")
        return
    if kind == "fact":
        if version != source.get("version") or any(
            value is not None for value in (content_hash, start, end, quote_hash)
        ):
            _fail("fact locator changed its approved version lineage")
        return
    _fail("metric locator kind is unsupported")


def _locator_identity(
    *, kind: str, reference: str, version: object
) -> tuple[str, str, str | None]:
    """Use the Fact's approved version in its locator identity.

    Answers and citations are respectively bound by their separate content lineage
    and immutable citation identity. A Fact is different: the visible evidence ref
    is ``fact-id@version`` while its locator carries the two fields separately.
    """

    return (kind, reference, str(version) if kind == "fact" and _is_text(version) else None)


def _locator_evidence_ref(*, kind: str, reference: str, version: object) -> str:
    if kind == "fact":
        if not _is_text(version):
            _fail("fact locator requires an approved version")
        return f"{reference}@{version}"
    return reference


def _mapping_items(value: object, label: str) -> list[Mapping[str, object]]:
    if not _is_json_array(value) or not all(isinstance(item, Mapping) for item in value):
        _fail(f"{label} must be an array of objects")
    return [item for item in value if isinstance(item, Mapping)]


def _string_items(value: object, label: str) -> list[str]:
    if not _is_json_array(value) or not all(_is_text(item) for item in value):
        _fail(f"{label} must be an array of strings")
    return [str(item) for item in value]


def _text(value: object, label: str) -> str:
    if not _is_text(value):
        _fail(f"{label} must be non-empty text")
    return str(value)


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_json_array(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _fail(message: str) -> NoReturn:
    raise PromptOutputRuleViolation("semantic_rule_failed", message)


__all__ = ["validate_metric_judge"]
