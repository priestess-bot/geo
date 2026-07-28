-- Freeze the execution backend at child admission. Existing rows are native
-- unless immutable Dify attempt evidence proves the exact release used.
ALTER TABLE synthetic_lab_model_call_children
ADD COLUMN execution_backend text NOT NULL DEFAULT 'model_gateway',
ADD COLUMN workflow_release_id uuid,
ADD COLUMN workflow_release_hash text,
ADD COLUMN backend_lineage_source text NOT NULL DEFAULT 'migration_backfill_native';

-- The predecessor table is append-only. Alembic owns this transaction and
-- temporarily removes only that exact immutable-row trigger so the one-time
-- evidence reconstruction can annotate legacy rows. Any later failure rolls
-- the transaction back with the trigger still enabled.
DROP TRIGGER synthetic_lab_model_call_children_immutable
ON synthetic_lab_model_call_children;

WITH latest_dify AS (
    SELECT DISTINCT ON (attempt.project_id, attempt.job_id)
           attempt.project_id, attempt.job_id, attempt.release_id,
           release.release_hash, release.purpose, release.prompt_release_id,
           release.prompt_release_hash, release.configured_model
    FROM dify_workflow_execution_attempts attempt
    JOIN dify_workflow_releases release
      ON release.id = attempt.release_id AND release.project_id = attempt.project_id
    WHERE attempt.execution_kind = 'business' AND attempt.job_id IS NOT NULL
    ORDER BY attempt.project_id, attempt.job_id, attempt.attempt_number DESC
)
UPDATE synthetic_lab_model_call_children child
SET execution_backend = 'dify',
    workflow_release_id = latest.release_id,
    workflow_release_hash = latest.release_hash,
    backend_lineage_source = CASE
        WHEN (latest.purpose, latest.prompt_release_id,
              latest.prompt_release_hash, latest.configured_model)
             IS NOT DISTINCT FROM
             (child.prompt_purpose, child.prompt_release_id,
              child.prompt_release_hash, child.configured_model)
        THEN 'migration_backfill_verified'
        ELSE 'migration_backfill_historical_mismatch'
    END
FROM latest_dify latest
WHERE child.project_id = latest.project_id
  AND child.child_job_id = latest.job_id;

CREATE TRIGGER synthetic_lab_model_call_children_immutable
BEFORE UPDATE OR DELETE ON synthetic_lab_model_call_children
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

-- Rows that predate this migration retain an explicit weaker provenance: the
-- backend/release was reconstructed from their immutable 0097 attempt evidence.
-- Every row inserted after this point is admitted by the strict trigger below.
ALTER TABLE synthetic_lab_model_call_children
ALTER COLUMN backend_lineage_source SET DEFAULT 'runtime_admission';

-- Fail closed after the evidence backfill. A queued/active child under an
-- active Dify purpose cannot be guessed from the current binding, and an exact
-- Dify release without its successful-canary pin is not executable.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM synthetic_lab_model_call_children child
        JOIN durable_jobs job
          ON job.id = child.child_job_id AND job.project_id = child.project_id
        LEFT JOIN LATERAL (
            SELECT attempt.published_snapshot_id
            FROM dify_workflow_execution_attempts attempt
            WHERE attempt.project_id = child.project_id
              AND attempt.job_id = child.child_job_id
              AND attempt.execution_kind = 'business'
              AND attempt.release_id = child.workflow_release_id
            ORDER BY attempt.attempt_number DESC
            LIMIT 1
        ) latest_attempt ON true
        LEFT JOIN dify_workflow_release_snapshot_pins pin
          ON pin.project_id = child.project_id
         AND pin.release_id = child.workflow_release_id
        WHERE job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
          AND child.execution_backend = 'dify'
          AND (
              pin.release_id IS NULL
              OR latest_attempt.published_snapshot_id IS NULL
              OR latest_attempt.published_snapshot_id
                   IS DISTINCT FROM pin.published_snapshot_id
          )
    ) OR EXISTS (
        SELECT 1
        FROM synthetic_lab_model_call_children child
        JOIN durable_jobs job
          ON job.id = child.child_job_id AND job.project_id = child.project_id
        LEFT JOIN dify_workflow_releases release
          ON release.id = child.workflow_release_id
         AND release.project_id = child.project_id
         AND release.release_hash = child.workflow_release_hash
        LEFT JOIN LATERAL (
            SELECT binding.release_id, binding.release_hash
            FROM dify_workflow_bindings binding
            WHERE binding.project_id = child.project_id
              AND binding.purpose = child.prompt_purpose
            ORDER BY binding.binding_version DESC
            LIMIT 1
        ) active_binding ON true
        WHERE job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
          AND child.execution_backend = 'dify'
          AND (
              release.id IS NULL
              OR release.purpose <> child.prompt_purpose
              OR release.prompt_release_id <> child.prompt_release_id
              OR release.prompt_release_hash <> child.prompt_release_hash
              OR release.configured_model <> child.configured_model
              OR active_binding.release_id IS DISTINCT FROM child.workflow_release_id
              OR active_binding.release_hash IS DISTINCT FROM child.workflow_release_hash
          )
    ) OR EXISTS (
        SELECT 1
        FROM synthetic_lab_model_call_children child
        JOIN durable_jobs job
          ON job.id = child.child_job_id AND job.project_id = child.project_id
        JOIN LATERAL (
            SELECT binding.release_id
            FROM dify_workflow_bindings binding
            WHERE binding.project_id = child.project_id
              AND binding.purpose = child.prompt_purpose
            ORDER BY binding.binding_version DESC
            LIMIT 1
        ) active_binding ON true
        WHERE job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
          AND child.execution_backend = 'model_gateway'
          AND child.prompt_purpose IN (
              'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
              'synthetic_lab.conflict_check', 'synthetic_lab.revision',
              'synthetic_lab.style_profile'
          )
    ) THEN
        RAISE EXCEPTION 'cannot migrate: a non-terminal Synthetic child lacks its exact pinned execution backend; drain it first'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

