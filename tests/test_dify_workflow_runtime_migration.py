from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0093_dify_workflow_runtime.py"
UP = ROOT / "infra/db/alembic/sql/0093_dify_workflow_runtime.sql"
DOWN = ROOT / "infra/db/alembic/sql/0093_dify_workflow_runtime.down.sql"


def test_dify_runtime_is_the_linear_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0093_dify_workflow_runtime"' in source
    assert 'down_revision = "0092_prompt_workspace_kinds"' in source
    assert UP.is_file() and DOWN.is_file()


def test_dify_runtime_freezes_release_binding_and_attempt_lineage() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "CREATE TABLE dify_workflow_releases",
        "CREATE TABLE dify_workflow_bindings",
        "CREATE TABLE dify_workflow_execution_attempts",
        "prompt_release_hash",
        "dsl_hash",
        "context_contract_version",
        "api_secret_reference_id",
        "dify_run_id",
        "fencing_generation",
        "successful canary before activation",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
    ):
        assert contract in source
    assert "GRANT DELETE" not in source
    assert "api_key" not in source.lower()


def test_worker_can_only_mutate_attempts() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "GRANT SELECT ON dify_workflow_releases, dify_workflow_bindings TO geo_worker" in source
    assert "GRANT SELECT, INSERT, UPDATE ON dify_workflow_execution_attempts TO geo_worker" in source
    assert "GRANT INSERT ON dify_workflow_releases" not in source.split("TO geo_worker")[0][-100:]
