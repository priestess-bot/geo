from __future__ import annotations

import csv
import io

import pytest

from geo_core.project_exports.csv_serialization import render_csv


@pytest.mark.parametrize("prefix", ("=", "+", "-", "@", "\t="))
def test_project_export_csv_neutralizes_spreadsheet_formulas(prefix: str) -> None:
    content = render_csv((("text", "string"),), ({"text": f"{prefix}DANGEROUS()"},))

    [row] = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))

    assert row["text"] == f"'{prefix}DANGEROUS()"