ALTER TABLE synthetic_lab_model_call_children
ADD CONSTRAINT synthetic_lab_model_call_children_backend_shape_check CHECK (
    (execution_backend = 'model_gateway'
        AND workflow_release_id IS NULL AND workflow_release_hash IS NULL)
    OR (execution_backend = 'dify'
        AND workflow_release_id IS NOT NULL
        AND workflow_release_hash ~ '^[0-9a-f]{64}$')
),
ADD CONSTRAINT synthetic_lab_model_call_children_lineage_source_check CHECK (
    backend_lineage_source IN (
        'migration_backfill_native', 'migration_backfill_verified',
        'migration_backfill_historical_mismatch', 'runtime_admission'
    )
),
ADD CONSTRAINT synthetic_lab_model_call_children_workflow_release_fkey
FOREIGN KEY (workflow_release_id, project_id, workflow_release_hash)
REFERENCES dify_workflow_releases(id, project_id, release_hash);

CREATE FUNCTION geo_assert_synthetic_child_execution_backend() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    requested_backend text := nullif(
        current_setting('geo.synthetic_child_execution_backend', true), ''
    );
    requested_release_id text := nullif(
        current_setting('geo.synthetic_child_workflow_release_id', true), ''
    );
    requested_release_hash text := nullif(
        current_setting('geo.synthetic_child_workflow_release_hash', true), ''
    );
    workflow dify_workflow_releases%ROWTYPE;
    active_binding dify_workflow_bindings%ROWTYPE;
BEGIN
    -- The compatibility wrappers communicate the three new immutable values
    -- to the unchanged v1 transaction body. Direct inserts retain table values.
    IF requested_backend IS NOT NULL THEN
        NEW.execution_backend := requested_backend;
        NEW.workflow_release_id := requested_release_id::uuid;
        NEW.workflow_release_hash := requested_release_hash;
    END IF;
    IF NEW.backend_lineage_source <> 'runtime_admission' THEN
        RAISE EXCEPTION 'new Synthetic child lineage must be admitted at runtime'
            USING ERRCODE = '23514';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'dify-binding:' || NEW.project_id::text || ':' || NEW.prompt_purpose, 0
    ));
    SELECT binding.* INTO active_binding
    FROM dify_workflow_bindings binding
    WHERE binding.project_id = NEW.project_id
      AND binding.purpose = NEW.prompt_purpose
    ORDER BY binding.binding_version DESC
    LIMIT 1;

    IF NEW.execution_backend = 'dify' THEN
        IF NEW.prompt_purpose NOT IN (
            'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
            'synthetic_lab.conflict_check', 'synthetic_lab.revision',
            'synthetic_lab.style_profile'
        ) OR NEW.workflow_release_id IS NULL
           OR coalesce(NEW.workflow_release_hash, '') !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'Synthetic Dify child has an invalid frozen backend shape'
                USING ERRCODE = '23514';
        END IF;
        SELECT release.* INTO workflow
        FROM dify_workflow_releases release
        WHERE release.id = NEW.workflow_release_id
          AND release.project_id = NEW.project_id
          AND release.release_hash = NEW.workflow_release_hash;
        IF NOT FOUND
           OR workflow.purpose <> NEW.prompt_purpose
           OR workflow.prompt_release_id <> NEW.prompt_release_id
           OR workflow.prompt_release_hash <> NEW.prompt_release_hash
           OR workflow.configured_model <> NEW.configured_model
           OR active_binding.id IS NULL
           OR active_binding.release_id <> NEW.workflow_release_id
           OR active_binding.release_hash <> NEW.workflow_release_hash
           OR NOT EXISTS (
                SELECT 1 FROM dify_workflow_release_snapshot_pins pin
                WHERE pin.project_id = NEW.project_id
                  AND pin.release_id = NEW.workflow_release_id
           ) THEN
            RAISE EXCEPTION 'Synthetic Dify child differs from the active pinned Workflow Release'
                USING ERRCODE = '40001';
        END IF;
    ELSIF NEW.execution_backend = 'model_gateway' THEN
        IF NEW.workflow_release_id IS NOT NULL OR NEW.workflow_release_hash IS NOT NULL THEN
            RAISE EXCEPTION 'native Synthetic child cannot carry Dify release identity'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.prompt_purpose IN (
            'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
            'synthetic_lab.conflict_check', 'synthetic_lab.revision',
            'synthetic_lab.style_profile'
        ) AND active_binding.id IS NOT NULL THEN
            RAISE EXCEPTION 'Synthetic Prompt purpose is bound to Dify; deploy the backend-aware worker before enqueue'
                USING ERRCODE = '40001';
        END IF;
    ELSE
        RAISE EXCEPTION 'Synthetic child execution backend is unsupported'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_assert_synthetic_child_execution_backend() FROM PUBLIC;
