"""Stable non-secret fingerprint for one encrypted Secret Store envelope."""

import hashlib

from .models import EncryptedSecretVersion


def envelope_fingerprint(envelope: EncryptedSecretVersion) -> str:
    digest = hashlib.sha256()
    digest.update(str(envelope.handle.reference_id).encode("ascii"))
    digest.update(envelope.handle.version.to_bytes(8, "big"))
    digest.update(envelope.master_key_version.to_bytes(8, "big"))
    digest.update(envelope.data_nonce)
    digest.update(envelope.ciphertext)
    digest.update(envelope.wrap_nonce)
    digest.update(envelope.wrapped_data_key)
    return digest.hexdigest()


__all__ = ["envelope_fingerprint"]
