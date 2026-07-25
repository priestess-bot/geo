-- Add Kimi as a first-class Provider API source without using a consumer-UI label.

ALTER TABLE monitoring_observations
    DROP CONSTRAINT monitoring_observations_platform_check,
    DROP CONSTRAINT monitoring_observations_surface_check;

CREATE OR REPLACE FUNCTION geo_observation_surface_matches(
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
            WHEN 'kimi_api' THEN platform = 'kimi' AND surface_kind = 'provider_api'
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

DO $migration$
DECLARE
    function_name text;
    function_source text;
BEGIN
    FOREACH function_name IN ARRAY ARRAY[
        'geo_source_stratum_json_valid(jsonb)',
        'geo_source_stratum_v3_json_valid(jsonb)'
    ] LOOP
        SELECT pg_get_functiondef(function_name::regprocedure) INTO function_source;
        IF strpos(function_source, '''microsoft'', ''anthropic''') = 0 THEN
            RAISE EXCEPTION 'unexpected source validation function shape: %', function_name;
        END IF;
        function_source := replace(
            function_source,
            '''microsoft'', ''anthropic''',
            '''microsoft'', ''kimi'', ''anthropic'''
        );
        EXECUTE function_source;
    END LOOP;
END
$migration$;

ALTER TABLE monitoring_observations
    ADD CONSTRAINT monitoring_observations_platform_check CHECK (
        platform IN (
            'openai', 'google', 'perplexity', 'microsoft', 'kimi', 'anthropic', 'other'
        )
    ),
    ADD CONSTRAINT monitoring_observations_surface_check CHECK (
        surface IN (
            'chatgpt_search', 'google_search', 'google_ai_overviews',
            'google_ai_mode', 'gemini', 'perplexity_answer', 'bing_search',
            'bing_copilot', 'claude_ai', 'openai_api', 'google_gemini_api',
            'perplexity_api', 'kimi_api', 'anthropic_api',
            'microsoft_foundry_bing_grounding', 'google_vertex_grounding',
            'internal_benchmark', 'other'
        )
    );