CREATE TRIGGER synthetic_lab_model_call_backend_guard
BEFORE INSERT ON synthetic_lab_model_call_children
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_child_execution_backend();

CREATE FUNCTION geo_reject_synthetic_child_backend_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Synthetic child execution backend and Workflow Release are immutable'
        USING ERRCODE = '55000';
END;
$$;
REVOKE ALL ON FUNCTION geo_reject_synthetic_child_backend_change() FROM PUBLIC;
CREATE TRIGGER synthetic_lab_model_call_backend_immutable
BEFORE UPDATE OF execution_backend, workflow_release_id, workflow_release_hash,
                 backend_lineage_source
ON synthetic_lab_model_call_children
FOR EACH ROW EXECUTE FUNCTION geo_reject_synthetic_child_backend_change();

-- A Style Profile build consumes a draft Profile by design. Keep the strict
-- frozen-profile requirement for every other parent/purpose combination.
CREATE OR REPLACE FUNCTION geo_assert_synthetic_model_call_child() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_job durable_jobs%ROWTYPE;
    child_job durable_jobs%ROWTYPE;
    parent_metadata synthetic_lab_job_metadata%ROWTYPE;
    child_metadata synthetic_lab_job_metadata%ROWTYPE;
    parent_task synthetic_lab_execution_tasks%ROWTYPE;
    child_outbox synthetic_lab_outbox_messages%ROWTYPE;
    prompt_binding prompt_program_bindings%ROWTYPE;
    prompt_release prompt_program_releases%ROWTYPE;
    prompt_state prompt_program_release_states%ROWTYPE;
    runtime_manifest model_gateway_runtime_manifests%ROWTYPE;
    runtime_option model_gateway_runtime_options%ROWTYPE;
    model_release model_gateway_model_releases%ROWTYPE;
    expected_payload jsonb;
    expected_payload_hash text;
