DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM generation_template_release_states
        WHERE NOT is_legacy_backfill OR state_version <> 1 OR status <> 'approved'
    ) OR EXISTS (
        SELECT 1 FROM opportunity_prompt_release_bindings
        WHERE NOT is_legacy_backfill OR binding_version <> 1 OR binding_state <> 'unbound'
    ) OR EXISTS (
        SELECT 1 FROM prompt_bundles
        WHERE binding_contract_version = 'opportunity-binding-v2'
    ) OR EXISTS (
        SELECT 1 FROM prompt_simulations
        WHERE binding_contract_version = 'opportunity-binding-v2'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: Campaign Prompt context contains v2 audit data'
            USING ERRCODE = '55000';
    END IF;
END $$;

DROP TRIGGER IF EXISTS placement_opportunities_campaign_lineage_immutable
ON placement_opportunities;
DROP TRIGGER IF EXISTS placement_briefs_campaign_lineage_immutable ON placement_briefs;
DROP TRIGGER IF EXISTS evidence_pack_attempts_campaign_lineage_immutable
ON evidence_pack_attempts;
DROP TRIGGER IF EXISTS placement_packages_campaign_lineage_immutable ON placement_packages;
DROP TRIGGER IF EXISTS placement_package_versions_campaign_lineage_immutable
ON placement_package_versions;
DROP TRIGGER IF EXISTS publication_requests_campaign_lineage_immutable
ON publication_requests;
DROP TRIGGER IF EXISTS publication_submissions_campaign_lineage_immutable
ON publication_submissions;
DROP TRIGGER IF EXISTS placement_measurements_campaign_lineage_immutable
ON placement_measurements;
DROP TRIGGER IF EXISTS measurement_collection_tasks_campaign_lineage_immutable
ON measurement_collection_tasks;
DROP FUNCTION IF EXISTS geo_reject_campaign_lineage_update();

DROP TRIGGER IF EXISTS artifact_finalize_outbox_delete_guard ON artifact_finalize_outbox;
DROP TRIGGER IF EXISTS artifact_finalize_outbox_identity_immutable
ON artifact_finalize_outbox;
DROP FUNCTION IF EXISTS geo_protect_artifact_finalize_identity();
DROP TRIGGER IF EXISTS prompt_simulation_job_specs_delete_guard
ON prompt_simulation_job_specs;
DROP TRIGGER IF EXISTS prompt_simulation_job_specs_immutable
ON prompt_simulation_job_specs;
DROP TRIGGER IF EXISTS measurement_job_specs_delete_guard ON measurement_job_specs;
DROP TRIGGER IF EXISTS measurement_job_specs_immutable ON measurement_job_specs;
DROP TRIGGER IF EXISTS verification_job_specs_delete_guard ON verification_job_specs;
DROP TRIGGER IF EXISTS verification_job_specs_immutable ON verification_job_specs;
DROP TRIGGER IF EXISTS generation_job_specs_delete_guard ON generation_job_specs;
DROP TRIGGER IF EXISTS generation_job_specs_immutable ON generation_job_specs;
DROP TRIGGER IF EXISTS evidence_pack_job_specs_delete_guard ON evidence_pack_job_specs;
DROP TRIGGER IF EXISTS evidence_pack_job_specs_immutable ON evidence_pack_job_specs;
DROP FUNCTION IF EXISTS geo_require_job_deleted_with_spec();
DROP FUNCTION IF EXISTS geo_reject_placement_job_spec_update();

DROP TRIGGER IF EXISTS artifact_finalize_campaign_guard ON artifact_finalize_outbox;
DROP FUNCTION IF EXISTS geo_assert_artifact_campaign_context();
DROP TRIGGER IF EXISTS durable_job_campaign_spec_guard ON durable_jobs;
DROP TRIGGER IF EXISTS durable_job_campaign_guard ON durable_jobs;
DROP FUNCTION IF EXISTS geo_require_durable_job_campaign_spec();
DROP FUNCTION IF EXISTS geo_assert_new_durable_job_campaign();
DROP TRIGGER IF EXISTS prompt_simulation_results_new_contract_guard
ON prompt_simulation_results;
DROP FUNCTION IF EXISTS geo_assert_new_prompt_simulation_result();

DROP INDEX IF EXISTS prompt_simulations_binding_fk_idx;
DROP INDEX IF EXISTS opportunity_prompt_bindings_actor_fk_idx;
DROP INDEX IF EXISTS opportunity_prompt_bindings_previous_fk_idx;
DROP INDEX IF EXISTS opportunity_prompt_bindings_release_fk_idx;
DROP INDEX IF EXISTS opportunity_prompt_bindings_opportunity_fk_idx;
DROP INDEX IF EXISTS generation_template_release_states_actor_fk_idx;
DROP INDEX IF EXISTS generation_template_release_states_previous_fk_idx;
DROP INDEX IF EXISTS generation_template_release_states_release_fk_idx;
DROP INDEX IF EXISTS placement_export_receipts_version_fk_idx;
DROP INDEX IF EXISTS prompt_simulations_release_fk_idx;
DROP INDEX IF EXISTS prompt_simulations_opportunity_fk_idx;
DROP INDEX IF EXISTS prompt_simulation_results_job_spec_fk_idx;
DROP INDEX IF EXISTS prompt_simulation_results_simulation_fk_idx;
DROP INDEX IF EXISTS artifact_finalize_outbox_job_campaign_fk_idx;
DROP INDEX IF EXISTS prompt_simulation_job_specs_simulation_fk_idx;
DROP INDEX IF EXISTS prompt_simulation_job_specs_job_fk_idx;
DROP INDEX IF EXISTS measurement_job_specs_protocol_fk_idx;
DROP INDEX IF EXISTS measurement_job_specs_job_fk_idx;
DROP INDEX IF EXISTS measurement_job_specs_submission_fk_idx;
DROP INDEX IF EXISTS measurement_collection_tasks_protocol_fk_idx;
DROP INDEX IF EXISTS verification_job_specs_submission_fk_idx;
DROP INDEX IF EXISTS verification_job_specs_job_fk_idx;
DROP INDEX IF EXISTS generation_job_specs_bundle_fk_idx;
DROP INDEX IF EXISTS generation_job_specs_job_fk_idx;
DROP INDEX IF EXISTS evidence_pack_job_specs_attempt_fk_idx;
DROP INDEX IF EXISTS evidence_pack_job_specs_job_fk_idx;
DROP INDEX IF EXISTS durable_jobs_parent_campaign_fk_idx;
DROP INDEX IF EXISTS durable_jobs_campaign_fk_idx;
DROP INDEX IF EXISTS measurement_collection_tasks_submission_fk_idx;
DROP INDEX IF EXISTS placement_measurements_submission_fk_idx;
DROP INDEX IF EXISTS publication_requests_package_version_fk_idx;
DROP INDEX IF EXISTS placement_package_versions_package_fk_idx;
DROP INDEX IF EXISTS placement_packages_opportunity_fk_idx;
DROP INDEX IF EXISTS evidence_pack_attempts_brief_version_fk_idx;
DROP INDEX IF EXISTS placement_brief_versions_brief_fk_idx;
DROP INDEX IF EXISTS placement_briefs_opportunity_fk_idx;
DROP INDEX IF EXISTS placement_measurements_campaign_query_fk_idx;
DROP INDEX IF EXISTS publication_submissions_request_fk_idx;
DROP INDEX IF EXISTS placement_package_versions_generated_job_fk_idx;
DROP INDEX IF EXISTS placement_package_versions_generation_spec_fk_idx;
DROP INDEX IF EXISTS placement_package_versions_base_fk_idx;
DROP INDEX IF EXISTS placement_package_versions_bundle_fk_idx;
DROP INDEX IF EXISTS prompt_bundles_binding_fk_idx;
DROP INDEX IF EXISTS prompt_bundles_release_fk_idx;
DROP INDEX IF EXISTS prompt_bundles_evidence_attempt_fk_idx;
DROP INDEX IF EXISTS prompt_bundles_brief_version_fk_idx;
DROP INDEX IF EXISTS evidence_pack_attempts_superseded_fk_idx;
DROP INDEX IF EXISTS placement_brief_versions_base_fk_idx;
DROP INDEX IF EXISTS measurement_collection_tasks_job_spec_fk_idx;

ALTER TABLE prompt_simulation_results
    DROP CONSTRAINT prompt_simulation_results_exact_job_spec_fkey,
    DROP CONSTRAINT prompt_simulation_results_exact_simulation_fkey,
    DROP CONSTRAINT prompt_simulation_results_lineage_contract_check,
    DROP COLUMN lineage_contract_version,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;

DROP INDEX IF EXISTS artifact_finalize_outbox_campaign_idx;
ALTER TABLE artifact_finalize_outbox
    DROP CONSTRAINT artifact_finalize_outbox_exact_job_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;

DROP INDEX IF EXISTS prompt_simulation_job_specs_campaign_idx;
ALTER TABLE prompt_simulation_job_specs
    DROP CONSTRAINT prompt_simulation_job_specs_exact_result_key,
    DROP CONSTRAINT prompt_simulation_job_specs_exact_simulation_fkey,
    DROP CONSTRAINT prompt_simulation_job_specs_exact_job_fkey,
    DROP CONSTRAINT prompt_simulation_job_specs_campaign_pair_check,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;

DROP INDEX IF EXISTS measurement_job_specs_campaign_idx;
ALTER TABLE measurement_collection_tasks
    DROP CONSTRAINT measurement_collection_tasks_exact_job_spec_fkey;
ALTER TABLE measurement_job_specs
    DROP CONSTRAINT measurement_job_specs_exact_collection_key,
    DROP CONSTRAINT measurement_job_specs_exact_protocol_fkey,
    DROP CONSTRAINT measurement_job_specs_exact_submission_fkey,
    DROP CONSTRAINT measurement_job_specs_exact_job_fkey,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS verification_job_specs_campaign_idx;
ALTER TABLE verification_job_specs
    DROP CONSTRAINT verification_job_specs_exact_submission_fkey,
    DROP CONSTRAINT verification_job_specs_exact_job_fkey,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS generation_job_specs_campaign_idx;
ALTER TABLE placement_package_versions
    DROP CONSTRAINT placement_package_versions_exact_generation_spec_fkey,
    DROP CONSTRAINT placement_package_versions_exact_generated_job_fkey;
ALTER TABLE generation_job_specs
    DROP CONSTRAINT generation_job_specs_exact_generation_key,
    DROP CONSTRAINT generation_job_specs_exact_bundle_fkey,
    DROP CONSTRAINT generation_job_specs_exact_job_fkey,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS evidence_pack_job_specs_campaign_idx;
ALTER TABLE evidence_pack_job_specs
    DROP CONSTRAINT evidence_pack_job_specs_exact_attempt_fkey,
    DROP CONSTRAINT evidence_pack_job_specs_exact_job_fkey,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;

DROP INDEX IF EXISTS durable_jobs_campaign_activity_idx;
ALTER TABLE durable_jobs
    DROP CONSTRAINT durable_jobs_exact_parent_campaign_fkey,
    DROP CONSTRAINT durable_jobs_exact_campaign_key,
    DROP CONSTRAINT durable_jobs_campaign_fkey,
    DROP COLUMN campaign_id;

CREATE OR REPLACE FUNCTION geo_assert_prompt_simulation_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    destination_channel text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM product_entities entity
        WHERE entity.id = NEW.primary_brand_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'brand' AND entity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'prompt simulation primary brand must reference an active brand'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM product_entities entity
        WHERE entity.id = NEW.product_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'product' AND entity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'prompt simulation product must reference an active product'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.destination_policy_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM destination_policy_versions policy
        WHERE policy.id = NEW.destination_policy_version_id
          AND policy.project_id = NEW.project_id
          AND policy.destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'prompt simulation policy does not belong to its destination'
            USING ERRCODE = '23514';
    END IF;
    SELECT destination.publication_channel INTO destination_channel
    FROM publication_destinations destination
    WHERE destination.id = NEW.destination_id
      AND destination.project_id = NEW.project_id;
    IF NOT EXISTS (
        SELECT 1 FROM content_task_prompt_releases binding
        WHERE binding.project_id = NEW.project_id
          AND binding.task_key = destination_channel
          AND binding.template_release_id = NEW.template_release_id
    ) THEN
        RAISE EXCEPTION 'prompt simulation release is not selected for its destination channel'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE prompt_simulations
    DROP CONSTRAINT prompt_simulations_exact_context_key,
    DROP CONSTRAINT prompt_simulations_exact_binding_fkey,
    DROP CONSTRAINT prompt_simulations_exact_release_fkey,
    DROP CONSTRAINT prompt_simulations_exact_opportunity_fkey,
    DROP CONSTRAINT prompt_simulations_template_release_hash_check,
    DROP CONSTRAINT prompt_simulations_binding_contract_check,
    DROP CONSTRAINT prompt_simulations_binding_contract_version_check,
    DROP COLUMN binding_contract_version,
    DROP COLUMN template_release_hash,
    DROP COLUMN template_release_number,
    DROP COLUMN template_skill_version_id,
    DROP COLUMN binding_version,
    DROP COLUMN binding_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;

DROP INDEX IF EXISTS measurement_collection_tasks_campaign_idx;
ALTER TABLE measurement_collection_tasks
    DROP CONSTRAINT measurement_collection_tasks_exact_protocol_fkey,
    DROP CONSTRAINT measurement_collection_tasks_exact_submission_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS placement_measurements_campaign_idx;
DROP INDEX IF EXISTS placement_measurements_campaign_query_idx;
ALTER TABLE placement_measurements
    DROP CONSTRAINT placement_measurements_exact_campaign_query_fkey,
    DROP CONSTRAINT placement_measurements_exact_submission_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS publication_submissions_campaign_idx;
ALTER TABLE publication_submissions
    DROP CONSTRAINT publication_submissions_job_context_key,
    DROP CONSTRAINT publication_submissions_exact_context_key,
    DROP CONSTRAINT publication_submissions_exact_request_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS publication_requests_campaign_idx;
ALTER TABLE publication_requests
    DROP CONSTRAINT publication_requests_exact_context_key,
    DROP CONSTRAINT publication_requests_exact_package_version_fkey,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
ALTER TABLE placement_export_receipts
    DROP CONSTRAINT placement_export_receipts_exact_version_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS placement_package_versions_campaign_idx;
ALTER TABLE placement_package_versions
    DROP CONSTRAINT placement_package_versions_exact_context_key,
    DROP CONSTRAINT placement_package_versions_exact_base_fkey,
    DROP CONSTRAINT placement_package_versions_exact_lineage_key,
    DROP CONSTRAINT placement_package_versions_exact_bundle_fkey,
    DROP CONSTRAINT placement_package_versions_exact_package_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS placement_packages_campaign_idx;
ALTER TABLE placement_packages
    DROP CONSTRAINT placement_packages_exact_context_key,
    DROP CONSTRAINT placement_packages_exact_opportunity_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN campaign_id;

DROP TRIGGER IF EXISTS prompt_bundle_binding_guard ON prompt_bundles;
DROP FUNCTION IF EXISTS geo_assert_prompt_bundle_binding();
DROP INDEX IF EXISTS prompt_bundles_idempotency_key;
DROP INDEX IF EXISTS prompt_bundles_campaign_idx;
ALTER TABLE prompt_bundles
    DROP CONSTRAINT prompt_bundles_job_context_key,
    DROP CONSTRAINT prompt_bundles_exact_context_key,
    DROP CONSTRAINT prompt_bundles_exact_binding_fkey,
    DROP CONSTRAINT prompt_bundles_exact_release_fkey,
    DROP CONSTRAINT prompt_bundles_exact_evidence_attempt_fkey,
    DROP CONSTRAINT prompt_bundles_exact_brief_version_fkey,
    DROP CONSTRAINT prompt_bundles_template_release_hash_check,
    DROP CONSTRAINT prompt_bundles_binding_contract_version_check,
    DROP CONSTRAINT prompt_bundles_binding_contract_check,
    DROP CONSTRAINT prompt_bundles_v2_idempotency_check,
    DROP CONSTRAINT prompt_bundles_idempotency_pair_check,
    DROP CONSTRAINT prompt_bundles_command_hash_check,
    DROP CONSTRAINT prompt_bundles_idempotency_key_check,
    DROP COLUMN binding_contract_version,
    DROP COLUMN command_hash,
    DROP COLUMN idempotency_key,
    DROP COLUMN template_release_hash,
    DROP COLUMN template_release_number,
    DROP COLUMN template_skill_version_id,
    DROP COLUMN binding_version,
    DROP COLUMN binding_id,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;

DROP INDEX IF EXISTS evidence_pack_attempts_campaign_idx;
ALTER TABLE evidence_pack_attempts
    DROP CONSTRAINT evidence_pack_attempts_job_context_key,
    DROP CONSTRAINT evidence_pack_attempts_exact_superseded_by_fkey,
    DROP CONSTRAINT evidence_pack_attempts_exact_bundle_context_key,
    DROP CONSTRAINT evidence_pack_attempts_exact_brief_context_key,
    DROP CONSTRAINT evidence_pack_attempts_exact_context_key,
    DROP CONSTRAINT evidence_pack_attempts_exact_brief_version_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS placement_brief_versions_campaign_idx;
ALTER TABLE placement_brief_versions
    DROP CONSTRAINT placement_brief_versions_exact_context_key,
    DROP CONSTRAINT placement_brief_versions_exact_base_fkey,
    DROP CONSTRAINT placement_brief_versions_exact_lineage_key,
    DROP CONSTRAINT placement_brief_versions_exact_brief_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN opportunity_id,
    DROP COLUMN campaign_id;
DROP INDEX IF EXISTS placement_briefs_campaign_idx;
ALTER TABLE placement_briefs
    DROP CONSTRAINT placement_briefs_exact_context_key,
    DROP CONSTRAINT placement_briefs_exact_opportunity_fkey,
    DROP COLUMN destination_id,
    DROP COLUMN campaign_id;

DROP TRIGGER IF EXISTS placement_opportunity_requires_initial_binding
ON placement_opportunities;
DROP FUNCTION IF EXISTS geo_require_opportunity_initial_binding();
DROP VIEW IF EXISTS current_opportunity_prompt_release_bindings;
DROP TRIGGER IF EXISTS opportunity_prompt_release_bindings_immutable
ON opportunity_prompt_release_bindings;
DROP TRIGGER IF EXISTS opportunity_prompt_binding_append_guard
ON opportunity_prompt_release_bindings;
DROP FUNCTION IF EXISTS geo_protect_opportunity_prompt_binding();
DROP FUNCTION IF EXISTS geo_assert_opportunity_prompt_binding_append();
DROP TABLE opportunity_prompt_release_bindings;
ALTER TABLE placement_opportunities
    DROP CONSTRAINT placement_opportunities_exact_context_key;
ALTER TABLE campaign_monitoring_queries
    DROP CONSTRAINT campaign_monitoring_queries_exact_context_key;

DROP TRIGGER IF EXISTS generation_template_release_requires_state
ON generation_template_releases;
DROP FUNCTION IF EXISTS geo_require_release_initial_state();
DROP VIEW IF EXISTS current_generation_template_release_states;
DROP TRIGGER IF EXISTS generation_template_release_states_immutable
ON generation_template_release_states;
DROP TRIGGER IF EXISTS generation_template_release_state_append_guard
ON generation_template_release_states;
DROP FUNCTION IF EXISTS geo_protect_append_only_release_state();
DROP FUNCTION IF EXISTS geo_assert_release_state_append();
DROP TABLE generation_template_release_states;
ALTER TABLE generation_template_releases
    DROP CONSTRAINT generation_template_releases_exact_identity_key;
