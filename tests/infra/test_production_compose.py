from geo_core.engineering.performance_profile import non_b_performance_profile_v1
from tests.infra.production_compose_support import (
    COMPOSE_PATH,
    ROOT,
    load_compose,
    load_runtime_services,
    load_style_compose,
)


def test_production_runtime_limits_match_frozen_performance_profile() -> None:
    services = load_runtime_services()
    profile = non_b_performance_profile_v1()

    assert services["internal-api"]["environment"]["GEO_DB_POOL_MAX_SIZE"] == str(
        profile.process_topology.api_database_pool_max_size
    )
    assert services["customer-api"]["environment"]["GEO_DB_POOL_MAX_SIZE"] == str(
        profile.process_topology.api_database_pool_max_size
    )
    for service_name, expected in profile.process_topology.resource_limits.items():
        actual = services[service_name]["deploy"]["resources"]["limits"]
        assert str(actual["cpus"]) == expected["cpus"]
        assert actual["memory"] == expected["memory"]


def test_production_compose_is_standalone_and_has_only_supported_runtime_services() -> None:
    services = load_runtime_services()

    assert {
        "internal-api",
        "customer-api",
        "admin-web",
        "customer-web",
        "style-browser-worker",
    } <= set(services)
    assert {"qdrant", "litellm", "api", "dashboard-web", "web"}.isdisjoint(services)
    assert all("build" not in service for service in services.values())
    assert "ports" not in services["postgres"]
    assert "ports" not in services["minio"]
    assert "ports" not in services["valkey"]
    assert "ports" not in services["style-browser-worker"]


def test_every_production_service_has_process_resource_and_log_limits() -> None:
    services = load_runtime_services()

    for name, service in services.items():
        assert 1 <= service["pids_limit"] <= 512, name
        assert service["security_opt"] == ["no-new-privileges:true"], name
        assert service["cap_drop"] == ["ALL"], name
        assert service["logging"] == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        }, name
        limits = service["deploy"]["resources"]["limits"]
        assert float(limits["cpus"]) > 0, name
        assert str(limits["memory"]).endswith(("M", "G")), name
        assert limits["pids"] == service["pids_limit"], name