BEGIN
    SELECT * INTO STRICT parent_job FROM durable_jobs
    WHERE id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_job FROM durable_jobs
    WHERE id = NEW.child_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT parent_metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.child_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT parent_task FROM synthetic_lab_execution_tasks
    WHERE job_id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_outbox FROM synthetic_lab_outbox_messages
    WHERE id = NEW.outbox_id AND project_id = NEW.project_id;

    expected_payload := jsonb_build_object(
        'parent_job_id', NEW.parent_job_id::text,
        'step_key_hash', NEW.step_key_hash,
        'task_artifact_hash', NEW.task_artifact_hash
    );
    expected_payload_hash := encode(digest(
        convert_to(geo_jsonb_canonical_text(expected_payload), 'UTF8'), 'sha256'
    ), 'hex');
    IF NEW.step_key_hash <> encode(digest(convert_to(NEW.step_key, 'UTF8'), 'sha256'), 'hex')
       OR parent_job.kind <> NEW.parent_job_kind
       OR parent_job.status NOT IN ('running', 'finalizing')
       OR parent_job.cancel_requested_at IS NOT NULL
       OR parent_job.lease_token IS DISTINCT FROM NEW.parent_lease_token
       OR parent_job.fencing_generation <> NEW.parent_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= NEW.created_at
       OR parent_task.task_input_hash <> NEW.parent_task_input_hash
       OR child_job.kind <> 'synthetic.model.call'
       OR child_job.status <> 'queued'
       OR child_job.attempt_count <> 0
       OR child_job.fencing_generation <> 0
       OR child_job.input_hash <> NEW.child_input_hash
       OR child_job.parent_job_id IS DISTINCT FROM NEW.parent_job_id
       OR child_job.campaign_id IS DISTINCT FROM parent_job.campaign_id
       OR child_metadata.domain_job_kind <> 'model_call_child'
       OR child_metadata.payload <> expected_payload
       OR child_metadata.payload_hash <> expected_payload_hash
       OR child_outbox.job_id <> NEW.child_job_id
       OR child_outbox.event_type <> 'synthetic.model.call.queued'
       OR child_outbox.payload_hash <> NEW.child_input_hash THEN
        RAISE EXCEPTION 'Synthetic model child does not match parent lease, Job, or Outbox lineage'
            USING ERRCODE = '40001';
    END IF;
    IF (parent_metadata.fact_snapshot_id, parent_metadata.fact_snapshot_hash,
        parent_metadata.profile_version_id, parent_metadata.profile_hash,
        parent_metadata.prompt_release_id, parent_metadata.prompt_release_hash)
       IS DISTINCT FROM
       (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
        NEW.profile_version_id, NEW.profile_hash,
        NEW.runtime_prompt_release_id, NEW.runtime_prompt_release_hash)
       OR NOT coalesce(parent_metadata.facts_current_approved, false)
       OR (
            NOT coalesce(parent_metadata.profile_frozen, false)
            AND NOT (
                parent_job.kind = 'style.profile.build'
                AND NEW.parent_job_kind = 'style.profile.build'
                AND NEW.prompt_program_kind = 'style_profile'
                AND NEW.prompt_purpose = 'synthetic_lab.style_profile'
            )
       )
       OR NOT coalesce(parent_metadata.prompt_frozen, false)
       OR (child_metadata.fact_snapshot_id, child_metadata.fact_snapshot_hash,
           child_metadata.profile_version_id, child_metadata.profile_hash,
           child_metadata.prompt_release_id, child_metadata.prompt_release_hash,
           child_metadata.facts_current_approved, child_metadata.profile_frozen,
           child_metadata.prompt_frozen)
          IS DISTINCT FROM
          (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
           NEW.profile_version_id, NEW.profile_hash,
           NEW.runtime_prompt_release_id, NEW.runtime_prompt_release_hash,
           true, true, true) THEN
        RAISE EXCEPTION 'Synthetic model child changed frozen parent runtime lineage'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO STRICT prompt_binding FROM prompt_program_bindings
    WHERE id = NEW.prompt_binding_id AND project_id = NEW.project_id
      AND purpose = NEW.prompt_purpose
      AND binding_version = NEW.prompt_binding_version;
    SELECT * INTO STRICT prompt_release FROM prompt_program_releases
    WHERE id = NEW.prompt_release_id AND project_id = NEW.project_id
      AND release_hash = NEW.prompt_release_hash;
    SELECT * INTO STRICT prompt_state FROM prompt_program_release_states
    WHERE id = NEW.prompt_frozen_state_id AND project_id = NEW.project_id
      AND release_id = NEW.prompt_release_id
      AND release_hash = NEW.prompt_release_hash
      AND version = NEW.prompt_state_version;
    IF prompt_binding.release_id <> NEW.prompt_release_id
       OR prompt_binding.release_version <> NEW.prompt_release_version
       OR prompt_binding.release_hash <> NEW.prompt_release_hash
       OR prompt_binding.frozen_state_id <> NEW.prompt_frozen_state_id
       OR prompt_release.version <> NEW.prompt_release_version
       OR prompt_release.program_kind <> NEW.prompt_program_kind
       OR prompt_release.purpose <> NEW.prompt_purpose
       OR prompt_release.model_policy_hash <> NEW.prompt_model_policy_hash
       OR prompt_release.output_schema_hash <> NEW.portable_output_schema_hash
       OR prompt_release.application_output_schema_hash
            <> NEW.application_output_schema_hash
       OR prompt_state.status <> 'frozen'
       OR EXISTS (
            SELECT 1 FROM prompt_program_bindings newer
            WHERE newer.project_id = NEW.project_id
              AND newer.purpose = NEW.prompt_purpose
              AND newer.binding_version > NEW.prompt_binding_version
       ) THEN
        RAISE EXCEPTION 'Synthetic model child requires the exact current frozen Prompt binding'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO STRICT runtime_manifest FROM model_gateway_runtime_manifests
    WHERE id = NEW.runtime_manifest_id AND project_id = NEW.project_id
      AND manifest_hash = NEW.runtime_manifest_hash
    FOR SHARE;
    SELECT * INTO STRICT runtime_option FROM model_gateway_runtime_options
    WHERE id = NEW.runtime_option_id AND project_id = NEW.project_id
      AND manifest_id = NEW.runtime_manifest_id
      AND option_hash = NEW.runtime_option_hash;
    SELECT * INTO STRICT model_release FROM model_gateway_model_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND model_release_id = NEW.model_release_id
      AND release_hash = NEW.model_release_hash;
    IF runtime_manifest.status <> 'approved'
       OR runtime_option.provider <> NEW.provider
       OR runtime_option.adapter_release_id <> NEW.adapter_release_id
       OR runtime_option.adapter_release_hash <> NEW.adapter_release_hash
       OR runtime_option.model_release_id <> NEW.model_release_id
       OR runtime_option.model_release_hash <> NEW.model_release_hash
       OR NEW.prompt_purpose <> ALL(runtime_option.allowed_purposes)
       OR NOT runtime_option.allowed_search_modes @> jsonb_build_array(NEW.search_mode)
       OR model_release.configured_model <> NEW.configured_model
       OR model_release.state <> 'approved' THEN
        RAISE EXCEPTION 'Synthetic model child differs from the approved runtime option'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

