#!/usr/bin/env python3
"""Run one real SerpAPI Provider canary when its Secret Store inputs exist.

This command is deliberately fail-closed. It never accepts ``SERPAPI_API_KEY``
or prints a provider credential. Without the frozen project/Secret reference,
worker identity, database and keyring inputs it exits with code 77 (skipped),
so an absent external dependency cannot be reported as a successful canary.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from uuid import UUID

from geo_core.search_aggregation import build_search_provider
from geo_core.search_aggregation.domain import AiOverviewQuery, SearchAggregationError
from geo_core.secrets.models import SecretVersionHandle
from geo_core.model_gateway import build_secret_store_credential_resolver


SKIP_EXIT_CODE = 77
_REQUIRED_ENV = (
    "GEO_DATABASE_URL",
    "GEO_PROJECT_ID",
    "GEO_WORKER_ACTOR_ID",
    "GEO_SECRET_STORE_MASTER_KEYRING_FILE",
    "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE",
    "SERPAPI_SECRET_REFERENCE_ID",
    "SERPAPI_SECRET_VERSION",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="One approved measurement query.")
    parser.add_argument("--location", default=None)
    parser.add_argument("--gl", default="au")
    parser.add_argument("--hl", default="en-AU")
    parser.add_argument("--google-domain", default="google.com.au")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    return parser


def _missing_environment() -> tuple[str, ...]:
    """Return missing non-secret references; plaintext key env vars are ignored."""
    return tuple(name for name in _REQUIRED_ENV if not os.getenv(name, "").strip())


def _uuid_env(name: str) -> UUID:
    value = os.environ[name].strip()
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a UUID") from exc
    if parsed.int == 0:
        raise ValueError(f"{name} must not be nil")
    return parsed


def _positive_int_env(name: str) -> int:
    try:
        value = int(os.environ[name])
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _response_hash(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    project_id = _uuid_env("GEO_PROJECT_ID")
    secret_handle = SecretVersionHandle(
        project_id=project_id,
        reference_id=_uuid_env("SERPAPI_SECRET_REFERENCE_ID"),
        purpose="search.serpapi",
        version=_positive_int_env("SERPAPI_SECRET_VERSION"),
    )
    resolver = build_secret_store_credential_resolver(
        database_url=os.environ["GEO_DATABASE_URL"].strip(),
        master_keyring_path=os.environ["GEO_SECRET_STORE_MASTER_KEYRING_FILE"],
        request_hash_key_path=os.environ["GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE"],
        worker_actor_id=_uuid_env("GEO_WORKER_ACTOR_ID"),
    )
    provider = build_search_provider(
        "serpapi",
        secret_handle=secret_handle,
        credential_resolver=resolver,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
    )
    result = await provider.fetch_ai_overview(
        AiOverviewQuery(
            text=args.query,
            locale=args.hl,
            region=args.gl,
            location=args.location,
            google_domain=args.google_domain,
        )
    )
    return {
        "status": "passed",
        "provider": "serpapi",
        "surface": "google_search",
        "query": result.query,
        "captured_at": datetime.now(UTC).isoformat(),
        "block_count": len(result.blocks),
        "reference_count": len(result.references),
        "response_hash": _response_hash(result.raw_response),
        "secret_reference_id": str(secret_handle.reference_id),
        "secret_version": secret_handle.version,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    missing = _missing_environment()
    if missing:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "SerpAPI Secret Store canary inputs are not configured",
                    "missing": list(missing),
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return SKIP_EXIT_CODE
    try:
        result = asyncio.run(_run(args))
    except SearchAggregationError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "provider": "serpapi",
                    "error_code": exc.code.value,
                    "retryable": exc.retryable,
                    "status_code": exc.status_code,
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "provider": "serpapi",
                    "error_code": "configuration",
                    "detail": str(exc),
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
