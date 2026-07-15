from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "infra" / "compose.prod.yml"


def load_compose() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_production_compose_is_standalone_and_has_only_supported_runtime_services() -> None:
    compose = load_compose()
    services = compose["services"]

    assert {"internal-api", "customer-api", "admin-web", "customer-web"} <= set(services)
    assert {"qdrant", "litellm", "api", "dashboard-web", "web"}.isdisjoint(services)
    assert all("build" not in service for service in services.values())
    assert "ports" not in services["postgres"]
    assert "ports" not in services["minio"]
    assert "ports" not in services["valkey"]


def test_api_services_use_secrets_read_only_filesystems_and_separate_entrypoints() -> None:
    services = load_compose()["services"]
    internal = services["internal-api"]
    customer = services["customer-api"]

    assert internal["read_only"] is True
    assert customer["read_only"] is True
    assert internal["environment"]["GEO_DATABASE_URL_FILE"] == "/run/secrets/database_url"
    assert customer["environment"]["GEO_DATABASE_URL_FILE"] == "/run/secrets/database_url"
    assert "geo_api.internal_app:app" in internal["command"]
    assert "geo_api.customer_app:app" in customer["command"]
    assert internal["environment"]["GEO_DEV_TOOLS_ENABLED"] == "0"
    assert "deepseek_api_key" not in internal["secrets"]
    assert "deepseek_api_key" not in customer["secrets"]


def test_durable_worker_and_outbox_relay_use_the_worker_database_identity() -> None:
    services = load_compose()["services"]
    worker = services["task-worker"]
    relay = services["outbox-relay"]

    assert "geo_worker.tasks" in worker["command"]
    assert "geo_worker.relay" in relay["command"]
    assert worker["environment"]["GEO_DATABASE_URL_FILE"] == (
        "/run/secrets/worker_database_url"
    )
    assert relay["environment"]["GEO_DATABASE_URL_FILE"] == (
        "/run/secrets/worker_database_url"
    )
    assert "deepseek_api_key" in worker["secrets"]
    assert "deepseek_api_key" not in relay["secrets"]


def test_minio_bootstrap_receives_every_principal_it_requires() -> None:
    compose = load_compose()
    bootstrap = compose["services"]["minio-bootstrap"]
    required = {
        "object_store_access_key",
        "object_store_secret_key",
        "object_store_backup_access_key",
        "object_store_backup_secret_key",
        "object_store_restore_access_key",
        "object_store_restore_secret_key",
        "object_store_retention_access_key",
        "object_store_retention_secret_key",
    }

    assert required <= set(bootstrap["secrets"])
    assert required <= set(compose["secrets"])
    for name in required:
        assert bootstrap["environment"][name.upper() + "_FILE"] == f"/run/secrets/{name}"


def test_production_environment_example_covers_required_secret_files() -> None:
    example = (ROOT / "infra" / "production.env.example").read_text(encoding="utf-8")
    for name in (
        "GEO_WORKER_DATABASE_URL_FILE",
        "GEO_OBJECT_STORE_RESTORE_ACCESS_KEY_FILE",
        "GEO_OBJECT_STORE_RESTORE_SECRET_KEY_FILE",
        "GEO_OBJECT_STORE_RETENTION_ACCESS_KEY_FILE",
        "GEO_OBJECT_STORE_RETENTION_SECRET_KEY_FILE",
    ):
        assert f"{name}=" in example


def test_production_compose_contains_no_source_mounts_or_weak_default_credentials() -> None:
    raw = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "../apps" not in raw
    assert "../packages" not in raw
    assert "minio123" not in raw
    assert "geo-local" not in raw
    assert ":-postgres" not in raw
    assert "GEO_DEEPSEEK_API_KEY_FILE" in raw
    assert "digest-pinned" in raw


def test_production_web_portals_use_strict_deployment_url_policy() -> None:
    services = load_compose()["services"]

    assert services["admin-web"]["environment"]["GEO_DEPLOYMENT_ENVIRONMENT"] == (
        "production"
    )
    assert services["customer-web"]["environment"]["GEO_DEPLOYMENT_ENVIRONMENT"] == (
        "production"
    )


def test_backup_and_restore_smoke_scripts_are_present() -> None:
    backup = ROOT / "scripts" / "backup_geo_data.sh"
    restore = ROOT / "scripts" / "restore_geo_backup_smoke.sh"

    assert backup.stat().st_mode & 0o111
    assert restore.stat().st_mode & 0o111
    assert "pg_dump" in backup.read_text(encoding="utf-8")
    assert "restore-smoke-postgres" in restore.read_text(encoding="utf-8")


def test_initial_owner_provision_is_explicit_installer_only_profile() -> None:
    services = load_compose()["services"]
    provision = services["initial-owner-provision"]

    assert provision["profiles"] == ["provisioning"]
    assert provision["restart"] == "no"
    assert provision["read_only"] is True
    assert provision["environment"]["GEO_INSTALLER_DATABASE_URL_FILE"] == (
        "/run/secrets/installer_database_url"
    )
    assert provision["secrets"] == ["installer_database_url"]
    assert "scripts.provision_initial_owner" in provision["command"]
    assert "initial-owner-provision" not in services["internal-api"].get("depends_on", {})