-- Preserve the implementation that shipped with 0030 and expose it only
-- through backend-aware wrappers below.
ALTER FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) RENAME TO geo_enqueue_synthetic_model_call_child_v1;
REVOKE ALL ON FUNCTION geo_enqueue_synthetic_model_call_child_v1(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;

CREATE FUNCTION geo_enqueue_synthetic_model_call_child(
    p_project_id uuid, p_parent_job_id uuid, p_parent_lease_token uuid,
    p_parent_fencing_generation bigint, p_child_job_id uuid,
    p_parent_job_kind text, p_parent_task_input_hash text, p_step_key text,
    p_model_job_version integer, p_fact_snapshot_id uuid,
    p_fact_snapshot_hash text, p_profile_version_id uuid, p_profile_hash text,
    p_runtime_prompt_release_id uuid, p_runtime_prompt_release_hash text,
    p_prompt_binding_id uuid, p_prompt_binding_version integer,
    p_prompt_frozen_state_id uuid, p_prompt_frozen_state_version integer,
    p_prompt_release_id uuid, p_prompt_release_version integer,
    p_prompt_release_hash text, p_prompt_program_kind text,
    p_prompt_purpose text, p_admitted_by uuid, p_prompt_model_policy_hash text,
    p_provider text, p_adapter_release_id text, p_adapter_release_hash text,
    p_model_release_id text, p_model_release_hash text, p_configured_model text,
    p_execution_backend text, p_workflow_release_id uuid,
    p_workflow_release_hash text, p_runtime_manifest_id uuid,
    p_runtime_manifest_hash text, p_runtime_option_id uuid,
    p_runtime_option_hash text, p_search_mode text, p_prompt_bundle_hash text,
    p_structured_input_hash text, p_portable_output_schema_hash text,
    p_application_output_schema_hash text, p_task_artifact_uri text,
    p_task_artifact_hash text, p_deterministic_seed numeric,
    p_max_output_tokens integer, p_child_input_hash text
) RETURNS TABLE (
    child_job_id uuid, outbox_id uuid, durable_status text, replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    stored synthetic_lab_model_call_children%ROWTYPE;
BEGIN
    IF p_execution_backend NOT IN ('model_gateway', 'dify')
       OR (p_execution_backend = 'model_gateway' AND (
            p_workflow_release_id IS NOT NULL OR p_workflow_release_hash IS NOT NULL
       ))
       OR (p_execution_backend = 'dify' AND (
            p_workflow_release_id IS NULL
            OR coalesce(p_workflow_release_hash, '') !~ '^[0-9a-f]{64}$'
       )) THEN
        RAISE EXCEPTION 'Synthetic child backend parameters are invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM set_config(
        'geo.synthetic_child_execution_backend', p_execution_backend, true
    );
    PERFORM set_config(
        'geo.synthetic_child_workflow_release_id',
        coalesce(p_workflow_release_id::text, ''), true
    );
    PERFORM set_config(
        'geo.synthetic_child_workflow_release_hash',
        coalesce(p_workflow_release_hash, ''), true
    );
    RETURN QUERY SELECT * FROM geo_enqueue_synthetic_model_call_child_v1(
        p_project_id, p_parent_job_id, p_parent_lease_token,
        p_parent_fencing_generation, p_child_job_id, p_parent_job_kind,
        p_parent_task_input_hash, p_step_key, p_model_job_version,
        p_fact_snapshot_id, p_fact_snapshot_hash, p_profile_version_id,
        p_profile_hash, p_runtime_prompt_release_id,
        p_runtime_prompt_release_hash, p_prompt_binding_id,
        p_prompt_binding_version, p_prompt_frozen_state_id,
        p_prompt_frozen_state_version, p_prompt_release_id,
        p_prompt_release_version, p_prompt_release_hash,
        p_prompt_program_kind, p_prompt_purpose, p_admitted_by,
        p_prompt_model_policy_hash, p_provider, p_adapter_release_id,
        p_adapter_release_hash, p_model_release_id, p_model_release_hash,
        p_configured_model, p_runtime_manifest_id, p_runtime_manifest_hash,
        p_runtime_option_id, p_runtime_option_hash, p_search_mode,
        p_prompt_bundle_hash, p_structured_input_hash,
        p_portable_output_schema_hash, p_application_output_schema_hash,
        p_task_artifact_uri, p_task_artifact_hash, p_deterministic_seed,
        p_max_output_tokens, p_child_input_hash
    );
    PERFORM set_config('geo.synthetic_child_execution_backend', '', true);
    PERFORM set_config('geo.synthetic_child_workflow_release_id', '', true);
    PERFORM set_config('geo.synthetic_child_workflow_release_hash', '', true);
    SELECT child.* INTO STRICT stored
    FROM synthetic_lab_model_call_children child
    WHERE child.project_id = p_project_id AND child.child_job_id = p_child_job_id;
    IF (stored.execution_backend, stored.workflow_release_id, stored.workflow_release_hash)
       IS DISTINCT FROM
       (p_execution_backend, p_workflow_release_id, p_workflow_release_hash) THEN
        RAISE EXCEPTION 'Synthetic child idempotency backend identity changed'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

-- The old signature remains callable during rolling deployment, but the
-- backend guard rejects a new native child once its purpose is bound to Dify.
CREATE FUNCTION geo_enqueue_synthetic_model_call_child(
    p_project_id uuid, p_parent_job_id uuid, p_parent_lease_token uuid,
    p_parent_fencing_generation bigint, p_child_job_id uuid,
    p_parent_job_kind text, p_parent_task_input_hash text, p_step_key text,
    p_model_job_version integer, p_fact_snapshot_id uuid,
    p_fact_snapshot_hash text, p_profile_version_id uuid, p_profile_hash text,
    p_runtime_prompt_release_id uuid, p_runtime_prompt_release_hash text,
    p_prompt_binding_id uuid, p_prompt_binding_version integer,
    p_prompt_frozen_state_id uuid, p_prompt_frozen_state_version integer,
    p_prompt_release_id uuid, p_prompt_release_version integer,
    p_prompt_release_hash text, p_prompt_program_kind text,
    p_prompt_purpose text, p_admitted_by uuid, p_prompt_model_policy_hash text,
    p_provider text, p_adapter_release_id text, p_adapter_release_hash text,
    p_model_release_id text, p_model_release_hash text, p_configured_model text,
    p_runtime_manifest_id uuid, p_runtime_manifest_hash text,
    p_runtime_option_id uuid, p_runtime_option_hash text, p_search_mode text,
    p_prompt_bundle_hash text, p_structured_input_hash text,
    p_portable_output_schema_hash text, p_application_output_schema_hash text,
    p_task_artifact_uri text, p_task_artifact_hash text,
    p_deterministic_seed numeric, p_max_output_tokens integer,
    p_child_input_hash text
) RETURNS TABLE (
    child_job_id uuid, outbox_id uuid, durable_status text, replayed boolean
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
    SELECT * FROM geo_enqueue_synthetic_model_call_child(
        p_project_id, p_parent_job_id, p_parent_lease_token,
        p_parent_fencing_generation, p_child_job_id, p_parent_job_kind,
        p_parent_task_input_hash, p_step_key, p_model_job_version,
        p_fact_snapshot_id, p_fact_snapshot_hash, p_profile_version_id,
        p_profile_hash, p_runtime_prompt_release_id,
        p_runtime_prompt_release_hash, p_prompt_binding_id,
        p_prompt_binding_version, p_prompt_frozen_state_id,
        p_prompt_frozen_state_version, p_prompt_release_id,
        p_prompt_release_version, p_prompt_release_hash,
        p_prompt_program_kind, p_prompt_purpose, p_admitted_by,
        p_prompt_model_policy_hash, p_provider, p_adapter_release_id,
        p_adapter_release_hash, p_model_release_id, p_model_release_hash,
        p_configured_model, 'model_gateway', NULL, NULL,
        p_runtime_manifest_id, p_runtime_manifest_hash, p_runtime_option_id,
        p_runtime_option_hash, p_search_mode, p_prompt_bundle_hash,
        p_structured_input_hash, p_portable_output_schema_hash,
        p_application_output_schema_hash, p_task_artifact_uri,
        p_task_artifact_hash, p_deterministic_seed, p_max_output_tokens,
        p_child_input_hash
    );
$$;

REVOKE ALL ON FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, text, uuid, text, uuid, text, uuid, text,
    text, text, text, text, text, text, text, numeric, integer, text
), geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, text, uuid, text, uuid, text, uuid, text,
    text, text, text, text, text, text, text, numeric, integer, text
), geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) TO geo_worker;

