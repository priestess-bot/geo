from __future__ import annotations

import ast
from pathlib import Path

import scripts.production_preflight as entrypoint


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
MODULES = {
    "entrypoint": SCRIPTS / "production_preflight.py",
    "common": SCRIPTS / "production_preflight_common.py",
    "contracts": SCRIPTS / "production_preflight_contracts.py",
    "runtime": SCRIPTS / "production_preflight_runtime.py",
    "secrets": SCRIPTS / "production_preflight_secrets.py",
    "storage": SCRIPTS / "production_preflight_storage.py",
    "style": SCRIPTS / "production_preflight_style.py",
}


def test_preflight_entrypoint_remains_small_orchestration_and_public_api() -> None:
    assert _line_count(MODULES["entrypoint"]) <= 250
    assert callable(entrypoint.parse_env_file)
    assert callable(entrypoint.run_preflight)
    assert callable(entrypoint.validate_environment)
    assert entrypoint.APPLICATION_SECRET_UID == 10001
    assert entrypoint.APPLICATION_SECRET_GID == 10001
    for former_implementation in (
        "_master_key_material",
        "_validate_key_material",
        "_read_style_registry_file",
        "_validate_style_registry",
        "_validate_backup_root",
    ):
        assert not hasattr(entrypoint, former_implementation)


def test_preflight_security_modules_stay_below_reviewable_size_budget() -> None:
    oversized = {
        name: _line_count(path)
        for name, path in MODULES.items()
        if name != "entrypoint" and _line_count(path) > 400
    }
    assert oversized == {}


def test_preflight_leaf_validators_do_not_import_each_other_or_entrypoint() -> None:
    leaf_names = {"runtime", "secrets", "storage", "style"}
    module_names = {
        name: f"scripts.production_preflight_{name}" for name in leaf_names
    }
    forbidden = set(module_names.values()) | {"scripts.production_preflight"}
    offenders: dict[str, list[str]] = {}
    for name in leaf_names:
        imports = _imports(MODULES[name])
        invalid = sorted((imports & forbidden) - {module_names[name]})
        if invalid:
            offenders[name] = invalid
    assert offenders == {}


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


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())
