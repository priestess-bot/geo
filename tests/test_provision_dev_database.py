from uuid import UUID

import pytest

from scripts import provision_dev_database


WORKER_ID = UUID("40000000-0000-4000-8000-000000000004")


class _Cursor:
    def __init__(self, result: tuple[object, ...] | None) -> None:
        self.result = result
        self.statement = ""
        self.parameters: tuple[object, ...] = ()

    def execute(self, statement: str, parameters: tuple[object, ...]) -> "_Cursor":
        self.statement = statement
        self.parameters = parameters
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        return self.result


def test_optional_worker_identity_is_strict_but_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(provision_dev_database.MODEL_GATEWAY_WORKER_IDENTITY_ENV, raising=False)
    assert (
        provision_dev_database.optional_uuid(
            provision_dev_database.MODEL_GATEWAY_WORKER_IDENTITY_ENV
        )
        is None
    )

    monkeypatch.setenv(provision_dev_database.MODEL_GATEWAY_WORKER_IDENTITY_ENV, "not-a-uuid")
    with pytest.raises(RuntimeError, match="must be a UUID"):
        provision_dev_database.optional_uuid(
            provision_dev_database.MODEL_GATEWAY_WORKER_IDENTITY_ENV
        )


def test_worker_identity_uses_the_governed_idempotent_provisioning_rpc() -> None:
    cursor = _Cursor((WORKER_ID,))

    provision_dev_database.provision_model_gateway_worker(  # type: ignore[arg-type]
        cursor, identity_id=WORKER_ID
    )

    assert "geo_provision_service_identity" in cursor.statement
    assert cursor.parameters == (WORKER_ID,)