CREATE OR REPLACE FUNCTION geo_assert_synthetic_model_call_child_job_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    link synthetic_lab_model_call_children%ROWTYPE;
    parent_job durable_jobs%ROWTYPE;
    successful_attempt uuid;
BEGIN
    IF OLD.kind <> 'synthetic.model.call' AND NEW.kind <> 'synthetic.model.call' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT link FROM synthetic_lab_model_call_children
    WHERE child_job_id = OLD.id AND project_id = OLD.project_id;
    IF (NEW.id, NEW.project_id, NEW.kind, NEW.input_hash,
        NEW.idempotency_key, NEW.parent_job_id, NEW.replay_nonce,
        NEW.campaign_id, NEW.max_attempts)
       IS DISTINCT FROM
       (OLD.id, OLD.project_id, OLD.kind, OLD.input_hash,
        OLD.idempotency_key, OLD.parent_job_id, OLD.replay_nonce,
        OLD.campaign_id, OLD.max_attempts) THEN
        RAISE EXCEPTION 'Synthetic model child immutable Durable Job identity changed'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.attempt_count = 0 AND NEW.status = 'running' THEN
        IF NEW.attempt_count <> 1 THEN
            RAISE EXCEPTION 'Synthetic model child first claim has an invalid attempt counter'
                USING ERRCODE = '40001';
        END IF;
        SELECT * INTO STRICT parent_job FROM durable_jobs
        WHERE id = link.parent_job_id AND project_id = link.project_id FOR SHARE;
        IF parent_job.cancel_requested_at IS NOT NULL
           OR NOT ((parent_job.status IN ('running', 'finalizing')
                    AND parent_job.lease_expires_at > clock_timestamp())
                OR (parent_job.status = 'retry_wait'
                    AND parent_job.error_code = 'synthetic_child_pending')) THEN
            RAISE EXCEPTION 'Synthetic model child cannot start after its parent was blocked'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    IF NEW.status = 'succeeded' AND OLD.status IS DISTINCT FROM 'succeeded' THEN
        IF link.execution_backend = 'model_gateway' THEN
            SELECT attempt.id INTO successful_attempt
            FROM model_gateway_call_attempts attempt
            JOIN model_gateway_terminal_events terminal
              ON terminal.attempt_id = attempt.id
             AND terminal.project_id = attempt.project_id
             AND terminal.job_id = attempt.job_id
            WHERE attempt.project_id = NEW.project_id AND attempt.job_id = NEW.id
              AND terminal.status = 'succeeded'
            ORDER BY attempt.attempt_number DESC LIMIT 1;
            IF successful_attempt IS NULL OR NEW.result_ref IS DISTINCT FROM
               'model-gateway://attempt/' || successful_attempt::text THEN
                RAISE EXCEPTION 'native Synthetic child success lacks its exact Model Gateway result'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF link.execution_backend = 'dify' THEN
            SELECT attempt.id INTO successful_attempt
            FROM dify_workflow_execution_attempts attempt
            JOIN dify_workflow_execution_results result
              ON result.attempt_id = attempt.id
             AND result.project_id = attempt.project_id
             AND result.job_id = attempt.job_id
            JOIN dify_workflow_release_snapshot_pins pin
              ON pin.project_id = attempt.project_id
             AND pin.release_id = attempt.release_id
             AND pin.published_snapshot_id = attempt.published_snapshot_id
            WHERE attempt.project_id = NEW.project_id AND attempt.job_id = NEW.id
              AND attempt.release_id = link.workflow_release_id
              AND attempt.execution_kind = 'business'
              AND attempt.status = 'succeeded'
            ORDER BY attempt.attempt_number DESC LIMIT 1;
            IF successful_attempt IS NULL OR NEW.result_ref IS DISTINCT FROM
               'dify-workflow://attempt/' || successful_attempt::text THEN
                RAISE EXCEPTION 'Dify Synthetic child success lacks its exact pinned Workflow result'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'Synthetic child success has an unsupported frozen backend'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP VIEW synthetic_lab_model_call_child_status;
