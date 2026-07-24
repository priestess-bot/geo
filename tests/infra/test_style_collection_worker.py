from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "infra" / "compose.style-collection.yml"


def _service() -> dict[str, object]:
    compose = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    return compose["services"]["style-browser-worker"]


def test_style_browser_worker_has_a_frozen_isolated_process_budget() -> None:
    service = _service()

    assert "ports" not in service
    assert service["read_only"] is True
    assert service["user"] == "10001:10001"
    assert service["cap_drop"] == ["ALL"]
    assert service["pids_limit"] == 512
    assert service["deploy"]["resources"]["limits"] == {
        "cpus": "1.5",
        "memory": "2G",
        "pids": 512,
    }
    assert set(service["networks"]) == {"backend", "egress", "style-browser-control"}
    assert service["command"] == ["python", "-m", "geo_style_worker.entrypoint"]
    assert any("/run/geo-style-capture" in item for item in service["tmpfs"])


def test_page_runtime_has_egress_but_no_backend_or_secrets() -> None:
    compose = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    runtime = compose["services"]["style-browser-runtime"]

    assert set(runtime["networks"]) == {"style-browser-control", "egress"}
    assert "backend" not in runtime["networks"]
    assert "secrets" not in runtime
    assert "ports" not in runtime
    assert runtime["read_only"] is True
    assert runtime["cap_drop"] == ["ALL"]
    assert compose["networks"]["style-browser-control"]["internal"] is True
    assert runtime["command"] == [
        "playwright", "run-server", "--host", "0.0.0.0", "--port", "9222"
    ]


def test_style_browser_worker_uses_only_its_queue_and_required_secrets() -> None:
    service = _service()
    environment = service["environment"]

    assert environment["GEO_STYLE_COLLECTION_QUEUE"] == "style-collection"
    assert environment["GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID"] == (
        "${GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID:?set the provisioned Style Collection worker service identity UUID}"
    )
    assert environment["GEO_STYLE_BROWSER_WS_ENDPOINT"] == (
        "ws://style-browser-runtime:9222/"
    )
    assert environment["GEO_RUNTIME_EXPECTED_STYLE_BROWSER_WORKER_INSTANCES"] == (
        "${GEO_RUNTIME_EXPECTED_STYLE_BROWSER_WORKER_INSTANCES:-1}"
    )
    assert environment["GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE"] == (
        "/run/secrets/synthetic_artifact_keyring"
    )
    assert environment["GEO_DATABASE_URL_FILE"] == (
        "/run/secrets/style_browser_worker_database_url"
    )
    assert environment["GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE_BUCKET"] == (
        "geo-synthetic-style-raw"
    )
    assert environment["GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE_BUCKET"] == (
        "geo-synthetic-style-derived"
    )
    assert "OBJECT_STORE_BUCKET" not in environment
    assert set(service["secrets"]) == {
        "style_browser_worker_database_url",
        "synthetic_style_artifact_writer_access_key",
        "synthetic_style_artifact_writer_secret_key",
        "secret_store_master_keyring",
        "secret_store_request_hash_key",
        "synthetic_artifact_keyring",
    }
    health = service["healthcheck"]["test"]
    assert health[-1] == "style_browser_worker"


def test_style_browser_image_and_actor_are_frozen_to_one_process() -> None:
    dockerfile = (ROOT / "apps" / "api" / "Dockerfile.style-browser").read_text(
        encoding="utf-8"
    )
    entrypoint = (ROOT / "apps" / "api" / "geo_style_worker" / "entrypoint.py").read_text(
        encoding="utf-8"
    )
    tasks = (ROOT / "apps" / "api" / "geo_style_worker" / "tasks.py").read_text(
        encoding="utf-8"
    )

    assert "ARG GEO_STYLE_BROWSER_BASE_IMAGE" in dockerfile
    assert "uv sync --frozen --no-dev --extra style-browser" in dockerfile
    assert "python -m playwright install --with-deps chromium" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert '"--processes",\n            "1"' in entrypoint
    assert '"--threads",\n            "1"' in entrypoint
    assert 'queue_name=STYLE_QUEUE' in tasks
    assert 'max_retries=0' in tasks


def test_generic_worker_cannot_consume_style_collection_jobs() -> None:
    production = yaml.safe_load(
        (ROOT / "infra" / "compose.prod.yml").read_text(encoding="utf-8")
    )
    generic = production["services"]["task-worker"]
    relay = (ROOT / "apps" / "api" / "geo_worker" / "relay.py").read_text(
        encoding="utf-8"
    )
    generic_tasks = (ROOT / "apps" / "api" / "geo_worker" / "tasks.py").read_text(
        encoding="utf-8"
    )

    assert "geo_worker.tasks" in generic["command"]
    assert "geo_style_worker.tasks" not in generic["command"]
    assert 'actor_name="process_style_collection_job"' not in generic_tasks
    assert "synthetic.style.collect.queued" in relay
    assert "from geo_style_worker.tasks" not in relay
    assert "send_durable_job" in relay


def test_style_runtime_fails_closed_on_image_queue_browser_and_tmpfs() -> None:
    preflight = (ROOT / "apps" / "api" / "geo_style_worker" / "preflight.py").read_text(
        encoding="utf-8"
    )

    assert "EXPECTED_PLAYWRIGHT_VERSION = \"1.60.0\"" in preflight
    assert "GEO_STYLE_BROWSER_IMAGE_REFERENCE must be digest pinned" in preflight
    assert "Style Collection worker must use its dedicated queue" in preflight
    assert "GEO_STYLE_COLLECTION_SERVICE_IDENTITY_ID must be a UUID" in preflight
    assert "frozen Chromium executable is unavailable" in preflight
    assert "Style Collection capture mount must be tmpfs" in preflight
    assert "Style browser must use the isolated remote runtime" in preflight
    browser = (ROOT / "apps" / "api" / "geo_style_worker" / "browser_adapter.py").read_text(
        encoding="utf-8"
    )
    assert 'context.route_web_socket("**/*", lambda socket: socket.close())' in browser
