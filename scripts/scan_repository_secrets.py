"""Fail CI when repository content contains high-confidence credential material."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
_MAX_FILE_BYTES = 8 * 1024 * 1024
_SENSITIVE_SUFFIXES = frozenset({".env", ".key", ".p12", ".pfx", ".pem"})
_SENSITIVE_NAMES = frozenset({".env", "credentials.json", "service-account.json"})
_SAFE_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")
_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private_key",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("aws_access_key", re.compile(rb"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])")),
    ("google_api_key", re.compile(rb"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}")),
    (
        "github_token",
        re.compile(
            rb"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,}|"
            rb"github_pat_[A-Za-z0-9_]{60,})"
        ),
    ),
    (
        "openai_api_key",
        re.compile(rb"(?<![A-Za-z0-9_-])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    ),
    ("slack_token", re.compile(rb"(?<![A-Za-z0-9-])xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("stripe_live_key", re.compile(rb"(?<![A-Za-z0-9_])sk_live_[A-Za-z0-9]{20,}")),
)


@dataclass(frozen=True)
class SecretFinding:
    path: Path
    categories: tuple[str, ...]


def scan_paths(paths: Iterable[Path]) -> tuple[SecretFinding, ...]:
    findings: list[SecretFinding] = []
    for path in sorted({candidate.absolute() for candidate in paths}, key=str):
        categories = _classify(path)
        if categories:
            findings.append(SecretFinding(path=path, categories=tuple(sorted(categories))))
    return tuple(findings)


def repository_paths(root: Path = ROOT) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError("repository file inventory is unavailable")
    return tuple(root / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw)


def _classify(path: Path) -> set[str]:
    if path.is_symlink():
        return {"symlink"} if _sensitive_filename(path) else set()
    if not path.is_file():
        return set()
    categories: set[str] = set()
    if _sensitive_filename(path):
        categories.add("sensitive_file")
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return categories
        content = path.read_bytes()
    except OSError:
        return {"unreadable"}
    if b"\0" in content[:8192]:
        return categories
    for name, pattern in _PATTERNS:
        if pattern.search(content) is not None:
            categories.add(name)
    return categories


def _sensitive_filename(path: Path) -> bool:
    folded = path.name.casefold()
    if folded.endswith(_SAFE_TEMPLATE_SUFFIXES):
        return False
    return folded in _SENSITIVE_NAMES or path.suffix.casefold() in _SENSITIVE_SUFFIXES


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return "<external-scan-path>"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    try:
        paths = tuple(args.paths) or repository_paths()
    except RuntimeError as error:
        print(f"ERROR code=REPOSITORY_SECRET_SCAN_UNAVAILABLE detail={error}")
        return 2
    findings = scan_paths(paths)
    if findings:
        for finding in findings:
            print(
                "ERROR code=REPOSITORY_SECRET_DETECTED "
                f"path={_display(finding.path)} categories={','.join(finding.categories)}"
            )
        return 2
    print(f"OK code=REPOSITORY_SECRET_SCAN_PASSED files={len(paths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
