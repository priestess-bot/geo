from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0081_surface_parser_results.py"
UP = ROOT / "infra/db/alembic/sql/0081_surface_parser_results.sql"
DOWN = ROOT / "infra/db/alembic/sql/0081_surface_parser_results.down.sql"


def test_surface_parser_migration_is_linear_and_file_backed() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0081_surface_parser_results"' in version
    assert 'down_revision = "0080_synthetic_corpus_execution"' in version
    assert len("0081_surface_parser_results") <= 32
    assert "0081_surface_parser_results.sql" in version
    assert "0081_surface_parser_results.down.sql" in version


def test_surface_parser_summary_is_project_scoped_immutable_and_text_free() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "CREATE TABLE workflow_c_surface_parse_results" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "geo_current_project_ids()" in source
    assert "surface parse results are immutable" in source
    assert "GRANT SELECT ON workflow_c_surface_parse_results TO geo_app, geo_worker" in source
    assert "GRANT INSERT" not in source
    assert "'automated_capture'" in source
    assert "p_surface_parse->'automated_capture' <> 'false'::jsonb" in source
    assert "p_surface_parse->'live_capture_eligible' <> 'false'::jsonb" in source
    assert "answer_text_hash" in source
    assert "answer_text'," not in source
    assert "citation_set_hash" in source
    assert "citation_url" not in source


def test_surface_parser_submission_wraps_manual_evidence_atomically() -> None:
    source = UP.read_text(encoding="utf-8")

    assert "geo_submit_workflow_c_surface_parsed_evidence" in source
    assert "geo_submit_workflow_c_manual_sampling_evidence(" in source
    assert "ON CONFLICT (project_id, manual_import_id) DO NOTHING" in source
    assert "Manual surface parse idempotency conflict" in source
    assert "geo_jsonb_canonical_text(p_surface_parse - 'summary_hash')" in source


def test_surface_parser_downgrade_refuses_to_remove_evidence() -> None:
    source = DOWN.read_text(encoding="utf-8")

    assert "cannot downgrade consumer surface parser results after evidence exists" in source
    assert "DROP FUNCTION geo_submit_workflow_c_surface_parsed_evidence" in source
    assert "DROP TABLE workflow_c_surface_parse_results" in source
