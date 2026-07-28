from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets import SecretValue, SecretVersionHandle
from geo_core.workflow_runtime import (
    PublishedWorkflowSnapshot,
    PublishedWorkflowSnapshotPin,
    WorkflowExecutionRequest,
    WorkflowRuntimeRelease,
)
from geo_core.workflow_runtime.contracts import CONTEXT_CONTRACT_VERSION, canonical_json_hash


class FakeCredentials:
    def __init__(self, value: str = "app-secret") -> None:
        self.value = value
        self.handles = []

    def resolve(self, handle):
        self.handles.append(handle)
        return SecretValue(self.value)


class FakeRepository:
    def __init__(self, release) -> None:
        self.release = release
        self.started = []
        self.finished = []
        self.attempt_id = uuid4()
        self.replay = None
        self.unresolved_attempt_id = None
        self.snapshot_id = uuid4()
        self.pin = PublishedWorkflowSnapshotPin(
            project_id=release.project_id,
            release_id=release.id,
            published_snapshot_id=self.snapshot_id,
            workflow_id=release.dify_workflow_id,
            workflow_hash="e" * 64,
            snapshot_hash="f" * 64,
        )

    def resolve_active(self, *, project_id, purpose):
        assert project_id == self.release.project_id
        assert purpose == self.release.purpose
        return self.release

    def get_release(self, *, project_id, release_id):
        assert (project_id, release_id) == (self.release.project_id, self.release.id)
        return self.release

    def begin_business_attempt(self, lease, **values):
        self.started.append((lease, values))
        return self.attempt_id

    def finish_business_attempt(self, lease, *, attempt_id, values):
        self.finished.append((lease, attempt_id, values))

    def load_successful_business_result(self, lease, **values):
        del lease, values
        return self.replay

    def load_published_snapshot_pin(self, *, release):
        assert release == self.release
        return self.pin

    def find_unresolved_business_attempt(self, lease, **values):
        del lease, values
        return self.unresolved_attempt_id

    def begin_canary_attempt(self, **values):
        self.started.append((None, values))
        return self.attempt_id

    def finish_canary_attempt(self, **values):
        self.finished.append((None, values["attempt_id"], values["values"]))

    def record_published_snapshot(self, *, release, snapshot):
        assert release == self.release
        self.snapshot = snapshot
        return self.snapshot_id


class FakePublishedReader:
    def __init__(
        self,
        release,
        *,
        workflow_id: str | None = None,
        workflow_hash: str = "e" * 64,
        snapshot_hash: str = "f" * 64,
        model_provider: str | None = None,
        configured_model: str | None = None,
    ) -> None:
        self.release = release
        self.workflow_id = workflow_id or release.dify_workflow_id
        self.workflow_hash = workflow_hash
        self.snapshot_hash = snapshot_hash
        self.model_provider = model_provider or release.model_provider
        self.configured_model = configured_model or release.configured_model
        self.read_count = 0

    def read(self, *, purpose, app_id):
        self.read_count += 1
        assert (purpose, app_id) == (self.release.purpose, self.release.dify_app_id)
        return PublishedWorkflowSnapshot(
            purpose=purpose,
            app_id=app_id,
            workflow_id=self.workflow_id,
            workflow_hash=self.workflow_hash,
            snapshot_hash=self.snapshot_hash,
            prompt_nodes=(
                {
                    "node_id": "llm",
                    "model_provider": self.model_provider,
                    "model_name": self.configured_model,
                    "messages": [],
                },
            ),
            input_variables=({"name": "geo_context_json"},),
            graph_nodes=({"node_id": "llm", "type": "llm", "title": "LLM"},),
            published_at=datetime(2026, 7, 27, tzinfo=UTC),
            observed_at=datetime(2026, 7, 27, tzinfo=UTC),
        )


def release_and_request():
    project_id = uuid4()
    output_schema = {
        "type": "object",
        "properties": {"questions": {"type": "array"}},
        "required": ["questions"],
    }
    input_schema = {
        "type": "object",
        "properties": {"dimensions": {"type": "array"}},
        "required": ["dimensions"],
    }
    release = WorkflowRuntimeRelease(
        id=uuid4(),
        project_id=project_id,
        purpose="knowledge.question_generation",
        version=1,
        prompt_program_id=uuid4(),
        prompt_release_id=uuid4(),
        prompt_release_hash="a" * 64,
        prompt_system_template="Frozen program system policy.",
        prompt_user_template="Process this request:\n{{request_json}}",
        dify_app_id="app-one",
        dify_workflow_id="workflow-one",
        dsl_hash="b" * 64,
        registered_workflow_hash="e" * 64,
        registered_snapshot_hash="f" * 64,
        registered_identity_source="runtime_enrollment",
        context_contract_version=CONTEXT_CONTRACT_VERSION,
        input_schema=input_schema,
        input_schema_hash=canonical_json_hash(input_schema),
        output_schema=output_schema,
        output_schema_hash=canonical_json_hash(output_schema),
        configured_model="deepseek-chat",
        model_provider="deepseek",
        api_secret_handle=SecretVersionHandle(
            reference_id=uuid4(),
            project_id=project_id,
            purpose="workflow_runtime.dify",
            version=1,
        ),
        release_hash="c" * 64,
        binding_version=1,
    )
    request = WorkflowExecutionRequest(
        project_id=project_id,
        purpose=release.purpose,
        context={"dimensions": [{"dimension_key": "value"}]},
        input_hash="d" * 64,
        output_schema=output_schema,
    )
    lease = WorkerLease(
        uuid4(), project_id, "knowledge.question.generate", "worker", uuid4(), 2, 1, 3
    )
    return release, request, lease
