"""Deterministic numeric grounding for Recommendation prose."""

from __future__ import annotations

from collections.abc import Iterable
import re


_NUMERIC_LITERAL = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|(?:AUD\s*|USD\s*|A\$\s*|\$\s*)"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:AUD|USD)"
    r"|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:\s?(?:%|per\s+cent|percentage\s+points?|basis\s+points?|bps|"
    r"days?|weeks?|months?|years?|hours?|minutes?|seconds?|thousand|million|billion))?"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def invented_recommendation_numeric_literals(
    *,
    evidence_texts: Iterable[str],
    decision_texts: Iterable[str],
) -> tuple[str, ...]:
    """Return normalized numeric claims absent from the selected evidence."""

    allowed = {
        _normalise_numeric_literal(match.group(0))
        for text in evidence_texts
        for match in _NUMERIC_LITERAL.finditer(text)
    }
    used = {
        _normalise_numeric_literal(match.group(0))
        for text in decision_texts
        for match in _NUMERIC_LITERAL.finditer(text)
    }
    return tuple(sorted(used - allowed))


def _normalise_numeric_literal(value: str) -> str:
    normalized = " ".join(value.casefold().split())
    normalized = re.sub(r"^(aud|usd)\s*", r"\1 ", normalized)
    return re.sub(r"^(a\$|\$)\s*", r"\1", normalized)


__all__ = ["invented_recommendation_numeric_literals"]
