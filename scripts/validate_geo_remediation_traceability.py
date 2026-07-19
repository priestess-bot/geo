"""Validate GEO acceptance evidence against real test collectors and commands."""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import re
import shlex
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.geo_remediation_clause_map import (  # noqa: E402
    ACCEPTANCE_EVIDENCE,
    HIGH_RISK_BEHAVIOR_CLAUSES,
    REQUIRED_BEHAVIOR_SCENARIOS,
)
from scripts.geo_remediation_registry import (  # noqa: E402
    EvidenceTarget,
    TEST_EVIDENCE,
)

PLAN = ROOT / "docs/engineering/GEO-accepted-remediation-implementation-plan-2026-07-19.md"
ACCEPTED_FINDINGS = {
    "001",
    "009",
    "011",
    "012",
    "013",
    "014",
    "015",
    "016",
    "018",
    "019",
    "021",
    "023",
    "025",
    "027",
}


class TraceabilityError(AssertionError):
    pass


def plan_traceability_rows(document: str) -> dict[str, str]:
    section = document.split("### 6.1 验收追踪矩阵", maxsplit=1)[1].split(
        "## 7. 测试目标与发布门禁", maxsplit=1
    )[0]
    return {
        finding: mapping
        for finding, mapping in re.findall(
            r"^\| F-(\d{3}) \| (.+) \|$", section, re.MULTILINE
        )
    }


def plan_clauses(document: str) -> set[str]:
    section = document.split("## 6. 逐项验收标准与测试清单", maxsplit=1)[1].split(
        "### 6.1 验收追踪矩阵", maxsplit=1
    )[0]
    return set(re.findall(r"`(F\d{3}-AC\d+)`", section))


def plan_test_ids(document: str) -> set[str]:
    section = document.split("## 6. 逐项验收标准与测试清单", maxsplit=1)[1].split(
        "## 7. 测试目标与发布门禁", maxsplit=1
    )[0]
    return set(re.findall(r"`(F\d{3}-[A-Z]+-\d+)`", section))


def missing_evidence() -> dict[str, tuple[str, ...]]:
    missing: dict[str, tuple[str, ...]] = {}
    for test_id, targets in TEST_EVIDENCE.items():
        reasons = tuple(
            target.reason or "unspecified missing executable evidence"
            for target in targets
            if target.kind == "missing"
        )
        if reasons:
            missing[test_id] = reasons
    return missing


def validate_registry_shape(document: str) -> None:
    rows = plan_traceability_rows(document)
    clauses = plan_clauses(document)
    planned_test_ids = plan_test_ids(document)
    errors: list[str] = []
    if set(rows) != ACCEPTED_FINDINGS:
        errors.append(
            f"traceability findings differ: expected {sorted(ACCEPTED_FINDINGS)}, "
            f"found {sorted(rows)}"
        )
    if len(clauses) != 70:
        errors.append(f"expected 70 acceptance clauses, found {len(clauses)}")
    if set(ACCEPTANCE_EVIDENCE) != clauses:
        errors.append(
            _set_difference("acceptance clause registry", clauses, set(ACCEPTANCE_EVIDENCE))
        )
    if set(TEST_EVIDENCE) != planned_test_ids:
        errors.append(
            _set_difference("stable test ID registry", planned_test_ids, set(TEST_EVIDENCE))
        )
    referenced = {
        test_id for test_ids in ACCEPTANCE_EVIDENCE.values() for test_id in test_ids
    }
    unknown = referenced - set(TEST_EVIDENCE)
    if unknown:
        errors.append(f"clauses reference unregistered test IDs: {sorted(unknown)}")
    unused = set(TEST_EVIDENCE) - referenced
    if unused:
        errors.append(f"planned test IDs have no acceptance clause: {sorted(unused)}")

    for clause in sorted(HIGH_RISK_BEHAVIOR_CLAUSES):
        targets = [
            target
            for test_id in ACCEPTANCE_EVIDENCE.get(clause, ())
            for target in TEST_EVIDENCE.get(test_id, ())
        ]
        has_behavior = any(
            target.behavior and target.kind in {"pytest", "playwright"}
            for target in targets
        )
        explicitly_missing = any(target.kind == "missing" for target in targets)
        if not has_behavior and not explicitly_missing:
            errors.append(
                f"{clause} lacks pytest/Playwright behavior evidence; source or command "
                "contracts cannot be its only proof"
            )
    for scenario, scenario_clauses in REQUIRED_BEHAVIOR_SCENARIOS.items():
        unknown_clauses = scenario_clauses - clauses
        if unknown_clauses:
            errors.append(
                f"{scenario} behavior registry references unknown clauses: "
                f"{sorted(unknown_clauses)}"
            )
    if errors:
        raise TraceabilityError("\n".join(errors))


def validate_target_definitions(root: Path = ROOT) -> None:
    errors: list[str] = []
    for test_id, targets in sorted(TEST_EVIDENCE.items()):
        if not targets:
            errors.append(f"{test_id}: target list is empty")
        for target in targets:
            try:
                if target.kind == "pytest":
                    _validate_pytest_node(root, target.locator)
                elif target.kind == "playwright":
                    _validate_playwright_source(root, target)
                elif target.kind == "command":
                    _validate_command(root, target.locator)
                elif target.kind != "missing":
                    raise TraceabilityError(f"unsupported evidence kind {target.kind!r}")
            except (OSError, SyntaxError, TraceabilityError) as error:
                errors.append(f"{test_id}: {error}")
    if errors:
        raise TraceabilityError("\n".join(errors))


def collect_registered_targets(root: Path = ROOT) -> None:
    _collect_pytest_nodes(root)
    _collect_playwright_titles(root)


