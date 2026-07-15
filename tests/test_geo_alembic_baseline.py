from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = ROOT / "infra" / "db" / "alembic"
BASELINE = (ALEMBIC / "sql" / "0001_geo_baseline.sql").read_text(encoding="utf-8")


def test_revision_graph_has_exactly_one_root_and_head() -> None:
    revisions = sorted((ALEMBIC / "versions").glob("*.py"))
    assert [path.name for path in revisions] == ["0001_geo_baseline.py"]
    revision = revisions[0].read_text(encoding="utf-8")
    assert 'revision = "0001_geo_baseline"' in revision
    assert "down_revision = None" in revision


def test_baseline_covers_required_geo_aggregates() -> None:
    required_tables = {
        "tenants",
        "projects",
        "project_memberships",
        "product_entities",
        "market_profiles",
        "monitoring_queries",
        "evidence_items",
        "geo_campaigns",
        "placement_opportunities",
        "placement_brief_versions",
        "placement_brief_subject_entities",
        "evidence_pack_attempts",
        "prompt_skill_versions",
        "generation_template_releases",
        "prompt_bundles",
        "placement_package_versions",
        "placement_claims",
        "placement_reviews",
        "publication_requests",
        "publication_submissions",
        "placement_measurements",
        "durable_jobs",
        "generation_job_specs",
        "collection_job_queries",
        "measurement_job_queries",
        "broker_outbox",
        "artifact_finalize_outbox",
        "evidence_embeddings",
    }
    created = set(re.findall(r"CREATE TABLE ([a-z_]+)", BASELINE))
    assert required_tables <= created


def test_project_relationships_and_rls_are_database_contracts() -> None:
    assert "FOREIGN KEY (brief_version_id, project_id)" in BASELINE
    assert "FOREIGN KEY (package_version_id, project_id)" in BASELINE
    assert "FOREIGN KEY (job_id, project_id)" in BASELINE
    assert "ENABLE ROW LEVEL SECURITY" in BASELINE
    assert "FORCE ROW LEVEL SECURITY" in BASELINE
    assert "project_id = geo_current_project_id()" in BASELINE
    assert "compared_entity_ids" not in BASELINE
    assert "monitoring_query_ids" not in BASELINE


def test_content_publication_and_evidence_invariants_are_explicit() -> None:
    assert "Export and delivery are projections/events" in BASELINE
    assert "Export and delivery MUST NOT create this row" in BASELINE
    assert "publication requires the exact approved package version" in BASELINE
    assert "claim_inventory_complete" in BASELINE
    assert "extracted_claim_support_confirmed" in BASELINE
    assert "consumer_experience" in BASELINE
    assert "left(storage_uri, 16) = 'content-prompts/'" in BASELINE
    assert "vector(1024)" in BASELINE
    assert "vector_cosine_ops" in BASELINE


def test_job_contract_has_recovery_indexes_and_no_partial_success_state() -> None:
    durable_job_section = BASELINE.split("CREATE TABLE durable_jobs", maxsplit=1)[1].split(
        "CREATE TABLE collection_job_specs", maxsplit=1
    )[0]
    assert "lease_expires_at" in durable_job_section
    assert "fencing_generation" in durable_job_section
    assert "retry_wait" in durable_job_section
    assert "dead_lettered" in durable_job_section
    assert "partial_succeeded" not in durable_job_section
    assert "durable_jobs_reclaim_idx" in BASELINE
