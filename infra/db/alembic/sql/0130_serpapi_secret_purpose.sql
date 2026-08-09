CREATE FUNCTION geo_model_gateway_provider_secret_purpose(p_provider text)
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

REVOKE ALL ON FUNCTION geo_model_gateway_provider_secret_purpose(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_model_gateway_provider_secret_purpose(text)
    TO geo_app, geo_worker, geo_readonly;

ALTER TABLE model_gateway_runtime_options
    DROP CONSTRAINT model_gateway_runtime_options_secret_purpose;
ALTER TABLE model_gateway_runtime_options
    ADD CONSTRAINT model_gateway_runtime_options_secret_purpose CHECK (
        secret_purpose = geo_model_gateway_provider_secret_purpose(provider)
    );

-- The paid-call counter is the durable budget ledger.  A page-token GET is
-- another paid request in the same logical Attempt, so the terminal event and
-- its trigger guard must accept any positive count for successful calls.
ALTER TABLE model_gateway_terminal_events
    DROP CONSTRAINT model_gateway_terminal_events_paid_call_count_check,
    DROP CONSTRAINT model_gateway_terminal_events_status_shape,
    DROP CONSTRAINT model_gateway_terminal_events_failed_artifact_shape;
ALTER TABLE model_gateway_terminal_events
    ADD CONSTRAINT model_gateway_terminal_events_paid_call_count_check CHECK (
        paid_call_count >= 0
    ),
    ADD CONSTRAINT model_gateway_terminal_events_status_shape CHECK (
        (status = 'succeeded'
            AND paid_call_count >= 1
            AND output_hash IS NOT NULL AND response_hash IS NOT NULL
            AND (
                error_classification IS NULL
                OR error_classification = 'manual_reconciliation'
            )
            AND error_code IS NULL
            AND error_retryable IS NULL)
        OR (status = 'failed'
            AND error_classification IS NOT NULL AND error_code IS NOT NULL
            AND error_retryable IS NOT NULL)
    ),
    ADD CONSTRAINT model_gateway_terminal_events_failed_artifact_shape CHECK (
        status <> 'failed'
        OR (
            output_hash IS NULL AND response_hash IS NULL
            AND gateway_call_log_id IS NULL
        )
        OR (
            paid_call_count >= 1
            AND error_classification IN (
                'application_structured_output',
                'application_result_contract',
                'manual_reconciliation'
            )
        )
    );

-- 0033 installed this trigger ahead of the table checks.  Recreate exactly
-- that known function, changing only the paid-call cardinality contract.
DO $$
DECLARE
    definition text;
BEGIN
    definition := pg_get_functiondef(
        'public.geo_assert_model_gateway_terminal_shape()'::regprocedure
    );
    definition := replace(definition, 'paid_call_count = 1', 'paid_call_count >= 1');
    EXECUTE definition;
END;
$$;

-- Recreate only the three known Model Gateway functions that embed the
-- provider Secret purpose.  An open-ended pg_proc scan could rewrite unrelated
-- application functions during an online migration.
DO $$
DECLARE
    definition text;
BEGIN
    definition := pg_get_functiondef(
        'public.geo_add_model_gateway_runtime_option(uuid,uuid,uuid,text,text,text,text,text,uuid,text,text,text,text,text,text,text[],jsonb,text,timestamptz)'::regprocedure
    );
    definition := replace(
        definition,
        '''model_provider.'' || p_provider',
        'geo_model_gateway_provider_secret_purpose(p_provider)'
    );
    EXECUTE definition;

    definition := pg_get_functiondef(
        'public.geo_assert_model_gateway_job_admission_insert()'::regprocedure
    );
    definition := replace(
        definition,
        '''model_provider.'' || NEW.provider',
        'geo_model_gateway_provider_secret_purpose(NEW.provider)'
    );
    EXECUTE definition;

    definition := pg_get_functiondef(
        'public.geo_assert_model_gateway_attempt_insert()'::regprocedure
    );
    definition := replace(
        definition,
        '''model_provider.'' || NEW.provider',
        'geo_model_gateway_provider_secret_purpose(NEW.provider)'
    );
    EXECUTE definition;
END;
$$;
