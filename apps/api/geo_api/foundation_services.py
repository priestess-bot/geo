"""Application-facing service ports for the API foundation.

Domain slices replace these unavailable defaults as they are migrated. Keeping
the ports here prevents transport code from reaching into repositories, scripts,
or worker implementation details.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from geo_api.contracts import (
    AuthIdentity,
    EngineeringSyncRequest,
    JobAccepted,
    JobStatus,
    OffsetPage,
    ProjectSummary,
)


class FoundationServiceUnavailable(RuntimeError):
    """Raised when a domain adapter has not been connected to the new API."""


class FoundationServices(Protocol):
    def current_identity(self, *, authorization: str | None) -> AuthIdentity: ...

    def logout(self, *, authorization: str | None) -> None: ...

    def list_projects(self, *, limit: int, offset: int) -> OffsetPage[ProjectSummary]: ...

    def list_jobs(self, *, limit: int, offset: int) -> OffsetPage[JobStatus]: ...

    def get_job(self, *, job_id: UUID) -> JobStatus | None: ...

    def request_engineering_sync(self, payload: EngineeringSyncRequest) -> JobAccepted: ...


class UnavailableFoundationServices:
    """Fail-closed defaults used until each application service is migrated."""

    _MESSAGE = "The application service for this operation is not connected."

    def current_identity(self, *, authorization: str | None) -> AuthIdentity:
        del authorization
        raise FoundationServiceUnavailable(self._MESSAGE)

    def logout(self, *, authorization: str | None) -> None:
        del authorization
        raise FoundationServiceUnavailable(self._MESSAGE)

    def list_projects(self, *, limit: int, offset: int) -> OffsetPage[ProjectSummary]:
        del limit, offset
        raise FoundationServiceUnavailable(self._MESSAGE)

    def list_jobs(self, *, limit: int, offset: int) -> OffsetPage[JobStatus]:
        del limit, offset
        raise FoundationServiceUnavailable(self._MESSAGE)

    def get_job(self, *, job_id: UUID) -> JobStatus | None:
        del job_id
        raise FoundationServiceUnavailable(self._MESSAGE)

    def request_engineering_sync(self, payload: EngineeringSyncRequest) -> JobAccepted:
        del payload
        raise FoundationServiceUnavailable(self._MESSAGE)
