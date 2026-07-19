from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0014_observation_source_contract.py"
UP = ROOT / "infra/db/alembic/sql/0014_observation_source_contract.sql"
DOWN = ROOT / "infra/db/alembic/sql/0014_observation_source_contract.down.sql"


def test_observation_source_contract_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0014_observation_source_contract"' in source
    assert 'down_revision = "0013_fact_evidence_lineage"' in source
    assert UP.is_file() and DOWN.is_file()


def test_observation_contract_separates_answer_synthetic_and_official_sources() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "eligibility_requested boolean NOT NULL DEFAULT false",
        "citations_captured boolean NOT NULL DEFAULT false",
        "raw_evidence_kind",
        "geo-observation-source-v2",
        "geo_observation_source_stratum_hash",
        "source_strata_snapshot",
        "query_cluster_key",
        "synthetic_test_only",
        "pg_has_role(session_user, 'geo_worker', 'USAGE')",
        "prompt_simulation_results",
        "monitoring_official_report_imports",
        "monitoring_official_report_rows",
        "capture_method = 'official_report_import'",
        "capture_method IN (\n            'manual_ui', 'provider_api', 'proxy_grounded_api', 'synthetic', 'unknown'",
        "UNIQUE NULLS NOT DISTINCT",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
    ):
        assert contract in source
    observation_contract = source.split(
        "ADD CONSTRAINT monitoring_observations_capture_method_check", maxsplit=1
    )[1].split(
        "ADD CONSTRAINT monitoring_observations_platform_check", maxsplit=1
    )[0]
    assert "official_report_import" not in observation_contract


def test_observation_contract_downgrade_restores_legacy_eligibility() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: typed observation source data exists" in source
    assert "monitoring_observation_legacy_migration_state" in source
    assert "SET eligible = migration_state.eligible" in source
    assert "DROP TABLE monitoring_official_report_rows" in source
    assert "DROP TABLE monitoring_official_report_imports" in source
