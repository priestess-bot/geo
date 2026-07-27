from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx

from scripts.configure_dify_runtime import configure_runtime


PURPOSES = (
    "knowledge.question_generation",
    "knowledge.rag_grounding",
    "placements.generation",
    "placements.simulation",
)


class DifyConsoleStub:
    def __init__(self, *, password: str) -> None:
        self.password = password
        self.setup_finished = False
        self.credentials_configured = False
        self.apps: dict[str, dict[str, str]] = {}
        self.mutations: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        body = json.loads(request.content) if request.content else {}
        if method == "GET" and path == "/console/api/setup":
            return self._json(200, {"step": "finished" if self.setup_finished else "not_started"})
        if method == "POST" and path == "/console/api/setup":
            assert body["language"] == "zh-Hans"
            assert body["password"] == self.password
            self.setup_finished = True
            self.mutations.append("setup")
            return self._json(201, {"result": "success"})
        if method == "POST" and path == "/console/api/login":
            assert base64.b64decode(body["password"]).decode() == self.password
            return self._json(
                200,
                {"result": "success"},
                headers=[
                    ("set-cookie", "access_token=access; Path=/"),
                    ("set-cookie", "csrf_token=csrf; Path=/"),
                ],
            )
        if method == "POST" and path.endswith("/plugin/install/marketplace"):
            assert request.headers["X-CSRF-Token"] == "csrf"
            self.mutations.append("plugin")
            return self._json(200, {"all_installed": True, "task_id": "", "task": None})
        if path.endswith("/model-providers/langgenius/deepseek/deepseek/credentials"):
            if method == "GET":
                return self._json(
                    200,
                    {"credentials": {"api_key": "masked"} if self.credentials_configured else None},
                )
            assert body == {"credentials": {"api_key": "sk-live"}, "name": "GEO DeepSeek"}
            self.credentials_configured = True
            self.mutations.append("credential")
            return self._json(201, {"result": "success"})
        if method == "POST" and path == "/console/api/apps/imports":
            purpose = PURPOSES[len(self.apps)]
            app_id = f"app-{len(self.apps) + 1}"
            self.apps[app_id] = {
                "purpose": purpose,
                "workflow_id": f"workflow-{len(self.apps) + 1}",
                "token": "",
            }
            self.mutations.append(f"import:{purpose}")
            return self._json(
                200,
                {"id": f"import-{app_id}", "status": "completed", "app_id": app_id},
            )
        app_id = self._app_id(path)
        if app_id and path.endswith("/workflows/publish"):
            app = self.apps[app_id]
            if method == "POST":
                self.mutations.append(f"publish:{app['purpose']}")
                return self._json(200, {"result": "success", "created_at": 1})
            return self._json(200, {"id": app["workflow_id"]})
        if app_id and path.endswith("/api-keys"):
            app = self.apps[app_id]
            if method == "GET":
                rows = [] if not app["token"] else [{"id": app_id, "token": app["token"]}]
                return self._json(200, {"data": rows})
            app["token"] = f"app-token-{app_id}"
            self.mutations.append(f"key:{app['purpose']}")
            return self._json(201, {"id": app_id, "type": "app", "token": app["token"]})
        return self._json(404, {"message": f"unhandled {method} {path}"})

    @staticmethod
    def _app_id(path: str) -> str | None:
        parts = path.split("/")
        return parts[4] if len(parts) > 5 and parts[3] == "apps" else None

    @staticmethod
    def _json(
        status: int,
        body: object,
        *,
        headers: list[tuple[str, str]] | None = None,
    ) -> httpx.Response:
        return httpx.Response(status, json=body, headers=headers)


def test_configure_runtime_is_private_complete_and_idempotent(tmp_path: Path) -> None:
    password = "private-password-1"
    state = {
        "schema_version": 1,
        "admin_email": "geo@example.test",
        "admin_password": password,
        "workflows": {},
    }
    state_path = tmp_path / "state.json"
    manifest, manifest_dir = _manifest(tmp_path)
    stub = DifyConsoleStub(password=password)

    with httpx.Client(
        base_url="http://dify.test",
        transport=httpx.MockTransport(stub),
    ) as client:
        result = configure_runtime(
            client,
            state=state,
            state_file=state_path,
            manifest=manifest,
            manifest_dir=manifest_dir,
            deepseek_api_key="sk-live",
            readiness_seconds=1,
        )

    assert result["status"] == "configured"
    assert len(result["workflows"]) == 4
    assert state_path.stat().st_mode & 0o777 == 0o600
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(persisted["workflows"]) == set(PURPOSES)
    assert all(item["api_token"].startswith("app-token-") for item in persisted["workflows"].values())
    assert len([item for item in stub.mutations if item.startswith("import:")]) == 4
    assert len([item for item in stub.mutations if item.startswith("publish:")]) == 4
    assert len([item for item in stub.mutations if item.startswith("key:")]) == 4

    for row in persisted["workflows"].values():
        row["geo_secret"] = {
            "reference_id": "00000000-0000-4000-8000-000000000001",
            "version": 1,
            "token_hash": "a" * 64,
        }
        row["geo_release_id"] = "00000000-0000-4000-8000-000000000002"
    before = tuple(stub.mutations)
    with httpx.Client(
        base_url="http://dify.test",
        transport=httpx.MockTransport(stub),
    ) as client:
        configure_runtime(
            client,
            state=persisted,
            state_file=state_path,
            manifest=manifest,
            manifest_dir=manifest_dir,
            deepseek_api_key="sk-live",
            readiness_seconds=1,
        )
    new_mutations = stub.mutations[len(before) :]
    assert new_mutations == ["plugin"]
    rerun = json.loads(state_path.read_text(encoding="utf-8"))
    assert all("geo_secret" in item for item in rerun["workflows"].values())
    assert all("geo_release_id" in item for item in rerun["workflows"].values())


def _manifest(root: Path) -> tuple[dict[str, object], Path]:
    workflows: list[dict[str, str]] = []
    for index, purpose in enumerate(PURPOSES, 1):
        file_name = f"workflow-{index}.yml"
        body = f"app:\n  name: workflow-{index}\n"
        (root / file_name).write_text(body, encoding="utf-8")
        workflows.append(
            {
                "purpose": purpose,
                "file": file_name,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        )
    return {"dify_version": "1.16.0", "workflows": workflows}, root
