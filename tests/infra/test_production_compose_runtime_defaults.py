from tests.infra.production_compose_support import (
    ROOT,
    load_compose,
    load_style_compose,
)


def test_production_environment_example_freezes_runtime_truth_defaults() -> None:
    lines = (ROOT / "infra" / "production.env.example").read_text(encoding="utf-8").splitlines()
    values = dict(
        line.split("=", 1)
        for line in lines
        if line and not line.startswith("#") and "=" in line
    )

    assert values["GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS"] == "2"
    assert values["GEO_READINESS_TOTAL_TIMEOUT_SECONDS"] == "5"
    assert values["GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS"] == "10"
    assert values["GEO_RUNTIME_HEARTBEAT_STALE_SECONDS"] == "30"
    assert values["GEO_RUNTIME_QUEUED_STALE_SECONDS"] == "600"
    assert values["GEO_RUNTIME_OUTBOX_STALE_SECONDS"] == "300"
    assert values["GEO_RUNTIME_RUNNING_GRACE_SECONDS"] == "60"
    assert values["GEO_RUNTIME_FAILURE_WINDOW_SECONDS"] == "86400"
    assert values["GEO_RUNTIME_EXPECTED_TASK_WORKER_INSTANCES"] == "4"
    assert values["GEO_RUNTIME_EXPECTED_OUTBOX_RELAY_INSTANCES"] == "1"
    assert values["GEO_RUNTIME_EXPECTED_STYLE_BROWSER_WORKER_INSTANCES"] == "1"
    assert values["GEO_RUNTIME_EXPECTED_WORKFLOW_C_MAINTENANCE_SCHEDULER_INSTANCES"] == "1"
    assert values["GEO_BACKUP_MINIO_STAGING_SIZE"] == "8g"
    assert values["GEO_RESTORE_TMPFS_ROOT"] == "/run/geo-restore-tmpfs"

    services = load_compose()["services"]
    for name in ("internal-api", "customer-api"):
        environment = services[name]["environment"]
        for field in (
            "GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS",
            "GEO_READINESS_TOTAL_TIMEOUT_SECONDS",
        ):
            assert environment[field] == f"${{{field}:-{values[field]}}}"
    worker_environment = services["task-worker"]["environment"]
    relay_environment = services["outbox-relay"]["environment"]
    style_environment = load_style_compose()["services"]["style-browser-worker"][
        "environment"
    ]
    worker_count_field = "GEO_RUNTIME_EXPECTED_TASK_WORKER_INSTANCES"
    relay_count_field = "GEO_RUNTIME_EXPECTED_OUTBOX_RELAY_INSTANCES"
    assert worker_environment[worker_count_field] == (
        f"${{{worker_count_field}:-{values[worker_count_field]}}}"
    )
    assert relay_environment[relay_count_field] == (
        f"${{{relay_count_field}:-{values[relay_count_field]}}}"
    )
    style_count_field = "GEO_RUNTIME_EXPECTED_STYLE_BROWSER_WORKER_INSTANCES"
    assert style_environment[style_count_field] == (
        f"${{{style_count_field}:-{values[style_count_field]}}}"
    )
    scheduler_count_field = "GEO_RUNTIME_EXPECTED_WORKFLOW_C_MAINTENANCE_SCHEDULER_INSTANCES"
    scheduler_environment = services["workflow-c-maintenance-scheduler"]["environment"]
    assert scheduler_environment[scheduler_count_field] == (
        f"${{{scheduler_count_field}:-{values[scheduler_count_field]}}}"
    )
    assert "--processes" in services["task-worker"]["command"]
    process_index = services["task-worker"]["command"].index("--processes")
    assert services["task-worker"]["command"][process_index + 1] == (
        f"${{{worker_count_field}:-{values[worker_count_field]}}}"
    )
    thread_index = services["task-worker"]["command"].index("--threads")
    assert services["task-worker"]["command"][thread_index + 1] == "4"
    for name in ("task-worker", "outbox-relay"):
        environment = services[name]["environment"]
        for field in (
            "GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS",
            "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS",
            "GEO_RUNTIME_QUEUED_STALE_SECONDS",
            "GEO_RUNTIME_OUTBOX_STALE_SECONDS",
            "GEO_RUNTIME_RUNNING_GRACE_SECONDS",
            "GEO_RUNTIME_FAILURE_WINDOW_SECONDS",
        ):
            assert environment[field] == f"${{{field}:-{values[field]}}}"
