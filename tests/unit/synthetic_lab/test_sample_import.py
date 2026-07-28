from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.synthetic_lab import (
    ManualSampleImportRequest,
    ManualSampleRow,
    SampleDedupStatus,
    SampleSourceRights,
    SyntheticLabContractError,
    build_manual_import_manifest,
    manual_import_input_hash,
    manual_import_manifest_hash,
)


NOW = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row(row_number: int, **changes: object) -> ManualSampleRow:
    values: dict[str, object] = {
        "row_number": row_number,
        "sample_id": uuid4(),
        "source_locator_hash": _hash(f"source-url-{row_number}"),
        "source_artifact_hash": _hash(f"source-artifact-{row_number}"),
        "normalized_text_hash": _hash(f"anonymous-au-text-{row_number}"),
        "text_length": 120,
        "au_english_declared": True,
        "language_reviewer_id": uuid4(),
        "language_reviewed_at": NOW,
        "anonymization_verified": True,
        "unresolved_pii_codes": (),
        "dedup_status": SampleDedupStatus.UNIQUE,
        "nearest_sample_hash": None,
        "source_rights": SampleSourceRights.AUTHORIZED_MANUAL_CAPTURE,
        "rights_evidence_hash": _hash(f"rights-{row_number}"),
        "source_overlap_ratio": 0.1,
        "reproduction_risk": False,
    }
    values.update(changes)
    return ManualSampleRow(**values)  # type: ignore[arg-type]


def _request(
    rows: tuple[ManualSampleRow, ...],
    *,
    project_id: UUID | None = None,
    **changes: object,
) -> ManualSampleImportRequest:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": project_id or uuid4(),
        "channel": "reddit",
        "locale": "en-AU",
        "style_source_revision_id": uuid4(),
        "source_revision_number": 1,
        "collection_run_id": uuid4(),
        "imported_by": uuid4(),
        "imported_at": NOW,
        "schema_release": "manual-style-import-v1",
        "submitted_field_names": (
            "source_locator",
            "source_artifact",
            "anonymous_text",
            "source_rights",
        ),
        "rows": rows,
    }
    values.update(changes)
    return ManualSampleImportRequest(**values)  # type: ignore[arg-type]


def _error_codes(manifest, row_number: int) -> set[str]:
    return {item.code for item in manifest.row_errors if item.row_number == row_number}


def test_manual_import_accepts_anonymous_reviewed_au_english_with_rights() -> None:
    request = _request((_row(1), _row(2)))
    manifest = build_manual_import_manifest(request, manifest_id=uuid4(), preview_id=uuid4())

    assert manifest.row_count == 2
    assert manifest.accepted_count == 2
    assert manifest.rejected_count == 0
    assert manifest.duplicate_row_count == 0
    assert manifest.row_errors == ()
    assert all(item.anonymized and item.au_english for item in manifest.accepted_samples)
    assert all(item.short_example_eligible for item in manifest.accepted_samples)
    assert manifest.input_hash == manual_import_input_hash(request)
    assert manifest.manifest_hash == manual_import_manifest_hash(manifest)


def test_import_hashes_are_deterministic_and_manifest_is_immutable() -> None:
    request = _request((_row(1),))
    manifest_id = uuid4()
    preview_id = uuid4()
    first = build_manual_import_manifest(
        request, manifest_id=manifest_id, preview_id=preview_id
    )
    second = build_manual_import_manifest(
        request, manifest_id=manifest_id, preview_id=preview_id
    )

    assert first == second
    assert first.input_hash == second.input_hash
    assert first.manifest_hash == second.manifest_hash
    with pytest.raises(FrozenInstanceError):
        first.row_count = 0  # type: ignore[misc]
    with pytest.raises(SyntheticLabContractError):
        replace(first, row_count=2)


def test_au_english_requires_declaration_and_named_reviewer() -> None:
    request = _request(
        (
            _row(
                1,
                au_english_declared=False,
                language_reviewer_id=None,
                language_reviewed_at=None,
            ),
        )
    )
    manifest = build_manual_import_manifest(request, manifest_id=uuid4(), preview_id=uuid4())

    assert manifest.accepted_count == 0
    assert _error_codes(manifest, 1) == {
        "au_english_not_declared",
        "language_review_missing",
    }


def test_unresolved_pii_or_missing_anonymization_rejects_row_without_raw_text() -> None:
    request = _request(
        (
            _row(
                1,
                anonymization_verified=False,
                unresolved_pii_codes=("email", "account_url"),
            ),
        )
    )
    manifest = build_manual_import_manifest(request, manifest_id=uuid4(), preview_id=uuid4())

    assert manifest.accepted_count == 0
    assert _error_codes(manifest, 1) == {"anonymization_failed"}
    assert all("@" not in error.message for error in manifest.row_errors)


