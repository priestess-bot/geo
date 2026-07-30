from __future__ import annotations

import pytest

from scripts.publish_prompt_bootstrap_suites import (
    PromptSuiteError,
    child_key,
    matching_run,
    require_passing_terminal,
)


def test_child_key_changes_with_the_draft_revision() -> None:
    from uuid import UUID

    project_id = UUID("00000000-0000-4000-8000-000000000001")
    first = child_key(project_id, "monitoring.metric_judge", "suite-r1")
    second = child_key(project_id, "monitoring.metric_judge", "suite-r2")

    assert first != second
    assert child_key(project_id, "monitoring.metric_judge", "suite-r2") == second


def test_matching_run_uses_the_exact_job_identity() -> None:
    rows = [{"job_id": "first", "status": "succeeded"}, {"job_id": "second"}]
    assert matching_run(rows, "first") == rows[0]
    assert matching_run(rows, "missing") is None


def test_only_a_successful_passing_suite_can_publish() -> None:
    require_passing_terminal(
        {"status": "succeeded", "passed": True, "score": 100}, purpose="example"
    )
    with pytest.raises(PromptSuiteError, match="did not pass"):
        require_passing_terminal(
            {"status": "succeeded", "passed": False, "score": 80}, purpose="example"
        )
    with pytest.raises(PromptSuiteError, match="dead_lettered"):
        require_passing_terminal(
            {"status": "dead_lettered", "error_code": "provider_error"}, purpose="example"
        )
