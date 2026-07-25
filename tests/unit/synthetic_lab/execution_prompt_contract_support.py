"""Test doubles shared by Synthetic execution Prompt contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from geo_core.model_gateway.contracts import ModelGatewayResult


class _CaptureModelCallApplication:
    def __init__(self) -> None:
        self.command = None

    def execute(self, command, *, policy):
        del policy
        self.command = command
        raise RuntimeError("captured before external execution")


class _GovernedRuntime:
    def __init__(self, loaded) -> None:
        self.loaded = loaded
        self.admissions = []
        self.loads = []

    def load_or_admit_claimed_job(self, request):
        self.admissions.append(request)
        return SimpleNamespace(job=self.loaded.job)

    def load(self, *, project_id, job_id):
        self.loads.append((project_id, job_id))
        return self.loaded


class _GovernedApplication:
    def __init__(self, result: ModelGatewayResult) -> None:
        self.result = result
        self.command = None

    def execute(self, command, *, policy):
        del policy
        self.command = command
        return SimpleNamespace(
            attempt=SimpleNamespace(spec=SimpleNamespace(id=uuid4())),
            result=self.result,
        )


class _NoopRecovery:
    def recover_derived(self, request):
        del request
        raise AssertionError("non-replayed model call must not recover an artifact")


__all__ = [
    "_CaptureModelCallApplication",
    "_GovernedApplication",
    "_GovernedRuntime",
    "_NoopRecovery",
]