@pytest.mark.parametrize(
    "rights",
    [SampleSourceRights.UNKNOWN, SampleSourceRights.RESTRICTED],
)
def test_unknown_or_restricted_source_rights_do_not_enter_samples(
    rights: SampleSourceRights,
) -> None:
    request = _request((_row(1, source_rights=rights, rights_evidence_hash=None),))
    manifest = build_manual_import_manifest(request, manifest_id=uuid4(), preview_id=uuid4())

    assert manifest.accepted_count == 0
    assert _error_codes(manifest, 1) == {"source_rights_ineligible"}


def test_exact_near_cross_run_and_in_batch_duplicates_are_row_errors() -> None:
    first = _row(1)
    same_hash = _row(2, normalized_text_hash=first.normalized_text_hash)
    near = _row(
        3,
        dedup_status=SampleDedupStatus.NEAR_DUPLICATE,
        nearest_sample_hash=first.normalized_text_hash,
    )
    cross_run = _row(
        4,
        dedup_status=SampleDedupStatus.CROSS_RUN_DUPLICATE,
        nearest_sample_hash=_hash("prior-run-sample"),
    )
    request = _request((first, same_hash, near, cross_run))
    manifest = build_manual_import_manifest(request, manifest_id=uuid4(), preview_id=uuid4())

    assert manifest.accepted_count == 1
    assert manifest.rejected_count == 3
    assert manifest.duplicate_row_count == 3
    assert _error_codes(manifest, 2) == {"duplicate_exact_in_batch"}
    assert _error_codes(manifest, 3) == {"duplicate_near_duplicate"}
    assert _error_codes(manifest, 4) == {"duplicate_cross_run_duplicate"}


def test_long_high_overlap_or_reproduction_risk_sample_is_kept_but_never_a_short_example() -> None:
    request = _request(
        (
            _row(
                1,
                text_length=500,
                source_overlap_ratio=0.8,
                reproduction_risk=True,
            ),
        )
    )
    manifest = build_manual_import_manifest(request, manifest_id=uuid4(), preview_id=uuid4())
    sample = manifest.accepted_samples[0]

    assert manifest.accepted_count == 1
    assert not sample.short_example_eligible
    assert set(sample.short_example_exclusion_codes) == {
        "too_long_for_short_example",
        "source_overlap_too_high",
        "source_reproduction_risk",
    }


@pytest.mark.parametrize(
    ("text_length", "eligible"),
    ((240, True), (241, False)),
)
def test_short_example_character_boundary_is_exact(
    text_length: int, eligible: bool
) -> None:
    manifest = build_manual_import_manifest(
        _request((_row(1, text_length=text_length),)),
        manifest_id=uuid4(),
        preview_id=uuid4(),
    )

    sample = manifest.accepted_samples[0]
    assert sample.short_example_eligible is eligible
    assert ("too_long_for_short_example" in sample.short_example_exclusion_codes) is (
        not eligible
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "cookie",
        "authorization_header",
        "session_token",
        "password",
        "secret_reference_value",
        "storage_state",
    ],
)
def test_manual_import_schema_rejects_credential_fields_before_row_processing(
    field_name: str,
) -> None:
    with pytest.raises(SyntheticLabContractError, match="credential fields"):
        _request(
            (_row(1),),
            submitted_field_names=("anonymous_text", field_name),
        )


def test_partial_manifest_accounts_for_every_row_with_stable_safe_errors() -> None:
    request = _request(
        (
            _row(1),
            _row(2, au_english_declared=False),
            _row(3, source_rights=SampleSourceRights.UNKNOWN),
        )
    )
    manifest = build_manual_import_manifest(request, manifest_id=uuid4(), preview_id=uuid4())

    assert manifest.accepted_count == 1
    assert manifest.rejected_count == 2
    assert len({error.row_number for error in manifest.row_errors}) == 2
    assert all(len(error.evidence_hash) == 64 for error in manifest.row_errors)
    assert all(
        error.message and "anonymous-au-text" not in error.message for error in manifest.row_errors
    )


def test_manual_import_objects_remain_synthetic_test_only_and_nonpublication() -> None:
    request = _request((_row(1), _row(2, au_english_declared=False)))
    manifest = build_manual_import_manifest(request, manifest_id=uuid4(), preview_id=uuid4())
    resources = (
        request,
        *request.rows,
        manifest,
        *manifest.accepted_samples,
        *manifest.row_errors,
    )

    assert all(item.synthetic and item.test_only for item in resources)
    assert not any(item.publication_eligible for item in resources)
