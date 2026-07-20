from __future__ import annotations

import base64
import json
from time import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
import pytest

from geo_api.oidc import (
    OidcAuthenticationError,
    OidcConfigurationError,
    OidcTokenVerifier,
    OidcVerifierSettings,
)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _token(
    private_key: rsa.RSAPrivateKey,
    claims: dict[str, object],
    *,
    algorithm: str = "RS256",
) -> str:
    header = _encode(json.dumps({"alg": algorithm, "kid": "key-1"}).encode())
    payload = _encode(json.dumps(claims).encode())
    signed = f"{header}.{payload}".encode("ascii")
    signature = private_key.sign(signed, padding.PKCS1v15(), SHA256())
    return f"{header}.{payload}.{_encode(signature)}"


def _verifier() -> tuple[OidcTokenVerifier, rsa.RSAPrivateKey, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "kid": "key-1",
                "n": _encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
                "e": _encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
            }
        ]
    }
    tenant_id = str(uuid4())
    verifier = OidcTokenVerifier(
        OidcVerifierSettings(
            discovery_url="https://issuer.example/.well-known/openid-configuration",
            issuer="https://issuer.example",
            audience="geo-admin",
        ),
        jwks_provider=lambda: jwks,
    )
    return verifier, private_key, tenant_id


def test_oidc_settings_require_a_nonempty_tenant_claim() -> None:
    with pytest.raises(OidcConfigurationError):
        OidcVerifierSettings(
            discovery_url="https://issuer.example/.well-known/openid-configuration",
            issuer="https://issuer.example",
            audience="geo-admin",
            tenant_claim="",
        )


def test_valid_rs256_token_returns_external_identity() -> None:
    verifier, private_key, tenant_id = _verifier()
    claims = {
        "iss": "https://issuer.example",
        "sub": "operator-42",
        "aud": ["another-api", "geo-admin"],
        "tenant_id": tenant_id,
        "exp": int(time()) + 300,
        "email": "operator@example.com",
    }

    identity = verifier.verify(_token(private_key, claims))

    assert identity.subject == "operator-42"
    assert str(identity.tenant_id) == tenant_id
    assert identity.email == "operator@example.com"


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "https://attacker.example"),
        ("aud", "wrong-audience"),
        ("exp", 1),
        ("tenant_id", "not-a-uuid"),
    ],
)
def test_invalid_trust_claims_are_rejected(claim: str, value: object) -> None:
    verifier, private_key, tenant_id = _verifier()
    claims: dict[str, object] = {
        "iss": "https://issuer.example",
        "sub": "operator-42",
        "aud": "geo-admin",
        "tenant_id": tenant_id,
        "exp": int(time()) + 300,
    }
    claims[claim] = value

    with pytest.raises(OidcAuthenticationError):
        verifier.verify(_token(private_key, claims))


def test_non_rs256_algorithm_and_tampered_signature_are_rejected() -> None:
    verifier, private_key, tenant_id = _verifier()
    claims = {
        "iss": "https://issuer.example",
        "sub": "operator-42",
        "aud": "geo-admin",
        "tenant_id": tenant_id,
        "exp": int(time()) + 300,
    }
    invalid_algorithm = _token(private_key, claims, algorithm="HS256")
    valid = _token(private_key, claims)
    header, payload, signature = valid.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{replacement}{signature[1:]}"

    with pytest.raises(OidcAuthenticationError):
        verifier.verify(invalid_algorithm)
    with pytest.raises(OidcAuthenticationError):
        verifier.verify(tampered)
