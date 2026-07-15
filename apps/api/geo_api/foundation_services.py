"""Transport adapter connecting stable API routes to access application services."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import os
from pathlib import Path
from typing import Literal, NoReturn, Protocol
from uuid import UUID

from geo_api.contracts import (
    AuthIdentity,
    CustomerProjectSummary,
    EngineeringSyncRequest,
    JobAccepted,
    JobState,
    JobStatus,
    OffsetPage,
    ProjectSummary,
)
from geo_api.access_contracts import (
    CreateInvitationRequest,
    CreatedInvitationResponse,
    InvitationCredentialRequest,
    InvitationListResponse,
    InvitationPreflightResponse,
    InvitationSummary,
)
from geo_api.oidc import (
    OidcAuthenticationError,
    OidcConfigurationError,
    OidcTokenVerifier,
    OidcVerifierSettings,
)
from geo_core.access.models import (
    AccessPrincipal,
    AuthenticationRequired,
    Page,
    ProjectRecord,
    RedeemedSession,
)
from geo_core.access.service import AccessApplicationService


Surface = Literal["internal", "customer"]


class FoundationServiceUnavailable(RuntimeError):
    """Raised when required persistence or trusted auth configuration is absent."""


@dataclass(frozen=True)
class AuthenticationInput:
    authorization: str | None = None
    customer_session: str | None = None
    development_actor_id: str | None = None
    development_tenant_id: str | None = None
    csrf_cookie: str | None = None
    csrf_header: str | None = None


class FoundationServices(Protocol):
    def authenticate(self, authentication: AuthenticationInput) -> AccessPrincipal: ...

    def require_project_role(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal: ...

    def current_identity(self, authentication: AuthenticationInput) -> AuthIdentity: ...

    def logout(self, authentication: AuthenticationInput) -> None: ...

    def list_internal_projects(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[ProjectSummary]: ...

    def list_customer_projects(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[CustomerProjectSummary]: ...

    def list_jobs(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[JobStatus]: ...

    def get_job(self, authentication: AuthenticationInput, *, job_id: UUID) -> JobStatus | None: ...

    def request_engineering_sync(self, payload: EngineeringSyncRequest) -> JobAccepted: ...

    def identity_contract(self, principal: AccessPrincipal) -> AuthIdentity: ...

    def create_invitation(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        payload: CreateInvitationRequest,
        idempotency_key: str,
    ) -> CreatedInvitationResponse: ...

    def list_invitations(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> InvitationListResponse: ...

    def revoke_invitation(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        invitation_id: UUID,
    ) -> None: ...

    def preflight_invitation(
        self, payload: InvitationCredentialRequest
    ) -> InvitationPreflightResponse: ...

    def redeem_invitation(
        self, payload: InvitationCredentialRequest, *, idempotency_key: str
    ) -> RedeemedSession: ...


class UnavailableFoundationServices:
    """Fail-closed service used when database or authentication is not configured."""

    _MESSAGE = "The access application service is not configured."

    def _unavailable(self) -> NoReturn:
        raise FoundationServiceUnavailable(self._MESSAGE)

    def authenticate(self, authentication: AuthenticationInput) -> AccessPrincipal:
        del authentication
        self._unavailable()

    def require_project_role(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        del authentication, project_id, allowed_roles
        self._unavailable()

    def current_identity(self, authentication: AuthenticationInput) -> AuthIdentity:
        del authentication
        self._unavailable()

    def logout(self, authentication: AuthenticationInput) -> None:
        del authentication
        self._unavailable()

    def list_internal_projects(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[ProjectSummary]:
        del authentication, limit, offset
        self._unavailable()

    def list_customer_projects(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[CustomerProjectSummary]:
        del authentication, limit, offset
        self._unavailable()

    def list_jobs(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[JobStatus]:
        del authentication, limit, offset
        self._unavailable()

    def get_job(self, authentication: AuthenticationInput, *, job_id: UUID) -> JobStatus | None:
        del authentication, job_id
        self._unavailable()

    def request_engineering_sync(self, payload: EngineeringSyncRequest) -> JobAccepted:
        del payload
        self._unavailable()

    def identity_contract(self, principal: AccessPrincipal) -> AuthIdentity:
        del principal
        self._unavailable()

    def create_invitation(self, *args: object, **kwargs: object) -> CreatedInvitationResponse:
        del args, kwargs
        self._unavailable()

    def list_invitations(self, *args: object, **kwargs: object) -> InvitationListResponse:
        del args, kwargs
        self._unavailable()

    def revoke_invitation(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self._unavailable()

    def preflight_invitation(
        self, payload: InvitationCredentialRequest
    ) -> InvitationPreflightResponse:
        del payload
        self._unavailable()

    def redeem_invitation(
        self, payload: InvitationCredentialRequest, *, idempotency_key: str
    ) -> RedeemedSession:
        del payload, idempotency_key
        self._unavailable()


class ConnectedFoundationServices:
    def __init__(
        self,
        access: AccessApplicationService,
        *,
        surface: Surface,
        auth_mode: str,
        oidc_verifier: OidcTokenVerifier | None = None,
    ) -> None:
        self._access = access
        self._surface = surface
        self._auth_mode = auth_mode
        self._oidc_verifier = oidc_verifier

    def current_identity(self, authentication: AuthenticationInput) -> AuthIdentity:
        principal = self.authenticate(authentication)
        return self.identity_contract(principal)

    def identity_contract(self, principal: AccessPrincipal) -> AuthIdentity:
        return AuthIdentity(
            actor_id=principal.actor_id,
            tenant_id=principal.tenant_id,
            project_ids=list(principal.project_ids),
            roles=list(principal.roles),
        )

    def logout(self, authentication: AuthenticationInput) -> None:
        if self._surface == "customer":
            csrf_cookie = authentication.csrf_cookie or ""
            csrf_header = authentication.csrf_header or ""
            csrf_proof = (
                csrf_header if csrf_cookie and hmac.compare_digest(csrf_cookie, csrf_header) else ""
            )
            self._access.logout_customer_session(
                raw_token=authentication.customer_session or "",
                csrf_token=csrf_proof,
            )
            return
        self._access.logout(self.authenticate(authentication))

    def authenticate(self, authentication: AuthenticationInput) -> AccessPrincipal:
        return self._authenticate(authentication)

    def require_project_role(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        principal = self.authenticate(authentication)
        self._access.require_project_role(
            principal, project_id=project_id, allowed_roles=allowed_roles
        )
        return principal

    def list_internal_projects(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[ProjectSummary]:
        principal = self.authenticate(authentication)
        page = self._access.list_projects(principal, limit=limit, offset=offset)
        return OffsetPage[ProjectSummary](
            items=[_internal_project(item) for item in _projects(page)],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    def list_customer_projects(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[CustomerProjectSummary]:
        principal = self.authenticate(authentication)
        page = self._access.list_projects(principal, limit=limit, offset=offset)
        return OffsetPage[CustomerProjectSummary](
            items=[
                CustomerProjectSummary(
                    project_id=item.id,
                    display_name=item.name,
                    market_code=item.market_code or "UNSET",
                    status=item.status,
                )
                for item in _projects(page)
            ],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    def list_jobs(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[JobStatus]:
        page = self._access.list_jobs(self.authenticate(authentication), limit=limit, offset=offset)
        return OffsetPage[JobStatus](
            items=[_job(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    def get_job(self, authentication: AuthenticationInput, *, job_id: UUID) -> JobStatus | None:
        job = self._access.get_job(self.authenticate(authentication), job_id=job_id)
        return _job(job) if job else None

    def request_engineering_sync(self, payload: EngineeringSyncRequest) -> JobAccepted:
        del payload
        raise FoundationServiceUnavailable(
            "The engineering synchronization service is not connected."
        )

    def create_invitation(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        payload: CreateInvitationRequest,
        idempotency_key: str,
    ) -> CreatedInvitationResponse:
        created = self._access.create_invitation(
            self.authenticate(authentication),
            project_id=project_id,
            email=payload.email,
            role=payload.role,
            target_surface=payload.target_surface,
            expires_in_hours=payload.expires_in_hours,
            idempotency_key=idempotency_key,
        )
        return CreatedInvitationResponse(
            invitation=_invitation_summary(created.invitation),
            invite_token=created.invite_token,
            replayed=created.replayed,
        )

    def list_invitations(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        limit: int,
        offset: int,
    ) -> InvitationListResponse:
        page = self._access.list_invitations(
            self.authenticate(authentication),
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        return InvitationListResponse(
            items=[_invitation_summary(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    def revoke_invitation(
        self,
        authentication: AuthenticationInput,
        *,
        project_id: UUID,
        invitation_id: UUID,
    ) -> None:
        self._access.revoke_invitation(
            self.authenticate(authentication),
            project_id=project_id,
            invitation_id=invitation_id,
        )

    def preflight_invitation(
        self, payload: InvitationCredentialRequest
    ) -> InvitationPreflightResponse:
        result = self._access.preflight_invitation(
            invitation_id=payload.invitation_id,
            invite_token=payload.invite_token,
            requested_surface=payload.requested_surface,
        )
        return InvitationPreflightResponse(
            compatibility=result.compatibility,
            requested_surface=result.requested_surface,
            recommended_surface=result.recommended_surface,
            invitation_role=result.invitation_role,
        )

    def redeem_invitation(
        self, payload: InvitationCredentialRequest, *, idempotency_key: str
    ) -> RedeemedSession:
        return self._access.redeem_invitation(
            invitation_id=payload.invitation_id,
            invite_token=payload.invite_token,
            requested_surface=payload.requested_surface,
            idempotency_key=idempotency_key,
        )

    def _authenticate(self, authentication: AuthenticationInput) -> AccessPrincipal:
        if self._surface == "customer":
            return self._access.authenticate_customer_session(
                raw_token=authentication.customer_session or ""
            )
        if self._auth_mode == "development":
            try:
                identity_id = UUID(authentication.development_actor_id or "")
                tenant_id = UUID(authentication.development_tenant_id or "")
            except ValueError as error:
                raise AuthenticationRequired(
                    "Development authentication headers are required."
                ) from error
            return self._access.authenticate_development(
                identity_id=identity_id, tenant_id=tenant_id
            )
        token = _bearer_token(authentication.authorization)
        if self._oidc_verifier is None:
            raise FoundationServiceUnavailable("OIDC authentication is not configured.")
        try:
            external = self._oidc_verifier.verify(token)
        except OidcAuthenticationError as error:
            raise AuthenticationRequired("The bearer token is invalid.") from error
        except OidcConfigurationError as error:
            raise FoundationServiceUnavailable("OIDC authentication is unavailable.") from error
        return self._access.authenticate_external(external)


def services_from_environment(*, surface: Surface) -> FoundationServices:
    """Build the access slice or return a deterministic fail-closed adapter."""
    try:
        database_url = _secret_setting("GEO_DATABASE_URL")
        if not database_url:
            return UnavailableFoundationServices()
        from geo_core.access.postgres import PsycopgAccessUnitOfWorkFactory

        access = AccessApplicationService(
            PsycopgAccessUnitOfWorkFactory(database_url),
            token_secret=_secret_setting("GEO_AUTH_TOKEN_SECRET"),
        )
        if surface == "customer":
            return ConnectedFoundationServices(access, surface=surface, auth_mode="session")
        auth_mode = os.getenv("GEO_AUTH_MODE", "oidc").strip().lower()
        if auth_mode == "development":
            deployment = os.getenv("GEO_DEPLOYMENT_ENVIRONMENT", "development").strip().lower()
            if deployment == "production":
                return UnavailableFoundationServices()
            return ConnectedFoundationServices(access, surface=surface, auth_mode=auth_mode)
        if auth_mode != "oidc":
            return UnavailableFoundationServices()
        settings = OidcVerifierSettings(
            discovery_url=os.getenv("GEO_OIDC_DISCOVERY_URL", "").strip(),
            issuer=os.getenv("GEO_JWT_ISSUER", "").strip(),
            audience=os.getenv("GEO_JWT_AUDIENCE", "").strip(),
            tenant_claim=os.getenv("GEO_OIDC_TENANT_CLAIM", "tenant_id").strip(),
        )
        return ConnectedFoundationServices(
            access,
            surface=surface,
            auth_mode=auth_mode,
            oidc_verifier=OidcTokenVerifier(settings),
        )
    except (ImportError, OSError, ValueError, OidcConfigurationError):
        return UnavailableFoundationServices()


def _secret_setting(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct


def _bearer_token(authorization: str | None) -> str:
    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationRequired("A bearer token is required.")
    return token.strip()


def _projects(page: Page) -> tuple[ProjectRecord, ...]:
    if not all(isinstance(item, ProjectRecord) for item in page.items):
        raise RuntimeError("Project application service returned an invalid page.")
    return tuple(item for item in page.items if isinstance(item, ProjectRecord))


def _internal_project(item: ProjectRecord) -> ProjectSummary:
    return ProjectSummary(id=item.id, key=str(item.id), name=item.name, role=item.role)


def _job(item: object) -> JobStatus:
    from geo_core.access.models import JobRecord

    if not isinstance(item, JobRecord):
        raise RuntimeError("Job application service returned an invalid record.")
    return JobStatus(
        id=item.id,
        kind=item.kind,
        status=JobState(item.status),
        created_at=item.created_at,
        updated_at=item.updated_at,
        result_ref=item.result_ref,
        error_code=item.error_code,
    )


def _invitation_summary(item: object) -> InvitationSummary:
    from geo_core.access.models import InvitationRecord

    if not isinstance(item, InvitationRecord):
        raise RuntimeError("Access application service returned an invalid invitation.")
    return InvitationSummary(
        id=item.id,
        project_id=item.project_id,
        email=item.email,
        role=item.role,
        target_surface=item.target_surface,
        token_hint=item.token_hint,
        status=item.status,
        expires_at=item.expires_at,
        created_at=item.created_at,
    )
