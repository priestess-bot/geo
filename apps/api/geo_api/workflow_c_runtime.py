"""Composition contract for the non-B workflow C Internal API vertical."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import importlib
import os
from pathlib import Path
from typing import cast

from geo_api.workflow_c_alert_runtime import WorkflowCAlertRuntime
from geo_api.workflow_c_analysis_runtime import WorkflowCAnalysisPort, WorkflowCAnalysisRuntime
from geo_api.workflow_c_sampling_runtime import WorkflowCSamplingRuntime
from geo_api.workflow_c_manual_artifacts import InMemoryManualArtifactWriter


class WorkflowCUnavailable(RuntimeError):
    """A durable workflow C runtime has not been mounted."""


@dataclass(frozen=True)
class WorkflowCApi:
    sampling: WorkflowCSamplingRuntime
    analysis: WorkflowCAnalysisPort
    alerts: WorkflowCAlertRuntime
    persistence: str

    def __post_init__(self) -> None:
        if self.persistence not in {"memory_test_only", "durable"}:
            raise ValueError("workflow C persistence classification is invalid")


def memory_workflow_c_api(*, clock: Callable[[], datetime]) -> WorkflowCApi:
    """Explicit test/development adapter; production must install a durable runtime."""
    return WorkflowCApi(
        sampling=WorkflowCSamplingRuntime(
            clock=clock,
            manual_artifact_writer=InMemoryManualArtifactWriter(),
        ),
        analysis=WorkflowCAnalysisRuntime(clock=clock),
        alerts=WorkflowCAlertRuntime(clock=clock),
        persistence="memory_test_only",
    )


def build_workflow_c_api() -> WorkflowCApi | None:
    """Resolve the fenced PostgreSQL runtime without ever falling back to memory.

    The concrete adapter is intentionally loaded only after the complete Workflow
    C migration/RPC contract is available. Returning ``None`` is significant: the
    Internal API still mounts its route shape, but readiness remains failed and
    every route responds unavailable until all durable sub-runtimes can be built.
    """

    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    # The API writer validates this mounted Docker Secret against database
    # canaries during durable construction. Treat an absent mount as an absent
    # runtime so application construction can expose the stable unavailable
    # route/readiness contract instead of crashing before readiness runs.
    if not os.getenv("GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE", "").strip():
        return None
    module_name = "geo_api.workflow_c_postgres"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        # The concrete adapter is optional during a staged code rollout. A
        # missing dependency *inside* it must still abort startup rather than
        # disguising a broken durable runtime as an absent one.
        if error.name != module_name:
            raise
        return None
    builder = getattr(module, "build_workflow_c_api", None)
    if not callable(builder):
        return None
    runtime = builder(database_url=database_url)
    if getattr(runtime, "persistence", None) != "durable":
        raise RuntimeError("Workflow C PostgreSQL builder did not return a durable runtime")
    return cast(WorkflowCApi, runtime)


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if not file_name:
        return direct
    return Path(file_name).read_text(encoding="utf-8").strip()


__all__ = [
    "WorkflowCApi",
    "WorkflowCUnavailable",
    "build_workflow_c_api",
    "memory_workflow_c_api",
]
