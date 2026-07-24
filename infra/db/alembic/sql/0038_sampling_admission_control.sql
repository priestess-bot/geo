-- Sampling admission is a maker-checker authorization boundary.  The initial
-- Workflow C schema had storage for policies but could not represent its own
-- lifecycle, and geo_app could write directly around idempotency and audit.

ALTER TABLE workflow_c_sampling_admission_policies
    ADD COLUMN platform text,
    ADD COLUMN capture_method text,
    ADD COLUMN adapter_release text,
    ADD COLUMN location_control text,
    ADD COLUMN location_evidence_hash text,
    ADD COLUMN authorization_reference text,
    ADD COLUMN created_by text,
    ADD COLUMN authorized_purposes jsonb,
    ADD COLUMN submitted_by text,
    ADD COLUMN submitted_at timestamptz,
    ADD COLUMN decided_by text,
    ADD COLUMN decided_at timestamptz,
    ADD COLUMN decision_reason text,
    ADD COLUMN revoked_by text,
    ADD COLUMN revoked_at timestamptz,
    ADD COLUMN revocation_reason text;

-- The table has not had a durable writer before this migration.  Preserve any
-- manually seeded legacy rows as auditable, read-only policy history rather
-- than silently dropping them while making the new lifecycle representable.
UPDATE workflow_c_sampling_admission_policies
   SET platform = COALESCE(NULLIF(payload->>'platform', ''), 'legacy_migration'),
       capture_method = COALESCE(NULLIF(payload->>'capture_method', ''), 'provider_api'),
       adapter_release = COALESCE(NULLIF(payload->>'adapter_release', ''), 'legacy_migration'),
       location_control = COALESCE(NULLIF(payload->>'location_control', ''), 'not_controlled'),
       location_evidence_hash = COALESCE(
           NULLIF(payload->>'location_evidence_hash', ''), repeat('0', 64)
       ),
       authorization_reference = COALESCE(
           NULLIF(payload->>'authorization_reference', ''), 'legacy_migration'
       ),
       created_by = COALESCE(NULLIF(payload->>'created_by', ''), 'legacy_migration'),
       authorized_purposes = COALESCE(
           CASE WHEN jsonb_typeof(payload->'authorized_purposes') = 'array'
                AND jsonb_array_length(payload->'authorized_purposes') > 0
                THEN payload->'authorized_purposes' END,
           '["legacy_migration"]'::jsonb
       );

UPDATE workflow_c_sampling_admission_policies
   SET submitted_by = created_by,
       submitted_at = created_at,
       decided_by = CASE
           WHEN created_by = 'legacy_migration' THEN 'legacy_migration_reviewer'
           ELSE created_by
       END,
       decided_at = updated_at,
       decision_reason = 'legacy policy state migrated to durable lifecycle',
       effective_authorization_state = 'approved'
 WHERE status = 'approved';

UPDATE workflow_c_sampling_admission_policies
   SET status = 'revoked',
       effective_authorization_state = 'revoked',
       submitted_by = created_by,
       submitted_at = created_at,
       decided_by = CASE
           WHEN created_by = 'legacy_migration' THEN 'legacy_migration_reviewer'
           ELSE created_by
       END,
       decided_at = updated_at,
       decision_reason = 'legacy retired policy migrated to revoked',
       revoked_by = 'legacy_migration',
       revoked_at = updated_at,
       revocation_reason = 'legacy retired policy migrated to revoked'
 WHERE status = 'retired';

