from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "infra/db/alembic/versions/0027_prompt_programs.py"
UP = ROOT / "infra/db/alembic/sql/0027_prompt_programs.sql"
DOWN = ROOT / "infra/db/alembic/sql/0027_prompt_programs.down.sql"


def test_prompt_program_revision_is_the_single_linear_head() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "0027_prompt_programs"' in source
    assert 'down_revision = "0026_legacy_simulation"' in source
    assert UP.is_file() and DOWN.is_file()


def test_prompt_program_schema_is_project_scoped_append_only_and_complete() -> None:
    source = UP.read_text(encoding="utf-8")
    for table in (
        "prompt_programs",
        "prompt_program_releases",
        "prompt_program_release_states",
        "prompt_program_test_evidence",
        "prompt_program_test_run_tasks",
        "prompt_program_bindings",
        "prompt_program_command_receipts",
    ):
        assert f"CREATE TABLE {table}" in source
        assert table in source.split("FORCE ROW LEVEL SECURITY", maxsplit=1)[0]
    for contract in (
        "variable_schema jsonb",
        "input_schema jsonb",
        "output_schema jsonb",
        "output_schema_hash text",
        "application_output_schema_version text",
        "application_output_schema jsonb",
        "application_output_schema_hash text",
        "model_policy jsonb",
        "model_policy_hash",
        "system_template_hash",
        "user_template_hash",
        "release_hash",
        "test_set_version",
        "test_set_hash",
        "compiler_version",
        "idempotency_key_hash",
        "request_hash",
        "result_payload jsonb",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "geo_current_project_ids()",
        "geo_reject_immutable_change()",
        "geo_assert_prompt_program_release_append()",
        "geo_assert_prompt_program_state_append()",
        "geo_assert_prompt_program_binding_append()",
        "geo_assert_prompt_program_state_evidence()",
        "geo_assert_prompt_program_test_run_task()",
        "geo_jsonb_canonical_text(jsonb)",
        "prompt.test.execute",
        "task_payload_hash = expected_job_input_hash",
        "Prompt test task requires the current draft state",
        "DEFERRABLE INITIALLY DEFERRED",
        "Prompt Program owner cannot approve own Release",
        "Prompt Program Release version is not linear",
        "Prompt Program Release Schema hash is invalid",
        "evidence.tested_by IS DISTINCT FROM NEW.acted_by",
        "evidence.tested_at IS DISTINCT FROM NEW.acted_at",
        "evidence.test_set_id IS DISTINCT FROM release_record.test_set_id",
        "'create_release'",
        "'diff'",
        "'created_release'",
        "'diffed'",
    ):
        assert contract in source
    assert "reference_translation" in source
    assert "style_profile" in source
    assert "offline_answer" in source
    assert "GRANT UPDATE ON" not in source
    assert "GRANT DELETE ON" not in source
    assert source.count("BEFORE UPDATE OR DELETE ON prompt_program") == 7
    grants = source.split("GRANT SELECT ON")[1:]
    assert "TO geo_app;" in grants[0]
    assert "prompt_program_command_receipts" not in grants[1].split(";", maxsplit=1)[0]
    assert "TO geo_worker;" in grants[1]
    assert all("geo_readonly" not in grant.split(";", maxsplit=1)[0] for grant in grants)


def test_prompt_program_schema_uses_composite_project_lineage() -> None:
    source = UP.read_text(encoding="utf-8")
    normalized = " ".join(source.split())
    for constraint in (
        "prompt_program_releases_program_fkey",
        "prompt_program_release_states_release_fkey",
        "prompt_program_release_states_previous_fkey",
        "prompt_program_test_evidence_release_fkey",
        "prompt_program_test_evidence_state_fkey",
        "prompt_program_test_run_tasks_job_fkey",
        "prompt_program_test_run_tasks_release_fkey",
        "prompt_program_test_run_tasks_state_fkey",
        "prompt_program_test_run_tasks_test_set_fkey",
        "prompt_program_bindings_program_fkey",
        "prompt_program_bindings_release_fkey",
        "prompt_program_bindings_state_fkey",
        "prompt_program_bindings_previous_fkey",
    ):
        section = source.split(f"CONSTRAINT {constraint}", maxsplit=1)[1]
        assert "project_id" in section.split(")", maxsplit=1)[0]
    assert "UNIQUE (release_id, version)" in normalized
    assert "UNIQUE ( project_id, purpose, binding_version )" in normalized
    assert "UNIQUE ( previous_state_id, project_id, release_id )" in normalized


def test_prompt_program_schema_indexes_fk_and_project_scope_paths() -> None:
    source = UP.read_text(encoding="utf-8")
    for index in (
        "prompt_programs_project_created_idx",
        "prompt_programs_owner_idx",
        "prompt_program_releases_program_fkey_idx",
        "prompt_program_releases_owner_idx",
        "prompt_program_release_states_current_idx",
        "prompt_program_release_states_release_fkey_idx",
        "prompt_program_release_states_previous_fkey_idx",
        "prompt_program_release_states_acted_by_idx",
        "prompt_program_test_evidence_release_idx",
        "prompt_program_test_evidence_release_fkey_idx",
        "prompt_program_test_evidence_state_fkey_idx",
        "prompt_program_test_evidence_tested_by_idx",
        "prompt_program_test_run_tasks_release_idx",
        "prompt_program_test_run_tasks_release_fkey_idx",
        "prompt_program_test_run_tasks_state_fkey_idx",
        "prompt_program_test_run_tasks_requested_by_idx",
        "prompt_program_bindings_current_idx",
        "prompt_program_bindings_program_fkey_idx",
        "prompt_program_bindings_release_idx",
        "prompt_program_bindings_release_fkey_idx",
        "prompt_program_bindings_state_fkey_idx",
        "prompt_program_bindings_bound_by_idx",
    ):
        assert f"CREATE INDEX {index}" in source


def test_prompt_program_downgrade_refuses_to_discard_history() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "cannot downgrade: Prompt Program data exists" in source
    for table in (
        "prompt_program_command_receipts",
        "prompt_program_bindings",
        "prompt_program_test_evidence",
        "prompt_program_test_run_tasks",
        "prompt_program_release_states",
        "prompt_program_releases",
        "prompt_programs",
    ):
        assert f"EXISTS (SELECT 1 FROM {table})" in source
