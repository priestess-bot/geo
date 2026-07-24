REVOKE ALL ON FUNCTION geo_read_workflow_c_artifact_keyring_canaries()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_read_workflow_c_artifact_keyring_canaries();
