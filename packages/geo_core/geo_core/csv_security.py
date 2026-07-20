"""Spreadsheet-safe rendering for user-controlled CSV text cells."""

from __future__ import annotations

import re


_FORMULA_PREFIX = re.compile(r"^[\t\r\n ]*[=+\-@]")


def neutralize_spreadsheet_formula(value: str) -> str:
    """Force formula-looking text to remain literal when a spreadsheet opens the CSV."""
    return f"'{value}" if _FORMULA_PREFIX.match(value) else value
