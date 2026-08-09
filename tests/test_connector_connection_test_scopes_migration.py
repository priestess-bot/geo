from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0128_connector_connection_test_scopes.py"
UP = ROOT / "infra/db/alembic/sql/0128_connector_test_scopes.sql"
DOWN = ROOT / "infra/db/alembic/sql/0128_connector_test_scopes.down.sql"


def test_scope_bound_connection_test_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0128_connector_test_scopes"' in source
    assert 'down_revision = "0127_question_set_dedup"' in source
    assert UP.is_file() and DOWN.is_file()


def test_upgrade_freezes_ordered_active_scope_identity_without_credentials() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "schema_version', 2",
        "scope.status = 'active'",
        "jsonb_agg(",
        "ORDER BY scope.id",
        "'id', scope.id",
        "'version', scope.version",
        "'scope_hash', scope.scope_hash",
        "'source_locator', scope.source_locator",
        "'streams', scope.streams",
        "'report_spec', scope.report_spec",
        "'date_policy', scope.date_policy",
        "must have at least one active Scope",
        "nonterminal v1 Jobs exist",
    ):
        assert contract in source
    assert "credential" not in source


def test_upgrade_and_downgrade_fail_closed_for_nonterminal_contract_mismatch() -> None:
    up = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")
    assert "test.status IN ('queued', 'running')" in up
    assert "schema_version' IS DISTINCT FROM '2'" in up
    assert "test.status IN ('queued', 'running')" in down
    assert "schema_version' IS DISTINCT FROM '1'" in down
    assert "nonterminal v2 Jobs exist" in down
