"""Shared invocation and problem mapping for Synthetic Lab route modules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, TypeVar, cast

from fastapi import Header, Query, Request

from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.synthetic_lab_runtime import SyntheticLabApi, SyntheticLabApiNotFound
from geo_core.synthetic_lab.domain import SyntheticLabContractError, SyntheticLabScopeError
from geo_core.synthetic_lab.execution_contracts import (
    SyntheticExecutionError,
    SyntheticExecutionStale,
)
from geo_core.synthetic_lab.ports import (
    SyntheticLabIdempotencyConflict,
    SyntheticLabJobOwnershipLost,
    SyntheticLabNotFound,
    SyntheticLabPermissionDenied,
    SyntheticLabPersistenceError,
    SyntheticLabStaleInput,
    SyntheticLabVersionConflict,
)


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=256)]
LimitQuery = Annotated[int, Query(ge=1, le=200)]
OffsetQuery = Annotated[int, Query(ge=0)]
_ResultT = TypeVar("_ResultT")


def run(request: Request, method: str, principal: object, **values: object) -> object:
    operation = cast(Callable[..., object], getattr(_api(request), method))
    return _call(lambda: operation(principal, **values))


def run_write(
    request: Request,
    method: str,
    principal: object,
    idempotency_key: str,
    **values: object,
) -> object:
    return run(
        request,
        method,
        principal,
        idempotency_key=idempotency_key,
        **values,
    )


def _api(request: Request) -> SyntheticLabApi:
    application = getattr(request.app.state, "synthetic_lab_api", None)
    if application is None:
        raise FoundationServiceUnavailable(
            "Synthetic Lab persistence is unavailable until its PostgreSQL builder is installed."
        )
    return cast(SyntheticLabApi, application)


def _call(operation: Callable[[], _ResultT]) -> _ResultT:
    try:
        return operation()
    except (SyntheticLabApiNotFound, SyntheticLabNotFound) as error:
        raise _problem(404, "Not Found", error, "not-found") from error
    except (SyntheticLabPermissionDenied, SyntheticLabScopeError) as error:
        raise _problem(403, "Forbidden", error, "forbidden") from error
    except SyntheticExecutionStale as error:
        raise _problem(409, "Conflict", error, "stale-execution-input") from error
    except SyntheticExecutionError as error:
        raise _problem(422, "Unprocessable Content", error, "execution-contract") from error
    except SyntheticLabContractError as error:
        raise _problem(422, "Unprocessable Content", error, "contract") from error
    except (
        SyntheticLabIdempotencyConflict,
        SyntheticLabVersionConflict,
        SyntheticLabStaleInput,
        SyntheticLabJobOwnershipLost,
    ) as error:
        raise _problem(409, "Conflict", error, "conflict") from error
    except SyntheticLabPersistenceError as error:
        raise _problem(503, "Service Unavailable", error, "persistence-unavailable") from error


def _problem(status_code: int, title: str, error: Exception, suffix: str) -> ApiProblem:
    return ApiProblem(
        status=status_code,
        title=title,
        detail=str(error),
        type_uri=f"urn:geo:problem:synthetic-lab-{suffix}",
        headers={"Retry-After": "30"} if status_code == 503 else None,
    )


__all__ = [
    "AuthorizationHeader",
    "IdempotencyHeader",
    "LimitQuery",
    "OffsetQuery",
    "run",
    "run_write",
]
