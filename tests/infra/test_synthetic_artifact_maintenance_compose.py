from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _services() -> dict[str, Any]:
    compose = yaml.safe_load(
        (ROOT / "infra" / "compose.prod.yml").read_text(encoding="utf-8")
    )
    assert isinstance(compose, dict)
    return compose["services"]


def test_synthetic_retention_worker_has_only_deletion_capabilities() -> None:
    services = _services()
    worker = services["synthetic-artifact-maintenance-worker"]

    assert set(worker["secrets"]) == {
        "worker_database_url",
        "synthetic_artifact_deleter_access_key",
        "synthetic_artifact_deleter_secret_key",
    }
    assert worker["networks"] == ["backend"]
    assert worker["command"] == [
        "dramatiq",
        "geo_worker.synthetic_artifact_maintenance_worker",
        "--queues",
        "synthetic-artifact-maintenance",
        "--processes",
        "1",
        "--threads",
        "1",
    ]
    assert worker["environment"]["GEO_SYNTHETIC_ARTIFACT_DELETER_RAW_OBJECT_STORE_BUCKET"] == (
        "geo-synthetic-style-raw"
    )
    assert worker["environment"][
        "GEO_SYNTHETIC_ARTIFACT_DELETER_DERIVED_OBJECT_STORE_BUCKET"
    ] == "geo-synthetic-style-derived"
    assert {
        "synthetic_artifact_keyring",
        "provider_artifact_keyring",
        "recommendation_artifact_keyring",
        "object_store_access_key",
        "object_store_secret_key",
        "workflow_c_artifact_deleter_access_key",
        "workflow_c_artifact_deleter_secret_key",
    }.isdisjoint(worker["secrets"])

    deleter_principal_holders = {
        name
        for name, service in services.items()
        if "synthetic_artifact_deleter_access_key" in service.get("secrets", ())
        or "synthetic_artifact_deleter_secret_key" in service.get("secrets", ())
    }
    assert deleter_principal_holders == {
        "minio-bootstrap",
        "synthetic-artifact-maintenance-worker",
    }
