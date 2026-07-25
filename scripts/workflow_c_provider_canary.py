#!/usr/bin/env python3
"""Execute, collect or verify one governed Provider Sampling live canary."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
import json
import os
from pathlib import Path
import re
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.sampling.postgres_provider_canary import (
    PostgresProviderCanaryRepository,
)
from geo_core.sampling.provider_canary import (
    ProviderCanaryError,
    ProviderCanaryManifest,
    build_provider_canary_manifest,
    verify_provider_canary_manifest,
)
from geo_core.sampling.provider_release import (
    ProviderSamplingRelease,
    ProviderSamplingReleaseError,
    provider_sampling_release_from_value,
)


_IDEMPOTENCY_PREFIX = re.compile(r"^[A-Za-z0-9._:-]{1,180}$")
_MAX_RESPONSE_BYTES = 5_000_000
_TERMINAL_RUN_STATES = frozenset({"completed", "cancelled", "failed"})


class CanaryApi(Protocol):
    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Mapping[str, object]: ...


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    release = commands.add_parser("verify-release")
    release.add_argument("release", type=Path)

    execute = commands.add_parser("execute")
    execute.add_argument("release", type=Path)
    execute.add_argument("--base-url", required=True)
    execute.add_argument("--project-id", type=UUID, required=True)
    execute.add_argument("--suite-id", type=UUID, required=True)
    execute.add_argument("--requested-not-before", type=_aware_datetime, required=True)
    execute.add_argument("--idempotency-prefix", required=True)
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--poll-interval-seconds", type=float, default=5.0)
    execute.add_argument("--timeout-seconds", type=float, default=1800.0)
    execute.add_argument("--request-timeout-seconds", type=float, default=30.0)
    execute.add_argument("--authorization-env", default="GEO_CANARY_AUTH_TOKEN")
    execute.add_argument("--actor-id-env", default="GEO_CANARY_ACTOR_ID")
    execute.add_argument("--tenant-id-env", default="GEO_CANARY_TENANT_ID")
    execute.add_argument("--database-url-env", default="GEO_DATABASE_URL")
    execute.add_argument("--database-url-file-env", default="GEO_DATABASE_URL_FILE")

    collect = commands.add_parser("collect")
    collect.add_argument("release", type=Path)
    collect.add_argument("--project-id", type=UUID, required=True)
    collect.add_argument("--run-id", type=UUID, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--database-url-env", default="GEO_DATABASE_URL")
    collect.add_argument("--database-url-file-env", default="GEO_DATABASE_URL_FILE")

    verify = commands.add_parser("verify")
    verify.add_argument("release", type=Path)
    verify.add_argument("manifest", type=Path)

    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "verify-release":
            item = _load_release(arguments.release)
            _print(
                {
                    "status": "verified",
                    "release_id": item.release_id,
                    "release_hash": item.release_hash,
                    "record_hash": item.record_hash,
                    "state": item.state.value,
                }
            )
            return 0
        if arguments.command == "verify":
            manifest_hash = verify_provider_canary_manifest(
                _load_object(arguments.manifest, label="Provider canary manifest"),
                _load_release(arguments.release),
            )
            _print({"status": "verified", "manifest_hash": manifest_hash})
            return 0
        if arguments.command == "execute":
            item = _load_release(arguments.release)
            api = HttpCanaryApi.from_environment(
                base_url=arguments.base_url,
                request_timeout_seconds=arguments.request_timeout_seconds,
                authorization_env=arguments.authorization_env,
                actor_id_env=arguments.actor_id_env,
                tenant_id_env=arguments.tenant_id_env,
            )
            run_id = execute_provider_canary(
                api,
                release=item,
                project_id=arguments.project_id,
                suite_id=arguments.suite_id,
                requested_not_before=arguments.requested_not_before,
                idempotency_prefix=arguments.idempotency_prefix,
                poll_interval_seconds=arguments.poll_interval_seconds,
                timeout_seconds=arguments.timeout_seconds,
            )
            manifest = _collect(
                item,
                project_id=arguments.project_id,
                run_id=run_id,
                database_url=_database_url(
                    direct_env=arguments.database_url_env,
                    file_env=arguments.database_url_file_env,
                ),
            )
            _write_json(arguments.output, manifest.value())
            _print_collected(item, manifest, arguments.output, executed=True)
            return 0
        item = _load_release(arguments.release)
        manifest = _collect(
            item,
            project_id=arguments.project_id,
            run_id=arguments.run_id,
            database_url=_database_url(
                direct_env=arguments.database_url_env,
                file_env=arguments.database_url_file_env,
            ),
        )
        _write_json(arguments.output, manifest.value())
        _print_collected(item, manifest, arguments.output, executed=False)
        return 0
    except (ProviderCanaryError, ProviderSamplingReleaseError, ValueError) as error:
        raise SystemExit(str(error)) from error


class HttpCanaryApi:
    """Minimal JSON client that never accepts credentials on the command line."""

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str],
        request_timeout_seconds: float,
    ) -> None:
        self.base_url = _base_url(base_url)
        self.headers = dict(headers)
        if request_timeout_seconds <= 0 or request_timeout_seconds > 300:
            raise ProviderCanaryError("request timeout must be within (0, 300] seconds")
        self.request_timeout_seconds = request_timeout_seconds

    @classmethod
    def from_environment(
        cls,
        *,
        base_url: str,
        request_timeout_seconds: float,
        authorization_env: str,
        actor_id_env: str,
        tenant_id_env: str,
    ) -> "HttpCanaryApi":
        token = os.getenv(authorization_env, "").strip()
        actor_id = os.getenv(actor_id_env, "").strip()
        tenant_id = os.getenv(tenant_id_env, "").strip()
        if token and (actor_id or tenant_id):
            raise ProviderCanaryError(
                "configure either canary bearer authentication or development identity"
            )
        if token:
            headers = {"Authorization": f"Bearer {token}"}
        elif actor_id and tenant_id:
            headers = {
                "X-GEO-Actor-ID": actor_id,
                "X-GEO-Tenant-ID": tenant_id,
            }
        else:
            raise ProviderCanaryError(
                f"configure {authorization_env}, or both {actor_id_env} and {tenant_id_env}"
            )
        return cls(
            base_url=base_url,
            headers=headers,
            request_timeout_seconds=request_timeout_seconds,
        )

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, object] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Mapping[str, object]:
        headers = {**self.headers, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(
            f"{self.base_url}{path}",
            data=(
                json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode()
                if body is not None
                else None
            ),
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.request_timeout_seconds) as response:  # nosec B310
                content = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            error.close()
            raise ProviderCanaryError(
                f"canary API {method} {path} returned HTTP {error.code}"
            ) from error
        except (OSError, URLError) as error:
            raise ProviderCanaryError(
                f"canary API {method} {path} could not be reached"
            ) from error
        if len(content) > _MAX_RESPONSE_BYTES:
            raise ProviderCanaryError("canary API response exceeds the size limit")
        try:
            value = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProviderCanaryError("canary API response is not JSON") from error
        if not isinstance(value, Mapping) or not all(
            isinstance(key, str) for key in value
        ):
            raise ProviderCanaryError("canary API response root must be an object")
        return value


def execute_provider_canary(
    api: CanaryApi,
    *,
    release: ProviderSamplingRelease,
    project_id: UUID,
    suite_id: UUID,
    requested_not_before: datetime,
    idempotency_prefix: str,
    poll_interval_seconds: float,
    timeout_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> UUID:
    """Start, idempotently replay and wait for one exact Provider canary Run."""

    _require_aware(requested_not_before, "requested-not-before")
    if _IDEMPOTENCY_PREFIX.fullmatch(idempotency_prefix) is None:
        raise ProviderCanaryError("canary idempotency prefix has invalid characters or length")
    if len(idempotency_prefix) + len(":enqueue") > 200:
        raise ProviderCanaryError("canary idempotency keys exceed 200 characters")
    if poll_interval_seconds <= 0 or timeout_seconds <= 0:
        raise ProviderCanaryError("canary poll interval and timeout must be positive")

    prefix = f"/v1/projects/{project_id}/sampling"
    suite = api.request("GET", f"{prefix}/suites/{suite_id}")
    _validate_suite(suite, release=release, suite_id=suite_id)
    start_body = {
        "purpose": "provider_live_canary",
        "requested_not_before": requested_not_before.isoformat(),
    }
    run_path = f"{prefix}/suites/{suite_id}/runs"
    started = api.request(
        "POST",
        run_path,
        start_body,
        idempotency_key=f"{idempotency_prefix}:start",
    )
    replayed_start = api.request(
        "POST",
        run_path,
        start_body,
        idempotency_key=f"{idempotency_prefix}:start",
    )
    run = _object(started, "run")
    replayed_run = _object(replayed_start, "run")
    _same_immutable_run(run, replayed_run)
    run_id = _uuid(run, "id")
    if _uuid(run, "suite_id") != suite_id or _string(run, "purpose") != "provider_live_canary":
        raise ProviderCanaryError("canary API started a different Sampling Run")
    if _string(run, "suite_hash") != _string(suite, "suite_hash"):
        raise ProviderCanaryError("canary Run does not preserve the Suite hash")

    enqueue_path = f"{prefix}/runs/{run_id}/enqueue-ready"
    enqueue_body = {
        "requested_not_before": requested_not_before.isoformat(),
        "max_tasks": _integer(suite, "planned_task_count"),
    }
    enqueued = api.request(
        "POST",
        enqueue_path,
        enqueue_body,
        idempotency_key=f"{idempotency_prefix}:enqueue",
    )
    enqueue_replay = api.request(
        "POST",
        enqueue_path,
        enqueue_body,
        idempotency_key=f"{idempotency_prefix}:enqueue",
    )
    _validate_enqueue_replay(enqueued, enqueue_replay, run_id=run_id)

    deadline = monotonic() + timeout_seconds
    detail_path = f"{prefix}/runs/{run_id}"
    while True:
        detail = api.request("GET", detail_path)
        current = _object(detail, "run")
        _same_immutable_run(run, current)
        state = _string(current, "status")
        if state in _TERMINAL_RUN_STATES:
            if state != "completed":
                raise ProviderCanaryError(f"Provider canary Run ended as {state}")
            return run_id
        if monotonic() >= deadline:
            raise ProviderCanaryError("Provider canary Run did not finish before timeout")
        sleep(poll_interval_seconds)


def _validate_suite(
    value: Mapping[str, object],
    *,
    release: ProviderSamplingRelease,
    suite_id: UUID,
) -> None:
    if _uuid(value, "id") != suite_id:
        raise ProviderCanaryError("canary Suite response has the wrong identity")
    questions = _sequence(value, "questions")
    repetitions = _integer(value, "repetitions")
    if not questions or repetitions != 10:
        raise ProviderCanaryError("Provider canary Suite requires ten repeats per question")
    if _integer(value, "planned_task_count") != len(questions) * repetitions:
        raise ProviderCanaryError("Provider canary Suite denominator is inconsistent")
    expected = {
        "adapter_release_id": release.adapter_release_id,
        "adapter_release_hash": release.adapter_release_hash,
        "model_release_id": release.model_release_id,
        "model_release_hash": release.model_release_hash,
    }
    if any(_string(value, key) != expected_value for key, expected_value in expected.items()):
        raise ProviderCanaryError("Provider canary Suite release lineage differs")
    source = _object(value, "source_stratum")
    source_expected = {
        "platform": release.platform,
        "surface": release.surface,
        "capture_method": release.capture_method.value,
        "configured_model": release.configured_model,
        "adapter_release": release.adapter_release_id,
        "search_mode": release.search_mode,
    }
    if any(
        _string(source, key) != expected_value
        for key, expected_value in source_expected.items()
    ):
        raise ProviderCanaryError("Provider canary Suite source identity differs")
    if not release.accepts_reported_model(_string(source, "reported_model")):
        raise ProviderCanaryError("Provider canary Suite reported model is not allowed")


def _same_immutable_run(
    first: Mapping[str, object], second: Mapping[str, object]
) -> None:
    immutable = (
        "id",
        "project_id",
        "suite_id",
        "suite_hash",
        "admission_policy_id",
        "admission_policy_hash",
        "admission_grant_hash",
        "purpose",
        "authorization_reference",
        "authorization_valid_until",
        "admission_policy_version",
        "reserved_task_count",
        "planned_task_keys",
        "admitted_not_before",
        "created_at",
    )
    if any(first.get(key) != second.get(key) for key in immutable):
        raise ProviderCanaryError("canary Run changed across idempotent replay or polling")


def _validate_enqueue_replay(
    first: Mapping[str, object],
    replay: Mapping[str, object],
    *,
    run_id: UUID,
) -> None:
    first_ids = _sequence(first, "attempt_ids")
    replay_ids = _sequence(replay, "attempt_ids")
    if (
        _uuid(first, "run_id") != run_id
        or _uuid(replay, "run_id") != run_id
        or not first_ids
        or first_ids != replay_ids
        or _integer(first, "enqueued_count") != len(first_ids)
        or _integer(replay, "replayed_count") != len(first_ids)
        or replay.get("replayed") is not True
    ):
        raise ProviderCanaryError("canary bulk enqueue did not replay exactly")


def _collect(
    release: ProviderSamplingRelease,
    *,
    project_id: UUID,
    run_id: UUID,
    database_url: str,
) -> ProviderCanaryManifest:
    repository = PostgresProviderCanaryRepository(
        connect=lambda: psycopg.connect(database_url, row_factory=dict_row)
    )
    first = repository.read(project_id=project_id, run_id=run_id)
    second = repository.read(project_id=project_id, run_id=run_id)
    if first != second:
        raise ProviderCanaryError("Provider canary changed across replayed reads")
    return build_provider_canary_manifest(
        release,
        first,
        generated_at=first.completed_at,
    )


def _print_collected(
    release: ProviderSamplingRelease,
    manifest: ProviderCanaryManifest,
    output: Path,
    *,
    executed: bool,
) -> None:
    _print(
        {
            "status": "executed_and_collected" if executed else "collected",
            "provider": release.gateway_provider,
            "run_id": str(manifest.run_id),
            "manifest_hash": manifest.manifest_hash,
            "valid_task_count": manifest.valid_task_count,
            "planned_task_count": manifest.planned_task_count,
            "output": str(output),
        }
    )


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("datetime must use ISO 8601") from error
    try:
        _require_aware(parsed, "datetime")
    except ProviderCanaryError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return parsed


def _base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProviderCanaryError("canary base URL is invalid or contains credentials")
    if parsed.scheme == "http" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ProviderCanaryError("non-local canary API requires HTTPS")
    return value.strip().rstrip("/")


def _object(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, Mapping) or not all(
        isinstance(child_key, str) for child_key in item
    ):
        raise ProviderCanaryError(f"canary API field {key} must be an object")
    return item


def _sequence(value: Mapping[str, object], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ProviderCanaryError(f"canary API field {key} must be an array")
    return item


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ProviderCanaryError(f"canary API field {key} must be a non-empty string")
    return item


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ProviderCanaryError(f"canary API field {key} must be a non-negative integer")
    return item


def _uuid(value: Mapping[str, object], key: str) -> UUID:
    try:
        item = UUID(_string(value, key))
    except ValueError as error:
        raise ProviderCanaryError(f"canary API field {key} must be a UUID") from error
    if item.int == 0:
        raise ProviderCanaryError(f"canary API field {key} cannot be a zero UUID")
    return item


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderCanaryError(f"{label} must include a timezone")


def _load_release(path: Path) -> ProviderSamplingRelease:
    return provider_sampling_release_from_value(
        _load_object(path, label="Provider Sampling release")
    )


def _load_object(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProviderCanaryError(f"{label} cannot be read as JSON") from error
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ProviderCanaryError(f"{label} root must be an object")
    return value


def _database_url(*, direct_env: str, file_env: str) -> str:
    direct = os.getenv(direct_env, "").strip()
    file_name = os.getenv(file_env, "").strip()
    if bool(direct) == bool(file_name):
        raise ProviderCanaryError(
            f"configure exactly one of {direct_env} or {file_env}"
        )
    if direct:
        return direct
    try:
        value = Path(file_name).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise ProviderCanaryError(f"{file_env} cannot be read") from error
    if not value:
        raise ProviderCanaryError(f"{file_env} is empty")
    return value


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _print(value: Mapping[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
