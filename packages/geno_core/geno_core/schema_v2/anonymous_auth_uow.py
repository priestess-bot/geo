from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Callable, Sequence, TypeVar
from uuid import UUID

from geno_core.schema_v2.session_uow import (
    SchemaV2ResolvedProjectScope,
    SchemaV2SessionAuthorizationError,
    SchemaV2SessionCleanupTelemetry,
    SchemaV2SessionConnection,
    SchemaV2SessionTokenHash,
    _ACTIVE_CONNECTION_IDS,
    _ACTIVE_CONNECTION_IDS_LOCK,
    _connection_is_idle,
    _json_array,
    _parse_project_scope,
    _string_tuple,
    _uuid_tuple,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DELIVERY_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
MAX_RAW_INVITATION_TOKEN_LENGTH = 512
MIN_RAW_INVITATION_TOKEN_LENGTH = 32
MIN_RAW_IDEMPOTENCY_KEY_LENGTH = 16
MAX_RAW_IDEMPOTENCY_KEY_LENGTH = 512
MAX_RAW_SOURCE_IDENTITY_LENGTH = 1024
MIN_SOURCE_IDENTITY_HMAC_KEY_LENGTH = 32
MAX_SOURCE_IDENTITY_HMAC_KEY_LENGTH = 64
MAX_DELIVERY_CIPHERTEXT_LENGTH = 16384
AUTH_SURFACE_POLICY_VERSION = "auth_surface_policy_v1"
_OPAQUE_FACTORY_KEY = object()
_INVITATION_ROLES = frozenset(
    {
        "project_owner",
        "analyst",
        "reviewer",
        "knowledge_architect",
        "content_operator",
        "client_viewer",
    }
)
_STABLE_COMMAND_ERRORS = {
    "42501": "auth_writes_temporarily_disabled",
    "GA001": "auth_command_invalid_argument",
    "GA003": "auth_command_not_authorized",
    "GA004": "auth_command_idempotency_conflict",
    "GA005": "auth_command_state_conflict",
    "GA006": "auth_command_invariant_violation",
}


class SchemaV2AnonymousAuthUnitOfWorkError(RuntimeError):
    """A redacted, fail-closed anonymous Schema v2 auth error."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class SchemaV2AnonymousAuthInputError(SchemaV2AnonymousAuthUnitOfWorkError):
    def __init__(self, detail: str = "anonymous auth input is invalid") -> None:
        super().__init__("invalid_anonymous_auth_input", detail)


class SchemaV2AnonymousAuthResultError(SchemaV2AnonymousAuthUnitOfWorkError):
    def __init__(self) -> None:
        super().__init__(
            "invalid_anonymous_auth_result",
            "Schema v2 anonymous auth result is invalid",
        )


class SchemaV2AnonymousAuthCommandError(SchemaV2AnonymousAuthUnitOfWorkError):
    """A stable command rejection translated without database detail."""

    def __init__(self, code: str) -> None:
        super().__init__(code, "Schema v2 anonymous auth command was rejected")


class SchemaV2AnonymousAuthLifecycleError(SchemaV2AnonymousAuthUnitOfWorkError):
    def __init__(self, detail: str) -> None:
        super().__init__("invalid_anonymous_auth_uow_lifecycle", detail)


class SchemaV2AnonymousAuthCommitOutcomeUnknownError(SchemaV2AnonymousAuthUnitOfWorkError):
    retryable = False
    requires_idempotency_recovery = True
    transaction_outcome = "unknown"

    def __init__(self) -> None:
        super().__init__(
            "anonymous_auth_commit_outcome_unknown",
            "Schema v2 anonymous auth commit outcome is unknown; recover by request key",
        )


class SchemaV2AnonymousAuthRollbackError(SchemaV2AnonymousAuthUnitOfWorkError):
    retryable = False
    requires_idempotency_recovery = False
    transaction_outcome = "unknown"

    def __init__(self) -> None:
        super().__init__(
            "anonymous_auth_rollback_failed",
            "Schema v2 anonymous auth rollback could not be confirmed",
        )


class _AnonymousAuthState(str, Enum):
    NEW = "new"
    ACTIVE = "active"
    FINISHED = "finished"
    BROKEN = "broken"


class SchemaV2InvitationSurface(str, Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"


class SchemaV2PreflightResultCode(str, Enum):
    COMPATIBLE = "compatible"
    SURFACE_MISMATCH = "surface_mismatch"
    POLICY_STALE = "policy_stale"
    INVALID = "invalid"
    RATE_LIMITED = "rate_limited"


class SchemaV2RedeemResultCode(str, Enum):
    SUCCEEDED = "succeeded"
    REPLAYED = "replayed"
    SURFACE_MISMATCH = "surface_mismatch"
    INVALID = "invalid"
    RECOVERY_EXPIRED = "recovery_expired"
    REPLAY_LIMIT_EXCEEDED = "replay_limit_exceeded"
    SESSION_UNAVAILABLE = "session_unavailable"


@dataclass(frozen=True, init=False)
class SchemaV2InvitationTokenHash:
    _value: str = field(repr=False)

    def __init__(self, value: str, *, _factory_key: object | None = None) -> None:
        if _factory_key is not _OPAQUE_FACTORY_KEY or not SHA256_PATTERN.fullmatch(value):
            raise SchemaV2AnonymousAuthInputError()
        object.__setattr__(self, "_value", value)

    def __repr__(self) -> str:
        return "SchemaV2InvitationTokenHash([redacted])"


@dataclass(frozen=True, init=False)
class SchemaV2IdempotencyKeyHash:
    _value: str = field(repr=False)

    def __init__(self, value: str, *, _factory_key: object | None = None) -> None:
        if _factory_key is not _OPAQUE_FACTORY_KEY or not SHA256_PATTERN.fullmatch(value):
            raise SchemaV2AnonymousAuthInputError()
        object.__setattr__(self, "_value", value)

    def __repr__(self) -> str:
        return "SchemaV2IdempotencyKeyHash([redacted])"


@dataclass(frozen=True, init=False)
class SchemaV2SourceIdentityHmacKey:
    _value: bytes = field(repr=False)

    def __init__(self, value: bytes, *, _factory_key: object | None = None) -> None:
        if _factory_key is not _OPAQUE_FACTORY_KEY:
            raise SchemaV2AnonymousAuthInputError()
        if not (
            MIN_SOURCE_IDENTITY_HMAC_KEY_LENGTH <= len(value) <= MAX_SOURCE_IDENTITY_HMAC_KEY_LENGTH
        ):
            raise SchemaV2AnonymousAuthInputError()
        object.__setattr__(self, "_value", value)

    def __repr__(self) -> str:
        return "SchemaV2SourceIdentityHmacKey([redacted])"


@dataclass(frozen=True, init=False)
class SchemaV2SourceIdentityHmac:
    _value: str = field(repr=False)

    def __init__(self, value: str, *, _factory_key: object | None = None) -> None:
        if _factory_key is not _OPAQUE_FACTORY_KEY or not SHA256_PATTERN.fullmatch(value):
            raise SchemaV2AnonymousAuthInputError()
        object.__setattr__(self, "_value", value)

    def __repr__(self) -> str:
        return "SchemaV2SourceIdentityHmac([redacted])"


@dataclass(frozen=True, init=False)
class SchemaV2DeliveryCiphertext:
    _value: bytes = field(repr=False)

    def __init__(self, value: bytes, *, _factory_key: object | None = None) -> None:
        if _factory_key is not _OPAQUE_FACTORY_KEY or not (
            1 <= len(value) <= MAX_DELIVERY_CIPHERTEXT_LENGTH
        ):
            raise SchemaV2AnonymousAuthInputError()
        object.__setattr__(self, "_value", value)

    def as_bytes(self) -> bytes:
        return self._value

    def __repr__(self) -> str:
        return "SchemaV2DeliveryCiphertext([redacted])"


@dataclass(frozen=True, init=False)
class SchemaV2DeliveryNonce:
    _value: bytes = field(repr=False)

    def __init__(self, value: bytes, *, _factory_key: object | None = None) -> None:
        if _factory_key is not _OPAQUE_FACTORY_KEY or len(value) != 12:
            raise SchemaV2AnonymousAuthInputError()
        object.__setattr__(self, "_value", value)

    def as_bytes(self) -> bytes:
        return self._value

    def __repr__(self) -> str:
        return "SchemaV2DeliveryNonce([redacted])"


def hash_raw_invitation_token(raw_invitation_token: str) -> SchemaV2InvitationTokenHash:
    if type(raw_invitation_token) is not str or not (
        MIN_RAW_INVITATION_TOKEN_LENGTH
        <= len(raw_invitation_token)
        <= MAX_RAW_INVITATION_TOKEN_LENGTH
    ):
        raise SchemaV2AnonymousAuthInputError(
            "raw invitation token must be a non-empty bounded string"
        )
    return SchemaV2InvitationTokenHash(
        hashlib.sha256(raw_invitation_token.encode("utf-8")).hexdigest(),
        _factory_key=_OPAQUE_FACTORY_KEY,
    )


def hash_raw_idempotency_key(raw_idempotency_key: str) -> SchemaV2IdempotencyKeyHash:
    if type(raw_idempotency_key) is not str or not (
        MIN_RAW_IDEMPOTENCY_KEY_LENGTH <= len(raw_idempotency_key) <= MAX_RAW_IDEMPOTENCY_KEY_LENGTH
    ):
        raise SchemaV2AnonymousAuthInputError("raw idempotency key must be a bounded string")
    return SchemaV2IdempotencyKeyHash(
        hashlib.sha256(raw_idempotency_key.encode("utf-8")).hexdigest(),
        _factory_key=_OPAQUE_FACTORY_KEY,
    )


def build_source_identity_hmac_key(raw_key: bytes) -> SchemaV2SourceIdentityHmacKey:
    if type(raw_key) is not bytes:
        raise SchemaV2AnonymousAuthInputError()
    return SchemaV2SourceIdentityHmacKey(
        raw_key,
        _factory_key=_OPAQUE_FACTORY_KEY,
    )


def hmac_source_identity(
    raw_source_identity: str,
    *,
    server_key: SchemaV2SourceIdentityHmacKey,
) -> SchemaV2SourceIdentityHmac:
    if type(server_key) is not SchemaV2SourceIdentityHmacKey:
        raise SchemaV2AnonymousAuthInputError()
    if (
        type(raw_source_identity) is not str
        or not raw_source_identity
        or raw_source_identity != raw_source_identity.strip()
        or len(raw_source_identity) > MAX_RAW_SOURCE_IDENTITY_LENGTH
    ):
        raise SchemaV2AnonymousAuthInputError(
            "source identity must be a non-empty bounded canonical string"
        )
    digest = hmac.new(
        server_key._value,
        raw_source_identity.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return SchemaV2SourceIdentityHmac(digest, _factory_key=_OPAQUE_FACTORY_KEY)


def protect_delivery_ciphertext(value: bytes) -> SchemaV2DeliveryCiphertext:
    if type(value) is not bytes:
        raise SchemaV2AnonymousAuthInputError()
    return SchemaV2DeliveryCiphertext(value, _factory_key=_OPAQUE_FACTORY_KEY)


def protect_delivery_nonce(value: bytes) -> SchemaV2DeliveryNonce:
    if type(value) is not bytes:
        raise SchemaV2AnonymousAuthInputError()
    return SchemaV2DeliveryNonce(value, _factory_key=_OPAQUE_FACTORY_KEY)


@dataclass(frozen=True)
class SchemaV2AnonymousAuthPreflightResult:
    result_code: SchemaV2PreflightResultCode
    compatibility: SchemaV2PreflightResultCode
    requested_surface: SchemaV2InvitationSurface
    recommended_surface: SchemaV2InvitationSurface | None
    invitation_role: str | None
    policy_version: str | None
    invitation_request_count: int
    source_request_count: int
    retry_after_seconds: int | None
    correlation_id: UUID


@dataclass(frozen=True)
class SchemaV2AnonymousAuthSession:
    session_id: UUID
    actor_id: str
    tenant_id: UUID
    project_ids: tuple[UUID, ...]
    tenant_roles: tuple[str, ...]
    project_scopes: tuple[SchemaV2ResolvedProjectScope, ...]


@dataclass(frozen=True)
class SchemaV2AnonymousAuthRedeemResult:
    result_code: SchemaV2RedeemResultCode
    attempt_id: UUID | None
    session: SchemaV2AnonymousAuthSession | None
    delivery_ciphertext: SchemaV2DeliveryCiphertext | None
    delivery_key_id: str | None
    delivery_nonce: SchemaV2DeliveryNonce | None
    delivery_expires_at: datetime | None
    replay_count: int | None
    recommended_surface: SchemaV2InvitationSurface | None
    correlation_id: UUID


_ResultT = TypeVar("_ResultT")


class SchemaV2AnonymousAuthUnitOfWork:
    """One exact anonymous auth command in one isolated transaction."""

    def __init__(self, connection: SchemaV2SessionConnection) -> None:
        if getattr(connection, "autocommit", False):
            raise SchemaV2AnonymousAuthLifecycleError(
                "anonymous auth unit of work requires autocommit to be disabled"
            )
        self._connection = connection
        self._state = _AnonymousAuthState.NEW
        self._connection_reserved = False
        self._connection_reusable = True
        self._cleanup_telemetry = SchemaV2SessionCleanupTelemetry(
            status="not_run",
            connection_discarded=False,
        )
        self._transaction_outcome = "not_started"

    @property
    def connection_reusable(self) -> bool:
        return self._connection_reusable

    @property
    def cleanup_telemetry(self) -> SchemaV2SessionCleanupTelemetry:
        return self._cleanup_telemetry

    @property
    def transaction_outcome(self) -> str:
        return self._transaction_outcome

    def preflight(
        self,
        *,
        invitation_id: UUID,
        invitation_token_hash: SchemaV2InvitationTokenHash,
        requested_surface: SchemaV2InvitationSurface,
        source_fingerprint_hmac: SchemaV2SourceIdentityHmac,
    ) -> SchemaV2AnonymousAuthPreflightResult:
        _require_uuid(invitation_id)
        _require_exact_type(invitation_token_hash, SchemaV2InvitationTokenHash)
        _require_exact_type(requested_surface, SchemaV2InvitationSurface)
        _require_exact_type(source_fingerprint_hmac, SchemaV2SourceIdentityHmac)
        params = (
            invitation_id,
            invitation_token_hash._value,
            requested_surface.value,
            source_fingerprint_hmac._value,
        )
        return self._execute_exact(
            """
            SELECT result_code, compatibility, requested_surface,
                   recommended_surface, invitation_role, policy_version,
                   invitation_request_count, source_request_count,
                   retry_after_seconds, correlation_id
            FROM public.geno_v2_preflight_auth_invitation(%s, %s, %s, %s)
            """,
            params,
            lambda rows: _parse_preflight_rows(
                rows,
                expected_surface=requested_surface,
            ),
        )

    def redeem(
        self,
        *,
        attempt_id: UUID,
        session_id: UUID,
        invitation_id: UUID,
        invitation_token_hash: SchemaV2InvitationTokenHash,
        requested_surface: SchemaV2InvitationSurface,
        idempotency_key_hash: SchemaV2IdempotencyKeyHash,
        session_token_hash: SchemaV2SessionTokenHash,
        session_expires_at: datetime,
        delivery_ciphertext: SchemaV2DeliveryCiphertext,
        delivery_key_id: str,
        delivery_nonce: SchemaV2DeliveryNonce,
        delivery_expires_at: datetime,
    ) -> SchemaV2AnonymousAuthRedeemResult:
        for value in (attempt_id, session_id, invitation_id):
            _require_uuid(value)
        _require_exact_type(invitation_token_hash, SchemaV2InvitationTokenHash)
        _require_exact_type(requested_surface, SchemaV2InvitationSurface)
        _require_exact_type(idempotency_key_hash, SchemaV2IdempotencyKeyHash)
        _require_exact_type(session_token_hash, SchemaV2SessionTokenHash)
        _require_exact_type(delivery_ciphertext, SchemaV2DeliveryCiphertext)
        _require_exact_type(delivery_nonce, SchemaV2DeliveryNonce)
        if type(delivery_key_id) is not str or not DELIVERY_KEY_ID_PATTERN.fullmatch(
            delivery_key_id
        ):
            raise SchemaV2AnonymousAuthInputError("delivery key id is invalid")
        normalized_session_expiry = _aware_datetime(session_expires_at)
        normalized_delivery_expiry = _aware_datetime(delivery_expires_at)
        if normalized_delivery_expiry > normalized_session_expiry:
            raise SchemaV2AnonymousAuthInputError("delivery expiry cannot exceed session expiry")

        params = (
            attempt_id,
            session_id,
            invitation_id,
            invitation_token_hash._value,
            requested_surface.value,
            idempotency_key_hash._value,
            session_token_hash._value,
            normalized_session_expiry,
            delivery_ciphertext._value,
            delivery_key_id,
            delivery_nonce._value,
            normalized_delivery_expiry,
        )
        return self._execute_exact(
            """
            SELECT result_code, attempt_id, session_id, actor_id, tenant_id,
                   project_ids, tenant_roles, project_scopes,
                   delivery_ciphertext, delivery_key_id, delivery_nonce,
                   delivery_expires_at, replay_count, recommended_surface,
                   correlation_id
            FROM public.geno_v2_redeem_auth_invitation(
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            params,
            lambda rows: _parse_redeem_rows(
                rows,
                expected_attempt_id=attempt_id,
                expected_session_id=session_id,
                expected_surface=requested_surface,
                expected_ciphertext=delivery_ciphertext,
                expected_key_id=delivery_key_id,
                expected_nonce=delivery_nonce,
                expected_delivery_expiry=normalized_delivery_expiry,
            ),
        )

    def _execute_exact(
        self,
        statement: str,
        params: tuple[object, ...],
        parser: Callable[[object], _ResultT],
    ) -> _ResultT:
        self._start()
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute("SET LOCAL ROLE geno_v2_runtime")
                cursor.execute("SELECT set_config('app.session_token_hash', '', true)")
                cursor.execute(statement, params)
                result = parser(cursor.fetchall())
        except SchemaV2AnonymousAuthResultError:
            if self._abort_failed_call():
                raise SchemaV2AnonymousAuthRollbackError() from None
            raise SchemaV2AnonymousAuthResultError() from None
        except Exception as exc:
            command_code = _stable_command_error_code(exc)
            if self._abort_failed_call():
                raise SchemaV2AnonymousAuthRollbackError() from None
            if command_code is not None:
                raise SchemaV2AnonymousAuthCommandError(command_code) from None
            raise SchemaV2AnonymousAuthUnitOfWorkError(
                "anonymous_auth_transaction_failed",
                "Schema v2 anonymous auth transaction failed",
            ) from None

        self._state = _AnonymousAuthState.ACTIVE
        try:
            self._connection.commit()
        except Exception:
            try:
                self._connection.rollback()
            except Exception:
                pass
            self._transaction_outcome = "unknown"
            self._finalize(force_discard=True)
            raise SchemaV2AnonymousAuthCommitOutcomeUnknownError() from None

        self._transaction_outcome = "committed"
        self._finalize(force_discard=False)
        return result

    def _start(self) -> None:
        if self._state is not _AnonymousAuthState.NEW:
            raise SchemaV2AnonymousAuthLifecycleError(
                "anonymous auth unit of work can execute only once"
            )
        connection_id = id(self._connection)
        with _ACTIVE_CONNECTION_IDS_LOCK:
            if connection_id in _ACTIVE_CONNECTION_IDS:
                self._state = _AnonymousAuthState.BROKEN
                raise SchemaV2AnonymousAuthLifecycleError(
                    "database connection already has an active Schema v2 unit of work"
                )
            _ACTIVE_CONNECTION_IDS.add(connection_id)
        self._connection_reserved = True
        if not _connection_is_idle(self._connection):
            self._release_connection()
            self._state = _AnonymousAuthState.BROKEN
            raise SchemaV2AnonymousAuthLifecycleError(
                "anonymous auth unit of work requires an idle database connection"
            )
        self._state = _AnonymousAuthState.ACTIVE

    def _abort_failed_call(self) -> bool:
        rollback_failed = False
        try:
            self._connection.rollback()
        except Exception:
            rollback_failed = True
        self._transaction_outcome = "unknown" if rollback_failed else "rolled_back"
        cleanup_failed = not self._reset_session_state()
        should_discard = rollback_failed or cleanup_failed
        if should_discard:
            self._discard_connection()
        self._cleanup_telemetry = SchemaV2SessionCleanupTelemetry(
            status="failed" if cleanup_failed else "succeeded",
            connection_discarded=should_discard,
        )
        self._release_connection()
        self._state = _AnonymousAuthState.BROKEN if should_discard else _AnonymousAuthState.FINISHED
        if cleanup_failed and not rollback_failed:
            raise SchemaV2AnonymousAuthUnitOfWorkError(
                "anonymous_auth_connection_cleanup_failed",
                "Schema v2 anonymous auth connection could not be cleaned",
            ) from None
        return rollback_failed

    def _finalize(self, *, force_discard: bool) -> None:
        cleanup_succeeded = self._reset_session_state()
        should_discard = force_discard or not cleanup_succeeded
        if should_discard:
            self._discard_connection()
        self._cleanup_telemetry = SchemaV2SessionCleanupTelemetry(
            status="succeeded" if cleanup_succeeded else "failed",
            connection_discarded=should_discard,
        )
        self._release_connection()
        self._state = _AnonymousAuthState.BROKEN if should_discard else _AnonymousAuthState.FINISHED

    def _reset_session_state(self) -> bool:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("RESET ALL")
                cursor.execute("RESET ROLE")
            self._connection.commit()
            return _connection_is_idle(self._connection)
        except Exception:
            return False

    def _discard_connection(self) -> None:
        self._connection_reusable = False
        invalidate = getattr(self._connection, "invalidate", None)
        close = getattr(self._connection, "close", None)
        try:
            if callable(invalidate):
                invalidate()
            elif callable(close):
                close()
        except Exception:
            pass

    def _release_connection(self) -> None:
        if not self._connection_reserved:
            return
        with _ACTIVE_CONNECTION_IDS_LOCK:
            _ACTIVE_CONNECTION_IDS.discard(id(self._connection))
        self._connection_reserved = False


def _parse_preflight_rows(
    rows: object,
    *,
    expected_surface: SchemaV2InvitationSurface,
) -> SchemaV2AnonymousAuthPreflightResult:
    row = _strict_row(rows, 10)
    try:
        result_code = SchemaV2PreflightResultCode(row[0])
        compatibility = SchemaV2PreflightResultCode(row[1])
        requested_surface = SchemaV2InvitationSurface(row[2])
    except (TypeError, ValueError):
        raise SchemaV2AnonymousAuthResultError() from None
    if requested_surface is not expected_surface:
        raise SchemaV2AnonymousAuthResultError()
    expected_compatibility = {
        SchemaV2PreflightResultCode.COMPATIBLE: SchemaV2PreflightResultCode.COMPATIBLE,
        SchemaV2PreflightResultCode.SURFACE_MISMATCH: (
            SchemaV2PreflightResultCode.SURFACE_MISMATCH
        ),
        SchemaV2PreflightResultCode.POLICY_STALE: SchemaV2PreflightResultCode.POLICY_STALE,
        SchemaV2PreflightResultCode.INVALID: SchemaV2PreflightResultCode.INVALID,
        SchemaV2PreflightResultCode.RATE_LIMITED: SchemaV2PreflightResultCode.INVALID,
    }[result_code]
    if compatibility is not expected_compatibility:
        raise SchemaV2AnonymousAuthResultError()

    recommended_surface = _optional_surface(row[3])
    invitation_role = row[4]
    if invitation_role is not None and invitation_role not in _INVITATION_ROLES:
        raise SchemaV2AnonymousAuthResultError()
    policy_version = row[5]
    if policy_version is not None and policy_version != AUTH_SURFACE_POLICY_VERSION:
        raise SchemaV2AnonymousAuthResultError()
    invitation_count = _positive_int(row[6])
    source_count = _positive_int(row[7])
    retry_after = _optional_positive_int(row[8])
    correlation_id = _canonical_uuid(row[9])

    if result_code is SchemaV2PreflightResultCode.COMPATIBLE:
        if (
            invitation_role is None
            or policy_version != AUTH_SURFACE_POLICY_VERSION
            or recommended_surface is not requested_surface
            or retry_after is not None
        ):
            raise SchemaV2AnonymousAuthResultError()
    elif result_code is SchemaV2PreflightResultCode.SURFACE_MISMATCH:
        if (
            invitation_role is None
            or policy_version != AUTH_SURFACE_POLICY_VERSION
            or recommended_surface is None
            or recommended_surface is requested_surface
            or retry_after is not None
        ):
            raise SchemaV2AnonymousAuthResultError()
    elif result_code is SchemaV2PreflightResultCode.RATE_LIMITED:
        if (
            invitation_role is not None
            or recommended_surface is not None
            or policy_version is not None
            or retry_after is None
        ):
            raise SchemaV2AnonymousAuthResultError()
    elif (
        invitation_role is not None
        or recommended_surface is not None
        or policy_version is not None
        or retry_after is not None
    ):
        raise SchemaV2AnonymousAuthResultError()

    return SchemaV2AnonymousAuthPreflightResult(
        result_code=result_code,
        compatibility=compatibility,
        requested_surface=requested_surface,
        recommended_surface=recommended_surface,
        invitation_role=invitation_role,
        policy_version=policy_version,
        invitation_request_count=invitation_count,
        source_request_count=source_count,
        retry_after_seconds=retry_after,
        correlation_id=correlation_id,
    )


def _parse_redeem_rows(
    rows: object,
    *,
    expected_attempt_id: UUID,
    expected_session_id: UUID,
    expected_surface: SchemaV2InvitationSurface,
    expected_ciphertext: SchemaV2DeliveryCiphertext,
    expected_key_id: str,
    expected_nonce: SchemaV2DeliveryNonce,
    expected_delivery_expiry: datetime,
) -> SchemaV2AnonymousAuthRedeemResult:
    row = _strict_row(rows, 15)
    try:
        result_code = SchemaV2RedeemResultCode(row[0])
    except (TypeError, ValueError):
        raise SchemaV2AnonymousAuthResultError() from None
    correlation_id = _canonical_uuid(row[14])
    recommended_surface = _optional_surface(row[13])
    delivery_values = row[8:12]

    if result_code in {
        SchemaV2RedeemResultCode.SUCCEEDED,
        SchemaV2RedeemResultCode.REPLAYED,
    }:
        if any(value is None for value in row[1:13]) or recommended_surface is not None:
            raise SchemaV2AnonymousAuthResultError()
        attempt_id = _canonical_uuid(row[1])
        session = _parse_redeem_session(row)
        ciphertext = _ciphertext_from_database(row[8])
        key_id = _delivery_key_id_from_database(row[9])
        nonce = _nonce_from_database(row[10])
        delivery_expiry = _aware_datetime_result(row[11])
        replay_count = _nonnegative_int(row[12])
        if result_code is SchemaV2RedeemResultCode.SUCCEEDED:
            if (
                attempt_id != expected_attempt_id
                or session.session_id != expected_session_id
                or replay_count != 0
                or not hmac.compare_digest(ciphertext.as_bytes(), expected_ciphertext.as_bytes())
                or key_id != expected_key_id
                or not hmac.compare_digest(nonce.as_bytes(), expected_nonce.as_bytes())
                or delivery_expiry != expected_delivery_expiry
            ):
                raise SchemaV2AnonymousAuthResultError()
        elif replay_count not in {1, 2, 3}:
            raise SchemaV2AnonymousAuthResultError()
        return SchemaV2AnonymousAuthRedeemResult(
            result_code=result_code,
            attempt_id=attempt_id,
            session=session,
            delivery_ciphertext=ciphertext,
            delivery_key_id=key_id,
            delivery_nonce=nonce,
            delivery_expires_at=delivery_expiry,
            replay_count=replay_count,
            recommended_surface=None,
            correlation_id=correlation_id,
        )

    if any(value is not None for value in delivery_values):
        raise SchemaV2AnonymousAuthResultError()
    if result_code is SchemaV2RedeemResultCode.SURFACE_MISMATCH:
        if (
            any(value is not None for value in row[1:13])
            or recommended_surface is None
            or recommended_surface is expected_surface
        ):
            raise SchemaV2AnonymousAuthResultError()
        return _empty_redeem_result(result_code, recommended_surface, correlation_id)
    if result_code is SchemaV2RedeemResultCode.INVALID:
        if any(value is not None for value in row[1:14]):
            raise SchemaV2AnonymousAuthResultError()
        return _empty_redeem_result(result_code, None, correlation_id)

    if any(value is not None for value in row[1:14]):
        raise SchemaV2AnonymousAuthResultError()
    return _empty_redeem_result(result_code, None, correlation_id)


def _parse_redeem_session(row: Sequence[object]) -> SchemaV2AnonymousAuthSession:
    session_id = _canonical_uuid(row[2])
    actor_id = _canonical_actor_id(row[3])
    tenant_id = _canonical_uuid(row[4])
    try:
        project_ids = _uuid_tuple(_json_array(row[5]))
        tenant_roles = _string_tuple(_json_array(row[6]), allow_empty=True)
        raw_scopes = _json_array(row[7])
        project_scopes = tuple(_parse_project_scope(value) for value in raw_scopes)
    except SchemaV2SessionAuthorizationError:
        raise SchemaV2AnonymousAuthResultError() from None
    if not project_ids or tuple(scope.project_id for scope in project_scopes) != project_ids:
        raise SchemaV2AnonymousAuthResultError()
    return SchemaV2AnonymousAuthSession(
        session_id=session_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        project_ids=project_ids,
        tenant_roles=tenant_roles,
        project_scopes=project_scopes,
    )


def _empty_redeem_result(
    result_code: SchemaV2RedeemResultCode,
    recommended_surface: SchemaV2InvitationSurface | None,
    correlation_id: UUID,
) -> SchemaV2AnonymousAuthRedeemResult:
    return SchemaV2AnonymousAuthRedeemResult(
        result_code=result_code,
        attempt_id=None,
        session=None,
        delivery_ciphertext=None,
        delivery_key_id=None,
        delivery_nonce=None,
        delivery_expires_at=None,
        replay_count=None,
        recommended_surface=recommended_surface,
        correlation_id=correlation_id,
    )


def _strict_row(rows: object, column_count: int) -> Sequence[object]:
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes, bytearray))
        or len(rows) != 1
    ):
        raise SchemaV2AnonymousAuthResultError()
    row = rows[0]
    if (
        not isinstance(row, Sequence)
        or isinstance(row, (str, bytes, bytearray))
        or len(row) != column_count
    ):
        raise SchemaV2AnonymousAuthResultError()
    return row


