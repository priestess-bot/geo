ALTER TABLE browser_capture_sessions
DROP CONSTRAINT browser_capture_sessions_project_id_sampling_attempt_id_key;
ALTER TABLE browser_capture_sessions
ADD COLUMN execution_ordinal integer NOT NULL DEFAULT 1 CHECK (execution_ordinal > 0);
ALTER TABLE browser_capture_sessions
ADD CONSTRAINT browser_capture_sessions_attempt_execution_key
UNIQUE (project_id, sampling_attempt_id, execution_ordinal);

ALTER TABLE browser_egress_verifications
DROP CONSTRAINT browser_egress_verifications_project_id_sampling_attempt_id_key;
ALTER TABLE browser_page_artifact_bundles
DROP CONSTRAINT browser_page_artifact_bundles_project_id_sampling_attempt_i_key;

CREATE FUNCTION geo_start_browser_capture_execution(
    p_project_id uuid, p_job_id uuid, p_lease_token uuid, p_fencing_generation integer,
    p_sticky_lease_id text, p_sticky_lease_hash text,
    p_lease_started_at timestamptz, p_lease_expires_at timestamptz,
    p_session_hash text
) RETURNS TABLE (
    capture_session_id uuid, execution_ordinal integer, spec_hash text,
    task_version integer, attempt_version integer, spec_payload jsonb,
    question_text text, surface jsonb, endpoint jsonb, profile jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE spec browser_capture_job_specs%ROWTYPE;
DECLARE attempt workflow_c_sampling_attempts%ROWTYPE;
DECLARE task workflow_c_sampling_tasks%ROWTYPE;
DECLARE ordinal_value integer;
DECLARE session_id uuid := gen_random_uuid();
BEGIN
    SELECT * INTO durable FROM durable_jobs
     WHERE project_id = p_project_id AND id = p_job_id FOR UPDATE;
    SELECT * INTO spec FROM browser_capture_job_specs
     WHERE project_id = p_project_id AND job_id = p_job_id FOR SHARE;
    SELECT * INTO attempt FROM workflow_c_sampling_attempts
     WHERE project_id = p_project_id AND durable_job_id = p_job_id FOR UPDATE;
    SELECT * INTO task FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND id = attempt.task_id FOR UPDATE;
    IF durable.id IS NULL OR spec.job_id IS NULL OR attempt.id IS NULL OR task.id IS NULL
       OR durable.kind <> 'browser.capture' OR durable.status <> 'running'
       OR durable.lease_token <> p_lease_token
       OR durable.fencing_generation <> p_fencing_generation
       OR durable.lease_expires_at <= clock_timestamp()
       OR durable.input_hash <> spec.spec_hash
       OR attempt.id <> spec.attempt_id OR task.id <> spec.task_id
       OR attempt.status NOT IN ('queued', 'running')
       OR task.status NOT IN ('queued', 'running')
       OR NOT EXISTS (
            SELECT 1 FROM browser_surface_releases surface
             WHERE surface.project_id = p_project_id
               AND surface.id = spec.surface_release_id
               AND surface.status = 'approved'
               AND surface.authorization_status = 'approved'
               AND surface.authorization_valid_until > clock_timestamp()
       )
       OR NOT EXISTS (
            SELECT 1 FROM browser_egress_endpoints endpoint
             JOIN secret_versions secret
               ON secret.reference_id = endpoint.secret_reference_id
              AND secret.project_id = endpoint.project_id
              AND secret.purpose = endpoint.secret_purpose
              AND secret.version = endpoint.secret_version
              AND secret.status = 'active'
             WHERE endpoint.project_id = p_project_id
               AND endpoint.id = spec.egress_endpoint_id
               AND endpoint.status = 'approved'
               AND endpoint.expected_country = 'AU'
               AND endpoint.network_type IN ('residential', 'mobile')
       )
       OR NOT EXISTS (
            SELECT 1 FROM browser_profile_versions profile
             WHERE profile.project_id = p_project_id
               AND profile.id = spec.profile_version_id
               AND profile.status = 'approved'
       )
       OR p_sticky_lease_hash !~ '^[0-9a-f]{64}$'
       OR btrim(coalesce(p_sticky_lease_id, '')) = ''
       OR p_session_hash !~ '^[0-9a-f]{64}$'
       OR p_lease_started_at IS NULL OR p_lease_expires_at <= p_lease_started_at THEN
        RAISE EXCEPTION 'Browser Capture execution start was fenced' USING ERRCODE = '40001';
    END IF;
    IF attempt.status = 'queued' THEN
        UPDATE workflow_c_sampling_attempts SET status = 'running', version = version + 1,
            updated_at = clock_timestamp()
         WHERE project_id = p_project_id AND id = attempt.id AND version = attempt.version;
    END IF;
    IF task.status = 'queued' THEN
        UPDATE workflow_c_sampling_tasks SET status = 'running', version = version + 1,
            updated_at = clock_timestamp()
         WHERE project_id = p_project_id AND id = task.id AND version = task.version;
    END IF;
    SELECT coalesce(max(item.execution_ordinal), 0) + 1 INTO ordinal_value
      FROM browser_capture_sessions item
     WHERE item.project_id = p_project_id AND item.sampling_attempt_id = attempt.id;
    INSERT INTO browser_capture_sessions(
        id, project_id, sampling_attempt_id, surface_release_id, egress_endpoint_id,
        profile_version_id, sticky_lease_id, sticky_lease_hash, lease_started_at,
        lease_expires_at, session_hash, status, started_at, execution_ordinal
    ) VALUES (
        session_id, p_project_id, attempt.id, spec.surface_release_id,
        spec.egress_endpoint_id, spec.profile_version_id, p_sticky_lease_id,
        p_sticky_lease_hash, p_lease_started_at, p_lease_expires_at,
        p_session_hash, 'running', clock_timestamp(), ordinal_value
    );
    RETURN QUERY SELECT session_id, ordinal_value, spec.spec_hash,
        (SELECT version FROM workflow_c_sampling_tasks
          WHERE project_id = p_project_id AND id = task.id),
        (SELECT version FROM workflow_c_sampling_attempts
          WHERE project_id = p_project_id AND id = attempt.id),
        spec.spec_payload, spec.question_text,
        (SELECT to_jsonb(value) FROM browser_surface_releases value
          WHERE value.project_id = p_project_id AND value.id = spec.surface_release_id),
        (SELECT to_jsonb(value) FROM browser_egress_endpoints value
          WHERE value.project_id = p_project_id AND value.id = spec.egress_endpoint_id),
        (SELECT to_jsonb(value) FROM browser_profile_versions value
          WHERE value.project_id = p_project_id AND value.id = spec.profile_version_id);
END;
$$;

CREATE FUNCTION geo_commit_browser_capture_execution(
    p_project_id uuid, p_job_id uuid, p_lease_token uuid, p_fencing_generation integer,
    p_capture_session_id uuid, p_expected_task_version integer,
    p_expected_attempt_version integer,
    p_verification_id uuid, p_pre jsonb, p_post jsonb, p_ip_hash text, p_asn text,
    p_country text, p_region text, p_network_type text, p_connection_log_reference text,
    p_connection_log_hash text, p_verification_hash text, p_egress_outcome text,
    p_egress_eligible boolean,
    p_bundle_id uuid, p_manifest_uri text, p_manifest_hash text, p_screenshot_hash text,
    p_dom_hash text, p_har_hash text, p_final_url text, p_final_url_hash text,
    p_page_location jsonb, p_encryption_key_reference text, p_retention_until timestamptz,
    p_parsed_id uuid, p_result_class text, p_answer_text text, p_citations jsonb,
    p_evidence_locators jsonb, p_parser_release text, p_parsed_hash text,
    p_parsed_eligible boolean, p_observed_at timestamptz,
    p_observation_id uuid, p_observation_hash text, p_evidence_status text,
    p_ineligible_reasons jsonb, p_actual_location jsonb, p_actual_location_hash text,
    p_evidence jsonb
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE spec browser_capture_job_specs%ROWTYPE;
DECLARE attempt workflow_c_sampling_attempts%ROWTYPE;
DECLARE task workflow_c_sampling_tasks%ROWTYPE;
BEGIN
    PERFORM geo_validate_workflow_c_sampling_observation_input(
        p_observation_id, p_observation_hash, p_evidence_status, p_ineligible_reasons,
        p_actual_location, p_actual_location_hash, p_evidence, p_observed_at
    );
    SELECT * INTO durable FROM durable_jobs
     WHERE project_id = p_project_id AND id = p_job_id FOR UPDATE;
    SELECT * INTO spec FROM browser_capture_job_specs
     WHERE project_id = p_project_id AND job_id = p_job_id FOR SHARE;
    SELECT * INTO attempt FROM workflow_c_sampling_attempts
     WHERE project_id = p_project_id AND id = spec.attempt_id FOR UPDATE;
    SELECT * INTO task FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND id = spec.task_id FOR UPDATE;
    IF durable.status NOT IN ('running', 'finalizing') OR durable.lease_token <> p_lease_token
       OR durable.fencing_generation <> p_fencing_generation
       OR durable.lease_expires_at <= clock_timestamp() OR durable.input_hash <> spec.spec_hash
       OR attempt.status <> 'running' OR attempt.version <> p_expected_attempt_version
       OR task.status <> 'running' OR task.version <> p_expected_task_version
       OR btrim(coalesce(p_country, '')) = '' OR jsonb_typeof(p_pre) <> 'array'
       OR jsonb_typeof(p_post) <> 'array' OR jsonb_typeof(p_citations) <> 'array'
       OR jsonb_typeof(p_evidence_locators) <> 'object'
       OR jsonb_typeof(p_page_location) <> 'object' THEN
        RAISE EXCEPTION 'Browser Capture completion was fenced or invalid'
            USING ERRCODE = '40001';
    END IF;
    INSERT INTO browser_egress_verifications(
        id, project_id, capture_session_id, sampling_attempt_id, pre_observations,
        post_observations, observed_ip_hash, observed_asn, observed_country,
        observed_region, network_type, connection_log_reference, connection_log_hash,
        verification_hash, outcome, eligible, verified_at
    ) VALUES (
        p_verification_id, p_project_id, p_capture_session_id, attempt.id, p_pre, p_post,
        p_ip_hash, p_asn, p_country, p_region, p_network_type,
        p_connection_log_reference, p_connection_log_hash, p_verification_hash,
        p_egress_outcome, p_egress_eligible, p_observed_at
    );
    INSERT INTO browser_page_artifact_bundles(
        id, project_id, capture_session_id, sampling_attempt_id, egress_verification_id,
        manifest_uri, manifest_hash, screenshot_hash, dom_hash, har_hash, final_url,
        final_url_hash, page_location_signal, encryption_key_reference,
        retention_until, created_at
    ) VALUES (
        p_bundle_id, p_project_id, p_capture_session_id, attempt.id, p_verification_id,
        p_manifest_uri, p_manifest_hash, p_screenshot_hash, p_dom_hash, p_har_hash,
        p_final_url, p_final_url_hash, p_page_location, p_encryption_key_reference,
        p_retention_until, p_observed_at
    );
    INSERT INTO browser_parsed_observations(
        id, project_id, sampling_attempt_id, surface_release_id, artifact_bundle_id,
        egress_verification_id, result_class, answer_text, citations, evidence_locators,
        parser_release, observation_hash, eligible, observed_at
    ) VALUES (
        p_parsed_id, p_project_id, attempt.id, spec.surface_release_id, p_bundle_id,
        p_verification_id, p_result_class, p_answer_text, p_citations,
        p_evidence_locators, p_parser_release, p_parsed_hash, p_parsed_eligible, p_observed_at
    );
    INSERT INTO workflow_c_sampling_observations(
        id, project_id, run_id, task_id, attempt_id, task_key, source_stratum_hash,
        status, observation_hash, actual_location_json, evidence_json, payload, observed_at
    ) VALUES (
        p_observation_id, p_project_id, spec.run_id, spec.task_id, spec.attempt_id,
        task.task_key, task.source_stratum_hash, p_evidence_status, p_observation_hash,
        p_actual_location, p_evidence,
        jsonb_build_object('evidence_status', p_evidence_status,
            'ineligible_reasons', p_ineligible_reasons,
            'browser_parsed_observation_id', p_parsed_id), p_observed_at
    );
    UPDATE browser_capture_sessions SET status = CASE WHEN p_parsed_eligible
        THEN 'completed' ELSE 'blocked' END, closed_at = p_observed_at
     WHERE project_id = p_project_id AND id = p_capture_session_id AND status = 'running';
    UPDATE workflow_c_sampling_attempts SET status = 'succeeded',
        actual_location_json = p_actual_location, actual_location_hash = p_actual_location_hash,
        error_code = NULL, version = version + 1, updated_at = p_observed_at
     WHERE project_id = p_project_id AND id = attempt.id AND version = attempt.version;
    UPDATE workflow_c_sampling_tasks SET status = 'succeeded', version = version + 1,
        updated_at = p_observed_at
     WHERE project_id = p_project_id AND id = task.id AND version = task.version;
    IF NOT EXISTS (
        SELECT 1 FROM workflow_c_sampling_tasks item
         WHERE item.project_id = p_project_id AND item.run_id = spec.run_id
           AND item.status <> 'succeeded'
    ) THEN
        UPDATE workflow_c_sampling_runs SET status = 'completed', version = version + 1
         WHERE project_id = p_project_id AND id = spec.run_id AND status = 'running';
    END IF;
    RETURN p_observation_id;
END;
$$;

CREATE FUNCTION geo_reconcile_browser_capture_durable_status() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public SET row_security = off
AS $$
DECLARE attempt workflow_c_sampling_attempts%ROWTYPE;
DECLARE task workflow_c_sampling_tasks%ROWTYPE;
BEGIN
    IF NEW.kind <> 'browser.capture'
       OR NEW.status NOT IN ('retry_wait', 'failed', 'dead_lettered', 'cancelled') THEN
        RETURN NEW;
    END IF;
    SELECT * INTO attempt FROM workflow_c_sampling_attempts
     WHERE project_id = NEW.project_id AND durable_job_id = NEW.id FOR UPDATE;
    SELECT * INTO task FROM workflow_c_sampling_tasks
     WHERE project_id = NEW.project_id AND id = attempt.task_id FOR UPDATE;
    UPDATE browser_capture_sessions SET status = 'orphaned', closed_at = clock_timestamp()
     WHERE project_id = NEW.project_id AND sampling_attempt_id = attempt.id AND status = 'running';
    IF NEW.status = 'retry_wait' THEN
        UPDATE workflow_c_sampling_attempts SET status = 'queued', error_code = NEW.error_code,
            version = version + 1, updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = attempt.id AND status = 'running';
        UPDATE workflow_c_sampling_tasks SET status = 'retry_ready', version = version + 1,
            updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = task.id AND status = 'running';
        UPDATE workflow_c_sampling_tasks SET status = 'queued', version = version + 1,
            updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = task.id AND status = 'retry_ready';
    ELSE
        UPDATE workflow_c_sampling_attempts SET status = CASE WHEN NEW.status = 'cancelled'
            THEN 'cancelled' ELSE 'failed' END, error_code = coalesce(NEW.error_code, 'cancelled'),
            version = version + 1, updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = attempt.id
           AND status IN ('queued', 'running');
        UPDATE workflow_c_sampling_tasks SET status = CASE WHEN NEW.status = 'cancelled'
            THEN 'cancelled' ELSE 'failed' END, version = version + 1,
            updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = task.id
           AND status IN ('queued', 'running', 'retry_ready');
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER browser_capture_durable_status_reconcile
AFTER UPDATE OF status ON durable_jobs FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION geo_reconcile_browser_capture_durable_status();

REVOKE ALL ON FUNCTION geo_start_browser_capture_execution(
    uuid, uuid, uuid, integer, text, text, timestamptz, timestamptz, text
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_start_browser_capture_execution(
    uuid, uuid, uuid, integer, text, text, timestamptz, timestamptz, text
) TO geo_worker;
REVOKE ALL ON FUNCTION geo_commit_browser_capture_execution(
    uuid,uuid,uuid,integer,uuid,integer,integer,uuid,jsonb,jsonb,text,text,text,text,text,
    text,text,text,text,boolean,uuid,text,text,text,text,text,text,text,jsonb,text,timestamptz,
    uuid,text,text,jsonb,jsonb,text,text,boolean,timestamptz,uuid,text,text,jsonb,jsonb,text,jsonb
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_commit_browser_capture_execution(
    uuid,uuid,uuid,integer,uuid,integer,integer,uuid,jsonb,jsonb,text,text,text,text,text,
    text,text,text,text,boolean,uuid,text,text,text,text,text,text,text,jsonb,text,timestamptz,
    uuid,text,text,jsonb,jsonb,text,text,boolean,timestamptz,uuid,text,text,jsonb,jsonb,text,jsonb
) TO geo_worker;
REVOKE ALL ON FUNCTION geo_reconcile_browser_capture_durable_status()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
