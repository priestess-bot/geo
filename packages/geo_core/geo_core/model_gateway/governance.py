"""Fail-closed evidence locators used by Model Gateway release governance."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_EVIDENCE_SCHEMES = frozenset({"https", "minio", "s3"})


def validate_evidence(
    reference: str | None,
    sha256: str | None,
    *,
    label: str,
) -> None:
    """Require an immutable digest and a credential-free, resolvable locator."""
    if reference is None or sha256 is None or _SHA256.fullmatch(sha256) is None:
        raise ValueError(f"{label} requires a locator and lowercase SHA-256")
    value = reference.strip()
    if (
        value != reference
        or not value.isascii()
        or len(value) > 2048
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} locator is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in _ALLOWED_EVIDENCE_SCHEMES
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
    ):
        raise ValueError(f"{label} locator must be a credential-free HTTPS/S3/MinIO URI")
    if parsed.scheme == "https" and parsed.hostname is None:
        raise ValueError(f"{label} HTTPS locator requires a host")


__all__ = ["validate_evidence"]
