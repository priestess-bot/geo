"""Small RS256 OIDC verifier used by the internal API surface."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
import json
from threading import Lock
from time import monotonic, time
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
import httpx

from geo_core.access.models import ExternalIdentity


class OidcAuthenticationError(ValueError):
    """Raised for an invalid bearer token without disclosing validation detail."""


class OidcConfigurationError(RuntimeError):
    """Raised when trusted OIDC metadata cannot be loaded or validated."""


@dataclass(frozen=True)
class OidcVerifierSettings:
    discovery_url: str
    issuer: str
    audience: str
    tenant_claim: str = "tenant_id"
    cache_ttl_seconds: float = 300.0
    timeout_seconds: float = 3.0
    clock_skew_seconds: int = 30

    def __post_init__(self) -> None:
        _validate_remote_url(self.discovery_url, name="GEO_OIDC_DISCOVERY_URL")
        if not self.issuer.strip() or not self.audience.strip() or not self.tenant_claim.strip():
            raise OidcConfigurationError(
                "OIDC issuer, audience, and tenant claim are required."
            )
        if self.cache_ttl_seconds <= 0 or self.timeout_seconds <= 0:
            raise OidcConfigurationError("OIDC cache TTL and timeout must be positive.")


class RemoteJwksProvider:
    """Load discovery and JWKS documents with a bounded in-process cache."""

    def __init__(
        self,
        settings: OidcVerifierSettings,
        *,
        get: Callable[..., httpx.Response] = httpx.get,
    ) -> None:
        self._settings = settings
        self._get = get
        self._lock = Lock()
        self._cached: dict[str, Any] | None = None
        self._expires_at = 0.0

    def __call__(self) -> dict[str, Any]:
        with self._lock:
            if self._cached is not None and monotonic() < self._expires_at:
                return self._cached
            document = self._json(self._settings.discovery_url, "OIDC discovery")
            if document.get("issuer") != self._settings.issuer:
                raise OidcConfigurationError("OIDC discovery issuer does not match configuration.")
            jwks_url = str(document.get("jwks_uri") or "")
            _validate_remote_url(jwks_url, name="OIDC jwks_uri")
            jwks = self._json(jwks_url, "OIDC JWKS")
            keys = jwks.get("keys")
            if not isinstance(keys, list) or not keys:
                raise OidcConfigurationError("OIDC JWKS must contain signing keys.")
            self._cached = jwks
            self._expires_at = monotonic() + self._settings.cache_ttl_seconds
            return jwks

    def _json(self, url: str, name: str) -> dict[str, Any]:
        try:
            response = self._get(url, timeout=self._settings.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise OidcConfigurationError(f"{name} is unavailable.") from error
        if not isinstance(payload, dict):
            raise OidcConfigurationError(f"{name} must be a JSON object.")
        return payload


class OidcTokenVerifier:
    def __init__(
        self,
        settings: OidcVerifierSettings,
        *,
        jwks_provider: Callable[[], dict[str, Any]] | None = None,
        now: Callable[[], float] = time,
    ) -> None:
        self._settings = settings
        self._jwks_provider = jwks_provider or RemoteJwksProvider(settings)
        self._now = now

    def verify(self, token: str) -> ExternalIdentity:
        header, claims, signed, signature = _decode_token(token)
        if header.get("alg") != "RS256":
            raise OidcAuthenticationError("The bearer token is invalid.")
        key = _select_key(self._jwks_provider(), str(header.get("kid") or ""))
        _verify_signature(key, signed, signature)
        self._verify_claims(claims)
        try:
            tenant_id = UUID(str(claims[self._settings.tenant_claim]))
        except (KeyError, TypeError, ValueError) as error:
            raise OidcAuthenticationError("The bearer token is invalid.") from error
        return ExternalIdentity(
            issuer=str(claims["iss"]),
            subject=str(claims["sub"]),
            tenant_id=tenant_id,
            email=_optional_string(claims.get("email")),
            display_name=_optional_string(claims.get("name")),
        )

    def _verify_claims(self, claims: dict[str, Any]) -> None:
        now = self._now()
        skew = self._settings.clock_skew_seconds
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        try:
            valid = (
                claims.get("iss") == self._settings.issuer
                and isinstance(claims.get("sub"), str)
                and bool(str(claims.get("sub") or "").strip())
                and isinstance(audiences, list)
                and self._settings.audience in audiences
                and float(claims["exp"]) > now - skew
                and float(claims.get("nbf", 0)) <= now + skew
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise OidcAuthenticationError("The bearer token is invalid.")


def _decode_token(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    try:
        encoded_header, encoded_claims, encoded_signature = token.strip().split(".")
        header = json.loads(_base64url(encoded_header))
        claims = json.loads(_base64url(encoded_claims))
        signature = _base64url(encoded_signature)
    except (ValueError, json.JSONDecodeError) as error:
        raise OidcAuthenticationError("The bearer token is invalid.") from error
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise OidcAuthenticationError("The bearer token is invalid.")
    return header, claims, f"{encoded_header}.{encoded_claims}".encode("ascii"), signature


def _base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _select_key(jwks: dict[str, Any], kid: str) -> dict[str, Any]:
    candidates = [
        key
        for key in jwks.get("keys", [])
        if isinstance(key, dict)
        and key.get("kty") == "RSA"
        and key.get("use", "sig") == "sig"
        and (not kid or key.get("kid") == kid)
    ]
    if len(candidates) != 1:
        raise OidcAuthenticationError("The bearer token is invalid.")
    return candidates[0]


def _verify_signature(key: dict[str, Any], signed: bytes, signature: bytes) -> None:
    try:
        exponent = int.from_bytes(_base64url(str(key["e"])), "big")
        modulus = int.from_bytes(_base64url(str(key["n"])), "big")
        public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        public_key.verify(signature, signed, padding.PKCS1v15(), SHA256())
    except (KeyError, TypeError, ValueError, InvalidSignature) as error:
        raise OidcAuthenticationError("The bearer token is invalid.") from error


def _validate_remote_url(value: str, *, name: str) -> None:
    parsed = urlparse(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if not parsed.hostname or (parsed.scheme != "https" and not local_http):
        raise OidcConfigurationError(f"{name} must be an HTTPS URL.")


def _optional_string(value: object) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None
