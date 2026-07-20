from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0021_observation_source_details.py"
UP = ROOT / "infra/db/alembic/sql/0021_observation_source_details.sql"
DOWN = ROOT / "infra/db/alembic/sql/0021_observation_source_details.down.sql"


def test_source_details_extend_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0021_observation_source_details"' in source
    assert 'down_revision = "0020_project_exports"' in source
    assert UP.is_file() and DOWN.is_file()


def test_source_details_add_a_separate_v3_hash_contract() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "geo_observation_source_stratum_v3_canonical",
        "geo_observation_source_stratum_v3_hash",
        "geo_source_stratum_v3_json_valid",
        "geo_source_stratum_v3_hash_from_json",
        "geo_source_strata_v3_inventory_hash",
        "platform_detail",
        "surface_detail",
        "geo-observation-source-v3",
        "geo_assert_metric_membership_member",
    ):
        assert contract in source
    assert "CREATE OR REPLACE FUNCTION geo_observation_source_stratum_canonical" not in source
    assert "CREATE OR REPLACE FUNCTION geo_observation_source_stratum_hash" not in source


def test_source_details_downgrade_is_fail_closed_and_data_preserving() -> None:
    down = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: observation source v3 data exists" in down
    assert "DELETE FROM monitoring_" not in down
    assert "UPDATE monitoring_" not in down
    assert "geo-observation-source-v2" in down
