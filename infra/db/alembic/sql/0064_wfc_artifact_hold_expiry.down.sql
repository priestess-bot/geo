-- The predecessor schema cannot model bounded or extended holds. Preserve the
-- removed fields in immutable audit text before mapping them to its closest
-- legacy representation, so a compatibility downgrade does not silently lose
-- the original action, policy version, or expiry timestamp.
UPDATE workflow_c_artifact_hold_requests
SET request_reason = request_reason
        || E'\n[legacy_0064_bounded_hold policy=' || hold_policy_version::text
        || ' action=' || action
        || ' hold_until=' || coalesce(hold_until::text, 'none') || ']',
    decision_reason = CASE
        WHEN decision_reason IS NULL THEN NULL
        ELSE decision_reason
            || E'\n[legacy_0064_bounded_hold policy=' || hold_policy_version::text
            || ' action=' || action
            || ' hold_until=' || coalesce(hold_until::text, 'none') || ']'
    END,
    action = CASE WHEN action = 'extend' THEN 'apply' ELSE action END
WHERE hold_policy_version = 2;

UPDATE workflow_c_artifact_lifecycle_events
SET event_type = 'hold_applied',
    reason = reason || E'\n[legacy_0064_hold_extended]'
WHERE event_type = 'hold_extended';

CREATE OR REPLACE FUNCTION geo_seed_workflow_c_artifact_maintenance(
    p_now timestamptz,
    p_staged_grace_seconds integer,
    p_limit integer
) RETURNS TABLE (project_id uuid, job_id uuid, outbox_id uuid, inserted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate record;
BEGIN
    IF p_now IS NULL OR p_staged_grace_seconds NOT BETWEEN 60 AND 86400
       OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'Workflow C artifact maintenance seed input is invalid'
            USING ERRCODE = '22023';
    END IF;
    FOR candidate IN
        SELECT due.project_id
        FROM (
            SELECT artifact.project_id, min(artifact.created_at) AS due_at
            FROM workflow_c_manual_artifacts AS artifact
            WHERE (artifact.status = 'staged'
                   AND artifact.created_at <= p_now
                       - make_interval(secs => p_staged_grace_seconds))
               OR (artifact.status = 'active' AND NOT artifact.legal_hold
                   AND artifact.expires_at <= p_now)
            GROUP BY artifact.project_id
            UNION
            SELECT queued.project_id, min(queued.next_attempt_at) AS due_at
            FROM workflow_c_artifact_deletion_queue AS queued
            WHERE (queued.status IN ('pending', 'retry_wait')
                   AND queued.next_attempt_at <= p_now)
               OR (queued.status = 'running' AND queued.lease_expires_at <= p_now)
            GROUP BY queued.project_id
        ) AS due
        ORDER BY due.due_at, due.project_id
        LIMIT p_limit
    LOOP
        PERFORM set_config('geo.project_id', candidate.project_id::text, true);
        PERFORM set_config(
            'geo.project_ids', jsonb_build_array(candidate.project_id::text)::text, true
        );
        PERFORM * FROM geo_enqueue_workflow_c_artifact_maintenance(
            candidate.project_id, p_now, p_staged_grace_seconds
        );
        RETURN QUERY
        SELECT candidate.project_id, scheduled.job_id, scheduled.outbox_id, scheduled.inserted
        FROM geo_schedule_workflow_c_artifact_maintenance(candidate.project_id, p_now)
            AS scheduled;
    END LOOP;
END;
$$;

DROP FUNCTION geo_expire_workflow_c_artifact_holds(timestamptz, integer);
DROP FUNCTION geo_request_workflow_c_artifact_hold(
    uuid, uuid, uuid, text, text, text, timestamptz, timestamptz
);

CREATE FUNCTION geo_request_workflow_c_artifact_hold(
    p_project_id uuid,
    p_artifact_id uuid,
    p_request_id uuid,
    p_action text,
    p_actor_id text,
    p_reason text,
    p_requested_at timestamptz
) RETURNS SETOF workflow_c_artifact_hold_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE existing workflow_c_artifact_hold_requests%ROWTYPE;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR p_action NOT IN ('apply', 'release')
       OR btrim(coalesce(p_actor_id, '')) = ''
       OR btrim(coalesce(p_reason, '')) = '' OR p_requested_at IS NULL THEN
        RAISE EXCEPTION 'invalid Workflow C artifact hold request'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing
    FROM workflow_c_artifact_hold_requests
    WHERE project_id = p_project_id AND id = p_request_id;
    IF FOUND THEN
        IF (existing.artifact_id, existing.action, existing.requested_by,
            existing.request_reason, existing.requested_at)
           IS DISTINCT FROM
           (p_artifact_id, p_action, p_actor_id, p_reason, p_requested_at) THEN
            RAISE EXCEPTION 'Workflow C artifact hold request idempotency changed'
                USING ERRCODE = '40001';
        END IF;
        RETURN NEXT existing;
        RETURN;
    END IF;
    SELECT * INTO STRICT artifact
    FROM workflow_c_manual_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
    FOR UPDATE;
    IF artifact.status <> 'active' OR artifact.expires_at <= p_requested_at
       OR (p_action = 'apply' AND artifact.legal_hold)
       OR (p_action = 'release' AND NOT artifact.legal_hold) THEN
        RAISE EXCEPTION 'Workflow C artifact hold target state is invalid'
            USING ERRCODE = '23514';
    END IF;
    INSERT INTO workflow_c_artifact_hold_requests(
        id, project_id, artifact_id, action, status, requested_by,
        requested_at, request_reason, expected_artifact_status, aggregate_version
    ) VALUES (
        p_request_id, p_project_id, p_artifact_id, p_action, 'pending',
        p_actor_id, p_requested_at, p_reason, 'active', 1
    ) RETURNING * INTO existing;
    PERFORM geo_append_workflow_c_artifact_event(
        p_project_id, p_artifact_id, 'hold_requested',
        p_actor_id, p_reason, p_requested_at
    );
    RETURN NEXT existing;
END;
$$;

CREATE OR REPLACE FUNCTION geo_decide_workflow_c_artifact_hold(
    p_project_id uuid,
    p_request_id uuid,
    p_expected_version integer,
    p_actor_id text,
    p_approved boolean,
    p_reason text,
    p_decided_at timestamptz
) RETURNS SETOF workflow_c_artifact_hold_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE request_record workflow_c_artifact_hold_requests%ROWTYPE;
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE event_kind text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR btrim(coalesce(p_actor_id, '')) = ''
       OR btrim(coalesce(p_reason, '')) = '' OR p_decided_at IS NULL THEN
        RAISE EXCEPTION 'invalid Workflow C artifact hold decision'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT request_record
    FROM workflow_c_artifact_hold_requests
    WHERE project_id = p_project_id AND id = p_request_id
    FOR UPDATE;
    IF request_record.status <> 'pending'
       OR request_record.aggregate_version <> p_expected_version
       OR p_expected_version <> 1
       OR request_record.requested_by = p_actor_id
       OR p_decided_at < request_record.requested_at THEN
        RAISE EXCEPTION 'Workflow C artifact hold decision lost maker-checker or version CAS'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO STRICT artifact
    FROM workflow_c_manual_artifacts
    WHERE project_id = p_project_id
      AND artifact_id = request_record.artifact_id
    FOR UPDATE;
    IF artifact.status <> request_record.expected_artifact_status
       OR (request_record.action = 'apply' AND artifact.legal_hold)
       OR (request_record.action = 'release' AND NOT artifact.legal_hold) THEN
        RAISE EXCEPTION 'Workflow C artifact hold target became stale'
            USING ERRCODE = '40001';
    END IF;
    IF p_approved THEN
        UPDATE workflow_c_manual_artifacts
        SET legal_hold = (request_record.action = 'apply')
        WHERE project_id = p_project_id AND artifact_id = request_record.artifact_id;
        event_kind := CASE request_record.action
            WHEN 'apply' THEN 'hold_applied' ELSE 'hold_released' END;
    ELSE
        event_kind := 'hold_rejected';
    END IF;
    UPDATE workflow_c_artifact_hold_requests
    SET status = CASE WHEN p_approved THEN 'approved' ELSE 'rejected' END,
        decided_by = p_actor_id, decided_at = p_decided_at,
        decision_reason = p_reason, aggregate_version = 2
    WHERE project_id = p_project_id AND id = p_request_id
    RETURNING * INTO request_record;
    PERFORM geo_append_workflow_c_artifact_event(
        p_project_id, request_record.artifact_id, event_kind,
        p_actor_id, p_reason, p_decided_at
    );
    RETURN NEXT request_record;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_workflow_c_manual_artifact_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'staged' OR NEW.legal_hold
           OR NOT EXISTS (
                SELECT 1 FROM workflow_c_artifact_deks AS dek
                WHERE dek.key_ref = NEW.key_ref
                  AND dek.project_id = NEW.project_id
                  AND dek.artifact_id = NEW.artifact_id
                  AND dek.status = 'active'
           ) THEN
            RAISE EXCEPTION 'Workflow C manual artifact must begin as a staged encrypted record'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Workflow C manual artifact lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'status', 'legal_hold', 'activated_at', 'object_uri', 'manifest_uri',
        'key_ref', 'tombstoned_at', 'tombstone_reason'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'status', 'legal_hold', 'activated_at', 'object_uri', 'manifest_uri',
        'key_ref', 'tombstoned_at', 'tombstone_reason'
    ];
    IF old_fixed <> new_fixed THEN
        RAISE EXCEPTION 'Workflow C manual artifact immutable lineage changed'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'staged' AND NEW.status = 'active'
       AND NEW.activated_at IS NOT NULL AND NOT NEW.legal_hold THEN
        PERFORM geo_append_workflow_c_artifact_event(
            NEW.project_id, NEW.artifact_id, 'activated',
            'workflow_c.artifact_writer', 'stage_committed', NEW.activated_at
        );
    ELSIF OLD.status IN ('staged', 'active') AND NEW.status = 'delete_pending'
       AND NEW.object_uri = OLD.object_uri AND NEW.manifest_uri = OLD.manifest_uri
       AND NEW.key_ref = OLD.key_ref AND NEW.legal_hold = OLD.legal_hold THEN
        NULL;
    ELSIF OLD.status = 'delete_pending' AND NEW.status = 'crypto_erased'
       AND NEW.object_uri = OLD.object_uri AND NEW.manifest_uri = OLD.manifest_uri
       AND NEW.key_ref = OLD.key_ref AND NEW.legal_hold = OLD.legal_hold THEN
        NULL;
    ELSIF OLD.status = 'crypto_erased' AND NEW.status = 'tombstoned'
       AND NEW.object_uri IS NULL AND NEW.manifest_uri IS NULL
       AND NEW.key_ref IS NULL AND NEW.tombstoned_at IS NOT NULL
       AND NEW.legal_hold = OLD.legal_hold THEN
        NULL;
    ELSIF OLD.status = 'active' AND NEW.status = 'active'
       AND NEW.legal_hold <> OLD.legal_hold THEN
        NULL;
    ELSE
        RAISE EXCEPTION 'Workflow C manual artifact lifecycle transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE workflow_c_artifact_lifecycle_events
