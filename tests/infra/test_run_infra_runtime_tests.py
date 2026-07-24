from __future__ import annotations

from subprocess import CompletedProcess

from scripts import run_infra_runtime_tests


def test_runtime_gate_fails_when_disposable_compose_cleanup_fails(
    monkeypatch, capsys
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command, **_kwargs):
        calls.append(tuple(command))
        if "down" in command:
            return CompletedProcess(command, 1, stdout="cleanup stdout", stderr="cleanup stderr")
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(run_infra_runtime_tests, "_run", fake_run)
    monkeypatch.setattr(run_infra_runtime_tests, "_unused_port", lambda: 55499)

    assert run_infra_runtime_tests.main() == 2
    output = capsys.readouterr().out
    assert "failed to clean disposable Docker resources" in output
    assert "cleanup stdout" in output
    assert "cleanup stderr" in output
    assert "down" in calls[-1]


def test_runtime_gate_preserves_test_failure_when_cleanup_succeeds(monkeypatch) -> None:
    def fake_run(command, **_kwargs):
        if command[:3] == ["uv", "run", "pytest"]:
            return CompletedProcess(command, 1, stdout="", stderr="")
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(run_infra_runtime_tests, "_run", fake_run)
    monkeypatch.setattr(run_infra_runtime_tests, "_unused_port", lambda: 55499)

    assert run_infra_runtime_tests.main() == 1
