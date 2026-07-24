from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
import hashlib
from uuid import UUID, uuid4

import pytest

from geo_core.synthetic_lab import (
    CollectionRun,
    CollectionRunStatus,
    ReviewCase,
    ReviewSuite,
    ReviewSuiteStatus,
    ScenarioMode,
    StyleAccessMode,
    StyleProfileStatus,
    StyleProfileVersion,
    StyleSample,
    StyleSampleReviewStatus,
    StyleSource,
    StyleSourceStatus,
    SyntheticLabContractError,
    SyntheticLabScopeError,
    SyntheticLabTransitionError,
    assert_collection_run_lineage,
    assert_next_profile_version,
    assert_next_review_suite_version,
    assert_next_style_source_revision,
    assert_profile_sample_set,
    assert_review_suite_case_set,
    assert_style_sample_lineage,
    assert_synthetic_boundary,
    review_case_content_hash,
    review_case_set_hash,
    style_sample_manifest_hash,
    transition_collection_run,
    transition_review_suite,
    transition_style_profile,
    transition_style_sample_review,
    transition_style_source,
)


NOW = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source(*, project_id: UUID | None = None, **changes: object) -> StyleSource:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": project_id or uuid4(),
        "source_id": uuid4(),
        "revision_number": 1,
        "channel": "reddit",
        "access_mode": StyleAccessMode.PUBLIC,
        "locale": "en-AU",
        "source_locator_hash": _hash("https://www.reddit.com/r/australia/example"),
    }
    values.update(changes)
    return StyleSource(**values)  # type: ignore[arg-type]


def _run(source: StyleSource, **changes: object) -> CollectionRun:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": source.project_id,
        "style_source_revision_id": source.id,
        "source_revision_number": source.revision_number,
        "source_locator_hash": source.source_locator_hash,
        "adapter_release": "manual-import-v1",
    }
    values.update(changes)
    return CollectionRun(**values)  # type: ignore[arg-type]


def _sample(
    source: StyleSource,
    run: CollectionRun,
    *,
    index: int = 1,
    approved: bool = False,
    **changes: object,
) -> StyleSample:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": source.project_id,
        "collection_run_id": run.id,
        "style_source_revision_id": source.id,
        "source_revision_number": source.revision_number,
        "channel": source.channel,
        "locale": source.locale,
        "content_hash": _hash(f"anonymous-sample-{index}"),
        "is_anonymized": True,
        "is_au_english": True,
    }
    if approved:
        values.update(
            {
                "review_status": StyleSampleReviewStatus.APPROVED,
                "reviewed_by": uuid4(),
                "reviewed_at": NOW,
            }
        )
    values.update(changes)
    return StyleSample(**values)  # type: ignore[arg-type]


def _profile(
    project_id: UUID,
    samples: tuple[StyleSample, ...],
    **changes: object,
) -> StyleProfileVersion:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": project_id,
        "profile_id": uuid4(),
        "version_number": 1,
        "channel": "reddit",
        "locale": "en-AU",
        "corpus_hash": style_sample_manifest_hash(samples),
        "profile_hash": _hash("reddit-profile-v1"),
        "prompt_release_id": uuid4(),
        "prompt_release_hash": _hash("style-profile-prompt-v1"),
        "approved_sample_count": len(samples),
    }
    values.update(changes)
    return StyleProfileVersion(**values)  # type: ignore[arg-type]


def _case(
    *,
    project_id: UUID,
    suite_version_id: UUID,
    suite_version_number: int = 1,
    ordinal: int = 1,
    mode: ScenarioMode = ScenarioMode.AUTONOMOUS,
    **changes: object,
) -> ReviewCase:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": project_id,
        "review_suite_version_id": suite_version_id,
        "review_suite_version_number": suite_version_number,
        "case_key": f"reddit-case-{ordinal}",
        "ordinal": ordinal,
        "mode": mode,
        "channel": "reddit",
        "persona": "Australian home workshop owner",
        "use_case": "compare two compact pressure washers",
        "subject": "Acme PW-20",
        "question_set_version_id": uuid4(),
        "question_set_hash": _hash("question-set-v1"),
        "fact_snapshot_id": uuid4(),
        "fact_snapshot_hash": _hash("facts-v1"),
        "profile_version_id": uuid4(),
        "profile_hash": _hash("reddit-profile-v1"),
        "competitor_scenario": True,
        "expected_risks": ("subject_mix", "unsupported_claim"),
        "creative_reference": "Focus on a small garage." if mode == ScenarioMode.GUIDED else None,
    }
    values.update(changes)
    hash_fields = {
        key: values[key]
        for key in (
            "case_key",
            "ordinal",
            "mode",
            "channel",
            "persona",
            "use_case",
            "subject",
            "question_set_version_id",
            "question_set_hash",
            "fact_snapshot_id",
            "fact_snapshot_hash",
            "profile_version_id",
            "profile_hash",
            "competitor_scenario",
            "expected_risks",
            "creative_reference",
        )
    }
    values.setdefault("content_hash", review_case_content_hash(**hash_fields))  # type: ignore[arg-type]
    return ReviewCase(**values)  # type: ignore[arg-type]


