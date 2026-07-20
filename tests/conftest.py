from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

import pytest
from _pytest.reports import CollectReport, TestReport
from _pytest.terminal import TerminalReporter


@dataclass
class _RunSummary:
    collected: int = 0
    passed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)


class _CiTruthPlugin:
    def __init__(self, config: pytest.Config) -> None:
        self._config = config
        self._summary = _RunSummary()

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self._summary.collected = len(session.items)

    def pytest_collectreport(self, report: CollectReport) -> None:
        if report.failed:
            self._summary.failed.add(report.nodeid)
        elif report.skipped:
            self._summary.skipped.add(report.nodeid)

    def pytest_runtest_logreport(self, report: TestReport) -> None:
        if report.failed:
            self._summary.failed.add(report.nodeid)
            self._summary.passed.discard(report.nodeid)
            return
        if report.skipped:
            self._summary.skipped.add(report.nodeid)
            self._summary.passed.discard(report.nodeid)
            return
        if report.when == "call" and report.passed:
            self._summary.passed.add(report.nodeid)

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        del exitstatus
        if self._config.getoption("fail_on_skipped") and self._summary.skipped:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(
        self,
        terminalreporter: TerminalReporter,
        exitstatus: int,
        config: pytest.Config,
    ) -> None:
        del exitstatus, config
        label = str(self._config.getoption("ci_summary_label") or "pytest")
        line = (
            f"CI test summary [{label}]: collected={self._summary.collected} "
            f"passed={len(self._summary.passed)} failed={len(self._summary.failed)} "
            f"skipped={len(self._summary.skipped)}"
        )
        terminalreporter.write_sep("=", line)
        summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as summary_file:
                summary_file.write(f"### {label}\n\n`{line}`\n\n")


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("geo-ci-truth")
    group.addoption(
        "--fail-on-skipped",
        action="store_true",
        help="Fail the pytest run when any selected test is skipped.",
    )
    group.addoption(
        "--ci-summary-label",
        action="store",
        default=None,
        help="Print collected/passed/failed/skipped counts under this label.",
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("fail_on_skipped") or config.getoption("ci_summary_label"):
        config.pluginmanager.register(_CiTruthPlugin(config), "geo-ci-truth-plugin")
