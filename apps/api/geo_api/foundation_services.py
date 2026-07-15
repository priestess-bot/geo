"""Transport adapter connecting stable API routes to access application services."""

from __future__ import annotations

from dataclasses import dataclass
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


class FoundationServices(Protocol):
    def authenticate(self, authentication: AuthenticationInput) -> AccessPrincipal: ...

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


class UnavailableFoundationServices:
    """Fail-closed service used when database or authentication is not configured."""

    _MESSAGE = "The access application service is not configured."

    def _unavailable(self) -> NoReturn:
        raise FoundationServiceUnavailable(self._MESSAGE)

    def current_identity(self, authentication: AuthenticationInput) -> AuthIdentity:
        del authentication
        self._unavailable()

    def authenticate(self, authentication: AuthenticationInput) -> AccessPrincipal:
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
        principal = self._authenticate(authentication)
        return AuthIdentity(
            actor_id=principal.actor_id,
            tenant_id=principal.tenant_id,
            project_ids=list(principal.project_ids),
            roles=list(principal.roles),
        )

    def authenticate(self, authentication: AuthenticationInput) -> AccessPrincipal:
        """Authenticate once for domain routers that enforce project command roles."""
        return self._authenticate(authentication)

    def logout(self, authentication: AuthenticationInput) -> None:
        self._access.logout(self._authenticate(authentication))

    def list_internal_projects(
        self, authentication: AuthenticationInput, *, limit: int, offset: int
    ) -> OffsetPage[ProjectSummary]:
        principal = self._authenticate(authentication)
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
        principal = self._authenticate(authentication)
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
        page = self._access.list_jobs(
            self._authenticate(authentication), limit=limit, offset=offset
        )
        return OffsetPage[JobStatus](
            items=[_job(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    def get_job(self, authentication: AuthenticationInput, *, job_id: UUID) -> JobStatus | None:
        job = self._access.get_job(self._authenticate(authentication), job_id=job_id)
        return _job(job) if job else None

    def request_engineering_sync(self, payload: EngineeringSyncRequest) -> JobAccepted:
        del payload
        raise FoundationServiceUnavailable(
            "The engineering synchronization service is not connected."
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

        access = AccessApplicationService(PsycopgAccessUnitOfWorkFactory(database_url))
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
        result_details=item.result_details,
    )
