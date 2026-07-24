from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from geo_core.sampling import (
    AuthorizationState,
    CaptureMethod,
    SamplingAdmissionCommand,
    SamplingRuleViolation,
    SamplingSourceStratum,
    SamplingSuite,
    admit_sampling_suite,
)

from tests.unit.sampling.factories import NOW, digest, make_policy, make_run, make_suite


def test_provider_suite_freezes_exactly_ten_repeats_and_planned_tasks() -> None:
    suite = make_suite()
    grant, run, tasks = make_run(suite)

    assert suite.repetitions == 10
    assert suite.minimum_valid_repeats == 8
    assert suite.planned_task_count == 10
    assert len(tasks) == 10
    assert len({task.identity.task_key for task in tasks}) == 10
    assert tuple(sorted(task.identity.task_key for task in tasks)) == run.planned_task_keys
    assert run.admission_grant_hash == grant.grant_hash
    assert run.authorization_reference == grant.authorization_reference
    assert run.purpose == grant.purpose
    assert run.reserved_task_count == len(run.planned_task_keys)


@pytest.mark.parametrize("repetitions", [1, 3, 9, 11])
def test_provider_suite_rejects_non_default_repeat_counts(repetitions: int) -> None:
    with pytest.raises(SamplingRuleViolation, match="exactly 10"):
        make_suite(repetitions=repetitions)


def test_manual_suite_requires_at_least_three_repeats() -> None:
    with pytest.raises(SamplingRuleViolation, match="at least three"):
        make_suite(CaptureMethod.MANUAL_UI, repetitions=2)

    suite = make_suite(CaptureMethod.MANUAL_UI, repetitions=3)
    assert suite.minimum_valid_repeats == 3


def test_automated_ui_is_explicitly_ineligible_in_sampling_core() -> None:
    with pytest.raises(SamplingRuleViolation, match="Browser/Egress"):
        SamplingSourceStratum(
            platform="google",
            surface="ai-mode",
            configured_model="not_reported",
            reported_model="not_reported",
            capture_method=CaptureMethod.AUTOMATED_UI,
            adapter_release="surface-release-v1",
            locale="en-AU",
            region="AU",
            language="en",
            search_mode="enabled",
            account_cohort="clean-account",
            egress_policy_category="au-residential-v1",
            location_control="country",
            location_evidence_hash="a" * 64,
            requested_country="AU",
            requested_region=None,
            requested_locale="en-AU",
            requested_language="en",
            effective_country="AU",
            effective_region=None,
            effective_locale=None,
            effective_language=None,
        )


def test_api_stratum_uses_not_applicable_account_and_egress_dimensions() -> None:
    suite = make_suite(CaptureMethod.PROXY_GROUNDED_API)
    source = suite.source_stratum

    assert source.account_cohort == "not_applicable"
    assert source.egress_policy_category == "not_applicable"
    with pytest.raises(SamplingRuleViolation, match="account_cohort"):
        replace(source, account_cohort="consumer-account")


@pytest.mark.parametrize(
    ("policy_change", "message"),
    [
        ({"authorization_state": AuthorizationState.NOT_ASSESSED}, "not approved"),
        ({"authorized_purposes": ("style_research",)}, "purpose"),
        ({"quota_remaining": 9}, "quota"),
        ({"daily_task_limit": 9}, "daily budget"),
        ({"minimum_request_interval_seconds": 3}, "rate"),
        ({"max_concurrency": 1}, "concurrency"),
    ],
)
def test_admission_fails_closed_on_authorization_and_budget(
    policy_change: dict[str, object], message: str
) -> None:
    suite = make_suite()
    policy = replace(make_policy(suite), **policy_change)
    command = SamplingAdmissionCommand(
        idempotency_key="admission:test",
        purpose="geo_measurement",
        requested_at=NOW,
        requested_not_before=NOW,
    )

    with pytest.raises(SamplingRuleViolation, match=message):
        admit_sampling_suite(suite, policy=policy, command=command)


def test_admission_freezes_later_rate_limit_not_before() -> None:
    suite = make_suite()
    policy = make_policy(suite)
    command = SamplingAdmissionCommand(
        idempotency_key="admission:not-before",
        purpose="geo_measurement",
        requested_at=NOW,
        requested_not_before=NOW + timedelta(seconds=15),
    )

    grant = admit_sampling_suite(suite, policy=policy, command=command)

    assert grant.not_before == policy.next_allowed_at
    assert grant.reserved_task_count == suite.planned_task_count
    assert grant.suite_hash == suite.suite_hash


def test_admission_rejects_work_delayed_beyond_authorization_expiry() -> None:
    suite = make_suite()
    policy = make_policy(suite)
    policy = replace(policy, next_allowed_at=policy.valid_until)
    command = SamplingAdmissionCommand(
        idempotency_key="admission:too-late",
        purpose="geo_measurement",
        requested_at=NOW,
        requested_not_before=NOW,
    )

    with pytest.raises(SamplingRuleViolation, match="expires before"):
        admit_sampling_suite(suite, policy=policy, command=command)


def test_suite_hash_changes_for_any_stratum_dimension() -> None:
    suite = make_suite()
    changed_source = replace(suite.source_stratum, reported_model="gpt-5-mini-revision-2")
    changed = SamplingSuite(
        id=suite.id,
        project_id=suite.project_id,
        question_set_id=suite.question_set_id,
        question_set_version=suite.question_set_version,
        question_set_hash=digest("question-set"),
        adapter_release_id=suite.adapter_release_id,
        adapter_release_hash=suite.adapter_release_hash,
        model_release_id=suite.model_release_id,
        model_release_hash=suite.model_release_hash,
        route_policy_id=suite.route_policy_id,
        route_policy_hash=suite.route_policy_hash,
        runtime_manifest_id=suite.runtime_manifest_id,
        runtime_manifest_hash=suite.runtime_manifest_hash,
        runtime_option_id=suite.runtime_option_id,
        runtime_option_hash=suite.runtime_option_hash,
        admission_policy_id=suite.admission_policy_id,
        admission_policy_hash=suite.admission_policy_hash,
        questions=suite.questions,
        source_stratum=changed_source,
        repetitions=suite.repetitions,
        statistics_method_version=suite.statistics_method_version,
        max_planned_tasks=suite.max_planned_tasks,
        max_daily_tasks=suite.max_daily_tasks,
        minimum_request_interval_seconds=suite.minimum_request_interval_seconds,
        max_concurrency=suite.max_concurrency,
        frozen_by=suite.frozen_by,
        frozen_at=suite.frozen_at,
    )

    assert changed.source_stratum.stratum_hash != suite.source_stratum.stratum_hash
    assert changed.suite_hash != suite.suite_hash
