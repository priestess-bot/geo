REVOKE ALL ON FUNCTION geo_enqueue_workflow_c_job_spec(
    uuid, text, text, jsonb, text, integer
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_enqueue_workflow_c_job_spec(uuid, text, text, jsonb, text, integer);

-- Restore the predecessor migration's direct-insert contract on downgrade.
GRANT INSERT ON workflow_c_job_specs TO geo_app, geo_worker;

CREATE OR REPLACE FUNCTION geo_workflow_c_job_spec_payload_is_safe(p_value jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
DECLARE child_key text;
DECLARE child_value jsonb;
BEGIN
    CASE jsonb_typeof(p_value)
        WHEN 'object' THEN
            FOR child_key, child_value IN SELECT key, value FROM jsonb_each(p_value)
            LOOP
                IF lower(child_key) = ANY (ARRAY[
                    'secret', 'secret_value', 'credential', 'credential_value',
                    'password', 'token', 'proxy_password', 'authorization'
                ]) OR NOT geo_workflow_c_job_spec_payload_is_safe(child_value) THEN
                    RETURN false;
                END IF;
            END LOOP;
        WHEN 'array' THEN
            FOR child_value IN SELECT value FROM jsonb_array_elements(p_value)
            LOOP
                IF NOT geo_workflow_c_job_spec_payload_is_safe(child_value) THEN
                    RETURN false;
                END IF;
            END LOOP;
    END CASE;
    RETURN true;
END;
$$;
