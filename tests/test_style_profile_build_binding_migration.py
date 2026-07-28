from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0099_style_profile_build_binding.py"
UP = ROOT / "infra/db/alembic/sql/0099_style_profile_build_binding.sql"
DOWN = ROOT / "infra/db/alembic/sql/0099_style_profile_build_binding.down.sql"


def test_style_profile_build_binding_is_a_separate_linear_migration() -> None:
    version = VERSION.read_text(encoding="utf-8")
    assert 'revision = "0099_style_profile_build_binding"' in version
    assert 'down_revision = "0098_synthetic_dify_lineage"' in version
    assert "0099_style_profile_build_binding.sql" in version
    assert "0099_style_profile_build_binding.down.sql" in version


def test_profile_review_freezes_one_exact_canonical_build_result() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "CREATE TABLE synthetic_lab_style_profile_build_bindings" in source
    assert "PRIMARY KEY (project_id, profile_version_id)" in source
    assert "UNIQUE (project_id, execution_result_id)" in source
    assert "geo_synthetic_style_profile_result_hash" in source
    assert "result_record.result_payload_hash <> encode(digest" in source
    assert "profile_record.payload #>> '{fields,status,value}' <> 'draft'" in source
    assert "Style Profile review binding does not match its exact canonical build result" in source
    assert "Style Profile build result binding is immutable" in source
    assert "char_length(profile_summary) > 16000" in source
    assert "verification_status IN ('verified', 'legacy_unverified')" in source
    assert "binding_source IN ('migration_backfill', 'migration_legacy', 'runtime_review')" in source
    assert "'legacy_unverified', 'migration_legacy', true" in source
    assert "new Style Profile review requires one runtime-verified build result" in source


def test_parent_admission_terminal_and_result_identity_are_narrowly_guarded() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT synthetic_lab_command_receipts_operation_check" in source
    assert "'import_samples', 'freeze_profile', 'submit_profile', 'freeze_suite'" in source
    assert "CREATE TRIGGER style_profile_parent_admission_lock" in source
    assert "'dify-binding:' || NEW.project_id::text || chr(58) ||" in source
    assert "'synthetic_lab.style_profile', 0" in source
    assert "CREATE TRIGGER synthetic_style_profile_result_identity_guard" in source
    assert "jsonb_array_length(model_calls) + jsonb_array_length(workflow_calls) <> 1" in source
    assert "metadata.domain_job_kind <> 'style_profile_build'" in source
    assert "(profile_frozen OR domain_job_kind = 'style_profile_build')" not in source
    assert "geo_synthetic_style_profile_result_matches_child" in source
    assert "'style-profile' || chr(58) || 'build' || chr(58) || 'v1'" in source
    assert "terminal.gateway_call_log_id::text" in source
    assert "expected.workflow_calls #>> '{0,$uuid}' = attempt.id::text" in source
    assert "result.output = expected.summary_json" in source
    assert "terminal.output_hash = expected.artifact_hash" in source
    assert "convert_to(expected.profile_summary, 'UTF8')" in source
    assert source.count("SECURITY DEFINER\nSET search_path = pg_catalog, public") >= 2


def test_status_projection_uses_result_ref_exact_attempt_after_success() -> None:
    source = UP.read_text(encoding="utf-8")
    assert "child.execution_backend, child.backend_lineage_source" in source
    assert "durable.result_ref =\n           'model-gateway://attempt/' || attempt.id::text" in source
    assert "durable.result_ref =\n           'dify-workflow://attempt/' || attempt.id::text" in source
    assert "durable.status <> 'succeeded'" in source
    assert "ORDER BY attempt.attempt_number DESC LIMIT 1" in source


def test_downgrade_refuses_data_loss_and_restores_0098_contract() -> None:
    source = DOWN.read_text(encoding="utf-8")
    assert "WHERE binding_source = 'runtime_review'" in source
    assert "cannot downgrade while post-migration Style Profile reviews exist" in source
    assert "DROP TABLE synthetic_lab_style_profile_build_bindings" in source
    assert "OR coalesce(metadata.profile_frozen, true) IS NOT TRUE" in source
    assert "AND metadata.domain_job_kind <> 'style_profile_build'" not in source
    assert "exact pinned Dify child backend" in source
    assert "child.execution_backend, child.backend_lineage_source" in source
    assert "durable.result_ref =\n           'model-gateway://attempt/'" not in source
    operation_contract = source.split(
        "ADD CONSTRAINT synthetic_lab_command_receipts_operation_check", 1
    )[1].split("));", 1)[0]
    assert "'freeze_profile', 'freeze_suite'" in operation_contract
    assert "submit_profile" not in operation_contract
