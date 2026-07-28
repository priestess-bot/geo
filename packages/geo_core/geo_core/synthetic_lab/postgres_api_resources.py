"""Resource, review and governed manual-import methods for the Synthetic API."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
from typing import Any, Callable
from uuid import UUID

from geo_core.access.models import AccessPrincipal
from geo_core.object_store_config import build_object_store
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.artifact_keyring import load_synthetic_artifact_keyring
from geo_core.synthetic_lab.artifact_keyring_postgres import (
    synchronize_artifact_master_key_canaries,
)
from geo_core.synthetic_lab.domain import (
    StyleAccessMode,
    StyleProfileStatus,
    StyleProfileVersion,
    StyleSource,
    StyleSourceStatus,
    style_sample_manifest_hash,
)
from geo_core.synthetic_lab.manual_import_artifacts import (
    EncryptedManualImportArtifactStore,
)
from geo_core.synthetic_lab.postgres_manual_import import PostgresManualImportService
from geo_core.synthetic_lab.ports import (
    SyntheticLabNotFound,
    SyntheticLabPersistenceError,
)
from geo_core.synthetic_lab.postgres_api_reads import SyntheticApiPage
from geo_core.synthetic_lab.postgres_api_support import (
    domain_principal,
    int_value,
    payload,
    project,
    stable_id,
    uuid_value,
)
from geo_core.synthetic_lab.review_cases import (
    ReviewCase,
    ReviewSuite,
    ReviewSuiteStatus,
    review_case_content_hash,
)


class PostgresSyntheticResourceApiMixin:
    _reads: Any
    _resources: Any
    _review: Any
    _manual_imports: PostgresManualImportService | None

    def resource_inventory(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.resource_inventory(project_id)

    def list_style_sources(self, principal: AccessPrincipal, **values: object):
        return self._aggregate_page(principal, values, "style_source")

    def create_style_source(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        source_url = request["source_url"]
        locator = source_url if source_url is not None else str(request["source_label"]).strip()
        source = StyleSource(
            id=stable_id(project_id, values["idempotency_key"], "style-source-revision"),
            project_id=project_id,
            source_id=stable_id(project_id, values["idempotency_key"], "style-source"),
            revision_number=1,
            channel=request["channel"],
            access_mode=StyleAccessMode(request["access_mode"]),
            locale=request["locale"],
            source_locator_hash=hashlib.sha256(locator.encode()).hexdigest(),
            status=(StyleSourceStatus.ACTIVE if source_url is not None else StyleSourceStatus.DRAFT),
            source_url=source_url,
        )
        return self._resources.create_style_source(
            principal=actor,
            source=source,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def list_import_previews(self, principal: AccessPrincipal, **values: object):
        service = self._manual_service()
        actor = domain_principal(principal, project(values))
        items, total = service.list_previews(
            principal=actor,
            limit=int_value(values["limit"]),
            offset=int_value(values["offset"]),
        )
        return SyntheticApiPage(items, total, int_value(values["limit"]), int_value(values["offset"]))

    def get_import_preview(self, principal: AccessPrincipal, **values: object):
        actor = domain_principal(principal, project(values))
        return self._manual_service().get_preview(
            principal=actor,
            preview_id=uuid_value(values["preview_id"]),
        )

    def create_import_preview(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        source = self._reads.style_source(project_id, request["style_source_revision_id"])
        return self._manual_service().create_preview(
            principal=actor,
            source=source,
            values=request,
            idempotency_key=str(values["idempotency_key"]),
        )

    def approve_import_preview(self, principal: AccessPrincipal, **values: object):
        actor = domain_principal(principal, project(values))
        request = payload(values)
        return self._manual_service().approve_preview(
            principal=actor,
            preview_id=uuid_value(values["preview_id"]),
            expected_version=int(request["expected_version"]),
            selected_rows=tuple(request["selected_row_numbers"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def reject_import_preview(self, principal: AccessPrincipal, **values: object):
        actor = domain_principal(principal, project(values))
        request = payload(values)
        return self._manual_service().reject_preview(
            principal=actor,
            preview_id=uuid_value(values["preview_id"]),
            expected_version=int(request["expected_version"]),
            reason=str(request["reason"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def list_imported_sample_options(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.imported_sample_options(
            project_id,
            limit=int_value(values["limit"]),
            offset=int_value(values["offset"]),
        )

    def list_profiles(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.profiles(
            project_id,
            limit=int_value(values["limit"]),
            offset=int_value(values["offset"]),
        )

    def create_profile(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        sample_ids = tuple(request["approved_sample_ids"])
        resolved = self._reads.profile_creation_inputs(
            project_id,
            channel=str(request["channel"]),
            sample_ids=sample_ids,
            prompt_binding_id=request["prompt_binding_id"],
        )
        samples = self._reads.approved_style_samples(
            project_id,
            channel=str(request["channel"]),
            sample_ids=sample_ids,
        )
        corpus_hash = style_sample_manifest_hash(samples)
        profile_hash = canonical_hash(
            {
                "corpus_hash": corpus_hash,
                "prompt_release_id": str(resolved["prompt_release_id"]),
                "prompt_release_hash": resolved["prompt_release_hash"],
                "prompt_binding_version": resolved["prompt_binding_version"],
            }
        )
        profile = StyleProfileVersion(
            id=stable_id(project_id, values["idempotency_key"], "style-profile"),
            project_id=project_id,
            profile_id=stable_id(project_id, values["idempotency_key"], "style-profile-id"),
            version_number=1,
            channel=request["channel"],
            locale=request["locale"],
            corpus_hash=corpus_hash,
            profile_hash=profile_hash,
            prompt_release_id=resolved["prompt_release_id"],
            prompt_release_hash=resolved["prompt_release_hash"],
            approved_sample_count=len(sample_ids),
            status=StyleProfileStatus.DRAFT,
        )
        return self._resources.create_style_profile(
            principal=actor,
            profile=profile,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
            sample_ids=sample_ids,
        )

    def submit_profile(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        profile = self._profile(project_id, uuid_value(values["profile_version_id"]))
        actor = domain_principal(principal, project_id)
        build = self._reads.profile_build_candidate(
            project_id,
            profile_version_id=profile.id,
            profile_hash=profile.profile_hash,
            bound_by=actor.actor_id,
        )
        if build is None or not build.output.profile_summary:
            raise SyntheticLabPersistenceError(
                "Style Profile requires a completed governed build before review"
            )
        return self._review.submit_profile(
            principal=actor,
            profile=profile,
            build_binding=build.binding,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def decide_profile(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        return self._review.decide_profile(
            principal=domain_principal(principal, project_id),
            profile=self._profile(project_id, uuid_value(values["profile_version_id"])),
            decision=str(request["decision"]),
            decided_at=datetime.now(UTC),
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def freeze_profile(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        profile = self._profile(project_id, uuid_value(values["profile_version_id"]))
        sample_ids = self._reads.profile_sample_ids(
            project_id,
            profile_version_id=profile.id,
            corpus_hash=profile.corpus_hash,
            legacy_sample_ids=tuple(request["approved_sample_ids"]),
        )
        samples = self._reads.approved_style_samples(
            project_id,
            channel=profile.channel,
            sample_ids=sample_ids,
        )
        return self._review.freeze_profile(
            principal=domain_principal(principal, project_id),
            profile=profile,
            samples=samples,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def list_suites(self, principal: AccessPrincipal, **values: object):
        return self._aggregate_page(principal, values, "review_suite")

    def create_suite(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        suite_id = stable_id(project_id, values["idempotency_key"], "review-suite-id")
        suite = ReviewSuite(
            id=stable_id(project_id, values["idempotency_key"], "review-suite"),
            project_id=project_id,
            suite_id=suite_id,
            version_number=1,
            channel=request["channel"],
            case_count=0,
            case_set_hash=canonical_hash(
                {
                    "suite_id": str(suite_id),
                    "suite_name": request["suite_name"],
                    "channel": request["channel"],
                    "cases": [],
                }
            ),
            status=ReviewSuiteStatus.DRAFT,
        )
        return self._resources.create_review_suite(
            principal=actor,
            suite=suite,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def list_cases(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        page = self._reads.aggregates(project_id, kind="review_case", limit=10_000, offset=0)
        filtered = tuple(
            item for item in page.items
            if getattr(item, "review_suite_version_id", None) == values["suite_version_id"]
        )
        offset, limit = int_value(values["offset"]), int_value(values["limit"])
        return type(page)(filtered[offset : offset + limit], len(filtered), limit, offset)

    def create_case(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        suite_record = self._reads.aggregate(
            project_id, kind="review_suite", resource_id=uuid_value(values["suite_version_id"])
        )
        if not isinstance(suite_record.payload, ReviewSuite):
            raise SyntheticLabNotFound("Review Suite payload type changed")
        if suite_record.payload.status is not ReviewSuiteStatus.DRAFT:
            raise SyntheticLabPersistenceError("Review Suite no longer accepts Cases")
        resolved = self._reads.review_case_inputs(
            project_id,
            question_set_id=request["question_set_version_id"],
            fact_snapshot_id=request["fact_snapshot_id"],
            profile_version_id=request["profile_version_id"],
        )
        request = {**request, **resolved}
        content_hash = review_case_content_hash(
            **{key: request[key] for key in (
                "case_key", "ordinal", "mode", "channel", "persona", "use_case", "subject",
                "question_set_version_id", "question_set_hash", "fact_snapshot_id",
                "fact_snapshot_hash", "profile_version_id", "profile_hash",
                "competitor_scenario", "creative_reference",
            )},
            expected_risks=tuple(request["expected_risks"]),
        )
        case = ReviewCase(
            id=stable_id(project_id, values["idempotency_key"], "review-case"),
            project_id=project_id,
            review_suite_version_id=suite_record.payload.id,
            review_suite_version_number=suite_record.payload.version_number,
            content_hash=content_hash,
            **{key: request[key] for key in (
                "case_key", "ordinal", "mode", "channel", "persona", "use_case", "subject",
                "question_set_version_id", "question_set_hash", "fact_snapshot_id",
                "fact_snapshot_hash", "profile_version_id", "profile_hash",
                "competitor_scenario", "expected_risks", "creative_reference",
            )},
        )
        return self._resources.create_review_case(
            principal=actor,
            case=case,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def freeze_suite(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        suite_id = uuid_value(values["suite_version_id"])
        suite_record = self._reads.aggregate(project_id, kind="review_suite", resource_id=suite_id)
        if not isinstance(suite_record.payload, ReviewSuite):
            raise SyntheticLabNotFound("Review Suite payload type changed")
        page = self._reads.aggregates(project_id, kind="review_case", limit=10_000, offset=0)
        cases = tuple(
            case for case in page.items
            if isinstance(case, ReviewCase) and case.review_suite_version_id == suite_id
        )
        return self._review.freeze_suite(
            principal=domain_principal(principal, project_id),
            suite=suite_record.payload,
            cases=cases,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def _aggregate_page(self, principal: AccessPrincipal, values: dict[str, object], kind: str):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.aggregates(
            project_id,
            kind=kind,
            limit=int_value(values["limit"]),
            offset=int_value(values["offset"]),
            include_state=True,
        )

    def _profile(self, project_id: UUID, profile_id: UUID) -> StyleProfileVersion:
        record = self._reads.aggregate(project_id, kind="style_profile", resource_id=profile_id)
        if not isinstance(record.payload, StyleProfileVersion):
            raise SyntheticLabNotFound("Style Profile payload type changed")
        return record.payload

    def _manual_service(self) -> PostgresManualImportService:
        if self._manual_imports is None:
            raise SyntheticLabPersistenceError(
                "manual import encryption or object storage is unavailable"
            )
        return self._manual_imports


def build_manual_import_service(
    connection_factory: Callable[[], Any],
) -> PostgresManualImportService | None:
    keyring_path = os.getenv("GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE", "").strip()
    if not keyring_path or not os.getenv("OBJECT_STORE_ENDPOINT", "").strip():
        return None
    keyring = load_synthetic_artifact_keyring(keyring_path)
    synchronize_artifact_master_key_canaries(connection_factory, keyring)
    return PostgresManualImportService(
        connection_factory=connection_factory,
        artifacts=EncryptedManualImportArtifactStore(
            object_store=build_object_store(),
            keyring=keyring,
        ),
    )


__all__ = ["PostgresSyntheticResourceApiMixin", "build_manual_import_service"]
