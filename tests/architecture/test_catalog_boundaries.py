from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    values.update(
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return values


def test_catalog_domain_application_and_ports_do_not_import_infrastructure() -> None:
    root = ROOT / "packages" / "geo_core" / "geo_core" / "catalog"
    forbidden = {"fastapi", "psycopg", "httpx", "boto3", "dramatiq"}

    for name in ("domain.py", "application.py", "ports.py"):
        assert _imports(root / name).isdisjoint(forbidden), name


def test_catalog_api_does_not_import_legacy_or_executable_layers() -> None:
    root = ROOT / "apps" / "api" / "geo_api"
    forbidden = {"scripts", "workers", "geo_api.main"}

    for name in ("catalog_contracts.py", "catalog_routes.py", "catalog_runtime.py"):
        imports = _imports(root / name)
        assert not any(
            item == value or item.startswith(f"{value}.")
            for item in imports
            for value in forbidden
        ), name
