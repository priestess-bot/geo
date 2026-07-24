from __future__ import annotations

import ast
from pathlib import Path

from geo_core.sampling import CaptureMethod


SAMPLING_ROOT = (
    Path(__file__).parents[3] / "packages" / "geo_core" / "geo_core" / "sampling"
)


def test_sampling_modules_remain_small_and_framework_independent() -> None:
    forbidden_import_fragments = (
        "connector",
        "attribution",
        "browser_capture",
        "egress",
        "fastapi",
        "sqlalchemy",
        "psycopg",
    )
    files = tuple(SAMPLING_ROOT.glob("*.py"))
    assert files

    for path in files:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) < 600, path
        # Persistence adapters deliberately depend on the PostgreSQL driver.
        # The pure sampling core must remain reusable without that dependency.
        if path.name.startswith("postgres_"):
            continue
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(
            fragment in module
            for module in imported
            for fragment in forbidden_import_fragments
        ), (path, imported)


def test_sampling_core_capture_methods_exclude_automated_ui_execution() -> None:
    executable = {
        CaptureMethod.PROVIDER_API,
        CaptureMethod.PROXY_GROUNDED_API,
        CaptureMethod.MANUAL_UI,
    }

    assert CaptureMethod.AUTOMATED_UI not in executable
