-- The restricted App writer must prove that its mounted keyring matches the
-- Worker-registered canaries before it stages encrypted evidence. It receives
-- no direct SELECT privilege on the global master-key table.
CREATE FUNCTION geo_read_workflow_c_artifact_keyring_canaries()
RETURNS TABLE (
    master_key_version integer,
    status text,
    algorithm text,
    canary_nonce bytea,
    canary_ciphertext bytea,
    retired_at timestamptz
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = pg_catalog, public
SET row_security = off
AS $$
    SELECT key_version.master_key_version,
           key_version.status,
           key_version.algorithm,
           key_version.canary_nonce,
           key_version.canary_ciphertext,
           key_version.retired_at
      FROM workflow_c_artifact_master_key_versions AS key_version
     WHERE key_version.status <> 'retired'
     ORDER BY key_version.master_key_version
$$;

REVOKE ALL ON FUNCTION geo_read_workflow_c_artifact_keyring_canaries()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_read_workflow_c_artifact_keyring_canaries()
TO geo_app, geo_worker;
