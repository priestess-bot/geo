from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra" / "docker-compose.yml"


def test_development_compose_uses_new_runtime_only() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]

    assert {
        "postgres",
        "migrate",
        "minio",
        "valkey",
        "internal-api",
        "customer-api",
        "task-worker",
    } <= set(services)
    assert {"qdrant", "litellm", "api", "dashboard-web", "web", "db-migrate"}.isdisjoint(services)
    assert "geo_api.internal_app:app" in services["internal-api"]["command"]
    assert "geo_api.customer_app:app" in services["customer-api"]["command"]


def test_development_api_logins_are_not_installer_superuser() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]

    assert "geo_app_dev" in services["internal-api"]["environment"]["DATABASE_URL"]
    assert "geo_app_dev" in services["customer-api"]["environment"]["DATABASE_URL"]
    assert "geo_worker_dev" in services["task-worker"]["environment"]["DATABASE_URL"]
    assert "provision_dev_database.py" in " ".join(services["migrate"]["command"])
    assert "uv run" not in " ".join(services["migrate"]["command"])
    assert services["migrate"]["environment"]["GEO_DEV_BOOTSTRAP_ENABLED"] == "1"


def test_development_worker_can_read_the_mode_0600_host_key_without_widening_it() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    worker = services["task-worker"]
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert worker["user"] == "${GEO_DEV_HOST_UID:-1000}:${GEO_DEV_HOST_GID:-1000}"
    assert worker["environment"]["GEO_DEEPSEEK_API_KEY_FILE"] == (
        "/run/secrets/deepseek_api_key"
    )
    assert any(
        volume.endswith(":/run/secrets/deepseek_api_key:ro")
        for volume in worker["volumes"]
    )
    assert 'GEO_DEV_HOST_UID="$$(id -u)"' in makefile
    assert 'GEO_DEV_HOST_GID="$$(id -g)"' in makefile


def test_development_admin_uses_the_deterministic_local_owner() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    environment = services["admin-web"]["environment"]

    assert environment["GEO_AUTH_MODE"] == "development"
    assert environment["GEO_ADMIN_ACTOR_ID"] == "30000000-0000-4000-8000-000000000003"
    assert environment["GEO_ADMIN_TENANT_ID"] == "10000000-0000-4000-8000-000000000001"
    assert environment["GEO_DEPLOYMENT_ENVIRONMENT"] == "development"
    assert services["customer-web"]["environment"]["GEO_DEPLOYMENT_ENVIRONMENT"] == (
        "development"
    )
    assert "GEO_ADMIN_WEB_HOST_PORT" in services["customer-web"]["environment"][
        "ADMIN_WEB_BASE_URL"
    ]
