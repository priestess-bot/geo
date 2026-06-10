from __future__ import annotations

import argparse
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts import run_browser_fidelity_scheduler as scheduler


class BrowserFidelitySchedulerCliTest(unittest.TestCase):
    def _args(self, *, execute: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            run_date="2026-06-11",
            cadence="weekly",
            prompt_count=2,
            city_count=1,
            sample_size=1,
            selection_seed="scheduler-test",
            persist_plan=False,
            execute=execute,
        )

    def test_scheduler_plan_only_does_not_execute_worker(self) -> None:
        plan_payload = {
            "recommended_worker_args": [
                "--mode",
                "api",
                "--prompt-ids",
                "p1,p2",
                "--prompt-limit",
                "2",
                "--cities",
                "Sydney",
            ]
        }
        calls: list[list[str]] = []

        def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(plan_payload), stderr="")

        with patch.object(scheduler, "_run_command", side_effect=fake_run):
            payload, exit_code = scheduler.run_scheduler(self._args())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "planned")
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(payload["worker_command"])
        self.assertIsNone(payload["worker_returncode"])

    def test_scheduler_execute_runs_recommended_worker_args(self) -> None:
        plan_payload = {
            "recommended_worker_args": [
                "--mode",
                "api",
                "--prompt-ids",
                "p1,p2",
                "--prompt-limit",
                "2",
                "--cities",
                "Sydney",
            ]
        }
        worker_payload = {"mode": "api", "record_count": 6}
        calls: list[list[str]] = []

        def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if len(calls) == 1:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(plan_payload), stderr="")
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(worker_payload), stderr="")

        with patch.object(scheduler, "_run_command", side_effect=fake_run):
            payload, exit_code = scheduler.run_scheduler(self._args(execute=True))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "executed")
        self.assertEqual(len(calls), 2)
        self.assertIn("--prompt-ids", calls[1])
        self.assertEqual(payload["worker_stdout"], worker_payload)

    def test_scheduler_requires_recommended_worker_args(self) -> None:
        def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({}), stderr="")

        with patch.object(scheduler, "_run_command", side_effect=fake_run):
            payload, exit_code = scheduler.run_scheduler(self._args(execute=True))

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "plan_missing_worker_args")
        self.assertIsNone(payload["worker_command"])


if __name__ == "__main__":
    unittest.main()
