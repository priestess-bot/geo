DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM monitoring_observations
        WHERE source_contract_version = 'geo-observation-source-v2'
    ) OR EXISTS (
        SELECT 1 FROM monitoring_metric_snapshots
        WHERE source_contract_version = 'geo-observation-source-v2'
    ) OR EXISTS (
        SELECT 1 FROM monitoring_official_report_imports
    ) OR EXISTS (
        SELECT 1 FROM monitoring_protocols
        WHERE jsonb_array_length(source_strata_snapshot) > 0
           OR source_strata_hash IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM monitoring_query_suggestions
        WHERE query_cluster_key IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM monitoring_protocol_queries
        WHERE query_cluster_key IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: typed observation source data exists'
            USING ERRCODE = '55000';
    END IF;
END $$;

DROP TRIGGER IF EXISTS monitoring_official_report_rows_required
ON monitoring_official_report_imports;
DROP TRIGGER IF EXISTS monitoring_official_report_imports_immutable
ON monitoring_official_report_imports;
DROP TRIGGER IF EXISTS monitoring_official_report_rows_immutable
ON monitoring_official_report_rows;
DROP FUNCTION IF EXISTS geo_require_official_report_rows();
DROP TABLE monitoring_official_report_rows;
DROP TABLE monitoring_official_report_imports;

DROP TRIGGER IF EXISTS monitoring_metric_source_stratum_guard
ON monitoring_metric_snapshots;
DROP FUNCTION IF EXISTS geo_assert_new_metric_source_stratum();
DROP INDEX IF EXISTS monitoring_metric_snapshots_source_stratum_idx;
ALTER TABLE monitoring_metric_snapshots
    DROP CONSTRAINT monitoring_metric_source_slot_key,
    DROP CONSTRAINT monitoring_metric_legacy_shape_check,
    DROP CONSTRAINT monitoring_metric_source_contract_check,
    DROP CONSTRAINT monitoring_metric_capture_method_check,
    DROP CONSTRAINT monitoring_metric_source_stratum_hash_check,
    DROP CONSTRAINT monitoring_metric_source_stratum_type_check,
    DROP COLUMN source_contract_version,
    DROP COLUMN capture_method,
    DROP COLUMN source_stratum_hash,
    DROP COLUMN source_stratum;

DROP TRIGGER IF EXISTS monitoring_observation_citation_capture_guard
ON monitoring_observations;
DROP TRIGGER IF EXISTS monitoring_observation_source_guard ON monitoring_observations;
DROP TRIGGER IF EXISTS monitoring_observations_immutable ON monitoring_observations;
DROP FUNCTION IF EXISTS geo_require_observation_citation_capture();
DROP FUNCTION IF EXISTS geo_assert_new_observation_source();

ALTER TABLE monitoring_observations
    DROP CONSTRAINT monitoring_observations_legacy_shape_check;

UPDATE monitoring_observations AS observation
SET eligible = migration_state.eligible,
    ineligible_reasons = migration_state.ineligible_reasons
FROM monitoring_observation_legacy_migration_state AS migration_state
WHERE migration_state.observation_id = observation.id
  AND migration_state.project_id = observation.project_id;

DROP INDEX IF EXISTS monitoring_observations_model_call_fk_idx;
DROP INDEX IF EXISTS monitoring_observations_source_job_fk_idx;
DROP INDEX IF EXISTS monitoring_observations_source_stratum_idx;
ALTER TABLE monitoring_observations
    DROP CONSTRAINT monitoring_observations_source_slot_key,
    DROP CONSTRAINT monitoring_observations_model_call_fkey,
    DROP CONSTRAINT monitoring_observations_source_job_fkey,
    DROP CONSTRAINT monitoring_observations_source_job_pair_check,
    DROP CONSTRAINT monitoring_observations_source_stratum_hash_check,
    DROP CONSTRAINT monitoring_observations_source_contract_version_check,
    DROP CONSTRAINT monitoring_observations_raw_evidence_kind_check,
    DROP CONSTRAINT monitoring_observations_follow_up_prompts_check,
    DROP CONSTRAINT monitoring_observations_search_mode_check,
    DROP CONSTRAINT monitoring_observations_client_kind_check,
    DROP CONSTRAINT monitoring_observations_run_enum_check,
    DROP CONSTRAINT monitoring_observations_model_value_check,
    DROP CONSTRAINT monitoring_observations_model_state_check,
    DROP CONSTRAINT monitoring_observations_surface_kind_check,
    DROP CONSTRAINT monitoring_observations_surface_check,
    DROP CONSTRAINT monitoring_observations_platform_check,
    DROP CONSTRAINT monitoring_observations_capture_method_check,
    ADD CONSTRAINT monitoring_observations_protocol_id_monitoring_query_id_mea_key
        UNIQUE (
            protocol_id, monitoring_query_id, measurement_window, sample_index
        ),
    DROP COLUMN publication_eligible,
    DROP COLUMN test_only,
    DROP COLUMN model_call_log_id,
    DROP COLUMN source_job_id,
    DROP COLUMN query_cluster_key,
    DROP COLUMN source_stratum_hash,
    DROP COLUMN source_contract_version,
    DROP COLUMN citations_captured,
    DROP COLUMN raw_evidence_kind,
    DROP COLUMN provider_request_id,
    DROP COLUMN adapter_version,
    DROP COLUMN adapter_name,
    DROP COLUMN follow_up_prompts,
    DROP COLUMN prompt_text,
    DROP COLUMN search_mode,
    DROP COLUMN search_enabled,
    DROP COLUMN client_kind,
    DROP COLUMN observation_device,
    DROP COLUMN language,
    DROP COLUMN region,
    DROP COLUMN locale,
    DROP COLUMN provider_reported_model_state,
    DROP COLUMN configured_model_state,
    DROP COLUMN engine,
    DROP COLUMN surface_detail,
    DROP COLUMN surface_kind,
    DROP COLUMN surface,
    DROP COLUMN platform_detail,
    DROP COLUMN platform,
    DROP COLUMN capture_method,
    DROP COLUMN eligibility_requested,
    ALTER COLUMN configured_model SET NOT NULL;
CREATE TRIGGER monitoring_observations_immutable
BEFORE UPDATE OR DELETE ON monitoring_observations
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

ALTER TABLE model_call_logs DROP CONSTRAINT model_call_logs_exact_job_key;
DROP TABLE monitoring_observation_legacy_migration_state;

DROP TRIGGER IF EXISTS monitoring_protocol_query_cluster_guard
ON monitoring_protocol_queries;
DROP TRIGGER IF EXISTS monitoring_query_suggestion_cluster_guard
ON monitoring_query_suggestions;
DROP TRIGGER IF EXISTS monitoring_protocol_source_strata_guard ON monitoring_protocols;
DROP FUNCTION IF EXISTS geo_assert_new_query_cluster();
DROP FUNCTION IF EXISTS geo_assert_protocol_source_strata();
ALTER TABLE monitoring_protocol_queries DROP COLUMN query_cluster_key;
ALTER TABLE monitoring_query_suggestions DROP COLUMN query_cluster_key;
ALTER TABLE monitoring_protocols
    DROP CONSTRAINT monitoring_protocols_source_strata_pair_check,
    DROP COLUMN source_strata_hash,
    DROP COLUMN source_strata_snapshot;

DROP FUNCTION IF EXISTS geo_source_strata_inventory_hash(jsonb);
DROP FUNCTION IF EXISTS geo_source_stratum_hash_from_json(jsonb);
DROP FUNCTION IF EXISTS geo_source_stratum_json_valid(jsonb);
DROP FUNCTION IF EXISTS geo_observation_source_stratum_hash(
    text,text,text,text,text,text,text,text,text,text,text,text,text,text,boolean,text
);
DROP FUNCTION IF EXISTS geo_observation_source_stratum_canonical(
    text,text,text,text,text,text,text,text,text,text,text,text,text,text,boolean,text
);
DROP FUNCTION IF EXISTS geo_observation_surface_matches(text,text,text,text,text,text);
DROP FUNCTION IF EXISTS geo_ascii_nonempty(text);
