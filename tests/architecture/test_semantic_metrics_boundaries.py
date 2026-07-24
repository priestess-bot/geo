from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages" / "geo_core" / "geo_core" / "semantic_metrics"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    values.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return values


def test_semantic_metric_core_is_independent_of_capture_and_framework_layers() -> None:
    forbidden_prefixes = (
        "fastapi",
        "psycopg",
        "httpx",
        "dramatiq",
        "playwright",
        "geo_core.monitoring",
        "geo_core.connectors",
        "geo_core.attribution",
        "geo_core.model_gateway",
    )
    for path in PACKAGE.glob("*.py"):
        assert not any(
            imported.startswith(forbidden_prefixes) for imported in _imports(path)
        ), path.name


def test_deterministic_rules_cannot_depend_on_model_judgements() -> None:
    imports = _imports(PACKAGE / "rules.py")
    assert "geo_core.semantic_metrics.judges" not in imports
    assert "geo_core.model_gateway" not in imports


def test_semantic_metric_modules_stay_below_the_reviewability_limit() -> None:
    oversized = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in PACKAGE.glob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) >= 600
    }
    assert oversized == {}
