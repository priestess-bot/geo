#!/usr/bin/env python3
"""Configure the pinned local Dify runtime and publish GEO Workflows.

The command is intentionally limited to Dify's public console API. It keeps
the generated administrator password and application API tokens in one local,
Git-ignored 0600 state file and never prints either value.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import Any, Mapping

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:15000"
DEFAULT_STATE_FILE = Path(".runtime/geo-dify-state.json")
DEFAULT_MANIFEST = Path("infra/dify/workflows/manifest.json")
DEFAULT_DEEPSEEK_KEY_FILE = Path("deepseek_api_key.txt")
DEEPSEEK_PLUGIN = (
    "langgenius/deepseek:0.0.19@"
    "5b68617c637b62d31e7f33a9f5677b76e88f81868fb04a728e208588564b72ea"
)
DEEPSEEK_PROVIDER = "langgenius/deepseek/deepseek"
TERMINAL_PLUGIN_STATES = frozenset({"success", "failed"})


class DifyConfigurationError(RuntimeError):
    """An actionable Dify bootstrap failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--deepseek-api-key-file", type=Path, default=DEFAULT_DEEPSEEK_KEY_FILE
    )
    parser.add_argument("--admin-email", default="geo-dify-admin@local.invalid")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--readiness-seconds", type=float, default=180.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        state_file = args.state_file.resolve()
        state = _load_or_create_state(state_file, admin_email=args.admin_email)
        manifest_path = args.manifest.resolve()
        manifest = _load_manifest(manifest_path)
        deepseek_key = _read_secret(args.deepseek_api_key_file.resolve(), "DeepSeek API key")
        try:
            with httpx.Client(
                base_url=args.base_url.rstrip("/"),
                timeout=args.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                result = configure_runtime(
                    client,
                    state=state,
                    state_file=state_file,
                    manifest=manifest,
                    manifest_dir=manifest_path.parent,
                    deepseek_api_key=deepseek_key,
                    readiness_seconds=args.readiness_seconds,
                )
        finally:
            del deepseek_key
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (DifyConfigurationError, OSError, ValueError, httpx.HTTPError) as exc:
        print(f"Dify configuration failed: {exc}", file=sys.stderr)
        return 1


def configure_runtime(
    client: httpx.Client,
    *,
    state: dict[str, Any],
    state_file: Path,
    manifest: Mapping[str, Any],
    manifest_dir: Path,
    deepseek_api_key: str,
    readiness_seconds: float,
) -> Mapping[str, object]:
    _wait_until_ready(client, readiness_seconds=readiness_seconds)
    _setup_if_needed(client, state)
    _login(client, state)
    _install_deepseek(client)
    _configure_deepseek(client, deepseek_api_key)

    configured: list[Mapping[str, str]] = []
    workflows = state.setdefault("workflows", {})
    if not isinstance(workflows, dict):
        raise DifyConfigurationError("local Dify state has an invalid workflows object")
    for item in _manifest_workflows(manifest):
        purpose = str(item["purpose"])
        dsl_path = (manifest_dir / str(item["file"])).resolve()
        dsl = dsl_path.read_text(encoding="utf-8")
        dsl_hash = hashlib.sha256(dsl.encode()).hexdigest()
        if dsl_hash != item["sha256"]:
            raise DifyConfigurationError(
                f"{dsl_path} does not match its frozen manifest hash; regenerate the DSLs"
            )
        previous = workflows.get(purpose)
        record = _ensure_workflow(
            client,
            purpose=purpose,
            dsl=dsl,
            dsl_hash=dsl_hash,
            previous=previous if isinstance(previous, Mapping) else None,
        )
        workflows[purpose] = record
        _write_private_json(state_file, state)
        configured.append(
            {
                "purpose": purpose,
                "app_id": str(record["app_id"]),
                "workflow_id": str(record["workflow_id"]),
                "dsl_hash": dsl_hash,
            }
        )
    state["schema_version"] = 1
    state["dify_version"] = manifest["dify_version"]
    _write_private_json(state_file, state)
    return {
        "status": "configured",
        "dify_version": manifest["dify_version"],
        "state_file": str(state_file),
        "workflows": configured,
    }


def _wait_until_ready(client: httpx.Client, *, readiness_seconds: float) -> None:
    if readiness_seconds <= 0:
        raise ValueError("readiness timeout must be positive")
    deadline = time.monotonic() + readiness_seconds
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            response = client.get("/console/api/setup")
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = exc.__class__.__name__
        time.sleep(1)
    raise DifyConfigurationError(
        f"Dify did not become ready within {readiness_seconds:g}s ({last_error}); "
        "check ./scripts/bootstrap_dify_runtime.sh status and container logs"
    )


def _setup_if_needed(client: httpx.Client, state: Mapping[str, Any]) -> None:
    setup = _json_response(client.get("/console/api/setup"), "read Dify setup status")
    step = setup.get("step")
    if step == "finished":
        return
    if step != "not_started":
        raise DifyConfigurationError(f"Dify returned an unknown setup state: {step!r}")
    response = client.post(
        "/console/api/setup",
        json={
            "email": state["admin_email"],
            "name": "GEO Operator",
            "password": state["admin_password"],
            "language": "zh-Hans",
        },
    )
    _json_response(response, "create the local Dify administrator", expected=(201,))


def _login(client: httpx.Client, state: Mapping[str, Any]) -> None:
    encoded = base64.b64encode(str(state["admin_password"]).encode()).decode()
    response = client.post(
        "/console/api/login",
        json={
            "email": state["admin_email"],
            "password": encoded,
            "remember_me": False,
        },
    )
    body = _json_response(response, "log in to the local Dify console")
    if body.get("result") != "success":
        raise DifyConfigurationError("Dify login did not return success")
    csrf = client.cookies.get("csrf_token") or client.cookies.get("__Host-csrf_token")
    if not csrf:
        raise DifyConfigurationError("Dify login did not issue a CSRF cookie")
    client.headers["X-CSRF-Token"] = csrf


def _install_deepseek(client: httpx.Client) -> None:
    response = client.post(
        "/console/api/workspaces/current/plugin/install/marketplace",
        json={"plugin_unique_identifiers": [DEEPSEEK_PLUGIN]},
    )
    result = _json_response(response, "install the pinned DeepSeek plugin")
    if result.get("all_installed") is True:
        return
    task_id = str(result.get("task_id") or "").strip()
    if not task_id:
        raise DifyConfigurationError("DeepSeek plugin install returned no task ID")
    for _ in range(120):
        body = _json_response(
            client.get(f"/console/api/workspaces/current/plugin/tasks/{task_id}"),
            "read DeepSeek plugin installation status",
        )
        task = body.get("task")
        status = task.get("status") if isinstance(task, Mapping) else None
        if status == "success":
            return
        if status == "failed":
            failures = task.get("plugins") if isinstance(task, Mapping) else None
            raise DifyConfigurationError(
                f"DeepSeek plugin installation failed: {_safe_failure(failures)}"
            )
        time.sleep(1)
    raise DifyConfigurationError("DeepSeek plugin installation did not finish within 120s")


def _configure_deepseek(client: httpx.Client, api_key: str) -> None:
    path = f"/console/api/workspaces/current/model-providers/{DEEPSEEK_PROVIDER}/credentials"
    existing = _json_response(client.get(path), "read DeepSeek provider credentials")
    if existing.get("credentials"):
        return
    _json_response(
        client.post(
            path,
            json={"credentials": {"api_key": api_key}, "name": "GEO DeepSeek"},
        ),
        "validate and store the DeepSeek provider credential",
        expected=(201,),
    )


def _ensure_workflow(
    client: httpx.Client,
    *,
    purpose: str,
    dsl: str,
    dsl_hash: str,
    previous: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if previous and previous.get("dsl_hash") == dsl_hash:
        verified = _verify_existing_workflow(client, previous)
        if verified is not None:
            return verified

    payload: dict[str, object] = {"mode": "yaml-content", "yaml_content": dsl}
    if previous and previous.get("app_id"):
        payload["app_id"] = previous["app_id"]
    imported = _json_response(
        client.post("/console/api/apps/imports", json=payload),
        f"import {purpose}",
        expected=(200, 202),
    )
    if imported.get("status") == "pending":
        import_id = str(imported.get("id") or "").strip()
        if not import_id:
            raise DifyConfigurationError(f"{purpose} import is pending without an import ID")
        imported = _json_response(
            client.post(f"/console/api/apps/imports/{import_id}/confirm", json={}),
            f"confirm {purpose} import",
        )
    if imported.get("status") not in {"completed", "completed-with-warnings"}:
        raise DifyConfigurationError(
            f"{purpose} import failed: {_safe_failure(imported.get('error'))}"
        )
    app_id = str(imported.get("app_id") or "").strip()
    if not app_id:
        raise DifyConfigurationError(f"{purpose} import returned no app ID")
    _json_response(
        client.post(
            f"/console/api/apps/{app_id}/workflows/publish",
            json={"marked_name": "GEO v1", "marked_comment": "GEO frozen DSL import"},
        ),
        f"publish {purpose}",
    )
    published = _json_response(
        client.get(f"/console/api/apps/{app_id}/workflows/publish"),
        f"read published {purpose}",
    )
    workflow_id = str(published.get("id") or "").strip()
    if not workflow_id:
        raise DifyConfigurationError(f"published {purpose} returned no Workflow ID")
    api_token = _application_token(client, app_id, previous=previous)
    record: dict[str, Any] = {
        "purpose": purpose,
        "app_id": app_id,
        "workflow_id": workflow_id,
        "workflow_hash": str(published.get("hash") or "").strip(),
        "dsl_hash": dsl_hash,
        "api_token": api_token,
        "prompt_source": "dify",
    }
    for key in ("geo_secret", "geo_release_id"):
        if previous and key in previous:
            record[key] = previous[key]
    return record


def _verify_existing_workflow(
    client: httpx.Client, previous: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    app_id = str(previous.get("app_id") or "").strip()
    workflow_id = str(previous.get("workflow_id") or "").strip()
    token = str(previous.get("api_token") or "").strip()
    if not app_id or not workflow_id or not token:
        return None
    response = client.get(f"/console/api/apps/{app_id}/workflows/publish")
    if response.status_code == 404:
        return None
    published = _json_response(response, f"verify existing {previous.get('purpose')} Workflow")
    if str(published.get("id") or "") != workflow_id:
        return None
    keys = _json_response(
        client.get(f"/console/api/apps/{app_id}/api-keys"),
        f"verify existing {previous.get('purpose')} API key",
    )
    rows = keys.get("data")
    if not isinstance(rows, list) or not any(
        isinstance(item, Mapping) and item.get("token") == token for item in rows
    ):
        return None
    verified: dict[str, Any] = {
        "purpose": str(previous["purpose"]),
        "app_id": app_id,
        "workflow_id": workflow_id,
        "dsl_hash": str(previous["dsl_hash"]),
        "api_token": token,
    }
    verified["workflow_hash"] = str(published.get("hash") or "").strip()
    verified["prompt_source"] = str(previous.get("prompt_source") or "dify")
    for key in ("geo_secret", "geo_release_id"):
        if key in previous:
            verified[key] = previous[key]
    return verified


def _application_token(
    client: httpx.Client, app_id: str, *, previous: Mapping[str, Any] | None
) -> str:
    keys = _json_response(
        client.get(f"/console/api/apps/{app_id}/api-keys"), "read Dify application keys"
    )
    rows = keys.get("data")
    previous_token = str((previous or {}).get("api_token") or "")
    if isinstance(rows, list):
        if previous_token and any(
            isinstance(item, Mapping) and item.get("token") == previous_token
            for item in rows
        ):
            return previous_token
        for item in rows:
            if isinstance(item, Mapping) and str(item.get("token") or "").strip():
                return str(item["token"])
    created = _json_response(
        client.post(f"/console/api/apps/{app_id}/api-keys", json={}),
        "create Dify application key",
        expected=(201,),
    )
    token = str(created.get("token") or "").strip()
    if not token:
        raise DifyConfigurationError("Dify created an application key without a token")
    return token


def _load_or_create_state(path: Path, *, admin_email: str) -> dict[str, Any]:
    if path.exists():
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise DifyConfigurationError(f"{path} must not be accessible by group or other users")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise DifyConfigurationError("local Dify state must be a JSON object")
        if not value.get("admin_email") or not value.get("admin_password"):
            raise DifyConfigurationError("local Dify state is missing administrator credentials")
        return value
    email = admin_email.strip().lower()
    if "@" not in email:
        raise ValueError("Dify administrator email is invalid")
    state: dict[str, Any] = {
        "schema_version": 1,
        "admin_email": email,
        "admin_password": f"{secrets.token_urlsafe(24)}A1",
        "workflows": {},
    }
    _write_private_json(path, state)
    return state


def _load_manifest(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or value.get("dify_version") != "1.16.0":
        raise DifyConfigurationError("Dify Workflow manifest must target version 1.16.0")
    return value


def _manifest_workflows(manifest: Mapping[str, Any]) -> tuple[Mapping[str, str], ...]:
    rows = manifest.get("workflows")
    if not isinstance(rows, list) or len(rows) != 4:
        raise DifyConfigurationError("Dify Workflow manifest must contain exactly four flows")
    result: list[Mapping[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise DifyConfigurationError("Dify Workflow manifest item must be an object")
        required = ("purpose", "file", "sha256")
        if not all(isinstance(row.get(key), str) and row[key] for key in required):
            raise DifyConfigurationError("Dify Workflow manifest item is incomplete")
        result.append({key: str(row[key]) for key in required})
    return tuple(result)


def _read_secret(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise DifyConfigurationError(f"{label} file is missing or is a symbolic link: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise DifyConfigurationError(f"{label} file is empty: {path}")
    return value


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _json_response(
    response: httpx.Response, action: str, *, expected: tuple[int, ...] = (200,)
) -> Mapping[str, Any]:
    if response.status_code not in expected:
        detail = _safe_failure(_response_body(response))
        raise DifyConfigurationError(
            f"could not {action}: HTTP {response.status_code}; {detail}"
        )
    try:
        value = response.json()
    except ValueError as exc:
        raise DifyConfigurationError(f"could not {action}: response was not JSON") from exc
    if not isinstance(value, Mapping):
        raise DifyConfigurationError(f"could not {action}: response was not an object")
    return value


def _response_body(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


def _safe_failure(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text.replace("\n", " ")[:500] or "no error detail"


if __name__ == "__main__":
    raise SystemExit(main())
