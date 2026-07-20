"""Historical statistics-v2 snapshots remain exportable but unrecalculable."""

from __future__ import annotations

from dataclasses import replace
import json

from geo_core.project_exports import (
    AdminProjectExportInput,
    ProjectExportScope,
    build_project_export,
    metric_result_hash,
    recalculate_project_export,
)
from tests.unit.project_exports.test_project_export_core import (
    CAMPAIGN_ID,
    GENERATED_AT,
    PROJECT_ID,
    _current_snapshot,
    _data,
    _stratum_value,
)


def test_f027_recalc_01_historical_v2_without_membership_is_explicitly_unrecalculable() -> None:
    data = _data()
    historical = replace(
        _current_snapshot(data),
        observation_membership_version=None,
        observation_membership_count=None,
        observation_membership_hash=None,
    )
    historical = replace(
        historical,
        result_hash=metric_result_hash(historical, _stratum_value()),
    )
    source = AdminProjectExportInput(
        ProjectExportScope(PROJECT_ID, CAMPAIGN_ID),
        replace(
            data,
            metric_snapshots=(historical,),
            metric_observation_memberships=(),
        ),
    )
    bundle = build_project_export(source, generated_at=GENERATED_AT)
    exported = json.loads(bundle.file("project-export.json"))["metric_snapshots"][0]

    assert exported["observation_memberships"] is None
    result = recalculate_project_export(bundle.as_mapping())
    assert result.metrics == ()
    assert result.unrecalculable[0].reason == (
        "historical_statistics_v2_has_no_frozen_observation_membership"
    )
