from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from geo_core.monitoring.official_reports import (
    OfficialReportImportDraft,
    OfficialReportRowDraft,
    OfficialReportRuleViolation,
    official_report_payload_hash,
)
from geo_core.monitoring.source_contract import (
    ObservationPlatform,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
)


def test_f009_domain_01_official_payload_hash_covers_parsed_rows() -> None:
    draft = _draft()
    first = (OfficialReportRowDraft(0, {"query": "first", "clicks": 3}),)
    changed = (OfficialReportRowDraft(0, {"query": "first", "clicks": 4}),)

    assert official_report_payload_hash(draft, first) != official_report_payload_hash(
        draft, changed
    )


def test_f009_domain_01_official_rows_are_canonical_and_unique() -> None:
    row = OfficialReportRowDraft(
        1,
        {"query": "unsupported"},
        eligible=False,
        ineligible_reasons=(" parser_failure ", "parser_failure"),
    )

    assert row.ineligible_reasons == ("parser_failure",)
    with pytest.raises(OfficialReportRuleViolation, match="indexes must be unique"):
        official_report_payload_hash(
            _draft(),
            (row, OfficialReportRowDraft(1, {"query": "duplicate"})),
        )


def test_f009_domain_01_eligible_official_row_cannot_carry_exclusion_reasons() -> None:
    with pytest.raises(OfficialReportRuleViolation, match="cannot carry"):
        OfficialReportRowDraft(
            0, {"query": "valid"}, eligible=True,
            ineligible_reasons=("operator_exclusion",),
        )


def test_f009_domain_01_official_report_rejects_unsupported_platform() -> None:
    draft = _draft()

    with pytest.raises(OfficialReportRuleViolation, match="supported official"):
        OfficialReportImportDraft(
            campaign_id=draft.campaign_id,
            platform=ObservationPlatform.OPENAI,
            surface=ObservationSurface.OTHER,
            platform_detail=None,
            surface_detail="custom report",
            artifact=draft.artifact,
            parser_name=draft.parser_name,
            parser_version=draft.parser_version,
            report_period_start=draft.report_period_start,
            report_period_end=draft.report_period_end,
            account_ref=draft.account_ref,
        )


def _draft() -> OfficialReportImportDraft:
    return OfficialReportImportDraft(
        campaign_id=uuid4(),
        platform=ObservationPlatform.GOOGLE,
        surface=ObservationSurface.GOOGLE_GENERATIVE_AI_PERFORMANCE_REPORT,
        platform_detail=None,
        surface_detail=None,
        artifact=RawEvidence(
            RawEvidenceKind.ARTIFACT,
            artifact_uri="s3://geo-artifacts/observation-artifacts/project/report.csv",
            artifact_hash="a" * 64,
            artifact_verified=True,
        ),
        parser_name="google-ai-performance-csv",
        parser_version="1.0.0",
        report_period_start=date(2026, 6, 1),
        report_period_end=date(2026, 6, 30),
        account_ref="account-1",
    )
