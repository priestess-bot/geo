ALTER TABLE monitoring_protocols
    ADD COLUMN statistics_contract_version text NOT NULL DEFAULT 'legacy-v1',
    ADD COLUMN minimum_valid_repeats integer,
    ADD COLUMN statistics_method_version text,
    ALTER COLUMN statistics_contract_version
        SET DEFAULT 'geo-observation-statistics-v2',
    ADD CONSTRAINT monitoring_protocols_statistics_contract_check CHECK (
        (statistics_contract_version = 'legacy-v1'
            AND minimum_valid_repeats IS NULL
            AND statistics_method_version IS NULL)
        OR
        (statistics_contract_version = 'geo-observation-statistics-v2'
            AND sample_size >= 3
            AND minimum_valid_repeats BETWEEN 3 AND sample_size
            AND minimum_valid_repeats * 5 >= sample_size * 4
            AND statistics_method_version = 'geo-observation-statistics-v2')
    );

CREATE FUNCTION geo_assert_new_protocol_statistics() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.statistics_contract_version <> 'geo-observation-statistics-v2' THEN
        RAISE EXCEPTION 'new monitoring protocols require statistics v2'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.sample_size < 3
       OR NEW.minimum_valid_repeats < 3
       OR NEW.minimum_valid_repeats > NEW.sample_size
       OR NEW.minimum_valid_repeats * 5 < NEW.sample_size * 4
       OR NEW.statistics_method_version <> 'geo-observation-statistics-v2' THEN
        RAISE EXCEPTION 'monitoring protocol repeat threshold is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER monitoring_protocol_statistics_guard
BEFORE INSERT ON monitoring_protocols
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_protocol_statistics();

