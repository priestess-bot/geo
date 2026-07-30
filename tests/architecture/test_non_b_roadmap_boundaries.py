from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "packages" / "geo_core" / "geo_core"
NON_B_PACKAGES = (
    "alerts",
    "model_gateway",
    "prompts",
    "recommendations",
    "sampling",
    "secrets",
    "semantic_metrics",
    "statistical_methods",
    "synthetic_lab",
)
FORBIDDEN_PREFIXES = (
    "playwright",
    "geo_core.attribution",
    "geo_core.browser_capture",
    "geo_core.connectors",
    "geo_core.connector_core",
    "geo_core.production_connectors",
)


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


def test_non_b_roadmap_packages_do_not_cross_into_excluded_workstreams() -> None:
    offenders: dict[str, list[str]] = {}
    for package_name in NON_B_PACKAGES:
        for path in (CORE / package_name).glob("*.py"):
            forbidden = sorted(
                imported
                for imported in _imports(path)
                if imported.startswith(FORBIDDEN_PREFIXES)
            )
            if forbidden:
                offenders[path.relative_to(ROOT).as_posix()] = forbidden

    assert offenders == {}
