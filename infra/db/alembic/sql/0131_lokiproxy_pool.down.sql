-- Restore the 0113 Egress-test admission function before removing the
-- provider-managed pool columns it no longer knows about.
DO $$
DECLARE
    definition text;
BEGIN
    definition := pg_get_functiondef(
        'public.geo_enqueue_browser_egress_test(uuid,uuid,uuid,uuid,timestamptz)'::regprocedure
    );
    definition := replace(
        definition,
        'OR endpoint.expected_country <> ''AU'' '
        'OR endpoint.provider <> ''lokiproxy'' '
        'OR endpoint.health_status = ''disabled'' '
        'OR (endpoint.cooldown_until IS NOT NULL AND endpoint.cooldown_until > p_requested_at)',
        'OR endpoint.expected_country <> ''AU'''
    );
    definition := replace(
        definition,
        '''egress_cohort_key'', endpoint.egress_cohort_key, '
        '''provider'', endpoint.provider, '
        '''pool_product'', endpoint.pool_product, '
        '''session_ttl_seconds'', endpoint.session_ttl_seconds, '
        '''max_concurrency'', endpoint.max_concurrency,',
        '''egress_cohort_key'', endpoint.egress_cohort_key,'
    );
    EXECUTE definition;
END;
$$;

DO $$
DECLARE
    definition text;
BEGIN
    definition := pg_get_functiondef(
        'public.geo_enqueue_browser_capture_attempt(uuid,uuid,uuid,uuid,integer,uuid,uuid,uuid,text,text,timestamptz,timestamptz)'::regprocedure
    );
    definition := replace(
        definition,
        'OR endpoint.status <> ''approved'' OR endpoint.provider <> ''lokiproxy'' '
        'OR endpoint.health_status <> ''healthy'' '
        'OR endpoint.cooldown_until IS NOT NULL '
        'OR endpoint.expected_country <> ''AU''',
        'OR endpoint.status <> ''approved'' OR endpoint.expected_country <> ''AU'''
    );
    EXECUTE definition;

    definition := pg_get_functiondef(
        'public.geo_enqueue_ready_browser_capture_attempts(uuid,uuid,uuid,uuid,uuid,text,text,timestamptz,timestamptz,integer,jsonb)'::regprocedure
    );
    definition := replace(
        definition,
        'OR endpoint_row.status <> ''approved'' '
        'OR endpoint_row.provider <> ''lokiproxy'' '
        'OR endpoint_row.health_status <> ''healthy'' '
        'OR endpoint_row.cooldown_until IS NOT NULL',
        'OR endpoint_row.status <> ''approved'''
    );
    EXECUTE definition;

    definition := pg_get_functiondef(
        'public.geo_start_browser_capture_execution(uuid,uuid,uuid,integer,text,text,timestamptz,timestamptz,text)'::regprocedure
    );
    definition := replace(
        definition,
        '    IF spec.egress_endpoint_id IS NOT NULL THEN '
        'PERFORM pg_advisory_xact_lock(hashtextextended('
        '$lock$lokiproxy-pool:$lock$ || p_project_id::text || chr(58) '
        '|| spec.egress_endpoint_id::text, 0)); END IF; '
        'IF durable.id IS NULL OR spec.job_id IS NULL',
        '    IF durable.id IS NULL OR spec.job_id IS NULL'
    );
    definition := replace(
        definition,
        'AND endpoint.status = ''approved'' '
        'AND endpoint.provider = ''lokiproxy'' '
        'AND endpoint.health_status = ''healthy'' '
        'AND endpoint.cooldown_until IS NULL '
        'AND (SELECT count(*) FROM browser_capture_sessions active_session '
        'WHERE active_session.project_id = p_project_id '
        'AND active_session.egress_endpoint_id = endpoint.id '
        'AND active_session.status = ''running'') < endpoint.max_concurrency ',
        'AND endpoint.status = ''approved'''
    );
    EXECUTE definition;
END;
$$;

DROP INDEX browser_egress_endpoints_pool_health_idx;

DROP TRIGGER browser_egress_pool_health_projection ON browser_egress_tests;
DROP FUNCTION geo_update_browser_egress_pool_health();

ALTER TABLE browser_egress_endpoints
    DROP CONSTRAINT browser_egress_endpoints_lokiproxy_shape,
    DROP CONSTRAINT browser_egress_endpoints_health,
    DROP CONSTRAINT browser_egress_endpoints_max_concurrency,
    DROP CONSTRAINT browser_egress_endpoints_session_ttl,
    DROP CONSTRAINT browser_egress_endpoints_pool_product,
    DROP CONSTRAINT browser_egress_endpoints_provider,
    DROP COLUMN last_error_class,
    DROP COLUMN cooldown_until,
    DROP COLUMN last_checked_at,
    DROP COLUMN consecutive_failures,
    DROP COLUMN health_status,
    DROP COLUMN max_concurrency,
    DROP COLUMN session_ttl_seconds,
    DROP COLUMN pool_product,
    DROP COLUMN provider;

CREATE OR REPLACE FUNCTION geo_model_gateway_provider_secret_purpose(p_provider text)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT CASE
        WHEN p_provider = 'serpapi' THEN 'search.serpapi'
        ELSE 'model_provider.' || p_provider
    END
$$;