def test_style_source_identity_is_frozen_and_revision_history_is_contiguous() -> None:
    first = _source()
    active = transition_style_source(first, command="activate")

    assert first.status == StyleSourceStatus.DRAFT
    assert active.status == StyleSourceStatus.ACTIVE
    assert active.id == first.id
    with pytest.raises(FrozenInstanceError):
        first.id = uuid4()  # type: ignore[misc]

    second = replace(first, id=uuid4(), revision_number=2, source_locator_hash=_hash("v2"))
    assert_next_style_source_revision(first, second)
    with pytest.raises(SyntheticLabContractError, match="contiguous"):
        assert_next_style_source_revision(first, replace(second, revision_number=3))
    with pytest.raises(SyntheticLabScopeError, match="identity"):
        assert_next_style_source_revision(first, replace(second, source_id=uuid4()))
    with pytest.raises(SyntheticLabTransitionError, match="not allowed"):
        transition_style_source(
            replace(first, status=StyleSourceStatus.RETIRED), command="activate"
        )


def test_collection_run_freezes_source_lineage_and_requires_terminal_evidence() -> None:
    source = _source()
    queued = _run(source)
    assert_collection_run_lineage(source, queued)

    running = transition_collection_run(queued, command="start")
    completed = transition_collection_run(
        running,
        command="complete",
        raw_manifest_hash=_hash("raw-manifest"),
    )

    assert queued.status == CollectionRunStatus.QUEUED
    assert completed.status == CollectionRunStatus.COMPLETED
    assert completed.id == queued.id
    with pytest.raises(SyntheticLabContractError, match="raw manifest"):
        transition_collection_run(running, command="complete")
    with pytest.raises(SyntheticLabTransitionError, match="not allowed"):
        transition_collection_run(completed, command="start")
    with pytest.raises(SyntheticLabScopeError, match="frozen Style Source"):
        assert_collection_run_lineage(source, replace(queued, source_revision_number=2))


def test_style_sample_review_is_human_attributed_terminal_and_project_scoped() -> None:
    source = _source()
    run = _run(source)
    pending = _sample(source, run)

    approved = transition_style_sample_review(
        pending,
        command="approve",
        reviewer_id=uuid4(),
        reviewed_at=NOW,
    )
    assert approved.review_status == StyleSampleReviewStatus.APPROVED
    assert_style_sample_lineage(source, run, approved)
    with pytest.raises(SyntheticLabTransitionError, match="terminal"):
        transition_style_sample_review(
            approved,
            command="reject",
            reviewer_id=uuid4(),
            reviewed_at=NOW,
        )

    unsafe = _sample(source, run, is_anonymized=False)
    with pytest.raises(SyntheticLabContractError, match="anonymized Australian English"):
        transition_style_sample_review(
            unsafe,
            command="approve",
            reviewer_id=uuid4(),
            reviewed_at=NOW,
        )
    with pytest.raises(SyntheticLabScopeError, match="different Projects"):
        assert_style_sample_lineage(source, run, replace(pending, project_id=uuid4()))


def test_profile_freeze_requires_200_unique_approved_samples_and_frozen_hash() -> None:
    source = _source()
    run = _run(source)
    samples = tuple(_sample(source, run, index=index, approved=True) for index in range(200))
    draft = _profile(source.project_id, samples)
    in_review = transition_style_profile(draft, command="submit")
    approved = transition_style_profile(
        in_review,
        command="approve",
        reviewer_id=uuid4(),
        reviewed_at=NOW,
    )
    frozen = transition_style_profile(approved, command="freeze", samples=samples)

    assert draft.status == StyleProfileStatus.DRAFT
    assert frozen.status == StyleProfileStatus.FROZEN
    assert frozen.id == draft.id
    assert_profile_sample_set(frozen, samples)

    with pytest.raises(SyntheticLabContractError, match="duplicate sample content"):
        duplicate_content = replace(samples[0], id=uuid4())
        assert_profile_sample_set(frozen, samples[:-1] + (duplicate_content,))
    with pytest.raises(SyntheticLabContractError, match="corpus"):
        assert_profile_sample_set(replace(frozen, corpus_hash=_hash("wrong")), samples)


