-- The Worker already has SELECT and UPDATE(status) on this guarded keyring.
-- It also needs INSERT only for an initial immutable canary registration.
GRANT INSERT ON recommendation_artifact_master_key_versions TO geo_worker;
