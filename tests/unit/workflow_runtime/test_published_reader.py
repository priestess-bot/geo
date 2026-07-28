from __future__ import annotations

import json

import httpx
import pytest

from geo_core.workflow_runtime import DifyPublishedWorkflowReader
from geo_core.workflow_runtime.errors import (
    RetryableWorkflowExecutionError,
    WorkflowConfigurationError,
)


def test_reads_prompt_model_and_inputs_from_the_published_dify_graph(tmp_path) -> None:
    state = tmp_path / "dify.json"
    state.write_text(json.dumps({
        "admin_email": "operator@example.test",
        "admin_password": "private-password",
        "workflows": {"knowledge.question_generation": {"app_id": "app-1"}},
    }))
    state.chmod(0o600)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/console/api/login":
            return httpx.Response(200, json={"result": "success"})
        return httpx.Response(200, json={
            "id": "workflow-2",
            "hash": "a" * 64,
            "updated_at": 1785120000,
            "graph": {"nodes": [
                {"id": "start", "data": {"type": "start", "title": "输入", "variables": [
                    {"variable": "geo_context_json", "label": "业务上下文", "required": True, "type": "paragraph"}
                ]}},
                {"id": "llm", "data": {"type": "llm", "title": "生成", "model": {
                    "provider": "deepseek", "name": "deepseek-chat", "mode": "chat", "completion_params": {"temperature": 0.1}
                }, "prompt_template": [
                    {"role": "system", "text": "Dify owns this Prompt."},
                    {"role": "user", "text": "Use {{context}}."}
                ]}},
            ]},
        })

    snapshot = DifyPublishedWorkflowReader(
        base_url="http://dify.test",
        state_file=state,
        client=httpx.Client(base_url="http://dify.test", transport=httpx.MockTransport(handler)),
    ).read(purpose="knowledge.question_generation", app_id="app-1")

    assert snapshot.workflow_id == "workflow-2"
    assert snapshot.prompt_nodes[0]["messages"][0]["text"] == "Dify owns this Prompt."
    assert snapshot.input_variables[0]["name"] == "geo_context_json"


def test_rejects_a_reader_state_file_visible_to_other_users(tmp_path) -> None:
    state = tmp_path / "dify.json"
    state.write_text("{}")
    state.chmod(0o644)
    reader = DifyPublishedWorkflowReader(
        base_url="http://dify.test",
        state_file=state,
    )
    with pytest.raises(WorkflowConfigurationError, match="permissions"):
        reader.read(purpose="knowledge.question_generation", app_id="app-1")


def test_classifies_published_reader_network_failure_as_retryable(tmp_path) -> None:
    state = tmp_path / "dify.json"
    state.write_text(json.dumps({
        "admin_email": "operator@example.test",
        "admin_password": "private-password",
        "workflows": {"knowledge.question_generation": {"app_id": "app-1"}},
    }))
    state.chmod(0o600)

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    reader = DifyPublishedWorkflowReader(
        base_url="http://dify.test",
        state_file=state,
        client=httpx.Client(
            base_url="http://dify.test",
            transport=httpx.MockTransport(unavailable),
        ),
    )

    with pytest.raises(RetryableWorkflowExecutionError) as captured:
        reader.read(purpose="knowledge.question_generation", app_id="app-1")

    assert captured.value.code == "dify_reader_transport_unavailable"
