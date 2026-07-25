"""Deterministic high-confidence prompt-injection markers for untrusted answers."""

from __future__ import annotations

import re
import unicodedata


_PROTECTED_XML_CLOSING = re.compile(
    r"</\s*(?:request[\s_-]*json|user[\s_-]*input|"
    r"system(?:[\s_-]*prompt)?|developer|"
    r"instructions?)\s*>"
)
_INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\b"
    r"[^.!?]{0,80}"
    r"\b(?:previous|prior|earlier|above|system|developer)\b"
    r"[^.!?]{0,48}"
    r"\b(?:instructions?|directives?|prompts?|messages?|rules?)\b"
)
_ROLE_OVERRIDE = re.compile(
    r"\b(?:you\s+are\s+now|act\s+as|assume\s+(?:the\s+)?role\s+of|"
    r"switch\s+(?:your\s+)?role\s+to|set\s+(?:your\s+)?role\s+(?:to|as)|"
    r"change\s+(?:your\s+)?role\s+to)\s+"
    r"(?:(?:an?|the)\s+)?(?:system|developer|administrator|admin)\b"
)
_SERIALIZED_ROLE_OVERRIDE = re.compile(
    r"[\"']?role[\"']?\s*[:=]\s*[\"']?(?:system|developer|administrator|admin)"
    r"\b[\"']?"
)
_ROLE_HEADER = re.compile(
    r"(?:^|\n)\s*(?:"
    r"#{1,6}\s*(?:system|developer)\b|"
    r"\[(?:system|developer)\]|<(?:system|developer)>|"
    r"(?:system|developer)\s+(?:message|instructions?)\s*:"
    r")\s*:?")
_NEGATED_OVERRIDE_PREFIX = re.compile(
    r"(?:\b(?:do\s+not|don't|should\s+not|must\s+not|cannot|can't)\b|\bnever\b)"
    r"(?:[\s,;:()-]+(?:ever|again|under|any|circumstances)){0,4}"
    r"[\s,;:()-]*$"
)
_CONFUSABLE_CONTROL_CHARS = str.maketrans(
    {
        "\u0430": "a",  # Cyrillic/Greek lookalikes in control phrases.
        "\u03b1": "a",
        "\u0435": "e",
        "\u03b5": "e",
        "\u0456": "i",
        "\u03b9": "i",
        "\u0458": "j",
        "\u03ba": "k",
        "\u04cf": "l",
        "\u043e": "o",
        "\u03bf": "o",
        "\u0440": "p",
        "\u03c1": "p",
        "\u0441": "c",
        "\u0455": "s",
        "\u03c4": "t",
        "\u0443": "y",
        "\u0445": "x",
        "\u03c7": "x",
    }
)
_NON_FORMAT_DEFAULT_IGNORABLES = frozenset({"\u034f"})


def has_high_confidence_prompt_injection(text: str) -> bool:
    """Return whether untrusted answer text contains an explicit control marker.

    NFKC and case folding make the decision stable across full-width characters,
    casing and whitespace. The patterns intentionally avoid generic mentions of
    prompts, roles, or ordinary HTML so normal consumer answers remain admissible.
    """

    folded = unicodedata.normalize("NFKC", text).casefold().replace("\r\n", "\n")
    folded = "".join(
        character
        for character in folded
        if unicodedata.category(character) != "Cf"
        and character not in _NON_FORMAT_DEFAULT_IGNORABLES
    ).translate(_CONFUSABLE_CONTROL_CHARS)
    folded = folded.replace("\r", "\n")
    collapsed = re.sub(r"\s+", " ", folded).strip()
    return any(
        pattern.search(collapsed) is not None
        for pattern in (
            _PROTECTED_XML_CLOSING,
            _ROLE_OVERRIDE,
            _SERIALIZED_ROLE_OVERRIDE,
        )
    ) or _ROLE_HEADER.search(folded) is not None or _has_instruction_override(
        collapsed
    )


def _has_instruction_override(text: str) -> bool:
    return any(
        _NEGATED_OVERRIDE_PREFIX.search(text[: match.start()]) is None
        for match in _INSTRUCTION_OVERRIDE.finditer(text)
    )


__all__ = ["has_high_confidence_prompt_injection"]
