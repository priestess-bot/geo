from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "packages" / "geo_core" / "geo_core" / "prompts"
FRAMEWORKS = {"fastapi", "psycopg", "httpx", "boto3", "dramatiq"}
DOMAIN_FILES = (
    "program_contracts.py",
    "program_models.py",
    "program_lifecycle.py",
    "program_rendering.py",
)
PRODUCT_FILES = (
    *DOMAIN_FILES,
    "program.py",
    "ports.py",
    "application.py",
    "application_access.py",
    "application_models.py",
    "application_release_operations.py",
    "application_support.py",
    "memory.py",
    "postgres.py",
    "postgres_api.py",
    "postgres_api_support.py",
    "postgres_connection.py",
    "postgres_read.py",
    "postgres_repository.py",
    "postgres_serialization.py",
    "postgres_uow.py",
    "postgres_workspace_api.py",
)


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


def test_prompt_program_domain_files_are_framework_independent() -> None:
    for name in DOMAIN_FILES:
        top_level = {value.split(".")[0] for value in _imports(PROMPTS / name)}
        assert top_level.isdisjoint(FRAMEWORKS), name


def test_prompt_postgres_adapter_is_an_explicit_infrastructure_boundary() -> None:
    adapter_files = (
        "postgres.py",
        "postgres_api.py",
        "postgres_connection.py",
        "postgres_repository.py",
        "postgres_uow.py",
    )
    imports = {
        value.split(".")[0]
        for name in adapter_files
        for value in _imports(PROMPTS / name)
    }
    assert "psycopg" in imports
    for name in DOMAIN_FILES:
        top_level = {value.split(".")[0] for value in _imports(PROMPTS / name)}
        assert "psycopg" not in top_level, name


def test_prompt_repository_uses_concrete_connection_helpers_before_mixins() -> None:
    from geo_core.prompts.postgres_connection import PromptPostgresConnectionMixin
    from geo_core.prompts.postgres_repository import PsycopgPromptProgramRepository

    assert (
        PsycopgPromptProgramRepository._optional
        is PromptPostgresConnectionMixin._optional
    )


def test_prompt_program_domain_dependencies_point_inward() -> None:
    allowed = {
        "program_contracts.py": set(),
        "program_models.py": {"geo_core.prompts.program_contracts"},
        "program_lifecycle.py": {
            "geo_core.prompts.program_contracts",
            "geo_core.prompts.program_models",
        },
        "program_rendering.py": {
            "geo_core.prompts.program_contracts",
            "geo_core.prompts.program_models",
        },
    }
    for name, permitted in allowed.items():
        prompt_imports = {
            value for value in _imports(PROMPTS / name) if value.startswith("geo_core.prompts")
        }
        assert prompt_imports <= permitted, name


def test_prompt_program_product_files_stay_below_size_budget() -> None:
    oversized = {
        name: len((PROMPTS / name).read_text(encoding="utf-8").splitlines())
        for name in PRODUCT_FILES
        if len((PROMPTS / name).read_text(encoding="utf-8").splitlines()) >= 600
    }
    assert oversized == {}
