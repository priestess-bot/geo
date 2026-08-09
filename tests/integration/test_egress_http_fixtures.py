from __future__ import annotations

import base64
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from time import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
import httpx
import pytest

from geo_api.oidc import OidcTokenVerifier, OidcVerifierSettings
from geo_core.knowledge import processing
from geo_core.model_gateway import ModelCallBudget, ModelGatewayRequest, ModelPolicy
from geo_core.model_gateway.deepseek import (
    DeepSeekGateway,
    default_deepseek_capability_registry,
)
from geo_core.placements.url_verifier import FetchedResponse, PublicUrlVerifier


pytestmark = pytest.mark.integration


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _sign_token(
    private_key: rsa.RSAPrivateKey,
    *,
    issuer: str,
    tenant_id: str,
) -> str:
    header = _encode(json.dumps({"alg": "RS256", "kid": "fixture-key"}).encode())
    claims = _encode(
        json.dumps(
            {
                "iss": issuer,
                "sub": "fixture-operator",
                "aud": "geo-staging",
                "tenant_id": tenant_id,
                "exp": int(time()) + 300,
            }
        ).encode()
    )
    signed = f"{header}.{claims}".encode("ascii")
    signature = private_key.sign(signed, padding.PKCS1v15(), SHA256())
    return f"{header}.{claims}.{_encode(signature)}"


class _FixtureHandler(BaseHTTPRequestHandler):
    calls: list[tuple[str, str | None]] = []
    issuer = ""
    jwks: dict[str, object] = {}

    def do_GET(self) -> None:  # noqa: N802
        type(self).calls.append((self.path, self.headers.get("Authorization")))
        if self.path == "/.well-known/openid-configuration":
            self._json({"issuer": self.issuer, "jwks_uri": f"{self.issuer}/jwks"})
            return
        if self.path == "/jwks":
            self._json(self.jwks)
            return
        if self.path == "/knowledge":
            self._body(
                b"<html><body>Public product knowledge fixture.</body></html>",
                content_type="text/html",
            )
            return
        if self.path == "/publication":
            self._body(
                b"<html><body>Approved public review fixture.</body></html>",
                content_type="text/html",
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        type(self).calls.append((self.path, self.headers.get("Authorization")))
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        assert request["response_format"] == {"type": "json_object"}
        if self.path != "/model":
            self.send_error(404)
            return
        self._json(
            {
                # Keep body and header identities equal so this HTTP fixture
                # remains deterministic across Python HTTPMessage casing.
                "id": "fixture-request",
                "model": "fixture-model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"status":"ok"}'},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
            },
            extra_headers={"x-request-id": "fixture-request"},
        )

    def _json(
        self,
        payload: dict[str, object],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._body(
            json.dumps(payload).encode(),
            content_type="application/json",
            extra_headers=extra_headers,
        )

    def _body(
        self,
        body: bytes,
        *,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@contextmanager
def _http_fixture() -> Iterator[tuple[str, ThreadingHTTPServer]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    base_url = f"http://127.0.0.1:{server.server_port}"
    _FixtureHandler.calls = []
    _FixtureHandler.issuer = base_url
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield base_url, server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _LocalPublicationFetcher:
    def __init__(self, port: int) -> None:
        self._port = port

    def fetch(
        self,
        url: str,
        *,
        pinned_ip: str,
        timeout_seconds: float,
        maximum_bytes: int,
    ) -> FetchedResponse:
        del pinned_ip
        parsed = urlsplit(url)
        connection = HTTPConnection("127.0.0.1", self._port, timeout=timeout_seconds)
        try:
            connection.request("GET", parsed.path)
            response = connection.getresponse()
            body = response.read(maximum_bytes + 1)
            return FetchedResponse(
                response.status,
                dict(response.getheaders()),
                body,
            )
        finally:
            connection.close()


def test_f001_int_01_local_http_fixtures_cover_oidc_knowledge_model_and_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    _FixtureHandler.jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "kid": "fixture-key",
                "n": _encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
                "e": _encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
            }
        ]
    }
    with _http_fixture() as (base_url, server):
        settings = OidcVerifierSettings(
            discovery_url=f"{base_url}/.well-known/openid-configuration",
            issuer=base_url,
            audience="geo-staging",
        )
        identity = OidcTokenVerifier(settings).verify(
            _sign_token(private_key, issuer=base_url, tenant_id=str(uuid4()))
        )
        assert identity.subject == "fixture-operator"

        knowledge_url = f"http://knowledge.fixture:{server.server_port}/knowledge"

        def local_knowledge_target(url: str) -> processing._PublicUrlTarget:
            parsed = httpx.URL(url)
            return processing._PublicUrlTarget(parsed, parsed.host, ("127.0.0.1",))

        with monkeypatch.context() as knowledge_patch:
            knowledge_patch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
            knowledge_patch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
            knowledge_patch.setattr(
                processing,
                "_require_public_url",
                local_knowledge_target,
            )
            content, final_url, media_type = processing._fetch_public_url(knowledge_url)
        assert b"Public product knowledge fixture" in content
        assert final_url == knowledge_url
        assert media_type == "text/html"

        key_file = tmp_path / "model-key"
        key_file.write_text("fixture-model-secret", encoding="utf-8")
        gateway = DeepSeekGateway(
            api_key_file=key_file,
            capability_registry=default_deepseek_capability_registry(),
            endpoint=f"{base_url}/model",
        )
        model = gateway.generate(
            ModelGatewayRequest(
                messages=({"role": "user", "content": "Return JSON."},),
                configured_model="fixture-model",
                prompt_bundle_hash=hashlib.sha256(b"fixture").hexdigest(),
                project_id=uuid4(),
                purpose="f001_integration_fixture",
                max_output_tokens=32,
            ),
            policy=ModelPolicy(),
            budget=ModelCallBudget(1),
        )
        assert model.output == {"status": "ok"}
        assert model.provider_request_id == "fixture-request"
        assert len(model.response_hash) == 64

        publication = PublicUrlVerifier(
            resolver=lambda _hostname, _port: ("93.184.216.34",),
            fetcher=_LocalPublicationFetcher(server.server_port),
        ).verify(
            "https://publication.fixture/publication",
            expected_text_fragments=("Approved public review fixture",),
            required_disclosures=(),
            expected_links=(),
            allowed_hosts=("publication.fixture",),
        )
        assert publication.success is True

    paths = [path for path, _authorization in _FixtureHandler.calls]
    assert paths == [
        "/.well-known/openid-configuration",
        "/jwks",
        "/knowledge",
        "/model",
        "/publication",
    ]
    model_authorization = next(
        authorization
        for path, authorization in _FixtureHandler.calls
        if path == "/model"
    )
    assert model_authorization == "Bearer fixture-model-secret"
