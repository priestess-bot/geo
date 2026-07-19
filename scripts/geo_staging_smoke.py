#!/usr/bin/env python3
"""Explicitly authorized external staging smoke with redacted evidence."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from geo_api.oidc import (  # noqa: E402
    OidcTokenVerifier,
    OidcVerifierSettings,
    RemoteJwksProvider,
)
from geo_core.knowledge.processing import _fetch_public_url  # noqa: E402
from geo_core.model_gateway import (  # noqa: E402
    DeepSeekGateway,
    ModelCallBudget,
    ModelGatewayRequest,
    ModelPolicy,
)
from geo_core.model_gateway.deepseek import (  # noqa: E402
    default_deepseek_capability_registry,
)
from geo_core.placements.url_verifier import PublicUrlVerifier  # noqa: E402


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$")


class StagingSmokeConfigurationError(ValueError):
    def __init__(self, field: str, code: str = "CONFIG_REQUIRED") -> None:
        super().__init__(field)
        self.field = field
        self.code = code


class StagingSmokeCheckError(RuntimeError):
    def __init__(self, check: str) -> None:
        super().__init__(check)
        self.check = check


@dataclass(frozen=True)
class StagingSmokeConfig:
    run_id: str
    output_path: Path
    oidc_discovery_url: str
    oidc_issuer: str
    oidc_audience: str
    oidc_token_file: Path
    knowledge_url: str
    publication_url: str
    publication_expected_text: str
    deepseek_key_file: Path
    configured_model: str
    model_endpoint: str

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> "StagingSmokeConfig":
        run_id = values.get(
            "GEO_STAGING_SMOKE_RUN_ID",
            f"geo-staging-smoke-{datetime.now(UTC):%Y%m%d%H%M%S}",
        ).strip()
        if not _RUN_ID.fullmatch(run_id):
            raise StagingSmokeConfigurationError(
                "GEO_STAGING_SMOKE_RUN_ID", "CONFIG_INVALID"
            )
        discovery = _https_url(values, "GEO_STAGING_OIDC_DISCOVERY_URL")
        issuer = _https_url(values, "GEO_STAGING_OIDC_ISSUER")
        knowledge_url = _https_url(values, "GEO_STAGING_KNOWLEDGE_URL")
        publication_url = _https_url(values, "GEO_STAGING_PUBLICATION_URL")
        model_endpoint = _https_url(
            values,
            "GEO_STAGING_MODEL_ENDPOINT",
            default="https://api.deepseek.com/chat/completions",
        )
        token_file = _secret_file(values, "GEO_STAGING_OIDC_TOKEN_FILE")
        key_file = _secret_file(values, "GEO_DEEPSEEK_API_KEY_FILE")
        output = Path(
            values.get(
                "GEO_STAGING_SMOKE_OUTPUT",
                "artifacts/geo-staging-smoke/result.json",
            ).strip()
        )
        if not str(output):
            raise StagingSmokeConfigurationError(
                "GEO_STAGING_SMOKE_OUTPUT", "CONFIG_EMPTY"
            )
        return cls(
            run_id=run_id,
            output_path=output,
            oidc_discovery_url=discovery,
            oidc_issuer=issuer,
            oidc_audience=_required(values, "GEO_STAGING_OIDC_AUDIENCE"),
            oidc_token_file=token_file,
            knowledge_url=knowledge_url,
            publication_url=publication_url,
            publication_expected_text=_required(
                values, "GEO_STAGING_PUBLICATION_EXPECTED_TEXT"
            ),
            deepseek_key_file=key_file,
            configured_model=_required(
                values, "GEO_STAGING_MODEL", default="deepseek-chat"
            ),
            model_endpoint=model_endpoint,
        )


Check = Callable[[StagingSmokeConfig], dict[str, object]]


def run_staging_smoke(
    config: StagingSmokeConfig,
    *,
    oidc_check: Check | None = None,
    knowledge_check: Check | None = None,
    model_check: Check | None = None,
    publication_check: Check | None = None,
) -> dict[str, object]:
    checks = (
        ("oidc_jwks", oidc_check or _verify_oidc),
        ("knowledge_url", knowledge_check or _verify_knowledge_url),
        ("model", model_check or _verify_model),
        ("publication_url", publication_check or _verify_publication_url),
    )
    evidence: dict[str, object] = {}
    for name, check in checks:
        try:
            evidence[name] = check(config)
        except Exception as error:
            raise StagingSmokeCheckError(name) from error
    result: dict[str, object] = {
        "schema_version": "geo-staging-smoke-v1",
        "execution_mode": "staging_external",
        "run_id": config.run_id,
        "completed_at": datetime.now(UTC).isoformat(),
        "checks": evidence,
        "boundaries": {
            "external_calls_performed": True,
            "paid_model_call_budget": 1,
            "inline_acceptance": False,
            "production_worker_relay_topology_validated": False,
        },
    }
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_path.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _verify_oidc(config: StagingSmokeConfig) -> dict[str, object]:
    settings = OidcVerifierSettings(
        discovery_url=config.oidc_discovery_url,
        issuer=config.oidc_issuer,
        audience=config.oidc_audience,
        timeout_seconds=5,
    )
    provider = RemoteJwksProvider(settings)
    jwks = provider()
    token = _read_secret(config.oidc_token_file)
    OidcTokenVerifier(settings, jwks_provider=lambda: jwks).verify(token)
    return {
        "status": "passed",
        "discovery_url_sha256": _sha256(config.oidc_discovery_url),
        "issuer_sha256": _sha256(config.oidc_issuer),
        "signing_key_count": len(jwks["keys"]),
        "token_verified": True,
    }


def _verify_knowledge_url(config: StagingSmokeConfig) -> dict[str, object]:
    content, final_url, media_type = _fetch_public_url(config.knowledge_url)
    if not content:
        raise RuntimeError("Knowledge URL returned no content")
    return {
        "status": "passed",
        "requested_url_sha256": _sha256(config.knowledge_url),
        "final_url_sha256": _sha256(final_url),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_bytes": len(content),
        "media_type": media_type,
    }


def _verify_model(config: StagingSmokeConfig) -> dict[str, object]:
    gateway = DeepSeekGateway(
        api_key_file=config.deepseek_key_file,
        capability_registry=default_deepseek_capability_registry(),
        endpoint=config.model_endpoint,
        timeout_seconds=60,
    )
    prompt_hash = _sha256(f"geo-staging-smoke:{config.run_id}")
    result = gateway.generate(
        ModelGatewayRequest(
            messages=(
                {
                    "role": "system",
                    "content": "Return one JSON object and no prose.",
                },
                {
                    "role": "user",
                    "content": '{"status":"ok","purpose":"GEO staging smoke"}',
                },
            ),
            configured_model=config.configured_model,
            prompt_bundle_hash=prompt_hash,
            project_id=uuid5(NAMESPACE_URL, config.run_id),
            purpose="staging_external_smoke",
            temperature=0,
            max_output_tokens=64,
        ),
        policy=ModelPolicy(),
        budget=ModelCallBudget(maximum_calls=1),
    )
    if not result.output:
        raise RuntimeError("model response object is empty")
    return {
        "status": "passed",
        "configured_model": result.configured_model,
        "provider_reported_model": result.provider_reported_model,
        "response_sha256": result.response_hash,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
        "call_count": 1,
    }


def _verify_publication_url(config: StagingSmokeConfig) -> dict[str, object]:
    hostname = urlsplit(config.publication_url).hostname
    if hostname is None:
        raise RuntimeError("publication URL has no host")
    result = PublicUrlVerifier().verify(
        config.publication_url,
        expected_text_fragments=(config.publication_expected_text,),
        required_disclosures=(),
        expected_links=(),
        allowed_hosts=(hostname,),
    )
    if not result.success:
        raise RuntimeError("publication URL did not satisfy its content contract")
    evidence: dict[str, Any] = result.to_persistence_dict()
    evidence["status"] = "passed"
    return evidence


def _required(
    values: Mapping[str, str], field: str, *, default: str | None = None
) -> str:
    value = values.get(field, default or "").strip()
    if not value:
        raise StagingSmokeConfigurationError(field)
    return value


def _https_url(
    values: Mapping[str, str], field: str, *, default: str | None = None
) -> str:
    value = _required(values, field, default=default)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise StagingSmokeConfigurationError(field, "URL_INVALID") from error
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port == 0
    ):
        raise StagingSmokeConfigurationError(field, "URL_NOT_PUBLIC_HTTPS")
    return value


def _secret_file(values: Mapping[str, str], field: str) -> Path:
    path = Path(_required(values, field))
    try:
        metadata = path.stat()
    except OSError as error:
        raise StagingSmokeConfigurationError(field, "SECRET_FILE_UNAVAILABLE") from error
    mode = stat.S_IMODE(metadata.st_mode)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
        raise StagingSmokeConfigurationError(field, "SECRET_FILE_INVALID")
    if mode & 0o077 or not mode & stat.S_IRUSR:
        raise StagingSmokeConfigurationError(field, "SECRET_FILE_PERMISSIONS")
    return path


def _read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("secret file became empty after preflight")
    return value


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the authorized GEO staging smoke")
    parser.add_argument("--confirm-external-smoke", action="store_true")
    parser.add_argument("--confirm-paid-model-call", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if os.getenv("GEO_RUN_STAGING_SMOKE") != "1" or not args.confirm_external_smoke:
        print("REFUSED code=STAGING_EXTERNAL_SMOKE_NOT_AUTHORIZED field=GEO_RUN_STAGING_SMOKE")
        return 2
    if (
        os.getenv("GEO_CONFIRM_STAGING_PAID_MODEL_CALL") != "1"
        or not args.confirm_paid_model_call
    ):
        print(
            "REFUSED code=PAID_MODEL_CALL_NOT_AUTHORIZED "
            "field=GEO_CONFIRM_STAGING_PAID_MODEL_CALL"
        )
        return 2
    try:
        config = StagingSmokeConfig.from_environment(os.environ)
        result = run_staging_smoke(config)
    except StagingSmokeConfigurationError as error:
        print(f"ERROR code={error.code} field={error.field}")
        return 2
    except StagingSmokeCheckError as error:
        print(f"ERROR code=STAGING_SMOKE_CHECK_FAILED check={error.check}")
        return 1
    checks = result["checks"]
    print(
        "GEO staging smoke passed: execution_mode=staging_external "
        f"checks={len(checks) if isinstance(checks, Mapping) else 0} "
        f"result={config.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
