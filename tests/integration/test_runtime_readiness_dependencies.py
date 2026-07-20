from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import os
import socket
import subprocess
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest
from redis import Redis

from geo_api.app_factory import create_api_app
from geo_api.runtime_readiness import readiness_checker_from_environment
from geo_core.object_store import S3CompatibleObjectStore


POSTGRES_IMAGE = "pgvector/pgvector:pg16"
VALKEY_IMAGE = "valkey/valkey:8.0.2-alpine"
MINIO_IMAGE = "minio/minio:RELEASE.2025-01-20T14-49-07Z"

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class RuntimeDependencies:
    postgres_name: str
    valkey_name: str
    minio_name: str
    postgres_url: str
    postgres_password: str
    auth_token_secret: str
    valkey_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    bucket: str

    def readiness_environment(self) -> dict[str, str]:
        return {
            "GEO_DATABASE_URL": self.postgres_url,
            "GEO_AUTH_TOKEN_SECRET": self.auth_token_secret,
            "GEO_AUTH_MODE": "development",
            "GEO_DEPLOYMENT_ENVIRONMENT": "development",
            "GEO_TASK_QUEUE_BROKER_URL": self.valkey_url,
            "OBJECT_STORE_ENDPOINT": self.minio_endpoint,
            "OBJECT_STORE_BUCKET": self.bucket,
            "OBJECT_STORE_ACCESS_KEY": self.minio_access_key,
            "OBJECT_STORE_SECRET_KEY": self.minio_secret_key,
            "OBJECT_STORE_REGION": "us-east-1",
            "GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS": "1",
            "GEO_READINESS_TOTAL_TIMEOUT_SECONDS": "3",
        }


