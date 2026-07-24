"""Idempotent creation of versioned Synthetic Lab resources."""

from __future__ import annotations

from typing import TypeVar

from geo_core.synthetic_lab.application_support import (
    command_identity,
    recover_command,
    require_roles,
    stage_command,
)
from geo_core.synthetic_lab.domain import StyleProfileVersion, StyleSource
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    LabPrincipal,
    LabRole,
    SyntheticCommandOperation,
    SyntheticLabUnitOfWorkFactory,
    VersionedAggregate,
)
from geo_core.synthetic_lab.review_cases import ReviewCase, ReviewSuite


_Resource = TypeVar("_Resource", StyleSource, StyleProfileVersion, ReviewSuite, ReviewCase)


class SyntheticResourceApplication:
    def __init__(self, uow_factory: SyntheticLabUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def create_style_source(
        self,
        *,
        principal: LabPrincipal,
        source: StyleSource,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        return self._create(
            principal=principal,
            resource=source,
            kind="style_source",
            operation=SyntheticCommandOperation.CREATE_STYLE_SOURCE,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def create_style_profile(
        self,
        *,
        principal: LabPrincipal,
        profile: StyleProfileVersion,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        return self._create(
            principal=principal,
            resource=profile,
            kind="style_profile",
            operation=SyntheticCommandOperation.CREATE_STYLE_PROFILE,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def create_review_suite(
        self,
        *,
        principal: LabPrincipal,
        suite: ReviewSuite,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        return self._create(
            principal=principal,
            resource=suite,
            kind="review_suite",
            operation=SyntheticCommandOperation.CREATE_REVIEW_SUITE,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def create_review_case(
        self,
        *,
        principal: LabPrincipal,
        case: ReviewCase,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        return self._create(
            principal=principal,
            resource=case,
            kind="review_case",
            operation=SyntheticCommandOperation.CREATE_REVIEW_CASE,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def _create(
        self,
        *,
        principal: LabPrincipal,
        resource: _Resource,
        kind: str,
        operation: SyntheticCommandOperation,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, resource.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        if expected_version != 0:
            raise ValueError("resource creation expected_version must be zero")
        identity = command_identity(
            project_id=resource.project_id,
            idempotency_key=idempotency_key,
            operation=operation,
            request={"resource": resource, "expected_version": expected_version},
        )
        with self._uow_factory(project_id=resource.project_id) as uow:
            replay = recover_command(uow, identity, type(resource))
            if replay is not None:
                return replay
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=resource.project_id,
                    kind=kind,
                    resource_id=resource.id,
                    version=1,
                    submitted_by=principal.actor_id,
                    payload=resource,
                ),
                expected_version=0,
            )
            return stage_command(uow, identity, resource)


__all__ = ["SyntheticResourceApplication"]
