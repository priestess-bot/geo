from __future__ import annotations

import json

from scripts.geo_remediation_clause_map import ACCEPTANCE_EVIDENCE
from scripts.geo_remediation_registry import TEST_EVIDENCE
from scripts.validate_geo_remediation_traceability import (
    PLAN,
    ROOT,
    collect_registered_targets,
    missing_evidence,
    validate_registry_shape,
    validate_target_definitions,
)


def test_all_acceptance_clauses_have_registered_executable_evidence() -> None:
    validate_registry_shape(PLAN.read_text(encoding="utf-8"))
    assert len(ACCEPTANCE_EVIDENCE) == 70
    assert not missing_evidence(), "unfinished stable evidence IDs must keep F025 red"


def test_registered_pytest_nodes_playwright_titles_and_commands_are_real() -> None:
    validate_target_definitions(ROOT)
    collect_registered_targets(ROOT)


def test_high_risk_behavior_is_not_backed_only_by_source_contracts() -> None:
    validate_registry_shape(PLAN.read_text(encoding="utf-8"))


def test_ordinary_gate_is_chromium_desktop_without_unrelated_quality_thresholds() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    ordinary_ci = makefile.split("\nci:", maxsplit=1)[1].split("\n\n", maxsplit=1)[0]
    browser_command = package["scripts"]["test:browser:chromium"]
    browser_gate = browser_command
    if browser_command.startswith("node "):
        browser_gate += (ROOT / browser_command.removeprefix("node ")).read_text(
            encoding="utf-8"
        )
    forbidden = ("coverage", "firefox", "webkit", "mobile", "axe", "screen-reader")

    assert "--project=chromium-desktop" in browser_gate
    assert "--project=customer-desktop" in browser_gate
    assert all(word not in (ordinary_ci + browser_gate).lower() for word in forbidden)
    registered_projects = {
        target.project
        for targets in TEST_EVIDENCE.values()
        for target in targets
        if target.kind == "playwright"
    }
    assert registered_projects <= {"chromium-desktop", "customer-desktop"}
