from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
from typing import Callable

import pytest

from geo_core.engineering.migration_cutover import (
    AtomicFailureProbe,
    MigrationCutoverError,
    MigrationCutoverReceipt,
    ProjectionDigest,
    REQUIRED_RESOURCES,
    ReconciliationRound,
    WriterInventoryEntry,
    evaluate_migration_cutover,
)
from scripts.roadmap_migration_cutover import load_receipt


def _round(*, phase: str, number: int, watermark: int) -> ReconciliationRound:
    digest = ProjectionDigest(row_count=18, sha256="a" * 64)
    return ReconciliationRound(
        round_number=number,
        phase=phase,
        watermark=watermark,
        scope_count=8,
        difference_count=0,
        change_log_lag=0,
        old_projection=digest,
        new_projection=digest,
    )


def _receipt() -> MigrationCutoverReceipt:
    started = datetime(2026, 7, 24, 12, tzinfo=UTC)
    return MigrationCutoverReceipt(
        schema_version="geo-migration-cutover-receipt-v1",
        run_id="migration-cutover-test",
        strategy="transactional_dual_write",
        included_workstreams=("A", "C", "D"),
        excluded_workstreams=("B",),
        resources=REQUIRED_RESOURCES,
        environment_fingerprint="b" * 64,
        started_at=started,
        finished_at=started + timedelta(minutes=1),
        initial_watermark=16,
        cutover_watermark=17,
        rollback_window_watermark=18,
        writer_inventory=(
            WriterInventoryEntry(
                writer_id="api_command_writer_v1",
                resources=("prompt", "protocol"),
                start_state="active",
                compatibility_path="transactional_old_projection_trigger",
                contract_state="retired",
            ),
            WriterInventoryEntry(
                writer_id="durable_worker_writer_v1",
                resources=("observation", "metric"),
                start_state="active",
                compatibility_path="transactional_old_projection_trigger",
                contract_state="retired",
            ),
        ),
        compatible_writer_installed=True,
        cutover_lock_acquired=True,
        legacy_writers_retired=True,
        post_contract_legacy_write_rejected=True,
        rehearsal_schema_removed=True,
        atomic_failure_probe=AtomicFailureProbe(
            failure_code="new_projection_rejected",
            before_change_count=17,
            after_change_count=17,
            before_old_count=17,
            after_old_count=17,
            before_new_count=17,
            after_new_count=17,
        ),
        reconciliations=(
            _round(phase="cutover", number=1, watermark=17),
            _round(phase="cutover", number=2, watermark=17),
            _round(phase="rollback_window", number=1, watermark=18),
        ),
    ).with_hash()


def test_frozen_online_migration_receipt_is_accepted() -> None:
    decision = evaluate_migration_cutover(_receipt())

    assert decision.accepted is True
    assert decision.failed_checks == ()


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (
            lambda receipt: replace(receipt, cutover_lock_acquired=False),
            "cutover_lock_missing",
        ),
        (
            lambda receipt: replace(receipt, compatible_writer_installed=False),
            "compatible_writer_missing",
        ),
        (
            lambda receipt: replace(receipt, legacy_writers_retired=False),
            "legacy_writer_not_retired",
        ),
        (
            lambda receipt: replace(receipt, rehearsal_schema_removed=False),
            "rehearsal_schema_not_removed",
        ),
    ],
)
def test_migration_acceptance_fails_closed_on_missing_operational_proof(
    mutate: Callable[[MigrationCutoverReceipt], MigrationCutoverReceipt],
    failure: str,
) -> None:
    receipt = mutate(replace(_receipt(), receipt_hash=None)).with_hash()

    decision = evaluate_migration_cutover(receipt)

    assert decision.accepted is False
    assert failure in decision.failed_checks


def test_migration_acceptance_rejects_non_atomic_dual_write() -> None:
    probe = replace(_receipt().atomic_failure_probe, after_old_count=18)
    receipt = replace(_receipt(), receipt_hash=None, atomic_failure_probe=probe).with_hash()

    assert "dual_write_not_atomic" in evaluate_migration_cutover(receipt).failed_checks


def test_migration_acceptance_requires_two_stable_zero_difference_rounds() -> None:
    divergent = replace(
        _round(phase="cutover", number=2, watermark=17),
        difference_count=1,
    )
    receipt = replace(
        _receipt(),
        receipt_hash=None,
        reconciliations=(
            _round(phase="cutover", number=1, watermark=17),
            divergent,
            _round(phase="rollback_window", number=1, watermark=18),
        ),
    ).with_hash()

    assert "cutover_reconciliation_failed" in evaluate_migration_cutover(receipt).failed_checks


def test_receipt_loader_rejects_self_declared_acceptance(tmp_path) -> None:
    payload = asdict(_receipt())
    payload["accepted"] = True
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")

    with pytest.raises(MigrationCutoverError, match="cannot declare"):
        load_receipt(path)


def test_receipt_hash_detects_content_tampering() -> None:
    with pytest.raises(MigrationCutoverError, match="hash does not match"):
        replace(_receipt(), cutover_watermark=18)
