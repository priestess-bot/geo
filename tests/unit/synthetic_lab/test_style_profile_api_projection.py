from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geo_api.synthetic_lab_presenters import profile_response
from geo_core.synthetic_lab.domain import StyleProfileStatus, StyleProfileVersion
from geo_core.synthetic_lab.postgres_api_read_models import (
    StyleProfileAggregateView,
    SyntheticAggregateView,
)


@pytest.mark.parametrize(
    ("verification_status", "rebuild_required"),
    (("verified", False), ("legacy_unverified", True)),
)
def test_profile_response_exposes_build_verification(
    verification_status: str,
    rebuild_required: bool,
) -> None:
    profile = _profile()

    response = profile_response(
        StyleProfileAggregateView(
            payload=profile,
            state_version=3,
            build_verification_status=verification_status,
            rebuild_required=rebuild_required,
        )
    )

    assert response.state_version == 3
    assert response.build_verification_status == verification_status
    assert response.rebuild_required is rebuild_required


def test_unbuilt_profile_has_no_verification_and_does_not_require_rebuild() -> None:
    response = profile_response(SyntheticAggregateView(_profile(), 1))

    assert response.build_verification_status is None
    assert response.rebuild_required is False


def _profile() -> StyleProfileVersion:
    return StyleProfileVersion(
        id=uuid4(),
        project_id=uuid4(),
        profile_id=uuid4(),
        version_number=1,
        channel="reddit",
        locale="en-AU",
        corpus_hash="a" * 64,
        profile_hash="b" * 64,
        prompt_release_id=uuid4(),
        prompt_release_hash="c" * 64,
        approved_sample_count=200,
        status=StyleProfileStatus.FROZEN,
        reviewed_by=uuid4(),
        reviewed_at=datetime.now(UTC),
    )
