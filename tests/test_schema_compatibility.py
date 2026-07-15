from __future__ import annotations

import unittest

from geo_core.runtime import validate_runtime_schema_compatibility
from geo_core.schema_compatibility import (
    SCHEMA_APP_VERSION_ENV,
    SCHEMA_COMPATIBILITY_ENABLED_ENV,
    SCHEMA_DATABASE_URL_ENV,
    SCHEMA_EXPECTED_BASELINE_HASH_ENV,
    SCHEMA_EXPECTED_BASELINE_VERSION_ENV,
    SchemaCompatibilityError,
)


BASELINE_HASH = "a" * 64
DATABASE_URL = "postgresql://schema_user:SECRET_MARKER@db.internal:5432/geo_v2"


def enabled_environment(**overrides: str) -> dict[str, str]:
    environment = {
        SCHEMA_COMPATIBILITY_ENABLED_ENV: "1",
        SCHEMA_EXPECTED_BASELINE_VERSION_ENV: "2.0.0-b1",
        SCHEMA_EXPECTED_BASELINE_HASH_ENV: BASELINE_HASH,
        SCHEMA_APP_VERSION_ENV: "0.1.0",
        SCHEMA_DATABASE_URL_ENV: DATABASE_URL,
    }
    environment.update(overrides)
    return environment


class FakeCursor:
    def __init__(
        self,
        *,
        table_exists: bool = True,
        metadata_rows: list[tuple[object, ...]] | None = None,
        query_error: Exception | None = None,
    ) -> None:
        self.table_exists = table_exists
        self.metadata_rows = metadata_rows or []
        self.query_error = query_error
        self.statements: list[str] = []
        self._last_statement = ""

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        if self.query_error is not None:
            raise self.query_error
        self._last_statement = " ".join(statement.split())
        self.statements.append(self._last_statement)

    def fetchone(self) -> tuple[str | None]:
        if "to_regclass" not in self._last_statement:
            raise AssertionError("fetchone called for an unexpected statement")
        return ("app_schema_metadata" if self.table_exists else None,)

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.metadata_rows)


class FakeConnection:
    def __init__(self, cursor: FakeCursor, *, close_error: Exception | None = None) -> None:
        self.cursor_instance = cursor
        self.close_error = close_error
        self.close_count = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


def compatible_connection(
    *,
    generation: int = 2,
    baseline_version: str = "2.0.0-b1",
    baseline_hash: str = BASELINE_HASH,
    minimum_app_version: str = "0.1.0",
) -> FakeConnection:
    return FakeConnection(
        FakeCursor(
            metadata_rows=[
                (generation, baseline_version, baseline_hash, minimum_app_version),
            ]
        )
    )


