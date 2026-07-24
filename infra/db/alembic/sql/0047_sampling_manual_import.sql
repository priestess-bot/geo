-- A manual capture is reviewed before it becomes a Sampling Attempt.  The
-- original foreign key made that lifecycle impossible by requiring the
-- Attempt before the submitter could create the pending import.  Keep the
-- immutable future attempt ID, but create its durable Job and Attempt only in
-- the approved review transaction below.
ALTER TABLE workflow_c_sampling_manual_imports
    DROP CONSTRAINT workflow_c_sampling_manual_imports_attempt_id_project_id_fkey;

ALTER TABLE workflow_c_sampling_manual_imports
    ADD COLUMN review_reason text;

-- Older rows predate the explicit review-rationale field. Preserve that fact
-- rather than inventing a business rationale, while allowing the strengthened
-- invariant to be added to databases that already contain historical imports.
UPDATE workflow_c_sampling_manual_imports
   SET review_reason = 'legacy review reason unavailable'
 WHERE status IN ('approved', 'rejected', 'committed')
   AND review_reason IS NULL;

ALTER TABLE workflow_c_sampling_manual_imports
    ADD CONSTRAINT workflow_c_sampling_manual_imports_review_reason_check CHECK (
        (status = 'submitted' AND review_reason IS NULL)
        OR (status IN ('approved', 'rejected', 'committed')
            AND btrim(coalesce(review_reason, '')) <> '')
    );

-- Only the two constrained RPCs below may create or decide an import.  The
-- Worker commits a previously approved import through its existing fenced RPC.
REVOKE INSERT, UPDATE, DELETE ON workflow_c_sampling_manual_imports FROM geo_app;
GRANT SELECT ON workflow_c_sampling_manual_imports TO geo_app;

