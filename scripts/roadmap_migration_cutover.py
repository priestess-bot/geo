"""Run or verify the isolated PostgreSQL online-migration cutover rehearsal."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Sequence
from uuid import uuid4

import psycopg
from psycopg import sql
from pydantic import TypeAdapter, ValidationError

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
from geo_core.engineering.strict_dataclass_payload import (
    close_dataclass_json_schema,
    reject_unknown_dataclass_fields,
)


_ADAPTER = TypeAdapter(MigrationCutoverReceipt)
_SAFE_SCHEMA = re.compile(r"geo_migration_rehearsal_[0-9a-f]{12}")


def export_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = close_dataclass_json_schema(_ADAPTER.json_schema())
    _write_private_json(path, schema)


def load_receipt(path: Path) -> MigrationCutoverReceipt:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MigrationCutoverError("migration receipt cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise MigrationCutoverError("migration receipt is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise MigrationCutoverError("migration receipt must be a JSON object")
    if {"accepted", "failed_checks"}.intersection(payload):
        raise MigrationCutoverError("migration receipt cannot declare its own decision")
    reject_unknown_dataclass_fields(
        payload,
        MigrationCutoverReceipt,
        path="receipt",
        error_factory=MigrationCutoverError,
    )
    try:
        return _ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise MigrationCutoverError(f"invalid migration receipt: {exc}") from exc


def run_rehearsal(database_url: str) -> MigrationCutoverReceipt:
    started_at = datetime.now(UTC)
    run_id = f"migration-cutover-{started_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    schema_name = f"geo_migration_rehearsal_{uuid4().hex[:12]}"
    if _SAFE_SCHEMA.fullmatch(schema_name) is None:
        raise MigrationCutoverError("unsafe rehearsal schema identity")
    schema = sql.Identifier(schema_name)
    removed = False
    observations: dict[str, Any] = {}
    try:
        with psycopg.connect(database_url) as connection:
            _create_rehearsal_schema(connection, schema=schema, schema_name=schema_name)
            observations["environment_fingerprint"] = _environment_fingerprint(connection)
            _seed_legacy_rows(connection, schema=schema)
            observations["initial_watermark"] = _watermark(connection, schema=schema)
            _install_compatible_writer(connection, schema=schema, schema_name=schema_name)
            _initial_backfill_with_interleaved_writes(connection, schema=schema)
            observations["atomic_failure_probe"] = _atomic_failure_probe(
                connection,
                schema=schema,
            )
            cutover_watermark, cutover_rounds, cutover_lock_proved = _cutover(
                connection,
                database_url=database_url,
                schema=schema,
                schema_name=schema_name,
            )
            observations["cutover_watermark"] = cutover_watermark
            observations["cutover_rounds"] = cutover_rounds
            observations["cutover_lock_proved"] = cutover_lock_proved
            rollback_watermark, rollback_round = _exercise_rollback_window(
                connection,
                schema=schema,
            )
            observations["rollback_window_watermark"] = rollback_watermark
            observations["rollback_round"] = rollback_round
            observations["post_contract_rejected"] = _retire_legacy_writers(
                connection,
                schema=schema,
            )
    finally:
        try:
            with psycopg.connect(database_url, autocommit=True) as cleanup:
                cleanup.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(schema))
                removed = not bool(
                    cleanup.execute(
                        "SELECT 1 FROM pg_namespace WHERE nspname = %s",
                        (schema_name,),
                    ).fetchone()
                )
        except psycopg.Error:
            removed = False
    required = {
        "environment_fingerprint",
        "initial_watermark",
        "atomic_failure_probe",
        "cutover_watermark",
        "cutover_rounds",
        "cutover_lock_proved",
        "rollback_window_watermark",
        "rollback_round",
        "post_contract_rejected",
    }
    if set(observations) != required:
        raise MigrationCutoverError("migration rehearsal did not reach every required phase")
    receipt = MigrationCutoverReceipt(
        schema_version="geo-migration-cutover-receipt-v1",
        run_id=run_id,
        strategy="transactional_dual_write",
        included_workstreams=("A", "C", "D"),
        excluded_workstreams=("B",),
        resources=REQUIRED_RESOURCES,
        environment_fingerprint=observations["environment_fingerprint"],
        started_at=started_at,
        finished_at=datetime.now(UTC),
        initial_watermark=observations["initial_watermark"],
        cutover_watermark=observations["cutover_watermark"],
        rollback_window_watermark=observations["rollback_window_watermark"],
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
        cutover_lock_acquired=observations["cutover_lock_proved"],
        legacy_writers_retired=True,
        post_contract_legacy_write_rejected=observations["post_contract_rejected"],
        rehearsal_schema_removed=removed,
        atomic_failure_probe=observations["atomic_failure_probe"],
        reconciliations=(*observations["cutover_rounds"], observations["rollback_round"]),
    ).with_hash()
    decision = evaluate_migration_cutover(receipt)
    if not decision.accepted:
        raise MigrationCutoverError(
            f"migration rehearsal failed: {','.join(decision.failed_checks)}"
        )
    return receipt


def _create_rehearsal_schema(
    connection: psycopg.Connection[Any], *, schema: sql.Identifier, schema_name: str
) -> None:
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
    connection.execute(
        sql.SQL(
            """
            CREATE TABLE {}.migration_state (
                singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
                phase text NOT NULL CHECK (
                    phase IN ('legacy', 'compatible', 'cutover_locked', 'switched', 'contract')
                ),
                allow_legacy_writes boolean NOT NULL
            );
            INSERT INTO {}.migration_state(phase, allow_legacy_writes)
            VALUES ('legacy', true);
            CREATE TABLE {}.change_log (
                change_seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                resource text NOT NULL,
                project_key text NOT NULL,
                campaign_key text NOT NULL,
                business_key text NOT NULL,
                payload jsonb NOT NULL,
                payload_hash text NOT NULL
            );
            CREATE TABLE {}.old_projection (
                resource text NOT NULL,
                project_key text NOT NULL,
                campaign_key text NOT NULL,
                business_key text NOT NULL,
                payload jsonb NOT NULL,
                payload_hash text NOT NULL,
                change_seq bigint NOT NULL,
                PRIMARY KEY(resource, project_key, campaign_key, business_key)
            );
            CREATE TABLE {}.new_projection (
                resource text NOT NULL,
                project_key text NOT NULL,
                campaign_key text NOT NULL,
                business_key text NOT NULL,
                payload jsonb NOT NULL CHECK (NOT (payload ? '__reject_new_projection')),
                payload_hash text NOT NULL,
                change_seq bigint NOT NULL,
                PRIMARY KEY(resource, project_key, campaign_key, business_key)
            );
            """
        ).format(schema, schema, schema, schema, schema)
    )
    connection.execute(
        sql.SQL(
            """
            CREATE FUNCTION {}.legacy_write(
                p_resource text,
                p_project text,
                p_campaign text,
                p_business_key text,
                p_payload jsonb
            ) RETURNS bigint
            LANGUAGE plpgsql
            SET search_path = {}, pg_temp
            AS $body$
            DECLARE
                next_seq bigint;
                next_hash text;
            BEGIN
                IF NOT (SELECT allow_legacy_writes FROM migration_state WHERE singleton) THEN
                    RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'legacy_writer_retired';
                END IF;
                PERFORM pg_advisory_xact_lock_shared(hashtext({}));
                next_hash := encode(sha256(convert_to(p_payload::text, 'UTF8')), 'hex');
                INSERT INTO change_log(
                    resource, project_key, campaign_key, business_key, payload, payload_hash
                ) VALUES (
                    p_resource, p_project, p_campaign, p_business_key, p_payload, next_hash
                ) RETURNING change_seq INTO next_seq;
                INSERT INTO old_projection(
                    resource, project_key, campaign_key, business_key,
                    payload, payload_hash, change_seq
                ) VALUES (
                    p_resource, p_project, p_campaign, p_business_key,
                    p_payload, next_hash, next_seq
                ) ON CONFLICT(resource, project_key, campaign_key, business_key)
                DO UPDATE SET
                    payload = EXCLUDED.payload,
                    payload_hash = EXCLUDED.payload_hash,
                    change_seq = EXCLUDED.change_seq;
                RETURN next_seq;
            END;
            $body$;
            """
        ).format(schema, schema, sql.Literal(schema_name))
    )
    connection.commit()


def _install_compatible_writer(
    connection: psycopg.Connection[Any], *, schema: sql.Identifier, schema_name: str
) -> None:
    connection.execute(
        sql.SQL(
            """
            CREATE FUNCTION {}.mirror_old_to_new() RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = {}, pg_temp
            AS $body$
            BEGIN
                PERFORM pg_advisory_xact_lock_shared(hashtext({}));
                INSERT INTO new_projection(
                    resource, project_key, campaign_key, business_key,
                    payload, payload_hash, change_seq
                ) VALUES (
                    NEW.resource, NEW.project_key, NEW.campaign_key, NEW.business_key,
                    NEW.payload, NEW.payload_hash, NEW.change_seq
                ) ON CONFLICT(resource, project_key, campaign_key, business_key)
                DO UPDATE SET
                    payload = EXCLUDED.payload,
                    payload_hash = EXCLUDED.payload_hash,
                    change_seq = EXCLUDED.change_seq;
                RETURN NEW;
            END;
            $body$;
            CREATE TRIGGER compatible_writer_dual_write
            AFTER INSERT OR UPDATE ON {}.old_projection
            FOR EACH ROW EXECUTE FUNCTION {}.mirror_old_to_new();
            UPDATE {}.migration_state SET phase = 'compatible' WHERE singleton;
            """
        ).format(schema, schema, sql.Literal(schema_name), schema, schema, schema)
    )
    connection.commit()


def _seed_legacy_rows(connection: psycopg.Connection[Any], *, schema: sql.Identifier) -> None:
    for resource in REQUIRED_RESOURCES:
        for ordinal in range(1, 5):
            connection.execute(
                sql.SQL("SELECT {}.legacy_write(%s, %s, %s, %s, %s::jsonb)").format(schema),
                (
                    resource,
                    f"project-{(ordinal % 2) + 1}",
                    f"campaign-{(ordinal % 2) + 1}",
                    f"{resource}-{ordinal}",
                    json.dumps({"resource": resource, "revision": 1, "ordinal": ordinal}),
                ),
            )
    connection.commit()


def _initial_backfill_with_interleaved_writes(
    connection: psycopg.Connection[Any], *, schema: sql.Identifier
) -> None:
    for index, resource in enumerate(REQUIRED_RESOURCES):
        connection.execute(
            sql.SQL(
                """
                INSERT INTO {}.new_projection
                SELECT * FROM {}.old_projection WHERE resource = %s
                ON CONFLICT(resource, project_key, campaign_key, business_key)
                DO UPDATE SET
                    payload = EXCLUDED.payload,
                    payload_hash = EXCLUDED.payload_hash,
                    change_seq = EXCLUDED.change_seq
                """
            ).format(schema, schema),
            (resource,),
        )
        if index == 0:
            connection.execute(
                sql.SQL("SELECT {}.legacy_write(%s, %s, %s, %s, %s::jsonb)").format(schema),
                (
                    "prompt",
                    "project-1",
                    "campaign-1",
                    "prompt-during-backfill",
                    json.dumps({"resource": "prompt", "revision": 2, "during": "backfill"}),
                ),
            )
    connection.commit()


def _atomic_failure_probe(
    connection: psycopg.Connection[Any], *, schema: sql.Identifier
) -> AtomicFailureProbe:
    before = _table_counts(connection, schema=schema)
    try:
        with connection.transaction():
            connection.execute(
                sql.SQL("SELECT {}.legacy_write(%s, %s, %s, %s, %s::jsonb)").format(schema),
                (
                    "metric",
                    "project-2",
                    "campaign-2",
                    "metric-atomic-failure",
                    json.dumps({"__reject_new_projection": True}),
                ),
            )
    except psycopg.errors.CheckViolation:
        pass
    else:
        raise MigrationCutoverError("new projection failure probe unexpectedly committed")
    after = _table_counts(connection, schema=schema)
    probe = AtomicFailureProbe(
        failure_code="new_projection_rejected",
        before_change_count=before[0],
        after_change_count=after[0],
        before_old_count=before[1],
        after_old_count=after[1],
        before_new_count=before[2],
        after_new_count=after[2],
    )
    connection.commit()
    return probe


def _cutover(
    connection: psycopg.Connection[Any],
    *,
    database_url: str,
    schema: sql.Identifier,
    schema_name: str,
) -> tuple[int, tuple[ReconciliationRound, ReconciliationRound], bool]:
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (schema_name,))
        lock_proved = _probe_cutover_lock(database_url, schema=schema)
        connection.execute(
            sql.SQL("UPDATE {}.migration_state SET phase = 'cutover_locked' WHERE singleton").format(
                schema
            )
        )
        connection.execute(
            sql.SQL(
                """
                INSERT INTO {}.new_projection SELECT * FROM {}.old_projection
                ON CONFLICT(resource, project_key, campaign_key, business_key)
                DO UPDATE SET
                    payload = EXCLUDED.payload,
                    payload_hash = EXCLUDED.payload_hash,
                    change_seq = EXCLUDED.change_seq
                """
            ).format(schema, schema)
        )
        watermark = _watermark(connection, schema=schema)
        first = _reconcile(connection, schema=schema, round_number=1, phase="cutover")
        second = _reconcile(connection, schema=schema, round_number=2, phase="cutover")
        connection.execute(
            sql.SQL("UPDATE {}.migration_state SET phase = 'switched' WHERE singleton").format(
                schema
            )
        )
    return watermark, (first, second), lock_proved


def _probe_cutover_lock(database_url: str, *, schema: sql.Identifier) -> bool:
    try:
        with psycopg.connect(database_url) as contender:
            contender.execute("SET LOCAL lock_timeout = '150ms'")
            contender.execute(
                sql.SQL("SELECT {}.legacy_write(%s, %s, %s, %s, %s::jsonb)").format(schema),
                ("metric", "project-1", "campaign-1", "cutover-lock-probe", "{}"),
            )
    except psycopg.errors.LockNotAvailable:
        return True
    raise MigrationCutoverError("cutover lock did not block an active legacy writer")


def _exercise_rollback_window(
    connection: psycopg.Connection[Any], *, schema: sql.Identifier
) -> tuple[int, ReconciliationRound]:
    connection.execute(
        sql.SQL("SELECT {}.legacy_write(%s, %s, %s, %s, %s::jsonb)").format(schema),
        (
            "protocol",
            "project-2",
            "campaign-2",
            "protocol-rollback-window",
            json.dumps({"resource": "protocol", "revision": 3, "phase": "rollback_window"}),
        ),
    )
    connection.commit()
    watermark = _watermark(connection, schema=schema)
    return watermark, _reconcile(
        connection,
        schema=schema,
        round_number=1,
        phase="rollback_window",
    )


def _retire_legacy_writers(
    connection: psycopg.Connection[Any], *, schema: sql.Identifier
) -> bool:
    connection.execute(
        sql.SQL(
            """
            UPDATE {}.migration_state
            SET phase = 'contract', allow_legacy_writes = false
            WHERE singleton
            """
        ).format(schema)
    )
    connection.commit()
    before = _table_counts(connection, schema=schema)
    try:
        with connection.transaction():
            connection.execute(
                sql.SQL("SELECT {}.legacy_write(%s, %s, %s, %s, %s::jsonb)").format(schema),
                ("prompt", "project-1", "campaign-1", "retired", "{}"),
            )
    except psycopg.errors.ObjectNotInPrerequisiteState as exc:
        rejected = "legacy_writer_retired" in str(exc)
    else:
        rejected = False
    return rejected and before == _table_counts(connection, schema=schema)


def _reconcile(
    connection: psycopg.Connection[Any],
    *,
    schema: sql.Identifier,
    round_number: int,
    phase: str,
) -> ReconciliationRound:
    old_rows = _projection_rows(connection, schema=schema, table="old_projection")
    new_rows = _projection_rows(connection, schema=schema, table="new_projection")
    old_map = {tuple(row[:4]): tuple(row[4:]) for row in old_rows}
    new_map = {tuple(row[:4]): tuple(row[4:]) for row in new_rows}
    all_keys = set(old_map) | set(new_map)
    difference_count = sum(old_map.get(key) != new_map.get(key) for key in all_keys)
    maximum = _watermark(connection, schema=schema)
    projected = max((int(row[-1]) for row in new_rows), default=0)
    scopes = {(row[0], row[1], row[2]) for row in old_rows}
    return ReconciliationRound(
        round_number=round_number,
        phase=phase,
        watermark=maximum,
        scope_count=len(scopes),
        difference_count=difference_count,
        change_log_lag=maximum - projected,
        old_projection=_digest(old_rows),
        new_projection=_digest(new_rows),
    )


def _projection_rows(
    connection: psycopg.Connection[Any], *, schema: sql.Identifier, table: str
) -> list[tuple[Any, ...]]:
    return list(
        connection.execute(
            sql.SQL(
                """
                SELECT resource, project_key, campaign_key, business_key,
                       payload_hash, change_seq
                FROM {}.{}
                ORDER BY resource, project_key, campaign_key, business_key
                """
            ).format(schema, sql.Identifier(table))
        ).fetchall()
    )


def _digest(rows: list[tuple[Any, ...]]) -> ProjectionDigest:
    encoded = json.dumps(rows, separators=(",", ":"), default=str).encode("ascii")
    return ProjectionDigest(row_count=len(rows), sha256=hashlib.sha256(encoded).hexdigest())


def _watermark(connection: psycopg.Connection[Any], *, schema: sql.Identifier) -> int:
    row = connection.execute(
        sql.SQL("SELECT coalesce(max(change_seq), 0) FROM {}.change_log").format(schema)
    ).fetchone()
    return int(row[0]) if row else 0


def _table_counts(
    connection: psycopg.Connection[Any], *, schema: sql.Identifier
) -> tuple[int, int, int]:
    row = connection.execute(
        sql.SQL(
            """
            SELECT
              (SELECT count(*) FROM {}.change_log),
              (SELECT count(*) FROM {}.old_projection),
              (SELECT count(*) FROM {}.new_projection)
            """
        ).format(schema, schema, schema)
    ).fetchone()
    if row is None:
        raise MigrationCutoverError("rehearsal table counts are unavailable")
    return int(row[0]), int(row[1]), int(row[2])


def _environment_fingerprint(connection: psycopg.Connection[Any]) -> str:
    row = connection.execute(
        "SELECT current_database(), current_setting('server_version_num'), current_user"
    ).fetchone()
    if row is None:
        raise MigrationCutoverError("database environment identity is unavailable")
    encoded = json.dumps(row, separators=(",", ":"), default=str).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _write_private_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, default=str)
            stream.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    schema = commands.add_parser("export-schema")
    schema.add_argument("output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("receipt", type=Path)
    run = commands.add_parser("run")
    run.add_argument("--database-url", default=os.getenv("GEO_MIGRATION_REHEARSAL_DATABASE_URL"))
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--confirm-isolated-database", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "export-schema":
            export_schema(arguments.output)
            return 0
        if arguments.command == "verify":
            receipt = load_receipt(arguments.receipt)
        else:
            if not arguments.confirm_isolated_database:
                raise MigrationCutoverError("isolated database confirmation is required")
            if not arguments.database_url:
                raise MigrationCutoverError("migration rehearsal database URL is required")
            receipt = run_rehearsal(arguments.database_url)
            _write_private_json(arguments.output, asdict(receipt))
        decision = evaluate_migration_cutover(receipt)
    except (MigrationCutoverError, psycopg.Error) as exc:
        raise SystemExit(str(exc)) from exc
    print(
        json.dumps(
            {
                "accepted": decision.accepted,
                "failed_checks": decision.failed_checks,
                "receipt_hash": receipt.receipt_hash,
                "run_id": receipt.run_id,
            },
            sort_keys=True,
        )
    )
    return 0 if decision.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
