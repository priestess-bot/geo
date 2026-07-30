from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0118_rec_draft_materialize.py"
UP = ROOT / "infra/db/alembic/sql/0118_rec_draft_materialize.sql"
DOWN = ROOT / "infra/db/alembic/sql/0118_rec_draft_materialize.down.sql"


def test_recommendation_materialization_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0118_rec_draft_materialize"' in version
    assert 'down_revision = "0117_knowledge_rag_replay_link"' in version
    assert len("0118_rec_draft_materialize") <= 32
    assert "0118_rec_draft_materialize.sql" in version
    assert "0118_rec_draft_materialize.down.sql" in version


def test_worker_gets_only_the_fenced_draft_materialization_rpc() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "SECURITY DEFINER" in source
    assert "SET row_security = off" in source
    assert "lease_token IS DISTINCT FROM p_lease_token" in source
    assert "fencing_generation <> p_fencing_generation" in source
    assert "cancel_requested_at IS NOT NULL" in source
    assert "recommendation-generation-result-v3" in source
    assert "recommendation_value->>'status' <> 'draft'" in source
    assert "'approval', 'transitions'" in source
    assert "jsonb_array_length(workflow_value->'drafts') <> 0" in source
    assert "GRANT EXECUTE ON FUNCTION geo_materialize_recommendation_generation_draft" in source
    assert "GRANT INSERT ON recommendation_workflow_versions" not in source
    assert "GRANT INSERT ON recommendation_evidence_bindings" not in source
    assert "TO geo_app" not in source.split("GRANT EXECUTE", maxsplit=1)[1]


def test_materialization_supports_explicit_attribution_evidence_and_safe_downgrade() -> None:
    source = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")

    assert "'surface', 'attribution'" in source
    assert "'attribution_availability'" in source
    assert "DROP FUNCTION geo_materialize_recommendation_generation_draft" in down
    assert "'surface', 'attribution'" not in down