CREATE FUNCTION geo_submit_workflow_c_manual_sampling_evidence(
    p_project_id uuid,
    p_import_id uuid,
    p_attempt_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_run_id uuid,
    p_task_id uuid,
    p_expected_task_version integer,
    p_artifact_manifest_id uuid,
    p_artifact_manifest_hash text,
    p_artifact_content_hash text,
    p_governance_policy_hash text,
    p_capture_session_id uuid,
    p_payload jsonb,
    p_submitted_by text,
    p_submitted_at timestamptz
) RETURNS TABLE (import_id uuid, aggregate_version integer, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE suite_row workflow_c_sampling_suites%ROWTYPE;
DECLARE policy workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE stored_import workflow_c_sampling_manual_imports%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Manual Sampling evidence is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_import_id IS NULL OR p_attempt_id IS NULL OR p_run_id IS NULL OR p_task_id IS NULL
       OR p_artifact_manifest_id IS NULL OR p_capture_session_id IS NULL
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_artifact_manifest_hash !~ '^[0-9a-f]{64}$'
       OR p_artifact_content_hash !~ '^[0-9a-f]{64}$'
       OR p_governance_policy_hash !~ '^[0-9a-f]{64}$'
       OR p_expected_task_version < 1
       OR btrim(coalesce(p_submitted_by, '')) = ''
       OR p_submitted_at IS NULL
       OR NOT geo_workflow_c_json_has_exact_keys(p_payload, ARRAY[
           'schema_version', 'task_key', 'expected_task_version', 'evidence_kind',
           'device', 'locale', 'captured_at', 'source_content_hash',
           'content_type', 'governance_policy_option_key', 'pre_redacted_attestation'
       ])
       OR p_payload->'schema_version' <> '1'::jsonb
       OR NOT geo_workflow_c_json_is_sha256(p_payload->'task_key')
       OR NOT geo_workflow_c_json_is_positive_integer(p_payload->'expected_task_version')
       OR (p_payload->>'expected_task_version')::integer <> p_expected_task_version
       OR NOT geo_workflow_c_json_is_sha256(p_payload->'source_content_hash')
       OR btrim(coalesce(p_payload->>'content_type', '')) = ''
       OR length(p_payload->>'content_type') > 200
       OR btrim(coalesce(p_payload->>'governance_policy_option_key', '')) = ''
       OR length(p_payload->>'governance_policy_option_key') > 200
       OR jsonb_typeof(p_payload->'pre_redacted_attestation') <> 'boolean'
       OR p_payload->>'evidence_kind' NOT IN ('screenshot', 'html_export', 'transcript_export')
       OR p_payload->>'device' NOT IN ('desktop', 'mobile', 'tablet')
       OR btrim(coalesce(p_payload->>'locale', '')) = ''
       OR length(p_payload->>'locale') > 100
       OR NOT geo_workflow_c_json_is_rfc3339(p_payload->'captured_at') THEN
        RAISE EXCEPTION 'Manual Sampling evidence command is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF (p_payload->>'captured_at')::timestamptz > p_submitted_at THEN
        RAISE EXCEPTION 'Manual Sampling evidence cannot be submitted before capture'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-manual-evidence:' || p_project_id::text || ':' || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.manual_import.submit'
       AND aggregate_id = p_import_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_import_id THEN
            RAISE EXCEPTION 'Manual Sampling evidence idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO stored_import FROM workflow_c_sampling_manual_imports
         WHERE project_id = p_project_id AND id = p_import_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Manual Sampling evidence replay is missing its durable record'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT stored_import.id, stored_import.aggregate_version, true;
        RETURN;
    END IF;

    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND id = p_task_id FOR UPDATE;
    SELECT * INTO suite_row FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id AND id = run_row.suite_id FOR SHARE;
    SELECT * INTO policy FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = run_row.admission_policy_id FOR SHARE;
    SELECT * INTO artifact FROM workflow_c_manual_artifacts
     WHERE project_id = p_project_id AND artifact_id = p_artifact_manifest_id FOR UPDATE;
    IF run_row.id IS NULL OR task_row.id IS NULL OR suite_row.id IS NULL OR policy.id IS NULL
       OR artifact.artifact_id IS NULL
       OR task_row.run_id <> p_run_id OR task_row.suite_id <> run_row.suite_id
       OR task_row.version <> p_expected_task_version OR task_row.status <> 'planned'
       OR run_row.status NOT IN ('planned', 'running')
       OR suite_row.suite_hash <> run_row.suite_hash
       OR suite_row.capture_method <> 'manual_ui'
       OR task_row.capture_method <> 'manual_ui'
       OR task_row.source_stratum_hash <> suite_row.source_stratum_hash
       OR policy.id <> suite_row.admission_policy_id
       OR policy.definition_hash <> suite_row.admission_policy_hash
       OR policy.status <> 'approved'
       OR policy.effective_authorization_state <> 'approved'
       OR policy.policy_version <> run_row.payload->>'admission_policy_version'
       OR policy.authorization_reference <> run_row.payload->>'authorization_reference'
       OR p_submitted_at < run_row.admitted_not_before
       OR p_submitted_at >= run_row.authorization_valid_until
       OR p_submitted_at >= policy.valid_until
       OR artifact.status <> 'staged' OR artifact.expires_at <= p_submitted_at
       OR artifact.run_id <> p_run_id OR artifact.task_id <> p_task_id
       OR artifact.capture_session_id <> p_capture_session_id
       OR artifact.manifest_hash <> p_artifact_manifest_hash
       OR artifact.redacted_content_hash <> p_artifact_content_hash
       OR artifact.source_content_hash <> p_payload->>'source_content_hash'
       OR artifact.source_content_type <> p_payload->>'content_type'
       OR artifact.governance_policy_hash <> p_governance_policy_hash
       OR artifact.evidence_kind <> p_payload->>'evidence_kind'
       OR task_row.task_key <> p_payload->>'task_key'
       OR EXISTS (
           SELECT 1 FROM workflow_c_sampling_manual_imports AS prior
            WHERE prior.project_id = p_project_id AND prior.task_id = p_task_id
              AND prior.status IN ('submitted', 'approved', 'committed')
       ) THEN
        RAISE EXCEPTION 'Manual Sampling evidence Run, Task, authorization, or artifact is stale'
            USING ERRCODE = '40001';
    END IF;

    PERFORM geo_activate_workflow_c_manual_artifact(p_project_id, p_artifact_manifest_id);
    INSERT INTO workflow_c_sampling_manual_imports(
        id, project_id, run_id, task_id, attempt_id, artifact_manifest_id,
        artifact_manifest_hash, artifact_content_hash, governance_policy_hash,
        capture_session_id, status, submitted_by, aggregate_version, payload,
        submitted_at, review_reason
    ) VALUES (
        p_import_id, p_project_id, p_run_id, p_task_id, p_attempt_id, p_artifact_manifest_id,
        p_artifact_manifest_hash, p_artifact_content_hash, p_governance_policy_hash,
        p_capture_session_id, 'submitted', btrim(p_submitted_by), 1, p_payload,
        p_submitted_at, NULL
    );
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.manual_import.submit', p_import_id,
        p_idempotency_key_hash, p_input_hash, 'manual_sampling_import', p_import_id,
        1, jsonb_build_object('manual_import_id', p_import_id), p_submitted_at
    );
    RETURN QUERY SELECT p_import_id, 1, false;