def test_profile_versions_cannot_change_series_scope_or_skip_a_version() -> None:
    source = _source()
    run = _run(source)
    samples = (_sample(source, run, approved=True),)
    first = _profile(source.project_id, samples)
    second = replace(first, id=uuid4(), version_number=2, profile_hash=_hash("profile-v2"))

    assert_next_profile_version(first, second)
    with pytest.raises(SyntheticLabContractError, match="contiguous"):
        assert_next_profile_version(first, replace(second, version_number=3))
    with pytest.raises(SyntheticLabScopeError, match="different Projects"):
        assert_next_profile_version(first, replace(second, project_id=uuid4()))
    with pytest.raises(SyntheticLabScopeError, match="channel or locale"):
        assert_next_profile_version(first, replace(second, channel="quora"))


def test_review_case_hash_freezes_modes_fact_question_profile_and_rubric() -> None:
    project_id = uuid4()
    suite_version_id = uuid4()
    autonomous = _case(project_id=project_id, suite_version_id=suite_version_id)
    guided = _case(
        project_id=project_id,
        suite_version_id=suite_version_id,
        ordinal=2,
        mode=ScenarioMode.GUIDED,
    )

    assert autonomous.mode == ScenarioMode.AUTONOMOUS
    assert guided.creative_reference == "Focus on a small garage."
    with pytest.raises(SyntheticLabContractError, match="frozen hash"):
        replace(autonomous, fact_snapshot_hash=_hash("changed-facts"))
    with pytest.raises(SyntheticLabContractError, match="creative reference"):
        _case(
            project_id=project_id,
            suite_version_id=suite_version_id,
            creative_reference="Operator-provided claim",
        )
    with pytest.raises(SyntheticLabContractError, match="requires a creative reference"):
        _case(
            project_id=project_id,
            suite_version_id=suite_version_id,
            mode=ScenarioMode.GUIDED,
            creative_reference=None,
        )


def test_review_suite_freeze_verifies_case_set_project_and_version_lineage() -> None:
    project_id = uuid4()
    suite_version_id = uuid4()
    cases = tuple(
        _case(project_id=project_id, suite_version_id=suite_version_id, ordinal=index)
        for index in range(1, 4)
    )
    suite = ReviewSuite(
        id=suite_version_id,
        project_id=project_id,
        suite_id=uuid4(),
        version_number=1,
        channel="reddit",
        case_count=len(cases),
        case_set_hash=review_case_set_hash(cases),
    )

    frozen = transition_review_suite(suite, command="freeze", cases=cases)
    assert frozen.status == ReviewSuiteStatus.FROZEN
    assert_review_suite_case_set(frozen, cases)
    with pytest.raises(SyntheticLabTransitionError, match="not allowed"):
        transition_review_suite(frozen, command="freeze", cases=cases)
    with pytest.raises(SyntheticLabScopeError, match="different Projects"):
        assert_review_suite_case_set(
            suite,
            cases[:-1] + (replace(cases[-1], project_id=uuid4()),),
        )

    next_suite = replace(
        suite,
        id=uuid4(),
        version_number=2,
        case_set_hash=_hash("suite-v2"),
    )
    assert_next_review_suite_version(suite, next_suite)
    with pytest.raises(SyntheticLabContractError, match="contiguous"):
        assert_next_review_suite_version(suite, replace(next_suite, version_number=3))


def test_all_lab_resources_are_permanently_test_only_and_publication_ineligible() -> None:
    source = _source()
    run = _run(source)
    sample = _sample(source, run)
    profile = _profile(source.project_id, (sample,))
    suite_version_id = uuid4()
    case = _case(project_id=source.project_id, suite_version_id=suite_version_id)
    suite = ReviewSuite(
        id=suite_version_id,
        project_id=source.project_id,
        suite_id=uuid4(),
        version_number=1,
        channel="reddit",
        case_count=1,
        case_set_hash=review_case_set_hash((case,)),
    )

    resources = (source, run, sample, profile, suite, case)
    assert_synthetic_boundary(*resources)
    assert all(resource.synthetic for resource in resources)
    assert all(resource.test_only for resource in resources)
    assert not any(resource.publication_eligible for resource in resources)

    with pytest.raises(TypeError, match="publication_eligible"):
        StyleSource(
            id=uuid4(),
            project_id=uuid4(),
            source_id=uuid4(),
            revision_number=1,
            channel="reddit",
            access_mode=StyleAccessMode.PUBLIC,
            locale="en-AU",
            source_locator_hash=_hash("source"),
            publication_eligible=True,  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"revision_number": 0}, "positive"),
        ({"channel": "unknown"}, "unsupported style channel"),
        ({"locale": "en-US"}, "en-AU"),
        ({"source_locator_hash": "not-a-hash"}, "lowercase SHA-256"),
    ],
)
def test_style_source_rejects_invalid_versions_channels_locale_and_hashes(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(SyntheticLabContractError, match=message):
        _source(**changes)  # type: ignore[arg-type]
