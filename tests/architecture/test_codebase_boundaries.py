from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEBT_PATH = ROOT / "docs" / "engineering" / "architecture-debt.json"
SOURCE_ROOTS = (ROOT / "apps", ROOT / "packages")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx"}


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_product_modules_stay_within_size_budget() -> None:
    debt: dict[str, int] = json.loads(DEBT_PATH.read_text(encoding="utf-8"))
    observed: dict[str, int] = {}
    for root in SOURCE_ROOTS + (ROOT / "tests",):
        for path in root.rglob("*"):
            if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
                continue
            if any(part in {"node_modules", ".next", "__pycache__"} for part in path.parts):
                continue
            relative = path.relative_to(ROOT).as_posix()
            limit = 800 if relative.startswith("tests/") else 600
            count = line_count(path)
            if count > limit:
                observed[relative] = count

    assert set(observed) <= set(debt), f"new oversized files: {sorted(set(observed) - set(debt))}"
    growth = {
        path: {"recorded": debt[path], "current": count}
        for path, count in observed.items()
        if count > debt[path]
    }
    assert growth == {}, f"architecture debt grew: {growth}"


def test_retired_architecture_cannot_return() -> None:
    retired_paths = (
        ROOT / "apps" / "api" / "geo_api" / "main.py",
        ROOT / "apps" / "web" / "package.json",
        ROOT / "workers" / "task_queue" / "tasks.py",
        ROOT / "infra" / "db" / "migrations",
        ROOT / "infra" / "db" / "schema-v2",
        ROOT / "packages" / "geo_core" / "geo_core" / "repository.py",
        ROOT / "packages" / "geo_core" / "geo_core" / "runtime.py",
        ROOT / "packages" / "geo_core" / "geo_core" / "models.py",
    )
    assert not any(path.exists() for path in retired_paths)


def test_new_api_foundation_does_not_import_legacy_or_executable_layers() -> None:
    foundation_files = (
        "app_factory.py",
        "contracts.py",
        "customer_app.py",
        "foundation_services.py",
        "internal_app.py",
        "problems.py",
        "stable_routes.py",
    )
    api_root = ROOT / "apps" / "api" / "geo_api"
    forbidden = {"geo_api.main", "scripts", "workers"}

    for name in foundation_files:
        tree = ast.parse((api_root / name).read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imports.update(
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        )
        offenders = {item for item in imports if any(item == value or item.startswith(f"{value}.") for value in forbidden)}
        assert offenders == set(), f"{name} imports forbidden layers: {sorted(offenders)}"


def test_new_domain_contracts_do_not_depend_on_frameworks_or_infrastructure() -> None:
    domain_roots = (
        ROOT / "packages" / "geo_core" / "geo_core" / "jobs",
        ROOT / "packages" / "geo_core" / "geo_core" / "prompts",
    )
    forbidden = {"fastapi", "psycopg", "httpx", "boto3", "dramatiq"}

    for root in domain_roots:
        for path in root.glob("*.py"):
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
            assert imports.isdisjoint(forbidden), f"{path.relative_to(ROOT)} imports infrastructure"


def test_active_product_identifiers_use_geo_name() -> None:
    roots = (ROOT / "apps", ROOT / "packages", ROOT / "infra", ROOT / "contracts")
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or any(part in {"node_modules", ".next", "__pycache__"} for part in path.parts):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "GENO" in content or "Geno" in content or "geno" in content:
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