DROP CONSTRAINT workflow_c_artifact_lifecycle_events_event_type_check;

ALTER TABLE workflow_c_artifact_lifecycle_events
ADD CONSTRAINT workflow_c_artifact_lifecycle_events_event_type_check
CHECK (event_type IN (
    'staged', 'activated', 'delete_enqueued', 'deletion_claimed',
    'deletion_retry', 'crypto_erased', 'deleted',
    'hold_requested', 'hold_applied', 'hold_released',
    'hold_rejected', 'hold_expired'
));

ALTER TABLE workflow_c_artifact_hold_requests
DROP CONSTRAINT workflow_c_artifact_hold_requests_expiry_check,
DROP COLUMN hold_policy_version,
DROP COLUMN hold_until;

ALTER TABLE workflow_c_artifact_hold_requests
DROP CONSTRAINT workflow_c_artifact_hold_requests_action_check;

ALTER TABLE workflow_c_artifact_hold_requests
ADD CONSTRAINT workflow_c_artifact_hold_requests_action_check
CHECK (action IN ('apply', 'release'));

ALTER TABLE workflow_c_manual_artifacts
DROP CONSTRAINT workflow_c_manual_artifacts_legal_hold_expiry_check,
DROP COLUMN legal_hold_until;

GRANT INSERT ON workflow_c_artifact_hold_requests TO geo_app;
REVOKE ALL ON FUNCTION geo_request_workflow_c_artifact_hold(
    uuid, uuid, uuid, text, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_request_workflow_c_artifact_hold(
    uuid, uuid, uuid, text, text, text, timestamptz
) TO geo_app;
