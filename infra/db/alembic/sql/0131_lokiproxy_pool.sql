-- SerpAPI was never populated in the canonical database. Fail explicitly on
-- another environment rather than silently rewriting immutable runtime lineage.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM model_gateway_runtime_options
        WHERE provider NOT IN (
            'deepseek', 'openai', 'kimi', 'gemini', 'perplexity', 'microsoft'
        )
    ) THEN
        RAISE EXCEPTION
            'retire unsupported Model Gateway runtime options before 0131'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION geo_model_gateway_provider_secret_purpose(p_provider text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
STRICT
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF p_provider IN (
        'deepseek', 'openai', 'kimi', 'gemini', 'perplexity', 'microsoft'
    ) THEN
        RETURN 'model_provider.' || p_provider;
    END IF;
    RAISE EXCEPTION 'unsupported Model Gateway provider: %', p_provider
        USING ERRCODE = '22023';
END;
$$;

ALTER TABLE browser_egress_endpoints
    ADD COLUMN provider text NOT NULL DEFAULT 'manual',
    ADD COLUMN pool_product text NOT NULL DEFAULT 'manual',
    ADD COLUMN session_ttl_seconds integer NOT NULL DEFAULT 600,
    ADD COLUMN max_concurrency integer NOT NULL DEFAULT 1,
    ADD COLUMN health_status text NOT NULL DEFAULT 'untested',
    ADD COLUMN consecutive_failures integer NOT NULL DEFAULT 0,
    ADD COLUMN last_checked_at timestamptz,
    ADD COLUMN cooldown_until timestamptz,
    ADD COLUMN last_error_class text;

ALTER TABLE browser_egress_endpoints
    ADD CONSTRAINT browser_egress_endpoints_provider CHECK (
        provider IN ('manual', 'lokiproxy')
    ),
    ADD CONSTRAINT browser_egress_endpoints_pool_product CHECK (
        pool_product IN ('manual', 'rotating_residential', 'mobile')
    ),
    ADD CONSTRAINT browser_egress_endpoints_session_ttl CHECK (
        session_ttl_seconds BETWEEN 300 AND 10800
    ),
    ADD CONSTRAINT browser_egress_endpoints_max_concurrency CHECK (
        max_concurrency BETWEEN 1 AND 100
    ),
    ADD CONSTRAINT browser_egress_endpoints_health CHECK (
        health_status IN ('untested', 'healthy', 'degraded', 'cooldown', 'disabled')
        AND consecutive_failures >= 0
        AND (health_status = 'cooldown') = (cooldown_until IS NOT NULL)
    ),
    ADD CONSTRAINT browser_egress_endpoints_lokiproxy_shape CHECK (
        provider <> 'lokiproxy'
        OR (
            secret_purpose = 'browser_egress.lokiproxy'
            AND protocol IN ('http', 'https')
            AND sticky_mode = 'credential_session'
            AND (
                (pool_product = 'rotating_residential' AND network_type = 'residential')
                OR (pool_product = 'mobile' AND network_type = 'mobile')
            )
        )
    );

CREATE FUNCTION geo_update_browser_egress_pool_health()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    next_failures integer;
BEGIN
    IF NEW.status NOT IN ('succeeded', 'failed') THEN
        RETURN NEW;
    END IF;
    IF NEW.status = 'succeeded' AND NEW.eligible IS TRUE THEN
        UPDATE browser_egress_endpoints
           SET health_status = 'healthy', consecutive_failures = 0,
               last_checked_at = coalesce(NEW.finished_at, clock_timestamp()),
               cooldown_until = NULL, last_error_class = NULL
         WHERE project_id = NEW.project_id AND id = NEW.endpoint_id
           AND provider = 'lokiproxy' AND status = 'approved';
        RETURN NEW;
    END IF;

    SELECT consecutive_failures + 1 INTO next_failures
      FROM browser_egress_endpoints
     WHERE project_id = NEW.project_id AND id = NEW.endpoint_id
       AND provider = 'lokiproxy' AND status = 'approved'
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
    UPDATE browser_egress_endpoints
       SET consecutive_failures = next_failures,
           health_status = CASE WHEN next_failures >= 3 THEN 'cooldown' ELSE 'degraded' END,
           last_checked_at = coalesce(NEW.finished_at, clock_timestamp()),
           cooldown_until = CASE WHEN next_failures >= 3
               THEN clock_timestamp() + interval '15 minutes' ELSE NULL END,
           last_error_class = coalesce(NEW.error_class, NEW.outcome, 'egress_test_failed')
     WHERE project_id = NEW.project_id AND id = NEW.endpoint_id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER browser_egress_pool_health_projection
AFTER UPDATE OF status, eligible, error_class ON browser_egress_tests
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status OR OLD.eligible IS DISTINCT FROM NEW.eligible)
EXECUTE FUNCTION geo_update_browser_egress_pool_health();