CREATE FUNCTION geo_json_ascii_string(input_value text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
DECLARE
    output_value text := '"';
    character_value text;
    codepoint integer;
    adjusted integer;
    high_surrogate integer;
    low_surrogate integer;
    index_value integer;
BEGIN
    FOR index_value IN 1..char_length(input_value) LOOP
        character_value := substr(input_value, index_value, 1);
        codepoint := ascii(character_value);
        IF codepoint = 8 THEN
            output_value := output_value || chr(92) || 'b';
        ELSIF codepoint = 9 THEN
            output_value := output_value || chr(92) || 't';
        ELSIF codepoint = 10 THEN
            output_value := output_value || chr(92) || 'n';
        ELSIF codepoint = 12 THEN
            output_value := output_value || chr(92) || 'f';
        ELSIF codepoint = 13 THEN
            output_value := output_value || chr(92) || 'r';
        ELSIF codepoint = 34 THEN
            output_value := output_value || chr(92) || '"';
        ELSIF codepoint = 92 THEN
            output_value := output_value || chr(92) || chr(92);
        ELSIF codepoint BETWEEN 32 AND 126 THEN
            output_value := output_value || character_value;
        ELSIF codepoint <= 65535 THEN
            output_value := output_value || chr(92) || 'u'
                || lpad(to_hex(codepoint), 4, '0');
        ELSE
            adjusted := codepoint - 65536;
            high_surrogate := 55296 + (adjusted >> 10);
            low_surrogate := 56320 + (adjusted & 1023);
            output_value := output_value || chr(92) || 'u'
                || lpad(to_hex(high_surrogate), 4, '0')
                || chr(92) || 'u' || lpad(to_hex(low_surrogate), 4, '0');
        END IF;
    END LOOP;
    RETURN output_value || '"';
END;
$$;

CREATE FUNCTION geo_analysis_stratum_hash(
    query_cluster_key text, source_stratum_hash text
) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT encode(
        digest(
            convert_to(
                '{"query_cluster_key":' || geo_json_ascii_string(query_cluster_key)
                || ',"source_stratum_hash":'
                || geo_json_ascii_string(source_stratum_hash) || '}',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
$$;

CREATE FUNCTION geo_uuid_array_is_set(input_value uuid[]) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT array_position(input_value, NULL) IS NULL
       AND cardinality(input_value) = (
            SELECT count(DISTINCT item) FROM unnest(input_value) AS item
       )
$$;

CREATE FUNCTION geo_text_array_is_canonical_set(input_value text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT array_position(input_value, NULL) IS NULL
       AND NOT EXISTS (
            SELECT 1 FROM unnest(input_value) AS item WHERE btrim(item) = ''
       )
       AND input_value = COALESCE(
            (
                SELECT array_agg(item ORDER BY item COLLATE "C")
                FROM (
                    SELECT DISTINCT item FROM unnest(input_value) AS item
                ) AS canonical
            ),
            ARRAY[]::text[]
       )
$$;

CREATE FUNCTION geo_positive_integer_object(input_value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT jsonb_typeof(input_value) = 'object'
       AND NOT EXISTS (
            SELECT 1
            FROM jsonb_each(input_value) AS entry(key, value)
            WHERE btrim(entry.key) = ''
               OR jsonb_typeof(entry.value) <> 'number'
               OR entry.value::text !~ '^[1-9][0-9]*$'
       )
$$;

CREATE FUNCTION geo_statistics_estimate_valid(
    estimate jsonb, valid_sample_count integer
) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT jsonb_typeof(estimate) = 'object'
       AND estimate ?& ARRAY['numerator', 'denominator', 'share', 'ci_low', 'ci_high']
       AND (SELECT count(*) FROM jsonb_object_keys(estimate)) = 5
       AND jsonb_typeof(estimate -> 'numerator') = 'number'
       AND jsonb_typeof(estimate -> 'denominator') = 'number'
       AND jsonb_typeof(estimate -> 'share') = 'number'
       AND jsonb_typeof(estimate -> 'ci_low') = 'number'
       AND jsonb_typeof(estimate -> 'ci_high') = 'number'
       AND estimate ->> 'numerator' ~ '^(0|[1-9][0-9]*)$'
       AND estimate ->> 'denominator' ~ '^(0|[1-9][0-9]*)$'
       AND (estimate ->> 'denominator')::integer = valid_sample_count
       AND (estimate ->> 'numerator')::integer BETWEEN 0 AND valid_sample_count
       AND (estimate ->> 'share')::numeric BETWEEN 0 AND 1
       AND (estimate ->> 'ci_low')::numeric BETWEEN 0 AND 1
       AND (estimate ->> 'ci_high')::numeric BETWEEN 0 AND 1
       AND (estimate ->> 'ci_low')::numeric <= (estimate ->> 'ci_high')::numeric
       AND (
            (valid_sample_count = 0
                AND (estimate ->> 'numerator')::integer = 0
                AND (estimate ->> 'share')::numeric = 0
                AND (estimate ->> 'ci_low')::numeric = 0
                AND (estimate ->> 'ci_high')::numeric = 1)
            OR
            (valid_sample_count > 0
                AND (estimate ->> 'share')::numeric = round(
                    (estimate ->> 'numerator')::numeric / valid_sample_count,
                    6
                ))
       )
$$;

ALTER TABLE monitoring_metric_snapshots
    DROP CONSTRAINT monitoring_metric_snapshots_status_check,
    DROP CONSTRAINT monitoring_metric_snapshots_check1,
    DROP CONSTRAINT monitoring_metric_snapshots_protocol_id_measurement_window__key,
    DROP CONSTRAINT monitoring_metric_source_slot_key,
    ADD COLUMN statistics_contract_version text NOT NULL DEFAULT 'legacy-v1',
    ADD COLUMN query_cluster_key text,
    ADD COLUMN analysis_stratum_hash text,
    ADD COLUMN minimum_valid_repeats integer,
    ADD COLUMN sampled_sample_count integer,
    ADD COLUMN invalid_sample_count integer,
    ADD COLUMN missing_sample_count integer,
    ADD COLUMN sampling_completion_ratio numeric(9,6),
    ADD COLUMN valid_completion_ratio numeric(9,6),
    ADD COLUMN query_count integer,
    ADD COLUMN sufficient_query_count integer,
    ADD COLUMN invalid_reason_counts jsonb,
    ADD COLUMN declared_confounding_factors text[],
    ADD COLUMN query_results_snapshot jsonb,
    ADD COLUMN recommendation_ci_low numeric(9,6),
    ADD COLUMN recommendation_ci_high numeric(9,6),
    ADD COLUMN product_mention_ci_low numeric(9,6),
    ADD COLUMN product_mention_ci_high numeric(9,6),
    ADD COLUMN placement_citation_ci_low numeric(9,6),
    ADD COLUMN placement_citation_ci_high numeric(9,6),
    ADD COLUMN recommendation_query_min numeric(9,6),
    ADD COLUMN recommendation_query_max numeric(9,6),
    ADD COLUMN product_mention_query_min numeric(9,6),
    ADD COLUMN product_mention_query_max numeric(9,6),
    ADD COLUMN placement_citation_query_min numeric(9,6),
    ADD COLUMN placement_citation_query_max numeric(9,6),
    ADD COLUMN worst_query_id uuid,
    ADD COLUMN selected_destination_ids uuid[],
    ADD COLUMN qualified_destination_ids uuid[],
    ADD COLUMN verified_destination_ids uuid[],
    ADD COLUMN result_hash text,
    ALTER COLUMN statistics_contract_version
        SET DEFAULT 'geo-observation-statistics-v2',
    ADD CONSTRAINT monitoring_metric_snapshots_status_check CHECK (
        status IN ('complete', 'confounded', 'insufficient_evidence')
    ),
    ADD CONSTRAINT monitoring_metric_statistics_status_check CHECK (
        (status = 'complete' AND cardinality(confounded_reasons) = 0)
        OR (status = 'confounded' AND cardinality(confounded_reasons) > 0)
        OR status = 'insufficient_evidence'
    ),
    ADD CONSTRAINT monitoring_metric_statistics_contract_check CHECK (
        statistics_contract_version IN (
            'legacy-v1', 'geo-observation-statistics-v2'
        )
    ),
    ADD CONSTRAINT monitoring_metric_statistics_shape_check CHECK (
        (statistics_contract_version = 'legacy-v1' AND status <> 'insufficient_evidence'
            AND num_nonnulls(
                query_cluster_key, analysis_stratum_hash, minimum_valid_repeats,
                sampled_sample_count, invalid_sample_count, missing_sample_count,
                sampling_completion_ratio, valid_completion_ratio, query_count,
                sufficient_query_count, invalid_reason_counts,
                declared_confounding_factors, query_results_snapshot,
                recommendation_ci_low, recommendation_ci_high,
                product_mention_ci_low, product_mention_ci_high,
                placement_citation_ci_low, placement_citation_ci_high,
                recommendation_query_min, recommendation_query_max,
                product_mention_query_min, product_mention_query_max,
                placement_citation_query_min, placement_citation_query_max,
                worst_query_id, selected_destination_ids, qualified_destination_ids,
                verified_destination_ids, result_hash
            ) = 0)
        OR
        (statistics_contract_version = 'geo-observation-statistics-v2'
            AND method_version = 'geo-observation-statistics-v2'
            AND btrim(query_cluster_key) <> ''
            AND analysis_stratum_hash ~ '^[0-9a-f]{64}$'
            AND minimum_valid_repeats >= 3
            AND sampled_sample_count >= 0
            AND invalid_sample_count >= 0
            AND missing_sample_count >= 0
            AND sampling_completion_ratio BETWEEN 0 AND 1
            AND valid_completion_ratio BETWEEN 0 AND 1
            AND query_count > 0
            AND sufficient_query_count BETWEEN 0 AND query_count
            AND jsonb_typeof(invalid_reason_counts) = 'object'
            AND jsonb_typeof(query_results_snapshot) = 'array'
            AND recommendation_ci_low BETWEEN 0 AND recommendation_ci_high
            AND recommendation_ci_high <= 1
            AND product_mention_ci_low BETWEEN 0 AND product_mention_ci_high
            AND product_mention_ci_high <= 1
            AND placement_citation_ci_low BETWEEN 0 AND placement_citation_ci_high
            AND placement_citation_ci_high <= 1
            AND recommendation_query_min BETWEEN 0 AND recommendation_query_max
            AND recommendation_query_max <= 1
            AND product_mention_query_min BETWEEN 0 AND product_mention_query_max
            AND product_mention_query_max <= 1
            AND placement_citation_query_min BETWEEN 0 AND placement_citation_query_max
            AND placement_citation_query_max <= 1
            AND result_hash ~ '^[0-9a-f]{64}$'
            AND num_nulls(
                query_cluster_key, analysis_stratum_hash, minimum_valid_repeats,
                sampled_sample_count, invalid_sample_count, missing_sample_count,
                sampling_completion_ratio, valid_completion_ratio, query_count,
                sufficient_query_count, invalid_reason_counts,
                declared_confounding_factors, query_results_snapshot,
                recommendation_ci_low, recommendation_ci_high,
                product_mention_ci_low, product_mention_ci_high,
                placement_citation_ci_low, placement_citation_ci_high,
                recommendation_query_min, recommendation_query_max,
                product_mention_query_min, product_mention_query_max,
                placement_citation_query_min, placement_citation_query_max,
                worst_query_id, selected_destination_ids, qualified_destination_ids,
                verified_destination_ids, result_hash
            ) = 0)
    ),
    ADD CONSTRAINT monitoring_metric_statistics_worst_query_fkey
        FOREIGN KEY (protocol_id, worst_query_id, project_id)
        REFERENCES monitoring_protocol_queries(
            protocol_id, monitoring_query_id, project_id
        ),
    ADD CONSTRAINT monitoring_metric_statistics_slot_key
        UNIQUE NULLS NOT DISTINCT (
            protocol_id, measurement_window, source_stratum_hash,
            query_cluster_key, input_hash
        );

CREATE FUNCTION geo_assert_new_metric_statistics() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    protocol_record record;
    query_record record;
    cluster_query_count integer;
    item jsonb;
    estimate_name text;
    count_name text;
    item_query_id uuid;
    item_query_id_text text;
    previous_query_id_text text;
    row_expected integer;
    row_sampled integer;
    row_valid integer;
    row_invalid integer;
    row_missing integer;
    row_confounding_factors text[];
    recommendation jsonb;
    product_mention jsonb;
    placement_citation jsonb;
    competitor jsonb;
    total_sampled integer := 0;
    total_valid integer := 0;
    total_invalid integer := 0;
    total_missing integer := 0;
    total_sufficient integer := 0;
    recommendation_numerator integer := 0;
    product_numerator integer := 0;
    citation_numerator integer := 0;
    competitor_numerator integer := 0;
    aggregate_invalid_reason_counts jsonb := '{}'::jsonb;
    reason_record record;
    recommendation_min numeric;
    recommendation_max numeric;
    product_min numeric;
    product_max numeric;
    citation_min numeric;
    citation_max numeric;
    expected_qualified_coverage numeric;
    expected_verified_coverage numeric;
    expected_recommendation_share numeric;
    expected_product_share numeric;
    expected_citation_share numeric;
    expected_competitive_delta numeric;
BEGIN
    IF NEW.statistics_contract_version <> 'geo-observation-statistics-v2' THEN
        RAISE EXCEPTION 'new metric snapshots require statistics v2'
            USING ERRCODE = '23514';
    END IF;

    SELECT protocol.sample_size, protocol.minimum_valid_repeats,
           protocol.statistics_method_version
    INTO protocol_record
    FROM monitoring_protocols AS protocol
    WHERE protocol.id = NEW.protocol_id
      AND protocol.project_id = NEW.project_id
      AND protocol.campaign_id = NEW.campaign_id
      AND protocol.status = 'frozen'
      AND protocol.statistics_contract_version = 'geo-observation-statistics-v2';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'statistics v2 metrics require a frozen statistics v2 protocol'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.method_version <> protocol_record.statistics_method_version
       OR NEW.method_version <> 'geo-observation-statistics-v2'
       OR NEW.minimum_valid_repeats <> protocol_record.minimum_valid_repeats THEN
        RAISE EXCEPTION 'metric statistics method or threshold differs from protocol'
            USING ERRCODE = '23514';
    END IF;

    SELECT count(*)
    INTO cluster_query_count
    FROM monitoring_protocol_queries AS protocol_query
    WHERE protocol_query.protocol_id = NEW.protocol_id
      AND protocol_query.project_id = NEW.project_id
      AND protocol_query.query_cluster_key = NEW.query_cluster_key;
    IF cluster_query_count = 0 OR NEW.query_count <> cluster_query_count THEN
        RAISE EXCEPTION 'metric query cluster is not the frozen protocol inventory'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.expected_sample_count
            <> protocol_record.sample_size * cluster_query_count THEN
        RAISE EXCEPTION 'metric expected sample count differs from frozen protocol'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.analysis_stratum_hash IS DISTINCT FROM geo_analysis_stratum_hash(
        NEW.query_cluster_key, NEW.source_stratum_hash
    ) THEN
        RAISE EXCEPTION 'metric analysis stratum hash mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.sampled_sample_count > NEW.expected_sample_count
       OR NEW.eligible_sample_count + NEW.invalid_sample_count
            <> NEW.sampled_sample_count
       OR NEW.missing_sample_count
            <> NEW.expected_sample_count - NEW.sampled_sample_count
       OR NEW.sampling_completion_ratio <> round(
            NEW.sampled_sample_count::numeric / NEW.expected_sample_count, 6
       )
       OR NEW.valid_completion_ratio <> round(
            NEW.eligible_sample_count::numeric / NEW.expected_sample_count, 6
       ) THEN
        RAISE EXCEPTION 'metric sample counts or completion ratios are inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.status = 'insufficient_evidence')
            IS DISTINCT FROM (NEW.sufficient_query_count < NEW.query_count) THEN
        RAISE EXCEPTION 'metric conclusion status does not match query sufficiency'
            USING ERRCODE = '23514';
    END IF;
    IF jsonb_array_length(NEW.query_results_snapshot) <> NEW.query_count THEN
        RAISE EXCEPTION 'metric query result inventory is incomplete'
            USING ERRCODE = '23514';
    END IF;
    IF NOT geo_positive_integer_object(NEW.invalid_reason_counts)
       OR ((NEW.invalid_sample_count = 0) IS DISTINCT FROM
            (NEW.invalid_reason_counts = '{}'::jsonb))
       OR NOT geo_text_array_is_canonical_set(NEW.declared_confounding_factors)
       OR NOT geo_uuid_array_is_set(NEW.selected_destination_ids)
       OR NOT geo_uuid_array_is_set(NEW.qualified_destination_ids)
       OR NOT geo_uuid_array_is_set(NEW.verified_destination_ids)
       OR NOT (NEW.qualified_destination_ids <@ NEW.selected_destination_ids)
       OR NOT (NEW.verified_destination_ids <@ NEW.qualified_destination_ids) THEN
        RAISE EXCEPTION 'metric reasons or destination inventories are invalid'
            USING ERRCODE = '23514';
    END IF;
    expected_qualified_coverage := CASE
        WHEN cardinality(NEW.selected_destination_ids) = 0 THEN 0
        ELSE round(
            cardinality(NEW.qualified_destination_ids)::numeric
                / cardinality(NEW.selected_destination_ids),
            6
        )
    END;
    expected_verified_coverage := CASE
        WHEN cardinality(NEW.qualified_destination_ids) = 0 THEN 0
        ELSE round(
            cardinality(NEW.verified_destination_ids)::numeric
                / cardinality(NEW.qualified_destination_ids),
            6
        )
    END;
    IF NEW.qualified_destination_coverage <> expected_qualified_coverage
       OR NEW.verified_placement_coverage <> expected_verified_coverage THEN
        RAISE EXCEPTION 'metric destination coverage differs from frozen inventories'
            USING ERRCODE = '23514';
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(NEW.query_results_snapshot) LOOP
        IF jsonb_typeof(item) <> 'object'
           OR NOT item ?& ARRAY[
                'monitoring_query_id', 'query_text_snapshot', 'query_cluster_key',
                'expected_sample_count', 'sampled_sample_count', 'valid_sample_count',
                'invalid_sample_count', 'missing_sample_count', 'meets_threshold',
                'invalid_reason_counts', 'confounding_factors', 'recommendation',
                'product_mention', 'placement_citation', 'competitor',
                'competitive_delta'
           ]
           OR (SELECT count(*) FROM jsonb_object_keys(item)) <> 16 THEN
            RAISE EXCEPTION 'metric query result shape is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF jsonb_typeof(item -> 'monitoring_query_id') <> 'string'
           OR jsonb_typeof(item -> 'query_text_snapshot') <> 'string'
           OR jsonb_typeof(item -> 'query_cluster_key') <> 'string'
           OR jsonb_typeof(item -> 'meets_threshold') <> 'boolean'
           OR jsonb_typeof(item -> 'invalid_reason_counts') <> 'object'
           OR jsonb_typeof(item -> 'confounding_factors') <> 'array'
           OR jsonb_typeof(item -> 'competitive_delta') <> 'number' THEN
            RAISE EXCEPTION 'metric query result types are invalid'
                USING ERRCODE = '23514';
        END IF;
        FOREACH count_name IN ARRAY ARRAY[
            'expected_sample_count', 'sampled_sample_count', 'valid_sample_count',
            'invalid_sample_count', 'missing_sample_count'
        ] LOOP
            IF jsonb_typeof(item -> count_name) <> 'number'
               OR item ->> count_name !~ '^(0|[1-9][0-9]*)$' THEN
                RAISE EXCEPTION 'metric query result count is invalid'
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;

        item_query_id_text := item ->> 'monitoring_query_id';
        item_query_id := item_query_id_text::uuid;
        IF previous_query_id_text IS NOT NULL
           AND previous_query_id_text COLLATE "C"
                >= item_query_id_text COLLATE "C" THEN
            RAISE EXCEPTION 'metric query results must be uniquely sorted by query id'
                USING ERRCODE = '23514';
        END IF;
        previous_query_id_text := item_query_id_text;
        SELECT protocol_query.query_text_snapshot
        INTO query_record
        FROM monitoring_protocol_queries AS protocol_query
        WHERE protocol_query.protocol_id = NEW.protocol_id
          AND protocol_query.project_id = NEW.project_id
          AND protocol_query.monitoring_query_id = item_query_id
          AND protocol_query.query_cluster_key = NEW.query_cluster_key;
        IF NOT FOUND
           OR item ->> 'query_text_snapshot' IS DISTINCT FROM query_record.query_text_snapshot
           OR item ->> 'query_cluster_key' IS DISTINCT FROM NEW.query_cluster_key THEN
            RAISE EXCEPTION 'metric query result is outside the frozen cluster'
                USING ERRCODE = '23514';
        END IF;

        row_expected := (item ->> 'expected_sample_count')::integer;
        row_sampled := (item ->> 'sampled_sample_count')::integer;
        row_valid := (item ->> 'valid_sample_count')::integer;
        row_invalid := (item ->> 'invalid_sample_count')::integer;
        row_missing := (item ->> 'missing_sample_count')::integer;
        IF row_expected <> protocol_record.sample_size
           OR row_sampled > row_expected
           OR row_valid + row_invalid <> row_sampled
           OR row_missing <> row_expected - row_sampled
           OR (item ->> 'meets_threshold')::boolean IS DISTINCT FROM
                (row_valid >= protocol_record.minimum_valid_repeats)
           OR NOT geo_positive_integer_object(item -> 'invalid_reason_counts')
           OR ((row_invalid = 0) IS DISTINCT FROM
                (item -> 'invalid_reason_counts' = '{}'::jsonb)) THEN
            RAISE EXCEPTION 'metric per-query counts or threshold are inconsistent'
                USING ERRCODE = '23514';
        END IF;
        SELECT COALESCE(array_agg(value), ARRAY[]::text[])
        INTO row_confounding_factors
        FROM jsonb_array_elements_text(item -> 'confounding_factors');
        IF NOT geo_text_array_is_canonical_set(row_confounding_factors) THEN
            RAISE EXCEPTION 'metric per-query confounding factors are not canonical'
                USING ERRCODE = '23514';
        END IF;
        FOR reason_record IN
            SELECT key, value
            FROM jsonb_each_text(item -> 'invalid_reason_counts')
        LOOP
            aggregate_invalid_reason_counts := jsonb_set(
                aggregate_invalid_reason_counts,
                ARRAY[reason_record.key],
                to_jsonb(
                    COALESCE(
                        (aggregate_invalid_reason_counts ->> reason_record.key)::integer,
                        0
                    ) + reason_record.value::integer
                ),
                true
            );
        END LOOP;

        recommendation := item -> 'recommendation';
        product_mention := item -> 'product_mention';
        placement_citation := item -> 'placement_citation';
        competitor := item -> 'competitor';
        FOREACH estimate_name IN ARRAY ARRAY[
            'recommendation', 'product_mention', 'placement_citation', 'competitor'
        ] LOOP
            IF NOT geo_statistics_estimate_valid(item -> estimate_name, row_valid) THEN
                RAISE EXCEPTION 'metric per-query estimate is invalid'
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;
        IF (item ->> 'competitive_delta')::numeric <> round(
            (product_mention ->> 'share')::numeric
                - (competitor ->> 'share')::numeric,
            6
        ) OR (item ->> 'competitive_delta')::numeric NOT BETWEEN -1 AND 1 THEN
            RAISE EXCEPTION 'metric per-query competitive delta is invalid'
                USING ERRCODE = '23514';
        END IF;

        total_sampled := total_sampled + row_sampled;
        total_valid := total_valid + row_valid;
        total_invalid := total_invalid + row_invalid;
        total_missing := total_missing + row_missing;
        total_sufficient := total_sufficient
            + ((row_valid >= protocol_record.minimum_valid_repeats)::integer);
        recommendation_numerator := recommendation_numerator
            + (recommendation ->> 'numerator')::integer;
        product_numerator := product_numerator
            + (product_mention ->> 'numerator')::integer;
        citation_numerator := citation_numerator
            + (placement_citation ->> 'numerator')::integer;
        competitor_numerator := competitor_numerator
            + (competitor ->> 'numerator')::integer;
        recommendation_min := least(
            COALESCE(recommendation_min, (recommendation ->> 'share')::numeric),
            (recommendation ->> 'share')::numeric
        );
        recommendation_max := greatest(
            COALESCE(recommendation_max, (recommendation ->> 'share')::numeric),
            (recommendation ->> 'share')::numeric
        );
        product_min := least(
            COALESCE(product_min, (product_mention ->> 'share')::numeric),
            (product_mention ->> 'share')::numeric
        );
        product_max := greatest(
            COALESCE(product_max, (product_mention ->> 'share')::numeric),
            (product_mention ->> 'share')::numeric
        );
        citation_min := least(
            COALESCE(citation_min, (placement_citation ->> 'share')::numeric),
            (placement_citation ->> 'share')::numeric
        );
        citation_max := greatest(
            COALESCE(citation_max, (placement_citation ->> 'share')::numeric),
            (placement_citation ->> 'share')::numeric
        );
    END LOOP;

    expected_recommendation_share := CASE WHEN total_valid = 0 THEN 0 ELSE
        round(recommendation_numerator::numeric / total_valid, 6) END;
    expected_product_share := CASE WHEN total_valid = 0 THEN 0 ELSE
        round(product_numerator::numeric / total_valid, 6) END;
    expected_citation_share := CASE WHEN total_valid = 0 THEN 0 ELSE
        round(citation_numerator::numeric / total_valid, 6) END;
    expected_competitive_delta := CASE WHEN total_valid = 0 THEN 0 ELSE
        round((product_numerator - competitor_numerator)::numeric / total_valid, 6)
        END;
    IF total_sampled <> NEW.sampled_sample_count
       OR total_valid <> NEW.eligible_sample_count
       OR total_invalid <> NEW.invalid_sample_count
       OR total_missing <> NEW.missing_sample_count
       OR total_sufficient <> NEW.sufficient_query_count
       OR aggregate_invalid_reason_counts <> NEW.invalid_reason_counts
       OR NEW.recommendation_share <> expected_recommendation_share
       OR NEW.product_mention_share <> expected_product_share
       OR NEW.placement_citation_share <> expected_citation_share
       OR NEW.competitive_delta <> expected_competitive_delta
       OR NEW.recommendation_query_min <> recommendation_min
       OR NEW.recommendation_query_max <> recommendation_max
       OR NEW.product_mention_query_min <> product_min
       OR NEW.product_mention_query_max <> product_max
       OR NEW.placement_citation_query_min <> citation_min
       OR NEW.placement_citation_query_max <> citation_max THEN
        RAISE EXCEPTION 'metric aggregate values differ from per-query results'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER monitoring_metric_statistics_guard
BEFORE INSERT ON monitoring_metric_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_metric_statistics();

DROP INDEX monitoring_metric_snapshots_source_stratum_idx;
CREATE INDEX monitoring_metric_statistics_latest_idx
ON monitoring_metric_snapshots (
    project_id, campaign_id, protocol_id, measurement_window,
    source_stratum_hash, query_cluster_key, computed_at DESC, id DESC
);
CREATE INDEX monitoring_metric_statistics_worst_query_idx
ON monitoring_metric_snapshots (protocol_id, worst_query_id, project_id)
WHERE worst_query_id IS NOT NULL;

REVOKE ALL ON FUNCTION geo_assert_new_protocol_statistics(),
    geo_json_ascii_string(text), geo_analysis_stratum_hash(text,text),
    geo_uuid_array_is_set(uuid[]), geo_text_array_is_canonical_set(text[]),
    geo_positive_integer_object(jsonb), geo_statistics_estimate_valid(jsonb,integer),
    geo_assert_new_metric_statistics()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_assert_new_protocol_statistics(),
    geo_json_ascii_string(text), geo_analysis_stratum_hash(text,text),
    geo_uuid_array_is_set(uuid[]), geo_text_array_is_canonical_set(text[]),
    geo_positive_integer_object(jsonb), geo_statistics_estimate_valid(jsonb,integer),
    geo_assert_new_metric_statistics()
TO geo_app, geo_worker;
