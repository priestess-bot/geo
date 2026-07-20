CREATE FUNCTION geo_ascii_nonempty(value text) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT value IS NOT NULL
       AND btrim(value) <> ''
       AND octet_length(value) = char_length(value)
$$;

CREATE FUNCTION geo_observation_surface_matches(
    capture_method text,
    platform text,
    platform_detail text,
    surface text,
    surface_kind text,
    surface_detail text
) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT
        CASE capture_method
            WHEN 'manual_ui' THEN surface_kind = 'consumer_ui'
            WHEN 'provider_api' THEN surface_kind = 'provider_api'
            WHEN 'proxy_grounded_api' THEN surface_kind = 'grounded_proxy'
            WHEN 'synthetic' THEN surface_kind = 'internal_benchmark'
            WHEN 'unknown' THEN surface_kind = 'other'
            ELSE false
        END
        AND CASE surface
            WHEN 'chatgpt_search' THEN platform = 'openai' AND surface_kind = 'consumer_ui'
            WHEN 'google_search' THEN platform = 'google' AND surface_kind = 'consumer_ui'
            WHEN 'google_ai_overviews' THEN platform = 'google' AND surface_kind = 'consumer_ui'
            WHEN 'google_ai_mode' THEN platform = 'google' AND surface_kind = 'consumer_ui'
            WHEN 'gemini' THEN platform = 'google' AND surface_kind = 'consumer_ui'
            WHEN 'perplexity_answer' THEN
                platform = 'perplexity' AND surface_kind = 'consumer_ui'
            WHEN 'bing_search' THEN platform = 'microsoft' AND surface_kind = 'consumer_ui'
            WHEN 'bing_copilot' THEN platform = 'microsoft' AND surface_kind = 'consumer_ui'
            WHEN 'claude_ai' THEN platform = 'anthropic' AND surface_kind = 'consumer_ui'
            WHEN 'openai_api' THEN platform = 'openai' AND surface_kind = 'provider_api'
            WHEN 'google_gemini_api' THEN
                platform = 'google' AND surface_kind = 'provider_api'
            WHEN 'perplexity_api' THEN
                platform = 'perplexity' AND surface_kind = 'provider_api'
            WHEN 'anthropic_api' THEN
                platform = 'anthropic' AND surface_kind = 'provider_api'
            WHEN 'microsoft_foundry_bing_grounding' THEN
                platform = 'microsoft' AND surface_kind = 'grounded_proxy'
            WHEN 'google_vertex_grounding' THEN
                platform = 'google' AND surface_kind = 'grounded_proxy'
            WHEN 'internal_benchmark' THEN surface_kind = 'internal_benchmark'
            WHEN 'other' THEN geo_ascii_nonempty(surface_detail)
            ELSE false
        END
        AND (platform <> 'other' OR geo_ascii_nonempty(platform_detail))
$$;

