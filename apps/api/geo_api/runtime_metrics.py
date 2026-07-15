from __future__ import annotations

import os
import threading
from collections import defaultdict
from collections.abc import Mapping

from geo_core.runtime import RuntimePersistenceError, runtime_postgres_pool_snapshot


METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
REQUEST_DURATION_BUCKETS_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_METRICS_LOCK = threading.Lock()
_REQUEST_TOTAL: defaultdict[tuple[str, str, str], int] = defaultdict(int)
_REQUEST_DURATION_BUCKET_TOTAL: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
_REQUEST_DURATION_SUM: defaultdict[tuple[str, str, str], float] = defaultdict(float)
_REQUEST_DURATION_COUNT: defaultdict[tuple[str, str, str], int] = defaultdict(int)


def observe_api_request(*, method: str, path: str, status_code: int, duration_seconds: float) -> None:
    label_key = (method.upper(), path, str(status_code))
    with _METRICS_LOCK:
        _REQUEST_TOTAL[label_key] += 1
        _REQUEST_DURATION_SUM[label_key] += duration_seconds
        _REQUEST_DURATION_COUNT[label_key] += 1
        for bucket in REQUEST_DURATION_BUCKETS_SECONDS:
            if duration_seconds <= bucket:
                _REQUEST_DURATION_BUCKET_TOTAL[(*label_key, _format_bucket_label(bucket))] += 1
        _REQUEST_DURATION_BUCKET_TOTAL[(*label_key, "+Inf")] += 1


def reset_runtime_metrics() -> None:
    with _METRICS_LOCK:
        _REQUEST_TOTAL.clear()
        _REQUEST_DURATION_BUCKET_TOTAL.clear()
        _REQUEST_DURATION_SUM.clear()
        _REQUEST_DURATION_COUNT.clear()


def _format_bucket_label(bucket: float) -> str:
    return f"{bucket:g}"


def _format_metric_number(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.12g}"
    return "0"


def _escape_metric_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_labels(labels: Mapping[str, object]) -> str:
    return ",".join(f'{key}="{_escape_metric_label(value)}"' for key, value in labels.items())


def _durable_job_snapshot() -> dict[str, object]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return {}
    import psycopg

    from geo_core.durable_jobs import collect_durable_job_metrics

    connection = psycopg.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.rls_enabled', 'false', false)")
            cursor.execute("SELECT set_config('geo.runtime_project_access_control', 'false', false)")
            cursor.execute("SELECT set_config('app.actor_id', 'runtime-metrics', false)")
            cursor.execute("SELECT set_config('app.roles', 'system,worker', false)")
        connection.commit()
        return collect_durable_job_metrics(connection)
    finally:
        connection.close()


