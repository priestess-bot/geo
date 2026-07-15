from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra" / "docker-compose.yml"


def test_development_compose_uses_new_runtime_only() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]

    assert {"postgres", "migrate", "minio", "valkey", "internal-api", "customer-api", "task-worker"} <= set(services)
    assert {"qdrant", "litellm", "api", "dashboard-web", "web", "db-migrate"}.isdisjoint(services)
    assert "geo_api.internal_app:app" in services["internal-api"]["command"]
    assert "geo_api.customer_app:app" in services["customer-api"]["command"]


def test_development_api_logins_are_not_installer_superuser() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]

    assert "geo_app_dev" in services["internal-api"]["environment"]["DATABASE_URL"]
    assert "geo_app_dev" in services["customer-api"]["environment"]["DATABASE_URL"]
    assert "geo_worker_dev" in services["task-worker"]["environment"]["DATABASE_URL"]
    assert "provision_dev_database.py" in " ".join(services["migrate"]["command"])
