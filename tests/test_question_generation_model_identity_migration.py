from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0119_question_model_identity.py"
UP = ROOT / "infra/db/alembic/sql/0119_question_model_identity.sql"
DOWN = ROOT / "infra/db/alembic/sql/0119_question_model_identity.down.sql"


def test_question_model_identity_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0119_question_model_identity"' in version
    assert 'down_revision = "0118_rec_draft_materialize"' in version
    assert len("0119_question_model_identity") <= 32
    assert "0119_question_model_identity.sql" in version
    assert "0119_question_model_identity.down.sql" in version


def test_question_model_identity_is_sanitized_and_backfilled() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "execution_backend IN ('dify', 'native')" in source
    assert "DROP TRIGGER knowledge_question_results_immutable" in source
    assert "CREATE TRIGGER knowledge_question_results_immutable" in source
    assert "FROM dify_workflow_execution_attempts attempt" in source
    assert "FROM model_call_logs call" in source
    assert "provider_reported_model" in source
    assert "result.output" not in source
    assert "TO geo_app" not in source


def test_question_model_identity_downgrade_removes_only_projection_columns() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "DROP COLUMN actual_model" in source
    assert "DROP COLUMN execution_backend" in source
    assert "DROP TABLE" not in source
