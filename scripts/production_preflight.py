from __future__ import annotations

import argparse
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


IMAGE_FIELDS = (
    "GEO_POSTGRES_IMAGE",
    "GEO_MINIO_IMAGE",
    "GEO_MINIO_MC_IMAGE",
    "GEO_VALKEY_IMAGE",
    "GEO_API_IMAGE",
    "GEO_ADMIN_WEB_IMAGE",
    "GEO_CUSTOMER_WEB_IMAGE",
    "GEO_OTEL_COLLECTOR_IMAGE",
)

SECRET_FILE_FIELDS = (
    "GEO_POSTGRES_INSTALLER_PASSWORD_FILE",
    "GEO_INSTALLER_DATABASE_URL_FILE",
    "GEO_DATABASE_URL_FILE",
    "GEO_WORKER_DATABASE_URL_FILE",
    "GEO_AUTH_TOKEN_SECRET_FILE",
    "GEO_MINIO_ROOT_USER_FILE",
    "GEO_MINIO_ROOT_PASSWORD_FILE",
    "GEO_OBJECT_STORE_ACCESS_KEY_FILE",
    "GEO_OBJECT_STORE_SECRET_KEY_FILE",
    "GEO_OBJECT_STORE_BACKUP_ACCESS_KEY_FILE",
    "GEO_OBJECT_STORE_BACKUP_SECRET_KEY_FILE",
    "GEO_OBJECT_STORE_RESTORE_ACCESS_KEY_FILE",
    "GEO_OBJECT_STORE_RESTORE_SECRET_KEY_FILE",
    "GEO_OBJECT_STORE_RETENTION_ACCESS_KEY_FILE",
    "GEO_OBJECT_STORE_RETENTION_SECRET_KEY_FILE",
    "GEO_DEEPSEEK_API_KEY_FILE",
    "GEO_RESTORE_SMOKE_PASSWORD_FILE",
)

HTTPS_URL_FIELDS = (
    "GEO_OIDC_DISCOVERY_URL",
    "GEO_JWT_ISSUER",
    "GEO_ADMIN_OIDC_LOGIN_URL",
    "GEO_ADMIN_OIDC_LOGOUT_URL",
    "GEO_ADMIN_WEB_BASE_URL",
    "GEO_CUSTOMER_WEB_BASE_URL",
)

REQUIRED_TEXT_FIELDS = (
    "GEO_JWT_AUDIENCE",
    "GEO_ADMIN_OIDC_ALLOWED_ORIGINS",
    "GEO_RELEASE_VERSION",
    "GEO_BACKUP_ROOT",
)

INTEGER_BOUNDS = {
    "GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS": (1, 10),
    "GEO_READINESS_TOTAL_TIMEOUT_SECONDS": (2, 30),
    "GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS": (1, 300),
    "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS": (1, 3_600),
    "GEO_RUNTIME_QUEUED_STALE_SECONDS": (1, 604_800),
    "GEO_RUNTIME_OUTBOX_STALE_SECONDS": (1, 604_800),
    "GEO_RUNTIME_RUNNING_GRACE_SECONDS": (0, 86_400),
    "GEO_RUNTIME_FAILURE_WINDOW_SECONDS": (1, 2_592_000),
    "GEO_RUNTIME_EXPECTED_TASK_WORKER_INSTANCES": (1, 100),
    "GEO_RUNTIME_EXPECTED_OUTBOX_RELAY_INSTANCES": (1, 100),
}

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IMAGE_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-fA-F]{64}$")
_RELEASE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RELEASE_PLACEHOLDERS = {"development", "latest", "replace", "unknown"}
_MAX_SECRET_BYTES = 65_536


