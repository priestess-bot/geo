DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM monitoring_protocols
        WHERE statistics_contract_version = 'geo-observation-statistics-v2'
    ) OR EXISTS (
        SELECT 1 FROM monitoring_metric_snapshots
        WHERE statistics_contract_version = 'geo-observation-statistics-v2'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: observation statistics v2 data exists'
            USING ERRCODE = '55000';
    END IF;
END $$;

DROP TRIGGER IF EXISTS monitoring_metric_statistics_guard
ON monitoring_metric_snapshots;
DROP FUNCTION IF EXISTS geo_assert_new_metric_statistics();
DROP INDEX IF EXISTS monitoring_metric_statistics_worst_query_idx;
DROP INDEX IF EXISTS monitoring_metric_statistics_latest_idx;

ALTER TABLE monitoring_metric_snapshots
    DROP CONSTRAINT monitoring_metric_statistics_slot_key,
    DROP CONSTRAINT monitoring_metric_statistics_worst_query_fkey,
    DROP CONSTRAINT monitoring_metric_statistics_shape_check,
    DROP CONSTRAINT monitoring_metric_statistics_contract_check,
    DROP CONSTRAINT monitoring_metric_statistics_status_check,
    DROP CONSTRAINT monitoring_metric_snapshots_status_check,
    DROP COLUMN result_hash,
    DROP COLUMN verified_destination_ids,
    DROP COLUMN qualified_destination_ids,
    DROP COLUMN selected_destination_ids,
    DROP COLUMN worst_query_id,
    DROP COLUMN placement_citation_query_max,
    DROP COLUMN placement_citation_query_min,
    DROP COLUMN product_mention_query_max,
    DROP COLUMN product_mention_query_min,
    DROP COLUMN recommendation_query_max,
    DROP COLUMN recommendation_query_min,
    DROP COLUMN placement_citation_ci_high,
    DROP COLUMN placement_citation_ci_low,
    DROP COLUMN product_mention_ci_high,
    DROP COLUMN product_mention_ci_low,
    DROP COLUMN recommendation_ci_high,
    DROP COLUMN recommendation_ci_low,
    DROP COLUMN query_results_snapshot,
    DROP COLUMN declared_confounding_factors,
    DROP COLUMN invalid_reason_counts,
    DROP COLUMN sufficient_query_count,
    DROP COLUMN query_count,
    DROP COLUMN valid_completion_ratio,
    DROP COLUMN sampling_completion_ratio,
    DROP COLUMN missing_sample_count,
    DROP COLUMN invalid_sample_count,
    DROP COLUMN sampled_sample_count,
    DROP COLUMN minimum_valid_repeats,
    DROP COLUMN analysis_stratum_hash,
    DROP COLUMN query_cluster_key,
    DROP COLUMN statistics_contract_version,
    ADD CONSTRAINT monitoring_metric_snapshots_status_check CHECK (
        status IN ('complete', 'confounded')
    ),
    ADD CONSTRAINT monitoring_metric_snapshots_check1 CHECK (
        (status = 'confounded') = (cardinality(confounded_reasons) > 0)
    ),
    ADD CONSTRAINT monitoring_metric_snapshots_protocol_id_measurement_window__key
        UNIQUE (protocol_id, measurement_window, input_hash),
    ADD CONSTRAINT monitoring_metric_source_slot_key UNIQUE NULLS NOT DISTINCT (
        protocol_id, measurement_window, source_stratum_hash, input_hash
    );

CREATE INDEX monitoring_metric_snapshots_source_stratum_idx
ON monitoring_metric_snapshots (
    project_id, protocol_id, measurement_window, source_stratum_hash,
    computed_at DESC
);

DROP FUNCTION IF EXISTS geo_statistics_estimate_valid(jsonb,integer);
DROP FUNCTION IF EXISTS geo_positive_integer_object(jsonb);
DROP FUNCTION IF EXISTS geo_text_array_is_canonical_set(text[]);
DROP FUNCTION IF EXISTS geo_uuid_array_is_set(uuid[]);
DROP FUNCTION IF EXISTS geo_analysis_stratum_hash(text,text);
DROP FUNCTION IF EXISTS geo_json_ascii_string(text);

DROP TRIGGER IF EXISTS monitoring_protocol_statistics_guard ON monitoring_protocols;
DROP FUNCTION IF EXISTS geo_assert_new_protocol_statistics();
ALTER TABLE monitoring_protocols
    DROP CONSTRAINT monitoring_protocols_statistics_contract_check,
    DROP COLUMN statistics_method_version,
    DROP COLUMN minimum_valid_repeats,
    DROP COLUMN statistics_contract_version;