ALTER TABLE workflow_c_sampling_admission_policies
    ALTER COLUMN platform SET NOT NULL,
    ALTER COLUMN capture_method SET NOT NULL,
    ALTER COLUMN adapter_release SET NOT NULL,
    ALTER COLUMN location_control SET NOT NULL,
    ALTER COLUMN location_evidence_hash SET NOT NULL,
    ALTER COLUMN authorization_reference SET NOT NULL,
    ALTER COLUMN created_by SET NOT NULL,
    ALTER COLUMN authorized_purposes SET NOT NULL,
    DROP CONSTRAINT workflow_c_sampling_admission_policies_status_check,
    ADD CONSTRAINT workflow_c_sampling_admission_policies_status_check CHECK (
        status IN ('draft', 'pending_review', 'approved', 'assessed_no_basis', 'revoked')
    ),
    ADD CONSTRAINT workflow_c_sampling_admission_policies_purposes_check CHECK (
        jsonb_typeof(authorized_purposes) = 'array'
        AND jsonb_array_length(authorized_purposes) > 0
    ),
    ADD CONSTRAINT workflow_c_sampling_admission_policies_capture_method_check CHECK (
        capture_method IN ('provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui')
    ),
    ADD CONSTRAINT workflow_c_sampling_admission_policies_location_control_check CHECK (
        location_control IN ('country', 'market_language', 'language_only', 'not_controlled')
    ),
    ADD CONSTRAINT workflow_c_sampling_admission_policies_location_evidence_hash_check CHECK (
        location_evidence_hash ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT workflow_c_sampling_admission_policies_lifecycle_check CHECK (
        (status = 'draft'
            AND effective_authorization_state = 'not_assessed'
            AND submitted_by IS NULL AND submitted_at IS NULL
            AND decided_by IS NULL AND decided_at IS NULL AND decision_reason IS NULL
            AND revoked_by IS NULL AND revoked_at IS NULL AND revocation_reason IS NULL)
        OR (status = 'pending_review'
            AND effective_authorization_state = 'not_assessed'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND decided_by IS NULL AND decided_at IS NULL AND decision_reason IS NULL
            AND revoked_by IS NULL AND revoked_at IS NULL AND revocation_reason IS NULL)
        OR (status = 'approved'
            AND effective_authorization_state = 'approved'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND decision_reason IS NOT NULL
            AND revoked_by IS NULL AND revoked_at IS NULL AND revocation_reason IS NULL)
        OR (status = 'assessed_no_basis'
            AND effective_authorization_state = 'assessed_no_basis'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND decision_reason IS NOT NULL
            AND revoked_by IS NULL AND revoked_at IS NULL AND revocation_reason IS NULL)
        OR (status = 'revoked'
            AND effective_authorization_state = 'revoked'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND decision_reason IS NOT NULL
            AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)
    );

CREATE TABLE workflow_c_sampling_runtime_options (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    option_key text NOT NULL CHECK (btrim(option_key) <> ''),
    option_hash text NOT NULL CHECK (option_hash ~ '^[0-9a-f]{64}$'),
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    platform text NOT NULL CHECK (btrim(platform) <> ''),
    capture_method text NOT NULL CHECK (capture_method IN (
        'provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui'
    )),
    adapter_release text NOT NULL CHECK (btrim(adapter_release) <> ''),
    location_control text NOT NULL CHECK (location_control IN (
        'country', 'market_language', 'language_only', 'not_controlled'
    )),
    location_evidence_hash text NOT NULL CHECK (
        location_evidence_hash ~ '^[0-9a-f]{64}$'
    ),
    authorization_reference text NOT NULL CHECK (btrim(authorization_reference) <> ''),
    allowed_purposes jsonb NOT NULL CHECK (
        jsonb_typeof(allowed_purposes) = 'array'
        AND jsonb_array_length(allowed_purposes) > 0
    ),
    status text NOT NULL CHECK (status IN ('approved', 'retired')),
    frozen_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, option_key),
    UNIQUE (project_id, option_hash)
);

ALTER TABLE workflow_c_sampling_runtime_options ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_sampling_runtime_options FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_sampling_runtime_options
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

