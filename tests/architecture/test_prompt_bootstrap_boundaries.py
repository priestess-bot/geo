from __future__ import annotations

import ast
from pathlib import Path

from geo_core.prompts import (
    FIRST_PHASE_PROGRAM_KINDS,
    ProgramKind,
    default_prompt_bootstrap_specs,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages/geo_core/geo_core/prompts"
BOOTSTRAP_FILES = tuple(sorted(PACKAGE.glob("bootstrap_*.py")))


def test_bootstrap_catalog_is_non_b_and_has_no_external_runtime_dependency() -> None:
    forbidden_import_prefixes = (
        "geo_core.attribution",
        "geo_core.connectors",
        "geo_core.browser_capture",
        "airbyte",
        "pyairbyte",
        "requests",
        "httpx",
    )
    for path in BOOTSTRAP_FILES:
        imports = _imports(path)
        assert not {
            name
            for name in imports
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in forbidden_import_prefixes
            )
        }, path


def test_bootstrap_catalog_cannot_transition_or_bind_a_release() -> None:
    forbidden_calls = {
        "approve",
        "bind_frozen_release",
        "freeze",
        "transition_release_state",
    }
    calls: set[str] = set()
    for path in BOOTSTRAP_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    assert forbidden_calls.isdisjoint(calls)


def test_bootstrap_reuses_prompt_release_and_fail_closed_schema_validators() -> None:
    contracts = (PACKAGE / "bootstrap_contracts.py").read_text(encoding="utf-8")
    validation = (PACKAGE / "bootstrap_validation.py").read_text(encoding="utf-8")

    assert "ProgramSchemaContract" in contracts
    assert "PromptProgramRelease.compile(" in contracts
    assert "validate_output_schema_definition" in contracts
    assert "validate_structured_output" in validation
    assert "PromptOutputRuleViolation" in validation


def test_bootstrap_catalog_excludes_reserved_reference_translation() -> None:
    specs = default_prompt_bootstrap_specs()

    assert tuple(spec.program_kind for spec in specs) == FIRST_PHASE_PROGRAM_KINDS
    assert ProgramKind.REFERENCE_TRANSLATION not in {
        spec.program_kind for spec in specs
    }


def test_bootstrap_modules_stay_split_below_the_product_budget() -> None:
    assert BOOTSTRAP_FILES
    for path in BOOTSTRAP_FILES:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 600, path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return imports
