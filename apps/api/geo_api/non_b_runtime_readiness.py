"""Production readiness contract for durable non-B Internal API runtimes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from geo_api.runtime_readiness import (
    ReadinessDependency,
    ReadinessFailure,
    ReadinessResult,
    ReadinessService,
    Surface,
)


RuntimePersistence = Literal["absent", "memory_test_only", "durable", "unknown"]
RuntimeT_co = TypeVar("RuntimeT_co", covariant=True)
RuntimeT = TypeVar("RuntimeT")


@dataclass(frozen=True)
class RuntimeBinding(Generic[RuntimeT_co]):
    """A runtime plus the persistence classification trusted by readiness."""

    value: RuntimeT_co | None
    persistence: RuntimePersistence


@dataclass(frozen=True)
class NonBRuntimeBindings:
    """The complete durable-runtime set required by the production Internal API."""

    prompt_program: RuntimeBinding[object]
    secret_store: RuntimeBinding[object]
    synthetic_lab: RuntimeBinding[object]
    workflow_c: RuntimeBinding[object]
    recommendation: RuntimeBinding[object]
    model_gateway: RuntimeBinding[object]

    @classmethod
    def absent(cls) -> "NonBRuntimeBindings":
        binding = RuntimeBinding[object](value=None, persistence="absent")
        return cls(
            prompt_program=binding,
            secret_store=binding,
            synthetic_lab=binding,
            workflow_c=binding,
            recommendation=binding,
            model_gateway=binding,
        )

    def failures(self) -> tuple[ReadinessFailure, ...]:
        ordered: tuple[tuple[ReadinessDependency, RuntimeBinding[object]], ...] = (
            ("prompt_program_runtime", self.prompt_program),
            ("secret_store_runtime", self.secret_store),
            ("synthetic_lab_runtime", self.synthetic_lab),
            ("workflow_c_runtime", self.workflow_c),
            ("recommendation_runtime", self.recommendation),
            ("model_gateway_runtime", self.model_gateway),
        )
        return tuple(
            ReadinessFailure(dependency, f"{dependency}_not_durable")
            for dependency, binding in ordered
            if binding.persistence != "durable"
        )


def bind_runtime(
    *,
    injected: RuntimeT | None,
    durable_builder: Callable[[], RuntimeT | None] | None = None,
) -> RuntimeBinding[RuntimeT]:
    """Resolve one runtime without treating an unclassified injection as durable.

    A supplied builder is a composition boundary for a repository-owned,
    PostgreSQL-only builder. Injected test or extension objects must carry an
    explicit ``persistence`` marker and therefore fail closed by default.
    """

    if injected is not None:
        return RuntimeBinding(value=injected, persistence=_injected_persistence(injected))
    if durable_builder is None:
        return RuntimeBinding(value=None, persistence="absent")
    built = durable_builder()
    return RuntimeBinding(
        value=built,
        persistence="durable" if built is not None else "absent",
    )


class ProductionInternalRuntimeReadiness:
    """Require durable non-B runtimes only after shared readiness succeeds."""

    def __init__(
        self,
        delegate: ReadinessService,
        *,
        surface: Surface,
        deployment_environment: str,
        bindings: NonBRuntimeBindings,
    ) -> None:
        self._delegate = delegate
        self._enforced = (
            surface == "internal" and deployment_environment.strip().lower() == "production"
        )
        self._bindings = bindings

    async def check(self) -> ReadinessResult:
        result = await self._delegate.check()
        if not result.ready or not self._enforced:
            return result
        return ReadinessResult(failures=self._bindings.failures())


def _injected_persistence(runtime: object) -> RuntimePersistence:
    try:
        marker = getattr(runtime, "persistence", None)
    except Exception:
        return "unknown"
    if marker == "durable":
        return "durable"
    if marker == "memory_test_only":
        return "memory_test_only"
    return "unknown"


__all__ = [
    "NonBRuntimeBindings",
    "ProductionInternalRuntimeReadiness",
    "RuntimeBinding",
    "RuntimePersistence",
    "bind_runtime",
]