END;
$$;

CREATE FUNCTION geo_review_workflow_c_manual_sampling_evidence(
    p_project_id uuid,
    p_import_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_expected_version integer,
    p_reviewed_by text,
    p_review_reason text,
    p_approved boolean,
    p_reviewed_at timestamptz,
    p_spec_hash text,
    p_spec_payload jsonb,
    p_job_idempotency_key text
) RETURNS TABLE (
    import_id uuid,
    aggregate_version integer,
    durable_job_id uuid,
    task_version integer,
    run_version integer,
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE import_row workflow_c_sampling_manual_imports%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE suite_row workflow_c_sampling_suites%ROWTYPE;
DECLARE policy workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE usage_row workflow_c_sampling_admission_usage%ROWTYPE;
DECLARE durable_record record;
DECLARE usage_start timestamptz;
DECLARE usage_exists boolean;
DECLARE replay_job_id uuid;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Manual Sampling review is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_import_id IS NULL OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_expected_version < 1
       OR btrim(coalesce(p_reviewed_by, '')) = ''
       OR btrim(coalesce(p_review_reason, '')) = '' OR p_reviewed_at IS NULL
       OR p_approved IS NULL THEN
        RAISE EXCEPTION 'Manual Sampling review command is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_approved AND (
        p_spec_hash !~ '^[0-9a-f]{64}$'
        OR jsonb_typeof(p_spec_payload) <> 'object'
        OR btrim(coalesce(p_job_idempotency_key, '')) = ''
        OR length(p_job_idempotency_key) > 500
        OR NOT geo_workflow_c_sampling_job_spec_is_valid('sampling.manual_import', p_spec_payload)
    ) THEN
        RAISE EXCEPTION 'Approved Manual Sampling review lacks a valid frozen Job spec'
            USING ERRCODE = '22023';
    END IF;
    IF NOT p_approved AND (
        p_spec_hash IS NOT NULL OR p_spec_payload IS NOT NULL OR p_job_idempotency_key IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Rejected Manual Sampling review cannot enqueue a Job'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-manual-review:' || p_project_id::text || ':' || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.manual_import.review'
       AND aggregate_id = p_import_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_import_id THEN
            RAISE EXCEPTION 'Manual Sampling review idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO import_row FROM workflow_c_sampling_manual_imports
         WHERE project_id = p_project_id AND id = p_import_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Manual Sampling review replay is missing its durable record'
                USING ERRCODE = '40001';
        END IF;
        SELECT attempt.durable_job_id INTO replay_job_id
          FROM workflow_c_sampling_attempts AS attempt
         WHERE attempt.project_id = p_project_id AND attempt.id = import_row.attempt_id;
        RETURN QUERY SELECT import_row.id, import_row.aggregate_version, replay_job_id,
            (SELECT version FROM workflow_c_sampling_tasks
              WHERE project_id = p_project_id AND id = import_row.task_id),
            (SELECT version FROM workflow_c_sampling_runs
              WHERE project_id = p_project_id AND id = import_row.run_id),
            true;
        RETURN;
    END IF;

    SELECT * INTO import_row FROM workflow_c_sampling_manual_imports
     WHERE project_id = p_project_id AND id = p_import_id FOR UPDATE;
    IF import_row.id IS NULL OR import_row.status <> 'submitted'
       OR import_row.aggregate_version <> p_expected_version
       OR import_row.submitted_by = btrim(p_reviewed_by)
       OR p_reviewed_at < import_row.submitted_at THEN
        RAISE EXCEPTION 'Manual Sampling review is stale or violates maker-checker separation'
            USING ERRCODE = '40001';
    END IF;

    IF NOT p_approved THEN
        UPDATE workflow_c_sampling_manual_imports AS manual_import
           SET status = 'rejected', reviewed_by = btrim(p_reviewed_by),
               reviewed_at = p_reviewed_at, review_reason = btrim(p_review_reason),
               aggregate_version = manual_import.aggregate_version + 1
         WHERE manual_import.project_id = p_project_id AND manual_import.id = p_import_id
           AND manual_import.aggregate_version = p_expected_version;
        INSERT INTO workflow_c_command_ledger(
            project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
            result_type, result_id, result_version, result_payload, created_at
        ) VALUES (
            p_project_id, 'sampling.manual_import.review', p_import_id,
            p_idempotency_key_hash, p_input_hash, 'manual_sampling_import', p_import_id,
            p_expected_version + 1,
            jsonb_build_object('manual_import_id', p_import_id, 'approved', false), p_reviewed_at
        );
        RETURN QUERY SELECT p_import_id, p_expected_version + 1, NULL::uuid,
            (SELECT version FROM workflow_c_sampling_tasks
              WHERE project_id = p_project_id AND id = import_row.task_id),
            (SELECT version FROM workflow_c_sampling_runs
              WHERE project_id = p_project_id AND id = import_row.run_id),
            false;
        RETURN;
    END IF;

    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = import_row.run_id FOR UPDATE;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND id = import_row.task_id FOR UPDATE;
    SELECT * INTO suite_row FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id AND id = run_row.suite_id FOR SHARE;
    SELECT * INTO policy FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = run_row.admission_policy_id FOR UPDATE;
    IF run_row.id IS NULL OR task_row.id IS NULL OR suite_row.id IS NULL OR policy.id IS NULL
       OR task_row.run_id <> run_row.id OR task_row.suite_id <> run_row.suite_id
       OR task_row.status <> 'planned'
       OR task_row.version <> (p_spec_payload->>'task_version')::integer - 1
       OR run_row.status NOT IN ('planned', 'running')
       OR run_row.consumed_task_count + run_row.released_task_count >= run_row.reserved_task_count
       OR suite_row.suite_hash <> run_row.suite_hash
       OR suite_row.capture_method <> 'manual_ui' OR task_row.capture_method <> 'manual_ui'
       OR task_row.source_stratum_hash <> suite_row.source_stratum_hash
       OR policy.id <> suite_row.admission_policy_id
       OR policy.definition_hash <> suite_row.admission_policy_hash
       OR policy.status <> 'approved' OR policy.effective_authorization_state <> 'approved'
       OR policy.policy_version <> run_row.payload->>'admission_policy_version'
       OR policy.authorization_reference <> run_row.payload->>'authorization_reference'
       OR p_reviewed_at < run_row.admitted_not_before
       OR p_reviewed_at >= run_row.authorization_valid_until
       OR p_reviewed_at >= policy.valid_until
       OR EXISTS (
           SELECT 1 FROM workflow_c_sampling_attempts
            WHERE project_id = p_project_id AND id = import_row.attempt_id
       )
       OR p_job_idempotency_key <> 'sampling.manual:' || p_project_id::text || ':' || import_row.attempt_id::text
       OR p_spec_payload->>'manual_import_id' <> import_row.id::text
       OR p_spec_payload->>'run_id' <> import_row.run_id::text
       OR p_spec_payload->>'task_id' <> import_row.task_id::text
       OR p_spec_payload->>'attempt_id' <> import_row.attempt_id::text
       OR p_spec_payload->>'artifact_manifest_id' <> import_row.artifact_manifest_id::text
       OR p_spec_payload->>'artifact_manifest_hash' <> import_row.artifact_manifest_hash
       OR p_spec_payload->>'artifact_content_hash' <> import_row.artifact_content_hash
       OR p_spec_payload->>'governance_policy_hash' <> import_row.governance_policy_hash
       OR p_spec_payload->>'capture_session_id' <> import_row.capture_session_id::text
       OR p_spec_payload->>'task_version' <> (task_row.version + 1)::text
       OR p_spec_payload->>'attempt_version' <> '1' THEN
        RAISE EXCEPTION 'Approved Manual Sampling review has stale authorization or frozen lineage'
            USING ERRCODE = '40001';
    END IF;

    usage_start := date_trunc('day', p_reviewed_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    SELECT * INTO usage_row FROM workflow_c_sampling_admission_usage
     WHERE project_id = p_project_id AND policy_id = policy.id
       AND window_start = usage_start FOR UPDATE;
    usage_exists := FOUND;
    IF usage_exists AND usage_row.consumed_count + 1 > policy.daily_task_limit THEN
        RAISE EXCEPTION 'Sampling policy daily task limit is exhausted'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO durable_record FROM geo_enqueue_workflow_c_job_spec(
        p_project_id, 'sampling.manual_import', p_spec_hash, p_spec_payload,
        p_job_idempotency_key, 3
    );
    INSERT INTO workflow_c_sampling_attempts(
        id, project_id, run_id, task_id, task_key, durable_job_id, ordinal,
        status, authorization_checked_at, version, payload, created_at, updated_at
    ) VALUES (
        import_row.attempt_id, p_project_id, import_row.run_id, import_row.task_id,
        task_row.task_key, durable_record.job_id, 1, 'queued', p_reviewed_at,
        1, jsonb_build_object('schema_version', 1), p_reviewed_at, p_reviewed_at
    );
    UPDATE workflow_c_sampling_tasks
       SET status = 'queued', version = version + 1, updated_at = p_reviewed_at
     WHERE project_id = p_project_id AND id = task_row.id
       AND version = task_row.version;
    UPDATE workflow_c_sampling_runs
       SET status = 'running', consumed_task_count = consumed_task_count + 1,
           version = version + 1
     WHERE project_id = p_project_id AND id = run_row.id;
    IF usage_exists THEN
        UPDATE workflow_c_sampling_admission_usage
           SET consumed_count = consumed_count + 1, version = version + 1,
               updated_at = GREATEST(updated_at, p_reviewed_at)
         WHERE project_id = p_project_id AND policy_id = policy.id
           AND window_start = usage_start;
    ELSE
        INSERT INTO workflow_c_sampling_admission_usage(
            project_id, policy_id, window_start, reserved_count, consumed_count,
            released_count, version, updated_at
        ) VALUES (
            p_project_id, policy.id, usage_start, 1, 1, 0, 1, p_reviewed_at
        );
    END IF;
    UPDATE workflow_c_sampling_manual_imports AS manual_import
       SET status = 'approved', reviewed_by = btrim(p_reviewed_by),
           reviewed_at = p_reviewed_at, review_reason = btrim(p_review_reason),
           aggregate_version = manual_import.aggregate_version + 1
     WHERE manual_import.project_id = p_project_id AND manual_import.id = p_import_id
       AND manual_import.aggregate_version = p_expected_version;
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.manual_import.review', p_import_id,
        p_idempotency_key_hash, p_input_hash, 'manual_sampling_import', p_import_id,
        p_expected_version + 1,
        jsonb_build_object(
            'manual_import_id', p_import_id, 'approved', true,
            'attempt_id', import_row.attempt_id, 'durable_job_id', durable_record.job_id
        ), p_reviewed_at
    );
    RETURN QUERY SELECT p_import_id, p_expected_version + 1, durable_record.job_id,
        task_row.version + 1, run_row.version + 1, false;
END;
$$;

REVOKE ALL ON FUNCTION geo_submit_workflow_c_manual_sampling_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_submit_workflow_c_manual_sampling_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz
) TO geo_app;

REVOKE ALL ON FUNCTION geo_review_workflow_c_manual_sampling_evidence(
    uuid, uuid, text, text, integer, text, text, boolean, timestamptz, text, jsonb, text
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_review_workflow_c_manual_sampling_evidence(
    uuid, uuid, text, text, integer, text, text, boolean, timestamptz, text, jsonb, text
) TO geo_app;

COMMENT ON FUNCTION geo_submit_workflow_c_manual_sampling_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz
) IS 'Atomically validates a staged governed artifact, activates it, and creates a pending manual Sampling import.';

COMMENT ON FUNCTION geo_review_workflow_c_manual_sampling_evidence(
    uuid, uuid, text, text, integer, text, text, boolean, timestamptz, text, jsonb, text
) IS 'Maker-checker review that atomically creates the approved manual Sampling Job, Spec, Outbox, and Attempt.';
