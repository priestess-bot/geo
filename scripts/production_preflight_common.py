"""Side-effect-free and filesystem-neutral production preflight helpers."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit


def has_symlink_component(path: Path) -> bool:
    candidate = path.absolute()
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def strict_json_object(raw: bytes) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError from None
    if not isinstance(payload, dict):
        raise ValueError
    return payload


def valid_https_url(value: str, *, origin_only: bool = False) -> bool:
    if any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port is None and parsed.netloc.endswith(":")
        or port == 0
    ):
        return False
    if origin_only and (parsed.path not in {"", "/"} or parsed.query):
        return False
    return True


__all__ = ["has_symlink_component", "strict_json_object", "valid_https_url"]
