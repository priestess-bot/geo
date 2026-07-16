from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0008_prompt_simulations.py"
UP = ROOT / "infra/db/alembic/sql/0008_prompt_simulations.sql"
DOWN = ROOT / "infra/db/alembic/sql/0008_prompt_simulations.down.sql"


def test_prompt_simulation_revision_extends_placement_operations() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0008_prompt_simulations"' in source
    assert 'down_revision = "0007_placement_operations"' in source
    assert UP.is_file() and DOWN.is_file()


def test_prompt_simulation_schema_is_isolated_and_fail_closed() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "CREATE TABLE prompt_simulations",
        "CREATE TABLE prompt_simulation_evidence",
        "CREATE TABLE prompt_simulation_job_specs",
        "CREATE TABLE prompt_simulation_results",
        "CHECK (test_only)",
        "CHECK (NOT publication_eligible)",
        "prompt_simulation.generate",
        "content-simulations/",
        "FORCE ROW LEVEL SECURITY",
        "prompt_simulations_immutable",
    ):
        assert contract in source
    simulation_section = source.split("CREATE TABLE prompt_simulations", maxsplit=1)[1]
    for forbidden in (
        "REFERENCES placement_packages",
        "REFERENCES placement_package_versions",
        "REFERENCES placement_reviews",
        "REFERENCES placement_export_receipts",
        "REFERENCES publication_requests",
    ):
        assert forbidden not in simulation_section
