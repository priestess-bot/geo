from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(name: str, condition: bool, detail: str) -> dict[str, str]:
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    return {"name": name, "status": "pass", "detail": detail}


def build_ops_smoke_report() -> dict[str, object]:
    compose = _read("infra/docker-compose.yml")
    prometheus = _read("infra/prometheus/prometheus.yml")
    grafana = _read("infra/grafana/provisioning/datasources/prometheus.yml")
    ops_routes = _read("apps/api/geno_api/ops_routes.py")
    metrics = _read("apps/api/geno_api/runtime_metrics.py")
    api_main = _read("apps/api/geno_api/main.py")
    makefile = _read("Makefile")
    runtime_smoke = _read("scripts/run_ops_runtime_smoke.py")

    checks = [
        _require("health_endpoint", '@router.get("/health")' in ops_routes, "health endpoint is registered"),
        _require("ready_endpoint", '@router.get("/ready")' in ops_routes, "readiness endpoint is registered"),
        _require("metrics_endpoint", '@router.get("/metrics")' in ops_routes, "Prometheus metrics endpoint is registered"),
        _require("metrics_middleware", "runtime_metrics_middleware" in api_main, "API observes request metrics"),
        _require("prometheus_scrapes_api", "metrics_path: /metrics" in prometheus and "api:8000" in prometheus, "Prometheus scrapes API metrics"),
        _require("grafana_datasource", "http://prometheus:9090" in grafana, "Grafana datasource points at Prometheus"),
        _require("observability_profile", "- observability" in compose and "prom/prometheus" in compose and "grafana/grafana" in compose, "Compose observability profile exists"),
        _require("alert_api", "/v1/runtime-alerts" in api_main, "Runtime alert API exists"),
        _require("alert_workers", "runtime-alert-notification-worker" in compose and "runtime-alert-escalation-worker" in compose, "Alert notification/escalation workers are configured"),
        _require("ops_make_target", "ops-smoke:" in makefile and "scripts/verify_ops_smoke.py" in makefile, "Makefile runs executable ops smoke"),
        _require("metrics_pool_gauge", "geno_runtime_postgres_pool_snapshot_ok" in metrics, "Metrics expose runtime DB pool health"),
        _require("runtime_smoke_service", "ops-runtime-smoke:" in compose and "run_ops_runtime_smoke.py" in compose, "Compose can execute the runtime observability probe"),
        _require("runtime_smoke_endpoints", all(value in runtime_smoke for value in ("/health", "/ready", "/metrics", "/api/v1/targets", "/api/health")), "Runtime probe calls API, Prometheus and Grafana"),
        _require("runtime_smoke_make_target", "run --rm ops-runtime-smoke" in makefile, "Makefile requires the runtime observability probe"),
    ]
    return {"status": "pass", "checks": checks, "summary": {"pass": len(checks), "fail": 0}}


def main() -> int:
    print(json.dumps(build_ops_smoke_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
