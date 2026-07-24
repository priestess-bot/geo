-- Legal holds are exceptional retention controls. Every new hold is bounded to
-- 90 days, extensions are independently maker-checker approved, and the
-- maintenance scheduler releases a due hold before normal retention discovery.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM workflow_c_manual_artifacts
        WHERE legal_hold
    ) THEN
        RAISE EXCEPTION
            'active Workflow C legal holds require manual release and reapproval before 0064'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

ALTER TABLE workflow_c_manual_artifacts
ADD COLUMN legal_hold_until timestamptz;

ALTER TABLE workflow_c_manual_artifacts
ADD CONSTRAINT workflow_c_manual_artifacts_legal_hold_expiry_check
CHECK (
    (legal_hold AND legal_hold_until IS NOT NULL)
    OR (NOT legal_hold AND legal_hold_until IS NULL)
);

ALTER TABLE workflow_c_artifact_hold_requests
DROP CONSTRAINT workflow_c_artifact_hold_requests_action_check;

ALTER TABLE workflow_c_artifact_hold_requests
ADD CONSTRAINT workflow_c_artifact_hold_requests_action_check
CHECK (action IN ('apply', 'extend', 'release'));

ALTER TABLE workflow_c_artifact_hold_requests
ADD COLUMN hold_until timestamptz,
ADD COLUMN hold_policy_version smallint;

-- Pending requests issued before the bounded-hold contract cannot safely be
-- approved because they have no duration. Close them with an explicit audit
-- decision rather than silently inventing an expiry.
UPDATE workflow_c_artifact_hold_requests
SET status = 'expired',
    decided_by = 'workflow_c.hold_migration',
    decided_at = clock_timestamp(),
    decision_reason = 'pre_expiry_contract_request_closed',
    aggregate_version = 2
WHERE status = 'pending';

ALTER TABLE workflow_c_artifact_hold_requests
ADD CONSTRAINT workflow_c_artifact_hold_requests_expiry_check
CHECK (
    (hold_policy_version IS NULL AND hold_until IS NULL)
    OR (
        hold_policy_version = 2
        AND (
            (action IN ('apply', 'extend')
                AND hold_until IS NOT NULL
                AND hold_until > requested_at
                AND hold_until <= requested_at + INTERVAL '90 days')
            OR (action = 'release' AND hold_until IS NULL)
        )
    )
);

ALTER TABLE workflow_c_artifact_lifecycle_events
DROP CONSTRAINT workflow_c_artifact_lifecycle_events_event_type_check;

ALTER TABLE workflow_c_artifact_lifecycle_events
ADD CONSTRAINT workflow_c_artifact_lifecycle_events_event_type_check
CHECK (event_type IN (
    'staged', 'activated', 'delete_enqueued', 'deletion_claimed',
    'deletion_retry', 'crypto_erased', 'deleted',
    'hold_requested', 'hold_applied', 'hold_extended', 'hold_released',
    'hold_rejected', 'hold_expired'
));

CREATE OR REPLACE FUNCTION geo_assert_workflow_c_manual_artifact_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'staged' OR NEW.legal_hold
           OR NEW.legal_hold_until IS NOT NULL
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
        'status', 'legal_hold', 'legal_hold_until', 'activated_at', 'object_uri',
        'manifest_uri', 'key_ref', 'tombstoned_at', 'tombstone_reason'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'status', 'legal_hold', 'legal_hold_until', 'activated_at', 'object_uri',
        'manifest_uri', 'key_ref', 'tombstoned_at', 'tombstone_reason'
    ];
    IF old_fixed <> new_fixed THEN
        RAISE EXCEPTION 'Workflow C manual artifact immutable lineage changed'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'staged' AND NEW.status = 'active'
       AND NEW.activated_at IS NOT NULL AND NOT NEW.legal_hold
       AND NEW.legal_hold_until IS NULL THEN
        PERFORM geo_append_workflow_c_artifact_event(
            NEW.project_id, NEW.artifact_id, 'activated',
            'workflow_c.artifact_writer', 'stage_committed', NEW.activated_at
        );
    ELSIF OLD.status IN ('staged', 'active') AND NEW.status = 'delete_pending'
       AND NEW.object_uri = OLD.object_uri AND NEW.manifest_uri = OLD.manifest_uri
       AND NEW.key_ref = OLD.key_ref AND NEW.legal_hold = OLD.legal_hold
       AND NEW.legal_hold_until IS NOT DISTINCT FROM OLD.legal_hold_until THEN
        NULL;
    ELSIF OLD.status = 'delete_pending' AND NEW.status = 'crypto_erased'
       AND NEW.object_uri = OLD.object_uri AND NEW.manifest_uri = OLD.manifest_uri
       AND NEW.key_ref = OLD.key_ref AND NEW.legal_hold = OLD.legal_hold
       AND NEW.legal_hold_until IS NOT DISTINCT FROM OLD.legal_hold_until THEN
        NULL;
    ELSIF OLD.status = 'crypto_erased' AND NEW.status = 'tombstoned'
       AND NEW.object_uri IS NULL AND NEW.manifest_uri IS NULL
       AND NEW.key_ref IS NULL AND NEW.tombstoned_at IS NOT NULL
       AND NEW.legal_hold = OLD.legal_hold
       AND NEW.legal_hold_until IS NOT DISTINCT FROM OLD.legal_hold_until THEN
        NULL;
    ELSIF OLD.status = 'active' AND NEW.status = 'active' AND (
        (NOT OLD.legal_hold AND OLD.legal_hold_until IS NULL
            AND NEW.legal_hold AND NEW.legal_hold_until IS NOT NULL)
        OR (OLD.legal_hold AND OLD.legal_hold_until IS NOT NULL
            AND NEW.legal_hold AND NEW.legal_hold_until IS NOT NULL)
        OR (OLD.legal_hold AND OLD.legal_hold_until IS NOT NULL
            AND NOT NEW.legal_hold AND NEW.legal_hold_until IS NULL)
    ) THEN
        NULL;
    ELSE
        RAISE EXCEPTION 'Workflow C manual artifact lifecycle transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP FUNCTION geo_request_workflow_c_artifact_hold(
    uuid, uuid, uuid, text, text, text, timestamptz
);

