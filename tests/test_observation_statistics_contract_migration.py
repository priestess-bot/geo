from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0015_observation_statistics_contract.py"
UP = ROOT / "infra/db/alembic/sql/0015_observation_statistics_v2.sql"
DOWN = ROOT / "infra/db/alembic/sql/0015_observation_statistics_v2.down.sql"


def test_observation_statistics_contract_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0015_observation_statistics_v2"' in source
    assert 'down_revision = "0014_observation_source_contract"' in source
    assert UP.is_file() and DOWN.is_file()


def test_observation_statistics_contract_is_versioned_and_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "geo-observation-statistics-v2",
        "minimum_valid_repeats",
        "sample_size * 4",
        "analysis_stratum_hash",
        "query_cluster_key",
        "insufficient_evidence",
        "query_results_snapshot",
        "monitoring_metric_statistics_slot_key",
        "monitoring_metric_statistics_latest_idx",
        "geo_analysis_stratum_hash",
        "eligible_sample_count + NEW.invalid_sample_count",
        "qualified_destination_ids <@ NEW.selected_destination_ids",
        "verified_destination_ids <@ NEW.qualified_destination_ids",
    ):
        assert contract in source


def test_observation_statistics_downgrade_refuses_v2_truth() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: observation statistics v2 data exists" in source
    assert "monitoring_metric_snapshots_status_check" in source
    assert "monitoring_metric_source_slot_key" in source
    assert "monitoring_metric_snapshots_source_stratum_idx" in source