def _require_uuid(value: object) -> None:
    if type(value) is not UUID:
        raise SchemaV2AnonymousAuthInputError("resource identifiers must be UUID values")


def _require_exact_type(value: object, expected_type: type[object]) -> None:
    if type(value) is not expected_type:
        raise SchemaV2AnonymousAuthInputError()


def _canonical_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if type(value) is not str:
        raise SchemaV2AnonymousAuthResultError()
    try:
        parsed = UUID(value)
    except ValueError:
        raise SchemaV2AnonymousAuthResultError() from None
    if value != str(parsed):
        raise SchemaV2AnonymousAuthResultError()
    return parsed


def _canonical_actor_id(value: object) -> str:
    if type(value) is not str or not value or value != value.strip().lower():
        raise SchemaV2AnonymousAuthResultError()
    return value


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise SchemaV2AnonymousAuthResultError()
    return value


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise SchemaV2AnonymousAuthResultError()
    return value


def _optional_positive_int(value: object) -> int | None:
    return None if value is None else _positive_int(value)


def _optional_surface(value: object) -> SchemaV2InvitationSurface | None:
    if value is None:
        return None
    try:
        return SchemaV2InvitationSurface(value)
    except (TypeError, ValueError):
        raise SchemaV2AnonymousAuthResultError() from None