def test_first_party_runtime_images_drop_root_privileges() -> None:
    for relative in (
        "apps/api/Dockerfile",
        "apps/api/Dockerfile.style-browser",
        "apps/admin-web/Dockerfile",
        "apps/customer-web/Dockerfile",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "USER 10001:10001" in source, relative


def test_production_networks_enforce_the_egress_boundary() -> None:
    compose = load_compose()
    services = compose["services"]

    assert compose["networks"]["backend"]["internal"] is True
    assert compose["networks"]["egress"] is None
    assert set(services["internal-api"]["networks"]) == {"backend", "egress"}
    assert set(services["task-worker"]["networks"]) == {"backend", "egress"}
    style = load_style_compose()["services"]["style-browser-worker"]
    assert set(style["networks"]) == {"backend", "egress", "style-browser-control"}
    browser_runtime = load_style_compose()["services"]["style-browser-runtime"]
    assert set(browser_runtime["networks"]) == {"style-browser-control", "egress"}
    assert "backend" not in browser_runtime["networks"]

    for name in (
        "postgres",
        "migrate",
        "minio",
        "minio-bootstrap",
        "valkey",
        "customer-api",
        "workflow-c-maintenance-scheduler",
        "recommendation-artifact-maintenance-scheduler",
        "recommendation-artifact-maintenance-worker",
        "synthetic-artifact-maintenance-worker",
        "workflow-c-maintenance-worker",
        "outbox-relay",
        "initial-owner-provision",
        "otel-collector",
        "backup-object-store",
        "restore-smoke-postgres",
        "restore-smoke-application-key-probe",
    ):
        assert "egress" not in services[name]["networks"]

    for name, service in services.items():
        if name not in {"admin-web", "customer-web"}:
            assert "ports" not in service


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

    assert set(internal["secrets"]) == {
        "database_url",
        "object_store_access_key",
        "object_store_secret_key",
        "auth_token_secret",
        "secret_store_master_keyring",
        "secret_store_request_hash_key",
        "workflow_c_artifact_keyring",
        "workflow_c_artifact_object_store_access_key",
        "workflow_c_artifact_object_store_secret_key",
    }
    assert set(customer["secrets"]) == {"database_url", "auth_token_secret"}
    for key in (
        "OBJECT_STORE_ENDPOINT",
        "OBJECT_STORE_ACCESS_KEY_FILE",
        "OBJECT_STORE_SECRET_KEY_FILE",
        "GEO_TASK_QUEUE_BROKER_URL",
        "GEO_TASK_QUEUE_ENABLED",
        "GEO_OIDC_DISCOVERY_URL",
        "GEO_JWT_ISSUER",
        "GEO_JWT_AUDIENCE",
    ):
        assert key not in customer["environment"]
    assert set(customer["depends_on"]) == {"migrate"}
    assert set(internal["depends_on"]) == {"migrate", "minio-bootstrap", "valkey"}


def test_runtime_healthchecks_use_real_readiness_and_heartbeats() -> None:
    services = load_runtime_services()

    for name in ("internal-api", "customer-api"):
        command = services[name]["healthcheck"]["test"]
        assert "/ready" in " ".join(command)
        assert "/health" not in " ".join(command)

    expected_service_types = {
        "task-worker": "task_worker",
        "outbox-relay": "outbox_relay",
        "style-browser-worker": "style_browser_worker",
        "workflow-c-maintenance-scheduler": "workflow_c_maintenance_scheduler",
        "workflow-c-maintenance-worker": "workflow_c_maintenance_worker",
        "recommendation-artifact-maintenance-scheduler": (
            "recommendation_artifact_maintenance_scheduler"
        ),
        "recommendation-artifact-maintenance-worker": (
            "recommendation_artifact_maintenance_worker"
        ),
        "synthetic-artifact-maintenance-worker": (
            "synthetic_artifact_maintenance_worker"
        ),
    }
    for name, service_type in expected_service_types.items():
        command = services[name]["healthcheck"]["test"]
        assert command == [
            "CMD",
            "python",
            "-m",
            "geo_worker.runtime_health",
            "heartbeat",
            "--service-type",
            service_type,
        ]

    for name in (
        "postgres",
        "minio",
        "valkey",
        "internal-api",
        "customer-api",
        "task-worker",
        "outbox-relay",
        "style-browser-worker",
        "workflow-c-maintenance-scheduler",
        "workflow-c-maintenance-worker",
        "synthetic-artifact-maintenance-worker",
        "admin-web",
        "customer-web",
    ):
        assert "healthcheck" in services[name]


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
    assert {
        "secret_store_master_keyring",
        "secret_store_request_hash_key",
    } <= set(worker["secrets"])
    assert worker["environment"]["GEO_SECRET_STORE_MASTER_KEYRING_FILE"] == (
        "/run/secrets/secret_store_master_keyring"
    )
    assert worker["environment"]["GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"] == (
        "/run/secrets/secret_store_request_hash_key"
    )


def test_alert_delivery_uses_a_restricted_smtp_sidecar_and_secret_backed_webhook() -> None:
    compose = load_compose()
    services = compose["services"]
    worker = services["task-worker"]
    smtp = services["alert-smtp-relay"]

    assert smtp["command"] == ["python", "-m", "geo_alert_smtp_relay"]
    assert set(smtp["networks"]) == {"backend", "egress"}
    assert "ports" not in smtp
    assert smtp["read_only"] is True
    assert set(smtp["secrets"]) == {"alert_smtp_username", "alert_smtp_password"}
    assert "GEO_ALERT_SMTP_USERNAME" not in smtp["environment"]
    assert "GEO_ALERT_SMTP_PASSWORD" not in smtp["environment"]
    assert smtp["environment"]["GEO_ALERT_SMTP_USERNAME_FILE"] == (
        "/run/secrets/alert_smtp_username"
    )
    assert smtp["environment"]["GEO_ALERT_SMTP_PASSWORD_FILE"] == (
        "/run/secrets/alert_smtp_password"
    )
    assert worker["environment"]["GEO_ALERT_SMTP_HOST"] == "alert-smtp-relay"
    assert worker["depends_on"]["alert-smtp-relay"]["condition"] == "service_healthy"
    assert "alert_webhook_signing_secret" in worker["secrets"]
    assert worker["environment"]["GEO_ALERT_WEBHOOK_SIGNING_SECRET_FILE"] == (
        "/run/secrets/alert_webhook_signing_secret"
    )
    assert {
        "alert_smtp_username",
        "alert_smtp_password",
        "alert_webhook_signing_secret",
    } <= set(compose["secrets"])

    example = (ROOT / "infra" / "production.env.example").read_text(encoding="utf-8")
    for name in (
        "GEO_ALERT_SMTP_UPSTREAM_ALLOWED_HOSTS",
        "GEO_ALERT_SMTP_USERNAME_FILE",
        "GEO_ALERT_SMTP_PASSWORD_FILE",
        "GEO_ALERT_WEBHOOK_ALLOWED_HOSTS",
        "GEO_ALERT_WEBHOOK_SIGNING_SECRET_FILE",
    ):
        assert name in example


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
        "workflow_c_artifact_object_store_access_key",
        "workflow_c_artifact_object_store_secret_key",
        "workflow_c_artifact_reader_access_key",
        "workflow_c_artifact_reader_secret_key",
        "workflow_c_artifact_deleter_access_key",
        "workflow_c_artifact_deleter_secret_key",
        "synthetic_style_artifact_writer_access_key",
        "synthetic_style_artifact_writer_secret_key",
        "synthetic_artifact_deleter_access_key",
        "synthetic_artifact_deleter_secret_key",
    }

    assert required <= set(bootstrap["secrets"])
    assert required <= set(compose["secrets"])
    workflow_c_names = {
        "workflow_c_artifact_object_store_access_key",
        "workflow_c_artifact_object_store_secret_key",
        "workflow_c_artifact_reader_access_key",
        "workflow_c_artifact_reader_secret_key",
        "workflow_c_artifact_deleter_access_key",
        "workflow_c_artifact_deleter_secret_key",
        "synthetic_style_artifact_writer_access_key",
        "synthetic_style_artifact_writer_secret_key",
        "synthetic_artifact_deleter_access_key",
        "synthetic_artifact_deleter_secret_key",
    }
    for name in required:
        prefix = "GEO_" if name in workflow_c_names else ""
        assert bootstrap["environment"][prefix + name.upper() + "_FILE"] == (
            f"/run/secrets/{name}"
        )


