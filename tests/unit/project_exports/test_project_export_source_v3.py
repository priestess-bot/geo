"""F027 source-stratum v3 export round-trip coverage."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import io
import json
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from geo_core.monitoring.source_contract import (
    ClientKind,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    SearchMode,
    SOURCE_CONTRACT_VERSION,
    SourceStratumKey,
)
from geo_core.monitoring.source_registry import (
    CaptureMethod,
    ObservationPlatform,
    ObservationSurface,
    SurfaceKind,
)
from geo_core.project_exports import (
    AdminProjectExportInput,
    METRIC_METHOD_VERSION,
    ProjectExportData,
    ProjectExportScope,
    ProtocolExportRecord,
    build_project_export,
    recalculate_project_export,
)
from geo_core.project_exports.monitoring_adapter import source_stratum_record


PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")
CAMPAIGN_ID = UUID("20000000-0000-4000-8000-000000000001")
PROTOCOL_ID = UUID("30000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)


def test_f027_source_v3_other_details_round_trip_through_json_csv_and_hashes() -> None:
    source = _other_source()
    record = source_stratum_record(
        cast(
            Any,
            SimpleNamespace(
                id=PROTOCOL_ID,
                project_id=PROJECT_ID,
                campaign_id=CAMPAIGN_ID,
            ),
        ),
        source,
    )
    protocol = ProtocolExportRecord(
        id=PROTOCOL_ID,
        project_id=PROJECT_ID,
        campaign_id=CAMPAIGN_ID,
        name="OTHER source export",
        platform="other",
        locale="en-US",
        device="desktop",
        sample_size=3,
        window_days=28,
        status="frozen",
        protocol_hash="1" * 64,
        source_strata_hash=_canonical_hash([source.canonical_value()]),
        minimum_valid_repeats=3,
        statistics_method_version=METRIC_METHOD_VERSION,
        statistics_contract_version=METRIC_METHOD_VERSION,
        approved_at=NOW,
        frozen_at=NOW,
    )
    data = ProjectExportData(
        protocols=(protocol,),
        protocol_source_strata=(record,),
        queries=(),
        observations=(),
        citations=(),
        metric_snapshots=(),
        metric_observation_memberships=(),
        approved_reports=(),
        verified_urls=(),
    )

    bundle = build_project_export(
        AdminProjectExportInput(ProjectExportScope(PROJECT_ID, CAMPAIGN_ID), data),
        generated_at=NOW,
    )
    result = recalculate_project_export(bundle.as_mapping())
    value = json.loads(bundle.file("project-export.json"))
    exported = value["protocols"][0]["source_strata"][0]
    csv_row = list(
        csv.DictReader(
            io.StringIO(
                bundle.file("protocol_source_strata.csv").decode("utf-8"),
                newline="",
            )
        )
    )[0]

    assert result.metrics == ()
    assert exported["source_contract_version"] == SOURCE_CONTRACT_VERSION
    assert exported["platform_detail"] == "you-com"
    assert exported["surface_detail"] == "you-com-web"
    assert exported["source_stratum_hash"] == source.canonical_hash()
    assert csv_row["source_contract_version"] == SOURCE_CONTRACT_VERSION
    assert csv_row["platform_detail"] == "you-com"
    assert csv_row["surface_detail"] == "you-com-web"


def _other_source() -> SourceStratumKey:
    return SourceStratumKey(
        capture_method=CaptureMethod.MANUAL_UI,
        platform=ObservationPlatform.OTHER,
        platform_detail="you-com",
        surface=ObservationSurface.OTHER,
        surface_detail="you-com-web",
        surface_kind=SurfaceKind.OTHER,
        engine="you-search",
        configured_model=ModelIdentity(ModelIdentityState.NOT_DISCLOSED),
        reported_model=ModelIdentity(ModelIdentityState.NOT_DISCLOSED),
        locale="en-US",
        region="US",
        language="en",
        device=ObservationDevice.DESKTOP,
        client_kind=ClientKind.BROWSER,
        search_enabled=True,
        search_mode=SearchMode.LIVE_WEB,
    )


def _canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
