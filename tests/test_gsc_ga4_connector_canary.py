from __future__ import annotations

import json

from scripts.gsc_ga4_connector_canary import main


def test_canary_requires_database_before_any_external_operation(capsys, monkeypatch) -> None:
    monkeypatch.delenv("GEO_CONNECTOR_DATABASE_URL", raising=False)
    monkeypatch.delenv("GEO_DATABASE_URL", raising=False)

    result = main(
        [
            "--kind",
            "google_search_console",
            "--project-id",
            "00000000-0000-0000-0000-000000000001",
            "--connection-id",
            "00000000-0000-0000-0000-000000000002",
            "--scope-id",
            "00000000-0000-0000-0000-000000000003",
        ]
    )

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "GEO_CONNECTOR_DATABASE_URL_REQUIRED"
    assert "password" not in payload["detail"].lower()


def test_canary_rejects_invalid_scope_identifiers_without_database(monkeypatch) -> None:
    monkeypatch.setenv("GEO_CONNECTOR_DATABASE_URL", "postgresql://invalid.example/geo")

    result = main(
        [
            "--kind",
            "google_analytics_4",
            "--project-id",
            "not-a-uuid",
            "--connection-id",
            "00000000-0000-0000-0000-000000000002",
            "--scope-id",
            "00000000-0000-0000-0000-000000000003",
        ]
    )

    assert result == 2
