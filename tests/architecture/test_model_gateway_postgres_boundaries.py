from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "packages" / "geo_core" / "geo_core" / "model_gateway"
POSTGRES_FILES = tuple(sorted(GATEWAY.glob("postgres*.py")))
CORE_FILES = tuple(
    path
    for path in GATEWAY.glob("*.py")
    if not path.name.startswith("postgres")
)


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imports.update(
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return imports


def test_model_gateway_core_remains_persistence_and_transport_independent() -> None:
    for path in CORE_FILES:
        assert "psycopg" not in _top_level_imports(path), path.name
        assert "geo_api" not in _top_level_imports(path), path.name


def test_model_gateway_postgres_is_an_explicit_infrastructure_boundary() -> None:
    imports = {
        item for path in POSTGRES_FILES for item in _top_level_imports(path)
    }
    assert "psycopg" in imports
    assert "geo_api" not in imports


def test_model_gateway_postgres_files_stay_below_size_budget() -> None:
    oversized = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in POSTGRES_FILES
        if len(path.read_text(encoding="utf-8").splitlines()) >= 600
    }
    assert oversized == {}
