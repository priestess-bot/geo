from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0020_project_exports.py"
UP = ROOT / "infra/db/alembic/sql/0020_project_exports.sql"
DOWN = ROOT / "infra/db/alembic/sql/0020_project_exports.down.sql"


def test_project_exports_extend_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0020_project_exports"' in source
    assert 'down_revision = "0019_knowledge_question_sets"' in source
    assert UP.is_file() and DOWN.is_file()


def test_project_export_schema_freezes_request_artifact_and_role_contracts() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "CREATE TABLE project_export_specs",
        "CREATE TABLE project_export_artifacts",
        "project.export",
        "geo_assert_project_export_spec",
        "geo_assert_project_export_artifact",
        "project-exports/",
        "all-campaigns",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "GRANT INSERT ON project_export_specs TO geo_app",
        "GRANT INSERT ON project_export_artifacts TO geo_worker",
    ):
        assert contract in source


def test_project_export_downgrade_is_data_preserving_and_fail_closed() -> None:
    down = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: project export jobs or artifacts exist" in down
    assert "DELETE FROM project_export" not in down
    assert "DELETE FROM durable_jobs" not in down
    assert "UPDATE project_export" not in down
