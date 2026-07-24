from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages" / "geo_core" / "geo_core" / "statistical_methods"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    result.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return result


def test_statistical_methods_are_pure_and_capture_independent() -> None:
    forbidden = (
        "fastapi",
        "psycopg",
        "httpx",
        "dramatiq",
        "playwright",
        "geo_core.connectors",
        "geo_core.attribution",
        "geo_core.monitoring",
        "geo_core.model_gateway",
    )
    for path in PACKAGE.glob("*.py"):
        assert not any(value.startswith(forbidden) for value in _imports(path)), path.name


def test_statistical_modules_stay_below_reviewability_limit() -> None:
    oversized = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in PACKAGE.glob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) >= 600
    }
    assert oversized == {}


def test_bootstrap_uses_a_local_hash_seeded_rng() -> None:
    content = (PACKAGE / "bootstrap.py").read_text(encoding="utf-8")
    assert "random.Random(int(seed_hex, 16))" in content
    assert "random.seed(" not in content
