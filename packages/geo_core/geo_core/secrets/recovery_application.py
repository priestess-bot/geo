"""Application entrypoint for empty-environment Secret Store recovery."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar, Never
from uuid import UUID

from .errors import SecretSerializationRejected
from .recovery import (
    AuthenticatedKeyringSnapshot,
    KeyringRestoreResult,
    KeyringSnapshotCodec,
    RecoveryEscrowKey,
    RepresentativeSecretProbe,
    verify_representative_secret_probes,
)
from .recovery_files import KeyringSnapshotFileStore


@dataclass(frozen=True, kw_only=True, repr=False)
class SecretRecoveryReadiness:
    restore_result: KeyringRestoreResult
    verified_external_kinds: tuple[str, ...]

    __secret_bearing__: ClassVar[bool] = True

    def __repr__(self) -> str:
        return (
            "SecretRecoveryReadiness("
            f"snapshot_id={self.restore_result.snapshot_id!r}, "
            f"verified_key_versions={self.restore_result.verified_key_versions!r}, "
            f"verified_external_kinds={self.verified_external_kinds!r})"
        )

    def __reduce__(self) -> Never:
        raise SecretSerializationRejected("Secret Store recovery results cannot be serialized")


class SecretRecoveryApplication:
    def __init__(self, codec: KeyringSnapshotCodec) -> None:
        self._codec = codec

    def recover(
        self,
        *,
        snapshot: AuthenticatedKeyringSnapshot,
        escrow_key: RecoveryEscrowKey | None,
        representative_probes: Iterable[RepresentativeSecretProbe],
    ) -> SecretRecoveryReadiness:
        restored = self._codec.restore(snapshot=snapshot, escrow_key=escrow_key)
        verified = verify_representative_secret_probes(
            keyring=restored.keyring,
            probes=representative_probes,
        )
        return SecretRecoveryReadiness(
            restore_result=restored,
            verified_external_kinds=verified,
        )

    def recover_from_file(
        self,
        *,
        file_store: KeyringSnapshotFileStore,
        snapshot_id: UUID,
        escrow_key: RecoveryEscrowKey | None,
        representative_probes: Iterable[RepresentativeSecretProbe],
    ) -> SecretRecoveryReadiness:
        return self.recover(
            snapshot=file_store.load(snapshot_id),
            escrow_key=escrow_key,
            representative_probes=representative_probes,
        )