def _validate_pytest_node(root: Path, node: str) -> None:
    parts = node.split("::")
    if len(parts) < 2 or not parts[0].endswith(".py"):
        raise TraceabilityError(f"invalid pytest node {node!r}")
    path = root / parts[0]
    if not path.is_file():
        raise TraceabilityError(f"pytest file does not exist: {parts[0]}")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    body: list[ast.stmt] = list(tree.body)
    for index, raw_name in enumerate(parts[1:]):
        name = raw_name.split("[", maxsplit=1)[0]
        matches = [
            item
            for item in body
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        ]
        if len(matches) != 1:
            raise TraceabilityError(f"pytest node object does not exist exactly once: {node}")
        selected = matches[0]
        if index < len(parts[1:]) - 1:
            if not isinstance(selected, ast.ClassDef):
                raise TraceabilityError(f"non-class intermediate pytest node: {node}")
            body = list(selected.body)
        elif not isinstance(selected, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise TraceabilityError(f"pytest node does not end in a function: {node}")
    if not parts[-1].startswith("test_"):
        raise TraceabilityError(f"pytest function is not a test: {node}")


def _validate_playwright_source(root: Path, target: EvidenceTarget) -> None:
    if not target.file or not target.config or not target.project:
        raise TraceabilityError("Playwright target requires file, config and project")
    path = root / target.file
    config = root / target.config
    if not path.is_file():
        raise TraceabilityError(f"Playwright spec does not exist: {target.file}")
    if not config.is_file():
        raise TraceabilityError(f"Playwright config does not exist: {target.config}")
    titles = re.findall(r"\btest\(\s*[\"']([^\"']+)[\"']\s*,", path.read_text(encoding="utf-8"))
    if titles.count(target.locator) != 1:
        raise TraceabilityError(
            f"Playwright exact title does not exist once in {target.file}: {target.locator!r}"
        )


def _validate_command(root: Path, command: str) -> None:
    arguments = shlex.split(command)
    if len(arguments) != 2 or arguments[0] != "make":
        raise TraceabilityError(f"unreviewed infrastructure command shape: {command!r}")
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", makefile, re.MULTILINE))
    if arguments[1] not in targets:
        raise TraceabilityError(f"Make target does not exist: {arguments[1]}")


def _collect_pytest_nodes(root: Path) -> None:
    nodes = sorted(
        {
            target.locator
            for targets in TEST_EVIDENCE.values()
            for target in targets
            if target.kind == "pytest"
        }
    )
    completed = subprocess.run(
        ("uv", "run", "pytest", "--collect-only", "-q", *nodes),
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode:
        raise TraceabilityError(
            "registered pytest nodes do not collect:\n"
            + (completed.stdout + completed.stderr).strip()
        )
    collected = {
        line.strip().split("[", maxsplit=1)[0]
        for line in completed.stdout.splitlines()
        if "::test_" in line
    }
    absent = set(nodes) - collected
    if absent:
        raise TraceabilityError(f"pytest collector omitted registered nodes: {sorted(absent)}")


def _collect_playwright_titles(root: Path) -> None:
    grouped: dict[tuple[str, str], list[EvidenceTarget]] = defaultdict(list)
    for targets in TEST_EVIDENCE.values():
        for target in targets:
            if target.kind == "playwright":
                assert target.config and target.project and target.file
                grouped[(target.config, target.project)].append(target)
    for (config, project), group_targets in sorted(grouped.items()):
        files = sorted({target.file for target in group_targets if target.file})
        completed = subprocess.run(
            (
                "corepack",
                "pnpm",
                "exec",
                "playwright",
                "test",
                "--list",
                f"--config={config}",
                f"--project={project}",
                *files,
            ),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode:
            raise TraceabilityError(
                f"Playwright collector failed for {config}/{project}:\n"
                + (completed.stdout + completed.stderr).strip()
            )
        collected = _parse_playwright_listing(completed.stdout)
        absent = {
            (Path(target.file or "").name, target.locator)
            for target in group_targets
            if (Path(target.file or "").name, target.locator) not in collected
        }
        if absent:
            raise TraceabilityError(
                f"Playwright collector omitted exact titles for {config}/{project}: "
                f"{sorted(absent)}"
            )


def _parse_playwright_listing(output: str) -> set[tuple[str, str]]:
    collected: set[tuple[str, str]] = set()
    pattern = re.compile(r"\] › (?P<file>[^:]+):\d+:\d+ › (?P<title>.+)$")
    for line in output.splitlines():
        match = pattern.search(line.strip())
        if match:
            collected.add((Path(match.group("file")).name, match.group("title")))
    return collected


def _set_difference(label: str, expected: set[str], actual: set[str]) -> str:
    return (
        f"{label} differs; missing={sorted(expected - actual)}, "
        f"unexpected={sorted(actual - expected)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="validate paths and declarations without invoking test collectors",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="report unfinished evidence without closing the final gate",
    )
    arguments = parser.parse_args()
    document = PLAN.read_text(encoding="utf-8")
    validate_registry_shape(document)
    validate_target_definitions(ROOT)
    if not arguments.static_only:
        collect_registered_targets(ROOT)
    missing = missing_evidence()
    if missing:
        rendered = "\n".join(
            f"{test_id}: {'; '.join(reasons)}" for test_id, reasons in sorted(missing.items())
        )
        if not arguments.allow_missing:
            raise TraceabilityError("unfinished executable evidence:\n" + rendered)
        print("unfinished executable evidence:\n" + rendered)
    print(
        f"validated {len(ACCEPTANCE_EVIDENCE)} acceptance clauses, "
        f"{len(TEST_EVIDENCE)} stable test IDs"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TraceabilityError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from None
