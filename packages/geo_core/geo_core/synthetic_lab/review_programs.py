"""Prompt programs frozen into each Synthetic Review execution."""

from geo_core.prompts.program_contracts import ProgramKind


REVIEW_PROGRAM_KINDS = (
    ProgramKind.GENERATION,
    ProgramKind.CLAIM_EXTRACTION,
    ProgramKind.CONFLICT_CHECK,
    ProgramKind.REVISION,
    ProgramKind.STYLE_JUDGE,
    ProgramKind.ARBITER,
)


__all__ = ["REVIEW_PROGRAM_KINDS"]
