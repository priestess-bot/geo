from uuid import uuid4

from geo_api.connector_contracts import CreateConnectorConnectionRequest
from geo_core.connectors.contracts import ConnectorKind
from geo_core.connectors.scope import connector_secret_purpose


def test_connection_request_can_omit_internal_secret_purpose() -> None:
    request = CreateConnectorConnectionRequest.model_validate({
        "definition_id": uuid4(),
        "name": "GSC production property",
        "secret_reference_id": uuid4(),
        "secret_version": 1,
    })

    assert request.secret_purpose is None


def test_connector_kind_has_one_definition_derived_secret_purpose() -> None:
    assert connector_secret_purpose(ConnectorKind.GOOGLE_SEARCH_CONSOLE) == "connector.gsc"
    assert connector_secret_purpose(ConnectorKind.GOOGLE_ANALYTICS_4) == "connector.ga4"
