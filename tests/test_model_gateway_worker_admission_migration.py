from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0091_mgw_worker_admission.py"
UP = ROOT / "infra/db/alembic/sql/0091_mgw_worker_admit.sql"
DOWN = ROOT / "infra/db/alembic/sql/0091_mgw_worker_admit.down.sql"


def test_worker_admission_migration_is_linear_and_minimal() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    up = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")

    assert 'revision = "0091_mgw_worker_admit"' in migration
    assert 'down_revision = "0090_prompt_workspace"' in migration
    assert "GRANT INSERT ON model_gateway_job_admissions TO geo_worker;" in up
    assert "REVOKE INSERT ON model_gateway_job_admissions FROM geo_worker;" in down
    assert "GRANT UPDATE" not in up
    assert "GRANT DELETE" not in up
    assert "GRANT SELECT" not in up
