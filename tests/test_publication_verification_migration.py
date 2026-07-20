from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0016_publication_verification.py"
UP = ROOT / "infra/db/alembic/sql/0016_publication_verification.sql"
DOWN = ROOT / "infra/db/alembic/sql/0016_publication_verification.down.sql"


def test_publication_verification_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0016_publication_verification"' in source
    assert 'down_revision = "0015_observation_statistics_v2"' in source
    assert UP.is_file() and DOWN.is_file()


def test_publication_verification_attempts_are_governed_and_body_free() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "CREATE TABLE publication_verification_attempts",
        "verification_job_specs_attempt_context_key",
        "publication-url-verifier-v2",
        "publication_verification_attempts_job_attempt_key",
        "geo_assert_publication_verification_attempt",
        "job.attempt_count",
        "checks jsonb",
        "failures jsonb",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "GRANT SELECT, INSERT ON publication_verification_attempts TO geo_worker",
    ):
        assert contract in source
    table = source.split(
        "CREATE TABLE publication_verification_attempts", maxsplit=1
    )[1].split(");", maxsplit=1)[0]
    assert "body_hash" in table
    assert "body text" not in table
    assert "html" not in table
    assert "message" not in table


def test_publication_verification_downgrade_is_fail_closed() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: publication verification attempts exist" in source
    assert "DROP TABLE publication_verification_attempts" in source
    assert "verification_job_specs_attempt_context_key" in source
