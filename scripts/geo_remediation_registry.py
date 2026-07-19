"""Executable evidence registry for the accepted GEO remediation clauses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EvidenceKind = Literal["pytest", "playwright", "command", "missing"]


@dataclass(frozen=True)
class EvidenceTarget:
    kind: EvidenceKind
    locator: str
    file: str | None = None
    project: str | None = None
    config: str | None = None
    behavior: bool = True
    reason: str | None = None


def pytest_target(node: str, *, behavior: bool = True) -> EvidenceTarget:
    return EvidenceTarget("pytest", node, behavior=behavior)


def playwright_target(
    file: str,
    title: str,
    *,
    project: str = "chromium-desktop",
    config: str = "playwright.config.ts",
) -> EvidenceTarget:
    return EvidenceTarget(
        "playwright",
        title,
        file=file,
        project=project,
        config=config,
    )


def command_target(command: str, *, behavior: bool = True) -> EvidenceTarget:
    return EvidenceTarget("command", command, behavior=behavior)


def missing_target(reason: str) -> EvidenceTarget:
    return EvidenceTarget("missing", "", behavior=False, reason=reason)


ADMIN_SPEC = "tests/browser/admin-geo-context.spec.ts"
CUSTOMER_SPEC = "tests/browser/customer-geo-portal.spec.ts"
ADMIN_CONFIG = "playwright.config.ts"
CUSTOMER_CONFIG = "playwright.customer.config.ts"

F012_TITLE = (
    "F012: Campaign switch clears every descendant context and invalid deep links "
    "do not select the first child"
)
F009_TITLE = (
    "F009: observation source controls expose only public capture methods and "
    "serialize provenance"
)
F021_TITLE = (
    "F021: frozen protocol strata can compute an auditable insufficient-evidence "
    "snapshot with zero samples"
)
F011_TITLE = (
    "F011: a failed public URL check is retried explicitly after external content "
    "correction"
)
F013_TITLE = (
    "F013: approved Fact becomes governed Evidence and remains traceable inside a "
    "rebuilt Evidence Pack"
)
F014_TITLE = (
    "F014: Opportunity binding and Bundle creation freeze the approved Prompt "
    "Release identity"
)
F019_TITLE = (
    "F019-WEB-01: Admin completes governed QuestionSet binding and a non-publishable "
    "GEO simulation"
)
F023_SCOPE_TITLE = (
    "F023: Project and Campaign never first-fallback and invalid deep links stay invalid"
)
F023_HISTORY_TITLE = (
    "F023: selector, modules, refresh and browser history preserve exact Campaign scope"
)
F023_EMPTY_TITLE = (
    "F023: no approved report and no Campaign are distinct, project switch clears Campaign"
)
F027_ADMIN_TITLE = "F027: Admin downloads Campaign-scoped reproducible project export ZIP"
F027_CUSTOMER_TITLE = (
    "F027: Customer downloads only the selected Campaign approved export ZIP"
)


TEST_EVIDENCE: dict[str, tuple[EvidenceTarget, ...]] = {
    "F015-CI-01": (
        pytest_target(
            "tests/test_ci_truth_contracts.py::"
            "test_required_integration_gate_rejects_missing_environment"
        ),
        command_target("make test-integration-required"),
    ),
    "F015-CI-02": (
        pytest_target(
            "tests/test_ci_truth_contracts.py::"
            "test_selected_skip_fails_and_reports_truthful_counts"
        ),
    ),
    "F015-INT-01": (
        pytest_target(
            "tests/integration/test_geo_acceptance_postgres.py::"
            "test_stable_geo_acceptance_closes_the_controlled_full_flow"
        ),
    ),
    "F015-INT-02": (
        pytest_target(
            "tests/integration/test_geo_acceptance_postgres.py::"
            "test_parallel_inline_runs_keep_tenant_project_and_artifacts_isolated"
        ),
    ),
    "F015-LIVE-01": (
        pytest_target(
            "tests/test_ci_truth_contracts.py::"
            "test_live_marker_collects_one_test_without_requesting_a_paid_call"
        ),
        command_target("make deepseek-live"),
    ),
    "F016-UNIT-01": (
        pytest_target(
            "tests/test_geo_acceptance_contract.py::"
            "test_inline_isolation_refuses_unproven_endpoint_principal_or_marker"
        ),
    ),
    "F016-INT-01": (
        pytest_target(
            "tests/integration/test_geo_acceptance_postgres.py::"
            "test_inline_acceptance_refuses_unproven_marker_before_business_writes"
        ),
    ),
    "F016-INT-02": (
        pytest_target(
            "tests/integration/test_geo_acceptance_postgres.py::"
            "test_parallel_inline_runs_keep_tenant_project_and_artifacts_isolated"
        ),
    ),
    "F016-CONTRACT-01": (
        pytest_target(
            "tests/test_geo_acceptance_contract.py::"
            "test_inline_adapter_manifest_does_not_claim_worker_relay_topology"
        ),
    ),
    "F001-INFRA-01": (
        pytest_target(
            "tests/infra/test_production_compose.py::"
            "test_production_networks_enforce_the_egress_boundary",
            behavior=False,
        ),
    ),
    "F001-INFRA-02": (
        pytest_target(
            "tests/infra/test_production_network_runtime.py::"
            "test_backend_only_probe_is_blocked_while_egress_probe_reaches_fixture"
        ),
        command_target("make test-production-network"),
    ),
    "F001-INT-01": (
        pytest_target(
            "tests/integration/test_egress_http_fixtures.py::"
            "test_f001_int_01_local_http_fixtures_cover_oidc_knowledge_model_and_publication"
        ),
    ),
    "F001-STAGE-01": (
        pytest_target(
            "tests/test_delivery_gate_contracts.py::"
            "test_staging_script_refuses_before_configuration_or_external_calls"
        ),
        pytest_target(
            "tests/test_delivery_gate_contracts.py::"
            "test_f001_stage_01_make_target_requires_both_opt_ins_without_leaking_values"
        ),
        pytest_target(
            "tests/test_delivery_gate_contracts.py::"
            "test_staging_configuration_rejects_group_readable_secret_files"
        ),
        pytest_target(
            "tests/test_delivery_gate_contracts.py::"
            "test_staging_smoke_writes_separate_redacted_evidence_with_four_checks"
        ),
        command_target("make geo-staging-smoke"),
    ),
    "F018-UNIT-01": (
        pytest_target(
            "tests/test_runtime_health.py::"
            "test_runtime_health_defaults_match_the_accepted_operational_thresholds"
        ),
        pytest_target(
            "tests/test_api_runtime_readiness.py::"
            "test_surface_probe_contract_rejects_missing_or_external_dependencies"
        ),
    ),
    "F018-INT-01": (
        pytest_target(
            "tests/integration/test_runtime_readiness_dependencies.py::"
            "test_real_dependency_failures_follow_the_internal_customer_readiness_matrix"
        ),
    ),
    "F018-INT-02": (
        pytest_target(
            "tests/integration/test_runtime_health_postgres.py::"
            "test_runtime_heartbeat_is_worker_only_and_staleness_is_real"
        ),
        pytest_target(
            "tests/integration/test_runtime_health_postgres.py::"
            "test_runtime_findings_classify_every_required_queue_state_without_sensitive_data"
        ),
    ),
    "F018-INFRA-01": (
        pytest_target(
            "tests/infra/test_production_compose.py::"
            "test_runtime_healthchecks_use_real_readiness_and_heartbeats",
            behavior=False,
        ),
        pytest_target(
            "tests/infra/test_compose_health_runtime.py::"
            "test_f018_infra_01_running_compose_changes_healthy_unhealthy_and_recovers"
        ),
        command_target("make test-infra-runtime"),
    ),
    "F018-PREFLIGHT-01": (
        pytest_target(
            "tests/infra/test_production_preflight.py::"
            "test_preflight_rejects_invalid_configuration_matrix"
        ),
        pytest_target(
            "tests/infra/test_production_preflight.py::"
            "test_preflight_reports_only_stable_codes_and_field_names"
        ),
        command_target("make production-preflight"),
    ),
    "F018-CONTRACT-01": (
        pytest_target(
            "tests/infra/test_production_compose.py::"
            "test_production_compose_does_not_claim_nonexistent_prometheus_metrics",
            behavior=False,
        ),
    ),
    "F012-DOMAIN-01": (
        pytest_target(
            "tests/unit/placements/test_campaign_prompt_contracts.py::"
            "test_campaign_resource_lineage_rejects_mixed_opportunities_and_campaigns"
        ),
    ),
    "F012-INT-01": (
        pytest_target(
            "tests/integration/test_placement_worker_postgres.py::"
            "test_multi_project_crash_recovery_and_full_worker_chain"
        ),
    ),
    "F012-WEB-01": (playwright_target(ADMIN_SPEC, F012_TITLE),),
    "F012-REG-01": (playwright_target(ADMIN_SPEC, F012_TITLE),),
    "F014-DOMAIN-01": (
        pytest_target(
            "tests/unit/placements/test_campaign_prompt_contracts.py::"
            "test_prompt_release_lifecycle_is_forward_only"
        ),
        pytest_target(
            "tests/unit/placements/test_placement_edit_review.py::"
            "test_prompt_releases_are_independent_and_old_release_is_unchanged"
        ),
    ),
    "F014-INT-01": (
        pytest_target(
            "tests/integration/test_placement_worker_postgres.py::"
            "test_multi_project_crash_recovery_and_full_worker_chain"
        ),
        pytest_target(
            "tests/integration/test_geo_acceptance_postgres.py::"
            "test_stable_geo_acceptance_closes_the_controlled_full_flow"
        ),
    ),
    "F014-INT-02": (
        pytest_target(
            "tests/integration/test_campaign_prompt_lifecycle_postgres.py::"
            "test_release_and_binding_same_key_concurrency_replays_one_append"
        ),
        pytest_target(
            "tests/unit/placements/test_campaign_prompt_contracts.py::"
            "test_campaign_readiness_has_exactly_nine_ordered_channels"
        ),
    ),
    "F014-WEB-01": (playwright_target(ADMIN_SPEC, F014_TITLE),),
    "F013-DOMAIN-01": (
        pytest_target(
            "tests/unit/knowledge/test_evidence_request.py::"
            "test_promotion_hash_is_canonical_and_binds_the_target_fact"
        ),
        pytest_target(
            "tests/test_fact_evidence_lineage_migration.py::"
            "test_fact_evidence_lineage_is_exact_idempotent_and_current_only_for_packs",
            behavior=False,
        ),
    ),
    "F013-INT-01": (
        pytest_target(
            "tests/integration/test_knowledge_fact_evidence_postgres.py::"
            "test_concurrent_fact_promotion_is_idempotent_and_pack_requires_verified_lineage"
        ),
    ),
    "F013-INT-02": (
        pytest_target(
            "tests/test_api_knowledge_fact_evidence.py::"
            "test_fact_evidence_post_requires_idempotency_and_forbids_derived_lineage"
        ),
        pytest_target(
            "tests/integration/test_knowledge_fact_evidence_postgres.py::"
            "test_concurrent_fact_promotion_is_idempotent_and_pack_requires_verified_lineage"
        ),
    ),
    "F013-WEB-01": (playwright_target(ADMIN_SPEC, F013_TITLE),),
    "F009-DOMAIN-01": (
        pytest_target(
            "tests/unit/monitoring/test_observation_source_contract.py::"
            "test_f009_domain_01_all_public_capture_methods_build_separate_strata"
        ),
        pytest_target(
            "tests/unit/monitoring/test_observation_source_contract.py::"
            "test_f009_domain_01_unknown_is_history_only_and_never_eligible"
        ),
    ),
    "F009-INT-01": (
        pytest_target(
            "tests/integration/test_monitoring_postgres.py::"
            "test_monitoring_rls_idempotency_immutability_and_frozen_metrics"
        ),
    ),
    "F009-INT-02": (
        pytest_target(
            "tests/unit/monitoring/test_observation_source_contract.py::"
            "test_f009_domain_01_artifact_must_be_server_verified"
        ),
        pytest_target(
            "tests/unit/monitoring/test_observation_source_contract.py::"
            "test_f009_domain_01_synthetic_requires_controlled_lineage_and_flags"
        ),
    ),
    "F009-MIG-01": (
        pytest_target(
            "tests/integration/test_batch2_migrations_postgres.py::"
            "test_populated_0011_fixture_round_trips_without_fabricating_truth"
        ),
    ),
    "F009-WEB-01": (playwright_target(ADMIN_SPEC, F009_TITLE),),
    "F011-UNIT-01": (
        pytest_target(
            "tests/unit/placements/test_url_verifier.py::"
            "test_f011_unit_01_empty_required_disclosures_is_an_explicit_passing_check"
        ),
        pytest_target(
            "tests/unit/placements/test_url_verifier.py::"
            "test_f011_unit_01_missing_required_disclosure_has_stable_permanent_failure"
        ),
        pytest_target(
            "tests/unit/placements/test_url_verifier.py::"
            "test_f011_unit_01_content_must_be_visible_and_evidence_retains_only_hashes"
        ),
    ),
    "F011-CONTRACT-01": (
        pytest_target(
            "tests/unit/placements/test_url_verifier.py::"
            "test_f011_contract_01_required_disclosures_must_be_an_explicit_array"
        ),
    ),
    "F011-INT-01": (
        pytest_target(
            "tests/integration/test_publication_verification_migration_postgres.py::"
            "test_verification_attempt_migration_round_trip_rls_and_append_only_contract"
        ),
    ),
    "F011-INT-02": (
        pytest_target(
            "tests/integration/test_placement_worker_postgres.py::"
            "test_multi_project_crash_recovery_and_full_worker_chain"
        ),
    ),
    "F011-WEB-01": (playwright_target(ADMIN_SPEC, F011_TITLE),),
    "F021-UNIT-01": (
        pytest_target(
            "tests/unit/monitoring/test_monitoring_metrics.py::"
            "test_minimum_three_valid_repeats_is_enforced_per_query"
        ),
        pytest_target(
            "tests/unit/monitoring/test_monitoring_metrics.py::"
            "test_five_repeat_protocol_requires_four_valid_results"
        ),
    ),
    "F021-UNIT-02": (
        pytest_target(
            "tests/unit/monitoring/test_monitoring_metrics.py::"
            "test_wilson_interval_uses_exact_unrounded_proportion"
        ),
        pytest_target(
            "tests/unit/monitoring/test_monitoring_metrics.py::"
            "test_same_frozen_input_has_reproducible_input_and_result_hashes"
        ),
        pytest_target(
            "tests/unit/monitoring/test_monitoring_metrics.py::"
            "test_failed_samples_are_confounded_and_source_strata_are_isolated"
        ),
    ),
    "F021-INT-01": (
        pytest_target(
            "tests/integration/test_monitoring_postgres.py::"
            "test_monitoring_rls_idempotency_immutability_and_frozen_metrics"
        ),
    ),
    "F021-INT-02": (
        pytest_target(
            "tests/integration/test_metric_observation_membership_migration_postgres.py::"
            "test_metric_membership_manifest_exact_lineage_rls_and_fail_closed_down"
        ),
        pytest_target(
            "tests/integration/test_monitoring_postgres.py::"
            "test_monitoring_rls_idempotency_immutability_and_frozen_metrics"
        ),
    ),
    "F021-WEB-01": (playwright_target(ADMIN_SPEC, F021_TITLE),),
    "F019-BENCH-01": (
        pytest_target(
            "tests/unit/f019_benchmark/test_selection_manifest.py::"
            "test_checked_in_selection_records_final_auditable_decision"
        ),
        command_target("make f019-benchmark"),
    ),
    "F019-ARCH-01": (
        pytest_target(
            "tests/architecture/test_rag_boundaries.py::"
            "test_stable_rag_contracts_native_and_selection_do_not_import_frameworks_or_benchmark",
            behavior=False,
        ),
    ),
    "F019-INT-01": (
        pytest_target(
            "tests/integration/test_knowledge_rag_postgres.py::"
            "test_f019_int_01_02_governed_rag_revision_archive_and_project_isolation"
        ),
    ),
    "F019-INT-02": (
        pytest_target(
            "tests/integration/test_knowledge_rag_postgres.py::"
            "test_f019_int_01_02_governed_rag_revision_archive_and_project_isolation"
        ),
    ),
    "F019-INT-03": (
        pytest_target(
            "tests/integration/test_knowledge_question_sets_postgres.py::"
            "test_f019_int_03_question_candidates_freeze_bind_and_immutable_versions"
        ),
    ),
    "F019-WEB-01": (
        playwright_target(ADMIN_SPEC, F019_TITLE),
    ),
    "F019-REG-01": (
        pytest_target(
            "tests/integration/test_prompt_simulation_postgres.py::"
            "test_prompt_simulation_is_durable_and_cannot_create_formal_placement_objects"
        ),
    ),
    "F023-UNIT-01": (
        pytest_target(
            "tests/integration/test_monitoring_postgres.py::"
            "test_monitoring_rls_idempotency_immutability_and_frozen_metrics"
        ),
    ),
    "F023-INT-01": (
        pytest_target(
            "tests/integration/test_monitoring_postgres.py::"
            "test_monitoring_rls_idempotency_immutability_and_frozen_metrics"
        ),
    ),
    "F023-INT-02": (
        pytest_target(
            "tests/test_api_monitoring_slice.py::"
            "test_customer_invalid_campaign_is_a_404_and_never_falls_back"
        ),
        pytest_target(
            "tests/test_api_monitoring_slice.py::"
            "test_customer_project_scope_is_enforced_before_read_model_access"
        ),
    ),
    "F023-WEB-01": (
        playwright_target(
            CUSTOMER_SPEC,
            F023_SCOPE_TITLE,
            project="customer-desktop",
            config=CUSTOMER_CONFIG,
        ),
        playwright_target(
            CUSTOMER_SPEC,
            F023_HISTORY_TITLE,
            project="customer-desktop",
            config=CUSTOMER_CONFIG,
        ),
        playwright_target(
            CUSTOMER_SPEC,
            F023_EMPTY_TITLE,
            project="customer-desktop",
            config=CUSTOMER_CONFIG,
        ),
    ),
    "F027-UNIT-01": (
        pytest_target(
            "tests/unit/project_exports/test_project_export_core.py::"
            "test_f027_unit_01_manifest_counts_hashes_columns_and_canonical_hash"
        ),
        pytest_target(
            "tests/unit/project_exports/test_project_export_core.py::"
            "test_f027_unit_01_customer_contract_is_approved_only"
        ),
    ),
    "F027-RECALC-01": (
        pytest_target(
            "tests/unit/project_exports/test_project_export_core.py::"
            "test_f027_recalc_01_recomputes_snapshot_from_export_bytes"
        ),
    ),
    "F027-INT-01": (
        pytest_target(
            "tests/integration/test_project_exports_postgres.py::"
            "test_f027_int_01_admin_customer_durable_minio_export_and_recalculation"
        ),
    ),
    "F027-INT-02": (
        pytest_target(
            "tests/integration/test_project_exports_postgres.py::"
            "test_f027_int_02_project_campaign_rls_and_customer_approved_only_isolation"
        ),
    ),
    "F027-WEB-01": (
        playwright_target(ADMIN_SPEC, F027_ADMIN_TITLE),
        playwright_target(
            CUSTOMER_SPEC,
            F027_CUSTOMER_TITLE,
            project="customer-desktop",
            config=CUSTOMER_CONFIG,
        ),
    ),
    "F025-MAP-01": (
        pytest_target(
            "tests/test_geo_remediation_traceability.py::"
            "test_all_acceptance_clauses_have_registered_executable_evidence"
        ),
    ),
    "F025-WEB-01": (
        playwright_target(ADMIN_SPEC, F012_TITLE),
        playwright_target(ADMIN_SPEC, F014_TITLE),
        playwright_target(ADMIN_SPEC, F011_TITLE),
    ),
    "F025-WEB-02": (
        playwright_target(ADMIN_SPEC, F013_TITLE),
        playwright_target(ADMIN_SPEC, F019_TITLE),
    ),
    "F025-WEB-03": (
        playwright_target(ADMIN_SPEC, F009_TITLE),
        playwright_target(ADMIN_SPEC, F021_TITLE),
        playwright_target(ADMIN_SPEC, F027_ADMIN_TITLE),
    ),
    "F025-WEB-04": (
        playwright_target(
            CUSTOMER_SPEC,
            F023_HISTORY_TITLE,
            project="customer-desktop",
            config=CUSTOMER_CONFIG,
        ),
        playwright_target(
            CUSTOMER_SPEC,
            F027_CUSTOMER_TITLE,
            project="customer-desktop",
            config=CUSTOMER_CONFIG,
        ),
    ),
    "F025-CONTRACT-01": (
        pytest_target(
            "tests/test_geo_remediation_traceability.py::"
            "test_ordinary_gate_is_chromium_desktop_without_unrelated_quality_thresholds",
            behavior=False,
        ),
    ),
}
