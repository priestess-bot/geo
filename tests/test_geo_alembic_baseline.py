from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = ROOT / "infra" / "db" / "alembic"
BASELINE = (ALEMBIC / "sql" / "0001_geo_baseline.sql").read_text(encoding="utf-8")
ACCESS = (ALEMBIC / "sql" / "0003_access_invitations.sql").read_text(encoding="utf-8")
ALEMBIC_ENV = (ALEMBIC / "env.py").read_text(encoding="utf-8")
MONITORING = (ALEMBIC / "sql" / "0004_monitoring_observations.sql").read_text(
    encoding="utf-8"
)


def test_revision_graph_has_exactly_one_root_and_head() -> None:
    revisions = sorted((ALEMBIC / "versions").glob("*.py"))
    assert [path.name for path in revisions] == [
        "0001_geo_baseline.py",
        "0002_engineering_governance.py",
        "0003_access_invitations.py",
        "0004_monitoring_observations.py",
    ]
    root = revisions[0].read_text(encoding="utf-8")
    engineering = revisions[1].read_text(encoding="utf-8")
    invitations = revisions[2].read_text(encoding="utf-8")
    head = revisions[3].read_text(encoding="utf-8")
    assert 'revision = "0001_geo_baseline"' in root
    assert "down_revision = None" in root
    assert 'revision = "0002_engineering_governance"' in engineering
    assert 'down_revision = "0001_geo_baseline"' in engineering
    assert 'revision = "0003_access_invitations"' in invitations
    assert 'down_revision = "0002_engineering_governance"' in invitations
    assert 'revision = "0004_monitoring_observations"' in head
    assert 'down_revision = "0003_access_invitations"' in head


def test_alembic_uses_the_installed_psycopg3_driver_for_standard_urls() -> None:
    assert 'value.startswith("postgresql://")' in ALEMBIC_ENV
    assert '"postgresql+psycopg://"' in ALEMBIC_ENV


def test_alembic_verifies_external_sql_checksums_in_its_single_ledger() -> None:
    assert "ensure_ledger(connection)" in ALEMBIC_ENV
    assert "verify_applied(" in ALEMBIC_ENV
    assert "synchronize_ledger(" in ALEMBIC_ENV
    checksums = (ALEMBIC / "checksums.py").read_text(encoding="utf-8")
    assert "FROM PUBLIC, geo_app, geo_worker, geo_readonly" in checksums


def test_database_provision_wrapper_never_accepts_a_database_url_argument() -> None:
    provisioner = (ROOT / "scripts/provision_database.py").read_text(encoding="utf-8")
    assert "database_url" not in provisioner
    assert 'command.upgrade(configuration, "head")' in provisioner


def test_monitoring_revision_has_rls_composite_links_and_immutable_records() -> None:
    required_tables = {
        "monitoring_protocols",
        "monitoring_query_suggestions",
        "monitoring_protocol_queries",
        "monitoring_observations",
        "monitoring_observation_citations",
        "monitoring_metric_snapshots",
        "monitoring_reports",
    }
    assert required_tables <= set(re.findall(r"CREATE TABLE ([a-z_]+)", MONITORING))
    assert "FORCE ROW LEVEL SECURITY" in MONITORING
    assert "REFERENCES monitoring_protocol_queries(protocol_id, monitoring_query_id, project_id)" in MONITORING
    assert "monitoring_observations_immutable" in MONITORING
    assert "frozen monitoring protocols are immutable" in MONITORING


def test_baseline_covers_required_geo_aggregates() -> None:
    required_tables = {
        "tenants",
        "projects",
        "project_memberships",
        "customer_sessions",
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
    assert "project_id = ANY(geo_current_project_ids())" in BASELINE
    assert "identity_id = geo_current_identity_id()" in BASELINE
    assert "customer_sessions" in BASELINE
    assert "compared_entity_ids" not in BASELINE
    assert "monitoring_query_ids" not in BASELINE


def test_runtime_roles_are_non_login_non_bypassrls_permission_groups() -> None:
    for role in ("geo_app", "geo_worker", "geo_readonly"):
        assert f"CREATE ROLE {role} NOLOGIN NOSUPERUSER" in BASELINE
    assert BASELINE.count("NOBYPASSRLS") >= 3
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in BASELINE
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO geo_readonly" in BASELINE


def test_initial_owner_audit_is_append_only_and_installer_only() -> None:
    assert "'tenant.bootstrap'" in ACCESS
    assert "'project'" in ACCESS
    assert "geo_protect_bootstrap_audit_insert" in ACCESS
    assert "current_user = session_user" in ACCESS
    assert "current_user = pg_get_userbyid(database_owner.datdba)" in ACCESS
    assert "FROM pg_auth_members AS membership" in ACCESS
    assert "granted.rolname IN ('geo_app', 'geo_worker')" in ACCESS


def test_member_management_has_restricted_rls_and_idempotent_commands() -> None:
    assert "CREATE TABLE membership_commands" in ACCESS
    assert "UNIQUE (project_id, idempotency_key_hash)" in ACCESS
    assert "result_snapshot jsonb NOT NULL" in ACCESS
    assert "SECURITY DEFINER" in ACCESS
    assert "SET search_path = pg_catalog, public" in ACCESS
    assert "SET row_security = off" in ACCESS
    assert "FROM geo_worker, geo_readonly" in ACCESS
    assert "manager.role IN ('owner', 'admin')" in ACCESS


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