def _aware_datetime(value: object) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise SchemaV2AnonymousAuthInputError("auth expiry must be timezone-aware")
    return value.astimezone(UTC)


def _aware_datetime_result(value: object) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise SchemaV2AnonymousAuthResultError()
    return value.astimezone(UTC)


def _database_bytes(value: object) -> bytes:
    if type(value) is bytes:
        return value
    if type(value) is memoryview:
        return value.tobytes()
    raise SchemaV2AnonymousAuthResultError()


def _ciphertext_from_database(value: object) -> SchemaV2DeliveryCiphertext:
    try:
        return protect_delivery_ciphertext(_database_bytes(value))
    except SchemaV2AnonymousAuthInputError:
        raise SchemaV2AnonymousAuthResultError() from None


def _nonce_from_database(value: object) -> SchemaV2DeliveryNonce:
    try:
        return protect_delivery_nonce(_database_bytes(value))
    except SchemaV2AnonymousAuthInputError:
        raise SchemaV2AnonymousAuthResultError() from None


def _delivery_key_id_from_database(value: object) -> str:
    if type(value) is not str or not DELIVERY_KEY_ID_PATTERN.fullmatch(value):
        raise SchemaV2AnonymousAuthResultError()
    return value


def _stable_command_error_code(exc: BaseException) -> str | None:
    sqlstate = getattr(exc, "sqlstate", None)
    expected_message = _STABLE_COMMAND_ERRORS.get(sqlstate)
    if expected_message is None:
        return None
    diagnostic = getattr(exc, "diag", None)
    primary_message = getattr(diagnostic, "message_primary", None)
    return expected_message if primary_message == expected_message else None


