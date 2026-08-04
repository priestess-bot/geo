"""Allowlist-only presenters for Admin-visible Synthetic Lab resources."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar, cast

from geo_api.synthetic_lab_contracts import (
    AuthorizationPageResponse,
    AuthorizationResponse,
    AuthorizationState,
    Channel,
    ImportedSampleOptionPageResponse,
    ImportedSampleOptionResponse,
    JobKind,
    ManualImportPreviewPageResponse,
    ManualImportPreviewResponse,
    ManualImportPreviewRowResponse,
    ManualImportPreviewSummaryResponse,
    ManualImportRowErrorResponse,
    ManualSampleImportResponse,
    ReviewCasePageResponse,
    ReviewCaseResponse,
    ReviewSuitePageResponse,
    ReviewSuiteResponse,
    StyleProfilePageResponse,
    StyleProfileResponse,
    StyleSourcePageResponse,
    StyleSourceResponse,
    SyntheticResourceInventoryResponse,
    SyntheticResourceOptionResponse,
    StyleCollectionAdmissionResponse,
    SyntheticJobPageResponse,
    SyntheticJobResponse,
)


_ResponseT = TypeVar("_ResponseT")
_MISSING = object()
_NO_DEFAULT = object()


def authorization_response(item: object) -> AuthorizationResponse:
    value, replayed = _unwrap(item)
    state = _enum_value(_field(value, "state"))
    expires_at = _field(value, "expires_at", None)
    expiry = expires_at
    if isinstance(expiry, str):
        try:
            expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        except ValueError:
            expiry = None
    effective_state = (
        "expired"
        if state == "approved"
        and isinstance(expiry, datetime)
        and expiry <= datetime.now(UTC)
        else state
    )
    return AuthorizationResponse(
        id=_field(value, "id"),
        project_id=_field(value, "project_id"),
        channel=cast(Channel, _enum_value(_field(value, "channel"))),
        adapter_release=_field(value, "adapter_release"),
        version_number=_field(value, "version_number"),
        state=state,
        effective_state=cast(AuthorizationState, effective_state),
        evidence_reference_hash=_field(value, "evidence_reference_hash", None),
        allowed_purposes=list(_field(value, "allowed_purposes", ())),
        max_requests_per_period=_field(value, "max_requests_per_period", None),
        period_seconds=_field(value, "period_seconds", None),
        max_concurrency=_field(value, "max_concurrency", None),
        expires_at=expires_at,
        record_hash=_field(value, "record_hash"),
        replayed=replayed,
    )


def style_source_response(item: object) -> StyleSourceResponse:
    value, replayed = _unwrap(item)
    return StyleSourceResponse(
        id=_field(value, "id"),
        project_id=_field(value, "project_id"),
        source_id=_field(value, "source_id"),
        revision_number=_field(value, "revision_number"),
        channel=cast(Channel, _enum_value(_field(value, "channel"))),
        access_mode=_enum_value(_field(value, "access_mode")),
        locale=_field(value, "locale"),
        source_locator_hash=_field(value, "source_locator_hash"),
        status=_enum_value(_field(value, "status")),
        replayed=replayed,
    )


def manual_import_response(item: object) -> ManualSampleImportResponse:
    value, replayed = _unwrap(item)
    errors = [
        ManualImportRowErrorResponse(
            row_number=_field(error, "row_number"),
            code=_field(error, "code"),
            message=_field(error, "message"),
            evidence_hash=_field(error, "evidence_hash"),
        )
        for error in _field(value, "row_errors", ())
    ]
    accepted = _field(value, "accepted_count", _MISSING)
    if accepted is _MISSING:
        accepted = len(_field(value, "accepted_samples", ()))
    rejected = _field(value, "rejected_count", _MISSING)
    if rejected is _MISSING:
        rejected = _field(value, "row_count") - accepted
    return ManualSampleImportResponse(
        id=_field(value, "id"),
        project_id=_field(value, "project_id"),
        request_id=_field(value, "request_id"),
        channel=cast(Channel, _enum_value(_field(value, "channel"))),
        locale=_field(value, "locale"),
        row_count=_field(value, "row_count"),
        accepted_count=accepted,
        rejected_count=rejected,
        duplicate_row_count=_field(value, "duplicate_row_count"),
        input_hash=_field(value, "input_hash"),
        manifest_hash=_field(value, "manifest_hash"),
        row_errors=errors,
        replayed=replayed,
    )


def manual_import_preview_summary(item: object) -> ManualImportPreviewSummaryResponse:
    record, replayed = _unwrap(item)
    preview = _field(record, "preview", record)
    expires_at = _field(preview, "expires_at")
    status = _enum_value(_field(record, "status", "pending"))
    if status == "pending" and isinstance(expires_at, datetime) and expires_at <= datetime.now(UTC):
        status = "expired"
    rows = tuple(_field(preview, "rows"))
    return ManualImportPreviewSummaryResponse(
        id=_field(preview, "preview_id", _field(record, "id", None)),
        project_id=_field(preview, "project_id"),
        style_source_revision_id=_field(preview, "style_source_revision_id"),
        channel=cast(Channel, _enum_value(_field(preview, "channel"))),
        filename=_field(preview, "filename"),
        import_format=_enum_value(_field(preview, "import_format")),
        status=status,
        version=_field(record, "version", 1),
        submitted_by=_field(preview, "submitted_by"),
        submitted_at=_field(preview, "submitted_at"),
        expires_at=expires_at,
        row_count=_field(record, "row_count", len(rows)),
        selectable_count=_field(
            record,
            "selectable_count",
            sum(bool(_field(row, "selectable")) for row in rows),
        ),
        blocked_count=_field(
            record,
            "blocked_count",
            sum(not bool(_field(row, "selectable")) for row in rows),
        ),
        preview_manifest_hash=_field(preview, "preview_manifest_hash"),
        replayed=replayed,
    )


def manual_import_preview_response(item: object) -> ManualImportPreviewResponse:
    record, replayed = _unwrap(item)
    preview = _field(record, "preview", record)
    summary = manual_import_preview_summary(record)
    return ManualImportPreviewResponse(
        **summary.model_dump(exclude={"replayed"}),
        rows=[
            ManualImportPreviewRowResponse(
                row_number=_field(row, "row_number"),
                redacted_text=_field(row, "redacted_text"),
                source_rights=_enum_value(_field(row, "source_rights")),
                detected_codes=list(_field(row, "detected_codes")),
                blocking_codes=list(_field(row, "blocking_codes")),
                disposition=_enum_value(_field(row, "disposition")),
                selectable=bool(_field(row, "selectable")),
            )
            for row in _field(preview, "rows")
        ],
        replayed=replayed,
    )


def imported_sample_option_response(item: object) -> ImportedSampleOptionResponse:
    return ImportedSampleOptionResponse(
        id=_field(item, "id"),
        channel=cast(Channel, _enum_value(_field(item, "channel"))),
        source_rights=_enum_value(_field(item, "source_rights")),
        short_example_eligible=_field(item, "short_example_eligible"),
        created_at=_field(item, "created_at"),
        display_label=_field(item, "display_label"),
    )


def resource_inventory_response(item: object) -> SyntheticResourceInventoryResponse:
    def options(name: str) -> list[SyntheticResourceOptionResponse]:
        return [
            SyntheticResourceOptionResponse(
                id=_field(option, "id"),
                label=_field(option, "label"),
                kind=_field(option, "kind"),
                status=_field(option, "status"),
                channel=_field(option, "channel", None),
            )
            for option in _field(item, name, ())
        ]

    return SyntheticResourceInventoryResponse(
        samples=options("samples"),
        prompt_bindings=options("prompt_bindings"),
        question_sets=options("question_sets"),
        fact_snapshots=options("fact_snapshots"),
        profiles=options("profiles"),
        review_jobs=options("review_jobs"),
        candidate_corpora=options("candidate_corpora"),
        approved_corpora=options("approved_corpora"),
    )


def profile_response(item: object) -> StyleProfileResponse:
    value, replayed = _unwrap(item)
    state_version = _field(value, "state_version", None)
    build_verification_status = _field(value, "build_verification_status", None)
    rebuild_required = bool(_field(value, "rebuild_required", False))
    value = _field(value, "payload", value)
    return StyleProfileResponse(
        id=_field(value, "id"),
        project_id=_field(value, "project_id"),
        profile_id=_field(value, "profile_id"),
        version_number=_field(value, "version_number"),
        state_version=state_version or _field(value, "version_number"),
        channel=cast(Channel, _enum_value(_field(value, "channel"))),
        locale=_field(value, "locale"),
        corpus_hash=_field(value, "corpus_hash"),
        profile_hash=_field(value, "profile_hash"),
        prompt_release_id=_field(value, "prompt_release_id"),
        prompt_release_hash=_field(value, "prompt_release_hash"),
        approved_sample_count=_field(value, "approved_sample_count"),
        status=_enum_value(_field(value, "status")),
        build_verification_status=build_verification_status,
        rebuild_required=rebuild_required,
        replayed=replayed,
    )


def suite_response(item: object) -> ReviewSuiteResponse:
    value, replayed = _unwrap(item)
    state_version = _field(value, "state_version", None)
    value = _field(value, "payload", value)
    return ReviewSuiteResponse(
        id=_field(value, "id"),
        project_id=_field(value, "project_id"),
        suite_id=_field(value, "suite_id"),
        version_number=_field(value, "version_number"),
        state_version=state_version or _field(value, "version_number"),
        channel=cast(Channel, _enum_value(_field(value, "channel"))),
        case_count=_field(value, "case_count"),
        case_set_hash=_field(value, "case_set_hash"),
        status=_enum_value(_field(value, "status")),
        replayed=replayed,
    )


def case_response(item: object) -> ReviewCaseResponse:
    value, replayed = _unwrap(item)
    state_version = _field(value, "state_version", None)
    value = _field(value, "payload", value)
    return ReviewCaseResponse(
        id=_field(value, "id"),
        project_id=_field(value, "project_id"),
        review_suite_version_id=_field(value, "review_suite_version_id"),
        review_suite_version_number=_field(value, "review_suite_version_number"),
        state_version=state_version or 1,
        case_key=_field(value, "case_key"),
        ordinal=_field(value, "ordinal"),
        mode=_enum_value(_field(value, "mode")),
        channel=cast(Channel, _enum_value(_field(value, "channel"))),
        competitor_scenario=_field(value, "competitor_scenario"),
        content_hash=_field(value, "content_hash"),
        replayed=replayed,
    )


def job_response(item: object) -> SyntheticJobResponse:
    value, replayed = _unwrap(item)
    warning_summary = _field(value, "warning_summary", None)
    nested_job = _field(value, "job", _MISSING)
    if nested_job is not _MISSING:
        if nested_job is None:
            raise ValueError("Synthetic Lab command did not create a Job")
        value = nested_job
    durable = _field(value, "durable", None)
    result_hash = _field(value, "result_hash", None)
    if result_hash is None and durable is not None:
        result_hash = _field(durable, "result_ref", None)
    if isinstance(result_hash, str) and result_hash.startswith("synthetic://result/"):
        result_hash = result_hash.removeprefix("synthetic://result/")
    kind = _enum_value(_field(value, "kind"))
    public_kind = {
        "style.profile.build": "style_profile_build",
        "review.case.run": "candidate_generation",
        "corpus.finalize": "corpus_finalize",
        "offline_experiment.run": "offline_experiment",
    }.get(kind, kind)
    return SyntheticJobResponse(
        id=_field(value, "id"),
        project_id=_field(value, "project_id"),
        kind=cast(JobKind, public_kind),
        status=_enum_value(_field(value, "status")),
        version=_field(value, "version"),
        input_hash=_field(value, "input_hash"),
        fencing_generation=_field(value, "fencing_token", 0),
        cancel_requested=_field(value, "cancel_requested", False),
        result_hash=result_hash,
        warning_summary=warning_summary,
        replayed=replayed,
    )


def style_collection_admission_response(item: object) -> StyleCollectionAdmissionResponse:
    value, _replayed = _unwrap(item)
    nested = _field(value, "job", None)
    return StyleCollectionAdmissionResponse(
        disposition=_enum_value(_field(value, "disposition")),
        reason_code=_field(value, "reason_code"),
        may_issue_network_request=_field(value, "may_issue_network_request"),
        job=job_response(nested) if nested is not None else None,
    )


def authorization_page(page: object) -> AuthorizationPageResponse:
    return _page(page, authorization_response, AuthorizationPageResponse)


def style_source_page(page: object) -> StyleSourcePageResponse:
    return _page(page, style_source_response, StyleSourcePageResponse)


def manual_import_preview_page(page: object) -> ManualImportPreviewPageResponse:
    return _page(page, manual_import_preview_summary, ManualImportPreviewPageResponse)


def imported_sample_option_page(page: object) -> ImportedSampleOptionPageResponse:
    return _page(page, imported_sample_option_response, ImportedSampleOptionPageResponse)


def profile_page(page: object) -> StyleProfilePageResponse:
    return _page(page, profile_response, StyleProfilePageResponse)


def suite_page(page: object) -> ReviewSuitePageResponse:
    return _page(page, suite_response, ReviewSuitePageResponse)


def case_page(page: object) -> ReviewCasePageResponse:
    return _page(page, case_response, ReviewCasePageResponse)


def job_page(page: object) -> SyntheticJobPageResponse:
    return _page(page, job_response, SyntheticJobPageResponse)


def _page(
    page: object,
    presenter: Callable[[object], _ResponseT],
    response_type: type[Any],
) -> Any:
    return response_type(
        items=[presenter(item) for item in _field(page, "items")],
        total=_field(page, "total"),
        limit=_field(page, "limit"),
        offset=_field(page, "offset"),
    )


def _unwrap(item: object) -> tuple[object, bool]:
    replayed = bool(_field(item, "replayed", False))
    result = _field(item, "result", _MISSING)
    return (result if result is not _MISSING else item), replayed


def _field(item: object, name: str, default: object = _NO_DEFAULT) -> Any:
    if isinstance(item, Mapping):
        if name in item:
            return item[name]
    elif hasattr(item, name):
        return getattr(item, name)
    if default is not _NO_DEFAULT:
        return default
    raise ValueError(f"Synthetic Lab presenter requires safe field {name!r}")


def _enum_value(value: object) -> Any:
    return value.value if isinstance(value, Enum) else value


__all__ = [
    "authorization_page",
    "authorization_response",
    "case_page",
    "case_response",
    "job_response",
    "job_page",
    "imported_sample_option_page",
    "manual_import_preview_page",
    "manual_import_preview_response",
    "manual_import_preview_summary",
    "manual_import_response",
    "profile_page",
    "profile_response",
    "resource_inventory_response",
    "style_source_page",
    "style_source_response",
    "style_collection_admission_response",
    "suite_page",
    "suite_response",
]
