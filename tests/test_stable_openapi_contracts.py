from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from scripts.export_stable_openapi import (
    CUSTOMER_ALLOWED_WRITES,
    CUSTOMER_FORBIDDEN_PREFIXES,
    HTTP_METHODS,
    MANIFEST_NAME,
    MUTATING_METHODS,
    SNAPSHOT_NAMES,
)


ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "scripts" / "export_stable_openapi.py"
CONTRACT_DIR = ROOT / "contracts" / "openapi" / "stable"


def _run(command: str, output_dir: Path, *, marker: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "DATABASE_URL": f"postgresql://contract:{marker}@database.invalid/geo",
        "GEO_GITHUB_WEBHOOK_SECRET": marker,
        "GEO_RUNTIME_JWT_SECRET": marker,
        "GEO_DEV_TOOLS_ENABLED": "1",
    }
    return subprocess.run(
        [sys.executable, str(EXPORTER), command, "--output-dir", str(output_dir)],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _operations(document: dict[str, object]) -> list[tuple[str, str, str]]:
    operations: list[tuple[str, str, str]] = []
    for path, path_item in document["paths"].items():
        for method in HTTP_METHODS & set(path_item):
            operations.append((method, path, path_item[method]["operationId"]))
    return operations


def test_checked_in_stable_snapshots_verify_without_legacy_application() -> None:
    result = _run("verify", CONTRACT_DIR, marker="VERIFY_MARKER")

    assert result.returncode == 0, result.stderr
    assert "Stable OpenAPI contracts verified: 2 surfaces" in result.stdout
    source = EXPORTER.read_text(encoding="utf-8")
    assert "geo_api.main" not in source
    assert "geo_api.internal_app" in source
    assert "geo_api.customer_app" in source


def test_operation_ids_are_unique_within_each_surface() -> None:
    for surface, filename in SNAPSHOT_NAMES.items():
        document = json.loads((CONTRACT_DIR / filename).read_text())
        operations = _operations(document)
        operation_ids = [operation_id for _, _, operation_id in operations]
        assert len(operation_ids) == len(set(operation_ids)), surface


def test_customer_snapshot_excludes_internal_surfaces_and_writes() -> None:
    document = json.loads((CONTRACT_DIR / SNAPSHOT_NAMES["customer"]).read_text())
    operations = _operations(document)

    assert not any(
        path.startswith(prefix)
        for _, path, _ in operations
        for prefix in CUSTOMER_FORBIDDEN_PREFIXES
    )
    customer_writes = {(method, path) for method, path, _ in operations if method in MUTATING_METHODS}
    assert customer_writes <= CUSTOMER_ALLOWED_WRITES


def test_exports_are_byte_reproducible_and_ignore_runtime_environment() -> None:
    with tempfile.TemporaryDirectory(prefix="stable-openapi-") as temporary:
        root = Path(temporary)
        first, second = root / "first", root / "second"
        first_result = _run("export", first, marker="FIRST_SECRET_MARKER")
        second_result = _run("export", second, marker="SECOND_SECRET_MARKER")

        assert first_result.returncode == 0, first_result.stderr
        assert second_result.returncode == 0, second_result.stderr
        for filename in (*SNAPSHOT_NAMES.values(), MANIFEST_NAME):
            assert (first / filename).read_bytes() == (second / filename).read_bytes()
        combined = b"".join((first / filename).read_bytes() for filename in first.iterdir())
        assert b"FIRST_SECRET_MARKER" not in combined
        assert b"SECOND_SECRET_MARKER" not in combined


def test_makefile_wires_stable_snapshot_export_and_verification() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "openapi-snapshots:" in makefile
    assert "openapi-contracts:" in makefile
    assert "scripts/export_stable_openapi.py export" in makefile
    assert "scripts/export_stable_openapi.py verify" in makefile
    assert "tests/test_stable_openapi_contracts.py" in makefile
    assert "make openapi-contracts" in workflow
