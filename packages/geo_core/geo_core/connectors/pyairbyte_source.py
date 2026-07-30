"""Pinned PyAirbyte source adapter for GSC and GA4 report streams."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
import hashlib
import importlib
from typing import Protocol

from geo_core.connectors.contracts import (
    ConnectorSyncMode,
    ConnectorSyncPlan,
    SchemaCompatibility,
    canonical_hash,
)
from geo_core.connectors.runtime import ConnectorRuntimeError, ConnectorSourceBatch


PYAIRBYTE_RELEASE = "0.53.2"
GSC_SOURCE = "source-google-search-console"
GSC_CONNECTOR_RELEASE = "2.1.5"
GA4_SOURCE = "source-google-analytics-data-api"
GA4_CONNECTOR_RELEASE = "2.9.43"


class _Dataset(Protocol):
    @property
    def records(self) -> Sequence[object]: ...


class _ReadResult(Protocol):
    def __getitem__(self, stream: str) -> _Dataset: ...


class _RuntimeSource(Protocol):
    def check(self) -> object: ...

    def read(self, **arguments: object) -> _ReadResult: ...

    def get_stream_json_schema(self, stream: str) -> Mapping[str, object]: ...


_SourceFactory = Callable[..., _RuntimeSource]


class PyAirbyteSource:
    """Read selected streams through a fixed connector release.

    ``config`` is deliberately accepted only by the runtime constructor. It is
    resolved from Secret Store after the durable lease is held and never enters
    ConnectorSyncPlan, Job specs, artifacts, or database rows.
    """

    def __init__(
        self,
        *,
        source_name: str,
        connector_release: str,
        config: Mapping[str, object],
        streams: Sequence[str],
        cursor_fields: Sequence[str],
        watermark_field: str | None,
        source_factory: _SourceFactory | None = None,
    ) -> None:
        if source_name not in {GSC_SOURCE, GA4_SOURCE}:
            raise ConnectorRuntimeError("PyAirbyte source is not approved")
        if not connector_release.strip() or connector_release == "latest":
            raise ConnectorRuntimeError("PyAirbyte connector release must be pinned")
        if not streams or any(not stream.strip() for stream in streams):
            raise ConnectorRuntimeError("PyAirbyte streams are required")
        if not cursor_fields:
            raise ConnectorRuntimeError("PyAirbyte cursor fields are required")
        self._source_name = source_name
        self._connector_release = connector_release
        self._config = dict(config)
        self._streams = tuple(streams)
        self._cursor_fields = tuple(cursor_fields)
        self._watermark_field = watermark_field
        self._source_factory = source_factory

    def check_connection(self) -> None:
        factory = self._source_factory or _load_get_source()
        try:
            source = factory(
                self._source_name,
                config=dict(self._config),
                streams=list(self._streams),
                version=self._connector_release,
                install_if_missing=True,
            )
            outcome = source.check()
        except Exception as error:
            raise ConnectorRuntimeError(
                f"PyAirbyte {self._source_name}@{self._connector_release} check failed: "
                f"{type(error).__name__}"
            ) from error
        status = getattr(outcome, "status", None)
        normalized = str(getattr(status, "value", status or "succeeded")).lower()
        if normalized not in {"succeeded", "success", "ok"}:
            raise ConnectorRuntimeError(
                f"PyAirbyte {self._source_name}@{self._connector_release} check failed"
            )

    def read(self, plan: ConnectorSyncPlan) -> ConnectorSourceBatch:
        factory = self._source_factory or _load_get_source()
        try:
            source = factory(
                self._source_name,
                config=dict(self._config),
                streams=list(self._streams),
                version=self._connector_release,
                install_if_missing=True,
            )
            read_result = source.read(
                streams=list(self._streams),
                force_full_refresh=plan.mode is not ConnectorSyncMode.INCREMENTAL,
            )
            records = _records(read_result, self._streams)
            schemas = {
                stream: source.get_stream_json_schema(stream) for stream in self._streams
            }
        except Exception as error:
            raise ConnectorRuntimeError(
                f"PyAirbyte {self._source_name}@{self._connector_release} read failed: "
                f"{type(error).__name__}"
            ) from error
        cursor = _max_cursor(records, self._cursor_fields)
        watermark = _max_watermark(records, self._watermark_field)
        schema_document = {
            "source": self._source_name,
            "connector_release": self._connector_release,
            "streams": schemas,
        }
        fingerprint = canonical_hash(schema_document)
        return ConnectorSourceBatch(
            records=tuple(records),
            cursor_state={"fields": list(self._cursor_fields), "value": list(cursor)},
            watermark=watermark,
            schema_document=schema_document,
            source_fingerprint=fingerprint,
            compatibility=SchemaCompatibility.INITIAL,
            schema_diff={},
        )


def gsc_source(
    *, config: Mapping[str, object], source_factory: _SourceFactory | None = None
) -> PyAirbyteSource:
    return PyAirbyteSource(
        source_name=GSC_SOURCE,
        connector_release=GSC_CONNECTOR_RELEASE,
        config=config,
        streams=("search_analytics_by_date", "search_analytics_by_page"),
        cursor_fields=("date",),
        watermark_field="date",
        source_factory=source_factory,
    )


def ga4_source(
    *, config: Mapping[str, object], source_factory: _SourceFactory | None = None
) -> PyAirbyteSource:
    return PyAirbyteSource(
        source_name=GA4_SOURCE,
        connector_release=GA4_CONNECTOR_RELEASE,
        config=config,
        streams=("reports",),
        cursor_fields=("date",),
        watermark_field="date",
        source_factory=source_factory,
    )


def _load_get_source() -> _SourceFactory:
    try:
        module = importlib.import_module("airbyte")
    except ImportError as error:
        raise ConnectorRuntimeError(
            "PyAirbyte runtime is unavailable; install the connectors extra"
        ) from error
    factory = getattr(module, "get_source", None)
    if not callable(factory):
        raise ConnectorRuntimeError("PyAirbyte get_source is unavailable")
    return factory


def _records(read_result: _ReadResult, streams: Sequence[str]) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for stream in streams:
        dataset = read_result[stream]
        for record in dataset.records:
            value = getattr(record, "data", record)
            if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
                raise ConnectorRuntimeError("PyAirbyte returned a non-object record")
            records.append({"_geo_stream": stream, **dict(value)})
    return records


def _max_cursor(
    records: Sequence[Mapping[str, object]], fields: Sequence[str]
) -> tuple[str, ...]:
    values = [tuple(str(record.get(field, "")) for field in fields) for record in records]
    return max(values, default=tuple("" for _ in fields))


def _max_watermark(
    records: Sequence[Mapping[str, object]], field: str | None
) -> datetime | None:
    if field is None:
        return None
    values: list[datetime] = []
    for record in records:
        raw = record.get(field)
        if raw is None:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError as error:
            raise ConnectorRuntimeError("PyAirbyte watermark is not ISO-8601") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ConnectorRuntimeError("PyAirbyte watermark lacks a timezone")
        values.append(parsed)
    return max(values, default=None)


def release_fingerprint(source_name: str, connector_release: str) -> str:
    return hashlib.sha256(
        f"pyairbyte:{PYAIRBYTE_RELEASE}:{source_name}:{connector_release}".encode()
    ).hexdigest()


__all__ = [
    "GA4_CONNECTOR_RELEASE",
    "GA4_SOURCE",
    "GSC_CONNECTOR_RELEASE",
    "GSC_SOURCE",
    "PYAIRBYTE_RELEASE",
    "PyAirbyteSource",
    "ga4_source",
    "gsc_source",
    "release_fingerprint",
]
