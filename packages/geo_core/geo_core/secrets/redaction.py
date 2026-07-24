"""Central redaction and serialization guards for secret-bearing values."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass
import re
from typing import Never

from .crypto import EnvelopeCipher, MasterKeyring
from .errors import SecretSerializationRejected
from .models import EncryptedSecretVersion, REDACTED, SecretValue
from .recovery import (
    AuthenticatedKeyringSnapshot,
    KeyringRestoreResult,
    RecoveryEscrowKey,
    RepresentativeSecretCanary,
)
from .store import InMemorySecretStore


_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|password|passwd|secret|token|api[_-]?key|client[_-]?secret|"
    r"storage[_-]?state|proxy[_-]?(?:url|password))",
    re.IGNORECASE,
)
_INLINE_CREDENTIAL = re.compile(
    r"(?i)((?:proxy[_-]?)?authorization[\"']?\s*[:=]\s*[\"']?"
    r"(?:bearer\s+|basic\s+)?|(?:set[_-]?)?cookie[\"']?\s*[:=]\s*[\"']?|"
    r"(?:password|passwd|secret|token|(?:access|refresh|id)[_-]?token|"
    r"api[_-]?key|client[_-]?secret)[\"']?"
    r"\s*[:=]\s*[\"']?)([^\"'\s,;}&]+)"
)
_URI_USERINFO = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)
_AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic)\s+[^\s,;]+")


class SecretRedactor:
    """Redact registered values plus common credential-bearing structures."""

    def __init__(self, known_values: Iterable[SecretValue | bytes | str] = ()) -> None:
        values: list[str] = []
        for value in known_values:
            if isinstance(value, SecretValue):
                raw = value.reveal_bytes()
            elif isinstance(value, bytes):
                raw = value
            else:
                raw = value.encode("utf-8")
            if raw:
                try:
                    decoded = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                values.append(decoded)
        self._known_values = tuple(sorted(set(values), key=len, reverse=True))

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("secret redactors cannot be serialized")

    def redact(self, value: object, *, field_name: str | None = None) -> object:
        if isinstance(value, (SecretValue, EncryptedSecretVersion)):
            return REDACTED
        if field_name is not None and _SENSITIVE_KEY.search(field_name):
            return REDACTED
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, bytes):
            return REDACTED.encode("ascii")
        if isinstance(value, Mapping):
            return {
                str(key): self.redact(item, field_name=str(key))
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, set):
            return {self.redact(item) for item in value}
        if isinstance(value, BaseException):
            return RuntimeError(self.redact_text(str(value)))
        return value

    def redact_text(self, value: str) -> str:
        redacted = value
        for known in self._known_values:
            redacted = redacted.replace(known, REDACTED)
        redacted = _URI_USERINFO.sub(r"\g<scheme>[REDACTED]@", redacted)
        redacted = _INLINE_CREDENTIAL.sub(r"\1[REDACTED]", redacted)
        return _AUTH_SCHEME.sub(r"\1 [REDACTED]", redacted)

    def assert_no_registered_plaintext(self, value: object) -> None:
        rendered = repr(value)
        if any(known in rendered for known in self._known_values):
            raise SecretSerializationRejected("secret plaintext detected in serialized payload")


def reject_secret_bearing_payload(value: object) -> None:
    """Reject object graphs that would place secret objects in Jobs or artifacts."""

    if getattr(type(value), "__secret_bearing__", False) is True or isinstance(
        value,
        (
            SecretValue,
            EncryptedSecretVersion,
            MasterKeyring,
            EnvelopeCipher,
            SecretRedactor,
            InMemorySecretStore,
            AuthenticatedKeyringSnapshot,
            KeyringRestoreResult,
            RecoveryEscrowKey,
            RepresentativeSecretCanary,
        ),
    ):
        raise SecretSerializationRejected("secret-bearing values cannot enter serialized payloads")
    if isinstance(value, Mapping):
        for key, item in value.items():
            reject_secret_bearing_payload(key)
            reject_secret_bearing_payload(item)
        return
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            reject_secret_bearing_payload(getattr(value, field.name))
        return
    if isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            reject_secret_bearing_payload(item)
