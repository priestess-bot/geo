from __future__ import annotations

import pytest

from geo_core.placements.domain import (
    PlacementConflict,
    allowed_opportunity_commands,
    transition_opportunity_status,
)


@pytest.mark.parametrize(
    ("status", "commands"),
    (
        ("identified", ("qualify", "block", "cancel")),
        ("qualified", ("block", "cancel")),
        ("briefing", ("block", "cancel")),
        ("in_progress", ("block", "cancel")),
        ("blocked", ("reopen", "cancel")),
        ("completed", ()),
        ("cancelled", ()),
    ),
)
def test_opportunity_commands_are_explicit_for_every_state(
    status: str, commands: tuple[str, ...]
) -> None:
    assert allowed_opportunity_commands(status) == commands


def test_illegal_opportunity_transition_is_a_domain_conflict() -> None:
    with pytest.raises(PlacementConflict, match="not allowed"):
        transition_opportunity_status(status="qualified", command="qualify")
    with pytest.raises(PlacementConflict, match="not allowed"):
        transition_opportunity_status(status="completed", command="reopen")
    with pytest.raises(PlacementConflict, match="unknown opportunity status"):
        transition_opportunity_status(status="mystery", command="block")
