from __future__ import annotations

from types import SimpleNamespace

import pytest

from geo_api import workflow_c_postgres


def test_builder_composes_all_workflow_c_verticals_as_durable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE", "/run/secrets/keyring")
    monkeypatch.setattr(
        workflow_c_postgres,
        "build_workflow_c_artifact_api_writer_composition",
        lambda **_values: SimpleNamespace(writer=object()),
    )
    monkeypatch.setattr(
        workflow_c_postgres,
        "build_postgres_workflow_c_sampling_runtime",
        lambda **_values: SimpleNamespace(persistence="durable"),
    )
    monkeypatch.setattr(
        workflow_c_postgres,
        "PostgresWorkflowCAnalysisRuntime",
        lambda **_values: SimpleNamespace(persistence="durable"),
    )
    monkeypatch.setattr(
        workflow_c_postgres,
        "PostgresWorkflowCAlertControl",
        lambda **_values: SimpleNamespace(persistence="durable"),
    )

    api = workflow_c_postgres.build_workflow_c_api(
        database_url="postgresql://geo_app:secret@db/geo"
    )

    assert api.persistence == "durable"
    assert api.sampling.persistence == api.analysis.persistence == api.alerts.persistence == "durable"


def test_builder_requires_the_dedicated_artifact_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE", raising=False)

    with pytest.raises(RuntimeError, match="GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE"):
        workflow_c_postgres.build_workflow_c_api(
            database_url="postgresql://geo_app:secret@db/geo"
        )