CREATE FUNCTION geo_request_workflow_c_artifact_hold(
    p_project_id uuid,
    p_artifact_id uuid,
    p_request_id uuid,
    p_action text,
    p_actor_id text,
    p_reason text,
    p_requested_at timestamptz,
    p_hold_until timestamptz
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
       OR p_action NOT IN ('apply', 'extend', 'release')
       OR btrim(coalesce(p_actor_id, '')) = ''
       OR btrim(coalesce(p_reason, '')) = '' OR p_requested_at IS NULL
       OR (p_action IN ('apply', 'extend') AND (
            p_hold_until IS NULL OR p_hold_until <= p_requested_at
            OR p_hold_until > p_requested_at + INTERVAL '90 days'
       ))
       OR (p_action = 'release' AND p_hold_until IS NOT NULL) THEN
        RAISE EXCEPTION 'invalid Workflow C artifact hold request'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing
    FROM workflow_c_artifact_hold_requests
    WHERE project_id = p_project_id AND id = p_request_id;
    IF FOUND THEN
        IF (existing.artifact_id, existing.action, existing.requested_by,
            existing.request_reason, existing.requested_at, existing.hold_until)
           IS DISTINCT FROM
           (p_artifact_id, p_action, p_actor_id, p_reason, p_requested_at, p_hold_until) THEN
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
    IF artifact.status <> 'active'
       OR (p_action = 'apply' AND artifact.expires_at <= p_requested_at)
       OR (p_action = 'apply' AND artifact.legal_hold)
       OR (p_action = 'extend' AND (
            NOT artifact.legal_hold OR artifact.legal_hold_until IS NULL
            OR p_hold_until <= artifact.legal_hold_until
       ))
       OR (p_action = 'release' AND NOT artifact.legal_hold) THEN
        RAISE EXCEPTION 'Workflow C artifact hold target state is invalid'
            USING ERRCODE = '23514';
    END IF;
    INSERT INTO workflow_c_artifact_hold_requests(
        id, project_id, artifact_id, action, status, requested_by,
        requested_at, request_reason, hold_until, hold_policy_version,
        expected_artifact_status, aggregate_version
    ) VALUES (
        p_request_id, p_project_id, p_artifact_id, p_action, 'pending',
        p_actor_id, p_requested_at, p_reason, p_hold_until, 2, 'active', 1
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
       OR request_record.hold_policy_version IS DISTINCT FROM 2
       OR request_record.requested_by = p_actor_id
       OR p_decided_at < request_record.requested_at
       OR (request_record.action IN ('apply', 'extend')
           AND p_decided_at >= request_record.hold_until) THEN
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
       OR (request_record.action = 'extend' AND (
            NOT artifact.legal_hold OR artifact.legal_hold_until IS NULL
            OR request_record.hold_until <= artifact.legal_hold_until
       ))
       OR (request_record.action = 'release' AND NOT artifact.legal_hold) THEN
        RAISE EXCEPTION 'Workflow C artifact hold target became stale'
            USING ERRCODE = '40001';
    END IF;
    IF p_approved THEN
        UPDATE workflow_c_manual_artifacts
        SET legal_hold = request_record.action <> 'release',
            legal_hold_until = CASE request_record.action
                WHEN 'release' THEN NULL ELSE request_record.hold_until
            END
        WHERE project_id = p_project_id AND artifact_id = request_record.artifact_id;
        event_kind := CASE request_record.action
            WHEN 'apply' THEN 'hold_applied'
            WHEN 'extend' THEN 'hold_extended'
            ELSE 'hold_released'
        END;
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

CREATE FUNCTION geo_expire_workflow_c_artifact_holds(
    p_now timestamptz,
    p_limit integer
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE request_record workflow_c_artifact_hold_requests%ROWTYPE;
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE expired_count bigint := 0;
BEGIN
    IF p_now IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'Workflow C artifact hold expiry input is invalid'
            USING ERRCODE = '22023';
    END IF;
    FOR request_record IN
        SELECT request_row.*
        FROM workflow_c_artifact_hold_requests AS request_row
        WHERE request_row.hold_policy_version = 2
          AND request_row.action IN ('apply', 'extend')
          AND request_row.hold_until <= p_now
          AND (
              request_row.status = 'pending'
              OR (
                  request_row.status = 'approved'
                  AND EXISTS (
                      SELECT 1
                      FROM workflow_c_manual_artifacts AS artifact_row
                      WHERE artifact_row.project_id = request_row.project_id
                        AND artifact_row.artifact_id = request_row.artifact_id
                        AND artifact_row.status = 'active'
                        AND artifact_row.legal_hold
                        AND artifact_row.legal_hold_until = request_row.hold_until
                  )
              )
          )
        ORDER BY request_row.hold_until, request_row.id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    LOOP
        IF request_record.status = 'pending' THEN
            UPDATE workflow_c_artifact_hold_requests
            SET status = 'expired',
                decided_by = 'workflow_c.hold_expiry_scheduler',
                decided_at = p_now,
                decision_reason = 'approval_window_elapsed',
                aggregate_version = 2
            WHERE project_id = request_record.project_id
              AND id = request_record.id;
            PERFORM geo_append_workflow_c_artifact_event(
                request_record.project_id, request_record.artifact_id,
                'hold_expired', 'workflow_c.hold_expiry_scheduler',
                'approval_window_elapsed', p_now
            );
            expired_count := expired_count + 1;
            CONTINUE;
        END IF;
        SELECT * INTO artifact
        FROM workflow_c_manual_artifacts
        WHERE project_id = request_record.project_id
          AND artifact_id = request_record.artifact_id
        FOR UPDATE;
        IF FOUND AND artifact.status = 'active' AND artifact.legal_hold
           AND artifact.legal_hold_until = request_record.hold_until THEN
            UPDATE workflow_c_manual_artifacts AS artifact_row
            SET legal_hold = false, legal_hold_until = NULL
            WHERE artifact_row.project_id = artifact.project_id
              AND artifact_row.artifact_id = artifact.artifact_id;
            UPDATE workflow_c_artifact_hold_requests
            SET status = 'expired'
            WHERE project_id = request_record.project_id
              AND id = request_record.id;
            PERFORM geo_append_workflow_c_artifact_event(
                request_record.project_id, request_record.artifact_id,
                'hold_expired', 'workflow_c.hold_expiry_scheduler',
                'hold_period_elapsed', p_now
            );
            expired_count := expired_count + 1;
        END IF;
    END LOOP;
    RETURN expired_count;
END;
$$;

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
    PERFORM geo_expire_workflow_c_artifact_holds(p_now, p_limit);
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

-- Hold commands are reachable only through SECURITY DEFINER routines; direct
-- inserts would create unreviewed audit records that never reached the state
-- machine. The scheduler invokes the expiry helper under its definer identity.
REVOKE INSERT ON workflow_c_artifact_hold_requests FROM geo_app;
REVOKE ALL ON FUNCTION geo_expire_workflow_c_artifact_holds(timestamptz, integer)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_request_workflow_c_artifact_hold(
    uuid, uuid, uuid, text, text, text, timestamptz, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_request_workflow_c_artifact_hold(
    uuid, uuid, uuid, text, text, text, timestamptz, timestamptz
) TO geo_app;

COMMENT ON COLUMN workflow_c_manual_artifacts.legal_hold_until IS
    'Approved legal-hold expiry. Active legacy holds are rejected during migration and must be reapproved.';
COMMENT ON COLUMN workflow_c_artifact_hold_requests.hold_until IS
    'Requested bounded legal-hold expiry; apply and extend requests are capped at 90 days.';