__all__ = [
    "SchemaV2AnonymousAuthCommitOutcomeUnknownError",
    "SchemaV2AnonymousAuthCommandError",
    "SchemaV2AnonymousAuthInputError",
    "SchemaV2AnonymousAuthLifecycleError",
    "SchemaV2AnonymousAuthPreflightResult",
    "SchemaV2AnonymousAuthRedeemResult",
    "SchemaV2AnonymousAuthResultError",
    "SchemaV2AnonymousAuthRollbackError",
    "SchemaV2AnonymousAuthSession",
    "SchemaV2AnonymousAuthUnitOfWork",
    "SchemaV2AnonymousAuthUnitOfWorkError",
    "SchemaV2DeliveryCiphertext",
    "SchemaV2DeliveryNonce",
    "SchemaV2IdempotencyKeyHash",
    "SchemaV2InvitationSurface",
    "SchemaV2InvitationTokenHash",
    "SchemaV2PreflightResultCode",
    "SchemaV2RedeemResultCode",
    "SchemaV2SourceIdentityHmac",
    "SchemaV2SourceIdentityHmacKey",
    "build_source_identity_hmac_key",
    "hash_raw_idempotency_key",
    "hash_raw_invitation_token",
    "hmac_source_identity",
    "protect_delivery_ciphertext",
    "protect_delivery_nonce",
]
