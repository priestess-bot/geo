-- Manual alert dispositions are stateful commands.  Keep the alert row,
-- append-only disposition history, notification rows, durable notify Jobs and
-- broker wakeups in one project-scoped transaction.

CREATE FUNCTION geo_transition_workflow_c_alert(
    p_project_id uuid,
    p_alert_id uuid,
    p_expected_version integer,
    p_command_key text,
    p_command_hash text,
    p_command_payload jsonb,
    p_operation text,
    p_actor_id text,
    p_reason text,
    p_occurred_at timestamptz,
    p_suppressed_until timestamptz,
    p_notification_payload jsonb
) RETURNS TABLE (alert_id uuid, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE target workflow_c_alerts%ROWTYPE;
DECLARE prior workflow_c_alert_dispositions%ROWTYPE;
DECLARE item jsonb;
DECLARE expected_kind text;
DECLARE expected_status text;
DECLARE expected_event text;
DECLARE expected_hash text;
DECLARE notification workflow_c_alert_notifications%ROWTYPE;
DECLARE notify_job durable_jobs%ROWTYPE;
DECLARE summary jsonb;
DECLARE target_rule jsonb;
DECLARE next_version integer;
BEGIN
    IF p_project_id IS NULL OR p_alert_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Workflow C alert disposition is outside caller Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_expected_version < 1
       OR btrim(coalesce(p_command_key, '')) !~ '^[a-z][a-z0-9_.:-]{0,199}$'
       OR p_command_hash !~ '^[0-9a-f]{64}$'
       OR btrim(coalesce(p_actor_id, '')) = '' OR length(p_actor_id) > 200
       OR btrim(coalesce(p_reason, '')) = '' OR length(p_reason) > 1000
       OR p_occurred_at IS NULL
       OR p_operation NOT IN ('acknowledge', 'suppress', 'unsuppress', 'resolve')
       OR jsonb_typeof(p_command_payload) <> 'object'
       OR NOT geo_workflow_c_json_has_exact_keys(p_command_payload, ARRAY[
           'actor_id', 'disposition', 'reason', 'suppressed_until'
       ])
       OR p_command_payload->>'actor_id' <> btrim(p_actor_id)
       OR p_command_payload->>'reason' <> btrim(p_reason)
       OR jsonb_typeof(p_notification_payload) <> 'array' THEN
        RAISE EXCEPTION 'Workflow C alert disposition input is invalid'
            USING ERRCODE = '22023';
    END IF;

    expected_kind := CASE p_operation
        WHEN 'acknowledge' THEN 'acknowledged'
        WHEN 'suppress' THEN 'suppressed'
        WHEN 'unsuppress' THEN 'unsuppressed'
        ELSE 'resolved'
    END;
    expected_event := expected_kind;
    IF p_command_payload->>'disposition' <> expected_kind
       OR (
           p_operation = 'suppress' AND (
               p_suppressed_until IS NULL OR p_suppressed_until <= p_occurred_at
               OR jsonb_typeof(p_command_payload->'suppressed_until') <> 'string'
               OR (p_command_payload->>'suppressed_until')::timestamptz
                    <> p_suppressed_until
           )
       )
       OR (
           p_operation <> 'suppress' AND (
               p_suppressed_until IS NOT NULL
               OR p_command_payload->'suppressed_until' <> 'null'::jsonb
           )
       ) THEN
        RAISE EXCEPTION 'Workflow C alert disposition payload is inconsistent'
            USING ERRCODE = '22023';
    END IF;
    expected_hash := encode(digest(convert_to(
        geo_jsonb_canonical_text(p_command_payload), 'UTF8'
    ), 'sha256'), 'hex');
    IF expected_hash <> p_command_hash THEN
        RAISE EXCEPTION 'Workflow C alert disposition hash is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO target
    FROM workflow_c_alerts
    WHERE project_id = p_project_id AND id = p_alert_id
    FOR UPDATE;
    IF target.id IS NULL THEN
        RAISE EXCEPTION 'Workflow C alert does not exist in this Project'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO prior
    FROM workflow_c_alert_dispositions AS disposition
    WHERE disposition.project_id = p_project_id AND disposition.alert_id = p_alert_id
      AND disposition.command_key = p_command_key
    FOR SHARE;
    IF prior.id IS NOT NULL THEN
        IF prior.command_hash <> p_command_hash THEN
            RAISE EXCEPTION 'Workflow C alert disposition command key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT target.id, true;
        RETURN;
    END IF;
    IF target.version <> p_expected_version OR p_occurred_at < target.updated_at THEN
        RAISE EXCEPTION 'Workflow C alert disposition version was fenced'
            USING ERRCODE = '40001';
    END IF;
    expected_status := CASE p_operation
        WHEN 'acknowledge' THEN 'acknowledged'
        WHEN 'suppress' THEN 'suppressed'
        WHEN 'unsuppress' THEN 'open'
        ELSE 'resolved'
    END;
    IF (p_operation = 'acknowledge' AND target.status <> 'open')
       OR (p_operation = 'suppress' AND target.status NOT IN ('open', 'acknowledged'))
       OR (p_operation = 'unsuppress' AND target.status <> 'suppressed')
       OR (p_operation = 'resolve' AND target.status NOT IN ('open', 'acknowledged', 'suppressed')) THEN
        RAISE EXCEPTION 'Workflow C alert disposition state is invalid'
            USING ERRCODE = '23514';
    END IF;
    next_version := target.version + 1;
    IF jsonb_array_length(p_notification_payload) <> 3
       OR (SELECT count(DISTINCT value->>'channel')
           FROM jsonb_array_elements(p_notification_payload) AS value) <> 3 THEN
        RAISE EXCEPTION 'Workflow C alert disposition requires one notification per channel'
            USING ERRCODE = '22023';
    END IF;
    target_rule := target.payload->'rule';
    IF jsonb_typeof(target_rule) <> 'object' THEN
        RAISE EXCEPTION 'Workflow C alert payload is corrupt'
            USING ERRCODE = '23514';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_notification_payload)
    LOOP
        IF NOT geo_workflow_c_json_has_exact_keys(item, ARRAY[
            'id', 'alert_id', 'alert_version', 'channel', 'topic',
            'idempotency_key', 'payload_hash', 'payload', 'safe_summary',
            'created_at', 'notify_job_id', 'notify_spec_hash', 'notify_spec_payload'
        ])
           OR NOT geo_workflow_c_json_is_uuid(item->'id')
           OR item->>'alert_id' <> p_alert_id::text
           OR (item->>'alert_version')::integer <> next_version
           OR item->>'channel' NOT IN ('admin_inbox', 'local_smtp', 'internal_webhook')
           OR item->>'topic' <> ('alerts.notify.' || (item->>'channel'))
           OR item->>'idempotency_key' <> (
                'alert-notification:' || p_alert_id::text || ':' || 'v'
                || next_version::text || ':' || expected_event || ':'
                || (item->>'channel')
           )
           OR NOT geo_workflow_c_json_is_sha256(item->'payload_hash')
           OR NOT geo_workflow_c_json_has_exact_keys(item->'payload', ARRAY['summary'])
           OR jsonb_typeof(item->'payload'->'summary') <> 'object'
           OR NOT geo_workflow_c_json_has_exact_keys(item->'payload'->'summary', ARRAY[
                'alert_id', 'project_id', 'rule_key', 'rule_version', 'rule_kind',
                'severity', 'status', 'event_type', 'occurred_at', 'detail_link'
           ])
           OR NOT geo_workflow_c_json_is_sha256(item->'payload_hash')
           OR encode(digest(convert_to(
                geo_jsonb_canonical_text(item->'payload'->'summary'), 'UTF8'
           ), 'sha256'), 'hex') <> item->>'payload_hash'
           OR btrim(coalesce(item->>'safe_summary', '')) = ''
           OR length(item->>'safe_summary') > 1000
           OR NOT geo_workflow_c_json_is_rfc3339(item->'created_at')
           OR (item->>'created_at')::timestamptz <> p_occurred_at
           OR NOT geo_workflow_c_json_is_uuid(item->'notify_job_id')
           OR NOT geo_workflow_c_json_is_sha256(item->'notify_spec_hash')
           OR NOT geo_workflow_c_json_has_exact_keys(item->'notify_spec_payload', ARRAY[
                'schema_version', 'kind', 'notification_id'
           ])
           OR item->'notify_spec_payload'->'schema_version' <> '1'::jsonb
           OR item->'notify_spec_payload'->>'kind' <> 'workflow_c.alert.notify'
           OR item->'notify_spec_payload'->>'notification_id' <> item->>'id'
           OR encode(digest(convert_to(
                geo_jsonb_canonical_text(item->'notify_spec_payload'), 'UTF8'
           ), 'sha256'), 'hex') <> item->>'notify_spec_hash'
           OR NOT geo_workflow_c_job_spec_payload_is_safe(item) THEN
            RAISE EXCEPTION 'Workflow C alert disposition notification payload is invalid'
                USING ERRCODE = '22023';
        END IF;
        summary := item->'payload'->'summary';
        IF summary->>'alert_id' <> p_alert_id::text
           OR summary->>'project_id' <> p_project_id::text
           OR summary->>'rule_key' <> target_rule->>'rule_key'
           OR (summary->>'rule_version')::integer <> (target_rule->>'version')::integer
           OR summary->>'rule_kind' <> target_rule->>'kind'
           OR summary->>'severity' <> target.severity
           OR summary->>'status' <> expected_status
           OR summary->>'event_type' <> expected_event
           OR (summary->>'occurred_at')::timestamptz <> p_occurred_at
           OR summary->>'detail_link' <> (
                '/admin/projects/' || p_project_id::text || '/alerts/' || p_alert_id::text
           ) THEN
            RAISE EXCEPTION 'Workflow C alert disposition notification summary is invalid'
                USING ERRCODE = '22023';
        END IF;
        SELECT * INTO notification
        FROM workflow_c_alert_notifications
        WHERE project_id = p_project_id AND (
            id = (item->>'id')::uuid OR idempotency_key = item->>'idempotency_key'
        ) FOR SHARE;
        IF notification.id IS NOT NULL THEN
            RAISE EXCEPTION 'Workflow C alert disposition notification already exists'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO notify_job
        FROM durable_jobs
        WHERE project_id = p_project_id AND (
            id = (item->>'notify_job_id')::uuid OR (
                kind = 'workflow_c.alert.notify'
                AND idempotency_key = (
                    'workflow-c-alert-notify:' || (item->>'idempotency_key')
                )
                AND replay_nonce = 0
            )
        ) FOR SHARE;
        IF notify_job.id IS NOT NULL THEN
            RAISE EXCEPTION 'Workflow C alert disposition notify Job already exists'
                USING ERRCODE = '23505';
        END IF;
    END LOOP;

    UPDATE workflow_c_alerts
    SET status = expected_status, version = next_version, updated_at = p_occurred_at,
        resolved_at = CASE WHEN expected_status = 'resolved' THEN p_occurred_at ELSE NULL END
    WHERE project_id = p_project_id AND id = p_alert_id;
    INSERT INTO workflow_c_alert_dispositions(
        id, project_id, alert_id, kind, command_key, from_status, to_status,
        resulting_version, actor_id, reason, suppressed_until, command_hash, occurred_at
    ) VALUES (
        gen_random_uuid(), p_project_id, p_alert_id, expected_kind, p_command_key,
        target.status, expected_status, next_version, btrim(p_actor_id), btrim(p_reason),
        p_suppressed_until, p_command_hash, p_occurred_at
    );
    FOR item IN SELECT value FROM jsonb_array_elements(p_notification_payload)
    LOOP
        INSERT INTO workflow_c_alert_notifications(
            id, project_id, alert_id, alert_version, channel, topic, idempotency_key,
            status, payload_hash, payload, safe_summary, attempt_count,
            next_attempt_at, created_at
        ) VALUES (
            (item->>'id')::uuid, p_project_id, p_alert_id, next_version,
            item->>'channel', item->>'topic', item->>'idempotency_key', 'pending',
            item->>'payload_hash', item->'payload', item->>'safe_summary', 0,
            p_occurred_at, p_occurred_at
        );
        INSERT INTO durable_jobs(
            id, project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, replay_nonce, created_at, updated_at
        ) VALUES (
            (item->>'notify_job_id')::uuid, p_project_id, 'workflow_c.alert.notify',
            'queued', 5, item->>'notify_spec_hash',
            'workflow-c-alert-notify:' || (item->>'idempotency_key'), 3,
            p_occurred_at, 0, p_occurred_at, p_occurred_at
        );
        INSERT INTO workflow_c_job_specs(
            project_id, job_id, kind, spec_hash, spec_payload, created_at
        ) VALUES (
            p_project_id, (item->>'notify_job_id')::uuid, 'workflow_c.alert.notify',
            item->>'notify_spec_hash', item->'notify_spec_payload', p_occurred_at
        );
        INSERT INTO broker_outbox(
            id, project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            gen_random_uuid(), p_project_id, (item->>'notify_job_id')::uuid,
            'workflow_c.alert.notify',
            jsonb_build_object('job_id', item->>'notify_job_id',
                               'project_id', p_project_id::text),
            'wake:workflow_c.alert.notify:' || (item->>'notify_job_id'), p_occurred_at
        );
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
        ) VALUES (
            p_project_id, (item->>'notify_job_id')::uuid, 'job_enqueued',
            'workflow-c-alert-disposition', 0,
            jsonb_build_object('alert_id', p_alert_id::text,
                               'alert_version', next_version), p_occurred_at
        );
    END LOOP;
    RETURN QUERY SELECT p_alert_id, false;
END;
$$;

REVOKE INSERT, UPDATE, DELETE ON
    workflow_c_alerts, workflow_c_alert_dispositions, workflow_c_alert_notifications
FROM geo_app;
REVOKE ALL ON FUNCTION geo_transition_workflow_c_alert(
    uuid, uuid, integer, text, text, jsonb, text, text, text, timestamptz,
    timestamptz, jsonb
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_transition_workflow_c_alert(
    uuid, uuid, integer, text, text, jsonb, text, text, text, timestamptz,
    timestamptz, jsonb
) TO geo_app;
