"""Compatibility facade for Synthetic Lab PostgreSQL persistence."""

from __future__ import annotations

from dataclasses import dataclass

from geo_core.synthetic_lab.authorization import AuthorizationBinding, AuthorizationRecord
from geo_core.synthetic_lab.execution_application import SyntheticExecutionApplication
from geo_core.synthetic_lab.experiment_application import ExperimentApplication
from geo_core.synthetic_lab.review_application import ReviewApplication
from geo_core.synthetic_lab.resource_application import SyntheticResourceApplication
from geo_core.synthetic_lab.style_application import StyleApplication
from geo_core.synthetic_lab.postgres_uow import (
    PostgresSyntheticLabUnitOfWork,
    PostgresSyntheticLabUnitOfWorkFactory,
    synthetic_lab_uow_factory,
)


@dataclass(frozen=True)
class PostgresSyntheticLabPersistence:
    uow_factory: PostgresSyntheticLabUnitOfWorkFactory
    style: StyleApplication
    review: ReviewApplication
    experiments: ExperimentApplication
    execution: SyntheticExecutionApplication
    resources: SyntheticResourceApplication
    collection_authorizations: PostgresCollectionAuthorizationPort


class PostgresCollectionAuthorizationPort:
    def __init__(self, factory: PostgresSyntheticLabUnitOfWorkFactory) -> None:
        self._factory = factory

    def current(self, binding: AuthorizationBinding) -> AuthorizationRecord | None:
        with self._factory(project_id=binding.project_id) as unit_of_work:
            envelope = unit_of_work.authorizations.current(
                project_id=binding.project_id,
                channel=binding.channel,
                adapter_release=binding.adapter_release,
            )
        return envelope.record if envelope is not None else None


def build_synthetic_lab_persistence(
    database_url: str | None,
) -> PostgresSyntheticLabPersistence | None:
    if database_url is None or not database_url.strip():
        return None
    factory = synthetic_lab_uow_factory(database_url)
    return PostgresSyntheticLabPersistence(
        uow_factory=factory,
        style=StyleApplication(factory),
        review=ReviewApplication(factory),
        experiments=ExperimentApplication(factory),
        execution=SyntheticExecutionApplication(factory),
        resources=SyntheticResourceApplication(factory),
        collection_authorizations=PostgresCollectionAuthorizationPort(factory),
    )


def build_synthetic_lab_api(*, database_url: str):
    from geo_core.synthetic_lab.postgres_api import PostgresSyntheticLabApi

    if not database_url.strip():
        raise ValueError("Synthetic Lab database URL cannot be empty")
    return PostgresSyntheticLabApi(database_url)


__all__ = [
    "PostgresSyntheticLabPersistence",
    "PostgresCollectionAuthorizationPort",
    "PostgresSyntheticLabUnitOfWork",
    "PostgresSyntheticLabUnitOfWorkFactory",
    "build_synthetic_lab_persistence",
    "build_synthetic_lab_api",
    "synthetic_lab_uow_factory",
]
