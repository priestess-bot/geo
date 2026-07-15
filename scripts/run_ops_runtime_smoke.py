from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


def _request(url: str) -> tuple[int, str]:
    request = Request(url, headers={"accept": "application/json,text/plain"})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except URLError as exc:
        raise RuntimeError(f"request failed: {url}: {exc}") from exc


def _wait(url: str, *, attempts: int = 30) -> tuple[int, str]:
    last_error = ""
    for _ in range(attempts):
        try:
            status, body = _request(url)
            if status == 200:
                return status, body
            last_error = f"status={status} body={body[:200]}"
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(2)
    raise AssertionError(f"service did not become ready: {url}: {last_error}")


def _wait_prometheus_target(url: str, *, job_name: str, attempts: int = 30) -> tuple[int, list[dict[str, object]]]:
    last_targets: list[dict[str, object]] = []
    last_error = ""
    for _ in range(attempts):
        try:
            status, body = _request(url)
            if status == 200:
                payload = json.loads(body)
                active_targets = payload.get("data", {}).get("activeTargets", [])
                if isinstance(active_targets, list):
                    last_targets = [target for target in active_targets if isinstance(target, dict)]
                job_targets = [
                    target
                    for target in last_targets
                    if isinstance(target.get("labels"), dict)
                    and target["labels"].get("job") == job_name
                ]
                if job_targets and all(target.get("health") == "up" for target in job_targets):
                    return status, job_targets
                last_error = f"job_targets={job_targets}"
            else:
                last_error = f"status={status} body={body[:200]}"
        except (RuntimeError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise AssertionError(f"Prometheus target did not become ready: {url}: {last_error}; targets={last_targets}")


def run_ops_runtime_smoke() -> dict[str, object]:
    run_id = str(uuid4())
    started_at = datetime.now(UTC)
    api_base = os.environ.get("GEO_OPS_SMOKE_API_BASE_URL", "http://api:8000").rstrip("/")
    prometheus_base = os.environ.get("GEO_OPS_SMOKE_PROMETHEUS_BASE_URL", "http://prometheus:9090").rstrip("/")
    grafana_base = os.environ.get("GEO_OPS_SMOKE_GRAFANA_BASE_URL", "http://grafana:3000").rstrip("/")

    checks: list[dict[str, object]] = []
    health_status, health_body = _wait(f"{api_base}/health")
    health = json.loads(health_body)
    if health.get("status") != "ok":
        raise AssertionError(f"unexpected API health payload: {health}")
    checks.append({"name": "api_health", "status": "pass", "http_status": health_status})

    ready_status, ready_body = _wait(f"{api_base}/ready")
    ready = json.loads(ready_body)
    if ready.get("status") != "pass":
        raise AssertionError(f"unexpected API readiness payload: {ready}")
    checks.append({"name": "api_ready", "status": "pass", "http_status": ready_status})

    metrics_status, metrics_body = _wait(f"{api_base}/metrics")
    required_metrics = {"geo_api_requests_total", "geo_runtime_postgres_pool_snapshot_ok"}
    missing_metrics = sorted(metric for metric in required_metrics if metric not in metrics_body)
    if missing_metrics:
        raise AssertionError(f"missing runtime metrics: {missing_metrics}")
    checks.append({"name": "api_metrics", "status": "pass", "http_status": metrics_status})

    prometheus_status, api_targets = _wait_prometheus_target(
        f"{prometheus_base}/api/v1/targets",
        job_name="geo-api",
    )
    checks.append({"name": "prometheus_target", "status": "pass", "http_status": prometheus_status})

    grafana_status, grafana_body = _wait(f"{grafana_base}/api/health")
    grafana = json.loads(grafana_body)
    if str(grafana.get("database") or "").lower() != "ok":
        raise AssertionError(f"unexpected Grafana health payload: {grafana}")
    checks.append({"name": "grafana_health", "status": "pass", "http_status": grafana_status})

    completed_at = datetime.now(UTC)
    return {
        "status": "pass",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
        "checks": checks,
        "summary": {"pass": len(checks), "fail": 0},
    }


def main() -> int:
    print(json.dumps(run_ops_runtime_smoke(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
