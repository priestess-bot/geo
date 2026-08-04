from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0120_synthetic_direct_generation.py"
UP = ROOT / "infra/db/alembic/sql/0120_synthetic_direct_generation.sql"
DOWN = ROOT / "infra/db/alembic/sql/0120_synthetic_direct_generation.down.sql"
TASK_VERSION = ROOT / "infra/db/alembic/versions/0121_synth_direct_task.py"
TASK_UP = ROOT / "infra/db/alembic/sql/0121_synth_direct_task.sql"
TASK_DOWN = ROOT / "infra/db/alembic/sql/0121_synth_direct_task.down.sql"


def test_direct_generation_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0120_synthetic_direct_generation"' in version
    assert 'down_revision = "0119_question_model_identity"' in version
    assert len("0120_synthetic_direct_generation") <= 32
    assert "0120_synthetic_direct_generation.sql" in version
    assert "0120_synthetic_direct_generation.down.sql" in version


def test_direct_generation_extends_command_and_execution_contracts_linearly() -> None:
    source = UP.read_text(encoding="utf-8")
    task_version = TASK_VERSION.read_text(encoding="utf-8")
    task_source = TASK_UP.read_text(encoding="utf-8")

    assert "'create_channel_style'" in source
    assert 'revision = "0121_synth_direct_task"' in task_version
    assert 'down_revision = "0120_synthetic_direct_generation"' in task_version
    assert "DirectGenerationTask" in task_source
    assert "THEN 'review.case.run'" in task_source
    assert "THEN 'candidate_generation'" in task_source
    assert "THEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunOutput'" in task_source


def test_direct_generation_downgrade_fails_closed_and_restores_prior_types() -> None:
    source = TASK_DOWN.read_text(encoding="utf-8")

    assert "cannot downgrade direct Synthetic generation while evidence exists" in source
    assert "DirectGenerationTask" in source.split("DO $$", 1)[1].split("$$;", 1)[0]
    assert "DirectGenerationTask" not in source.split("$$;", 1)[1]
    assert "'create_channel_style'" not in DOWN.read_text(encoding="utf-8")