CREATE FUNCTION geo_observation_source_stratum_canonical(
    capture_method text,
    platform text,
    surface text,
    surface_kind text,
    engine text,
    configured_model_state text,
    configured_model text,
    reported_model_state text,
    reported_model text,
    locale text,
    region text,
    language text,
    device text,
    client_kind text,
    search_enabled boolean,
    search_mode text
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT
        '{"capture_method":' || to_jsonb(capture_method)::text
        || ',"client_kind":' || to_jsonb(client_kind)::text
        || ',"configured_model":{"state":'
        || to_jsonb(configured_model_state)::text
        || ',"value":' || COALESCE(to_jsonb(configured_model)::text, 'null') || '}'
        || ',"device":' || to_jsonb(device)::text
        || ',"engine":' || to_jsonb(engine)::text
        || ',"language":' || to_jsonb(language)::text
        || ',"locale":' || to_jsonb(locale)::text
        || ',"platform":' || to_jsonb(platform)::text
        || ',"region":' || to_jsonb(region)::text
        || ',"reported_model":{"state":'
        || to_jsonb(reported_model_state)::text
        || ',"value":' || COALESCE(to_jsonb(reported_model)::text, 'null') || '}'
        || ',"search_enabled":' || to_jsonb(search_enabled)::text
        || ',"search_mode":' || to_jsonb(search_mode)::text
        || ',"surface":' || to_jsonb(surface)::text
        || ',"surface_kind":' || to_jsonb(surface_kind)::text || '}'
$$;

CREATE FUNCTION geo_observation_source_stratum_hash(
    capture_method text,
    platform text,
    surface text,
    surface_kind text,
    engine text,
    configured_model_state text,
    configured_model text,
    reported_model_state text,
    reported_model text,
    locale text,
    region text,
    language text,
    device text,
    client_kind text,
    search_enabled boolean,
    search_mode text
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT encode(
        digest(
            convert_to(
                geo_observation_source_stratum_canonical(
                    capture_method, platform, surface, surface_kind, engine,
                    configured_model_state, configured_model, reported_model_state,
                    reported_model, locale, region, language, device, client_kind,
                    search_enabled, search_mode
                ),
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
$$;

CREATE FUNCTION geo_source_stratum_json_valid(source_stratum jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT jsonb_typeof(source_stratum) = 'object'
       AND source_stratum = jsonb_build_object(
            'capture_method', source_stratum ->> 'capture_method',
            'platform', source_stratum ->> 'platform',
            'surface', source_stratum ->> 'surface',
            'surface_kind', source_stratum ->> 'surface_kind',
            'engine', source_stratum ->> 'engine',
            'configured_model', jsonb_build_object(
                'state', source_stratum -> 'configured_model' ->> 'state',
                'value', source_stratum -> 'configured_model' ->> 'value'
            ),
            'reported_model', jsonb_build_object(
                'state', source_stratum -> 'reported_model' ->> 'state',
                'value', source_stratum -> 'reported_model' ->> 'value'
            ),
            'locale', source_stratum ->> 'locale',
            'region', source_stratum ->> 'region',
            'language', source_stratum ->> 'language',
            'device', source_stratum ->> 'device',
            'client_kind', source_stratum ->> 'client_kind',
            'search_enabled', (source_stratum ->> 'search_enabled')::boolean,
            'search_mode', source_stratum ->> 'search_mode'
       )
       AND source_stratum ->> 'capture_method' IN (
            'manual_ui', 'provider_api', 'proxy_grounded_api'
       )
       AND source_stratum ->> 'platform' IN (
            'openai', 'google', 'perplexity', 'microsoft', 'anthropic', 'other'
       )
       AND geo_observation_surface_matches(
            source_stratum ->> 'capture_method',
            source_stratum ->> 'platform',
            CASE WHEN source_stratum ->> 'platform' = 'other'
                 THEN 'protocol_other' ELSE NULL END,
            source_stratum ->> 'surface',
            source_stratum ->> 'surface_kind',
            CASE WHEN source_stratum ->> 'surface' = 'other'
                 THEN 'protocol_other' ELSE NULL END
       )
       AND geo_ascii_nonempty(source_stratum ->> 'engine')
       AND geo_ascii_nonempty(source_stratum ->> 'locale')
       AND geo_ascii_nonempty(source_stratum ->> 'region')
       AND geo_ascii_nonempty(source_stratum ->> 'language')
       AND source_stratum ->> 'device' IN ('desktop', 'mobile', 'tablet', 'api')
       AND source_stratum ->> 'client_kind' IN ('browser', 'native_app', 'api')
       AND source_stratum ->> 'search_mode' IN (
            'disabled', 'live_web', 'grounded_web', 'automatic', 'not_applicable'
       )
       AND (
            ((source_stratum ->> 'search_enabled')::boolean
                AND source_stratum ->> 'search_mode' NOT IN ('disabled', 'not_applicable'))
            OR (NOT (source_stratum ->> 'search_enabled')::boolean
                AND source_stratum ->> 'search_mode' IN ('disabled', 'not_applicable'))
       )
       AND source_stratum -> 'configured_model' ->> 'state' IN (
            'disclosed', 'not_disclosed', 'not_applicable'
       )
       AND source_stratum -> 'reported_model' ->> 'state' IN (
            'disclosed', 'not_disclosed', 'not_applicable'
       )
       AND (
            (source_stratum -> 'configured_model' ->> 'state' = 'disclosed'
                AND geo_ascii_nonempty(
                    source_stratum -> 'configured_model' ->> 'value'
                ))
            OR (source_stratum -> 'configured_model' ->> 'state' <> 'disclosed'
                AND source_stratum -> 'configured_model' ->> 'value' IS NULL)
       )
       AND (
            (source_stratum -> 'reported_model' ->> 'state' = 'disclosed'
                AND geo_ascii_nonempty(source_stratum -> 'reported_model' ->> 'value'))
            OR (source_stratum -> 'reported_model' ->> 'state' <> 'disclosed'
                AND source_stratum -> 'reported_model' ->> 'value' IS NULL)
       )
$$;

CREATE FUNCTION geo_source_stratum_hash_from_json(source_stratum jsonb) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT geo_observation_source_stratum_hash(
        source_stratum ->> 'capture_method',
        source_stratum ->> 'platform',
        source_stratum ->> 'surface',
        source_stratum ->> 'surface_kind',
        source_stratum ->> 'engine',
        source_stratum -> 'configured_model' ->> 'state',
        source_stratum -> 'configured_model' ->> 'value',
        source_stratum -> 'reported_model' ->> 'state',
        source_stratum -> 'reported_model' ->> 'value',
        source_stratum ->> 'locale',
        source_stratum ->> 'region',
        source_stratum ->> 'language',
        source_stratum ->> 'device',
        source_stratum ->> 'client_kind',
        (source_stratum ->> 'search_enabled')::boolean,
        source_stratum ->> 'search_mode'
    )
$$;

CREATE FUNCTION geo_source_strata_inventory_hash(source_strata jsonb) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    WITH canonical AS (
        SELECT geo_observation_source_stratum_canonical(
            item ->> 'capture_method', item ->> 'platform', item ->> 'surface',
            item ->> 'surface_kind', item ->> 'engine',
            item -> 'configured_model' ->> 'state',
            item -> 'configured_model' ->> 'value',
            item -> 'reported_model' ->> 'state',
            item -> 'reported_model' ->> 'value',
            item ->> 'locale', item ->> 'region', item ->> 'language',
            item ->> 'device', item ->> 'client_kind',
            (item ->> 'search_enabled')::boolean, item ->> 'search_mode'
        ) AS value
        FROM jsonb_array_elements(source_strata) AS entries(item)
    )
    SELECT encode(
        digest(
            convert_to(
                '[' || COALESCE(
                    string_agg(
                        value,
                        ',' ORDER BY encode(
                            digest(convert_to(value, 'UTF8'), 'sha256'), 'hex'
                        )
                    ),
                    ''
                ) || ']',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
    FROM canonical
$$;

ALTER TABLE monitoring_protocols
    ADD COLUMN source_strata_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(source_strata_snapshot) = 'array'),
    ADD COLUMN source_strata_hash text
        CHECK (source_strata_hash IS NULL OR source_strata_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT monitoring_protocols_source_strata_pair_check CHECK (
        (jsonb_array_length(source_strata_snapshot) = 0 AND source_strata_hash IS NULL)
        OR (jsonb_array_length(source_strata_snapshot) > 0
            AND source_strata_hash IS NOT NULL)
    );
ALTER TABLE monitoring_query_suggestions
    ADD COLUMN query_cluster_key text
        CHECK (query_cluster_key IS NULL OR btrim(query_cluster_key) <> '');
ALTER TABLE monitoring_protocol_queries
    ADD COLUMN query_cluster_key text
        CHECK (query_cluster_key IS NULL OR btrim(query_cluster_key) <> '');

CREATE FUNCTION geo_assert_protocol_source_strata() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    item jsonb;
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.source_strata_snapshot IS NOT DISTINCT FROM OLD.source_strata_snapshot
       AND NEW.source_strata_hash IS NOT DISTINCT FROM OLD.source_strata_hash THEN
        RETURN NEW;
    END IF;
    IF jsonb_array_length(NEW.source_strata_snapshot) = 0
       OR NEW.source_strata_hash IS NULL THEN
        RAISE EXCEPTION 'new monitoring protocols require source strata'
            USING ERRCODE = '23514';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(NEW.source_strata_snapshot) LOOP
        IF NOT geo_source_stratum_json_valid(item) THEN
            RAISE EXCEPTION 'protocol source stratum is invalid'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF (
        SELECT count(DISTINCT geo_source_stratum_hash_from_json(value))
        FROM jsonb_array_elements(NEW.source_strata_snapshot)
    ) <> jsonb_array_length(NEW.source_strata_snapshot) THEN
        RAISE EXCEPTION 'protocol source strata must be unique'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.source_strata_hash <> geo_source_strata_inventory_hash(
        NEW.source_strata_snapshot
    ) THEN
        RAISE EXCEPTION 'protocol source strata inventory hash mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_new_query_cluster() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF btrim(COALESCE(NEW.query_cluster_key, '')) = '' THEN
        RAISE EXCEPTION 'new monitoring queries require a query cluster key'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER monitoring_protocol_source_strata_guard
BEFORE INSERT OR UPDATE OF source_strata_snapshot, source_strata_hash
ON monitoring_protocols
FOR EACH ROW EXECUTE FUNCTION geo_assert_protocol_source_strata();
CREATE TRIGGER monitoring_query_suggestion_cluster_guard
BEFORE INSERT ON monitoring_query_suggestions
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_query_cluster();
CREATE TRIGGER monitoring_protocol_query_cluster_guard
BEFORE INSERT ON monitoring_protocol_queries
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_query_cluster();

CREATE TABLE monitoring_observation_legacy_migration_state (
    project_id uuid NOT NULL,
    observation_id uuid NOT NULL,
    eligible boolean NOT NULL,
    ineligible_reasons text[] NOT NULL,
    PRIMARY KEY (project_id, observation_id),
    FOREIGN KEY (observation_id, project_id)
        REFERENCES monitoring_observations(id, project_id) ON DELETE CASCADE
);
INSERT INTO monitoring_observation_legacy_migration_state (
    project_id, observation_id, eligible, ineligible_reasons
)
SELECT project_id, id, eligible, ineligible_reasons FROM monitoring_observations;

DROP TRIGGER monitoring_observations_immutable ON monitoring_observations;
ALTER TABLE model_call_logs
    ADD CONSTRAINT model_call_logs_exact_job_key UNIQUE (id, project_id, job_id);
ALTER TABLE monitoring_observations
    ALTER COLUMN configured_model DROP NOT NULL,
    ADD COLUMN eligibility_requested boolean NOT NULL DEFAULT false,
    ADD COLUMN capture_method text NOT NULL DEFAULT 'unknown',
    ADD COLUMN platform text NOT NULL DEFAULT 'other',
    ADD COLUMN platform_detail text,
    ADD COLUMN surface text NOT NULL DEFAULT 'other',
    ADD COLUMN surface_kind text NOT NULL DEFAULT 'other',
    ADD COLUMN surface_detail text,
    ADD COLUMN engine text,
    ADD COLUMN configured_model_state text,
    ADD COLUMN provider_reported_model_state text,
    ADD COLUMN locale text,
    ADD COLUMN region text,
    ADD COLUMN language text,
    ADD COLUMN observation_device text,
    ADD COLUMN client_kind text,
    ADD COLUMN search_enabled boolean,
    ADD COLUMN search_mode text,
    ADD COLUMN prompt_text text,
    ADD COLUMN follow_up_prompts jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN adapter_name text,
    ADD COLUMN adapter_version text,
    ADD COLUMN provider_request_id text,
    ADD COLUMN raw_evidence_kind text NOT NULL DEFAULT 'legacy_unknown',
    ADD COLUMN citations_captured boolean NOT NULL DEFAULT false,
    ADD COLUMN source_contract_version text NOT NULL DEFAULT 'legacy-v1',
    ADD COLUMN source_stratum_hash text,
    ADD COLUMN query_cluster_key text,
    ADD COLUMN source_job_id uuid,
    ADD COLUMN model_call_log_id uuid,
    ADD COLUMN test_only boolean NOT NULL DEFAULT false,
    ADD COLUMN publication_eligible boolean NOT NULL DEFAULT false;

UPDATE monitoring_observations AS observation
SET eligible = false,
    ineligible_reasons = ARRAY(
        SELECT DISTINCT reason
        FROM unnest(
            observation.ineligible_reasons
            || ARRAY['legacy_unknown_capture_method']::text[]
        ) AS reasons(reason)
        ORDER BY reason
    ),
    configured_model_state = 'disclosed',
    provider_reported_model_state = CASE
        WHEN provider_reported_model IS NULL THEN 'not_disclosed'
        ELSE 'disclosed'
    END,
    platform_detail = 'legacy_unclassified',
    surface_detail = 'legacy_unclassified';

ALTER TABLE monitoring_observations
    ALTER COLUMN configured_model_state SET NOT NULL,
    ALTER COLUMN provider_reported_model_state SET NOT NULL,
    ALTER COLUMN capture_method DROP DEFAULT,
    ALTER COLUMN platform DROP DEFAULT,
    ALTER COLUMN surface DROP DEFAULT,
    ALTER COLUMN surface_kind DROP DEFAULT,
    ALTER COLUMN raw_evidence_kind DROP DEFAULT,
    ALTER COLUMN source_contract_version SET DEFAULT 'geo-observation-source-v2',
    DROP CONSTRAINT monitoring_observations_protocol_id_monitoring_query_id_mea_key,
    ADD CONSTRAINT monitoring_observations_capture_method_check CHECK (
        capture_method IN (
            'manual_ui', 'provider_api', 'proxy_grounded_api', 'synthetic', 'unknown'
        )
    ),
    ADD CONSTRAINT monitoring_observations_platform_check CHECK (
        platform IN ('openai', 'google', 'perplexity', 'microsoft', 'anthropic', 'other')
    ),
    ADD CONSTRAINT monitoring_observations_surface_check CHECK (
        surface IN (
            'chatgpt_search', 'google_search', 'google_ai_overviews',
            'google_ai_mode', 'gemini', 'perplexity_answer', 'bing_search',
            'bing_copilot', 'claude_ai', 'openai_api', 'google_gemini_api',
            'perplexity_api', 'anthropic_api',
            'microsoft_foundry_bing_grounding', 'google_vertex_grounding',
            'internal_benchmark', 'other'
        )
    ),
    ADD CONSTRAINT monitoring_observations_surface_kind_check CHECK (
        surface_kind IN (
            'consumer_ui', 'provider_api', 'grounded_proxy',
            'internal_benchmark', 'other'
        )
    ),
    ADD CONSTRAINT monitoring_observations_model_state_check CHECK (
        configured_model_state IN ('disclosed', 'not_disclosed', 'not_applicable')
        AND provider_reported_model_state IN (
            'disclosed', 'not_disclosed', 'not_applicable'
        )
    ),
    ADD CONSTRAINT monitoring_observations_model_value_check CHECK (
        ((configured_model_state = 'disclosed') = (configured_model IS NOT NULL))
        AND ((provider_reported_model_state = 'disclosed')
            = (provider_reported_model IS NOT NULL))
        AND (configured_model IS NULL OR btrim(configured_model) <> '')
        AND (provider_reported_model IS NULL OR btrim(provider_reported_model) <> '')
    ),
    ADD CONSTRAINT monitoring_observations_run_enum_check CHECK (
        observation_device IS NULL OR observation_device IN (
            'desktop', 'mobile', 'tablet', 'api', 'internal_worker', 'report'
        )
    ),
    ADD CONSTRAINT monitoring_observations_client_kind_check CHECK (
        client_kind IS NULL OR client_kind IN (
            'browser', 'native_app', 'api', 'internal_worker', 'report_import'
        )
    ),
    ADD CONSTRAINT monitoring_observations_search_mode_check CHECK (
        search_mode IS NULL OR search_mode IN (
            'disabled', 'live_web', 'grounded_web', 'automatic', 'not_applicable'
        )
    ),
    ADD CONSTRAINT monitoring_observations_follow_up_prompts_check CHECK (
        jsonb_typeof(follow_up_prompts) = 'array'
    ),
    ADD CONSTRAINT monitoring_observations_raw_evidence_kind_check CHECK (
        raw_evidence_kind IN ('answer', 'inline_response', 'artifact', 'legacy_unknown')
    ),
    ADD CONSTRAINT monitoring_observations_source_contract_version_check CHECK (
        source_contract_version IN ('legacy-v1', 'geo-observation-source-v2')
    ),
    ADD CONSTRAINT monitoring_observations_source_stratum_hash_check CHECK (
        source_stratum_hash IS NULL OR source_stratum_hash ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT monitoring_observations_source_job_pair_check CHECK (
        (source_job_id IS NULL) = (model_call_log_id IS NULL)
    ),
    ADD CONSTRAINT monitoring_observations_legacy_shape_check CHECK (
        source_contract_version <> 'legacy-v1' OR (
            capture_method = 'unknown' AND platform = 'other' AND surface = 'other'
            AND surface_kind = 'other' AND NOT eligible
            AND NOT eligibility_requested AND NOT citations_captured
            AND raw_evidence_kind = 'legacy_unknown'
            AND source_stratum_hash IS NULL AND query_cluster_key IS NULL
            AND source_job_id IS NULL AND model_call_log_id IS NULL
            AND NOT test_only AND NOT publication_eligible
            AND 'legacy_unknown_capture_method' = ANY(ineligible_reasons)
        )
    ),
    ADD CONSTRAINT monitoring_observations_source_job_fkey
        FOREIGN KEY (source_job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id),
    ADD CONSTRAINT monitoring_observations_model_call_fkey
        FOREIGN KEY (model_call_log_id, project_id, source_job_id)
        REFERENCES model_call_logs(id, project_id, job_id),
    ADD CONSTRAINT monitoring_observations_source_slot_key
        UNIQUE NULLS NOT DISTINCT (
            protocol_id, monitoring_query_id, measurement_window,
            source_stratum_hash, sample_index
        );

CREATE FUNCTION geo_assert_new_observation_source() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_contract_version <> 'geo-observation-source-v2'
       OR NEW.capture_method IN ('unknown', 'official_report_import') THEN
        RAISE EXCEPTION 'new answer observations require a typed non-official source'
            USING ERRCODE = '23514';
    END IF;
    IF NOT geo_observation_surface_matches(
        NEW.capture_method, NEW.platform, NEW.platform_detail, NEW.surface,
        NEW.surface_kind, NEW.surface_detail
    ) OR NEW.ui_surface <> NEW.surface THEN
        RAISE EXCEPTION 'observation platform and surface contract mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NOT geo_ascii_nonempty(NEW.engine)
       OR NOT geo_ascii_nonempty(NEW.locale)
       OR NOT geo_ascii_nonempty(NEW.region)
       OR NOT geo_ascii_nonempty(NEW.language)
       OR NEW.observation_device IS NULL OR NEW.client_kind IS NULL
       OR NEW.search_enabled IS NULL OR NEW.search_mode IS NULL
       OR btrim(COALESCE(NEW.prompt_text, '')) = ''
       OR btrim(COALESCE(NEW.query_cluster_key, '')) = '' THEN
        RAISE EXCEPTION 'observation run parameters are incomplete'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.search_enabled AND NEW.search_mode IN ('disabled', 'not_applicable'))
       OR (NOT NEW.search_enabled
           AND NEW.search_mode NOT IN ('disabled', 'not_applicable')) THEN
        RAISE EXCEPTION 'observation search mode mismatch' USING ERRCODE = '23514';
    END IF;
    IF NEW.configured_model_state = 'not_applicable'
       OR (NEW.configured_model IS NOT NULL
           AND octet_length(NEW.configured_model) <> char_length(NEW.configured_model))
       OR (NEW.provider_reported_model IS NOT NULL
           AND octet_length(NEW.provider_reported_model)
               <> char_length(NEW.provider_reported_model)) THEN
        RAISE EXCEPTION 'observation model identity is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.capture_method IN ('provider_api', 'proxy_grounded_api', 'synthetic')
       AND (
           NEW.configured_model_state <> 'disclosed'
           OR btrim(COALESCE(NEW.adapter_name, '')) = ''
           OR btrim(COALESCE(NEW.adapter_version, '')) = ''
       ) THEN
        RAISE EXCEPTION 'API and synthetic observations require adapter identity'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.capture_method IN ('provider_api', 'proxy_grounded_api')
       AND btrim(COALESCE(NEW.provider_request_id, '')) = '' THEN
        RAISE EXCEPTION 'provider observations require a provider request id'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.capture_method = 'proxy_grounded_api' AND NOT NEW.search_enabled THEN
        RAISE EXCEPTION 'grounded proxy observations require search'
            USING ERRCODE = '23514';
    END IF;
    IF NOT NEW.citations_captured THEN
        RAISE EXCEPTION 'new observations must confirm citation capture'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.raw_evidence_kind = 'answer' AND (
            btrim(COALESCE(NEW.raw_answer, '')) = '' OR NEW.artifact_uri IS NOT NULL
        )) OR (NEW.raw_evidence_kind = 'inline_response' AND (
            NEW.raw_answer IS NOT NULL OR NEW.raw_result = '{}'::jsonb
            OR NEW.artifact_uri IS NOT NULL
        )) OR (NEW.raw_evidence_kind = 'artifact' AND (
            NEW.raw_answer IS NOT NULL OR NEW.artifact_uri IS NULL
        )) OR NEW.raw_evidence_kind = 'legacy_unknown' THEN
        RAISE EXCEPTION 'observation raw evidence does not match its kind'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.source_stratum_hash IS DISTINCT FROM geo_observation_source_stratum_hash(
        NEW.capture_method, NEW.platform, NEW.surface, NEW.surface_kind, NEW.engine,
        NEW.configured_model_state, NEW.configured_model,
        NEW.provider_reported_model_state, NEW.provider_reported_model,
        NEW.locale, NEW.region, NEW.language, NEW.observation_device,
        NEW.client_kind, NEW.search_enabled, NEW.search_mode
    ) THEN
        RAISE EXCEPTION 'observation source stratum hash mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM monitoring_protocol_queries AS query
        WHERE query.protocol_id = NEW.protocol_id
          AND query.project_id = NEW.project_id
          AND query.monitoring_query_id = NEW.monitoring_query_id
          AND query.query_cluster_key = NEW.query_cluster_key
    ) THEN
        RAISE EXCEPTION 'observation query cluster does not match the frozen query'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.eligible AND NOT EXISTS (
        SELECT 1
        FROM monitoring_protocols AS protocol,
             LATERAL jsonb_array_elements(protocol.source_strata_snapshot) AS strata(item)
        WHERE protocol.id = NEW.protocol_id AND protocol.project_id = NEW.project_id
          AND protocol.status = 'frozen'
          AND geo_source_stratum_hash_from_json(strata.item) = NEW.source_stratum_hash
    ) THEN
        RAISE EXCEPTION 'eligible observation stratum was not frozen into the protocol'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.eligible AND (
        NOT NEW.eligibility_requested OR NEW.result_status <> 'succeeded'
        OR cardinality(NEW.ineligible_reasons) <> 0
        OR NOT NEW.publication_eligible OR NEW.test_only
    ) THEN
        RAISE EXCEPTION 'stored observation eligibility is not server-derived'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.capture_method = 'synthetic' THEN
        IF NOT pg_has_role(session_user, 'geo_worker', 'USAGE')
           OR NOT NEW.test_only OR NEW.publication_eligible OR NEW.eligible
           OR NOT ('synthetic_test_only' = ANY(NEW.ineligible_reasons))
           OR NEW.raw_evidence_kind <> 'artifact'
           OR NEW.source_job_id IS NULL OR NEW.model_call_log_id IS NULL THEN
            RAISE EXCEPTION 'synthetic observations are worker-only and test-only'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM durable_jobs AS job
            JOIN prompt_simulation_job_specs AS spec
              ON spec.job_id = job.id AND spec.project_id = job.project_id
             AND spec.campaign_id = job.campaign_id
            JOIN prompt_simulations AS simulation
              ON simulation.id = spec.simulation_id
             AND simulation.project_id = spec.project_id
             AND simulation.campaign_id = spec.campaign_id
             AND simulation.opportunity_id = spec.opportunity_id
            JOIN prompt_simulation_results AS result
              ON result.simulation_id = simulation.id
             AND result.project_id = simulation.project_id
             AND result.campaign_id = simulation.campaign_id
             AND result.opportunity_id = simulation.opportunity_id
             AND result.generated_by_job_id = job.id
            JOIN model_call_logs AS model_call
              ON model_call.id = NEW.model_call_log_id
             AND model_call.project_id = job.project_id
             AND model_call.job_id = job.id
            JOIN artifact_finalize_outbox AS artifact
              ON artifact.project_id = simulation.project_id
             AND artifact.campaign_id = simulation.campaign_id
             AND artifact.opportunity_id = simulation.opportunity_id
             AND artifact.destination_id = simulation.destination_id
             AND artifact.resource_kind = 'prompt_simulation'
             AND artifact.resource_id = simulation.id
            WHERE job.id = NEW.source_job_id AND job.project_id = NEW.project_id
              AND job.campaign_id = NEW.campaign_id
              AND job.kind = 'prompt_simulation.generate' AND job.status = 'succeeded'
              AND simulation.binding_contract_version = 'opportunity-binding-v2'
              AND result.lineage_contract_version = 'opportunity-binding-v2'
              AND model_call.status = 'succeeded'
              AND model_call.configured_model = NEW.configured_model
              AND model_call.provider_reported_model
                    IS NOT DISTINCT FROM NEW.provider_reported_model
              AND artifact.status = 'finalized'
              AND artifact.final_uri = NEW.artifact_uri
              AND artifact.content_hash = NEW.artifact_hash
        ) THEN
            RAISE EXCEPTION 'synthetic observation lineage is incomplete'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.test_only OR NOT NEW.publication_eligible
          OR NEW.source_job_id IS NOT NULL OR NEW.model_call_log_id IS NOT NULL THEN
        RAISE EXCEPTION 'public answer observations cannot use synthetic flags'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_require_observation_citation_capture() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_contract_version = 'geo-observation-source-v2' AND (
        SELECT count(*) FROM monitoring_observation_citations AS citation
        WHERE citation.observation_id = NEW.id AND citation.project_id = NEW.project_id
    ) <> jsonb_array_length(NEW.raw_citations) THEN
        RAISE EXCEPTION 'captured citation rows do not match raw citation evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER monitoring_observation_source_guard
BEFORE INSERT ON monitoring_observations
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_observation_source();
CREATE CONSTRAINT TRIGGER monitoring_observation_citation_capture_guard
AFTER INSERT ON monitoring_observations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_observation_citation_capture();
CREATE TRIGGER monitoring_observations_immutable
BEFORE UPDATE OR DELETE ON monitoring_observations
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX monitoring_observations_source_stratum_idx
ON monitoring_observations (
    project_id, protocol_id, measurement_window, source_stratum_hash,
    monitoring_query_id, sample_index
);
CREATE INDEX monitoring_observations_source_job_fk_idx
ON monitoring_observations (source_job_id, project_id, campaign_id)
WHERE source_job_id IS NOT NULL;
CREATE INDEX monitoring_observations_model_call_fk_idx
ON monitoring_observations (model_call_log_id, project_id, source_job_id)
WHERE model_call_log_id IS NOT NULL;

ALTER TABLE monitoring_metric_snapshots
    ADD COLUMN source_stratum jsonb,
    ADD COLUMN source_stratum_hash text,
    ADD COLUMN capture_method text NOT NULL DEFAULT 'unknown',
    ADD COLUMN source_contract_version text NOT NULL DEFAULT 'legacy-v1',
    ALTER COLUMN source_contract_version SET DEFAULT 'geo-observation-source-v2',
    ADD CONSTRAINT monitoring_metric_source_stratum_type_check CHECK (
        source_stratum IS NULL OR jsonb_typeof(source_stratum) = 'object'
    ),
    ADD CONSTRAINT monitoring_metric_source_stratum_hash_check CHECK (
        source_stratum_hash IS NULL OR source_stratum_hash ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT monitoring_metric_capture_method_check CHECK (
        capture_method IN ('manual_ui', 'provider_api', 'proxy_grounded_api', 'unknown')
    ),
    ADD CONSTRAINT monitoring_metric_source_contract_check CHECK (
        source_contract_version IN ('legacy-v1', 'geo-observation-source-v2')
    ),
    ADD CONSTRAINT monitoring_metric_legacy_shape_check CHECK (
        source_contract_version <> 'legacy-v1'
        OR (capture_method = 'unknown' AND source_stratum IS NULL
            AND source_stratum_hash IS NULL)
    ),
    ADD CONSTRAINT monitoring_metric_source_slot_key UNIQUE NULLS NOT DISTINCT (
        protocol_id, measurement_window, source_stratum_hash, input_hash
    );

CREATE FUNCTION geo_assert_new_metric_source_stratum() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_contract_version <> 'geo-observation-source-v2'
       OR NEW.capture_method NOT IN ('manual_ui', 'provider_api', 'proxy_grounded_api')
       OR NEW.source_stratum IS NULL
       OR NOT geo_source_stratum_json_valid(NEW.source_stratum)
       OR NEW.capture_method <> NEW.source_stratum ->> 'capture_method'
       OR NEW.source_stratum_hash IS DISTINCT FROM
            geo_source_stratum_hash_from_json(NEW.source_stratum)
       OR NOT EXISTS (
            SELECT 1
            FROM monitoring_protocols AS protocol,
                 LATERAL jsonb_array_elements(
                     protocol.source_strata_snapshot
                 ) AS strata(item)
            WHERE protocol.id = NEW.protocol_id AND protocol.project_id = NEW.project_id
              AND protocol.campaign_id = NEW.campaign_id
              AND protocol.status = 'frozen'
              AND geo_source_stratum_hash_from_json(strata.item)
                    = NEW.source_stratum_hash
       ) THEN
        RAISE EXCEPTION 'metric snapshot source stratum is not frozen and eligible'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER monitoring_metric_source_stratum_guard
BEFORE INSERT ON monitoring_metric_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_metric_source_stratum();
CREATE INDEX monitoring_metric_snapshots_source_stratum_idx
ON monitoring_metric_snapshots (
    project_id, protocol_id, measurement_window, source_stratum_hash,
    computed_at DESC
);

CREATE TABLE monitoring_official_report_imports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    capture_method text NOT NULL DEFAULT 'official_report_import'
        CHECK (capture_method = 'official_report_import'),
    platform text NOT NULL CHECK (
        platform IN ('google', 'microsoft', 'other')
    ),
    platform_detail text,
    surface text NOT NULL CHECK (
        surface IN (
            'google_generative_ai_performance_report',
            'bing_ai_performance_report', 'other'
        )
    ),
    surface_kind text NOT NULL DEFAULT 'official_report'
        CHECK (surface_kind = 'official_report'),
    surface_detail text,
    artifact_uri text NOT NULL CHECK (artifact_uri ~ '^s3://[^/]+/.+$'),
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    parser_name text NOT NULL CHECK (btrim(parser_name) <> ''),
    parser_version text NOT NULL CHECK (btrim(parser_version) <> ''),
    report_period_start date NOT NULL,
    report_period_end date NOT NULL,
    account_ref text NOT NULL CHECK (btrim(account_ref) <> ''),
    row_count integer NOT NULL CHECK (row_count > 0),
    contract_version text NOT NULL DEFAULT 'geo-official-report-import-v1'
        CHECK (contract_version = 'geo-official-report-import-v1'),
    idempotency_key text NOT NULL CHECK (
        btrim(idempotency_key) <> '' AND length(idempotency_key) <= 200
    ),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    imported_by uuid NOT NULL REFERENCES identities(id),
    imported_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id),
    UNIQUE (id, project_id, campaign_id),
    UNIQUE (project_id, idempotency_key),
    CHECK (report_period_end >= report_period_start),
    CHECK (platform <> 'other' OR btrim(COALESCE(platform_detail, '')) <> ''),
    CHECK (surface <> 'other' OR btrim(COALESCE(surface_detail, '')) <> ''),
    CHECK (
        (surface = 'google_generative_ai_performance_report' AND platform = 'google')
        OR (surface = 'bing_ai_performance_report' AND platform = 'microsoft')
        OR surface = 'other'
    )
);

CREATE TABLE monitoring_official_report_rows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    import_id uuid NOT NULL,
    capture_method text NOT NULL DEFAULT 'official_report_import'
        CHECK (capture_method = 'official_report_import'),
    row_index integer NOT NULL CHECK (row_index >= 0),
    row_data jsonb NOT NULL CHECK (
        jsonb_typeof(row_data) = 'object' AND row_data <> '{}'::jsonb
    ),
    eligible boolean NOT NULL,
    ineligibility_reasons text[] NOT NULL DEFAULT ARRAY[]::text[],
    row_hash text NOT NULL CHECK (row_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (import_id, project_id, campaign_id)
        REFERENCES monitoring_official_report_imports(id, project_id, campaign_id)
        ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (import_id, row_index),
    UNIQUE (import_id, row_hash),
    CHECK (eligible OR cardinality(ineligibility_reasons) > 0),
    CHECK (NOT eligible OR cardinality(ineligibility_reasons) = 0)
);

CREATE FUNCTION geo_require_official_report_rows() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (
        SELECT count(*) FROM monitoring_official_report_rows AS report_row
        WHERE report_row.import_id = NEW.id
          AND report_row.project_id = NEW.project_id
          AND report_row.campaign_id = NEW.campaign_id
    ) <> NEW.row_count THEN
        RAISE EXCEPTION 'official report row count does not match its immutable import'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER monitoring_official_report_rows_required
AFTER INSERT ON monitoring_official_report_imports
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_official_report_rows();
CREATE TRIGGER monitoring_official_report_imports_immutable
BEFORE UPDATE OR DELETE ON monitoring_official_report_imports
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER monitoring_official_report_rows_immutable
BEFORE UPDATE OR DELETE ON monitoring_official_report_rows
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX monitoring_official_report_imports_campaign_idx
ON monitoring_official_report_imports (project_id, campaign_id, imported_at DESC);
CREATE INDEX monitoring_official_report_imports_campaign_fk_idx
ON monitoring_official_report_imports (campaign_id, project_id);
CREATE INDEX monitoring_official_report_imports_actor_idx
ON monitoring_official_report_imports (imported_by, imported_at DESC);
CREATE INDEX monitoring_official_report_rows_import_fk_idx
ON monitoring_official_report_rows (import_id, project_id, campaign_id);
CREATE INDEX monitoring_observation_legacy_state_observation_fk_idx
ON monitoring_observation_legacy_migration_state (observation_id, project_id);

ALTER TABLE monitoring_observation_legacy_migration_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitoring_observation_legacy_migration_state FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON monitoring_observation_legacy_migration_state
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));
ALTER TABLE monitoring_official_report_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitoring_official_report_imports FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON monitoring_official_report_imports
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));
ALTER TABLE monitoring_official_report_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitoring_official_report_rows FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON monitoring_official_report_rows
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON monitoring_observation_legacy_migration_state,
    monitoring_official_report_imports, monitoring_official_report_rows
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON monitoring_official_report_imports,
    monitoring_official_report_rows TO geo_app;
GRANT SELECT ON monitoring_official_report_imports,
    monitoring_official_report_rows TO geo_worker, geo_readonly;

REVOKE ALL ON FUNCTION geo_ascii_nonempty(text),
    geo_observation_surface_matches(text,text,text,text,text,text),
    geo_observation_source_stratum_canonical(
        text,text,text,text,text,text,text,text,text,text,text,text,text,text,boolean,text
    ),
    geo_observation_source_stratum_hash(
        text,text,text,text,text,text,text,text,text,text,text,text,text,text,boolean,text
    ),
    geo_source_stratum_json_valid(jsonb), geo_source_stratum_hash_from_json(jsonb),
    geo_source_strata_inventory_hash(jsonb), geo_assert_protocol_source_strata(),
    geo_assert_new_query_cluster(), geo_assert_new_observation_source(),
    geo_require_observation_citation_capture(), geo_assert_new_metric_source_stratum(),
    geo_require_official_report_rows()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_ascii_nonempty(text),
    geo_observation_surface_matches(text,text,text,text,text,text),
    geo_observation_source_stratum_canonical(
        text,text,text,text,text,text,text,text,text,text,text,text,text,text,boolean,text
    ),
    geo_observation_source_stratum_hash(
        text,text,text,text,text,text,text,text,text,text,text,text,text,text,boolean,text
    ),
    geo_source_stratum_json_valid(jsonb), geo_source_stratum_hash_from_json(jsonb),
    geo_source_strata_inventory_hash(jsonb), geo_assert_protocol_source_strata(),
    geo_assert_new_query_cluster(), geo_assert_new_observation_source(),
    geo_require_observation_citation_capture(), geo_assert_new_metric_source_stratum(),
    geo_require_official_report_rows()
TO geo_app, geo_worker;
