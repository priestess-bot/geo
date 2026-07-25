from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / "infra/db/alembic/sql/0075_wfc_manual_attempt_scope.sql"
DOWN = ROOT / "infra/db/alembic/sql/0075_wfc_manual_attempt_scope.down.sql"
REVISION = ROOT / "infra/db/alembic/versions/0075_wfc_manual_attempt_trigger_scope.py"


def test_provider_attempt_guard_resolves_capture_method_before_provider_spec() -> None:
    source = UP.read_text(encoding="utf-8")

    suite_lookup = source.index("SELECT * INTO suite_row")
    capture_guard = source.index(
        "suite_row.capture_method NOT IN ('provider_api', 'proxy_grounded_api')"
    )
    provider_spec = source.index("SELECT spec_payload INTO spec")

    assert suite_lookup < capture_guard < provider_spec
    assert "IF suite_row.id IS NULL THEN" in source
    assert "RETURN NEW;" in source[capture_guard:provider_spec]
    assert "status IN ('approved', 'retired')" in source
    assert "Provider Sampling Attempt question differs" in source
    assert "NEW.kind NOT IN ('sampling.provider_execute', 'sampling.manual_import')" in source
    assert "task_row.capture_method <> 'manual_ui'" in source


def test_manual_attempt_scope_migration_is_linear_and_reversible() -> None:
    revision = REVISION.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")

    assert 'revision = "0075_wfc_manual_attempt_scope"' in revision
    assert 'down_revision = "0074_wfc_semantic_job_v2"' in revision
    assert "CREATE OR REPLACE FUNCTION geo_verify_workflow_c_provider_execution_attempt" in down
    assert "Provider Sampling Attempt has no frozen Job spec" in down
    assert "NEW.kind <> 'sampling.provider_execute'" in down