REVOKE ALL ON FUNCTION geo_update_browser_egress_pool_health()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

CREATE INDEX browser_egress_endpoints_pool_health_idx
ON browser_egress_endpoints(
    project_id, provider, egress_cohort_key, health_status, cooldown_until
)
WHERE status = 'approved';

-- Freeze the provider-managed pool shape at Egress-test admission. An Egress
-- test may be requested for an untested/degraded pool, but never for a
-- disabled pool or while its cooldown is still active. The payload also
-- carries the immutable pool settings so the worker can reject drift before
-- opening a proxy connection.
DO $$
DECLARE
    definition text;
BEGIN
    definition := pg_get_functiondef(
        'public.geo_enqueue_browser_egress_test(uuid,uuid,uuid,uuid,timestamptz)'::regprocedure
    );
    definition := replace(
        definition,
        'OR endpoint.expected_country <> ''AU''',
        'OR endpoint.expected_country <> ''AU'' '
        'OR endpoint.provider <> ''lokiproxy'' '
        'OR endpoint.health_status = ''disabled'' '
        'OR (endpoint.cooldown_until IS NOT NULL AND endpoint.cooldown_until > p_requested_at)'
    );
    definition := replace(
        definition,
        '''egress_cohort_key'', endpoint.egress_cohort_key,',
        '''egress_cohort_key'', endpoint.egress_cohort_key, '
        '''provider'', endpoint.provider, '
        '''pool_product'', endpoint.pool_product, '
        '''session_ttl_seconds'', endpoint.session_ttl_seconds, '
        '''max_concurrency'', endpoint.max_concurrency,'
    );
    EXECUTE definition;
END;
$$;

-- Keep the existing public function signatures while tightening both single
-- and bulk capture admission to a tested, non-cooled-down LokiProxy pool.
DO $$
DECLARE
    definition text;
BEGIN
    definition := pg_get_functiondef(
        'public.geo_enqueue_browser_capture_attempt(uuid,uuid,uuid,uuid,integer,uuid,uuid,uuid,text,text,timestamptz,timestamptz)'::regprocedure
    );
    definition := replace(
        definition,
        'OR endpoint.status <> ''approved'' OR endpoint.expected_country <> ''AU''',
        'OR endpoint.status <> ''approved'' OR endpoint.provider <> ''lokiproxy'' '
        'OR endpoint.health_status <> ''healthy'' '
        'OR endpoint.cooldown_until IS NOT NULL '
        'OR endpoint.expected_country <> ''AU'''
    );
    EXECUTE definition;

    definition := pg_get_functiondef(
        'public.geo_enqueue_ready_browser_capture_attempts(uuid,uuid,uuid,uuid,uuid,text,text,timestamptz,timestamptz,integer,jsonb)'::regprocedure
    );
    definition := replace(
        definition,
        'OR endpoint_row.status <> ''approved''',
        'OR endpoint_row.status <> ''approved'' '
        'OR endpoint_row.provider <> ''lokiproxy'' '
        'OR endpoint_row.health_status <> ''healthy'' '
        'OR endpoint_row.cooldown_until IS NOT NULL'
    );
    EXECUTE definition;

    definition := pg_get_functiondef(
        'public.geo_start_browser_capture_execution(uuid,uuid,uuid,integer,text,text,timestamptz,timestamptz,text)'::regprocedure
    );
    definition := replace(
        definition,
        '    IF durable.id IS NULL OR spec.job_id IS NULL',
        '    IF spec.egress_endpoint_id IS NOT NULL THEN '
        'PERFORM pg_advisory_xact_lock(hashtextextended('
        '$lock$lokiproxy-pool:$lock$ || p_project_id::text || chr(58) '
        '|| spec.egress_endpoint_id::text, 0)); END IF; '
        'IF durable.id IS NULL OR spec.job_id IS NULL'
    );
    definition := replace(
        definition,
        'AND endpoint.status = ''approved''',
        'AND endpoint.status = ''approved'' '
        'AND endpoint.provider = ''lokiproxy'' '
        'AND endpoint.health_status = ''healthy'' '
        'AND endpoint.cooldown_until IS NULL '
        'AND (SELECT count(*) FROM browser_capture_sessions active_session '
        'WHERE active_session.project_id = p_project_id '
        'AND active_session.egress_endpoint_id = endpoint.id '
        'AND active_session.status = ''running'') < endpoint.max_concurrency '
    );
    EXECUTE definition;
END;
$$;
