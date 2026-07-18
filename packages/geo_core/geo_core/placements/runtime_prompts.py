"""Model-facing runtime prompts loaded from the operator-managed prompt directory."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from geo_core.placements.simulation import PromptSimulationAuthenticityMode
from geo_core.prompts.filesystem import load_prompt_text, render_prompt_file


_AUTHENTICITY_FILES = {
    PromptSimulationAuthenticityMode.BRAND_AUTHORED: ("runtime/authenticity/brand-authored.md"),
    PromptSimulationAuthenticityMode.FAKE_PERSONA: ("runtime/authenticity/fake-persona.md"),
    PromptSimulationAuthenticityMode.SYNTHETIC_TESTIMONIAL: (
        "runtime/authenticity/synthetic-testimonial.md"
    ),
}


def generation_system_prompt(output_schema: str, *, prompt_root: Path | str | None = None) -> str:
    return render_prompt_file(
        "runtime/generation-system.md",
        {"output_schema": output_schema},
        prompt_root=prompt_root,
    )


def simulation_system_prompt(
    *,
    authenticity_mode: PromptSimulationAuthenticityMode,
    internal_evidence_ids: Iterable[object],
    public_citation_ids: Iterable[object],
    output_schema: str,
    prompt_root: Path | str | None = None,
) -> str:
    return render_prompt_file(
        "runtime/simulation-system.md",
        {
            "authenticity_instruction": authenticity_instruction(
                authenticity_mode, prompt_root=prompt_root
            ),
            "internal_evidence_ids": _uuid_allowlist(internal_evidence_ids),
            "public_citation_ids": _uuid_allowlist(public_citation_ids),
            "output_schema": output_schema,
        },
        prompt_root=prompt_root,
    )


def authenticity_instruction(
    mode: PromptSimulationAuthenticityMode,
    *,
    prompt_root: Path | str | None = None,
) -> str:
    path = _AUTHENTICITY_FILES[mode]
    if mode is PromptSimulationAuthenticityMode.BRAND_AUTHORED:
        return load_prompt_text(path, prompt_root=prompt_root)
    return render_prompt_file(
        path,
        {
            "synthetic_experience_boundary": load_prompt_text(
                "runtime/authenticity/synthetic-experience-boundary.md",
                prompt_root=prompt_root,
            )
        },
        prompt_root=prompt_root,
    )


def _uuid_allowlist(values: Iterable[object]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"
