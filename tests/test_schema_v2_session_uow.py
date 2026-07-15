from __future__ import annotations

import dataclasses
import hashlib
import inspect
import threading
import unittest
from types import SimpleNamespace
from uuid import UUID

from geo_core.runtime import RuntimePersistenceError, RuntimePostgresConnectionPool
from geo_core.schema_v2.session_uow import (
    SchemaV2ApiSessionUnitOfWork,
    SchemaV2RawSessionTokenError,
    SchemaV2SessionAuthorizationError,
    SchemaV2SessionCommitOutcomeUnknownError,
    SchemaV2SessionLifecycleError,
    SchemaV2SessionTokenHash,
    SchemaV2SessionTokenHashError,
    SchemaV2SessionUnitOfWorkError,
    hash_raw_session_token,
)


RAW_SESSION_TOKEN = "unit-test-session-token"
SESSION_HASH = hashlib.sha256(RAW_SESSION_TOKEN.encode("utf-8")).hexdigest()
SESSION_TOKEN_HASH = hash_raw_session_token(RAW_SESSION_TOKEN)
SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")
TENANT_ID = UUID("22222222-2222-4222-8222-222222222222")
PROJECT_ID = UUID("33333333-3333-4333-8333-333333333333")


def resolver_row() -> tuple[object, ...]:
    return (
        SESSION_ID,
        "owner@example.test",
        TENANT_ID,
        [str(PROJECT_ID)],
        [],
        [
            {
                "project_id": str(PROJECT_ID),
                "roles": ["project_owner"],
                "permissions": ["project.read", "project.update"],
                "portal_capabilities": ["portal.admin.access"],
                "scope_sources": ["direct_member"],
            }
        ],
    )


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[object, ...] = ()) -> None:
        normalized = " ".join(statement.split())
        if self.connection.info.transaction_status.name == "IDLE":
            self.connection.info.transaction_status.name = "INTRANS"
        self.connection.calls.append((normalized, params))
        self.connection.events.append(f"SQL:{normalized}")
        if self.connection.fail_on_sql and self.connection.fail_on_sql in normalized:
            raise RuntimeError(f"database failure containing {SESSION_HASH}")

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.connection.resolver_rows)

    def fetchone(self) -> tuple[object, ...] | None:
        rows = self.fetchall()
        return rows[0] if rows else None


class FakeConnection:
    def __init__(
        self,
        *,
        resolver_rows: list[tuple[object, ...]] | None = None,
        fail_on_sql: str | None = None,
        fail_commit_calls: set[int] | None = None,
        fail_rollback: bool = False,
        fail_close: bool = False,
        nonidle_commit_calls: set[int] | None = None,
        transaction_status: object | None = None,
        autocommit: bool = False,
    ) -> None:
        self.resolver_rows = [resolver_row()] if resolver_rows is None else resolver_rows
        self.fail_on_sql = fail_on_sql
        self.fail_commit_calls = fail_commit_calls or set()
        self.fail_rollback = fail_rollback
        self.fail_close = fail_close
        self.nonidle_commit_calls = nonidle_commit_calls or set()
        self.autocommit = autocommit
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.events: list[str] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.info = SimpleNamespace(
            transaction_status=transaction_status or NamedTransactionStatus("IDLE")
        )

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commit_count += 1
        self.events.append("COMMIT")
        if self.commit_count in self.fail_commit_calls:
            self.info.transaction_status.name = "UNKNOWN"
            raise RuntimeError(f"commit failure containing {SESSION_HASH}")
        self.info.transaction_status.name = (
            "INTRANS" if self.commit_count in self.nonidle_commit_calls else "IDLE"
        )

    def rollback(self) -> None:
        self.rollback_count += 1
        self.events.append("ROLLBACK")
        if self.fail_rollback:
            self.info.transaction_status.name = "UNKNOWN"
            raise RuntimeError(f"rollback failure containing {SESSION_HASH}")
        self.info.transaction_status.name = "IDLE"

    def close(self) -> None:
        self.close_count += 1
        self.events.append("CLOSE")
        if self.fail_close:
            raise RuntimeError("simulated close failure")


class NamedTransactionStatus:
    def __init__(self, name: str) -> None:
        self.name = name


