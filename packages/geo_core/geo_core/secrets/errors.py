"""Secret Store errors whose messages are safe for logs and API mapping."""

from __future__ import annotations


class SecretStoreError(RuntimeError):
    """Base class for runtime failures that never embeds secret material."""


class SecretConfigurationError(SecretStoreError):
    """The master keyring is unavailable or does not meet security policy."""


class SecretKeyUnavailable(SecretStoreError):
    """A ciphertext references a master key version not present in memory."""


class SecretDecryptionError(SecretStoreError):
    """Envelope authentication or decryption failed."""


class SecretNotFound(SecretStoreError):
    """The scoped reference or immutable version is not available."""


class SecretScopeViolation(SecretStoreError):
    """A caller attempted to use a reference across project or purpose scope."""


class SecretVersionUnavailable(SecretStoreError):
    """A version is pending, revoked, or otherwise unavailable to a consumer."""


class SecretStateConflict(SecretStoreError):
    """A lifecycle transition cannot be applied to the current snapshot."""


class SecretSerializationRejected(SecretStoreError):
    """Secret-bearing material was about to enter a serialized payload."""


class SecretRecoveryError(SecretStoreError):
    """A keyring snapshot cannot be authenticated or restored."""


class SecretSnapshotIntegrityError(SecretRecoveryError):
    """A snapshot is partial, malformed, altered, or encrypted by another key."""


class SecretBackupLocationError(SecretRecoveryError):
    """Escrow storage permissions or separation policy is not satisfied."""


class SecretSnapshotAlreadyExists(SecretRecoveryError):
    """An immutable snapshot identity has already been written."""


class SecretAuthorizationError(SecretStoreError):
    """The principal cannot perform the requested Secret Store operation."""


class SecretIdempotencyConflict(SecretStoreError):
    """An Idempotency-Key was reused with a different request hash."""


class SecretConcurrencyConflict(SecretStoreError):
    """The expected aggregate or project transaction version is stale."""


class SecretLifecycleError(SecretStoreError):
    """A Secret Store lifecycle command is invalid for the current state."""


class SecretContractError(ValueError):
    """A non-secret field violates the immutable Secret Store contract."""
