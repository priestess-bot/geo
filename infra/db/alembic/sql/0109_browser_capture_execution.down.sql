DROP TRIGGER browser_capture_durable_status_reconcile ON durable_jobs;
DROP FUNCTION geo_reconcile_browser_capture_durable_status();
DROP FUNCTION geo_commit_browser_capture_execution(
    uuid,uuid,uuid,integer,uuid,integer,integer,uuid,jsonb,jsonb,text,text,text,text,text,
    text,text,text,text,boolean,uuid,text,text,text,text,text,text,text,jsonb,text,timestamptz,
    uuid,text,text,jsonb,jsonb,text,text,boolean,timestamptz,uuid,text,text,jsonb,jsonb,text,jsonb
);
DROP FUNCTION geo_start_browser_capture_execution(
    uuid, uuid, uuid, integer, text, text, timestamptz, timestamptz, text
);
ALTER TABLE browser_capture_sessions DROP CONSTRAINT browser_capture_sessions_attempt_execution_key;
ALTER TABLE browser_capture_sessions DROP COLUMN execution_ordinal;
ALTER TABLE browser_capture_sessions
ADD CONSTRAINT browser_capture_sessions_project_id_sampling_attempt_id_key
UNIQUE (project_id, sampling_attempt_id);
ALTER TABLE browser_egress_verifications
ADD CONSTRAINT browser_egress_verifications_project_id_sampling_attempt_id_key
UNIQUE (project_id, sampling_attempt_id);
ALTER TABLE browser_page_artifact_bundles
ADD CONSTRAINT browser_page_artifact_bundles_project_id_sampling_attempt_i_key
UNIQUE (project_id, sampling_attempt_id);
