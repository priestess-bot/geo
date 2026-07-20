from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0012_campaign_prompt_context.py"
UP = ROOT / "infra/db/alembic/sql/0012_campaign_prompt_context.sql"
DOWN = ROOT / "infra/db/alembic/sql/0012_campaign_prompt_context.down.sql"


def test_campaign_prompt_context_extends_the_linear_revision_chain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0012_campaign_prompt_context"' in source
    assert 'down_revision = "0011_runtime_health"' in source
    assert UP.is_file() and DOWN.is_file()


def test_campaign_prompt_context_freezes_exact_append_only_ancestry() -> None:
    source = UP.read_text(encoding="utf-8")
    for contract in (
        "generation_template_release_states",
        "opportunity_prompt_release_bindings",
        "WITH (security_invoker = true)",
        "state_version = 1 OR idempotency_key IS NOT NULL",
        "binding_version = 1 OR idempotency_key IS NOT NULL",
        "prompt_bundles_v2_idempotency_check",
        "placement_measurements_exact_campaign_query_fkey",
        "measurement_collection_tasks_exact_protocol_fkey",
        "placement_package_versions_exact_generation_spec_fkey",
        "prompt_simulation_results_exact_job_spec_fkey",
        "durable_jobs_exact_parent_campaign_fkey",
        "geo_reject_campaign_lineage_update",
        "legacy Placement jobs contain incomplete Campaign specifications",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
    ):
        assert contract in source


def test_campaign_prompt_context_downgrade_is_fail_closed_and_complete() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: Campaign Prompt context contains v2 audit data" in source
    assert "DROP TABLE opportunity_prompt_release_bindings" in source
    assert "DROP TABLE generation_template_release_states" in source
    assert "prompt_simulation_results_exact_job_spec_fkey" in source
    assert "placement_package_versions_exact_generation_spec_fkey" in source
