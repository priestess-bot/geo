from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0080_synthetic_corpus_execution.py"
UP = ROOT / "infra/db/alembic/sql/0080_synthetic_corpus_execution.sql"
DOWN = ROOT / "infra/db/alembic/sql/0080_synthetic_corpus_execution.down.sql"


def test_synthetic_corpus_execution_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0080_synthetic_corpus_execution"' in version
    assert 'down_revision = "0079_synth_profile_runtime"' in version
    assert len("0079_synth_profile_runtime") <= 32
    assert len("0080_synthetic_corpus_execution") <= 32
    assert "0080_synthetic_corpus_execution.sql" in version
    assert "0080_synthetic_corpus_execution.down.sql" in version


def test_synthetic_corpus_execution_extends_closed_world_task_and_result_types() -> None:
    source = UP.read_text(encoding="utf-8")

    for contract in (
        "'corpus.finalize'",
        "'offline_experiment.run'",
        "geo_core.synthetic_lab.execution_contracts.CorpusFinalizeTask",
        "geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask",
        "geo_core.synthetic_lab.execution_contracts.CorpusFinalizeOutput",
        "geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunOutput",
        "WHEN 'geo_core.synthetic_lab.execution_contracts.CorpusFinalizeTask'",
        "THEN 'corpus_finalize'",
        "Synthetic execution task does not match its queued Durable Job",
        "Synthetic execution result lost lease, fence, or frozen runtime lineage",
    ):
        assert contract in source


def test_synthetic_corpus_execution_downgrade_is_fail_closed_with_evidence() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "cannot downgrade synthetic Corpus execution while evidence exists" in source
    assert "execution_kind = 'corpus.finalize'" in source
    assert "CorpusFinalizeOutput" in source
    assert "OfflineExperimentRunTask" in source
    assert "OfflineExperimentRunOutput" in source
    assert "CorpusFinalizeTask" not in source.split("DO $$", 1)[1].split("$$;", 1)[1]
