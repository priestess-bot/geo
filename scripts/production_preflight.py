"""Fail-closed production configuration preflight CLI and public API."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.production_preflight_contracts import (  # noqa: E402
    APPLICATION_SECRET_GID,
    APPLICATION_SECRET_UID,
    CONFIG_FILE_FIELDS,
    HTTPS_URL_FIELDS,
    IMAGE_FIELDS,
    INTEGER_BOUNDS,
    PreflightIssue,
    REQUIRED_TEXT_FIELDS,
    SECRET_FILE_FIELDS,
)
from scripts.production_preflight_alerts import validate_alert_runtime  # noqa: E402
from scripts.production_preflight_runtime import (  # noqa: E402
    required_value,
    validate_runtime_values,
)
from scripts.production_preflight_secrets import (  # noqa: E402
    validate_key_domain_isolation,
    validate_key_material,
    validate_secret_file,
)
from scripts.production_preflight_storage import (  # noqa: E402
    filesystem_type,
    validate_backup_root,
    validate_restore_tmpfs_root,
)
from scripts.production_preflight_style import (  # noqa: E402
    read_style_registry_file,
    validate_style_registry,
    validate_style_runtime,
)


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_file(path: Path) -> tuple[dict[str, str], list[PreflightIssue]]:
    """Parse an env file without executing shell syntax."""

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


def validate_environment(values: dict[str, str]) -> list[PreflightIssue]:
    """Validate one already parsed production environment."""

    issues: list[PreflightIssue] = []
    secret_contents: dict[str, bytes] = {}
    style_registry_content: bytes | None = None

    validate_runtime_values(values, issues)
    for field in SECRET_FILE_FIELDS:
        value = required_value(values, field, issues)
        if value is None:
            continue
        content = validate_secret_file(
            field,
            value,
            issues,
            application_owner=_application_secret_owner,
            current_euid=os.geteuid(),
        )
        if content is not None:
            secret_contents[field] = content

    for field in CONFIG_FILE_FIELDS:
        value = required_value(values, field, issues)
        if value is not None:
            style_registry_content = read_style_registry_file(
                value,
                issues,
                current_euid=os.geteuid(),
            )

    backup_root = values.get("GEO_BACKUP_ROOT", "").strip()
    if backup_root:
        validate_backup_root(backup_root, issues, current_euid=os.geteuid())
    restore_tmpfs_root = values.get("GEO_RESTORE_TMPFS_ROOT", "").strip()
    if restore_tmpfs_root:
        validate_restore_tmpfs_root(
            restore_tmpfs_root,
            issues,
            current_euid=os.geteuid(),
            filesystem_resolver=_filesystem_type,
        )
    validate_key_material(values, secret_contents, issues)
    validate_key_domain_isolation(values, secret_contents, issues)
    validate_style_runtime(values, issues)
    validate_style_registry(values, style_registry_content, issues)
    validate_alert_runtime(values, issues)
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


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _application_secret_owner() -> tuple[int, int]:
    return APPLICATION_SECRET_UID, APPLICATION_SECRET_GID


def _filesystem_type(path: Path) -> str | None:
    return filesystem_type(path)


__all__ = [
    "APPLICATION_SECRET_GID",
    "APPLICATION_SECRET_UID",
    "CONFIG_FILE_FIELDS",
    "HTTPS_URL_FIELDS",
    "IMAGE_FIELDS",
    "INTEGER_BOUNDS",
    "PreflightIssue",
    "REQUIRED_TEXT_FIELDS",
    "SECRET_FILE_FIELDS",
    "main",
    "parse_env_file",
    "run_preflight",
    "validate_environment",
]


if __name__ == "__main__":
    sys.exit(main())