CREATE FUNCTION geo_assert_workflow_c_sampling_admission_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Sampling admission policies are append-only definitions'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' OR NEW.aggregate_version <> 1
           OR NEW.effective_authorization_state <> 'not_assessed' THEN
            RAISE EXCEPTION 'Sampling admission policy must begin as a draft'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(
        NEW.id, NEW.project_id, NEW.revision, NEW.supersedes_policy_id,
        NEW.platform, NEW.capture_method, NEW.adapter_release, NEW.location_control,
        NEW.location_evidence_hash, NEW.authorization_reference,
        NEW.definition_hash, NEW.policy_version, NEW.valid_until,
        NEW.quota_remaining, NEW.daily_task_limit,
        NEW.minimum_request_interval_seconds, NEW.max_concurrency,
        NEW.next_allowed_at, NEW.created_by, NEW.authorized_purposes,
        NEW.payload, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.id, OLD.project_id, OLD.revision, OLD.supersedes_policy_id,
        OLD.platform, OLD.capture_method, OLD.adapter_release, OLD.location_control,
        OLD.location_evidence_hash, OLD.authorization_reference,
        OLD.definition_hash, OLD.policy_version, OLD.valid_until,
        OLD.quota_remaining, OLD.daily_task_limit,
        OLD.minimum_request_interval_seconds, OLD.max_concurrency,
        OLD.next_allowed_at, OLD.created_by, OLD.authorized_purposes,
        OLD.payload, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'Sampling admission policy definition is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.aggregate_version <> OLD.aggregate_version + 1
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'Sampling admission policy version transition is invalid'
            USING ERRCODE = '40001';
    END IF;
    IF OLD.status = 'draft' AND NEW.status = 'pending_review'
       AND NEW.effective_authorization_state = 'not_assessed'
       AND NEW.submitted_by IS NOT NULL AND NEW.submitted_at IS NOT NULL
       AND NEW.decided_by IS NULL AND NEW.decided_at IS NULL AND NEW.decision_reason IS NULL
       AND NEW.revoked_by IS NULL AND NEW.revoked_at IS NULL AND NEW.revocation_reason IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'pending_review'
       AND NEW.status IN ('approved', 'assessed_no_basis')
       AND NEW.submitted_by = OLD.submitted_by AND NEW.submitted_at = OLD.submitted_at
       AND NEW.decided_by IS NOT NULL AND NEW.decided_by <> OLD.created_by
       AND NEW.decided_at IS NOT NULL AND NEW.decision_reason IS NOT NULL
       AND NEW.revoked_by IS NULL AND NEW.revoked_at IS NULL AND NEW.revocation_reason IS NULL
       AND NEW.effective_authorization_state = (CASE NEW.status
           WHEN 'approved' THEN 'approved' ELSE 'assessed_no_basis' END) THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'approved' AND NEW.status = 'revoked'
       AND NEW.submitted_by = OLD.submitted_by AND NEW.submitted_at = OLD.submitted_at
       AND NEW.decided_by = OLD.decided_by AND NEW.decided_at = OLD.decided_at
       AND NEW.decision_reason = OLD.decision_reason
       AND NEW.revoked_by IS NOT NULL AND NEW.revoked_at IS NOT NULL
       AND NEW.revocation_reason IS NOT NULL
       AND NEW.effective_authorization_state = 'revoked' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Sampling admission policy lifecycle transition is invalid'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER workflow_c_sampling_admission_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON workflow_c_sampling_admission_policies
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_sampling_admission_change();

CREATE FUNCTION geo_create_workflow_c_sampling_admission_policy(
    p_project_id uuid,
    p_policy_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_supersedes_policy_id uuid,
    p_definition_hash text,
    p_policy_version text,
    p_platform text,
    p_capture_method text,
    p_adapter_release text,
    p_location_control text,
    p_location_evidence_hash text,
    p_authorization_reference text,
    p_authorized_purposes jsonb,
    p_valid_until timestamptz,
    p_quota_remaining integer,
    p_daily_task_limit integer,
    p_minimum_request_interval_seconds integer,
    p_max_concurrency integer,
    p_created_by text,
    p_created_at timestamptz,
    p_payload jsonb
) RETURNS SETOF workflow_c_sampling_admission_policies
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE predecessor workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE option_row workflow_c_sampling_runtime_options%ROWTYPE;
DECLARE expected_revision integer := 1;
DECLARE expected_policy_version text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR jsonb_typeof(p_payload) <> 'object'
       OR p_payload <> jsonb_build_object(
           'schema_version', 1,
           'runtime_authorization_option_key', p_payload->>'runtime_authorization_option_key',
           'runtime_authorization_option_hash', p_payload->>'runtime_authorization_option_hash'
       )
       OR jsonb_typeof(p_authorized_purposes) <> 'array'
       OR jsonb_array_length(p_authorized_purposes) = 0
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Sampling admission create command is invalid or out of scope'
            USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-sampling-policy:' || p_project_id::text || ':' || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.admission_policy.create'
       AND aggregate_id = p_policy_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_policy_id THEN
            RAISE EXCEPTION 'Sampling admission create idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT * FROM workflow_c_sampling_admission_policies
         WHERE project_id = p_project_id AND id = p_policy_id;
        RETURN;
    END IF;
    IF p_supersedes_policy_id IS NOT NULL THEN
        SELECT * INTO predecessor FROM workflow_c_sampling_admission_policies
         WHERE project_id = p_project_id AND id = p_supersedes_policy_id FOR UPDATE;
        IF NOT FOUND OR predecessor.status IN ('draft', 'pending_review') THEN
            RAISE EXCEPTION 'Sampling admission predecessor is not decided'
                USING ERRCODE = '23514';
        END IF;
        expected_revision := predecessor.revision + 1;
    END IF;
    SELECT * INTO option_row FROM workflow_c_sampling_runtime_options
     WHERE project_id = p_project_id
       AND option_key = p_payload->>'runtime_authorization_option_key'
       AND option_hash = p_payload->>'runtime_authorization_option_hash'
       AND status = 'approved';
    IF NOT FOUND
       OR option_row.platform <> p_platform
       OR option_row.capture_method <> p_capture_method
       OR option_row.adapter_release <> p_adapter_release
       OR option_row.location_control <> p_location_control
       OR option_row.location_evidence_hash <> p_location_evidence_hash
       OR option_row.authorization_reference <> p_authorization_reference
       OR NOT option_row.allowed_purposes @> p_authorized_purposes THEN
        RAISE EXCEPTION 'Sampling admission does not match an approved runtime option'
            USING ERRCODE = '23514';
    END IF;
    IF encode(digest(convert_to(geo_jsonb_canonical_text(jsonb_build_object(
        'id', p_policy_id,
        'project_id', p_project_id,
        'revision', expected_revision,
        'supersedes_policy_id', p_supersedes_policy_id,
        'platform', p_platform,
        'capture_method', p_capture_method,
        'adapter_release', p_adapter_release,
        'location_control', p_location_control,
        'location_evidence_hash', p_location_evidence_hash,
        'authorization_reference', p_authorization_reference,
        'authorized_purposes', p_authorized_purposes,
        'valid_until', p_valid_until,
        'quota_remaining', p_quota_remaining,
        'daily_task_limit', p_daily_task_limit,
        'minimum_request_interval_seconds', p_minimum_request_interval_seconds,
        'max_concurrency', p_max_concurrency,
        'next_allowed_at', p_created_at
    )), 'UTF8'), 'sha256'), 'hex') <> p_definition_hash THEN
        RAISE EXCEPTION 'Sampling admission definition hash does not match frozen input'
            USING ERRCODE = '23514';
    END IF;
    expected_policy_version := 'sampling-admission:' || p_policy_id::text
        || ':r' || expected_revision::text || ':' || left(p_definition_hash, 12);
    IF p_policy_version <> expected_policy_version THEN
        RAISE EXCEPTION 'Sampling admission policy version does not match its definition'
            USING ERRCODE = '23514';
    END IF;
    INSERT INTO workflow_c_sampling_admission_policies(
        id, project_id, revision, supersedes_policy_id, status,
        effective_authorization_state, definition_hash, policy_version, valid_until,
        quota_remaining, daily_task_limit, minimum_request_interval_seconds,
        max_concurrency, next_allowed_at, aggregate_version, payload,
        created_at, updated_at, created_by, authorized_purposes,
        platform, capture_method, adapter_release, location_control,
        location_evidence_hash, authorization_reference
    ) VALUES (
        p_policy_id, p_project_id, expected_revision, p_supersedes_policy_id, 'draft',
        'not_assessed', p_definition_hash, p_policy_version, p_valid_until,
        p_quota_remaining, p_daily_task_limit, p_minimum_request_interval_seconds,
        p_max_concurrency, p_created_at, 1, p_payload,
        p_created_at, p_created_at, p_created_by, p_authorized_purposes,
        p_platform, p_capture_method, p_adapter_release, p_location_control,
        p_location_evidence_hash, p_authorization_reference
    );
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.admission_policy.create', p_policy_id,
        p_idempotency_key_hash, p_input_hash, 'sampling_admission_policy',
        p_policy_id, 1, jsonb_build_object('policy_id', p_policy_id), p_created_at
    );
    RETURN QUERY SELECT * FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = p_policy_id;
