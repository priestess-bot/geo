from pathlib import Path


def test_opportunity_reference_is_scoped_to_campaign_and_destination() -> None:
    source = Path(
        "packages/geo_core/geo_core/placements/postgres_repository.py"
    ).read_text(encoding="utf-8")
    assert "campaign:{values['campaign_id']}:destination:{destination_id}" in source


def test_database_enforces_one_task_per_campaign_destination_pair() -> None:
    migration = Path(
        "infra/db/alembic/sql/0010_campaign_destinations.sql"
    ).read_text(encoding="utf-8")
    assert "UNIQUE (project_id, campaign_id, destination_id)" in migration
    assert "UNIQUE (project_id, opportunity_ref)" in migration