def render_runtime_metrics() -> str:
    with _METRICS_LOCK:
        request_total = dict(_REQUEST_TOTAL)
        duration_buckets = dict(_REQUEST_DURATION_BUCKET_TOTAL)
        duration_sum = dict(_REQUEST_DURATION_SUM)
        duration_count = dict(_REQUEST_DURATION_COUNT)

    lines = [
        "# HELP geo_api_requests_total Total HTTP requests handled by the GEO API.",
        "# TYPE geo_api_requests_total counter",
    ]
    for (method, path, status), count in sorted(request_total.items()):
        lines.append(
            f'geo_api_requests_total{{{_metric_labels({"method": method, "path": path, "status": status})}}} {count}'
        )

    lines.extend(
        [
            "# HELP geo_api_request_duration_seconds HTTP request duration in seconds.",
            "# TYPE geo_api_request_duration_seconds histogram",
        ]
    )
    for (method, path, status, le), count in sorted(duration_buckets.items()):
        lines.append(
            "geo_api_request_duration_seconds_bucket"
            f'{{{_metric_labels({"method": method, "path": path, "status": status, "le": le})}}} {count}'
        )
    for (method, path, status), total_seconds in sorted(duration_sum.items()):
        lines.append(
            "geo_api_request_duration_seconds_sum"
            f'{{{_metric_labels({"method": method, "path": path, "status": status})}}} '
            f"{_format_metric_number(total_seconds)}"
        )
    for (method, path, status), count in sorted(duration_count.items()):
        lines.append(
            "geo_api_request_duration_seconds_count"
            f'{{{_metric_labels({"method": method, "path": path, "status": status})}}} {count}'
        )

    lines.extend(
        [
            "# HELP geo_runtime_postgres_pool_snapshot_ok Whether the runtime PostgreSQL pool snapshot could be read.",
            "# TYPE geo_runtime_postgres_pool_snapshot_ok gauge",
        ]
    )
    try:
        pool_snapshot = runtime_postgres_pool_snapshot()
    except RuntimePersistenceError:
        lines.append("geo_runtime_postgres_pool_snapshot_ok 0")
        pool_snapshot = {}
    else:
        lines.append("geo_runtime_postgres_pool_snapshot_ok 1")

    lines.extend(
        [
            "# HELP geo_runtime_postgres_pool_enabled Whether runtime PostgreSQL connection pooling is enabled.",
            "# TYPE geo_runtime_postgres_pool_enabled gauge",
            f"geo_runtime_postgres_pool_enabled {_format_metric_number(pool_snapshot.get('enabled', False))}",
            "# HELP geo_runtime_postgres_pool_max_size Configured runtime PostgreSQL pool maximum size.",
            "# TYPE geo_runtime_postgres_pool_max_size gauge",
            f"geo_runtime_postgres_pool_max_size {_format_metric_number(pool_snapshot.get('max_size', 0))}",
            "# HELP geo_runtime_postgres_pool_timeout_seconds Configured runtime PostgreSQL pool acquire timeout.",
            "# TYPE geo_runtime_postgres_pool_timeout_seconds gauge",
            f"geo_runtime_postgres_pool_timeout_seconds {_format_metric_number(pool_snapshot.get('timeout_seconds', 0.0))}",
            "# HELP geo_runtime_postgres_pool_connections_created Process-local PostgreSQL pool connections created.",
            "# TYPE geo_runtime_postgres_pool_connections_created gauge",
            f"geo_runtime_postgres_pool_connections_created {_format_metric_number(pool_snapshot.get('created', 0))}",
            "# HELP geo_runtime_postgres_pool_connections_available Process-local PostgreSQL pool connections available.",
            "# TYPE geo_runtime_postgres_pool_connections_available gauge",
            f"geo_runtime_postgres_pool_connections_available {_format_metric_number(pool_snapshot.get('available', 0))}",
        ]
    )

    lines.extend(
        [
            "# HELP geo_durable_job_snapshot_ok Whether durable PostgreSQL queue metrics could be read.",
            "# TYPE geo_durable_job_snapshot_ok gauge",
        ]
    )
    try:
        durable_snapshot = _durable_job_snapshot()
    except Exception:  # metrics must remain scrapeable while the queue DB is unavailable.
        durable_snapshot = {}
        lines.append("geo_durable_job_snapshot_ok 0")
    else:
        lines.append(f"geo_durable_job_snapshot_ok {1 if durable_snapshot else 0}")

    queue_metric_names = (
        ("queue_depth", "geo_durable_job_queue_depth"),
        ("oldest_queued_age_seconds", "geo_durable_job_oldest_queued_age_seconds"),
        ("expired_active_count", "geo_durable_job_expired_active_count"),
        ("oldest_expired_age_seconds", "geo_durable_job_oldest_expired_age_seconds"),
        ("reclaimed_total", "geo_durable_job_reclaimed_total"),
        ("dead_letter_total", "geo_durable_job_dead_letter_total"),
        ("cancelled_total", "geo_durable_job_cancelled_total"),
    )
    for key, metric_name in queue_metric_names:
        lines.extend([f"# TYPE {metric_name} gauge"])
        for record in durable_snapshot.get("queues", []):
            if not isinstance(record, Mapping):
                continue
            labels = _metric_labels(
                {"queue": record.get("queue", ""), "job_type": record.get("job_type", "")}
            )
            lines.append(f"{metric_name}{{{labels}}} {_format_metric_number(record.get(key, 0))}")
    for record in durable_snapshot.get("counters", []):
        if not isinstance(record, Mapping):
            continue
        labels = _metric_labels(
            {
                "queue": record.get("queue", ""),
                "job_type": record.get("job_type", ""),
                "event": record.get("metric", ""),
            }
        )
        lines.append(
            f"geo_durable_job_events_total{{{labels}}} {_format_metric_number(record.get('value', 0))}"
        )
    for record in durable_snapshot.get("cursors", []):
        if not isinstance(record, Mapping):
            continue
        labels = _metric_labels({"queue": record.get("queue_name", "")})
        lines.append(
            f"geo_durable_job_recovery_cursor{{{labels}}} "
            f"{_format_metric_number(record.get('cursor_index', 0))}"
        )
        lines.append(
            f"geo_durable_job_recovery_slots_used{{{labels}}} "
            f"{_format_metric_number(record.get('recovery_slots_used', 0))}"
        )
        lines.append(
            f"geo_durable_job_worker_heartbeat_age_seconds{{{labels}}} "
            f"{_format_metric_number(record.get('worker_heartbeat_age_seconds', 0))}"
        )
    return "\n".join(lines) + "\n"