CREATE VIEW synthetic_lab_model_call_child_status
WITH (security_barrier = true, security_invoker = true) AS
SELECT child.project_id, child.child_job_id, child.parent_job_id,
       child.parent_job_kind, child.parent_task_input_hash, child.step_key,
       child.step_key_hash, child.model_job_version, child.prompt_binding_id,
       child.prompt_binding_version, child.prompt_frozen_state_id,
       child.prompt_state_version, child.prompt_release_id,
       child.prompt_release_version, child.prompt_release_hash,
       child.prompt_program_kind, child.prompt_purpose, child.admitted_by,
       child.prompt_bundle_hash, child.structured_input_hash,
       child.portable_output_schema_hash, child.application_output_schema_hash,
       child.runtime_manifest_id, child.runtime_manifest_hash,
       child.runtime_option_id, child.runtime_option_hash,
       child.configured_model AS frozen_configured_model,
       child.execution_backend, child.backend_lineage_source,
       child.workflow_release_id,
       child.workflow_release_hash, child.task_artifact_uri,
       child.task_artifact_hash, child.child_input_hash,
       durable.status AS durable_status,
       CASE WHEN durable.status = 'succeeded' THEN 'succeeded'
            WHEN durable.status = 'cancelled' THEN 'cancelled'
            WHEN durable.error_code IN ('model_unknown_outcome', 'dify_unknown_outcome')
                THEN 'unknown_outcome'
            WHEN durable.status IN ('failed', 'dead_lettered') THEN 'failed'
            WHEN durable.status IN ('running', 'finalizing') THEN 'running'
            ELSE 'queued' END AS status,
       durable.attempt_count AS durable_attempt_count,
       durable.fencing_generation AS durable_fencing_generation,
       durable.cancel_requested_at,
       coalesce(
           durable.error_code,
           CASE WHEN child.execution_backend = 'dify'
                THEN dify.error_code ELSE native.error_code END
       ) AS failure_code,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.attempt_id END AS model_attempt_id,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.attempt_number END AS model_attempt_number,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.terminal_status END AS model_terminal_status,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.gateway_call_log_id END AS gateway_call_log_id,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_id END AS workflow_attempt_id,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_number END AS workflow_attempt_number,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_status END AS workflow_attempt_status,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.output_hash ELSE native.output_hash END AS output_hash,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.response_hash ELSE native.response_hash END AS response_hash,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.configured_model ELSE native.configured_model
            END AS model_configured_model,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.provider_reported_model ELSE native.provider_reported_model
            END AS model_reported_model,
       CASE WHEN child.execution_backend = 'dify' THEN dify.output END AS dify_output,
       CASE WHEN child.execution_backend = 'dify' THEN dify.release_id END
            AS dify_release_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.release_hash END
            AS dify_release_hash,
       CASE WHEN child.execution_backend = 'dify' THEN dify.prompt_release_id END
            AS dify_prompt_release_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.prompt_release_hash END
            AS dify_prompt_release_hash,
       CASE WHEN child.execution_backend = 'dify' THEN dify.purpose END
            AS dify_purpose,
       CASE WHEN child.execution_backend = 'dify' THEN dify.published_snapshot_id END
            AS published_snapshot_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.snapshot_hash END
            AS published_snapshot_hash,
       child.created_at
