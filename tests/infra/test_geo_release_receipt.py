from __future__ import annotations

import json
from pathlib import Path

from scripts import geo_release_receipt


ROOT = Path(__file__).resolve().parents[2]


def test_read_release_commit_ignores_all_other_env_values(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        "SECRET_VALUE=must-never-appear\n"
        "GEO_RELEASE_COMMIT=0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )

    assert geo_release_receipt.read_release_commit(env_file) == (
        "0123456789abcdef0123456789abcdef01234567"
    )


def test_receipt_without_runtime_is_non_secret_and_reviewable(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        "SECRET_VALUE=must-never-appear\n"
        "GEO_RELEASE_COMMIT=0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )
    payload = geo_release_receipt.build_receipt(
        repo_root=ROOT,
        mode="internal",
        project="geo-receipt-test-project-that-does-not-exist",
        dify_project="geo-receipt-test-dify-that-does-not-exist",
        env_file=env_file,
        compose_files=(ROOT / "infra/docker-compose.yml",),
    )

    serialized = json.dumps(payload)
    assert payload["schema_version"] == "geo-release-receipt-v3"
    assert payload["containers"] == []
    assert payload["dify_containers"] == []
    assert payload["runtime_release_matches_source"] is False
    assert payload["missing_release_tracked_services"]
    assert payload["unexpected_running_compose_containers"] == []
    assert payload["unexpected_running_dify_compose_containers"] == []
    assert payload["missing_required_running_services"]
    assert payload["unhealthy_required_services"]
    assert payload["incomplete_required_services"]
    assert payload["database_alembic_heads"] == []
    assert payload["database_alembic_matches_source"] is False
    assert payload["missing_dify_services"]
    assert payload["unhealthy_required_dify_services"]
    assert payload["all_runtime_images_content_addressed"] is False
    assert "must-never-appear" not in serialized
    assert payload["compose_files"][0]["sha256"]


def test_write_receipt_is_private_and_atomic(tmp_path: Path) -> None:
    destination = tmp_path / "receipts" / "release.json"
    geo_release_receipt.write_receipt(destination, {"schema_version": "test"})

    assert json.loads(destination.read_text(encoding="utf-8"))["schema_version"] == "test"
    assert destination.stat().st_mode & 0o777 == 0o600


def test_release_match_requires_every_tracked_service_and_commit() -> None:
    commit = "a" * 40
    containers = [
        {"service": "internal-api", "release_commit": commit},
        {"service": "admin-web", "release_commit": commit},
        {"service": "postgres", "release_commit": None},
    ]
    complete = geo_release_receipt.release_match_summary(
        containers,
        tracked_services=("internal-api", "admin-web"),
        source_commit=commit,
        declared_release=commit,
    )
    assert complete["runtime_release_matches_source"] is True
    assert complete["missing_release_commit_services"] == []

    missing = geo_release_receipt.release_match_summary(
        containers[:1],
        tracked_services=("internal-api", "admin-web"),
        source_commit=commit,
        declared_release=commit,
    )
    assert missing["runtime_release_matches_source"] is False
    assert missing["missing_release_tracked_services"] == ["admin-web"]


def test_required_running_services_include_stateful_dependencies() -> None:
    internal = set(geo_release_receipt.required_running_services(ROOT, "internal"))

    assert {"postgres", "minio", "valkey"} <= internal
    assert {"connector-worker", "browser-capture-worker"} <= internal
    assert "minio-init" not in internal


def test_health_and_completion_summaries_fail_closed() -> None:
    containers = [
        {
            "service": "postgres",
            "container_name": "postgres-new",
            "created_at": "2026-08-10T01:00:00Z",
            "state": "running",
            "health_status": "unhealthy",
            "exit_code": 0,
        },
        {
            "service": "migrate",
            "container_name": "migrate-old",
            "created_at": "2026-08-09T01:00:00Z",
            "state": "exited",
            "health_status": None,
            "exit_code": 0,
        },
        {
            "service": "migrate",
            "container_name": "migrate-new",
            "created_at": "2026-08-10T01:00:00Z",
            "state": "exited",
            "health_status": None,
            "exit_code": 1,
        },
    ]

    health = geo_release_receipt.service_health_summary(
        containers,
        required_services=("postgres", "minio"),
    )
    completed = geo_release_receipt.completed_service_summary(
        containers,
        required_services=("migrate", "minio-init"),
    )

    assert health["unhealthy_required_services"] == ["minio", "postgres"]
    assert completed["incomplete_required_services"] == ["migrate", "minio-init"]
    assert completed["completed_service_containers"][0]["container_name"] == "migrate-new"


def test_database_head_is_read_from_the_running_postgres_container(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, check=True):
        commands.append(list(command))
        return "0131_lokiproxy_pool\n"

    monkeypatch.setattr(geo_release_receipt, "run", fake_run)
    heads = geo_release_receipt.database_alembic_heads(
        [
            {
                "service": "postgres",
                "container_name": "geo-postgres-1",
                "created_at": "2026-08-10T01:00:00Z",
                "state": "running",
            }
        ],
        repo_root=ROOT,
    )

    assert heads == ["0131_lokiproxy_pool"]
    assert commands[0][:3] == ["docker", "exec", "geo-postgres-1"]


def test_compose_identity_rejects_oneoff_and_foreign_config(tmp_path: Path) -> None:
    canonical = tmp_path / "infra" / "compose.yml"
    overlay = tmp_path / "infra" / "overlay.yml"
    compose_files = (canonical, overlay)
    expected = {
        "container_name": "geo-postgres-1",
        "state": "running",
        "compose_project": "geo",
        "compose_oneoff": "False",
        "compose_config_files": sorted(str(path.resolve()) for path in compose_files),
        "compose_working_dir": str(canonical.resolve().parent),
    }
    oneoff = {**expected, "container_name": "geo-postgres-run", "compose_oneoff": "True"}
    foreign = {
        **expected,
        "container_name": "geo-postgres-foreign",
        "compose_config_files": [str(canonical.resolve())],
    }

    assert geo_release_receipt.matches_compose_identity(
        expected,
        project="geo",
        compose_files=compose_files,
    )
    summary = geo_release_receipt.compose_identity_summary(
        (expected, oneoff, foreign),
        project="geo",
        compose_files=compose_files,
    )

    assert summary["unexpected_running_compose_containers"] == [
        "geo-postgres-foreign",
        "geo-postgres-run",
    ]


def test_dify_compose_identity_uses_the_pinned_runtime_and_override() -> None:
    compose_files = geo_release_receipt.dify_compose_files(ROOT)

    assert compose_files == [
        (ROOT / ".runtime/dify-1.16.0/docker/docker-compose.yaml").resolve(),
        (ROOT / "infra/dify/docker-compose.dify.yml").resolve(),
    ]
