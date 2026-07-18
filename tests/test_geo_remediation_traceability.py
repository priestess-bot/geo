from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/engineering/GEO-accepted-remediation-implementation-plan-2026-07-19.md"
EXPECTED_FINDINGS = {
    "001",
    "009",
    "011",
    "012",
    "013",
    "014",
    "015",
    "016",
    "018",
    "019",
    "021",
    "023",
    "025",
    "027",
}


def _traceability_rows(document: str) -> dict[str, str]:
    section = document.split("### 6.1 验收追踪矩阵", maxsplit=1)[1].split(
        "## 7. 测试目标与发布门禁", maxsplit=1
    )[0]
    rows: dict[str, str] = {}
    for finding, mapping in re.findall(r"^\| F-(\d{3}) \| (.+) \|$", section, re.MULTILINE):
        rows[finding] = mapping
    return rows


def test_every_accepted_finding_has_a_traceability_row() -> None:
    document = PLAN.read_text(encoding="utf-8")
    assert set(_traceability_rows(document)) == EXPECTED_FINDINGS


def test_every_acceptance_clause_is_mapped_to_a_test_id() -> None:
    document = PLAN.read_text(encoding="utf-8")
    defined = {
        (finding, int(number))
        for finding, number in re.findall(r"`F(\d{3})-AC(\d+)`", document)
    }
    assert len(defined) == 70

    mapped: set[tuple[str, int]] = set()
    for finding, mapping in _traceability_rows(document).items():
        for clause in mapping.split("；"):
            acceptance_numbers = {int(value) for value in re.findall(r"AC(\d+)", clause)}
            if not acceptance_numbers:
                continue
            assert "->" in clause
            assert re.search(r"`F\d{3}-[A-Z]+-\d+", clause), clause
            mapped.update((finding, number) for number in acceptance_numbers)

    assert mapped == defined