class SchemaCompatibilityContractsTest(unittest.TestCase):
    def test_v1_default_is_disabled_without_connecting(self) -> None:
        calls: list[str] = []

        def connector(database_url: str) -> FakeConnection:
            calls.append(database_url)
            raise AssertionError("disabled check must not connect")

        result = validate_runtime_schema_compatibility({}, connector=connector)

        self.assertFalse(result.enabled)
        self.assertTrue(result.compatible)
        self.assertIsNone(result.metadata)
        self.assertEqual(calls, [])

    def test_enabled_check_reads_and_validates_exact_metadata(self) -> None:
        connection = compatible_connection()
        seen_urls: list[str] = []

        def connector(database_url: str) -> FakeConnection:
            seen_urls.append(database_url)
            return connection

        result = validate_runtime_schema_compatibility(
            enabled_environment(),
            connector=connector,
        )

        self.assertTrue(result.enabled)
        self.assertTrue(result.compatible)
        self.assertEqual(result.metadata.schema_generation, 2)
        self.assertEqual(result.metadata.baseline_version, "2.0.0-b1")
        self.assertEqual(result.metadata.baseline_hash, BASELINE_HASH)
        self.assertEqual(result.metadata.minimum_app_version, "0.1.0")
        self.assertEqual(seen_urls, [DATABASE_URL])
        self.assertEqual(connection.close_count, 1)
        statements = "\n".join(connection.cursor_instance.statements)
        self.assertIn("SET TRANSACTION READ ONLY", statements)
        self.assertIn("to_regclass('public.app_schema_metadata')", statements)
        self.assertIn("FROM public.app_schema_metadata", statements)

    def test_missing_metadata_fails_closed(self) -> None:
        connection = FakeConnection(FakeCursor(table_exists=False))

        with self.assertRaises(SchemaCompatibilityError) as raised:
            validate_runtime_schema_compatibility(
                enabled_environment(),
                connector=lambda _database_url: connection,
            )

        self.assertEqual(raised.exception.code, "schema_metadata_missing")
        self.assertEqual(connection.close_count, 1)

    def test_generation_baseline_version_and_hash_mismatches_are_distinct(self) -> None:
        cases = (
            (
                compatible_connection(generation=1),
                "schema_generation_mismatch",
            ),
            (
                compatible_connection(baseline_version="2.0.0-other"),
                "schema_baseline_version_mismatch",
            ),
            (
                compatible_connection(baseline_hash="b" * 64),
                "schema_baseline_hash_mismatch",
            ),
        )
        for connection, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(SchemaCompatibilityError) as raised:
                    validate_runtime_schema_compatibility(
                        enabled_environment(),
                        connector=lambda _database_url, current=connection: current,
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(connection.close_count, 1)

    def test_application_older_than_database_minimum_fails_closed(self) -> None:
        connection = compatible_connection(minimum_app_version="0.2.0")

        with self.assertRaises(SchemaCompatibilityError) as raised:
            validate_runtime_schema_compatibility(
                enabled_environment(),
                connector=lambda _database_url: connection,
            )

        self.assertEqual(raised.exception.code, "schema_application_version_too_old")
        self.assertEqual(
            raised.exception.details,
            {"application_version": "0.1.0", "minimum_app_version": "0.2.0"},
        )

    def test_incomplete_enabled_configuration_fails_before_connecting(self) -> None:
        environment = enabled_environment()
        environment.pop(SCHEMA_EXPECTED_BASELINE_HASH_ENV)

        with self.assertRaises(SchemaCompatibilityError) as raised:
            validate_runtime_schema_compatibility(
                environment,
                connector=lambda _database_url: self.fail("must not connect"),
            )

        self.assertEqual(
            raised.exception.code,
            "schema_compatibility_configuration_incomplete",
        )
        self.assertEqual(
            raised.exception.details,
            {"missing_settings": [SCHEMA_EXPECTED_BASELINE_HASH_ENV]},
        )

    def test_connection_and_query_errors_do_not_disclose_credentials(self) -> None:
        def connection_failure(_database_url: str) -> FakeConnection:
            raise RuntimeError(f"could not connect with {DATABASE_URL}")

        with self.assertRaises(SchemaCompatibilityError) as connection_error:
            validate_runtime_schema_compatibility(
                enabled_environment(),
                connector=connection_failure,
            )
        self.assertEqual(
            connection_error.exception.to_dict(),
            {
                "code": "schema_database_connection_failed",
                "message": "Schema v2 compatibility database connection failed",
                "details": {},
            },
        )

        query_connection = FakeConnection(
            FakeCursor(query_error=RuntimeError(f"query failed for {DATABASE_URL}"))
        )
        with self.assertRaises(SchemaCompatibilityError) as query_error:
            validate_runtime_schema_compatibility(
                enabled_environment(),
                connector=lambda _database_url: query_connection,
            )
        self.assertEqual(query_error.exception.code, "schema_metadata_read_failed")

        serialized_errors = f"{connection_error.exception.to_dict()} {query_error.exception.to_dict()}"
        self.assertNotIn("SECRET_MARKER", serialized_errors)
        self.assertNotIn("schema_user", serialized_errors)
        self.assertNotIn("postgresql://", serialized_errors)
        self.assertEqual(query_connection.close_count, 1)

    def test_adapter_defined_errors_cannot_bypass_redaction(self) -> None:
        def connection_failure(_database_url: str) -> FakeConnection:
            raise SchemaCompatibilityError(
                "adapter_error",
                f"adapter exposed {DATABASE_URL}",
            )

        with self.assertRaises(SchemaCompatibilityError) as connection_error:
            validate_runtime_schema_compatibility(
                enabled_environment(),
                connector=connection_failure,
            )

        self.assertEqual(connection_error.exception.code, "schema_database_connection_failed")
        self.assertNotIn("SECRET_MARKER", str(connection_error.exception.to_dict()))

        query_connection = FakeConnection(
            FakeCursor(
                query_error=SchemaCompatibilityError(
                    "adapter_query_error",
                    f"adapter exposed {DATABASE_URL}",
                )
            )
        )
        with self.assertRaises(SchemaCompatibilityError) as query_error:
            validate_runtime_schema_compatibility(
                enabled_environment(),
                connector=lambda _database_url: query_connection,
            )

        self.assertEqual(query_error.exception.code, "schema_metadata_read_failed")
        self.assertNotIn("SECRET_MARKER", str(query_error.exception.to_dict()))


if __name__ == "__main__":
    unittest.main()
