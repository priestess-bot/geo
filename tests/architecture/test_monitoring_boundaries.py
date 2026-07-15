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


def test_monitoring_domain_application_and_ports_are_framework_independent() -> None:
    root = ROOT / "packages" / "geo_core" / "geo_core" / "monitoring"
    forbidden = {"fastapi", "psycopg", "httpx", "boto3", "dramatiq"}
    for name in ("domain.py", "application.py", "ports.py"):
        assert _imports(root / name).isdisjoint(forbidden), name


def test_customer_geo_contract_does_not_import_internal_observation_contracts() -> None:
    content = (ROOT / "apps/api/geo_api/customer_geo_routes.py").read_text(encoding="utf-8")
    assert "MonitoringObservationResponse" not in content
    assert "ImportObservationRequest" not in content
    assert "geo_api.monitoring_routes" not in content
