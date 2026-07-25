-- The governed Worker initializes the Secret Store runtime before it resolves
-- any Provider credential. The function is SECURITY DEFINER and validates key
-- order, algorithm, state and canary ciphertext itself; granting execute to
-- geo_worker permits only that bounded synchronization path.
GRANT EXECUTE ON FUNCTION
    geo_sync_secret_master_key_version(integer, text, text, bytea, bytea, timestamptz)
TO geo_worker;
