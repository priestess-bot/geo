-- Keep the database boundary aligned with the application guard.  Secret
-- references remain valid immutable lineage; credential values, session state
-- and proxy configuration do not belong in a Durable Job spec.
CREATE OR REPLACE FUNCTION geo_workflow_c_job_spec_payload_is_safe(p_value jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
DECLARE child_key text;
DECLARE child_value jsonb;
DECLARE normalized_key text;
BEGIN
    CASE jsonb_typeof(p_value)
        WHEN 'object' THEN
            FOR child_key, child_value IN SELECT key, value FROM jsonb_each(p_value)
            LOOP
                normalized_key := replace(lower(btrim(child_key)), '-', '_');
                IF normalized_key = ANY (ARRAY[
                    'access_token', 'api_key', 'authorization', 'client_secret',
                    'cookie', 'cookies', 'secret', 'secret_value', 'credential',
                    'credential_value', 'password', 'passwd', 'proxy',
                    'proxy_credentials', 'proxy_password', 'proxy_url',
                    'refresh_token', 'id_token', 'session', 'session_token',
                    'storage_state', 'token'
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
        ELSE
            NULL;
    END CASE;
    RETURN true;
END;
$$;

COMMENT ON FUNCTION geo_workflow_c_job_spec_payload_is_safe(jsonb) IS
    'Recursively rejects credential values while allowing immutable Secret Store reference lineage.';