class SchemaV2SessionUnitOfWorkTest(unittest.TestCase):
    def test_success_uses_hash_only_role_resolver_and_complete_cleanup_transaction(self) -> None:
        connection = FakeConnection()
        uow = SchemaV2ApiSessionUnitOfWork(
            connection,
            session_token_hash=SESSION_TOKEN_HASH,
        )

        with uow as active:
            context = active.session_context
            self.assertEqual(context.session_id, SESSION_ID)
            self.assertEqual(context.actor_id, "owner@example.test")
            self.assertEqual(context.tenant_id, TENANT_ID)
            self.assertEqual(context.project_ids, (PROJECT_ID,))
            self.assertEqual(context.project_scopes[0].project_id, PROJECT_ID)
            self.assertFalse(hasattr(context, "session_token_hash"))
            with self.assertRaises(dataclasses.FrozenInstanceError):
                context.actor_id = "changed"  # type: ignore[misc]

        self.assertEqual(
            connection.events,
            [
                "SQL:BEGIN",
                "SQL:SET LOCAL ROLE geo_v2_runtime",
                "SQL:SELECT set_config('app.session_token_hash', %s, true)",
                "SQL:SELECT session_id, actor_id, tenant_id, project_ids, "
                "tenant_roles, project_scopes FROM public.geo_v2_resolve_session_context()",
                "COMMIT",
                "SQL:RESET ALL",
                "SQL:RESET ROLE",
                "COMMIT",
            ],
        )
        self.assertEqual(connection.calls[2][1], (SESSION_HASH,))
        self.assertEqual(connection.commit_count, 2)
        self.assertEqual(connection.rollback_count, 0)
        self.assertEqual(uow.transaction_outcome, "committed")
        self.assertEqual(uow.cleanup_telemetry.status, "succeeded")
        self.assertFalse(uow.cleanup_telemetry.connection_discarded)
        self.assertEqual(connection.info.transaction_status.name, "IDLE")
        self.assertTrue(uow.connection_reusable)
        with self.assertRaises(SchemaV2SessionLifecycleError):
            _ = uow.session_context

        sql = "\n".join(statement for statement, _params in connection.calls)
        for forbidden in (
            "app.actor_id",
            "app.tenant_id",
            "app.project_id",
            "app.project_ids",
            "app.roles",
            "geo.runtime_",
            "runtime_sessions",
        ):
            self.assertNotIn(forbidden, sql)

    def test_body_exception_rolls_back_then_commits_reset_without_masking_exception(self) -> None:
        connection = FakeConnection()
        uow = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)
        marker = ValueError("request failed")

        with self.assertRaises(ValueError) as raised:
            with uow:
                raise marker

        self.assertIs(raised.exception, marker)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(uow.transaction_outcome, "rolled_back")
        self.assertEqual(uow.cleanup_telemetry.status, "succeeded")
        self.assertEqual(connection.info.transaction_status.name, "IDLE")
        self.assertEqual(
            connection.events[-4:],
            ["ROLLBACK", "SQL:RESET ALL", "SQL:RESET ROLE", "COMMIT"],
        )

    def test_hash_boundary_is_opaque_and_uow_rejects_direct_strings(self) -> None:
        parameters = inspect.signature(SchemaV2ApiSessionUnitOfWork).parameters
        self.assertEqual(set(parameters), {"connection", "session_token_hash"})
        value = hash_raw_session_token(RAW_SESSION_TOKEN)
        self.assertIs(type(value), SchemaV2SessionTokenHash)
        self.assertNotIn(RAW_SESSION_TOKEN, repr(value))
        self.assertNotIn(SESSION_HASH, repr(value))

        with self.assertRaises(SchemaV2SessionTokenHashError):
            SchemaV2SessionTokenHash(SESSION_HASH)
        connection = FakeConnection()
        with self.assertRaises(SchemaV2SessionTokenHashError):
            SchemaV2ApiSessionUnitOfWork(
                connection,
                session_token_hash=SESSION_HASH,  # type: ignore[arg-type]
            )
        self.assertEqual(connection.calls, [])

        for invalid_raw in ("", 123, None, "x" * 4097):
            with self.subTest(invalid_type=type(invalid_raw).__name__):
                with self.assertRaises(SchemaV2RawSessionTokenError) as raised:
                    hash_raw_session_token(invalid_raw)  # type: ignore[arg-type]
                if invalid_raw not in ("", None):
                    self.assertNotIn(str(invalid_raw), str(raised.exception))

    def test_missing_duplicate_or_malformed_resolver_projection_fails_closed(self) -> None:
        malformed = list(resolver_row())
        malformed[1] = "Owner@Example.TEST"
        unsorted_scope = list(resolver_row())
        unsorted_scope[5] = [
            {
                **unsorted_scope[5][0],
                "permissions": ["project.update", "project.read"],
            }
        ]
        cases = (
            [],
            [resolver_row(), resolver_row()],
            [tuple(malformed)],
            [tuple(unsorted_scope)],
            [resolver_row()[:-1]],
        )
        for rows in cases:
            with self.subTest(row_count=len(rows)):
                connection = FakeConnection(resolver_rows=rows)
                with self.assertRaises(SchemaV2SessionAuthorizationError) as raised:
                    with SchemaV2ApiSessionUnitOfWork(
                        connection,
                        session_token_hash=SESSION_TOKEN_HASH,
                    ):
                        self.fail("invalid resolver context must not enter")
                self.assertNotIn(SESSION_HASH, str(raised.exception))
                self.assertEqual(connection.rollback_count, 1)
                self.assertEqual(connection.commit_count, 1)
                self.assertEqual(connection.close_count, 0)

    def test_database_setup_error_is_redacted_and_connection_is_cleaned(self) -> None:
        connection = FakeConnection(fail_on_sql="geo_v2_resolve_session_context")

        with self.assertRaises(SchemaV2SessionUnitOfWorkError) as raised:
            with SchemaV2ApiSessionUnitOfWork(
                connection,
                session_token_hash=SESSION_TOKEN_HASH,
            ):
                self.fail("database failure must not enter")

        self.assertEqual(raised.exception.code, "session_transaction_setup_failed")
        self.assertNotIn(SESSION_HASH, str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.close_count, 0)

    def test_cleanup_failure_discards_connection_and_marks_it_unusable(self) -> None:
        connection = FakeConnection(fail_on_sql="RESET ALL")
        uow = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)

        with uow:
            pass

        self.assertEqual(uow.transaction_outcome, "committed")
        self.assertEqual(uow.cleanup_telemetry.status, "failed")
        self.assertTrue(uow.cleanup_telemetry.connection_discarded)
        self.assertFalse(uow.connection_reusable)
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(connection.commit_count, 1)

    def test_body_exception_is_preserved_when_cleanup_fails_after_rollback(self) -> None:
        connection = FakeConnection(fail_on_sql="RESET ALL")
        uow = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)
        marker = ValueError("body failure")

        with self.assertRaises(ValueError) as raised:
            with uow:
                raise marker

        self.assertIs(raised.exception, marker)
        self.assertEqual(uow.transaction_outcome, "rolled_back")
        self.assertEqual(uow.cleanup_telemetry.status, "failed")
        self.assertTrue(uow.cleanup_telemetry.connection_discarded)
        self.assertEqual(connection.close_count, 1)

    def test_commit_failure_rolls_back_cleans_and_discards_unknown_outcome_connection(self) -> None:
        connection = FakeConnection(fail_commit_calls={1})
        uow = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)

        with self.assertRaises(SchemaV2SessionCommitOutcomeUnknownError) as raised:
            with uow:
                pass

        self.assertEqual(raised.exception.code, "session_commit_outcome_unknown")
        self.assertFalse(raised.exception.retryable)
        self.assertTrue(raised.exception.requires_idempotency_recovery)
        self.assertEqual(raised.exception.transaction_outcome, "unknown")
        self.assertEqual(uow.transaction_outcome, "unknown")
        self.assertEqual(uow.cleanup_telemetry.status, "succeeded")
        self.assertTrue(uow.cleanup_telemetry.connection_discarded)
        self.assertFalse(uow.connection_reusable)
        self.assertEqual(connection.rollback_count, 1)
        self.assertEqual(connection.commit_count, 2)
        self.assertEqual(connection.close_count, 1)

    def test_cleanup_transaction_commit_failure_discards_connection(self) -> None:
        connection = FakeConnection(fail_commit_calls={2})
        uow = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)

        with uow:
            pass

        self.assertEqual(uow.transaction_outcome, "committed")
        self.assertEqual(uow.cleanup_telemetry.status, "failed")
        self.assertFalse(uow.connection_reusable)
        self.assertEqual(connection.commit_count, 2)
        self.assertEqual(connection.close_count, 1)

    def test_repeated_and_nested_unit_of_work_entry_is_rejected(self) -> None:
        connection = FakeConnection()
        first = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)
        nested = SchemaV2ApiSessionUnitOfWork(
            connection,
            session_token_hash=hash_raw_session_token("nested-token"),
        )

        first.__enter__()
        try:
            with self.assertRaises(SchemaV2SessionLifecycleError):
                first.__enter__()
            with self.assertRaises(SchemaV2SessionLifecycleError):
                nested.__enter__()
        finally:
            first.__exit__(None, None, None)

        with self.assertRaises(SchemaV2SessionLifecycleError):
            first.__enter__()

    def test_nonidle_connection_is_rejected_without_mutating_external_transaction(self) -> None:
        connection = FakeConnection(transaction_status=NamedTransactionStatus("INTRANS"))
        uow = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)

        with self.assertRaises(SchemaV2SessionLifecycleError):
            uow.__enter__()

        self.assertEqual(connection.calls, [])
        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.rollback_count, 0)

    def test_missing_transaction_status_fails_closed_for_uow_and_pool_checkin(self) -> None:
        connection = FakeConnection()
        del connection.info
        uow = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)
        with self.assertRaises(SchemaV2SessionLifecycleError):
            uow.__enter__()
        self.assertEqual(connection.calls, [])

        connections = [connection]

        def connector(_database_url: str) -> FakeConnection:
            return connections[-1]

        pool = RuntimePostgresConnectionPool(
            database_url="configured",
            connector=connector,
            max_size=1,
            timeout_seconds=0,
        )
        pool.acquire().close()
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(pool._created, 0)

    def test_autocommit_connection_is_rejected_before_database_access(self) -> None:
        connection = FakeConnection(autocommit=True)
        with self.assertRaises(SchemaV2SessionLifecycleError):
            SchemaV2ApiSessionUnitOfWork(
                connection,
                session_token_hash=SESSION_TOKEN_HASH,
            )
        self.assertEqual(connection.calls, [])

    def test_nonidle_status_after_cleanup_commit_discards_connection(self) -> None:
        connection = FakeConnection(nonidle_commit_calls={2})
        uow = SchemaV2ApiSessionUnitOfWork(connection, session_token_hash=SESSION_TOKEN_HASH)

        with uow:
            pass

        self.assertEqual(uow.transaction_outcome, "committed")
        self.assertEqual(uow.cleanup_telemetry.status, "failed")
        self.assertFalse(uow.connection_reusable)
        self.assertEqual(connection.close_count, 1)

    def test_pooled_cleanup_failure_invalidates_instead_of_returning_connection(self) -> None:
        connections: list[FakeConnection] = []

        def connector(_database_url: str) -> FakeConnection:
            connection = FakeConnection(
                fail_on_sql="RESET ALL" if not connections else None,
                fail_close=not connections,
            )
            connections.append(connection)
            return connection

        pool = RuntimePostgresConnectionPool(
            database_url="configured",
            connector=connector,
            max_size=1,
            timeout_seconds=0,
        )
        borrowed = pool.acquire()
        uow = SchemaV2ApiSessionUnitOfWork(
            borrowed,  # type: ignore[arg-type]
            session_token_hash=SESSION_TOKEN_HASH,
        )
        with uow:
            pass
        self.assertEqual(uow.cleanup_telemetry.status, "failed")
        self.assertTrue(uow.cleanup_telemetry.connection_discarded)
        self.assertEqual(connections[0].close_count, 1)

        replacement = pool.acquire()
        self.assertEqual(len(connections), 2)
        replacement.invalidate()
        self.assertEqual(connections[1].close_count, 1)

    def test_pool_checkin_discards_connection_that_does_not_return_idle(self) -> None:
        connections: list[FakeConnection] = []

        def connector(_database_url: str) -> FakeConnection:
            connection = FakeConnection(
                nonidle_commit_calls={1} if not connections else set(),
            )
            connections.append(connection)
            return connection

        pool = RuntimePostgresConnectionPool(
            database_url="configured",
            connector=connector,
            max_size=1,
            timeout_seconds=0,
        )
        pool.acquire().close()
        self.assertEqual(connections[0].close_count, 1)
        replacement = pool.acquire()
        self.assertEqual(len(connections), 2)
        replacement.invalidate()

    def test_pooled_wrapper_close_and_invalidate_are_atomic(self) -> None:
        for actions in (("close", "invalidate"), ("close", "close")):
            with self.subTest(actions=actions):
                connections: list[FakeConnection] = []

                def connector(_database_url: str) -> FakeConnection:
                    connection = FakeConnection()
                    connections.append(connection)
                    return connection

                pool = RuntimePostgresConnectionPool(
                    database_url="configured",
                    connector=connector,
                    max_size=1,
                    timeout_seconds=0,
                )
                borrowed = pool.acquire()
                barrier = threading.Barrier(3)
                errors: list[BaseException] = []

                def release(action: str) -> None:
                    try:
                        barrier.wait()
                        getattr(borrowed, action)()
                    except BaseException as exc:
                        errors.append(exc)

                threads = [
                    threading.Thread(target=release, args=(action,))
                    for action in actions
                ]
                for thread in threads:
                    thread.start()
                barrier.wait()
                for thread in threads:
                    thread.join(timeout=2)

                self.assertTrue(all(not thread.is_alive() for thread in threads))
                self.assertEqual(errors, [])
                pool.closeall()
                self.assertEqual(connections[0].close_count, 1)
                self.assertEqual(pool._created, 0)
                self.assertEqual(pool._available.qsize(), 0)

                with self.assertRaises(RuntimePersistenceError):
                    pool.acquire()
                self.assertEqual(len(connections), 1)
                self.assertEqual(pool._created, 0)

    def test_connector_cannot_return_an_already_owned_connection(self) -> None:
        connection = FakeConnection()
        pool = RuntimePostgresConnectionPool(
            database_url="configured",
            connector=lambda _database_url: connection,
            max_size=2,
            timeout_seconds=0,
        )
        first = pool.acquire()
        with self.assertRaises(RuntimePersistenceError):
            pool.acquire()
        self.assertEqual(pool._created, 1)
        self.assertEqual(connection.close_count, 0)
        first.invalidate()
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(pool._created, 0)

    def test_pool_close_retires_connection_finishing_concurrent_reset(self) -> None:
        reset_started = threading.Event()
        allow_reset = threading.Event()

        class BlockingResetConnection(FakeConnection):
            def rollback(self) -> None:
                reset_started.set()
                if not allow_reset.wait(timeout=2):
                    raise RuntimeError("test reset release timed out")
                super().rollback()

        connection = BlockingResetConnection()
        pool = RuntimePostgresConnectionPool(
            database_url="configured",
            connector=lambda _database_url: connection,
            max_size=1,
            timeout_seconds=0,
        )
        borrowed = pool.acquire()
        release_thread = threading.Thread(target=borrowed.close)
        release_thread.start()
        self.assertTrue(reset_started.wait(timeout=2))

        pool.closeall()
        allow_reset.set()
        release_thread.join(timeout=2)

        self.assertFalse(release_thread.is_alive())
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(pool._created, 0)
        self.assertEqual(pool._available.qsize(), 0)
        with self.assertRaises(RuntimePersistenceError):
            pool.acquire()

    def test_pool_close_retires_connection_created_concurrently(self) -> None:
        connector_started = threading.Event()
        allow_connector = threading.Event()
        connection = FakeConnection()
        errors: list[BaseException] = []

        def connector(_database_url: str) -> FakeConnection:
            connector_started.set()
            if not allow_connector.wait(timeout=2):
                raise RuntimeError("test connector release timed out")
            return connection

        pool = RuntimePostgresConnectionPool(
            database_url="configured",
            connector=connector,
            max_size=1,
            timeout_seconds=0,
        )

        def acquire() -> None:
            try:
                pool.acquire()
            except BaseException as exc:
                errors.append(exc)

        acquire_thread = threading.Thread(target=acquire)
        acquire_thread.start()
        self.assertTrue(connector_started.wait(timeout=2))

        pool.closeall()
        allow_connector.set()
        acquire_thread.join(timeout=2)

        self.assertFalse(acquire_thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimePersistenceError)
        self.assertEqual(str(errors[0]), "Runtime PostgreSQL pool is closed")
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(pool._created, 0)
        self.assertEqual(pool._available.qsize(), 0)

    def test_pool_close_is_idempotent_and_checked_out_return_is_retired(self) -> None:
        connection = FakeConnection()
        pool = RuntimePostgresConnectionPool(
            database_url="configured",
            connector=lambda _database_url: connection,
            max_size=1,
            timeout_seconds=0,
        )
        borrowed = pool.acquire()
        barrier = threading.Barrier(3)
        errors: list[BaseException] = []

        def close_pool() -> None:
            try:
                barrier.wait()
                pool.closeall()
            except BaseException as exc:
                errors.append(exc)

        close_threads = [threading.Thread(target=close_pool) for _ in range(2)]
        for thread in close_threads:
            thread.start()
        barrier.wait()
        for thread in close_threads:
            thread.join(timeout=2)

        borrowed.close()
        pool.closeall()

        self.assertTrue(all(not thread.is_alive() for thread in close_threads))
        self.assertEqual(errors, [])
        self.assertEqual(connection.close_count, 1)
        self.assertEqual(pool._created, 0)
        self.assertEqual(pool._available.qsize(), 0)
        with self.assertRaises(RuntimePersistenceError):
            pool.acquire()


if __name__ == "__main__":
    unittest.main()
