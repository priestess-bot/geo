from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "tmp/full-project-lifecycle-smoke"
AUTO_PORTS_ENV = ROOT / "tmp/docker-compose.auto-ports.env"
ACTOR_HEADER = "X-GENO-Actor-Id"
CUSTOMER_PORTAL_HEADER = "X-GENO-Customer-Portal-Access"
ADMIN_ACTOR_ID = "runtime-console"
TEST_SECRET = "geno-full-lifecycle-secret-do-not-log"
LAST_STEPS: list["StepResult"] = []
LAST_CONTEXT: dict[str, Any] = {}


@dataclass(frozen=True)
class StepResult:
    name: str
    status: str
    detail: str
    data: dict[str, Any] | None = None
    duration_ms: int = 0


class SmokeFailure(RuntimeError):
    pass


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _read_auto_ports() -> dict[str, str]:
    if not AUTO_PORTS_ENV.exists():
        return {}
    values: dict[str, str] = {}
    for line in AUTO_PORTS_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _worker_env() -> dict[str, str]:
    env = os.environ.copy()
    ports = _read_auto_ports()
    postgres_port = ports.get("GENO_POSTGRES_HOST_PORT", "18000")
    minio_port = ports.get("GENO_MINIO_HOST_PORT", "18001")
    env.setdefault("DATABASE_URL", f"postgresql://geno_runtime_app:geno_runtime_app@localhost:{postgres_port}/geno")
    env.setdefault("OBJECT_STORE_ENDPOINT", f"http://localhost:{minio_port}")
    env.setdefault("OBJECT_STORE_BUCKET", "geno-reports")
    env.setdefault("OBJECT_STORE_ACCESS_KEY", "minio")
    env.setdefault("OBJECT_STORE_SECRET_KEY", "minio123")
    env.setdefault("OBJECT_STORE_REGION", "us-east-1")
    env.setdefault("PYTHONPATH", "packages/geno_core:apps/api")
    return env


def _docker_worker_container() -> str | None:
    configured = os.environ.get("GENO_FULL_LIFECYCLE_WORKER_CONTAINER", "").strip()
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for candidate in ("geno-auto-api-1", "geo-api-1", "geno-api-1", "api-1"):
        if candidate in names:
            return candidate
    return next((name for name in names if name.endswith("-api-1") or name == "api"), None)


def _run_fixture_worker(project_id: str) -> dict[str, Any]:
    worker_args = [
        "--mode",
        "fixture",
        "--project-id",
        project_id,
        "--prompt-limit",
        "1",
        "--cities",
        "Sydney",
        "--sample-size",
        "1",
        "--persist",
        "--persist-analysis",
    ]
    local_command = [sys.executable, str(ROOT / "workers/collector_worker/run_collection_slice.py"), *worker_args]
    result = subprocess.run(local_command, cwd=ROOT, env=_worker_env(), check=False, capture_output=True, text=True)
    runner = "host"
    if result.returncode != 0 and "psycopg is required" in result.stderr:
        container = _docker_worker_container()
        if container:
            docker_command = [
                "docker",
                "exec",
                container,
                "python",
                "workers/collector_worker/run_collection_slice.py",
                *worker_args,
            ]
            result = subprocess.run(docker_command, cwd=ROOT, check=False, capture_output=True, text=True)
            runner = f"docker:{container}"
    if result.returncode != 0:
        raise SmokeFailure(
            "fixture worker failed "
            f"(runner={runner}, exit={result.returncode}, stderr={result.stderr.strip()[:1200]}, stdout={result.stdout.strip()[:1200]})"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"fixture worker emitted invalid json (runner={runner}): {result.stdout[:1200]}") from exc
    payload["worker_runner"] = runner
    return payload


def _api_base(value: str | None) -> str:
    if value:
        return value.rstrip("/")
    env_value = os.environ.get("GENO_FULL_LIFECYCLE_API_BASE") or os.environ.get("NEXT_PUBLIC_API_BASE_URL")
    if env_value:
        return env_value.rstrip("/")
    ports = _read_auto_ports()
    return f"http://localhost:{ports.get('GENO_API_HOST_PORT', '18000')}"


def _headers(actor_id: str = ADMIN_ACTOR_ID, *, customer_portal: bool = False) -> dict[str, str]:
    headers = {ACTOR_HEADER: actor_id}
    if customer_portal:
        headers[CUSTOMER_PORTAL_HEADER] = "1"
    return headers


