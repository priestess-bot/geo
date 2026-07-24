"""Fail-closed filesystem adapter for independently stored keyring snapshots."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import shutil
import stat
import re
from uuid import UUID, uuid4

from .errors import (
    SecretBackupLocationError,
    SecretSnapshotAlreadyExists,
    SecretSnapshotIntegrityError,
)
from .recovery import (
    AuthenticatedKeyringSnapshot,
    KeyringRestoreResult,
    KeyringSnapshotCodec,
    RecoveryEscrowKey,
    parse_snapshot_manifest,
    snapshot_commit_bytes,
    verify_snapshot_commit,
)


_MANIFEST_NAME = "manifest.json"
_CIPHERTEXT_NAME = "keyring.enc"
_COMMIT_NAME = "COMMITTED"
_EXPECTED_FILES = frozenset({_MANIFEST_NAME, _CIPHERTEXT_NAME, _COMMIT_NAME})
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_CIPHERTEXT_BYTES = 16 * 1024 * 1024
_MAX_COMMIT_BYTES = 4 * 1024
_LOCATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class KeyringSnapshotFileStore:
    """Persist an immutable snapshot bundle with a commit marker written last."""

    def __init__(
        self,
        *,
        escrow_directory: str | os.PathLike[str],
        data_backup_directory: str | os.PathLike[str],
        escrow_location_id: str,
        data_backup_location_id: str,
    ) -> None:
        self._escrow_directory = Path(escrow_directory)
        self._data_backup_directory = Path(data_backup_directory)
        assert_independent_backup_locations(
            escrow_directory=self._escrow_directory,
            data_backup_directory=self._data_backup_directory,
            escrow_location_id=escrow_location_id,
            data_backup_location_id=data_backup_location_id,
        )
        self._escrow_location_id = escrow_location_id
        self._data_backup_location_id = data_backup_location_id

    def __repr__(self) -> str:
        return "KeyringSnapshotFileStore([REDACTED LOCATIONS])"

    def save(self, snapshot: AuthenticatedKeyringSnapshot) -> Path:
        self._validate_separation()
        self._ensure_escrow_root()
        bundle = self._escrow_directory / str(snapshot.manifest.snapshot_id)
        try:
            os.mkdir(bundle, mode=0o700)
        except FileExistsError:
            raise SecretSnapshotAlreadyExists("immutable keyring snapshot already exists") from None
        except OSError:
            raise SecretBackupLocationError("keyring snapshot directory cannot be created") from None

        committed = False
        try:
            _atomic_write_file(bundle / _MANIFEST_NAME, snapshot.manifest.serialized_bytes())
            _atomic_write_file(bundle / _CIPHERTEXT_NAME, snapshot.ciphertext)
            _fsync_directory(bundle)
            _atomic_write_file(bundle / _COMMIT_NAME, snapshot_commit_bytes(snapshot))
            _fsync_directory(bundle)
            _fsync_directory(self._escrow_directory)
            committed = True
            return bundle
        finally:
            if not committed:
                _remove_uncommitted_bundle(bundle)

    def load(self, snapshot_id: UUID) -> AuthenticatedKeyringSnapshot:
        if not isinstance(snapshot_id, UUID) or snapshot_id.int == 0:
            raise SecretSnapshotIntegrityError("keyring snapshot identity is invalid")
        self._validate_separation()
        _validate_directory(self._escrow_directory, label="keyring escrow root")
        bundle = self._escrow_directory / str(snapshot_id)
        _validate_directory(bundle, label="keyring snapshot bundle")
        try:
            entries = frozenset(item.name for item in bundle.iterdir())
        except OSError:
            raise SecretSnapshotIntegrityError("keyring snapshot bundle cannot be read") from None
        if entries != _EXPECTED_FILES:
            raise SecretSnapshotIntegrityError("keyring snapshot bundle is partial or invalid")

        manifest_raw = _secure_read_file(
            bundle / _MANIFEST_NAME,
            maximum_bytes=_MAX_MANIFEST_BYTES,
        )
        ciphertext = _secure_read_file(
            bundle / _CIPHERTEXT_NAME,
            maximum_bytes=_MAX_CIPHERTEXT_BYTES,
        )
        commit_raw = _secure_read_file(
            bundle / _COMMIT_NAME,
            maximum_bytes=_MAX_COMMIT_BYTES,
        )
        manifest = parse_snapshot_manifest(manifest_raw)
        if manifest.serialized_bytes() != manifest_raw:
            raise SecretSnapshotIntegrityError("keyring snapshot manifest is not canonical")
        if manifest.snapshot_id != snapshot_id:
            raise SecretSnapshotIntegrityError("keyring snapshot identity does not match bundle")
        verify_snapshot_commit(
            snapshot_id=snapshot_id,
            manifest=manifest,
            raw=commit_raw,
        )
        return AuthenticatedKeyringSnapshot(manifest=manifest, ciphertext=ciphertext)

    def restore(
        self,
        *,
        snapshot_id: UUID,
        codec: KeyringSnapshotCodec,
        escrow_key: RecoveryEscrowKey | None,
    ) -> KeyringRestoreResult:
        return codec.restore(snapshot=self.load(snapshot_id), escrow_key=escrow_key)

    def _ensure_escrow_root(self) -> None:
        try:
            os.mkdir(self._escrow_directory, mode=0o700)
        except FileExistsError:
            pass
        except OSError:
            raise SecretBackupLocationError("keyring escrow root cannot be created") from None
        _validate_directory(self._escrow_directory, label="keyring escrow root")

    def _validate_separation(self) -> None:
        assert_independent_backup_locations(
            escrow_directory=self._escrow_directory,
            data_backup_directory=self._data_backup_directory,
            escrow_location_id=self._escrow_location_id,
            data_backup_location_id=self._data_backup_location_id,
        )


def assert_independent_backup_locations(
    *,
    escrow_directory: str | os.PathLike[str],
    data_backup_directory: str | os.PathLike[str],
    escrow_location_id: str,
    data_backup_location_id: str,
) -> None:
    """Reject the same logical location and overlapping filesystem roots."""

    if (
        not isinstance(escrow_location_id, str)
        or not isinstance(data_backup_location_id, str)
        or _LOCATION_ID.fullmatch(escrow_location_id) is None
        or _LOCATION_ID.fullmatch(data_backup_location_id) is None
        or escrow_location_id == data_backup_location_id
    ):
        raise SecretBackupLocationError("keyring and data backup locations must be independent")
    escrow = Path(escrow_directory).resolve(strict=False)
    data = Path(data_backup_directory).resolve(strict=False)
    try:
        common = Path(os.path.commonpath((escrow, data)))
    except ValueError:
        return
    if common in {escrow, data}:
        raise SecretBackupLocationError("keyring and data backup paths must not overlap")


def _validate_directory(path: Path, *, label: str) -> None:
    try:
        details = path.lstat()
    except OSError:
        raise SecretBackupLocationError(f"{label} is unavailable") from None
    if path.is_symlink() or not stat.S_ISDIR(details.st_mode):
        raise SecretBackupLocationError(f"{label} must be a regular directory")
    if stat.S_IMODE(details.st_mode) != 0o700:
        raise SecretBackupLocationError(f"{label} permissions must be 0700")
    if details.st_uid not in {0, os.geteuid()}:
        raise SecretBackupLocationError(f"{label} owner is not trusted")


def _atomic_write_file(path: Path, payload: bytes) -> None:
    temporary = path.parent / f".{path.name}.{uuid4()}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count < 1:
                raise OSError(errno.EIO, "short write")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError:
        raise SecretBackupLocationError("keyring snapshot file cannot be written atomically") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _secure_read_file(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        initial = path.lstat()
    except OSError:
        raise SecretSnapshotIntegrityError("keyring snapshot file is unavailable") from None
    if path.is_symlink() or not stat.S_ISREG(initial.st_mode):
        raise SecretSnapshotIntegrityError("keyring snapshot file must be regular")
    if stat.S_IMODE(initial.st_mode) != 0o600 or initial.st_uid not in {0, os.geteuid()}:
        raise SecretSnapshotIntegrityError("keyring snapshot file permissions are invalid")
    if initial.st_size < 1 or initial.st_size > maximum_bytes:
        raise SecretSnapshotIntegrityError("keyring snapshot file size is invalid")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                opened.st_ino != initial.st_ino
                or opened.st_dev != initial.st_dev
                or opened.st_size != initial.st_size
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_uid not in {0, os.geteuid()}
            ):
                raise SecretSnapshotIntegrityError(
                    "keyring snapshot file changed during validation"
                )
            chunks: list[bytes] = []
            remaining = maximum_bytes + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            final = os.fstat(descriptor)
            if (
                final.st_size != opened.st_size
                or final.st_mtime_ns != opened.st_mtime_ns
                or final.st_ctime_ns != opened.st_ctime_ns
            ):
                raise SecretSnapshotIntegrityError(
                    "keyring snapshot file changed during validation"
                )
        finally:
            os.close(descriptor)
    except SecretSnapshotIntegrityError:
        raise
    except OSError:
        raise SecretSnapshotIntegrityError("keyring snapshot file cannot be read securely") from None
    raw = b"".join(chunks)
    if len(raw) != initial.st_size or len(raw) > maximum_bytes:
        raise SecretSnapshotIntegrityError("keyring snapshot file size is invalid")
    return raw


def _remove_uncommitted_bundle(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise SecretBackupLocationError("keyring snapshot directory cannot be synchronized") from None
