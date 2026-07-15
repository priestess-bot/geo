"""Measurement, customer projection and acceptance result assertions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Mapping

from geo_core.monitoring.domain import MonitoringReport
from geo_core.placements.domain import Measurement

from scripts.geo_acceptance.contracts import AcceptanceConfig, CHANNELS
from scripts.geo_acceptance.monitoring import (
    BaselineResult,
    FollowUpResult,
    run_t28_follow_up,
)
from scripts.geo_acceptance.placement import PlacementResult
from scripts.geo_acceptance.setup import AcceptanceSetup


@dataclass(frozen=True)
class ReportingResult:
    placement_measurement: Measurement
    follow_up: FollowUpResult
    report: MonitoringReport
    customer_metric_count: int
    customer_verified_url_count: int
    customer_approved_report_count: int


def run_reporting(
    setup: AcceptanceSetup,
    baseline: BaselineResult,
    placement: PlacementResult,
) -> ReportingResult:
    placement_measurement = setup.placement.record_measurement(
        project_id=setup.project_id,
        submission_id=placement.submission.id,
        monitoring_query_id=baseline.query.monitoring_query_id,
        measured_at=datetime.now(UTC),
        citation_present=True,
        recommendation_position=1,
        result_snapshot_uri=(
            f"s3://geo-artifacts/acceptance/{setup.suffix}/placement-result.json"
        ),
        metrics={"mode": "controlled_acceptance", "window": "t28"},
    )
    follow_up = run_t28_follow_up(
        setup,
        baseline,
        submitted_url=placement.submitted_url,
        submission_id=placement.submission.id,
    )
    report = baseline.application.generate_report(
        setup.owner,
        project_id=setup.project_id,
        metric_snapshot_id=follow_up.metric.id,
        title=f"Controlled GEO acceptance report {setup.suffix}",
    )
    report = baseline.application.approve_report(
        setup.owner, project_id=setup.project_id, report_id=report.id
    )
    customer_metrics = baseline.application.list_metrics(
        setup.customer, project_id=setup.project_id
    )
    customer_urls = baseline.application.list_verified_urls(
        setup.customer, project_id=setup.project_id
    )
    customer_reports = baseline.application.list_reports(
        setup.customer, project_id=setup.project_id, approved_only=True
    )
    if not customer_metrics or not customer_urls or not customer_reports:
        raise AssertionError("customer-safe metrics, verified URL and report are incomplete")
    if any(item.status != "approved" for item in customer_reports):
        raise AssertionError("customer projection exposed an unapproved report")
    return ReportingResult(
        placement_measurement,
        follow_up,
        report,
        len(customer_metrics),
        len(customer_urls),
        len(customer_reports),
    )


def build_result(
    config: AcceptanceConfig,
    setup: AcceptanceSetup,
    baseline: BaselineResult,
    placement: PlacementResult,
    reporting: ReportingResult,
) -> dict[str, object]:
    opportunities = setup.placement.list_opportunities(
        project_id=setup.project_id, campaign_id=setup.campaign.id
    )
    by_destination = {item.destination_id: item for item in opportunities}
    if set(by_destination) != {item.id for item in setup.destinations}:
        raise AssertionError("the persisted channel task matrix changed after creation")
    result: dict[str, object] = {
        "run_id": config.run_id,
        "mode": "live_deepseek" if config.live_deepseek else "deterministic",
        "project": {
            "tenant_id": setup.bootstrap.tenant_id,
            "project_id": setup.project_id,
            "owner_identity_id": setup.owner.identity_id,
            "reviewer_identity_id": setup.reviewer_identity_id,
            "customer_identity_id": setup.customer.identity_id,
            "brand_entity_id": setup.brand.id,
            "product_entity_id": setup.product.id,
            "market_profile_id": setup.market.id,
            "evidence_item_ids": [setup.fact.id, setup.experience.id],
        },
        "campaign": {
            "campaign_id": setup.campaign.id,
            "protocol_id": baseline.protocol.id,
            "monitoring_query_id": baseline.query.monitoring_query_id,
            "baseline_observation_id": baseline.observation.id,
            "baseline_metric_id": baseline.metric.id,
            "t28_observation_id": reporting.follow_up.observation.id,
            "t28_metric_id": reporting.follow_up.metric.id,
            "report_id": reporting.report.id,
        },
        "channels": [
            {
                "publication_channel": destination.publication_channel,
                "destination_id": destination.id,
                "opportunity_id": by_destination[destination.id].id,
                "task_status": by_destination[destination.id].status,
            }
            for destination in setup.destinations
        ],
        "placement": {
            "brief_version_id": placement.brief.id,
            "evidence_pack_attempt_id": placement.evidence_attempt.id,
            "prompt_binding_count": len(placement.prompt_bindings),
            "prompt_bundle_id": placement.prompt_bundle.id,
            "prompt_bundle_hash": placement.prompt_bundle.bundle_hash,
            "generation_job_id": placement.generation_job.id,
            "package_version_id": placement.package.id,
            "package_content_hash": placement.package.content_hash,
            "claim_ids": [item.id for item in placement.claims],
            "review_id": placement.review.id,
            "export_id": placement.export.id,
            "publication_request_id": placement.publication.id,
            "submission_id": placement.submission.id,
            "scheduled_measurement_offsets": list(placement.scheduled_windows),
            "placement_measurement_id": reporting.placement_measurement.id,
        },
        "customer_projection": {
            "metric_count": reporting.customer_metric_count,
            "verified_url_count": reporting.customer_verified_url_count,
            "approved_report_count": reporting.customer_approved_report_count,
        },
        "assertions": {
            "selected_channel_count": len(CHANNELS),
            "persistent_task_count": len(opportunities),
            "blocked_task_count": sum(item.status == "blocked" for item in opportunities),
            "approved_task_count": sum(item.status == "qualified" for item in opportunities),
            "export_created_publication": False,
            "claim_inventory_complete": placement.review.claim_inventory_complete,
            "review_submitter_differs_from_reviewer": (
                placement.review.submitted_for_review_by != placement.review.reviewer_id
            ),
            "customer_projection_approved_only": True,
        },
        "boundaries": {
            "external_publication_performed": False,
            "public_url_verification_mode": "controlled",
            "monitoring_data_mode": "controlled_acceptance",
            "causal_claim": False,
        },
    }
    _assert_result(result)
    return result


def write_result(path: Path, result: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _assert_result(result: Mapping[str, object]) -> None:
    assertions = result["assertions"]
    if not isinstance(assertions, Mapping):
        raise AssertionError("acceptance assertions are not structured")
    if assertions.get("selected_channel_count") != 9:
        raise AssertionError("the acceptance result does not cover all nine channels")
    if assertions.get("persistent_task_count") != 9:
        raise AssertionError("a selected channel lost its persistent task")
    if assertions.get("export_created_publication") is not False:
        raise AssertionError("export and publication intent are no longer separated")