def _safe_json(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.text


def _compact_error(response: httpx.Response) -> str:
    payload = _safe_json(response)
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return str(payload)[:600]


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected: set[int] | None = None,
    actor_id: str = ADMIN_ACTOR_ID,
    customer_portal: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    expected = expected or {200}
    response = client.request(method, path, headers=_headers(actor_id, customer_portal=customer_portal), **kwargs)
    if response.status_code not in expected:
        raise SmokeFailure(f"{method} {path} returned {response.status_code}: {_compact_error(response)}")
    return response


def _record_step(results: list[StepResult], name: str, func, *, critical: bool = True) -> Any:
    started = time.monotonic()
    try:
        value = func()
    except Exception as exc:  # noqa: BLE001 - smoke runner must capture step-level blockers.
        duration = int((time.monotonic() - started) * 1000)
        result = StepResult(name=name, status="fail", detail=str(exc), duration_ms=duration)
        results.append(result)
        if critical:
            raise
        return None
    duration = int((time.monotonic() - started) * 1000)
    if isinstance(value, tuple):
        detail, data = value
    else:
        detail, data = "passed", value if isinstance(value, dict) else None
    results.append(StepResult(name=name, status="pass", detail=str(detail), data=data, duration_ms=duration))
    return value


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records", [])
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _first_record(payload: dict[str, Any], label: str) -> dict[str, Any]:
    records = _records(payload)
    if not records:
        raise SmokeFailure(f"Expected at least one {label} record")
    return records[0]


def _record_payload(record: dict[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    return value if isinstance(value, dict) else record


def _payload_id(payload: dict[str, Any], key: str = "id") -> str:
    for wrapper in (
        "project",
        "entity",
        "member",
        "invitation",
        "token",
        "report",
        "report_export",
        "report_export_job",
        "fidelity_check",
        "action_recommendation",
        "content_draft",
        "saved_view",
    ):
        nested = payload.get(wrapper)
        if isinstance(nested, dict) and nested.get(key):
            return str(nested[key])
    if payload.get(key):
        return str(payload[key])
    raise SmokeFailure(f"response did not include {key}: {payload}")


def _payload_field(payload: dict[str, Any], field: str, default: Any = None) -> Any:
    if field in payload:
        return payload[field]
    for wrapper in (
        "project",
        "entity",
        "member",
        "invitation",
        "token",
        "report",
        "report_export",
        "report_export_job",
        "fidelity_check",
        "action_recommendation",
        "content_draft",
        "saved_view",
    ):
        nested = payload.get(wrapper)
        if isinstance(nested, dict) and field in nested:
            return nested[field]
    return default


def _invitation_field(payload: dict[str, Any], field: str, default: Any = None) -> Any:
    if field in payload:
        return payload[field]
    invitation = payload.get("invitation")
    if isinstance(invitation, dict) and field in invitation:
        return invitation[field]
    return _payload_field(payload, field, default)


def _assert_no_secret(value: Any, *, context: str) -> None:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if TEST_SECRET in serialized:
        raise SmokeFailure(f"{context} leaked raw connector secret")


def _create_project_payload(stamp: str) -> dict[str, Any]:
    brand = f"LifecycleSmoke{stamp}"
    return {
        "tenant_name": f"GEO Lifecycle Tenant {stamp}",
        "project_name": f"{brand} Production Flow",
        "target_brand": brand,
        "category": "DTC home and wellness products",
        "competitors": ["BrightNest", "KoalaLab", "HarbourHome"],
        "brand_official_domains": [f"{brand.lower()}.example.com"],
        "brand_parent_company": "Lifecycle Smoke Holdings",
        "brand_product_lines": ["Air purifier", "Weighted blanket"],
        "owner_user_id": ADMIN_ACTOR_ID,
        "customer_email": f"customer+{stamp}@example.com",
        "competitor_domains": ["brightnest.example.com", "koalalab.example.com", "harbourhome.example.com"],
        "collection_mode": "api",
        "launch_status": "ready",
        "schedule": {"frequency": "weekly", "timezone": "Australia/Sydney", "prompt_limit": 10},
        "external_connectors": {
            "openai": {"enabled": True, "config_ref": "full-lifecycle-openai"},
            "perplexity": {"enabled": True, "config_ref": "full-lifecycle-perplexity"},
            "google_manual": {"enabled": True, "access_method": "manual_backfill"},
        },
        "create_customer_invitation": True,
    }


def _prompt_csv(brand: str) -> str:
    return "\n".join(
        [
            "text,intent_type,city,language,target_brand,competitors,priority,intent_weight,prompt_version,status",
            f"Which AU brands are best for healthier sleep?,category_recommendation,Sydney,en-AU,{brand},BrightNest|KoalaLab,1,1.0,lifecycle_smoke_v1,active",
            f"Is {brand} recommended for apartment air quality?,brand_consideration,Melbourne,en-AU,{brand},BrightNest|HarbourHome,2,0.8,lifecycle_smoke_v1,active",
        ]
    )


def _knowledge_csv(brand: str) -> str:
    return "\n".join(
        [
            "fact_type,subject,predicate,object_value,market_code,city,confidence,status",
            f"customer_support,{brand},supports_market,AU customer support and recyclable packaging,AU,Sydney,0.92,approved",
            f"warranty,{brand},publishes_policy,Warranty details for home wellness products,AU,Melbourne,0.88,approved",
        ]
    )


def _manual_backfill_csv(prompt_id: str, brand: str) -> str:
    return "\n".join(
        [
            "prompt_question_id,platform,surface,answer_text,citation_urls,screenshot_url,html_snapshot_url,answer_present,surface_triggered,sample_index,sample_size,device,notes",
            (
                f"{prompt_id},google,google_ai_mode,"
                f"\"{brand} is mentioned with BrightNest and cites official warranty material\","
                "\"https://example.com/warranty|https://example.com/support\","
                "s3://geno-smoke/google-screen.png,s3://geno-smoke/google-page.html,true,true,1,1,desktop,lifecycle smoke backfill"
            ),
        ]
    )


def _run(
    api_base: str,
    output_dir: Path,
    *,
    skip_secret_step: bool = False,
    skip_fixture_step: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    stamp = _now_stamp()
    steps: list[StepResult] = []
    context: dict[str, Any] = {"stamp": stamp}
    global LAST_CONTEXT, LAST_STEPS
    LAST_CONTEXT = context
    LAST_STEPS = steps
    output_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=api_base, timeout=60) as client:
        def health() -> tuple[str, dict[str, Any]]:
            response = _request(client, "GET", "/health", expected={200, 404})
            return f"api reachable with status {response.status_code}", {"status_code": response.status_code}

        _record_step(steps, "api_reachable", health)

        def create_project() -> tuple[str, dict[str, Any]]:
            payload = _create_project_payload(stamp)
            response = _request(client, "POST", "/v1/projects/runtime/au/dtc-ecommerce", json=payload)
            data = response.json()
            project_id = str(data["project_id"])
            context["project_id"] = project_id
            context["tenant_id"] = str(data["tenant_id"])
            context["brand"] = payload["target_brand"]
            context["customer_email"] = payload["customer_email"]
            initial_invitation = data.get("customer_invitation") if isinstance(data.get("customer_invitation"), dict) else {}
            context["initial_invitation_id"] = _invitation_field(initial_invitation, "id")
            context["initial_invite_token"] = _invitation_field(initial_invitation, "invite_token")
            if payload["create_customer_invitation"] and not context["initial_invitation_id"]:
                raise SmokeFailure(f"create project did not return initial customer invitation: {data}")
            if payload["create_customer_invitation"] and not context["initial_invite_token"]:
                raise SmokeFailure(f"create project did not return one-time initial invite token: {data}")
            if data.get("prompt_count", 0) < 1 or data.get("competitor_count", 0) < 3:
                raise SmokeFailure(f"unexpected bootstrap counts: {data}")
            return f"created project {project_id}", {
                "project_id": project_id,
                "tenant_id": context["tenant_id"],
                "prompt_count": data.get("prompt_count"),
                "competitor_count": data.get("competitor_count"),
                "has_invitation": bool(context.get("initial_invitation_id")),
                "initial_invitation_id": context.get("initial_invitation_id"),
                "initial_invite_token_present": bool(context.get("initial_invite_token")),
            }

        _record_step(steps, "create_project", create_project)
        project_id = str(context["project_id"])
        brand = str(context["brand"])

        def read_project() -> tuple[str, dict[str, Any]]:
            data = _request(client, "GET", "/v1/projects/runtime", params={"project_id": project_id}).json()
            record = _first_record(data, "project")
            project = _record_payload(record, "project")
            if project.get("id") != project_id:
                raise SmokeFailure(f"project lookup returned wrong project: {project}")
            if project.get("status") != "paused":
                raise SmokeFailure(f"runtime-created project should default to paused: {project}")
            return "project list/detail is persisted", {"name": project.get("name"), "status": project.get("status")}

        _record_step(steps, "read_project", read_project)

        def update_project() -> tuple[str, dict[str, Any]]:
            updated_name = f"{brand} Updated Flow"
            data = _request(
                client,
                "PATCH",
                "/v1/projects/runtime",
                json={
                    "project_id": project_id,
                    "name": updated_name,
                    "category": "DTC healthy home products",
                    "status": "configured",
                    "updated_by": ADMIN_ACTOR_ID,
                    "reason": "full_project_lifecycle_smoke_update",
                },
            ).json()
            project = _record_payload(data, "project")
            if project.get("name") != updated_name:
                raise SmokeFailure(f"project update did not persist name: {data}")
            return "project update persisted", {"name": project.get("name"), "status": project.get("status")}

        _record_step(steps, "update_project", update_project)

        def project_status_action_flow() -> tuple[str, dict[str, Any]]:
            activated = _request(
                client,
                "PATCH",
                "/v1/projects/runtime",
                json={
                    "project_id": project_id,
                    "name": f"{brand} Updated Flow",
                    "category": "DTC healthy home products",
                    "status": "active",
                    "updated_by": ADMIN_ACTOR_ID,
                    "reason": "full_project_lifecycle_smoke_activate",
                },
            ).json()
            paused = _request(
                client,
                "PATCH",
                "/v1/projects/runtime",
                json={
                    "project_id": project_id,
                    "name": f"{brand} Updated Flow",
                    "category": "DTC healthy home products",
                    "status": "paused",
                    "updated_by": ADMIN_ACTOR_ID,
                    "reason": "full_project_lifecycle_smoke_pause",
                },
            ).json()
            archived = _request(
                client,
                "POST",
                "/v1/projects/runtime/action",
                json={"project_id": project_id, "action": "archive", "updated_by": ADMIN_ACTOR_ID},
            ).json()
            restored = _request(
                client,
                "POST",
                "/v1/projects/runtime/action",
                json={"project_id": project_id, "action": "restore", "updated_by": ADMIN_ACTOR_ID},
            ).json()
            statuses = {
                "active": _payload_field(activated, "status"),
                "paused": _payload_field(paused, "status"),
                "archived": _payload_field(archived, "status"),
                "restored": _payload_field(restored, "status"),
            }
            expected = {"active": "active", "paused": "paused", "archived": "archived", "restored": "paused"}
            if statuses != expected:
                raise SmokeFailure(f"project status action flow mismatch: {statuses}")
            return "project status activate/pause/archive/restore checked", statuses

        _record_step(steps, "project_status_action_flow", project_status_action_flow)

        def lifecycle_actions() -> tuple[str, dict[str, Any]]:
            archived = _request(
                client,
                "POST",
                "/v1/projects/runtime/action",
                json={"project_id": project_id, "action": "archive", "updated_by": ADMIN_ACTOR_ID},
            ).json()
            restored = _request(
                client,
                "POST",
                "/v1/projects/runtime/action",
                json={"project_id": project_id, "action": "restore", "updated_by": ADMIN_ACTOR_ID},
            ).json()
            archived_project = _record_payload(archived, "project")
            restored_project = _record_payload(restored, "project")
            return "project archive/restore actions accepted", {
                "archive_status": archived_project.get("status"),
                "restore_status": restored_project.get("status"),
            }

        _record_step(steps, "project_lifecycle_pause_restore", lifecycle_actions)

        def invalid_lifecycle_action() -> tuple[str, dict[str, Any]]:
            response = _request(
                client,
                "POST",
                "/v1/projects/runtime/action",
                expected={400, 409},
                json={"project_id": project_id, "action": "not-a-real-action", "updated_by": ADMIN_ACTOR_ID},
            )
            return "invalid project action rejected", {"status_code": response.status_code, "detail": _compact_error(response)}

        _record_step(steps, "negative_invalid_project_action", invalid_lifecycle_action)

        def brand_and_competitors() -> tuple[str, dict[str, Any]]:
            brand_entity = _request(
                client,
                "POST",
                "/v1/project-entities/runtime/brand",
                json={
                    "project_id": project_id,
                    "canonical_name": brand,
                    "official_domains": [f"{brand.lower()}.example.com", "support.example.com"],
                    "parent_company": "Lifecycle Smoke Holdings",
                    "product_lines": ["Air purifier", "Weighted blanket", "Sleep bundle"],
                    "status": "active",
                    "updated_by": ADMIN_ACTOR_ID,
                },
            ).json()
            competitor = _request(
                client,
                "POST",
                "/v1/project-entities/runtime/competitors",
                json={
                    "project_id": project_id,
                    "canonical_name": "Lifecycle Challenger",
                    "official_domains": ["challenger.example.com"],
                    "product_lines": ["Home wellness"],
                    "status": "active",
                    "updated_by": ADMIN_ACTOR_ID,
                },
            ).json()
            competitor_id = _payload_id(competitor)
            paused = _request(
                client,
                "POST",
                "/v1/project-entities/runtime/competitors",
                json={
                    "project_id": project_id,
                    "competitor_id": competitor_id or None,
                    "canonical_name": "Lifecycle Challenger",
                    "official_domains": ["challenger.example.com"],
                    "product_lines": ["Home wellness"],
                    "status": "paused",
                    "updated_by": ADMIN_ACTOR_ID,
                },
            ).json()
            return "brand and competitor create/update persisted", {
                "brand_status": _payload_field(brand_entity, "status"),
                "competitor_id": _payload_id(paused),
                "competitor_status": _payload_field(paused, "status"),
            }

        _record_step(steps, "brand_competitor_crud", brand_and_competitors)

        def connector_secret() -> tuple[str, dict[str, Any]]:
            if skip_secret_step:
                return "connector secret step skipped by explicit debug flag", {"skipped": True}
            created = _request(
                client,
                "POST",
                "/v1/connectors/runtime/secrets",
                json={
                    "project_id": project_id,
                    "provider": "deepseek",
                    "purpose": "lifecycle_smoke",
                    "raw_secret": TEST_SECRET,
                    "metadata": {"model": "deepseek-v4-flash", "source": "full_project_lifecycle_smoke"},
                    "updated_by": ADMIN_ACTOR_ID,
                    "reason": "full_project_lifecycle_smoke_secret_create",
                },
            ).json()
            _assert_no_secret(created, context="connector secret create response")
            listed = _request(
                client,
                "GET",
                "/v1/connectors/runtime/secrets",
                params={"project_id": project_id, "provider": "deepseek", "include_inactive": "true"},
            ).json()
            _assert_no_secret(listed, context="connector secret list response")
            records = _records(listed)
            if not records:
                raise SmokeFailure("connector secret list returned no records")
            return "connector secret stored and masked", {"secret_records": len(records), "provider": records[0].get("provider")}

        _record_step(steps, "connector_secret_masking", connector_secret, critical=not skip_secret_step)

        def connector_test_launch_config() -> tuple[str, dict[str, Any]]:
            tested = _request(
                client,
                "POST",
                "/v1/connectors/runtime/test",
                json={
                    "project_id": project_id,
                    "provider": "openai",
                    "mode": "official_api",
                    "model": "deepseek-v4-flash",
                    "raw_secret": TEST_SECRET,
                    "tested_by": ADMIN_ACTOR_ID,
                    "reason": "full_project_lifecycle_smoke_connector_test",
                },
            ).json()
            _assert_no_secret(tested, context="connector test response")
            connector_test = tested.get("connector_test") if isinstance(tested.get("connector_test"), dict) else {}
            if connector_test.get("status") != "active":
                raise SmokeFailure(f"connector test did not mark DeepSeek fallback active: {tested}")
            secret_ref = str(connector_test.get("secret_ref") or "")
            if not secret_ref:
                raise SmokeFailure(f"connector test did not return secret_ref: {tested}")
            launch = _request(
                client,
                "POST",
                "/v1/project-launch-configs/runtime",
                json={
                    "project_id": project_id,
                    "customer_email": str(context["customer_email"]),
                    "primary_domain": f"{brand.lower()}.example.com",
                    "competitor_domains": ["brightnest.example.com", "koalalab.example.com", "harbourhome.example.com"],
                    "collection_mode": "api",
                    "schedule": {"frequency": "weekly", "timezone": "Australia/Sydney", "prompt_limit": 10},
                    "external_connectors": {
                        "openai": {
                            "status": connector_test.get("status"),
                            "mode": connector_test.get("mode"),
                            "model": connector_test.get("model"),
                            "secret_ref": secret_ref,
                        },
                        "perplexity": {"status": "not_configured", "mode": "official_api", "model": "sonar"},
                        "google_ai_mode": {"status": "manual_ready", "mode": "manual_backfill", "model": "google_ai_mode"},
                    },
                    "scoring_profile": "au_visibility_v1",
                    "status": "ready",
                    "created_by": ADMIN_ACTOR_ID,
                    "updated_by": ADMIN_ACTOR_ID,
                    "reason": "full_project_lifecycle_smoke_connector_test_launch_sync",
                },
            ).json()
            _assert_no_secret(launch, context="launch config after connector test")
            fetched = _request(
                client,
                "GET",
                "/v1/project-launch-configs/runtime",
                params={"project_id": project_id},
            ).json()
            _assert_no_secret(fetched, context="launch config fetch after connector test")
            launch_config = fetched.get("launch_config") if isinstance(fetched.get("launch_config"), dict) else fetched
            connectors = launch_config.get("external_connectors") if isinstance(launch_config.get("external_connectors"), dict) else {}
            openai = connectors.get("openai") if isinstance(connectors.get("openai"), dict) else {}
            if openai.get("status") != "active" or openai.get("secret_ref") != secret_ref:
                raise SmokeFailure(f"launch config did not persist tested connector state: {fetched}")
            return "connector test saved masked secret and launch config state", {
                "provider": connector_test.get("provider"),
                "status": connector_test.get("status"),
                "model": connector_test.get("model"),
                "secret_ref_present": bool(secret_ref),
            }

        _record_step(steps, "connector_test_launch_config", connector_test_launch_config)

        def member_crud() -> tuple[str, dict[str, Any]]:
            member_user_id = f"analyst-{stamp}@example.com"
            created = _request(
                client,
                "POST",
                "/v1/project-members/runtime",
                json={"project_id": project_id, "user_id": member_user_id, "role": "analyst", "updated_by": ADMIN_ACTOR_ID},
            ).json()
            listed = _request(client, "GET", "/v1/project-members/runtime", params={"project_id": project_id}).json()
            deleted = _request(
                client,
                "DELETE",
                "/v1/project-members/runtime",
                json={"project_id": project_id, "user_id": member_user_id, "deleted_by": ADMIN_ACTOR_ID},
            ).json()
            return "member create/list/delete accepted", {
                "created_role": _payload_field(created, "role"),
                "listed_total": listed.get("total_count"),
                "deleted_status": _payload_field(deleted, "status"),
            }

        _record_step(steps, "project_member_crud", member_crud)

        def invitation_flow() -> tuple[str, dict[str, Any]]:
            email = f"viewer+{stamp}@example.com"
            first = _request(
                client,
                "POST",
                "/v1/project-member-invitations/runtime",
                json={"project_id": project_id, "email": email, "role": "viewer", "invited_by": ADMIN_ACTOR_ID},
            ).json()
            first_id = _payload_id(first)
            first_token = str(first.get("invite_token") or _payload_field(first, "invite_token", ""))
            revoked = _request(
                client,
                "POST",
                "/v1/project-member-invitations/runtime/action",
                json={
                    "project_id": project_id,
                    "invitation_id": first_id,
                    "action": "revoke",
                    "updated_by": ADMIN_ACTOR_ID,
                },
            ).json()
            second = _request(
                client,
                "POST",
                "/v1/project-member-invitations/runtime",
                json={"project_id": project_id, "email": email, "role": "viewer", "invited_by": ADMIN_ACTOR_ID},
            ).json()
            bad_accept = _request(
                client,
                "POST",
                "/v1/auth/invitations/redeem",
                expected={400, 401, 404, 409},
                json={"invitation_id": first_id, "invite_token": first_token or "wrong-token"},
            )
            return "invitation revoke/regenerate and revoked-token negative path checked", {
                "first_status": _payload_field(revoked, "status"),
                "second_status": _payload_field(second, "status"),
                "revoked_redeem_status": bad_accept.status_code,
                "second_has_token": bool(second.get("invite_token") or _payload_field(second, "invite_token")),
            }

        _record_step(steps, "invitation_revoke_regenerate", invitation_flow)

        def prompt_import_and_update() -> tuple[str, dict[str, Any]]:
            before = _request(client, "GET", "/v1/prompts/runtime", params={"project_id": project_id, "limit": 10}).json()
            imported = _request(
                client,
                "POST",
                "/v1/prompts/runtime/import.csv",
                json={
                    "project_id": project_id,
                    "csv_content": _prompt_csv(brand),
                    "imported_by": ADMIN_ACTOR_ID,
                    "max_rows": 10,
                },
            ).json()
            after = _request(client, "GET", "/v1/prompts/runtime", params={"project_id": project_id, "limit": 10}).json()
            prompt = _first_record(after, "prompt")
            prompt_payload = _record_payload(prompt, "prompt")
            prompt_id = str(prompt_payload["id"])
            context["prompt_id"] = prompt_id
            updated = _request(
                client,
                "PATCH",
                "/v1/prompts/runtime",
                json={
                    "project_id": project_id,
                    "prompt_id": prompt_id,
                    "text": f"{prompt_payload.get('text', 'Prompt')} updated",
                    "intent_type": prompt_payload.get("intent_type") or "brand_awareness",
                    "city": prompt_payload.get("city") or "Sydney",
                    "language": prompt_payload.get("language") or "en-AU",
                    "target_brand": brand,
                    "competitors": ["BrightNest", "KoalaLab"],
                    "priority": 1,
                    "intent_weight": 1.0,
                    "prompt_version": "lifecycle_smoke_v1",
                    "status": "active",
                    "updated_by": ADMIN_ACTOR_ID,
                    "reason": "full_project_lifecycle_smoke_prompt_update",
                },
            ).json()
            exported = _request(client, "GET", "/v1/prompts/runtime/export.csv", params={"project_id": project_id})
            return "prompt import/update/export checked", {
                "before_total": before.get("total_count"),
                "after_total": after.get("total_count"),
                "import_count": (imported.get("prompt_import") or {}).get("prompt_count"),
                "updated_prompt_id": (updated.get("prompt") or {}).get("id"),
                "export_status": exported.status_code,
            }

        _record_step(steps, "prompt_import_update_export", prompt_import_and_update)

        def invalid_prompt_import() -> tuple[str, dict[str, Any]]:
            response = _request(
                client,
                "POST",
                "/v1/prompts/runtime/import.csv",
                expected={400},
                json={"project_id": project_id, "csv_content": "bad_column\nvalue", "imported_by": ADMIN_ACTOR_ID, "max_rows": 2},
            )
            return "invalid prompt csv rejected", {"status_code": response.status_code, "detail": _compact_error(response)}

        _record_step(steps, "negative_invalid_prompt_csv", invalid_prompt_import)

        def knowledge_import_search() -> tuple[str, dict[str, Any]]:
            imported = _request(
                client,
                "POST",
                "/v1/knowledge-facts/runtime/import.csv",
                json={
                    "project_id": project_id,
                    "csv_content": _knowledge_csv(brand),
                    "imported_by": ADMIN_ACTOR_ID,
                    "max_rows": 10,
                    "default_market_code": "AU",
                },
            ).json()
            searched = _request(
                client,
                "GET",
                "/v1/knowledge-facts/runtime/search",
                params={"project_id": project_id, "query": "warranty support", "market_code": "AU", "limit": 5},
            ).json()
            if int(searched.get("total_count", 0)) < 1:
                raise SmokeFailure(f"knowledge search returned no results: {searched}")
            knowledge_import = imported.get("knowledge_fact_import") if isinstance(imported.get("knowledge_fact_import"), dict) else {}
            import_count = int(
                imported.get("knowledge_fact_count")
                or imported.get("fact_count")
                or knowledge_import.get("knowledge_fact_count")
                or knowledge_import.get("fact_count")
                or 0
            )
            if import_count < 1:
                raise SmokeFailure(f"knowledge import returned no imported fact count: {imported}")
            return "knowledge import/search checked", {
                "import_count": import_count,
                "search_total": searched.get("total_count"),
            }

        _record_step(steps, "knowledge_import_search", knowledge_import_search)

        def invalid_knowledge_import() -> tuple[str, dict[str, Any]]:
            response = _request(
                client,
                "POST",
                "/v1/knowledge-facts/runtime/import.csv",
                expected={400},
                json={
                    "project_id": project_id,
                    "csv_content": "fact_text,source_url\nbad,bad",
                    "imported_by": ADMIN_ACTOR_ID,
                    "max_rows": 2,
                    "default_market_code": "AU",
                },
            )
            return "invalid knowledge csv rejected", {"status_code": response.status_code, "detail": _compact_error(response)}

        _record_step(steps, "negative_invalid_knowledge_csv", invalid_knowledge_import)

        def manual_backfill() -> tuple[str, dict[str, Any]]:
            prompt_id = str(context["prompt_id"])
            single = _request(
                client,
                "POST",
                "/v1/evidence-runs/runtime/manual-backfill",
                json={
                    "prompt_question_id": prompt_id,
                    "platform": "google",
                    "surface": "google_ai_mode",
                    "answer_text": f"{brand} is recommended alongside BrightNest with source citations.",
                    "citation_urls": ["https://example.com/support", "https://example.com/warranty"],
                    "screenshot_url": "s3://geno-smoke/single-screen.png",
                    "html_snapshot_url": "s3://geno-smoke/single-page.html",
                    "answer_present": True,
                    "surface_triggered": True,
                    "sample_index": 1,
                    "sample_size": 1,
                    "device": "desktop",
                    "notes": "single manual backfill smoke",
                },
            ).json()
            batch = _request(
                client,
                "POST",
                "/v1/evidence-runs/runtime/manual-backfill/import.csv",
                json={
                    "project_id": project_id,
                    "csv_content": _manual_backfill_csv(prompt_id, brand),
                    "submitted_by": ADMIN_ACTOR_ID,
                    "notes": "csv manual backfill smoke",
                    "max_rows": 5,
                },
            ).json()
            return "manual backfill single/csv checked", {
                "single_answer_run_id": single.get("answer_run_id"),
                "batch_imported_count": batch.get("imported_count"),
                "batch_evidence_asset_count": batch.get("evidence_asset_count"),
            }

        _record_step(steps, "manual_backfill_single_csv", manual_backfill)

        def invalid_manual_backfill() -> tuple[str, dict[str, Any]]:
            response = _request(
                client,
                "POST",
                "/v1/evidence-runs/runtime/manual-backfill",
                expected={404},
                json={
                    "prompt_question_id": "00000000-0000-0000-0000-000000000000",
                    "platform": "google",
                    "surface": "google_ai_mode",
                    "answer_text": "bad prompt",
                },
            )
            return "manual backfill with missing prompt rejected", {"status_code": response.status_code}

        _record_step(steps, "negative_manual_backfill_missing_prompt", invalid_manual_backfill)

        def fixture_collection() -> tuple[str, dict[str, Any]]:
            if skip_fixture_step:
                return "fixture collection step skipped by explicit debug flag", {"skipped": True}
            data = _run_fixture_worker(project_id)
            if int(data.get("success_count", 0)) < 1:
                raise SmokeFailure(f"fixture collection produced no successes: {data}")
            return "fixture collection persisted analysis", {
                "record_count": data.get("record_count"),
                "success_count": data.get("success_count"),
                "failure_count": data.get("failure_count"),
                "worker_runner": data.get("worker_runner"),
            }

        _record_step(steps, "fixture_collection_analysis_scoring", fixture_collection, critical=not skip_fixture_step)

        def runtime_outputs() -> tuple[str, dict[str, Any]]:
            endpoints = {
                "collection_runs": "/v1/collection-runs/runtime",
                "evidence_runs": "/v1/evidence-runs/runtime",
                "visibility_scores": "/v1/visibility-scores/runtime",
                "reports": "/v1/reports/runtime",
                "traceability": "/v1/traceability/runtime",
                "action_plans": "/v1/action-plans/runtime",
                "content_engines": "/v1/content-engines/runtime",
            }
            totals: dict[str, int] = {}
            statuses: dict[str, int] = {}
            first_records: dict[str, dict[str, Any]] = {}
            for name, path in endpoints.items():
                response = _request(
                    client,
                    "GET",
                    path,
                    expected={200, 404},
                    params={"project_id": project_id, "limit": 10},
                )
                statuses[name] = response.status_code
                if response.status_code == 404:
                    totals[name] = 0
                    continue
                data = response.json()
                if name == "traceability":
                    bundle = data.get("traceability_bundle") if isinstance(data, dict) else None
                    totals[name] = 1 if isinstance(bundle, dict) and bundle.get("id") else 0
                    if isinstance(bundle, dict):
                        first_records[name] = bundle
                    continue
                totals[name] = int(data.get("total_count", len(_records(data))) or 0)
                records = _records(data)
                if records:
                    first_records[name] = records[0]
            required = ["collection_runs", "evidence_runs", "visibility_scores", "reports", "traceability", "action_plans"]
            missing = [name for name in required if totals.get(name, 0) < 1]
            if missing:
                raise SmokeFailure(f"missing runtime outputs: {missing}; totals={totals}; statuses={statuses}")
            context["report_export_id"] = _payload_id(first_records["reports"])
            action_record = first_records["action_plans"]
            recommendations = action_record.get("action_recommendations")
            if isinstance(recommendations, list) and recommendations and isinstance(recommendations[0], dict):
                context["action_id"] = _payload_id(recommendations[0])
            else:
                context["action_id"] = _payload_id(action_record)
            if "content_engines" in first_records:
                try:
                    context["content_draft_id"] = _payload_id(first_records["content_engines"])
                except SmokeFailure:
                    context["content_draft_id"] = ""
            return "runtime output records exist", {"totals": totals, "statuses": statuses}

        _record_step(steps, "runtime_outputs_exist", runtime_outputs)

        def report_lifecycle() -> tuple[str, dict[str, Any]]:
            report_id = str(context["report_export_id"])
            unpublished = _request(
                client,
                "GET",
                f"/v1/reports/runtime/{report_id}/artifact",
                expected={403, 404},
                customer_portal=True,
                params={"type": "markdown"},
            )
            published = _request(
                client,
                "POST",
                f"/v1/reports/runtime/{report_id}/management-events",
                json={"status": "published", "updated_by": ADMIN_ACTOR_ID, "note": "lifecycle smoke publish"},
            ).json()
            markdown = _request(
                client,
                "GET",
                f"/v1/reports/runtime/{report_id}/artifact",
                customer_portal=True,
                params={"type": "markdown"},
            )
            csv_artifact = _request(
                client,
                "GET",
                f"/v1/reports/runtime/{report_id}/artifact",
                customer_portal=True,
                params={"type": "csv"},
            )
            pdf_artifact = _request(
                client,
                "GET",
                f"/v1/reports/runtime/{report_id}/artifact",
                customer_portal=True,
                params={"type": "pdf"},
            )
            revoked = _request(
                client,
                "POST",
                f"/v1/reports/runtime/{report_id}/management-events",
                json={"status": "revoked", "updated_by": ADMIN_ACTOR_ID, "note": "lifecycle smoke revoke"},
            ).json()
            denied = _request(
                client,
                "GET",
                f"/v1/reports/runtime/{report_id}/artifact",
                expected={403, 404},
                customer_portal=True,
                params={"type": "markdown"},
            )
            return "report publish/download/revoke checked", {
                "unpublished_customer_status": unpublished.status_code,
                "published_status": published.get("management_status") or published.get("status"),
                "markdown_bytes": len(markdown.content),
                "csv_bytes": len(csv_artifact.content),
                "pdf_bytes": len(pdf_artifact.content),
                "revoked_status": revoked.get("management_status") or revoked.get("status"),
                "revoked_customer_status": denied.status_code,
            }

        _record_step(steps, "report_publish_download_revoke", report_lifecycle)

        def report_job_and_fidelity() -> tuple[str, dict[str, Any]]:
            report_id = str(context["report_export_id"])
            job = _request(
                client,
                "POST",
                "/v1/report-export-jobs/runtime",
                json={
                    "project_id": project_id,
                    "report_export_id": report_id,
                    "artifact_type": "pdf",
                    "template": "standard",
                    "requested_by": ADMIN_ACTOR_ID,
                    "reason": "full_project_lifecycle_smoke_job",
                },
            ).json()
            job_id = _payload_id(job)
            updated = _request(
                client,
                "POST",
                f"/v1/report-export-jobs/runtime/{job_id}/status",
                json={
                    "status": "succeeded",
                    "updated_by": ADMIN_ACTOR_ID,
                    "report_export_id": report_id,
                    "artifact_url": f"s3://geno-smoke/reports/{report_id}.pdf",
                },
            ).json()
            fidelity = _request(
                client,
                "POST",
                "/v1/fidelity-checks/runtime",
                json={"project_id": project_id, "report_export_id": report_id, "checked_by": ADMIN_ACTOR_ID},
            ).json()
            return "report job lifecycle and fidelity check accepted", {
                "job_id": job_id,
                "job_status": updated.get("status"),
                "fidelity_id": fidelity.get("id") or fidelity.get("fidelity_check_id"),
            }

        _record_step(steps, "report_job_fidelity", report_job_and_fidelity)

        def action_update() -> tuple[str, dict[str, Any]]:
            action_id = str(context["action_id"])
            data = _request(
                client,
                "PATCH",
                f"/v1/action-plans/runtime/{action_id}",
                json={
                    "project_id": project_id,
                    "status": "in_progress",
                    "owner_id": "delivery-owner",
                    "customer_visible": True,
                    "visibility_note": "Visible for lifecycle smoke validation",
                    "updated_by": ADMIN_ACTOR_ID,
                },
            ).json()
            return "action recommendation update accepted", {
                "action_id": action_id,
                "status": data.get("status"),
                "customer_visible": data.get("customer_visible"),
            }

        _record_step(steps, "action_plan_update", action_update)

        def content_review_optional() -> tuple[str, dict[str, Any]]:
            content_draft_id = str(context.get("content_draft_id") or "")
            if not content_draft_id:
                return "no content draft generated; optional review skipped", {"skipped": True}
            data = _request(
                client,
                "PATCH",
                f"/v1/content-drafts/runtime/{content_draft_id}/review",
                json={
                    "project_id": project_id,
                    "review_status": "approved",
                    "reviewer_id": ADMIN_ACTOR_ID,
                    "decision": "approved by full lifecycle smoke",
                    "notes": "optional content review branch",
                    "payload": {"source": "full_project_lifecycle_smoke"},
                },
            ).json()
            return "content draft review accepted", {"content_draft_id": content_draft_id, "status": data.get("review_status")}

        _record_step(steps, "content_review_optional", content_review_optional, critical=False)

        def saved_view_alerts_exports() -> tuple[str, dict[str, Any]]:
            saved = _request(
                client,
                "POST",
                "/v1/runtime-saved-views",
                json={
                    "project_id": project_id,
                    "name": "Full lifecycle smoke view",
                    "view_type": "project_status",
                    "filters": {"tab": "status"},
                    "query_path": f"/v1/projects/runtime?project_id={project_id}",
                    "export_path": f"/v1/audit-events/runtime/export.csv?project_id={project_id}",
                    "created_by": ADMIN_ACTOR_ID,
                },
            ).json()
            alerts = _request(client, "GET", "/v1/runtime-alerts", params={"project_id": project_id}).json()
            audit = _request(client, "GET", "/v1/audit-events/runtime", params={"project_id": project_id, "limit": 20}).json()
            lifecycle_csv = _request(
                client,
                "GET",
                "/v1/projects/runtime/lifecycle-events/export.csv",
                params={"project_id": project_id},
            )
            audit_csv = _request(client, "GET", "/v1/audit-events/runtime/export.csv", params={"project_id": project_id})
            return "saved view, alerts and audit exports checked", {
                "saved_view_id": _payload_id(saved),
                "alert_total": alerts.get("total_count"),
                "audit_total": audit.get("total_count"),
                "lifecycle_export_status": lifecycle_csv.status_code,
                "audit_export_status": audit_csv.status_code,
            }

        _record_step(steps, "ops_views_audit_exports", saved_view_alerts_exports)

        def cross_project_negative() -> tuple[str, dict[str, Any]]:
            payload = _create_project_payload(f"{stamp}x")
            payload["project_name"] = f"{brand} Isolated Negative"
            payload["target_brand"] = f"{brand}Isolated"
            payload["customer_email"] = f"isolated+{stamp}@example.com"
            other = _request(client, "POST", "/v1/projects/runtime/au/dtc-ecommerce", json=payload).json()
            other_project_id = str(other["project_id"])
            prompt_id = str(context["prompt_id"])
            response = _request(
                client,
                "POST",
                "/v1/evidence-runs/runtime/manual-backfill/import.csv",
                expected={400, 404},
                json={
                    "project_id": other_project_id,
                    "csv_content": _manual_backfill_csv(prompt_id, brand),
                    "submitted_by": ADMIN_ACTOR_ID,
                    "max_rows": 2,
                },
            )
            return "cross-project prompt backfill rejected", {
                "other_project_id": other_project_id,
                "status_code": response.status_code,
                "detail": _compact_error(response),
            }

        _record_step(steps, "negative_cross_project_backfill", cross_project_negative)

    failed = [step for step in steps if step.status == "fail"]
    report = {
        "status": "failed" if failed else "passed",
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "api_base": api_base,
        "project_id": context.get("project_id"),
        "tenant_id": context.get("tenant_id"),
        "steps": [asdict(step) for step in steps],
        "summary": {
            "pass": sum(1 for step in steps if step.status == "pass"),
            "fail": len(failed),
        },
    }
    latest_path = output_dir / "latest.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a full runtime project lifecycle smoke from project creation.")
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--skip-secret-step",
        action="store_true",
        help="Debug only: skip connector secret storage so later lifecycle branches can be explored.",
    )
    parser.add_argument(
        "--skip-fixture-step",
        action="store_true",
        help="Debug only: skip developer-only fixture collection so later lifecycle branches can be explored.",
    )
    args = parser.parse_args()

    api_base = _api_base(args.api_base)
    output_dir = Path(args.output_dir)
    try:
        report = _run(
            api_base=api_base,
            output_dir=output_dir,
            skip_secret_step=args.skip_secret_step,
            skip_fixture_step=args.skip_fixture_step,
        )
    except Exception as exc:  # noqa: BLE001 - CLI must emit a durable failure artifact.
        output_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "status": "failed",
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "api_base": api_base,
            "project_id": LAST_CONTEXT.get("project_id"),
            "error": str(exc),
            "steps": [asdict(step) for step in LAST_STEPS],
            "summary": {
                "pass": sum(1 for step in LAST_STEPS if step.status == "pass"),
                "fail": sum(1 for step in LAST_STEPS if step.status == "fail"),
            },
        }
        (output_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
