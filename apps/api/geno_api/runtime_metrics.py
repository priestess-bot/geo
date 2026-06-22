from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Mapping

from geno_core.runtime import RuntimePersistenceError, runtime_postgres_pool_snapshot


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


def render_runtime_metrics() -> str:
    with _METRICS_LOCK:
        request_total = dict(_REQUEST_TOTAL)
        duration_buckets = dict(_REQUEST_DURATION_BUCKET_TOTAL)
        duration_sum = dict(_REQUEST_DURATION_SUM)
        duration_count = dict(_REQUEST_DURATION_COUNT)

    lines = [
        "# HELP geno_api_requests_total Total HTTP requests handled by the GENO API.",
        "# TYPE geno_api_requests_total counter",
    ]
    for (method, path, status), count in sorted(request_total.items()):
        lines.append(
            f'geno_api_requests_total{{{_metric_labels({"method": method, "path": path, "status": status})}}} {count}'
        )

    lines.extend(
        [
            "# HELP geno_api_request_duration_seconds HTTP request duration in seconds.",
            "# TYPE geno_api_request_duration_seconds histogram",
        ]
    )
    for (method, path, status, le), count in sorted(duration_buckets.items()):
        lines.append(
            "geno_api_request_duration_seconds_bucket"
            f'{{{_metric_labels({"method": method, "path": path, "status": status, "le": le})}}} {count}'
        )
    for (method, path, status), total_seconds in sorted(duration_sum.items()):
        lines.append(
            "geno_api_request_duration_seconds_sum"
            f'{{{_metric_labels({"method": method, "path": path, "status": status})}}} '
            f"{_format_metric_number(total_seconds)}"
        )
    for (method, path, status), count in sorted(duration_count.items()):
        lines.append(
            "geno_api_request_duration_seconds_count"
            f'{{{_metric_labels({"method": method, "path": path, "status": status})}}} {count}'
        )

    lines.extend(
        [
            "# HELP geno_runtime_postgres_pool_snapshot_ok Whether the runtime PostgreSQL pool snapshot could be read.",
            "# TYPE geno_runtime_postgres_pool_snapshot_ok gauge",
        ]
    )
    try:
        pool_snapshot = runtime_postgres_pool_snapshot()
    except RuntimePersistenceError:
        lines.append("geno_runtime_postgres_pool_snapshot_ok 0")
        pool_snapshot = {}
    else:
        lines.append("geno_runtime_postgres_pool_snapshot_ok 1")

    lines.extend(
        [
            "# HELP geno_runtime_postgres_pool_enabled Whether runtime PostgreSQL connection pooling is enabled.",
            "# TYPE geno_runtime_postgres_pool_enabled gauge",
            f"geno_runtime_postgres_pool_enabled {_format_metric_number(pool_snapshot.get('enabled', False))}",
            "# HELP geno_runtime_postgres_pool_max_size Configured runtime PostgreSQL pool maximum size.",
            "# TYPE geno_runtime_postgres_pool_max_size gauge",
            f"geno_runtime_postgres_pool_max_size {_format_metric_number(pool_snapshot.get('max_size', 0))}",
            "# HELP geno_runtime_postgres_pool_timeout_seconds Configured runtime PostgreSQL pool acquire timeout.",
            "# TYPE geno_runtime_postgres_pool_timeout_seconds gauge",
            f"geno_runtime_postgres_pool_timeout_seconds {_format_metric_number(pool_snapshot.get('timeout_seconds', 0.0))}",
            "# HELP geno_runtime_postgres_pool_connections_created Process-local PostgreSQL pool connections created.",
            "# TYPE geno_runtime_postgres_pool_connections_created gauge",
            f"geno_runtime_postgres_pool_connections_created {_format_metric_number(pool_snapshot.get('created', 0))}",
            "# HELP geno_runtime_postgres_pool_connections_available Process-local PostgreSQL pool connections available.",
            "# TYPE geno_runtime_postgres_pool_connections_available gauge",
            f"geno_runtime_postgres_pool_connections_available {_format_metric_number(pool_snapshot.get('available', 0))}",
        ]
    )
    return "\n".join(lines) + "\n"
