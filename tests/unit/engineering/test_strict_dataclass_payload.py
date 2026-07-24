from __future__ import annotations

from dataclasses import dataclass

import pytest

from geo_core.engineering.strict_dataclass_payload import reject_unknown_dataclass_fields


@dataclass(frozen=True)
class _Child:
    value: str


@dataclass(frozen=True)
class _Parent:
    optional_child: _Child | None
    children: tuple[_Child, ...]


@pytest.mark.parametrize(
    "payload, path",
    [
        ({"optional_child": {"value": "ok", "extra": True}, "children": []}, "optional_child"),
        (
            {"optional_child": None, "children": [{"value": "ok", "extra": True}]},
            "children[0]",
        ),
    ],
)
def test_unknown_fields_are_rejected_through_optional_and_tuple_nesting(
    payload: dict[str, object], path: str
) -> None:
    with pytest.raises(ValueError, match=path.replace("[", r"\[").replace("]", r"\]")):
        reject_unknown_dataclass_fields(payload, _Parent, path="parent")