END;
$$;

CREATE FUNCTION geo_transition_workflow_c_sampling_admission_policy(
    p_project_id uuid,
    p_policy_id uuid,
    p_expected_version integer,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_operation text,
    p_actor_id text,
    p_reason text,
    p_occurred_at timestamptz
) RETURNS SETOF workflow_c_sampling_admission_policies
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE policy workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE scope_name text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR p_operation NOT IN ('submit', 'approve', 'assess_no_basis', 'revoke')
       OR btrim(p_actor_id) = ''
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Sampling admission transition is invalid or out of scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_operation IN ('approve', 'assess_no_basis', 'revoke')
       AND (p_reason IS NULL OR btrim(p_reason) = '') THEN
        RAISE EXCEPTION 'Sampling admission decision requires a reason'
            USING ERRCODE = '23514';
    END IF;
    scope_name := 'sampling.admission_policy.' || p_operation;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-sampling-policy:' || p_project_id::text || ':' || p_policy_id::text
            || ':' || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing FROM workflow_c_command_ledger
     WHERE project_id = p_project_id AND command_scope = scope_name
       AND aggregate_id = p_policy_id AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_policy_id THEN
            RAISE EXCEPTION 'Sampling admission transition idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT * FROM workflow_c_sampling_admission_policies
         WHERE project_id = p_project_id AND id = p_policy_id;
        RETURN;
    END IF;
    SELECT * INTO policy FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = p_policy_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling admission policy does not exist'
            USING ERRCODE = 'P0002';
    END IF;
    IF policy.aggregate_version <> p_expected_version OR p_occurred_at < policy.updated_at THEN
        RAISE EXCEPTION 'Sampling admission policy version is stale'
            USING ERRCODE = '40001';
    END IF;
    IF p_operation = 'submit' THEN
        IF policy.status <> 'draft' THEN
            RAISE EXCEPTION 'Only a draft Sampling admission policy can be submitted'
                USING ERRCODE = '23514';
        END IF;
        UPDATE workflow_c_sampling_admission_policies
           SET status = 'pending_review', submitted_by = p_actor_id,
               submitted_at = p_occurred_at, aggregate_version = aggregate_version + 1,
               updated_at = p_occurred_at
         WHERE project_id = p_project_id AND id = p_policy_id;
    ELSIF p_operation IN ('approve', 'assess_no_basis') THEN
        IF policy.status <> 'pending_review' OR policy.created_by = p_actor_id THEN
            RAISE EXCEPTION 'Sampling admission maker-checker decision is invalid'
                USING ERRCODE = '23514';
        END IF;
        UPDATE workflow_c_sampling_admission_policies
           SET status = CASE WHEN p_operation = 'approve' THEN 'approved'
                             ELSE 'assessed_no_basis' END,
               effective_authorization_state = CASE
                   WHEN p_operation = 'approve' THEN 'approved' ELSE 'assessed_no_basis' END,
               decided_by = p_actor_id, decided_at = p_occurred_at,
               decision_reason = p_reason, aggregate_version = aggregate_version + 1,
               updated_at = p_occurred_at
         WHERE project_id = p_project_id AND id = p_policy_id;
    ELSE
        IF policy.status <> 'approved' THEN
            RAISE EXCEPTION 'Only an approved Sampling admission policy can be revoked'
                USING ERRCODE = '23514';
        END IF;
        UPDATE workflow_c_sampling_admission_policies
           SET status = 'revoked', effective_authorization_state = 'revoked',
               revoked_by = p_actor_id, revoked_at = p_occurred_at,
               revocation_reason = p_reason, aggregate_version = aggregate_version + 1,
               updated_at = p_occurred_at
         WHERE project_id = p_project_id AND id = p_policy_id;
    END IF;
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) SELECT p_project_id, scope_name, p_policy_id, p_idempotency_key_hash,
             p_input_hash, 'sampling_admission_policy', p_policy_id,
             aggregate_version, jsonb_build_object('policy_id', p_policy_id), p_occurred_at
        FROM workflow_c_sampling_admission_policies
       WHERE project_id = p_project_id AND id = p_policy_id;
    RETURN QUERY SELECT * FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = p_policy_id;
