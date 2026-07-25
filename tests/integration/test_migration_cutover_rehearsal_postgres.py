from __future__ import annotations

import os

import psycopg
import pytest

from geo_core.engineering.migration_cutover import evaluate_migration_cutover
from scripts.roadmap_migration_cutover import run_rehearsal


DATABASE_URL = os.getenv("GEO_MIGRATION_REHEARSAL_DATABASE_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="GEO_MIGRATION_REHEARSAL_DATABASE_URL is required",
    ),
]


def test_transactional_dual_write_cutover_and_cleanup_on_real_postgres() -> None:
    before = _rehearsal_schemas()

    receipt = run_rehearsal(DATABASE_URL)

    decision = evaluate_migration_cutover(receipt)
    assert decision.accepted is True, decision.failed_checks
    assert receipt.initial_watermark == 16
    assert receipt.cutover_watermark == 17
    assert receipt.rollback_window_watermark > receipt.cutover_watermark
    assert receipt.atomic_failure_probe.rolled_back is True
    assert [item.difference_count for item in receipt.reconciliations] == [0, 0, 0]
    assert [item.change_log_lag for item in receipt.reconciliations] == [0, 0, 0]
    assert _rehearsal_schemas() == before


def _rehearsal_schemas() -> set[str]:
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'geo_migration_rehearsal_%'"
        ).fetchall()
    return {str(row[0]) for row in rows}
