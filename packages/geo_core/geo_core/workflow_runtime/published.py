"""Read and project the currently published Dify workflow without secrets."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

import httpx

from .contracts import DIFY_WORKFLOW_PURPOSES, canonical_json_hash, canonical_json_value
from .errors import (
    RetryableWorkflowExecutionError,
    WorkflowAuthenticationError,
    WorkflowConfigurationError,
    WorkflowContractError,
)


@dataclass(frozen=True)
class PublishedWorkflowSnapshot:
    purpose: str
    app_id: str
    workflow_id: str
    workflow_hash: str
    snapshot_hash: str
    prompt_nodes: tuple[Mapping[str, object], ...]
    input_variables: tuple[Mapping[str, object], ...]
    graph_nodes: tuple[Mapping[str, object], ...]
    published_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.purpose not in DIFY_WORKFLOW_PURPOSES:
            raise WorkflowContractError("published Dify purpose is not supported")
        for label, value in (
            ("Dify app ID", self.app_id),
            ("Dify workflow ID", self.workflow_id),
        ):
            if not value.strip():
                raise WorkflowContractError(f"{label} is required")
        for label, value in (
            ("Dify workflow hash", self.workflow_hash),
            ("Dify snapshot hash", self.snapshot_hash),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise WorkflowContractError(f"{label} must be lowercase SHA-256")

    def as_json(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "purpose": self.purpose,
                "app_id": self.app_id,
                "workflow_id": self.workflow_id,
                "workflow_hash": self.workflow_hash,
                "snapshot_hash": self.snapshot_hash,
                "prompt_nodes": [dict(item) for item in self.prompt_nodes],
                "input_variables": [dict(item) for item in self.input_variables],
                "graph_nodes": [dict(item) for item in self.graph_nodes],
                "published_at": self.published_at.isoformat(),
                "observed_at": self.observed_at.isoformat(),
            }
        )


@dataclass(frozen=True)
class PublishedWorkflowSnapshotPin:
    project_id: UUID
    release_id: UUID
    published_snapshot_id: UUID
    workflow_id: str
    workflow_hash: str
    snapshot_hash: str
    pin_source: str = "runtime_canary"

    def __post_init__(self) -> None:
        if not self.workflow_id.strip():
            raise WorkflowContractError("pinned Dify workflow ID is required")
        if self.pin_source not in {"migration_backfill", "runtime_canary"}:
            raise WorkflowContractError("Dify snapshot pin source is invalid")
        for label, value in (
            ("pinned Dify workflow hash", self.workflow_hash),
            ("pinned Dify snapshot hash", self.snapshot_hash),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise WorkflowContractError(f"{label} must be lowercase SHA-256")


class DifyPublishedWorkflowReader:
    """Use the pinned Dify console read API from a server-side private state file."""

    def __init__(
        self,
        *,
        base_url: str,
        state_file: str | Path,
        timeout_seconds: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = _base_url(base_url)
        self._state_file = Path(state_file)
        self._timeout = timeout_seconds
        self._client = client

    def read(self, *, purpose: str, app_id: str) -> PublishedWorkflowSnapshot:
        if purpose not in DIFY_WORKFLOW_PURPOSES:
            raise WorkflowContractError("published Dify purpose is not supported")
        state = _private_state(self._state_file)
        configured_app = _configured_app(state, purpose)
        if configured_app != app_id:
            raise WorkflowConfigurationError(
                "Dify published app differs from the frozen GEO runtime app",
                code="dify_published_app_mismatch",
            )
        client = self._client or httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout, connect=min(10.0, self._timeout)),
            follow_redirects=True,
            trust_env=False,
        )
        close = self._client is None
        try:
            try:
                _login(client, state)
                response = client.get(f"/console/api/apps/{app_id}/workflows/publish")
                body = _response(response, action="read the published Dify workflow")
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise RetryableWorkflowExecutionError(
                    "Dify published workflow reader is unreachable; retry the same GEO Job",
                    code="dify_reader_transport_unavailable",
                ) from exc
        finally:
            if close:
                client.close()
        return _snapshot(purpose=purpose, app_id=app_id, body=body)


def _snapshot(
    *, purpose: str, app_id: str, body: Mapping[str, object]
) -> PublishedWorkflowSnapshot:
    workflow_id = _required_text(body.get("id"), "published Dify workflow ID")
    workflow_hash = _sha(body.get("hash"), "published Dify workflow hash")
    graph = body.get("graph")
    if not isinstance(graph, Mapping):
        raise WorkflowContractError("published Dify workflow has no graph")
    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        raise WorkflowContractError("published Dify workflow graph has no nodes")
    prompt_nodes: list[Mapping[str, object]] = []
    input_variables: list[Mapping[str, object]] = []
    graph_nodes: list[Mapping[str, object]] = []
    for raw_node in raw_nodes:
        if not isinstance(raw_node, Mapping):
            raise WorkflowContractError("published Dify graph node is invalid")
        node_id = _required_text(raw_node.get("id"), "Dify node ID")
        data = raw_node.get("data")
        if not isinstance(data, Mapping):
            raise WorkflowContractError("published Dify graph node has no data")
        node_type = _required_text(data.get("type"), "Dify node type")
        title = str(data.get("title") or node_type).strip()
        graph_nodes.append({"node_id": node_id, "type": node_type, "title": title})
        if node_type == "start":
            input_variables.extend(_input_variables(data.get("variables")))
        if node_type == "llm":
            prompt_nodes.append(_prompt_node(node_id=node_id, title=title, data=data))
    if not prompt_nodes:
        raise WorkflowContractError("published Dify workflow has no Prompt node")
    if not input_variables:
        raise WorkflowContractError("published Dify workflow has no input variables")
    published_at = _timestamp(body.get("updated_at") or body.get("created_at"))
    observed_at = datetime.now(UTC)
    value = {
        "purpose": purpose,
        "app_id": app_id,
        "workflow_id": workflow_id,
        "workflow_hash": workflow_hash,
        "prompt_nodes": prompt_nodes,
        "input_variables": input_variables,
        "graph_nodes": graph_nodes,
        "published_at": published_at.isoformat(),
    }
    return PublishedWorkflowSnapshot(
        purpose=purpose,
        app_id=app_id,
        workflow_id=workflow_id,
        workflow_hash=workflow_hash,
        snapshot_hash=canonical_json_hash(value),
        prompt_nodes=tuple(prompt_nodes),
        input_variables=tuple(input_variables),
        graph_nodes=tuple(graph_nodes),
        published_at=published_at,
        observed_at=observed_at,
    )


def _prompt_node(*, node_id: str, title: str, data: Mapping[str, object]) -> Mapping[str, object]:
    templates = data.get("prompt_template")
    if not isinstance(templates, list):
        raise WorkflowContractError("published Dify LLM node has no Prompt messages")
    messages: list[Mapping[str, object]] = []
    for template in templates:
        if not isinstance(template, Mapping):
            raise WorkflowContractError("published Dify Prompt message is invalid")
        role = _required_text(template.get("role"), "Dify Prompt role")
        text = _required_text(template.get("text"), "Dify Prompt text")
        messages.append({"role": role, "text": text})
    model = data.get("model")
    if not isinstance(model, Mapping):
        model = {}
    return {
        "node_id": node_id,
        "title": title,
        "model_provider": str(model.get("provider") or "").strip(),
        "model_name": str(model.get("name") or "").strip(),
        "model_mode": str(model.get("mode") or "").strip(),
        "completion_params": canonical_json_value(model.get("completion_params") or {}),
        "messages": messages,
    }


def _input_variables(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise WorkflowContractError("published Dify Start node variables are invalid")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise WorkflowContractError("published Dify input variable is invalid")
        result.append(
            {
                "name": _required_text(item.get("variable"), "Dify input variable name"),
                "label": str(item.get("label") or item.get("variable") or "").strip(),
                "type": str(item.get("type") or "text-input").strip(),
                "required": bool(item.get("required", False)),
                "description": str(item.get("description") or "").strip(),
            }
        )
    return result


def _login(client: httpx.Client, state: Mapping[str, object]) -> None:
    password = _required_text(state.get("admin_password"), "Dify reader password")
    response = client.post(
        "/console/api/login",
        json={
            "email": _required_text(state.get("admin_email"), "Dify reader email"),
            "password": base64.b64encode(password.encode()).decode(),
            "remember_me": False,
        },
    )
    body = _response(response, action="authenticate the Dify workflow reader")
    if body.get("result") != "success":
        raise WorkflowAuthenticationError(
            "Dify workflow reader authentication failed",
            code="dify_reader_auth_failed",
        )
    csrf = client.cookies.get("csrf_token") or client.cookies.get("__Host-csrf_token")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf


def _response(response: httpx.Response, *, action: str) -> Mapping[str, object]:
    if response.status_code in {401, 403}:
        raise WorkflowAuthenticationError(
            f"Dify rejected the private reader while trying to {action}",
            code="dify_reader_auth_rejected",
        )
    if response.status_code >= 500:
        raise RetryableWorkflowExecutionError(
            f"Dify is unavailable while trying to {action}",
            code="dify_reader_unavailable",
        )
    if response.status_code >= 400:
        raise WorkflowConfigurationError(
            f"Dify could not {action} (HTTP {response.status_code})",
            code="dify_reader_request_rejected",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise WorkflowContractError("Dify reader returned non-JSON data") from exc
    if not isinstance(body, Mapping):
        raise WorkflowContractError("Dify reader response is not an object")
    return body


def _private_state(path: Path) -> Mapping[str, object]:
    try:
        if path.is_symlink() or not path.is_file():
            raise WorkflowConfigurationError(
                "Dify private reader state file is missing",
                code="dify_reader_state_missing",
            )
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise WorkflowConfigurationError(
                "Dify private reader state file permissions are too broad",
                code="dify_reader_state_permissions",
            )
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkflowConfigurationError(
            "Dify private reader state file cannot be read",
            code="dify_reader_state_unreadable",
        ) from exc
    except json.JSONDecodeError as exc:
        raise WorkflowConfigurationError(
            "Dify private reader state is invalid JSON",
            code="dify_reader_state_invalid",
        ) from exc
    if not isinstance(value, Mapping):
        raise WorkflowConfigurationError(
            "Dify private reader state is not an object",
            code="dify_reader_state_invalid",
        )
    return value


def _configured_app(state: Mapping[str, object], purpose: str) -> str:
    workflows = state.get("workflows")
    if not isinstance(workflows, Mapping) or not isinstance(workflows.get(purpose), Mapping):
        raise WorkflowConfigurationError(
            f"Dify private reader state has no {purpose} workflow",
            code="dify_reader_workflow_missing",
        )
    return _required_text(workflows[purpose].get("app_id"), "Dify configured app ID")


def _timestamp(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    raise WorkflowContractError("published Dify workflow has no valid timestamp")


def _sha(value: object, label: str) -> str:
    result = _required_text(value, label)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise WorkflowContractError(f"{label} must be lowercase SHA-256")
    return result


def _required_text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise WorkflowContractError(f"{label} is required")
    return result


def _base_url(value: str) -> str:
    result = value.strip().rstrip("/")
    if not result.startswith(("http://", "https://")):
        raise ValueError("Dify reader base URL must use HTTP(S)")
    return result


__all__ = [
    "DifyPublishedWorkflowReader",
    "PublishedWorkflowSnapshot",
    "PublishedWorkflowSnapshotPin",
]
