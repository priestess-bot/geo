"""Strict filesystem loading for operator-editable prompt assets."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Mapping


PROMPT_ROOT_ENV = "GEO_PROMPT_ROOT"
_CATALOG_FILE = "catalog.json"
_MARKER = re.compile(r"\[\[\s*([a-z][a-z0-9_]*)\s*\]\]")


class PromptFileError(RuntimeError):
    """Raised when an operator-managed prompt file cannot be loaded safely."""


def resolve_prompt_root(explicit_root: Path | str | None = None) -> Path:
    """Resolve the prompt root without allowing a missing override to fail silently."""

    configured = explicit_root or os.getenv(PROMPT_ROOT_ENV, "").strip() or None
    if configured is not None:
        root = Path(configured).expanduser().resolve()
        _validate_root(root)
        return root

    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for candidate in candidates:
        root = candidate / "prompt"
        if (root / _CATALOG_FILE).is_file():
            return root.resolve()
    raise PromptFileError(
        f"prompt root not found; set {PROMPT_ROOT_ENV} to the directory containing "
        f"{_CATALOG_FILE}"
    )


def load_prompt_text(relative_path: str, *, prompt_root: Path | str | None = None) -> str:
    """Load one non-empty UTF-8 prompt file confined to the configured prompt root."""

    path = _resolve_asset_path(relative_path, prompt_root=prompt_root)
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PromptFileError(f"could not read prompt file {relative_path}: {exc}") from exc
    if not content:
        raise PromptFileError(f"prompt file is empty: {relative_path}")
    return content


def load_prompt_json(relative_path: str, *, prompt_root: Path | str | None = None) -> object:
    """Load one JSON prompt manifest or contract from the prompt root."""

    content = load_prompt_text(relative_path, prompt_root=prompt_root)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise PromptFileError(f"prompt JSON is invalid: {relative_path}") from exc


def render_prompt_text(
    template: str,
    variables: Mapping[str, object],
    *,
    source: str,
) -> str:
    """Render internal ``[[name]]`` markers while preserving bundle ``{{ name }}`` variables."""

    required = set(_MARKER.findall(template))
    missing = sorted(required - set(variables))
    if missing:
        raise PromptFileError(
            f"missing internal prompt variables in {source}: {', '.join(missing)}"
        )
    rendered = _MARKER.sub(lambda match: str(variables[match.group(1)]), template).strip()
    unresolved = sorted(set(_MARKER.findall(rendered)))
    if unresolved:
        raise PromptFileError(
            f"unresolved internal prompt variables in {source}: {', '.join(unresolved)}"
        )
    if not rendered:
        raise PromptFileError(f"rendered prompt is empty: {source}")
    return rendered


def render_prompt_file(
    relative_path: str,
    variables: Mapping[str, object],
    *,
    prompt_root: Path | str | None = None,
) -> str:
    """Load and render one prompt file."""

    return render_prompt_text(
        load_prompt_text(relative_path, prompt_root=prompt_root),
        variables,
        source=relative_path,
    )


def _resolve_asset_path(relative_path: str, *, prompt_root: Path | str | None) -> Path:
    root = resolve_prompt_root(prompt_root)
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise PromptFileError(f"prompt path must be relative: {relative_path}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PromptFileError(f"prompt path escapes configured root: {relative_path}") from exc
    if not resolved.is_file():
        raise PromptFileError(f"prompt file does not exist: {relative_path}")
    return resolved


def _validate_root(root: Path) -> None:
    if not root.is_dir() or not (root / _CATALOG_FILE).is_file():
        raise PromptFileError(f"configured prompt root must contain {_CATALOG_FILE}: {root}")
