from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UP = (ROOT / "infra/db/alembic/sql/0074_wfc_semantic_job_v2.sql").read_text()
DOWN = (ROOT / "infra/db/alembic/sql/0074_wfc_semantic_job_v2.down.sql").read_text()


def test_semantic_v2_admission_is_atomic_scoped_and_secret_free() -> None:
    assert "geo_enqueue_workflow_c_semantic_metric_job_v2" in UP
    assert "p_project_id = ANY(geo_current_project_ids())" in UP
    assert "geo_workflow_c_job_spec_payload_is_safe(p_spec_payload)" in UP
    for table in (
        "workflow_c_analysis_input_manifests",
        "workflow_c_analysis_input_manifest_items",
        "durable_jobs",
        "workflow_c_job_specs",
        "broker_outbox",
        "durable_job_events",
    ):
        assert f"INTO {table}" in UP
    assert "TO geo_app" in UP
    assert "TO geo_worker" not in UP.split("GRANT EXECUTE", maxsplit=1)[1]


def test_semantic_v2_admission_revalidates_exact_lineage_and_refuses_lossy_down() -> None:
    for evidence in (
        "protocol_row.status <> 'approved'",
        "run_row.status <> 'completed'",
        "planned denominator changed",
        "source_job.status <> 'succeeded'",
        "Semantic Provider artifact is not recoverable",
        "Semantic manual artifact is not recoverable",
    ):
        assert evidence in UP
    assert "cannot downgrade semantic Job v2 after admitted work exists" in DOWN
