from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict[str, object]:
    return yaml.safe_load((ROOT / "infra" / name).read_text(encoding="utf-8"))


def _assert_isolated_bootstrap(
    service: dict[str, object], *, bucket: str, prefix: str
) -> None:
    assert service["restart"] == "no"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["networks"] == ["backend"]
    assert "ports" not in service
    environment = service["environment"]
    assert environment["ISOLATED_BUCKET"] == bucket
    assert environment["ISOLATED_PREFIX"] == prefix
    assert set(service["depends_on"]) == {"minio"}


def test_browser_capture_worker_is_a_dedicated_egress_runtime() -> None:
    compose = _load("compose.browser-capture.yml")
    service = compose["services"]["browser-capture-worker"]

    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["pids_limit"] == 512
    assert set(service["networks"]) == {"backend", "egress"}
    assert "ports" not in service
    assert service["command"] == ["python", "-m", "geo_browser_capture_worker.entrypoint"]
    assert set(service["depends_on"]) == {
        "migrate",
        "browser-capture-artifact-bootstrap",
        "valkey",
    }
    environment = service["environment"]
    assert environment["GEO_BROWSER_ARTIFACT_OBJECT_STORE_AUTO_CREATE_BUCKET"] == "0"
    assert environment["GEO_BROWSER_ARTIFACT_OBJECT_STORE_BUCKET"] == (
        "geo-browser-capture-raw"
    )
    assert environment["GEO_DATABASE_URL_FILE"] == (
        "/run/secrets/browser_capture_worker_database_url"
    )
    assert set(service["secrets"]) == {
        "browser_capture_worker_database_url",
        "browser_artifact_key",
        "browser_artifact_writer_access_key",
        "browser_artifact_writer_secret_key",
        "secret_store_master_keyring",
        "secret_store_request_hash_key",
    }
    _assert_isolated_bootstrap(
        compose["services"]["browser-capture-artifact-bootstrap"],
        bucket="geo-browser-capture-raw",
        prefix="browser-captures/",
    )


def test_connector_worker_bootstraps_its_actual_raw_bucket() -> None:
    compose = _load("compose.connector.yml")
    service = compose["services"]["connector-worker"]

    assert set(service["depends_on"]) == {
        "migrate",
        "connector-artifact-bootstrap",
        "valkey",
    }
    assert service["environment"]["GEO_CONNECTOR_ARTIFACT_OBJECT_STORE_BUCKET"] == (
        "geo-connector-raw"
    )
    _assert_isolated_bootstrap(
        compose["services"]["connector-artifact-bootstrap"],
        bucket="geo-connector-raw",
        prefix="connectors/",
    )


def test_isolated_writer_bootstrap_enforces_negative_permissions() -> None:
    source = (ROOT / "infra" / "minio" / "bootstrap-isolated-writer.sh").read_text(
        encoding="utf-8"
    )

    assert 'mc version enable "root/$bucket"' in source
    assert 's3:GetObjectVersion' in source
    assert '"s3:PutObject"' in source
    assert "s3:DeleteObject" not in source
    assert "unexpectedly wrote outside its prefix" in source
    assert "unexpectedly created a bucket" in source
    assert "unexpectedly used an admin API" in source
    assert "policy_sha256" in source


def test_external_worker_images_drop_root_privileges_and_freeze_queues() -> None:
    browser_dockerfile = (
        ROOT / "apps" / "browser_capture_worker" / "Dockerfile"
    ).read_text(encoding="utf-8")
    connector_dockerfile = (ROOT / "apps" / "connector_worker" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    browser_entrypoint = (
        ROOT
        / "apps"
        / "browser_capture_worker"
        / "geo_browser_capture_worker"
        / "entrypoint.py"
    ).read_text(encoding="utf-8")

    assert "USER 10001:10001" in browser_dockerfile
    assert "USER 10001:10001" in connector_dockerfile
    assert '"--queues",\n            BROWSER_CAPTURE_QUEUE' in browser_entrypoint
    assert '"--processes",\n            "1"' in browser_entrypoint
    assert '"--threads",\n            "1"' in browser_entrypoint
