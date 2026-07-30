"""Closed-world mapping from approved Connector releases to PyAirbyte sources."""

from __future__ import annotations

from collections.abc import Mapping

from geo_core.connectors.contracts import ConnectorKind
from geo_core.connectors.pyairbyte_source import (
    GA4_CONNECTOR_RELEASE,
    GSC_CONNECTOR_RELEASE,
    ga4_source,
    gsc_source,
)
from geo_core.connectors.runtime import ConnectorSource
from geo_core.connectors.worker import ConnectorExecutionState, ConnectorWorkerError


def build_pyairbyte_source(
    state: ConnectorExecutionState, credential: Mapping[str, object]
) -> ConnectorSource:
    if state.connector_kind is ConnectorKind.GOOGLE_SEARCH_CONSOLE:
        expected = f"source-google-search-console:{GSC_CONNECTOR_RELEASE}"
        if state.plan.adapter_release != expected:
            raise ConnectorWorkerError("GSC adapter release differs from the approved pin")
        expected_streams = {"search_analytics_by_date", "search_analytics_by_page"}
        if set(state.streams) != expected_streams:
            raise ConnectorWorkerError("GSC Scope streams differ from the approved contract")
        return gsc_source(config=credential)
    if state.connector_kind is ConnectorKind.GOOGLE_ANALYTICS_4:
        expected = f"source-google-analytics-data-api:{GA4_CONNECTOR_RELEASE}"
        if state.plan.adapter_release != expected:
            raise ConnectorWorkerError("GA4 adapter release differs from the approved pin")
        if state.streams != ("reports",):
            raise ConnectorWorkerError("GA4 Scope streams differ from the approved contract")
        return ga4_source(config=credential)
    raise ConnectorWorkerError("Official report imports use the dedicated import runtime")


def build_pyairbyte_connection_test_source(
    *, connector_kind: ConnectorKind, adapter_release: str,
    credential: Mapping[str, object]
) -> ConnectorSource:
    if connector_kind is ConnectorKind.GOOGLE_SEARCH_CONSOLE:
        expected = f"source-google-search-console:{GSC_CONNECTOR_RELEASE}"
        if adapter_release != expected:
            raise ConnectorWorkerError("GSC adapter release differs from the approved pin")
        return gsc_source(config=credential)
    if connector_kind is ConnectorKind.GOOGLE_ANALYTICS_4:
        expected = f"source-google-analytics-data-api:{GA4_CONNECTOR_RELEASE}"
        if adapter_release != expected:
            raise ConnectorWorkerError("GA4 adapter release differs from the approved pin")
        return ga4_source(config=credential)
    raise ConnectorWorkerError("This Connector kind does not support a connection test")


__all__ = ["build_pyairbyte_connection_test_source", "build_pyairbyte_source"]
