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
    assert internal["environment"]["DATABASE_URL_FILE"] == "/run/secrets/database_url"
    assert customer["environment"]["DATABASE_URL_FILE"] == "/run/secrets/database_url"
    assert "geo_api.internal_app:app" in internal["command"]
    assert "geo_api.customer_app:app" in customer["command"]
    assert internal["environment"]["GEO_DEV_TOOLS_ENABLED"] == "0"


def test_production_compose_contains_no_source_mounts_or_weak_default_credentials() -> None:
    raw = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "../apps" not in raw
    assert "../packages" not in raw
    assert "minio123" not in raw
    assert "geo-local" not in raw
    assert ":-postgres" not in raw
    assert "GEO_DEEPSEEK_API_KEY_FILE" in raw
    assert "digest-pinned" in raw


def test_backup_and_restore_smoke_scripts_are_present() -> None:
    backup = ROOT / "scripts" / "backup_geo_data.sh"
    restore = ROOT / "scripts" / "restore_geo_backup_smoke.sh"

    assert backup.stat().st_mode & 0o111
    assert restore.stat().st_mode & 0o111
    assert "pg_dump" in backup.read_text(encoding="utf-8")
    assert "restore-smoke-postgres" in restore.read_text(encoding="utf-8")