def test_production_environment_example_covers_required_secret_files() -> None:
    example = (ROOT / "infra" / "production.env.example").read_text(encoding="utf-8")
    for name in (
        "GEO_WORKER_DATABASE_URL_FILE",
        "GEO_OBJECT_STORE_RESTORE_ACCESS_KEY_FILE",
        "GEO_OBJECT_STORE_RESTORE_SECRET_KEY_FILE",
        "GEO_OBJECT_STORE_RETENTION_ACCESS_KEY_FILE",
        "GEO_OBJECT_STORE_RETENTION_SECRET_KEY_FILE",
        "GEO_SECRET_STORE_MASTER_KEYRING_FILE",
        "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE",
        "GEO_BACKUP_KEYRING_FILE",
        "GEO_PROVIDER_ARTIFACT_KEYRING_FILE",
        "GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE",
        "GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_ACCESS_KEY_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_OBJECT_STORE_SECRET_KEY_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_READER_ACCESS_KEY_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_READER_SECRET_KEY_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_DELETER_ACCESS_KEY_FILE",
        "GEO_WORKFLOW_C_ARTIFACT_DELETER_SECRET_KEY_FILE",
        "GEO_STYLE_BROWSER_WORKER_DATABASE_URL_FILE",
        "GEO_SYNTHETIC_STYLE_ARTIFACT_WRITER_ACCESS_KEY_FILE",
        "GEO_SYNTHETIC_STYLE_ARTIFACT_WRITER_SECRET_KEY_FILE",
        "GEO_SYNTHETIC_ARTIFACT_DELETER_ACCESS_KEY_FILE",
        "GEO_SYNTHETIC_ARTIFACT_DELETER_SECRET_KEY_FILE",
        "GEO_RESTORE_TMPFS_ROOT",
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


def test_production_compose_does_not_claim_nonexistent_prometheus_metrics() -> None:
    compose = load_compose()

    assert "prometheus" not in compose["services"]
    assert "prometheus_data" not in compose["volumes"]
    assert not (ROOT / "infra" / "prometheus" / "prometheus.yml").exists()
    assert not (
        ROOT / "infra" / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
    ).exists()


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
    assert "set -Eeuo pipefail" in backup.read_text(encoding="utf-8")
    assert "backup_envelope.py" in backup.read_text(encoding="utf-8")
    assert "backup_manifest.py" in restore.read_text(encoding="utf-8")


def test_secret_store_and_backup_keys_have_least_privilege_mounts() -> None:
    compose = load_compose()
    services = compose["services"]
    internal = services["internal-api"]
    worker = services["task-worker"]
    customer = services["customer-api"]
    relay = services["outbox-relay"]

    secret_names = {"secret_store_master_keyring", "secret_store_request_hash_key"}
    assert secret_names <= set(internal["secrets"])
    assert secret_names <= set(worker["secrets"])
    assert secret_names.isdisjoint(customer["secrets"])
    assert secret_names.isdisjoint(relay["secrets"])
    assert "backup_keyring" not in compose["secrets"]

    backup = services["backup-object-store"]
    assert backup["read_only"] is True
    assert any(item.startswith("/plaintext-staging:") for item in backup["tmpfs"])
    assert "backup-object-store" not in services["internal-api"]["depends_on"]

    restore_probe = services["restore-smoke-application-key-probe"]
    assert restore_probe["profiles"] == ["restore-smoke"]
    assert set(restore_probe["secrets"]) == {
        "restore_smoke_password",
        "secret_store_master_keyring",
        "secret_store_request_hash_key",
        "provider_artifact_keyring",
        "synthetic_artifact_keyring",
        "recommendation_artifact_keyring",
        "workflow_c_artifact_keyring",
    }
    assert (
        restore_probe["environment"]["GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"]
        == "/run/secrets/secret_store_request_hash_key"
    )
    assert "geo_worker.backup_restore_probe" in restore_probe["command"]
    assert "--secret-store-request-hash-key" in restore_probe["command"]
    assert "--secret-store-service-identity-id" in restore_probe["command"]
    assert restore_probe["networks"] == ["backend"]


def test_artifact_keyrings_and_style_runtime_have_least_privilege_mounts() -> None:
    base = load_compose()
    style_compose = load_style_compose()
    services = base["services"]
    style = style_compose["services"]["style-browser-worker"]
    worker = services["task-worker"]

    assert worker["environment"]["GEO_PROVIDER_ARTIFACT_KEYRING_FILE"] == (
        "/run/secrets/provider_artifact_keyring"
    )
    assert "provider_artifact_keyring" in worker["secrets"]
    assert worker["environment"]["GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE"] == (
        "/run/secrets/recommendation_artifact_keyring"
    )
    assert "recommendation_artifact_keyring" in worker["secrets"]
    # The generic task worker executes encrypted Synthetic child-model tasks.
    # It may decrypt that dedicated task artifact, but still has none of the
    # Style Collection browser/login credentials or its writer principal.
    assert worker["environment"]["GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"] == (
        "/run/secrets/synthetic_artifact_keyring"
    )
    assert "synthetic_artifact_keyring" in worker["secrets"]

    assert style["user"] == "10001:10001"
    assert style["read_only"] is True
    assert style["pids_limit"] == 512
    assert style["deploy"]["resources"]["limits"]["pids"] == 512
    assert style["environment"]["GEO_STYLE_ADAPTER_REGISTRY_FILE"] == (
        "/etc/geo/style-adapter-registry.json"
    )
    assert style["environment"]["GEO_STYLE_ADAPTER_REGISTRY_SHA256"] == (
        "${GEO_STYLE_ADAPTER_REGISTRY_SHA256:?set the reviewed Style adapter registry digest}"
    )
    assert style["environment"]["GEO_STYLE_ROBOTS_TIMEOUT_SECONDS"] == (
        "${GEO_STYLE_ROBOTS_TIMEOUT_SECONDS:-10}"
    )
    assert style["volumes"] == [
        "${GEO_STYLE_ADAPTER_REGISTRY_FILE:?set the host Style adapter registry file}:"
        "/etc/geo/style-adapter-registry.json:ro"
    ]
    assert style["environment"]["GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"] == (
        "/run/secrets/synthetic_artifact_keyring"
    )
    assert style["environment"]["GEO_SECRET_STORE_MASTER_KEYRING_FILE"] == (
        "/run/secrets/secret_store_master_keyring"
    )
    assert style["environment"]["GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"] == (
        "/run/secrets/secret_store_request_hash_key"
    )
    assert style["environment"]["GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_BUCKET"] == (
        "geo-synthetic-style-raw"
    )
    assert style["environment"]["GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_BUCKET"] == (
        "geo-synthetic-style-derived"
    )
    assert "OBJECT_STORE_BUCKET" not in style["environment"]
    assert set(style["secrets"]) == {
        "style_browser_worker_database_url",
        "synthetic_style_artifact_writer_access_key",
        "synthetic_style_artifact_writer_secret_key",
        "secret_store_master_keyring",
        "secret_store_request_hash_key",
        "synthetic_artifact_keyring",
    }
    assert {
        "provider_artifact_keyring",
        "deepseek_api_key",
        "auth_token_secret",
    }.isdisjoint(style["secrets"])

    provider_readers = {
        name
        for name, service in load_runtime_services().items()
        if "provider_artifact_keyring" in service.get("secrets", ())
    }
    synthetic_readers = {
        name
        for name, service in load_runtime_services().items()
        if "synthetic_artifact_keyring" in service.get("secrets", ())
    }
    recommendation_readers = {
        name
        for name, service in load_runtime_services().items()
        if "recommendation_artifact_keyring" in service.get("secrets", ())
    }
    workflow_c_readers = {
        name
        for name, service in load_runtime_services().items()
        if "workflow_c_artifact_keyring" in service.get("secrets", ())
    }
    assert provider_readers == {
        "task-worker",
        "restore-smoke-application-key-probe",
    }
    assert synthetic_readers == {
        "style-browser-worker",
        "task-worker",
        "restore-smoke-application-key-probe",
    }
    assert recommendation_readers == {
        "task-worker",
        "restore-smoke-application-key-probe",
    }
    assert workflow_c_readers == {
        "internal-api",
        "restore-smoke-application-key-probe",
        "task-worker",
    }
    assert {
        "workflow_c_artifact_object_store_access_key",
        "workflow_c_artifact_object_store_secret_key",
    } <= set(services["internal-api"]["secrets"])
    assert {
        "workflow_c_artifact_reader_access_key",
        "workflow_c_artifact_reader_secret_key",
    } <= set(worker["secrets"])
    assert {
        "workflow_c_artifact_reader_access_key",
        "workflow_c_artifact_reader_secret_key",
    }.isdisjoint(services["internal-api"]["secrets"])
    assert {
        "workflow_c_artifact_object_store_access_key",
        "workflow_c_artifact_object_store_secret_key",
    }.isdisjoint(worker["secrets"])

    maintenance = services["workflow-c-maintenance-worker"]
    assert set(maintenance["secrets"]) == {
        "worker_database_url",
        "workflow_c_artifact_deleter_access_key",
        "workflow_c_artifact_deleter_secret_key",
    }
    assert maintenance["networks"] == ["backend"]
    assert "workflow-c-maintenance" in maintenance["command"]
    assert {
        "provider_artifact_keyring",
        "recommendation_artifact_keyring",
        "object_store_access_key",
        "object_store_secret_key",
        "workflow_c_artifact_reader_access_key",
        "workflow_c_artifact_reader_secret_key",
        "workflow_c_artifact_object_store_access_key",
        "workflow_c_artifact_object_store_secret_key",
    }.isdisjoint(maintenance["secrets"])
    deleter_readers = {
        name
        for name, service in load_runtime_services().items()
        if "workflow_c_artifact_deleter_access_key" in service.get("secrets", ())
        or "workflow_c_artifact_deleter_secret_key" in service.get("secrets", ())
    }
    assert deleter_readers == {"minio-bootstrap", "workflow-c-maintenance-worker"}

    scheduler = services["workflow-c-maintenance-scheduler"]
    assert scheduler["secrets"] == ["worker_database_url"]
    assert scheduler["networks"] == ["backend"]
    assert scheduler["command"] == [
        "python",
        "-m",
        "geo_worker.workflow_c_maintenance_scheduler",
    ]
    assert {
        "workflow_c_artifact_keyring",
        "workflow_c_artifact_object_store_access_key",
        "workflow_c_artifact_object_store_secret_key",
        "workflow_c_artifact_reader_access_key",
        "workflow_c_artifact_reader_secret_key",
        "workflow_c_artifact_deleter_access_key",
        "workflow_c_artifact_deleter_secret_key",
    }.isdisjoint(scheduler["secrets"])

    recommendation_maintenance = services[
        "recommendation-artifact-maintenance-worker"
    ]
    assert set(recommendation_maintenance["secrets"]) == {
        "worker_database_url",
        "recommendation_artifact_deleter_access_key",
        "recommendation_artifact_deleter_secret_key",
    }
    assert recommendation_maintenance["networks"] == ["backend"]
    assert "recommendation-artifact-maintenance" in recommendation_maintenance[
        "command"
    ]
    assert {
        "recommendation_artifact_keyring",
        "recommendation_artifact_object_store_access_key",
        "recommendation_artifact_object_store_secret_key",
        "object_store_access_key",
        "object_store_secret_key",
        "workflow_c_artifact_deleter_access_key",
        "workflow_c_artifact_deleter_secret_key",
    }.isdisjoint(recommendation_maintenance["secrets"])
    recommendation_deleter_readers = {
        name
        for name, service in load_runtime_services().items()
        if "recommendation_artifact_deleter_access_key" in service.get("secrets", ())
        or "recommendation_artifact_deleter_secret_key" in service.get("secrets", ())
    }
    assert recommendation_deleter_readers == {
        "minio-bootstrap",
        "recommendation-artifact-maintenance-worker",
    }
    recommendation_writer_readers = {
        name
        for name, service in load_runtime_services().items()
        if "recommendation_artifact_object_store_access_key" in service.get(
            "secrets", ()
        )
        or "recommendation_artifact_object_store_secret_key" in service.get(
            "secrets", ()
        )
    }
    assert recommendation_writer_readers == {"minio-bootstrap", "task-worker"}

    recommendation_scheduler = services[
        "recommendation-artifact-maintenance-scheduler"
    ]
    assert recommendation_scheduler["secrets"] == ["worker_database_url"]
    assert recommendation_scheduler["networks"] == ["backend"]
    assert recommendation_scheduler["command"] == [
        "python",
        "-m",
        "geo_worker.recommendation_artifact_maintenance_scheduler",
    ]
    assert {
        "recommendation_artifact_keyring",
        "recommendation_artifact_object_store_access_key",
        "recommendation_artifact_object_store_secret_key",
        "recommendation_artifact_deleter_access_key",
        "recommendation_artifact_deleter_secret_key",
    }.isdisjoint(recommendation_scheduler["secrets"])

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for compose_file in (
        "infra/compose.prod.yml",
        "infra/compose.style-collection.yml",
        "infra/compose.connector.yml",
        "infra/compose.browser-capture.yml",
        "infra/dify/compose.production-runtime.yml",
    ):
        assert f"-f {compose_file}" in makefile


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
