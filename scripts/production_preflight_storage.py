"""Backup-root and authenticated restore-staging preflight checks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re
import stat

from scripts.production_preflight_common import has_symlink_component
from scripts.production_preflight_contracts import PreflightIssue


_MOUNTINFO_ESCAPE = re.compile(r"\\([0-7]{3})")


def filesystem_type(path: Path) -> str | None:
    try:
        resolved = path.resolve(strict=True)
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    selected: tuple[int, str] | None = None
    for line in lines:
        try:
            left, right = line.split(" - ", 1)
            left_fields = left.split()
            right_fields = right.split()
            mount_point = Path(_decode_mountinfo_path(left_fields[4]))
            filesystem = right_fields[0]
            resolved.relative_to(mount_point)
        except (IndexError, ValueError):
            continue
        specificity = len(mount_point.parts)
        if selected is None or specificity > selected[0]:
            selected = (specificity, filesystem)
    return None if selected is None else selected[1]


def validate_backup_root(
    value: str,
    issues: list[PreflightIssue],
    *,
    current_euid: int,
) -> None:
    _validate_directory(
        value,
        field="GEO_BACKUP_ROOT",
        issues=issues,
        current_euid=current_euid,
        require_tmpfs=False,
        filesystem_resolver=filesystem_type,
    )


def validate_restore_tmpfs_root(
    value: str,
    issues: list[PreflightIssue],
    *,
    current_euid: int,
    filesystem_resolver: Callable[[Path], str | None],
) -> None:
    _validate_directory(
        value,
        field="GEO_RESTORE_TMPFS_ROOT",
        issues=issues,
        current_euid=current_euid,
        require_tmpfs=True,
        filesystem_resolver=filesystem_resolver,
    )


def _validate_directory(
    value: str,
    *,
    field: str,
    issues: list[PreflightIssue],
    current_euid: int,
    require_tmpfs: bool,
    filesystem_resolver: Callable[[Path], str | None],
) -> None:
    path = Path(value)
    if not path.is_absolute():
        issues.append(PreflightIssue("DIRECTORY_PATH_NOT_ABSOLUTE", field))
        return
    if has_symlink_component(path):
        issues.append(PreflightIssue("DIRECTORY_NOT_DIRECTORY", field))
        return
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        issues.append(PreflightIssue("DIRECTORY_NOT_FOUND", field))
        return
    except OSError:
        issues.append(PreflightIssue("DIRECTORY_UNREADABLE", field))
        return
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        issues.append(PreflightIssue("DIRECTORY_NOT_DIRECTORY", field))
        return
    if metadata.st_uid not in {0, current_euid}:
        issues.append(PreflightIssue("DIRECTORY_OWNER", field))
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        issues.append(PreflightIssue("DIRECTORY_PERMISSIONS", field))
    if not stat.S_IMODE(metadata.st_mode) & 0o200:
        issues.append(PreflightIssue("DIRECTORY_NOT_WRITABLE", field))
    if require_tmpfs and filesystem_resolver(path) != "tmpfs":
        issues.append(PreflightIssue("DIRECTORY_NOT_TMPFS", field))


def _decode_mountinfo_path(value: str) -> str:
    return _MOUNTINFO_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


__all__ = ["filesystem_type", "validate_backup_root", "validate_restore_tmpfs_root"]