def _docker(
    *arguments: str,
    environment: Mapping[str, str] | None = None,
    check: bool = True,
    timeout: float = 180,
) -> str:
    process_environment = os.environ.copy()
    if environment:
        process_environment.update(environment)
    completed = subprocess.run(
        ("docker", *arguments),
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=process_environment,
    )
    return completed.stdout.strip()


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_until(
    check: Callable[[], None], *, description: str, timeout_seconds: float = 45
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            check()
            return
        except Exception as error:
            last_error = error
            time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {description}") from last_error


def _start_container(
    names: list[str],
    *,
    name: str,
    image: str,
    port: int,
    environment_names: tuple[str, ...] = (),
    environment: Mapping[str, str] | None = None,
    command: tuple[str, ...] = (),
) -> int:
    names.append(name)
    host_port = _unused_local_port()
    environment_arguments = tuple(
        argument for variable in environment_names for argument in ("-e", variable)
    )
    _docker(
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        "geo.test=f018-runtime-readiness",
        "--publish",
        f"127.0.0.1:{host_port}:{port}",
        *environment_arguments,
        image,
        *command,
        environment=environment,
    )
    published = _docker("port", name, f"{port}/tcp")
    assert published == f"127.0.0.1:{host_port}"
    return host_port


@contextmanager
def _isolated_runtime_dependencies() -> Iterator[RuntimeDependencies]:
    # Docker is an explicit requirement of F018-INT-01. A missing daemon or image fails the test.
    _docker("info", "--format", "{{.ServerVersion}}", timeout=30)
    run_id = uuid4().hex[:16]
    names: list[str] = []
    postgres_name = f"geo-f018-postgres-{run_id}"
    valkey_name = f"geo-f018-valkey-{run_id}"
    minio_name = f"geo-f018-minio-{run_id}"
    postgres_user = f"f018_{run_id}"
    postgres_password = f"pg-{uuid4().hex}"
    auth_token_secret = f"access-{uuid4().hex}"
    postgres_database = "geo_readiness"
    minio_access_key = f"f018{run_id}"
    minio_secret_key = f"minio-{uuid4().hex}"
    bucket = f"geo-f018-{run_id}"
    try:
        postgres_port = _start_container(
            names,
            name=postgres_name,
            image=POSTGRES_IMAGE,
            port=5432,
            environment_names=("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"),
            environment={
                "POSTGRES_DB": postgres_database,
                "POSTGRES_USER": postgres_user,
                "POSTGRES_PASSWORD": postgres_password,
            },
        )
        valkey_port = _start_container(
            names,
            name=valkey_name,
            image=VALKEY_IMAGE,
            port=6379,
        )
        minio_port = _start_container(
            names,
            name=minio_name,
            image=MINIO_IMAGE,
            port=9000,
            environment_names=("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"),
            environment={
                "MINIO_ROOT_USER": minio_access_key,
                "MINIO_ROOT_PASSWORD": minio_secret_key,
            },
            command=("server", "/data", "--address", ":9000"),
        )
        dependencies = RuntimeDependencies(
            postgres_name=postgres_name,
            valkey_name=valkey_name,
            minio_name=minio_name,
            postgres_url=(
                f"postgresql://{postgres_user}:{postgres_password}"
                f"@127.0.0.1:{postgres_port}/{postgres_database}"
            ),
            postgres_password=postgres_password,
            auth_token_secret=auth_token_secret,
            valkey_url=f"redis://127.0.0.1:{valkey_port}/0",
            minio_endpoint=f"http://127.0.0.1:{minio_port}",
            minio_access_key=minio_access_key,
            minio_secret_key=minio_secret_key,
            bucket=bucket,
        )
        _wait_for_dependencies(dependencies, create_bucket=True)
        yield dependencies
    finally:
        for name in reversed(names):
            _docker("rm", "--force", name, check=False, timeout=30)


def _wait_for_dependencies(
    dependencies: RuntimeDependencies, *, create_bucket: bool = False
) -> None:
    def postgres_ready() -> None:
        with psycopg.connect(dependencies.postgres_url, connect_timeout=1) as connection:
            assert connection.execute("SELECT 1").fetchone() == (1,)

    def valkey_ready() -> None:
        client = Redis.from_url(
            dependencies.valkey_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            assert client.ping() is True
        finally:
            client.close()

    _wait_until(postgres_ready, description="isolated PostgreSQL")
    _wait_until(valkey_ready, description="isolated Valkey")
    if create_bucket:
        store = S3CompatibleObjectStore(
            endpoint=dependencies.minio_endpoint,
            bucket=dependencies.bucket,
            access_key=dependencies.minio_access_key,
            secret_key=dependencies.minio_secret_key,
            auto_create_bucket=True,
        )
        _wait_until(store.ensure_bucket, description="isolated MinIO bucket")


def _assert_liveness(internal: TestClient, customer: TestClient) -> None:
    internal_health = internal.get("/health")
    customer_health = customer.get("/health")
    assert internal_health.status_code == 200
    assert customer_health.status_code == 200
    assert internal_health.json()["status"] == "ok"
    assert customer_health.json()["status"] == "ok"


def _assert_unavailable(
    response,
    *,
    expected_code: str,
    forbidden_values: tuple[str, ...],
) -> None:
    assert response.status_code == 503
    assert response.headers["X-GEO-Readiness-Codes"] == expected_code
    assert response.headers["Retry-After"] == "5"
    rendered = response.text + repr(dict(response.headers))
    for value in forbidden_values:
        assert value not in rendered


def _restart_and_wait_ready(
    container_name: str,
    client: TestClient,
    *,
    description: str,
) -> None:
    _docker("start", container_name)

    def api_ready() -> None:
        response = client.get("/ready")
        if response.status_code != 200:
            raise RuntimeError(f"{description} readiness has not recovered")

    _wait_until(api_ready, description=description)


def test_real_dependency_failures_follow_the_internal_customer_readiness_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_runtime_dependencies() as dependencies:
        environment = dependencies.readiness_environment()
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        for name in ("GEO_DATABASE_URL_FILE", "GEO_AUTH_TOKEN_SECRET_FILE"):
            monkeypatch.delenv(name, raising=False)
        internal_app = create_api_app(
            surface="internal",
            readiness_service=readiness_checker_from_environment(
                surface="internal", environment=environment
            ),
        )
        customer_app = create_api_app(
            surface="customer",
            readiness_service=readiness_checker_from_environment(
                surface="customer", environment=environment
            ),
        )
        forbidden_values = (
            dependencies.postgres_url,
            dependencies.postgres_password,
            dependencies.auth_token_secret,
            dependencies.valkey_url,
            dependencies.minio_access_key,
            dependencies.minio_secret_key,
            dependencies.minio_endpoint,
            dependencies.postgres_name,
            dependencies.valkey_name,
            dependencies.minio_name,
        )

        with TestClient(internal_app) as internal, TestClient(customer_app) as customer:
            assert internal.get("/ready").status_code == 200
            assert customer.get("/ready").status_code == 200
            _assert_liveness(internal, customer)

            _docker("stop", "--time", "1", dependencies.minio_name)
            _assert_unavailable(
                internal.get("/ready"),
                expected_code="object_store_unavailable",
                forbidden_values=forbidden_values,
            )
            assert customer.get("/ready").status_code == 200
            _assert_liveness(internal, customer)
            _restart_and_wait_ready(
                dependencies.minio_name,
                internal,
                description="Internal API after MinIO restart",
            )

            _docker("stop", "--time", "1", dependencies.valkey_name)
            _assert_unavailable(
                internal.get("/ready"),
                expected_code="valkey_unavailable",
                forbidden_values=forbidden_values,
            )
            assert customer.get("/ready").status_code == 200
            _assert_liveness(internal, customer)
            _restart_and_wait_ready(
                dependencies.valkey_name,
                internal,
                description="Internal API after Valkey restart",
            )

            _docker("stop", "--time", "1", dependencies.postgres_name)
            internal_unavailable = internal.get("/ready")
            customer_unavailable = customer.get("/ready")
            _assert_unavailable(
                internal_unavailable,
                expected_code="postgres_unavailable",
                forbidden_values=forbidden_values,
            )
            _assert_unavailable(
                customer_unavailable,
                expected_code="postgres_unavailable",
                forbidden_values=forbidden_values,
            )
            _assert_liveness(internal, customer)
            _restart_and_wait_ready(
                dependencies.postgres_name,
                internal,
                description="Internal API after PostgreSQL restart",
            )
            assert customer.get("/ready").status_code == 200
            _assert_liveness(internal, customer)
