from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol


SCHEMA_COMPATIBILITY_ENABLED_ENV = "GENO_SCHEMA_V2_COMPATIBILITY_CHECK_ENABLED"
SCHEMA_EXPECTED_BASELINE_VERSION_ENV = "GENO_SCHEMA_V2_EXPECTED_BASELINE_VERSION"
SCHEMA_EXPECTED_BASELINE_HASH_ENV = "GENO_SCHEMA_V2_EXPECTED_BASELINE_HASH"
SCHEMA_APP_VERSION_ENV = "GENO_APP_VERSION"
SCHEMA_DATABASE_URL_ENV = "DATABASE_URL"
EXPECTED_SCHEMA_GENERATION = 2
DEFAULT_SCHEMA_CONNECT_TIMEOUT_SECONDS = 5

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)(?:[-+].*)?$"
)


class SchemaCompatibilityConnection(Protocol):
    def cursor(self) -> Any: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SchemaCompatibilityConfig:
    expected_baseline_version: str
    expected_baseline_hash: str
    app_version: str


@dataclass(frozen=True)
class SchemaCompatibilityMetadata:
    schema_generation: int
    baseline_version: str
    baseline_hash: str
    minimum_app_version: str


@dataclass(frozen=True)
class SchemaCompatibilityResult:
    enabled: bool
    compatible: bool
    metadata: SchemaCompatibilityMetadata | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SchemaCompatibilityError(RuntimeError):
    """A stable startup error that never includes connection credentials."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError("version must be SemVer-compatible")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def _schema_check_enabled(env: Mapping[str, str]) -> bool:
    raw_value = env.get(SCHEMA_COMPATIBILITY_ENABLED_ENV, "").strip().lower()
    if raw_value in _TRUE_VALUES:
        return True
    if raw_value in _FALSE_VALUES:
        return False
    raise SchemaCompatibilityError(
        "schema_compatibility_configuration_invalid",
        f"{SCHEMA_COMPATIBILITY_ENABLED_ENV} must be a strict boolean",
        details={"setting": SCHEMA_COMPATIBILITY_ENABLED_ENV},
    )


def schema_compatibility_config_from_env(
    env: Mapping[str, str] | None = None,
) -> SchemaCompatibilityConfig | None:
    runtime_env = os.environ if env is None else env
    if not _schema_check_enabled(runtime_env):
        return None

    required_settings = (
        SCHEMA_EXPECTED_BASELINE_VERSION_ENV,
        SCHEMA_EXPECTED_BASELINE_HASH_ENV,
        SCHEMA_APP_VERSION_ENV,
        SCHEMA_DATABASE_URL_ENV,
    )
    missing = [name for name in required_settings if not runtime_env.get(name, "").strip()]
    if missing:
        raise SchemaCompatibilityError(
            "schema_compatibility_configuration_incomplete",
            "Schema v2 compatibility configuration is incomplete",
            details={"missing_settings": missing},
        )

    baseline_hash = runtime_env[SCHEMA_EXPECTED_BASELINE_HASH_ENV].strip()
    if _SHA256_RE.fullmatch(baseline_hash) is None:
        raise SchemaCompatibilityError(
            "schema_compatibility_configuration_invalid",
            f"{SCHEMA_EXPECTED_BASELINE_HASH_ENV} must be a lowercase SHA-256 digest",
            details={"setting": SCHEMA_EXPECTED_BASELINE_HASH_ENV},
        )
    app_version = runtime_env[SCHEMA_APP_VERSION_ENV].strip()
    try:
        _version_tuple(app_version)
    except ValueError:
        raise SchemaCompatibilityError(
            "schema_compatibility_configuration_invalid",
            f"{SCHEMA_APP_VERSION_ENV} must be SemVer-compatible",
            details={"setting": SCHEMA_APP_VERSION_ENV},
        ) from None

    return SchemaCompatibilityConfig(
        expected_baseline_version=runtime_env[SCHEMA_EXPECTED_BASELINE_VERSION_ENV].strip(),
        expected_baseline_hash=baseline_hash,
        app_version=app_version,
    )


def _metadata_from_row(row: object) -> SchemaCompatibilityMetadata:
    if not isinstance(row, (tuple, list)) or len(row) != 4:
        raise SchemaCompatibilityError(
            "schema_metadata_invalid",
            "Schema metadata has an invalid shape",
        )
    try:
        metadata = SchemaCompatibilityMetadata(
            schema_generation=int(row[0]),
            baseline_version=str(row[1]),
            baseline_hash=str(row[2]),
            minimum_app_version=str(row[3]),
        )
    except (TypeError, ValueError):
        raise SchemaCompatibilityError(
            "schema_metadata_invalid",
            "Schema metadata contains invalid values",
        ) from None
    if not metadata.baseline_version or _SHA256_RE.fullmatch(metadata.baseline_hash) is None:
        raise SchemaCompatibilityError(
            "schema_metadata_invalid",
            "Schema metadata contains invalid values",
        )
    try:
        _version_tuple(metadata.minimum_app_version)
    except ValueError:
        raise SchemaCompatibilityError(
            "schema_metadata_invalid",
            "Schema metadata contains an invalid minimum application version",
        ) from None
    return metadata


def read_schema_compatibility_metadata(
    connection: SchemaCompatibilityConnection,
) -> SchemaCompatibilityMetadata:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SELECT to_regclass('public.app_schema_metadata')")
            table_row = cursor.fetchone()
            if table_row is None or table_row[0] is None:
                raise SchemaCompatibilityError(
                    "schema_metadata_missing",
                    "Schema v2 metadata is not installed",
                )
            cursor.execute(
                "SELECT schema_generation, baseline_version, baseline_hash, minimum_app_version "
                "FROM public.app_schema_metadata"
            )
            rows = cursor.fetchall()
    except Exception as exc:
        if isinstance(exc, SchemaCompatibilityError) and exc.code == "schema_metadata_missing":
            raise
        raise SchemaCompatibilityError(
            "schema_metadata_read_failed",
            "Schema v2 metadata could not be read",
        ) from None
    if len(rows) != 1:
        raise SchemaCompatibilityError(
            "schema_metadata_invalid",
            "Schema v2 metadata must contain exactly one row",
            details={"row_count": len(rows)},
        )
    return _metadata_from_row(rows[0])


def assert_schema_compatibility(
    metadata: SchemaCompatibilityMetadata,
    config: SchemaCompatibilityConfig,
) -> None:
    if metadata.schema_generation != EXPECTED_SCHEMA_GENERATION:
        raise SchemaCompatibilityError(
            "schema_generation_mismatch",
            "Database schema generation is incompatible",
            details={
                "expected": EXPECTED_SCHEMA_GENERATION,
                "actual": metadata.schema_generation,
            },
        )
    if metadata.baseline_version != config.expected_baseline_version:
        raise SchemaCompatibilityError(
            "schema_baseline_version_mismatch",
            "Database schema baseline version is incompatible",
            details={
                "expected": config.expected_baseline_version,
                "actual": metadata.baseline_version,
            },
        )
    if metadata.baseline_hash != config.expected_baseline_hash:
        raise SchemaCompatibilityError(
            "schema_baseline_hash_mismatch",
            "Database schema baseline hash is incompatible",
            details={
                "expected": config.expected_baseline_hash,
                "actual": metadata.baseline_hash,
            },
        )
    if _version_tuple(config.app_version) < _version_tuple(metadata.minimum_app_version):
        raise SchemaCompatibilityError(
            "schema_application_version_too_old",
            "Application version is older than the database minimum",
            details={
                "application_version": config.app_version,
                "minimum_app_version": metadata.minimum_app_version,
            },
        )


def _default_connector(database_url: str) -> SchemaCompatibilityConnection:
    try:
        import psycopg
    except ModuleNotFoundError:
        raise SchemaCompatibilityError(
            "schema_database_driver_unavailable",
            "PostgreSQL support is required for the Schema v2 compatibility check",
        ) from None
    return psycopg.connect(
        database_url,
        connect_timeout=DEFAULT_SCHEMA_CONNECT_TIMEOUT_SECONDS,
    )


def check_schema_compatibility_from_env(
    env: Mapping[str, str] | None = None,
    *,
    connector: Callable[[str], SchemaCompatibilityConnection] | None = None,
) -> SchemaCompatibilityResult:
    runtime_env = os.environ if env is None else env
    config = schema_compatibility_config_from_env(runtime_env)
    if config is None:
        return SchemaCompatibilityResult(enabled=False, compatible=True)

    database_url = runtime_env[SCHEMA_DATABASE_URL_ENV].strip()
    connection: SchemaCompatibilityConnection
    try:
        connection = (connector or _default_connector)(database_url)
    except Exception as exc:
        if (
            connector is None
            and isinstance(exc, SchemaCompatibilityError)
            and exc.code == "schema_database_driver_unavailable"
        ):
            raise
        raise SchemaCompatibilityError(
            "schema_database_connection_failed",
            "Schema v2 compatibility database connection failed",
        ) from None

    result: SchemaCompatibilityResult | None = None
    pending_error: SchemaCompatibilityError | None = None
    try:
        metadata = read_schema_compatibility_metadata(connection)
        assert_schema_compatibility(metadata, config)
        result = SchemaCompatibilityResult(
            enabled=True,
            compatible=True,
            metadata=metadata,
        )
    except SchemaCompatibilityError as exc:
        pending_error = exc
    except Exception:
        pending_error = SchemaCompatibilityError(
            "schema_compatibility_check_failed",
            "Schema v2 compatibility check failed",
        )

    try:
        connection.close()
    except Exception:
        if pending_error is None:
            pending_error = SchemaCompatibilityError(
                "schema_database_cleanup_failed",
                "Schema v2 compatibility database cleanup failed",
            )

    if pending_error is not None:
        raise pending_error
    if result is None:  # pragma: no cover - all branches above set a result or error.
        raise SchemaCompatibilityError(
            "schema_compatibility_check_failed",
            "Schema v2 compatibility check failed",
        )
    return result


__all__ = [
    "EXPECTED_SCHEMA_GENERATION",
    "DEFAULT_SCHEMA_CONNECT_TIMEOUT_SECONDS",
    "SCHEMA_APP_VERSION_ENV",
    "SCHEMA_COMPATIBILITY_ENABLED_ENV",
    "SCHEMA_DATABASE_URL_ENV",
    "SCHEMA_EXPECTED_BASELINE_HASH_ENV",
    "SCHEMA_EXPECTED_BASELINE_VERSION_ENV",
    "SchemaCompatibilityConfig",
    "SchemaCompatibilityError",
    "SchemaCompatibilityMetadata",
    "SchemaCompatibilityResult",
    "assert_schema_compatibility",
    "check_schema_compatibility_from_env",
    "read_schema_compatibility_metadata",
    "schema_compatibility_config_from_env",
]