END;
$$;

REVOKE ALL ON workflow_c_sampling_admission_policies, workflow_c_command_ledger
FROM geo_app;
GRANT SELECT ON workflow_c_sampling_admission_policies, workflow_c_command_ledger,
    workflow_c_sampling_runtime_options TO geo_app;
REVOKE ALL ON workflow_c_sampling_runtime_options FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON workflow_c_sampling_runtime_options TO geo_app, geo_worker;

REVOKE ALL ON FUNCTION
    geo_assert_workflow_c_sampling_admission_change(),
    geo_create_workflow_c_sampling_admission_policy(
        uuid, uuid, text, text, uuid, text, text, text, text, text, text, text,
        text, jsonb, timestamptz, integer, integer, integer, integer, text,
        timestamptz, jsonb
    ),
    geo_transition_workflow_c_sampling_admission_policy(
        uuid, uuid, integer, text, text, text, text, text, timestamptz
    )
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_create_workflow_c_sampling_admission_policy(
        uuid, uuid, text, text, uuid, text, text, text, text, text, text, text,
        text, jsonb, timestamptz, integer, integer, integer, integer, text,
        timestamptz, jsonb
    ),
    geo_transition_workflow_c_sampling_admission_policy(
        uuid, uuid, integer, text, text, text, text, text, timestamptz
    ) TO geo_app;
