"""Fail-closed receipt contract for an online migration cutover rehearsal."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
import re


class MigrationCutoverError(ValueError):
    """Raised when migration evidence does not prove a safe online cutover."""


_SHA256 = re.compile(r"[0-9a-f]{64}")
REQUIRED_RESOURCES = ("prompt", "protocol", "observation", "metric")


@dataclass(frozen=True)
class WriterInventoryEntry:
    writer_id: str
    resources: tuple[str, ...]
    start_state: str
    compatibility_path: str
    contract_state: str

    def __post_init__(self) -> None:
        if not self.writer_id.strip() or not self.resources:
            raise MigrationCutoverError("writer inventory identity and resources are required")
        if any(resource not in REQUIRED_RESOURCES for resource in self.resources):
            raise MigrationCutoverError("writer inventory contains an unknown resource")
        if self.start_state != "active" or self.contract_state != "retired":
            raise MigrationCutoverError("writer inventory must prove active-to-retired lifecycle")
        if self.compatibility_path != "transactional_old_projection_trigger":
            raise MigrationCutoverError("writer inventory compatibility path is unsupported")


@dataclass(frozen=True)
class ProjectionDigest:
    row_count: int
    sha256: str

    def __post_init__(self) -> None:
        if self.row_count < 1:
            raise MigrationCutoverError("projection digest must cover at least one row")
        if _SHA256.fullmatch(self.sha256) is None:
            raise MigrationCutoverError("projection digest must use SHA-256")


@dataclass(frozen=True)
class ReconciliationRound:
    round_number: int
    phase: str
    watermark: int
    scope_count: int
    difference_count: int
    change_log_lag: int
    old_projection: ProjectionDigest
    new_projection: ProjectionDigest

    def __post_init__(self) -> None:
        if self.round_number < 1 or self.phase not in {"cutover", "rollback_window"}:
            raise MigrationCutoverError("reconciliation round identity is invalid")
        if self.watermark < 1 or self.scope_count < 1:
            raise MigrationCutoverError("reconciliation watermark and scope are required")
        if self.difference_count < 0 or self.change_log_lag < 0:
            raise MigrationCutoverError("reconciliation counters cannot be negative")


@dataclass(frozen=True)
class AtomicFailureProbe:
    failure_code: str
    before_change_count: int
    after_change_count: int
    before_old_count: int
    after_old_count: int
    before_new_count: int
    after_new_count: int

    def __post_init__(self) -> None:
        if self.failure_code != "new_projection_rejected":
            raise MigrationCutoverError("atomic failure probe used an unknown failure")
        if any(value < 0 for value in asdict(self).values() if isinstance(value, int)):
            raise MigrationCutoverError("atomic failure probe counters cannot be negative")

    @property
    def rolled_back(self) -> bool:
        return (
            self.before_change_count == self.after_change_count
            and self.before_old_count == self.after_old_count
            and self.before_new_count == self.after_new_count
        )


@dataclass(frozen=True)
class MigrationCutoverReceipt:
    schema_version: str
    run_id: str
    strategy: str
    included_workstreams: tuple[str, ...]
    excluded_workstreams: tuple[str, ...]
    resources: tuple[str, ...]
    environment_fingerprint: str
    started_at: datetime
    finished_at: datetime
    initial_watermark: int
    cutover_watermark: int
    rollback_window_watermark: int
    writer_inventory: tuple[WriterInventoryEntry, ...]
    compatible_writer_installed: bool
    cutover_lock_acquired: bool
    legacy_writers_retired: bool
    post_contract_legacy_write_rejected: bool
    rehearsal_schema_removed: bool
    atomic_failure_probe: AtomicFailureProbe
    reconciliations: tuple[ReconciliationRound, ...]
    receipt_hash: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "geo-migration-cutover-receipt-v1":
            raise MigrationCutoverError("unsupported migration receipt schema")
        if not self.run_id.strip():
            raise MigrationCutoverError("migration run identity is required")
        if self.strategy != "transactional_dual_write":
            raise MigrationCutoverError("migration rehearsal must use transactional dual-write")
        if self.included_workstreams != ("A", "C", "D") or self.excluded_workstreams != (
            "B",
        ):
            raise MigrationCutoverError("migration rehearsal scope must be exactly non-B")
        if self.resources != REQUIRED_RESOURCES:
            raise MigrationCutoverError("migration rehearsal resources differ from the frozen set")
        if _SHA256.fullmatch(self.environment_fingerprint) is None:
            raise MigrationCutoverError("migration environment fingerprint must use SHA-256")
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise MigrationCutoverError("migration timestamps must be timezone-aware")
        if self.finished_at <= self.started_at:
            raise MigrationCutoverError("migration finish must follow start")
        if self.receipt_hash is not None and self.receipt_hash != self.calculate_hash():
            raise MigrationCutoverError("migration receipt hash does not match its content")

    def calculate_hash(self) -> str:
        payload = asdict(self)
        payload.pop("receipt_hash", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()

    def with_hash(self) -> "MigrationCutoverReceipt":
        return replace(self, receipt_hash=self.calculate_hash())


@dataclass(frozen=True)
class MigrationCutoverDecision:
    accepted: bool
    failed_checks: tuple[str, ...]


def evaluate_migration_cutover(
    receipt: MigrationCutoverReceipt,
) -> MigrationCutoverDecision:
    """Derive acceptance without trusting a pass flag supplied by the runner."""

    failures: list[str] = []

    def require(condition: bool, code: str) -> None:
        if not condition:
            failures.append(code)

    require(receipt.receipt_hash == receipt.calculate_hash(), "receipt_hash_mismatch")
    require(receipt.initial_watermark >= 16, "initial_backfill_denominator_low")
    require(
        receipt.initial_watermark < receipt.cutover_watermark,
        "incremental_catch_up_not_exercised",
    )
    require(
        receipt.cutover_watermark < receipt.rollback_window_watermark,
        "rollback_window_write_not_exercised",
    )
    inventory_resources = {
        resource for writer in receipt.writer_inventory for resource in writer.resources
    }
    require(len(receipt.writer_inventory) >= 2, "writer_inventory_incomplete")
    require(inventory_resources == set(REQUIRED_RESOURCES), "writer_resource_coverage_incomplete")
    require(receipt.compatible_writer_installed, "compatible_writer_missing")
    require(receipt.cutover_lock_acquired, "cutover_lock_missing")
    require(receipt.atomic_failure_probe.rolled_back, "dual_write_not_atomic")
    require(receipt.legacy_writers_retired, "legacy_writer_not_retired")
    require(
        receipt.post_contract_legacy_write_rejected,
        "post_contract_legacy_write_not_rejected",
    )
    require(receipt.rehearsal_schema_removed, "rehearsal_schema_not_removed")

    cutover = tuple(item for item in receipt.reconciliations if item.phase == "cutover")
    rollback = tuple(
        item for item in receipt.reconciliations if item.phase == "rollback_window"
    )
    require(len(cutover) >= 2, "two_cutover_reconciliations_required")
    if len(cutover) >= 2:
        final_two = cutover[-2:]
        require(
            tuple(item.round_number for item in final_two) == (1, 2),
            "cutover_round_numbers_invalid",
        )
        require(
            all(item.watermark == receipt.cutover_watermark for item in final_two),
            "cutover_watermark_changed",
        )
        require(
            all(_round_is_zero_difference(item) for item in final_two),
            "cutover_reconciliation_failed",
        )
        require(
            final_two[0].old_projection == final_two[1].old_projection,
            "old_projection_changed_between_cutover_rounds",
        )
        require(
            final_two[0].new_projection == final_two[1].new_projection,
            "new_projection_changed_between_cutover_rounds",
        )
    require(len(rollback) == 1, "rollback_window_reconciliation_required")
    if rollback:
        require(
            rollback[0].watermark == receipt.rollback_window_watermark,
            "rollback_window_watermark_mismatch",
        )
        require(_round_is_zero_difference(rollback[0]), "rollback_window_diverged")
    return MigrationCutoverDecision(accepted=not failures, failed_checks=tuple(failures))


def _round_is_zero_difference(round_: ReconciliationRound) -> bool:
    return (
        round_.scope_count >= 8
        and round_.difference_count == 0
        and round_.change_log_lag == 0
        and round_.old_projection == round_.new_projection
    )


__all__ = [
    "AtomicFailureProbe",
    "MigrationCutoverDecision",
    "MigrationCutoverError",
    "MigrationCutoverReceipt",
    "ProjectionDigest",
    "REQUIRED_RESOURCES",
    "ReconciliationRound",
    "WriterInventoryEntry",
    "evaluate_migration_cutover",
]
