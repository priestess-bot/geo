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
from geo_core.connectors.scope import ConnectorScopeError, scoped_runtime_config
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
        try:
            config = scoped_runtime_config(
                kind=state.connector_kind,
                credential=credential,
                source_locator=state.source_locator,
                streams=state.streams,
                report_spec=state.report_spec,
                date_policy=state.date_policy,
            )
        except ConnectorScopeError as error:
            raise ConnectorWorkerError(str(error)) from error
        return gsc_source(config=config)
    if state.connector_kind is ConnectorKind.GOOGLE_ANALYTICS_4:
        expected = f"source-google-analytics-data-api:{GA4_CONNECTOR_RELEASE}"
        if state.plan.adapter_release != expected:
            raise ConnectorWorkerError("GA4 adapter release differs from the approved pin")
        if state.streams != ("reports",):
            raise ConnectorWorkerError("GA4 Scope streams differ from the approved contract")
        try:
            config = scoped_runtime_config(
                kind=state.connector_kind,
                credential=credential,
                source_locator=state.source_locator,
                streams=state.streams,
                report_spec=state.report_spec,
                date_policy=state.date_policy,
            )
        except ConnectorScopeError as error:
            raise ConnectorWorkerError(str(error)) from error
        return ga4_source(config=config)
    raise ConnectorWorkerError("Official report imports use the dedicated import runtime")


def build_pyairbyte_connection_test_source(
    *, connector_kind: ConnectorKind, adapter_release: str,
    credential: Mapping[str, object], source_locator: str,
    streams: tuple[str, ...] | list[str], report_spec: Mapping[str, object],
    date_policy: Mapping[str, object]
) -> ConnectorSource:
    try:
        config = scoped_runtime_config(
            kind=connector_kind,
            credential=credential,
            source_locator=source_locator,
            streams=streams,
            report_spec=report_spec,
            date_policy=date_policy,
        )
    except ConnectorScopeError as error:
        raise ConnectorWorkerError(str(error)) from error
    if connector_kind is ConnectorKind.GOOGLE_SEARCH_CONSOLE:
        expected = f"source-google-search-console:{GSC_CONNECTOR_RELEASE}"
        if adapter_release != expected:
            raise ConnectorWorkerError("GSC adapter release differs from the approved pin")
        return gsc_source(config=config)
    if connector_kind is ConnectorKind.GOOGLE_ANALYTICS_4:
        expected = f"source-google-analytics-data-api:{GA4_CONNECTOR_RELEASE}"
        if adapter_release != expected:
            raise ConnectorWorkerError("GA4 adapter release differs from the approved pin")
        return ga4_source(config=config)
    raise ConnectorWorkerError("This Connector kind does not support a connection test")


__all__ = ["build_pyairbyte_connection_test_source", "build_pyairbyte_source"]