FROM synthetic_lab_model_call_children child
JOIN durable_jobs durable
  ON durable.id = child.child_job_id AND durable.project_id = child.project_id
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id, attempt.attempt_number,
           terminal.status AS terminal_status, terminal.error_code,
           terminal.gateway_call_log_id, terminal.output_hash,
           terminal.response_hash, terminal.configured_model,
           terminal.provider_reported_model
    FROM model_gateway_call_attempts attempt
    LEFT JOIN model_gateway_terminal_events terminal
      ON terminal.attempt_id = attempt.id AND terminal.project_id = attempt.project_id
     AND terminal.job_id = attempt.job_id
    WHERE child.execution_backend = 'model_gateway'
      AND attempt.project_id = child.project_id
      AND attempt.job_id = child.child_job_id
    ORDER BY attempt.attempt_number DESC LIMIT 1
) native ON true
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id, attempt.attempt_number,
           attempt.status AS attempt_status, attempt.error_code,
           result.output, result.response_hash AS output_hash,
           result.response_hash, result.configured_model,
           result.provider_reported_model, release.id AS release_id,
           release.release_hash, release.prompt_release_id,
           release.prompt_release_hash, release.purpose,
           attempt.published_snapshot_id, snapshot.snapshot_hash
    FROM dify_workflow_execution_attempts attempt
    JOIN dify_workflow_releases release
      ON release.id = attempt.release_id AND release.project_id = attempt.project_id
     AND release.release_hash = child.workflow_release_hash
    LEFT JOIN dify_workflow_execution_results result
      ON result.attempt_id = attempt.id AND result.project_id = attempt.project_id
     AND result.job_id = attempt.job_id
    LEFT JOIN dify_workflow_published_snapshots snapshot
      ON snapshot.id = attempt.published_snapshot_id
     AND snapshot.project_id = attempt.project_id
     AND snapshot.release_id = attempt.release_id
    WHERE child.execution_backend = 'dify'
      AND attempt.project_id = child.project_id
      AND attempt.job_id = child.child_job_id
      AND attempt.release_id = child.workflow_release_id
    ORDER BY attempt.attempt_number DESC LIMIT 1
) dify ON true;
REVOKE ALL ON synthetic_lab_model_call_child_status
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON synthetic_lab_model_call_child_status TO geo_app, geo_worker;
COMMENT ON VIEW synthetic_lab_model_call_child_status IS
    'Admin/worker status projection over the frozen native or exact pinned Dify child backend; lineage source distinguishes historical backfill from runtime admission and backend-specific IDs are never aliased.';
