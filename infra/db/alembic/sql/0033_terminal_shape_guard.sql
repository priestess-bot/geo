-- Preserve deterministic terminal-event contract errors before the Model
-- Gateway artifact trigger performs any lineage or storage checks. PostgreSQL
-- runs BEFORE triggers before table CHECK constraints, so this trigger must
-- sort before the existing model_gateway_terminal_events_insert_guard.
CREATE FUNCTION geo_assert_model_gateway_terminal_shape() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF NOT (
        (NEW.status = 'succeeded'
            AND NEW.paid_call_count = 1
            AND NEW.output_hash IS NOT NULL AND NEW.response_hash IS NOT NULL
            AND (
                NEW.error_classification IS NULL
                OR NEW.error_classification = 'manual_reconciliation'
            )
            AND NEW.error_code IS NULL
            AND NEW.error_retryable IS NULL)
        OR (NEW.status = 'failed'
            AND NEW.error_classification IS NOT NULL AND NEW.error_code IS NOT NULL
            AND NEW.error_retryable IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'status_shape' USING ERRCODE = '23514';
    END IF;
    IF (NEW.reconciled_by IS NULL) <> (NEW.reconciliation_evidence_ref IS NULL) THEN
        RAISE EXCEPTION 'reconciliation_pair' USING ERRCODE = '23514';
    END IF;
    IF NOT (
        (NEW.reconciled_by IS NULL
            AND NEW.error_classification IS DISTINCT FROM 'manual_reconciliation')
        OR (NEW.reconciled_by IS NOT NULL
            AND NEW.error_classification = 'manual_reconciliation')
    ) THEN
        RAISE EXCEPTION 'reconciliation_class' USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'failed' AND NOT (
        (NEW.output_hash IS NULL AND NEW.response_hash IS NULL
            AND NEW.gateway_call_log_id IS NULL)
        OR (
            NEW.paid_call_count = 1
            AND NEW.error_classification IN (
                'application_structured_output',
                'application_result_contract',
                'manual_reconciliation'
            )
        )
    ) THEN
        RAISE EXCEPTION 'failed_artifact_shape' USING ERRCODE = '23514';
    END IF;
    IF NEW.raw_artifact_storage_decision <> 'allowed'
       AND NEW.raw_artifact_reference_hash IS NOT NULL THEN
        RAISE EXCEPTION 'raw_storage_shape' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER aaa_model_gateway_terminal_shape_guard
BEFORE INSERT ON model_gateway_terminal_events
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_terminal_shape();

REVOKE ALL ON FUNCTION geo_assert_model_gateway_terminal_shape()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
