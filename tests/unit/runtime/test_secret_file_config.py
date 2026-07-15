from pathlib import Path

import pytest

from geo_core.runtime import RuntimePersistenceError, connect_postgres_from_env


def test_database_url_can_be_read_from_secret_file(tmp_path: Path) -> None:
    secret = tmp_path / "database-url"
    secret.write_text("postgresql://geo_app:secret@postgres/geo\n", encoding="utf-8")
    observed: list[str] = []

    connection = connect_postgres_from_env(
        {"DATABASE_URL_FILE": str(secret)},
        connector=lambda database_url: observed.append(database_url) or object(),
    )

    assert connection is not None
    assert observed == ["postgresql://geo_app:secret@postgres/geo"]


def test_database_url_rejects_ambiguous_direct_and_file_configuration(tmp_path: Path) -> None:
    secret = tmp_path / "database-url"
    secret.write_text("postgresql://geo_app:file-secret@postgres/geo", encoding="utf-8")

    with pytest.raises(RuntimePersistenceError, match="cannot both be configured"):
        connect_postgres_from_env(
            {
                "DATABASE_URL": "postgresql://geo_app:env-secret@postgres/geo",
                "DATABASE_URL_FILE": str(secret),
            },
            connector=lambda _database_url: object(),
        )


def test_database_url_file_errors_do_not_disclose_file_contents(tmp_path: Path) -> None:
    missing = tmp_path / "missing-database-url"

    with pytest.raises(RuntimePersistenceError, match="Unable to read DATABASE_URL_FILE") as error:
        connect_postgres_from_env(
            {"DATABASE_URL_FILE": str(missing)},
            connector=lambda _database_url: object(),
        )

    assert "postgresql://" not in str(error.value)
