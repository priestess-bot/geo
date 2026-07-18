"""Measurement, customer projection and acceptance result assertions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Mapping

from geo_core.monitoring.domain import MonitoringReport
from geo_core.placements.domain import Measurement, MeasurementCollectionTask

from scripts.geo_acceptance.contracts import AcceptanceConfig, CHANNELS
from scripts.geo_acceptance.monitoring import (
    BaselineResult,
    FOLLOW_UP_WINDOWS,
    FollowUpResult,
    run_follow_up,
)
from scripts.geo_acceptance.placement import PlacementResult
from scripts.geo_acceptance.setup import AcceptanceSetup


@dataclass(frozen=True)
class ReportingResult:
    placement_measurements: tuple[Measurement, ...]
    measurement_tasks: tuple[MeasurementCollectionTask, ...]
    follow_ups: tuple[FollowUpResult, ...]
    reports: tuple[MonitoringReport, ...]
    customer_metric_count: int
    customer_verified_url_count: int
    customer_approved_report_count: int


def run_reporting(
    setup: AcceptanceSetup,
    baseline: BaselineResult,
    placement: PlacementResult,
) -> ReportingResult:
    tasks_by_window = {item.measurement_window: item for item in placement.measurement_tasks}
    placement_measurements: list[Measurement] = []
    completed_tasks: list[MeasurementCollectionTask] = []
    follow_ups: list[FollowUpResult] = []
    reports: list[MonitoringReport] = []
    for window in FOLLOW_UP_WINDOWS:
        task = tasks_by_window.get(window.value)
        if task is None:
            raise AssertionError(f"{window.value} collection task is missing")
        placement_measurements.append(setup.placement.record_measurement(
            project_id=setup.project_id,
            submission_id=placement.submission.id,
            monitoring_query_id=baseline.query.monitoring_query_id,
            measured_at=datetime.now(UTC),
            citation_present=True,
            recommendation_position=1,
            result_snapshot_uri=(
                f"s3://geo-artifacts/acceptance/{setup.suffix}/"
                f"placement-result-{window.value}.json"
            ),
            metrics={"mode": "controlled_acceptance", "window": window.value},
        ))
        follow_up = run_follow_up(
            setup,
            baseline,
            window=window,
            submitted_url=placement.submitted_url,
            submission_id=placement.submission.id,
        )
        follow_ups.append(follow_up)
        completed_tasks.append(setup.placement.complete_measurement_collection_task(
            project_id=setup.project_id,
            task_id=task.id,
            actor_id=setup.owner.identity_id,
        ))
        report = baseline.application.generate_report(
            setup.owner,
            project_id=setup.project_id,
            metric_snapshot_id=follow_up.metric.id,
            title=f"Controlled GEO {window.value.upper()} acceptance report {setup.suffix}",
        )
        reports.append(baseline.application.approve_report(
            setup.owner, project_id=setup.project_id, report_id=report.id
        ))
    customer_metrics = baseline.application.list_metrics(
        setup.customer, project_id=setup.project_id
    )
    customer_urls = baseline.application.list_verified_urls(
        setup.customer, project_id=setup.project_id
    )
    customer_reports = baseline.application.list_reports(
        setup.customer, project_id=setup.project_id, approved_only=True
    )
    if len(customer_metrics) != 4 or len(customer_urls) != 1 or len(customer_reports) != 3:
        raise AssertionError("customer-safe metrics, verified URL and report are incomplete")
    if any(item.status != "approved" for item in customer_reports):
        raise AssertionError("customer projection exposed an unapproved report")
    return ReportingResult(
        tuple(placement_measurements),
        tuple(completed_tasks),
        tuple(follow_ups),
        tuple(reports),
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
        "environment": config.environment,
        "mode": "live_deepseek" if config.live_deepseek else "deterministic",
        "target_manifest": (
            {
                "path": str(config.target_manifest),
                "sha256": hashlib.sha256(config.target_manifest.read_bytes()).hexdigest(),
            }
            if config.target_manifest is not None
            else None
        ),
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
            "follow_up_windows": [
                {
                    "window": window.value,
                    "observation_id": follow_up.observation.id,
                    "metric_id": follow_up.metric.id,
                    "report_id": report.id,
                }
                for window, follow_up, report in zip(
                    FOLLOW_UP_WINDOWS, reporting.follow_ups, reporting.reports, strict=True
                )
            ],
            "t28_observation_id": reporting.follow_ups[0].observation.id,
            "t28_metric_id": reporting.follow_ups[0].metric.id,
            "report_id": reporting.reports[0].id,
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
            "prompt_simulation_count": len(placement.prompt_simulations),
            "prompt_simulation_ids": [item.id for item in placement.prompt_simulations],
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
            "measurement_collection_tasks": [
                {
                    "task_id": task.id,
                    "window": task.measurement_window,
                    "status": task.status,
                    "placement_measurement_id": measurement.id,
                }
                for task, measurement in zip(
                    reporting.measurement_tasks,
                    reporting.placement_measurements,
                    strict=True,
                )
            ],
            "measurement_collection_task_id": reporting.measurement_tasks[0].id,
            "measurement_collection_task_status": reporting.measurement_tasks[0].status,
            "scheduled_measurement_offsets": list(placement.scheduled_windows),
            "placement_measurement_id": reporting.placement_measurements[0].id,
        },
        "customer_projection": {
            "metric_count": reporting.customer_metric_count,
            "verified_url_count": reporting.customer_verified_url_count,
            "approved_report_count": reporting.customer_approved_report_count,
        },
        "assertions": {
            "selected_channel_count": len(CHANNELS),
            "persistent_task_count": len(opportunities),
            "prompt_simulation_count": len(placement.prompt_simulations),
            "prompt_simulations_publication_eligible": any(
                item.publication_eligible for item in placement.prompt_simulations
            ),
            "blocked_task_count": sum(item.status == "blocked" for item in opportunities),
            "completed_task_count": sum(item.status == "completed" for item in opportunities),
            "export_created_publication": False,
            "claim_inventory_complete": placement.review.claim_inventory_complete,
            "review_submitter_differs_from_reviewer": (
                placement.review.submitted_for_review_by != placement.review.reviewer_id
            ),
            "customer_projection_approved_only": True,
            "follow_up_windows_completed": [
                task.measurement_window
                for task in reporting.measurement_tasks
                if task.status == "completed"
            ],
        },
        "boundaries": {
            "external_publication_performed": False,
            "public_url_verification_mode": "controlled",
            "monitoring_data_mode": "controlled_acceptance",
            "controlled_simulation": True,
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
    if assertions.get("prompt_simulation_count") != 9:
        raise AssertionError("the acceptance result does not simulate all nine channel prompts")
    if assertions.get("prompt_simulations_publication_eligible") is not False:
        raise AssertionError("a TEST ONLY simulation became publication eligible")
    if assertions.get("export_created_publication") is not False:
        raise AssertionError("export and publication intent are no longer separated")
    if assertions.get("follow_up_windows_completed") != ["t28", "t56", "t84"]:
        raise AssertionError("T+28, T+56 and T+84 follow-up tasks are not complete")
