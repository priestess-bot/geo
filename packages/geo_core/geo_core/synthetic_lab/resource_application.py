"""Idempotent creation of versioned Synthetic Lab resources."""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from geo_core.synthetic_lab.application_support import (
    command_identity,
    recover_command,
    require_roles,
    stage_command,
)
from geo_core.synthetic_lab.channel_styles import ChannelStyleVersion
from geo_core.synthetic_lab.domain import (
    StyleProfileSampleManifest,
    StyleProfileVersion,
    StyleSource,
)
from geo_core.synthetic_lab.ports import (
    CommandReceipt,
    LabPrincipal,
    LabRole,
    SyntheticCommandOperation,
    SyntheticLabIdempotencyConflict,
    SyntheticLabUnitOfWorkFactory,
    VersionedAggregate,
)
from geo_core.synthetic_lab.review_cases import ReviewCase, ReviewSuite


_Resource = TypeVar(
    "_Resource",
    StyleSource,
    StyleProfileVersion,
    ChannelStyleVersion,
    ReviewSuite,
    ReviewCase,
)


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
        sample_ids: tuple[UUID, ...] = (),
    ) -> CommandReceipt:
        require_roles(principal, profile.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        if expected_version != 0:
            raise ValueError("resource creation expected_version must be zero")
        manifest = (
            StyleProfileSampleManifest(
                project_id=profile.project_id,
                profile_version_id=profile.id,
                corpus_hash=profile.corpus_hash,
                sample_ids=sample_ids,
            )
            if sample_ids
            else None
        )
        identity = command_identity(
            project_id=profile.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.CREATE_STYLE_PROFILE,
            request={
                "resource": profile,
                "sample_manifest": manifest,
                "expected_version": expected_version,
            },
        )
        legacy_identity = command_identity(
            project_id=profile.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.CREATE_STYLE_PROFILE,
            request={"resource": profile, "expected_version": expected_version},
        )
        with self._uow_factory(project_id=profile.project_id) as uow:
            existing = uow.commands.get(
                project_id=profile.project_id,
                idempotency_key_hash=identity.idempotency_key_hash,
            )
            if existing is not None:
                if existing.identity not in {identity, legacy_identity}:
                    raise SyntheticLabIdempotencyConflict(
                        "Idempotency-Key was reused with another Profile manifest"
                    )
                if not isinstance(existing.result, StyleProfileVersion):
                    raise SyntheticLabIdempotencyConflict(
                        "Style Profile command result type changed"
                    )
                return CommandReceipt(existing.result, replayed=True)
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=profile.project_id,
                    kind="style_profile",
                    resource_id=profile.id,
                    version=1,
                    submitted_by=principal.actor_id,
                    payload=profile,
                ),
                expected_version=0,
            )
            if manifest is not None:
                uow.aggregates.stage(
                    VersionedAggregate(
                        project_id=profile.project_id,
                        kind="style_profile_sample_manifest",
                        resource_id=profile.id,
                        version=1,
                        submitted_by=principal.actor_id,
                        payload=manifest,
                    ),
                    expected_version=0,
                )
            return stage_command(uow, identity, profile)

    def create_channel_style(
        self,
        *,
        principal: LabPrincipal,
        style: ChannelStyleVersion,
        expected_version: int,
        idempotency_key: str,
    ) -> CommandReceipt:
        require_roles(principal, style.project_id, LabRole.OPERATOR, LabRole.REVIEWER)
        identity = command_identity(
            project_id=style.project_id,
            idempotency_key=idempotency_key,
            operation=SyntheticCommandOperation.CREATE_CHANNEL_STYLE,
            request={"resource": style, "expected_version": expected_version},
        )
        with self._uow_factory(project_id=style.project_id) as uow:
            replay = recover_command(uow, identity, ChannelStyleVersion)
            if replay is not None:
                return replay
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=style.project_id,
                    kind="channel_style",
                    resource_id=style.style_id,
                    version=style.version_number,
                    submitted_by=principal.actor_id,
                    payload=style,
                ),
                expected_version=expected_version,
            )
            return stage_command(uow, identity, style)

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
