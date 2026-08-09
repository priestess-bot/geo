DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM model_gateway_terminal_events
        WHERE paid_call_count > 1
    ) THEN
        RAISE EXCEPTION
            'cannot downgrade SerpAPI budget contract while multi-request terminal events exist'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

-- Restore the trigger function installed by 0033 before restoring its table
-- checks.  This is the exact known function, not a catalog-wide rewrite.
DO $$
DECLARE
    definition text;
BEGIN
    definition := pg_get_functiondef(
        'public.geo_assert_model_gateway_terminal_shape()'::regprocedure
    );
    definition := replace(definition, 'paid_call_count >= 1', 'paid_call_count = 1');
    EXECUTE definition;
END;
$$;

ALTER TABLE model_gateway_terminal_events
    DROP CONSTRAINT model_gateway_terminal_events_paid_call_count_check,
    DROP CONSTRAINT model_gateway_terminal_events_status_shape,
    DROP CONSTRAINT model_gateway_terminal_events_failed_artifact_shape;
ALTER TABLE model_gateway_terminal_events
    ADD CONSTRAINT model_gateway_terminal_events_paid_call_count_check CHECK (
        paid_call_count IN (0, 1)
    ),
    ADD CONSTRAINT model_gateway_terminal_events_status_shape CHECK (
        (status = 'succeeded'
            AND paid_call_count = 1
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
            paid_call_count = 1
            AND error_classification IN (
                'application_structured_output',
                'application_result_contract',
                'manual_reconciliation'
            )
        )
    );

-- Restore the same three functions changed by upgrade(), in a fixed list.
DO $$
DECLARE
    definition text;
BEGIN
    definition := pg_get_functiondef(
        'public.geo_add_model_gateway_runtime_option(uuid,uuid,uuid,text,text,text,text,text,uuid,text,text,text,text,text,text,text[],jsonb,text,timestamptz)'::regprocedure
    );
    definition := replace(
        definition,
        'geo_model_gateway_provider_secret_purpose(p_provider)',
        '''model_provider.'' || p_provider'
    );
    EXECUTE definition;

    definition := pg_get_functiondef(
        'public.geo_assert_model_gateway_job_admission_insert()'::regprocedure
    );
    definition := replace(
        definition,
        'geo_model_gateway_provider_secret_purpose(NEW.provider)',
        '''model_provider.'' || NEW.provider'
    );
    EXECUTE definition;

    definition := pg_get_functiondef(
        'public.geo_assert_model_gateway_attempt_insert()'::regprocedure
    );
    definition := replace(
        definition,
        'geo_model_gateway_provider_secret_purpose(NEW.provider)',
        '''model_provider.'' || NEW.provider'
    );
    EXECUTE definition;
END;
$$;

ALTER TABLE model_gateway_runtime_options
    DROP CONSTRAINT model_gateway_runtime_options_secret_purpose;
ALTER TABLE model_gateway_runtime_options
    ADD CONSTRAINT model_gateway_runtime_options_secret_purpose CHECK (
        secret_purpose = 'model_provider.' || provider
    );

REVOKE ALL ON FUNCTION geo_model_gateway_provider_secret_purpose(text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_model_gateway_provider_secret_purpose(text);
