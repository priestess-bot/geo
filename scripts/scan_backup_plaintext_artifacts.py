"""Detect plaintext or weakly protected files in backup evidence directories."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import stat
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DISCLOSED_LEGACY_ROOTS = (
    ROOT
    / "artifacts"
    / "advinsys-v600"
    / "20260716-advinsys-v600-01"
    / "backup-restore"
    / "20260716T040909Z",
    ROOT
    / "artifacts"
    / "advinsys-v600"
    / "20260716-gate1-premerge"
    / "backup-restore"
    / "20260716T051157Z",
)
SAFE_BACKUP_FILES = frozenset(
    {
        "COMMITTED",
        "manifest.json",
        "manifest.sig",
        "minio.tar.enc",
        "postgres.sql.gz.enc",
        "receipt.json",
    }
)
PLAINTEXT_NAMES = frozenset({"SHA256SUMS"})
PLAINTEXT_SUFFIXES = (".sql", ".sql.gz", ".tar")
SQL_MARKERS = (
    b"-- PostgreSQL database dump",
    b"SET statement_timeout",
    b"CREATE TABLE ",
)


@dataclass(frozen=True)
class ScanFinding:
    directory: Path
    file_count: int
    total_bytes: int
    categories: tuple[str, ...]
    disclosed_legacy: bool


@dataclass(frozen=True)
class _FileFinding:
    path: Path
    size: int
    categories: frozenset[str]
    disclosed_root: Path | None


def scan_backup_artifacts(
    roots: Iterable[Path],
    *,
    disclosed_roots: Iterable[Path] | None = None,
) -> tuple[ScanFinding, ...]:
    disclosed = tuple(
        path.absolute()
        for path in (
            DISCLOSED_LEGACY_ROOTS if disclosed_roots is None else disclosed_roots
        )
    )
    files: list[_FileFinding] = []
    for root in roots:
        candidate = root.absolute()
        if candidate.is_symlink() or not candidate.exists() or not candidate.is_dir():
            files.append(
                _FileFinding(
                    path=candidate,
                    size=0,
                    categories=frozenset({"unsafe_root"}),
                    disclosed_root=_disclosed_root(candidate, disclosed),
                )
            )
            continue
        for path in candidate.rglob("*"):
            if not path.is_file() and not path.is_symlink():
                continue
            disclosed_root = _disclosed_root(path, disclosed)
            categories = _classify(path, disclosed_root=disclosed_root)
            if not categories:
                continue
            try:
                size = path.lstat().st_size
            except OSError:
                size = 0
                categories.add("unreadable")
            files.append(
                _FileFinding(
                    path=path,
                    size=size,
                    categories=frozenset(categories),
                    disclosed_root=disclosed_root,
                )
            )
    return _aggregate(files)


def _classify(path: Path, *, disclosed_root: Path | None) -> set[str]:
    if disclosed_root is not None:
        return {"legacy_plaintext_backup", "permissions"}
    if not _is_backup_path(path):
        return set()
    categories: set[str] = set()
    if path.is_symlink():
        return {"symlink"}
    try:
        metadata = path.lstat()
    except OSError:
        return {"unreadable"}
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        categories.add("permissions")
    if path.name in SAFE_BACKUP_FILES:
        return categories
    if path.name in PLAINTEXT_NAMES or any(
        path.name.endswith(suffix) for suffix in PLAINTEXT_SUFFIXES
    ):
        categories.add("plaintext_backup_name")
    if _is_backup_path(path):
        categories.add("unexpected_backup_file")
    try:
        with path.open("rb") as stream:
            head = stream.read(512)
    except OSError:
        categories.add("unreadable")
        return categories
    if head.startswith(b"\x1f\x8b"):
        categories.add("gzip_plaintext")
    if len(head) >= 262 and head[257:262] == b"ustar":
        categories.add("tar_plaintext")
    if any(marker in head for marker in SQL_MARKERS):
        categories.add("sql_plaintext")
    return categories


def _is_backup_path(path: Path) -> bool:
    return any(
        "backup-restore" in part.casefold()
        or "backup_restore" in part.casefold()
        or part.casefold() in {"backups", "backup"}
        for part in path.parent.parts
    )


def _disclosed_root(path: Path, disclosed: tuple[Path, ...]) -> Path | None:
    absolute = path.absolute()
    for root in disclosed:
        if absolute == root or absolute.is_relative_to(root):
            return root
    return None


def _aggregate(files: list[_FileFinding]) -> tuple[ScanFinding, ...]:
    groups: dict[tuple[Path, bool], list[_FileFinding]] = {}
    for finding in files:
        directory = finding.disclosed_root or _backup_directory(finding.path)
        groups.setdefault((directory, finding.disclosed_root is not None), []).append(
            finding
        )
    return tuple(
        ScanFinding(
            directory=directory,
            file_count=len(items),
            total_bytes=sum(item.size for item in items),
            categories=tuple(
                sorted({category for item in items for category in item.categories})
            ),
            disclosed_legacy=is_disclosed,
        )
        for (directory, is_disclosed), items in sorted(
            groups.items(), key=lambda item: str(item[0][0])
        )
    )


def _backup_directory(path: Path) -> Path:
    parts = path.parent.parts
    marker_indexes = [
        index for index, part in enumerate(parts) if _is_backup_component(part)
    ]
    if not marker_indexes:
        return path.parent if path.suffix else path
    marker_index = marker_indexes[-1]
    run_end = min(marker_index + 2, len(parts))
    return Path(*parts[:run_end])


def _is_backup_component(value: str) -> bool:
    folded = value.casefold()
    return (
        "backup-restore" in folded
        or "backup_restore" in folded
        or folded in {"backups", "backup"}
    )


def _display_path(path: Path) -> str:
    try:
        return path.absolute().relative_to(ROOT).as_posix()
    except ValueError:
        return "<external-scan-root>"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path, nargs="+", help="Directories to scan")
    parser.add_argument(
        "--allow-disclosed-legacy",
        action="store_true",
        help="Report, but do not fail solely for the two frozen legacy evidence roots",
    )
    args = parser.parse_args(argv)
    findings = scan_backup_artifacts(args.roots)
    unexpected = tuple(item for item in findings if not item.disclosed_legacy)
    disclosed = tuple(item for item in findings if item.disclosed_legacy)
    for item in disclosed:
        print(
            "DISCLOSED code=PREEXISTING_BACKUP_PLAINTEXT "
            f"directory={_display_path(item.directory)} files={item.file_count} "
            f"bytes={item.total_bytes} categories={','.join(item.categories)}"
        )
    for item in unexpected:
        print(
            "ERROR code=BACKUP_PLAINTEXT_OR_WEAK_ARTIFACT "
            f"directory={_display_path(item.directory)} files={item.file_count} "
            f"bytes={item.total_bytes} categories={','.join(item.categories)}"
        )
    if unexpected:
        return 2
    if disclosed and not args.allow_disclosed_legacy:
        return 3
    print(
        "OK code=BACKUP_PLAINTEXT_SCAN_PASSED "
        f"disclosed_legacy_directories={len(disclosed)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