@dataclass(frozen=True, order=True)
class PreflightIssue:
    code: str
    field: str


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env_file(path: Path) -> tuple[dict[str, str], list[PreflightIssue]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, [PreflightIssue("ENV_FILE_NOT_FOUND", "ENV_FILE")]
    except (OSError, UnicodeError):
        return {}, [PreflightIssue("ENV_FILE_UNREADABLE", "ENV_FILE")]

    values: dict[str, str] = {}
    issues: list[PreflightIssue] = []
    for line in raw.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if candidate.startswith("export "):
            candidate = candidate.removeprefix("export ").lstrip()
        if "=" not in candidate:
            issues.append(PreflightIssue("ENV_SYNTAX_INVALID", "ENV_FILE"))
            continue
        key, value = candidate.split("=", 1)
        key = key.strip()
        if not _ENV_KEY.fullmatch(key):
            issues.append(PreflightIssue("ENV_KEY_INVALID", "ENV_FILE"))
            continue
        if key in values:
            issues.append(PreflightIssue("ENV_KEY_DUPLICATE", key))
            continue
        values[key] = _unquote(value.strip())
    return values, issues


def _required_value(
    values: dict[str, str], field: str, issues: list[PreflightIssue]
) -> str | None:
    if field not in values:
        issues.append(PreflightIssue("CONFIG_REQUIRED", field))
        return None
    value = values[field].strip()
    if not value:
        issues.append(PreflightIssue("CONFIG_EMPTY", field))
        return None
    return value


def _valid_https_url(value: str, *, origin_only: bool = False) -> bool:
    if any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port is None and parsed.netloc.endswith(":")
        or port == 0
    ):
        return False
    if origin_only and (parsed.path not in {"", "/"} or parsed.query):
        return False
    return True


def _validate_secret_file(field: str, value: str, issues: list[PreflightIssue]) -> None:
    path = Path(value)
    if not path.is_absolute():
        issues.append(PreflightIssue("SECRET_PATH_NOT_ABSOLUTE", field))
        return
    try:
        metadata = path.stat()
    except FileNotFoundError:
        issues.append(PreflightIssue("SECRET_FILE_NOT_FOUND", field))
        return
    except OSError:
        issues.append(PreflightIssue("SECRET_FILE_UNREADABLE", field))
        return
    if not stat.S_ISREG(metadata.st_mode):
        issues.append(PreflightIssue("SECRET_FILE_NOT_REGULAR", field))
    try:
        with path.open("rb") as secret_file:
            content = secret_file.read(_MAX_SECRET_BYTES + 1)
    except OSError:
        issues.append(PreflightIssue("SECRET_FILE_UNREADABLE", field))
    else:
        if len(content) > _MAX_SECRET_BYTES:
            issues.append(PreflightIssue("SECRET_FILE_TOO_LARGE", field))
        elif not content.strip():
            issues.append(PreflightIssue("SECRET_FILE_EMPTY", field))
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o077 or not mode & stat.S_IRUSR:
        issues.append(PreflightIssue("SECRET_FILE_PERMISSIONS", field))


def _validate_backup_root(value: str, issues: list[PreflightIssue]) -> None:
    path = Path(value)
    if not path.is_absolute():
        issues.append(PreflightIssue("DIRECTORY_PATH_NOT_ABSOLUTE", "GEO_BACKUP_ROOT"))
        return
    try:
        metadata = path.stat()
    except FileNotFoundError:
        issues.append(PreflightIssue("DIRECTORY_NOT_FOUND", "GEO_BACKUP_ROOT"))
        return
    except OSError:
        issues.append(PreflightIssue("DIRECTORY_UNREADABLE", "GEO_BACKUP_ROOT"))
        return
    if not stat.S_ISDIR(metadata.st_mode):
        issues.append(PreflightIssue("DIRECTORY_NOT_DIRECTORY", "GEO_BACKUP_ROOT"))
    elif not stat.S_IMODE(metadata.st_mode) & 0o222:
        issues.append(PreflightIssue("DIRECTORY_NOT_WRITABLE", "GEO_BACKUP_ROOT"))


