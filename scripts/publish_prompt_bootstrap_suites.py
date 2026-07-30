#!/usr/bin/env python3
"""Run, verify, and publish every bootstrapped Prompt suite through stable APIs."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID


TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "dead_lettered", "cancelled"})


class PromptSuiteError(RuntimeError):
    """Actionable failure from one Prompt suite or publication command."""


class Api:
    def __init__(self, base_url: str, actor_id: UUID, tenant_id: UUID) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "X-GEO-Actor-ID": str(actor_id),
            "X-GEO-Tenant-ID": str(tenant_id),
        }

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, object] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = dict(self.headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"null")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise PromptSuiteError(
                f"{method} {path} failed ({error.code}): {detail}"
            ) from error


def child_key(project_id: UUID, purpose: str, action: str) -> str:
    digest = hashlib.sha256(f"{project_id}:{purpose}:{action}".encode()).hexdigest()[:24]
    return f"advinsys-prompt-bootstrap:{digest}"


def matching_run(items: list[dict[str, Any]], job_id: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("job_id") == job_id), None)


def require_passing_terminal(run: dict[str, Any], *, purpose: str) -> None:
    status = run.get("status")
    if status not in TERMINAL_JOB_STATES:
        raise PromptSuiteError(f"{purpose} Prompt suite is not terminal: {status}")
    if status != "succeeded":
        raise PromptSuiteError(
            f"{purpose} Prompt suite {status}: {run.get('error_code') or 'no error code'}"
        )
    if run.get("passed") is not True:
        raise PromptSuiteError(
            f"{purpose} Prompt suite did not pass; score={run.get('score')!r}"
        )


def wait_for_run(
    api: Api,
    *,
    project_id: UUID,
    program_id: str,
    job_id: str,
    purpose: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        page = api.request(
            "GET", f"/v1/projects/{project_id}/prompt-programs/{program_id}/test-runs?limit=20"
        )
        run = matching_run(page["items"], job_id)
        if run is not None and run.get("status") in TERMINAL_JOB_STATES:
            require_passing_terminal(run, purpose=purpose)
            return run
        time.sleep(2)
    raise PromptSuiteError(
        f"{purpose} Prompt suite did not finish within {timeout_seconds} seconds; "
        f"job_id={job_id}"
    )


def execute(
    api: Api,
    *,
    project_id: UUID,
    runtime_selection_id: UUID,
    timeout_seconds: int,
    state_file: Path | None,
) -> dict[str, object]:
    flow_page = api.request("GET", f"/v1/projects/{project_id}/prompt-flows")
    flows = sorted(flow_page["items"], key=lambda item: item["purpose"])
    if len(flows) != 14 or any(item.get("program") is None for item in flows):
        raise PromptSuiteError("all 14 bootstrapped Prompt Programs must exist before publication")
    results: list[dict[str, object]] = []
    for flow in flows:
        purpose = str(flow["purpose"])
        program_id = str(flow["program"]["id"])
        draft = api.request(
            "GET", f"/v1/projects/{project_id}/prompt-programs/{program_id}/draft"
        )
        if (
            flow.get("current_release_id") == draft.get("base_release_id")
            and draft.get("candidate_release_id") is None
            and flow.get("current_release_id") is not None
        ):
            item = {
                "purpose": purpose,
                "program_id": program_id,
                "status": "already_published",
                "release_id": flow["current_release_id"],
            }
            results.append(item)
            _write_state(state_file, project_id, runtime_selection_id, results)
            continue
        suite = api.request(
            "POST",
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/suite-runs",
            {
                "runtime_selection_id": str(runtime_selection_id),
                "expected_revision": int(draft["revision"]),
            },
            idempotency_key=child_key(
                project_id, purpose, f"suite-r{int(draft['revision'])}"
            ),
        )
        job_id = str(suite["job"]["job_id"])
        run = wait_for_run(
            api,
            project_id=project_id,
            program_id=program_id,
            job_id=job_id,
            purpose=purpose,
            timeout_seconds=timeout_seconds,
        )
        published = api.request(
            "POST",
            f"/v1/projects/{project_id}/prompt-programs/{program_id}/publish",
            {"expected_revision": int(suite["draft"]["revision"])},
            idempotency_key=child_key(
                project_id, purpose, f"publish-r{int(suite['draft']['revision'])}"
            ),
        )
        item = {
            "purpose": purpose,
            "program_id": program_id,
            "status": "published",
            "job_id": job_id,
            "score": run["score"],
            "release_id": published["release"]["id"],
            "release_hash": published["release"]["release_hash"],
            "binding_version": published["binding"]["binding_version"],
        }
        results.append(item)
        _write_state(state_file, project_id, runtime_selection_id, results)
    if len(results) != 14:
        raise PromptSuiteError("Prompt publication result count is incomplete")
    return {
        "schema_version": 1,
        "status": "completed",
        "completed_at": datetime.now(UTC).isoformat(),
        "project_id": str(project_id),
        "runtime_selection_id": str(runtime_selection_id),
        "item_count": len(results),
        "items": results,
    }


def _write_state(
    path: Path | None,
    project_id: UUID,
    runtime_selection_id: UUID,
    results: list[dict[str, object]],
) -> None:
    if path is None:
        return
    payload = {
        "schema_version": 1,
        "status": "running",
        "updated_at": datetime.now(UTC).isoformat(),
        "project_id": str(project_id),
        "runtime_selection_id": str(runtime_selection_id),
        "items": results,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:18000")
    parser.add_argument("--project-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True, type=UUID)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--runtime-selection-id", required=True, type=UUID)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 30 <= args.timeout_seconds <= 3600:
        parser.error("--timeout-seconds must be between 30 and 3600")
    result = execute(
        Api(args.api_url, args.actor_id, args.tenant_id),
        project_id=args.project_id,
        runtime_selection_id=args.runtime_selection_id,
        timeout_seconds=args.timeout_seconds,
        state_file=args.state_file,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
