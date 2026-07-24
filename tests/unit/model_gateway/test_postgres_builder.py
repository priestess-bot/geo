from geo_core.model_gateway.postgres import (
    PostgresModelCallUnitOfWorkFactory,
    PostgresModelGatewayPersistence,
    build_model_gateway_persistence,
)


def test_model_gateway_persistence_builder_fails_closed_without_database() -> None:
    assert build_model_gateway_persistence(None) is None
    assert build_model_gateway_persistence("") is None
    assert build_model_gateway_persistence("   ") is None


def test_model_gateway_persistence_builder_exposes_only_infrastructure() -> None:
    persistence = build_model_gateway_persistence("postgresql://example.invalid/geo")

    assert isinstance(persistence, PostgresModelGatewayPersistence)
    assert isinstance(persistence.uow_factory, PostgresModelCallUnitOfWorkFactory)
    assert not hasattr(persistence, "provider_client")
    assert not hasattr(persistence, "credentials")