def validate_environment(values: dict[str, str]) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []

    for field in IMAGE_FIELDS:
        value = _required_value(values, field, issues)
        if value is not None and (
            not _IMAGE_DIGEST.fullmatch(value) or "replace" in value.casefold()
        ):
            issues.append(PreflightIssue("IMAGE_NOT_DIGEST_PINNED", field))

    for field in SECRET_FILE_FIELDS:
        value = _required_value(values, field, issues)
        if value is not None:
            _validate_secret_file(field, value, issues)

    for field in HTTPS_URL_FIELDS:
        value = _required_value(values, field, issues)
        if value is not None and not _valid_https_url(value):
            issues.append(PreflightIssue("URL_NOT_HTTPS", field))

    for field in REQUIRED_TEXT_FIELDS:
        _required_value(values, field, issues)

    origins = values.get("GEO_ADMIN_OIDC_ALLOWED_ORIGINS", "").strip()
    if origins:
        origin_values = [origin.strip() for origin in origins.split(",")]
        if any(
            not origin or not _valid_https_url(origin, origin_only=True)
            for origin in origin_values
        ):
            issues.append(
                PreflightIssue("ORIGIN_NOT_HTTPS", "GEO_ADMIN_OIDC_ALLOWED_ORIGINS")
            )

    release_version = values.get("GEO_RELEASE_VERSION", "").strip()
    if release_version and (
        not _RELEASE_VERSION.fullmatch(release_version)
        or release_version.casefold() in _RELEASE_PLACEHOLDERS
        or "replace" in release_version.casefold()
    ):
        issues.append(PreflightIssue("RELEASE_VERSION_INVALID", "GEO_RELEASE_VERSION"))

    parsed_integers: dict[str, int] = {}
    for field, (minimum, maximum) in INTEGER_BOUNDS.items():
        value = _required_value(values, field, issues)
        if value is None:
            continue
        try:
            parsed = int(value)
        except ValueError:
            issues.append(PreflightIssue("THRESHOLD_NOT_INTEGER", field))
            continue
        parsed_integers[field] = parsed
        if not minimum <= parsed <= maximum:
            issues.append(PreflightIssue("THRESHOLD_OUT_OF_RANGE", field))

    dependency_timeout = parsed_integers.get("GEO_READINESS_DEPENDENCY_TIMEOUT_SECONDS")
    total_timeout = parsed_integers.get("GEO_READINESS_TOTAL_TIMEOUT_SECONDS")
    if dependency_timeout is not None and total_timeout is not None:
        if total_timeout <= dependency_timeout:
            issues.append(
                PreflightIssue(
                    "READINESS_TOTAL_NOT_GREATER",
                    "GEO_READINESS_TOTAL_TIMEOUT_SECONDS",
                )
            )

    heartbeat_interval = parsed_integers.get("GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS")
    heartbeat_stale = parsed_integers.get("GEO_RUNTIME_HEARTBEAT_STALE_SECONDS")
    if heartbeat_interval is not None and heartbeat_stale is not None:
        if heartbeat_stale <= heartbeat_interval:
            issues.append(
                PreflightIssue(
                    "HEARTBEAT_STALE_NOT_GREATER",
                    "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS",
                )
            )

    backup_root = values.get("GEO_BACKUP_ROOT", "").strip()
    if backup_root:
        _validate_backup_root(backup_root, issues)

    return sorted(set(issues))


def run_preflight(path: Path) -> list[PreflightIssue]:
    values, parse_issues = parse_env_file(path)
    if parse_issues:
        return sorted(set(parse_issues))
    return validate_environment(values)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate production configuration safely.")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path("infra/production.env"),
        help="Production env file to validate without evaluating shell syntax.",
    )
    args = parser.parse_args(argv)

    issues = run_preflight(args.env_file)
    if issues:
        for issue in issues:
            print(f"ERROR code={issue.code} field={issue.field}")
        return 2
    print("OK code=PRODUCTION_PREFLIGHT_PASSED field=CONFIG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
