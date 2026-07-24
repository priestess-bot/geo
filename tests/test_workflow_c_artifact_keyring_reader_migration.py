from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (
    ROOT / "infra" / "db" / "alembic" / "sql" / "0072_wfc_artifact_keyring_reader.sql"
).read_text(encoding="utf-8")
DOWN = (
    ROOT / "infra" / "db" / "alembic" / "sql" / "0072_wfc_artifact_keyring_reader.down.sql"
).read_text(encoding="utf-8")


def test_restricted_app_can_verify_canaries_without_table_read_privilege() -> None:
    assert "CREATE FUNCTION geo_read_workflow_c_artifact_keyring_canaries()" in SQL
    assert "SECURITY DEFINER" in SQL
    assert "SET search_path = pg_catalog, public" in SQL
    assert "WHERE key_version.status <> 'retired'" in SQL
    assert "FROM PUBLIC, geo_app, geo_worker, geo_readonly" in SQL
    assert "GRANT EXECUTE ON FUNCTION geo_read_workflow_c_artifact_keyring_canaries()" in SQL
    assert "TO geo_app, geo_worker;" in SQL
    assert "DROP FUNCTION geo_read_workflow_c_artifact_keyring_canaries();" in DOWN
