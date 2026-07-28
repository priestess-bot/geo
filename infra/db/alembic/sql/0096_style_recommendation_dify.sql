ALTER TABLE dify_workflow_published_snapshots
DROP CONSTRAINT dify_workflow_published_snapshots_purpose_check;
ALTER TABLE dify_workflow_published_snapshots
ADD CONSTRAINT dify_workflow_published_snapshots_purpose_check CHECK (purpose IN (
    'knowledge.question_generation', 'knowledge.rag_grounding',
    'placements.generation', 'placements.simulation',
    'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
    'synthetic_lab.conflict_check', 'synthetic_lab.revision',
    'synthetic_lab.style_profile', 'recommendations.recommendation'
));
ALTER TABLE dify_workflow_releases
DROP CONSTRAINT dify_workflow_releases_purpose_check;
ALTER TABLE dify_workflow_releases
ADD CONSTRAINT dify_workflow_releases_purpose_check CHECK (purpose IN (
    'knowledge.question_generation', 'knowledge.rag_grounding',
    'placements.generation', 'placements.simulation',
    'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
    'synthetic_lab.conflict_check', 'synthetic_lab.revision',
    'synthetic_lab.style_profile', 'recommendations.recommendation'
));

ALTER TABLE dify_workflow_releases
ADD CONSTRAINT dify_workflow_releases_frozen_identity_key
UNIQUE (id, project_id, release_hash);

ALTER TABLE recommendation_model_tasks
ADD COLUMN execution_backend text NOT NULL DEFAULT 'model_gateway' CHECK (
    execution_backend IN ('model_gateway', 'dify')
),
ADD COLUMN workflow_release_id uuid,
ADD COLUMN workflow_release_hash text CHECK (
    workflow_release_hash IS NULL OR workflow_release_hash ~ '^[0-9a-f]{64}$'
),
ADD CONSTRAINT recommendation_model_tasks_workflow_release_fkey FOREIGN KEY (
    workflow_release_id, project_id, workflow_release_hash
) REFERENCES dify_workflow_releases(id, project_id, release_hash),
ADD CONSTRAINT recommendation_model_tasks_backend_shape_check CHECK (
    (execution_backend = 'model_gateway'
        AND workflow_release_id IS NULL AND workflow_release_hash IS NULL)
    OR (execution_backend = 'dify' AND role = 'primary'
        AND workflow_release_id IS NOT NULL AND workflow_release_hash IS NOT NULL)
);

ALTER TABLE recommendation_model_call_lineage
ADD COLUMN execution_backend text NOT NULL DEFAULT 'model_gateway' CHECK (
    execution_backend IN ('model_gateway', 'dify')
),
ADD COLUMN dify_attempt_id uuid,
ADD CONSTRAINT recommendation_model_lineage_dify_result_fkey FOREIGN KEY (
    dify_attempt_id, project_id
) REFERENCES dify_workflow_execution_results(attempt_id, project_id);

DO $$
DECLARE success_constraint text;
BEGIN
    SELECT constraint_name INTO STRICT success_constraint
    FROM information_schema.check_constraints
    WHERE constraint_schema = current_schema()
      AND constraint_name IN (
          SELECT conname FROM pg_constraint
          WHERE conrelid = 'recommendation_model_call_lineage'::regclass
            AND contype = 'c'
            AND pg_get_constraintdef(oid) LIKE '%model_attempt_id IS NOT NULL%'
            AND pg_get_constraintdef(oid) LIKE '%status = ''succeeded''%'
      );
    EXECUTE format(
        'ALTER TABLE recommendation_model_call_lineage DROP CONSTRAINT %I',
        success_constraint
    );
END;
$$;

ALTER TABLE recommendation_model_call_lineage
ADD CONSTRAINT recommendation_model_call_lineage_success_check CHECK (
    (status = 'succeeded' AND
        response_hash ~ '^[0-9a-f]{64}$' AND output_hash ~ '^[0-9a-f]{64}$'
        AND (
            (execution_backend = 'model_gateway'
                AND model_attempt_id IS NOT NULL AND model_call_log_id IS NOT NULL
                AND derived_artifact_uri ~ '^s3://[^/]+/.+'
                AND derived_artifact_manifest_hash ~ '^[0-9a-f]{64}$'
                AND derived_artifact_content_hash ~ '^[0-9a-f]{64}$'
                AND dify_attempt_id IS NULL)
            OR (execution_backend = 'dify' AND dify_attempt_id IS NOT NULL
                AND model_attempt_id IS NULL AND model_call_log_id IS NULL
                AND artifact_uri IS NULL AND artifact_manifest_hash IS NULL
                AND artifact_content_hash IS NULL
                AND derived_artifact_uri IS NULL
                AND derived_artifact_manifest_hash IS NULL
                AND derived_artifact_content_hash IS NULL)
        )
    )
    OR (status <> 'succeeded'
        AND model_attempt_id IS NULL AND model_call_log_id IS NULL
        AND dify_attempt_id IS NULL
        AND response_hash IS NULL AND output_hash IS NULL
        AND artifact_uri IS NULL AND artifact_manifest_hash IS NULL
        AND artifact_content_hash IS NULL
        AND derived_artifact_uri IS NULL
        AND derived_artifact_manifest_hash IS NULL
        AND derived_artifact_content_hash IS NULL)
);
ALTER TABLE recommendation_model_call_lineage
ADD CONSTRAINT recommendation_model_call_lineage_backend_shape_check CHECK (
    (execution_backend = 'model_gateway' AND dify_attempt_id IS NULL)
    OR (execution_backend = 'dify'
        AND model_attempt_id IS NULL AND model_call_log_id IS NULL
        AND artifact_uri IS NULL AND artifact_manifest_hash IS NULL
        AND artifact_content_hash IS NULL
        AND derived_artifact_uri IS NULL
        AND derived_artifact_manifest_hash IS NULL
        AND derived_artifact_content_hash IS NULL)
);

CREATE OR REPLACE FUNCTION geo_assert_dify_binding_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous_version integer;
    selected_purpose text;
    selected_hash text;
    selected_program_kind text;
BEGIN
    SELECT purpose, release_hash INTO STRICT selected_purpose, selected_hash
    FROM dify_workflow_releases
    WHERE id = NEW.release_id AND project_id = NEW.project_id;
    IF NEW.purpose <> selected_purpose OR NEW.release_hash <> selected_hash THEN
        RAISE EXCEPTION 'Dify binding release identity does not match'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.purpose IN (
        'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
        'synthetic_lab.conflict_check', 'synthetic_lab.revision',
        'synthetic_lab.style_profile'
    ) THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'dify-binding:' || NEW.project_id::text || ':' || NEW.purpose, 0
        ));
        selected_program_kind := CASE NEW.purpose
            WHEN 'synthetic_lab.generation' THEN 'generation'
            WHEN 'synthetic_lab.claim_extraction' THEN 'claim_extraction'
            WHEN 'synthetic_lab.conflict_check' THEN 'conflict_check'
            WHEN 'synthetic_lab.revision' THEN 'revision'
            WHEN 'synthetic_lab.style_profile' THEN 'style_profile'
        END;
        IF EXISTS (
            SELECT 1
            FROM synthetic_lab_model_call_children child
            JOIN durable_jobs job
              ON job.id = child.child_job_id AND job.project_id = child.project_id
            WHERE child.project_id = NEW.project_id
              AND child.prompt_program_kind = selected_program_kind
              AND job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
        ) THEN
            RAISE EXCEPTION 'drain non-terminal Synthetic child Jobs before changing the Dify binding for %', NEW.purpose
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF NEW.binding_version = 1 THEN
        IF NEW.previous_binding_id IS NOT NULL THEN
            RAISE EXCEPTION 'first Dify binding cannot have a predecessor'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT binding_version INTO STRICT previous_version
        FROM dify_workflow_bindings
        WHERE id = NEW.previous_binding_id AND project_id = NEW.project_id
          AND purpose = NEW.purpose;
        IF NEW.binding_version <> previous_version + 1 THEN
            RAISE EXCEPTION 'Dify binding version is not contiguous'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM dify_workflow_execution_attempts attempt
        WHERE attempt.project_id = NEW.project_id
          AND attempt.release_id = NEW.release_id
          AND attempt.execution_kind = 'canary'
          AND attempt.status = 'succeeded'
    ) THEN
        RAISE EXCEPTION 'Dify release requires a successful canary before activation'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.purpose = 'synthetic_lab.style_profile' AND (
        EXISTS (
            SELECT 1 FROM durable_jobs job
            WHERE job.project_id = NEW.project_id
              AND job.kind = 'style.profile.build'
              AND job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
        ) OR EXISTS (
            SELECT 1
            FROM synthetic_lab_model_call_children child
            JOIN durable_jobs job
              ON job.id = child.child_job_id AND job.project_id = child.project_id
            WHERE child.project_id = NEW.project_id
              AND child.prompt_program_kind = 'style_profile'
              AND job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
        )
    ) THEN
        RAISE EXCEPTION 'pause Style Profile admission and drain non-terminal profile Jobs before activating Dify'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_lock_synthetic_dify_child_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.prompt_purpose IN (
        'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
        'synthetic_lab.conflict_check', 'synthetic_lab.revision',
        'synthetic_lab.style_profile'
    ) THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'dify-binding:' || NEW.project_id::text || ':' || NEW.prompt_purpose, 0
        ));
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_lock_synthetic_dify_child_binding() FROM PUBLIC;
CREATE TRIGGER synthetic_dify_child_binding_lock
BEFORE INSERT ON synthetic_lab_model_call_children
FOR EACH ROW EXECUTE FUNCTION geo_lock_synthetic_dify_child_binding();

CREATE OR REPLACE FUNCTION geo_assert_recommendation_model_task_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation model task lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF (NEW.role = 'primary' AND NEW.prompt_purpose <> 'recommendations.recommendation')
           OR (NEW.role = 'arbiter' AND NEW.prompt_purpose <> 'synthetic_lab.arbiter')
           OR NEW.runtime_selection_id <> NEW.runtime_option_id
           OR NEW.task_artifact_expires_at <= NEW.created_at
           OR NEW.task_artifact_status <> 'uploading'
           OR (NEW.role = 'arbiter' AND NEW.execution_backend <> 'model_gateway')
           OR (NEW.execution_backend = 'dify' AND NOT EXISTS (
                SELECT 1 FROM dify_workflow_releases release
                WHERE release.id = NEW.workflow_release_id
                  AND release.project_id = NEW.project_id
                  AND release.release_hash = NEW.workflow_release_hash
                  AND release.purpose = NEW.prompt_purpose
                  AND release.prompt_release_id = NEW.prompt_release_id
                  AND release.prompt_release_hash = NEW.prompt_release_hash
                  AND release.configured_model = NEW.configured_model
           )) THEN
            RAISE EXCEPTION 'Recommendation model task frozen lineage is invalid'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'task_artifact_uri', 'task_artifact_manifest_hash',
        'task_artifact_payload_uri', 'task_artifact_content_hash',
        'task_artifact_byte_size', 'task_artifact_status', 'task_payload_hash'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'task_artifact_uri', 'task_artifact_manifest_hash',
        'task_artifact_payload_uri', 'task_artifact_content_hash',
        'task_artifact_byte_size', 'task_artifact_status', 'task_payload_hash'
    ];
    IF old_fixed <> new_fixed THEN
        RAISE EXCEPTION 'Recommendation model task frozen lineage is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.task_artifact_status = 'uploading' AND NEW.task_artifact_status = 'active'
       OR OLD.task_artifact_status = 'active' AND NEW.task_artifact_status = 'deletion_pending'
       OR OLD.task_artifact_status = 'deletion_pending' AND NEW.task_artifact_status = 'crypto_erased'
       OR OLD.task_artifact_status = 'crypto_erased' AND NEW.task_artifact_status = 'deleted' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Recommendation model task artifact lifecycle transition is invalid'
        USING ERRCODE = '23514';
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_recommendation_model_lineage_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
DECLARE old_outcome jsonb;
DECLARE new_outcome jsonb;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.task_artifact_status <> 'active'
           OR NOT EXISTS (
                SELECT 1 FROM recommendation_model_tasks task
                WHERE task.project_id = NEW.project_id
                  AND task.child_job_id = NEW.child_job_id
                  AND task.parent_job_id = NEW.parent_job_id
                  AND task.role = NEW.role
                  AND task.execution_backend = NEW.execution_backend
                  AND task.task_artifact_status = 'active'
           ) THEN
            RAISE EXCEPTION 'Recommendation model lineage requires its frozen active task'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation model result lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'model_attempt_id', 'model_call_log_id', 'dify_attempt_id',
        'response_hash', 'output_hash', 'artifact_uri', 'artifact_manifest_hash',
        'artifact_content_hash', 'derived_artifact_uri',
        'derived_artifact_manifest_hash', 'derived_artifact_content_hash',
        'task_artifact_status', 'status', 'error_code', 'updated_at'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'model_attempt_id', 'model_call_log_id', 'dify_attempt_id',
        'response_hash', 'output_hash', 'artifact_uri', 'artifact_manifest_hash',
        'artifact_content_hash', 'derived_artifact_uri',
        'derived_artifact_manifest_hash', 'derived_artifact_content_hash',
        'task_artifact_status', 'status', 'error_code', 'updated_at'
    ];
    IF old_fixed <> new_fixed OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'Recommendation model result immutable lineage changed'
            USING ERRCODE = '23514';
    END IF;
    IF NOT (
        NEW.task_artifact_status = OLD.task_artifact_status
        OR (OLD.task_artifact_status = 'active'
            AND NEW.task_artifact_status = 'deletion_pending')
        OR (OLD.task_artifact_status = 'deletion_pending'
            AND NEW.task_artifact_status = 'crypto_erased')
        OR (OLD.task_artifact_status = 'crypto_erased'
            AND NEW.task_artifact_status = 'deleted')
    ) THEN
        RAISE EXCEPTION 'Recommendation model result artifact lifecycle is invalid'
            USING ERRCODE = '23514';
    END IF;
    old_outcome := jsonb_build_object(
        'status', OLD.status, 'error_code', OLD.error_code,
        'model_attempt_id', OLD.model_attempt_id,
        'model_call_log_id', OLD.model_call_log_id,
        'dify_attempt_id', OLD.dify_attempt_id,
        'response_hash', OLD.response_hash, 'output_hash', OLD.output_hash,
        'artifact_uri', OLD.artifact_uri,
        'artifact_manifest_hash', OLD.artifact_manifest_hash,
        'artifact_content_hash', OLD.artifact_content_hash,
        'derived_artifact_uri', OLD.derived_artifact_uri,
        'derived_artifact_manifest_hash', OLD.derived_artifact_manifest_hash,
        'derived_artifact_content_hash', OLD.derived_artifact_content_hash
    );
    new_outcome := jsonb_build_object(
        'status', NEW.status, 'error_code', NEW.error_code,
        'model_attempt_id', NEW.model_attempt_id,
        'model_call_log_id', NEW.model_call_log_id,
        'dify_attempt_id', NEW.dify_attempt_id,
        'response_hash', NEW.response_hash, 'output_hash', NEW.output_hash,
        'artifact_uri', NEW.artifact_uri,
        'artifact_manifest_hash', NEW.artifact_manifest_hash,
        'artifact_content_hash', NEW.artifact_content_hash,
        'derived_artifact_uri', NEW.derived_artifact_uri,
        'derived_artifact_manifest_hash', NEW.derived_artifact_manifest_hash,
        'derived_artifact_content_hash', NEW.derived_artifact_content_hash
    );
    IF OLD.status IN ('succeeded', 'failed', 'dead_lettered', 'cancelled') THEN
        IF old_outcome <> new_outcome THEN
            RAISE EXCEPTION 'Recommendation terminal model result cannot be rewritten'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT (
        (OLD.status = 'queued' AND NEW.status IN (
            'running', 'retry_wait', 'succeeded', 'failed', 'dead_lettered', 'cancelled'
        ))
        OR (OLD.status IN ('running', 'retry_wait') AND NEW.status IN (
            'running', 'retry_wait', 'succeeded', 'failed', 'dead_lettered', 'cancelled'
        ))
        OR (OLD.status = 'queued' AND NEW.status = 'queued'
            AND OLD.task_artifact_status <> NEW.task_artifact_status
            AND old_outcome = new_outcome)
    ) THEN
        RAISE EXCEPTION 'Recommendation model result status transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'succeeded' AND NEW.execution_backend = 'dify' AND NOT EXISTS (
        SELECT 1
        FROM dify_workflow_execution_attempts attempt
        JOIN dify_workflow_execution_results result
          ON result.attempt_id = attempt.id AND result.project_id = attempt.project_id
         AND result.job_id = attempt.job_id
        JOIN dify_workflow_releases release
          ON release.id = attempt.release_id AND release.project_id = attempt.project_id
        JOIN recommendation_model_tasks task
          ON task.project_id = NEW.project_id AND task.child_job_id = NEW.child_job_id
         AND task.workflow_release_id = release.id
         AND task.workflow_release_hash = release.release_hash
         AND task.prompt_release_id = release.prompt_release_id
         AND task.prompt_release_hash = release.prompt_release_hash
         AND task.configured_model = release.configured_model
        WHERE attempt.id = NEW.dify_attempt_id
          AND attempt.project_id = NEW.project_id
          AND attempt.job_id = NEW.child_job_id
          AND attempt.execution_kind = 'business' AND attempt.status = 'succeeded'
          AND result.response_hash = NEW.response_hash
          AND result.configured_model = task.configured_model
    ) THEN
        RAISE EXCEPTION 'Recommendation Dify success lacks its frozen governed result'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'succeeded'
       AND NEW.execution_backend = 'model_gateway' AND NOT EXISTS (
        SELECT 1
        FROM model_gateway_call_attempts attempt
        JOIN model_gateway_terminal_events terminal
          ON terminal.attempt_id = attempt.id
         AND terminal.project_id = attempt.project_id
         AND terminal.job_id = attempt.job_id
        JOIN model_gateway_job_admissions admission
          ON admission.project_id = attempt.project_id
         AND admission.job_id = attempt.job_id
        JOIN recommendation_model_tasks task
          ON task.project_id = NEW.project_id
         AND task.child_job_id = NEW.child_job_id
         AND task.execution_backend = 'model_gateway'
         AND task.prompt_release_id = admission.prompt_release_id
         AND task.prompt_release_hash = admission.prompt_release_hash
         AND task.provider = admission.provider
         AND task.adapter_release_id = admission.adapter_release_id
         AND task.adapter_release_hash = admission.adapter_release_hash
         AND task.model_release_id = admission.model_release_id
         AND task.model_release_hash = admission.model_release_hash
        JOIN model_gateway_artifact_bundles bundle
          ON bundle.project_id = attempt.project_id
         AND bundle.job_id = attempt.job_id
         AND bundle.attempt_id = attempt.id
         AND bundle.status = 'committed'
        JOIN model_gateway_artifacts artifact
          ON artifact.project_id = bundle.project_id
         AND artifact.bundle_id = bundle.id
         AND artifact.kind = 'derived'
        WHERE attempt.id = NEW.model_attempt_id
          AND attempt.project_id = NEW.project_id
          AND attempt.job_id = NEW.child_job_id
          AND terminal.status = 'succeeded'
          AND terminal.gateway_call_log_id = NEW.model_call_log_id
          AND terminal.response_hash = NEW.response_hash
          AND terminal.output_hash = NEW.output_hash
          AND terminal.configured_model = task.configured_model
          AND artifact.manifest_uri = NEW.derived_artifact_uri
          AND artifact.manifest_hash = NEW.derived_artifact_manifest_hash
          AND artifact.content_hash = NEW.derived_artifact_content_hash
    ) THEN
        RAISE EXCEPTION 'Recommendation native success lacks its frozen governed result'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_reserve_recommendation_model_task(
    p_project_id uuid, p_parent_job_id uuid, p_parent_lease_token uuid,
    p_parent_fence bigint, p_child_job_id uuid, p_parent_input_hash text,
    p_role text, p_execution_backend text, p_workflow_release_id uuid,
    p_workflow_release_hash text, p_runtime_selection_id uuid,
    p_runtime_manifest_id uuid, p_runtime_manifest_hash text,
    p_runtime_option_id uuid, p_runtime_option_hash text,
    p_prompt_binding_id uuid, p_prompt_binding_version integer,
    p_prompt_frozen_state_id uuid, p_prompt_state_version integer,
    p_prompt_release_id uuid, p_prompt_release_version integer,
    p_prompt_release_hash text, p_prompt_purpose text, p_provider text,
    p_adapter_release_id text, p_adapter_release_hash text,
    p_model_release_id text, p_model_release_hash text, p_configured_model text,
    p_capture_method text, p_search_mode text, p_prompt_bundle_hash text,
    p_structured_input_hash text, p_output_schema_hash text,
    p_application_output_schema_hash text, p_artifact_expires_at timestamptz,
    p_admitted_by uuid, p_created_at timestamptz
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE existing recommendation_model_tasks%ROWTYPE;
BEGIN
    PERFORM geo_assert_recommendation_generation_lease(
        p_project_id, p_parent_job_id, p_parent_lease_token, p_parent_fence, p_created_at
    );
    IF p_artifact_expires_at IS NULL OR p_created_at IS NULL
       OR p_artifact_expires_at <= p_created_at THEN
        RAISE EXCEPTION 'Recommendation model task artifact expiry is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM recommendation_model_tasks
    WHERE project_id = p_project_id
      AND (child_job_id = p_child_job_id
           OR (parent_job_id = p_parent_job_id AND role = p_role))
    LIMIT 1 FOR SHARE;
    IF FOUND THEN
        IF (existing.parent_job_id, existing.child_job_id, existing.parent_input_hash,
            existing.role, existing.execution_backend, existing.workflow_release_id,
            existing.workflow_release_hash, existing.runtime_selection_id,
            existing.runtime_manifest_id, existing.runtime_manifest_hash,
            existing.runtime_option_id, existing.runtime_option_hash,
            existing.prompt_binding_id, existing.prompt_binding_version,
            existing.prompt_frozen_state_id, existing.prompt_state_version,
            existing.prompt_release_id, existing.prompt_release_version,
            existing.prompt_release_hash, existing.prompt_purpose, existing.provider,
            existing.adapter_release_id, existing.adapter_release_hash,
            existing.model_release_id, existing.model_release_hash,
            existing.configured_model, existing.capture_method, existing.search_mode,
            existing.prompt_bundle_hash, existing.structured_input_hash,
            existing.output_schema_hash, existing.application_output_schema_hash,
            existing.task_artifact_expires_at, existing.admitted_by)
           IS DISTINCT FROM
           (p_parent_job_id, p_child_job_id, p_parent_input_hash, p_role,
            p_execution_backend, p_workflow_release_id, p_workflow_release_hash,
            p_runtime_selection_id, p_runtime_manifest_id, p_runtime_manifest_hash,
            p_runtime_option_id, p_runtime_option_hash, p_prompt_binding_id,
            p_prompt_binding_version, p_prompt_frozen_state_id, p_prompt_state_version,
            p_prompt_release_id, p_prompt_release_version, p_prompt_release_hash,
            p_prompt_purpose, p_provider, p_adapter_release_id,
            p_adapter_release_hash, p_model_release_id, p_model_release_hash,
            p_configured_model, p_capture_method, p_search_mode,
            p_prompt_bundle_hash, p_structured_input_hash, p_output_schema_hash,
            p_application_output_schema_hash, p_artifact_expires_at, p_admitted_by) THEN
            RAISE EXCEPTION 'Recommendation model task reservation replay changed identity'
                USING ERRCODE = '40001';
        END IF;
        RETURN;
    END IF;
    INSERT INTO recommendation_model_tasks(
        project_id, parent_job_id, child_job_id, parent_input_hash, role,
        execution_backend, workflow_release_id, workflow_release_hash,
        runtime_selection_id, runtime_manifest_id, runtime_manifest_hash,
        runtime_option_id, runtime_option_hash, prompt_binding_id,
        prompt_binding_version, prompt_frozen_state_id, prompt_state_version,
        prompt_release_id, prompt_release_version, prompt_release_hash,
        prompt_purpose, provider, adapter_release_id, adapter_release_hash,
        model_release_id, model_release_hash, configured_model, capture_method,
        search_mode, prompt_bundle_hash, structured_input_hash, output_schema_hash,
        application_output_schema_hash, task_artifact_expires_at,
        task_artifact_status, admitted_by, created_at
    ) VALUES (
        p_project_id, p_parent_job_id, p_child_job_id, p_parent_input_hash, p_role,
        p_execution_backend, p_workflow_release_id, p_workflow_release_hash,
        p_runtime_selection_id, p_runtime_manifest_id, p_runtime_manifest_hash,
        p_runtime_option_id, p_runtime_option_hash, p_prompt_binding_id,
        p_prompt_binding_version, p_prompt_frozen_state_id, p_prompt_state_version,
        p_prompt_release_id, p_prompt_release_version, p_prompt_release_hash,
        p_prompt_purpose, p_provider, p_adapter_release_id, p_adapter_release_hash,
        p_model_release_id, p_model_release_hash, p_configured_model, p_capture_method,
        p_search_mode, p_prompt_bundle_hash, p_structured_input_hash,
        p_output_schema_hash, p_application_output_schema_hash,
        p_artifact_expires_at, 'uploading', p_admitted_by, p_created_at
    );
END;
$$;

CREATE FUNCTION geo_activate_recommendation_model_task(
    p_project_id uuid, p_parent_job_id uuid, p_parent_lease_token uuid,
    p_parent_fence bigint, p_child_job_id uuid, p_execution_backend text,
    p_artifact_uri text, p_artifact_manifest_hash text,
    p_artifact_payload_uri text, p_artifact_payload_hash text,
    p_artifact_content_hash text, p_artifact_byte_size bigint,
    p_activated_at timestamptz
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE task recommendation_model_tasks%ROWTYPE;
DECLARE parent_job durable_jobs%ROWTYPE;
DECLARE outbox_id uuid := gen_random_uuid();
DECLARE child_kind text;
DECLARE child_key text;
BEGIN
    PERFORM geo_assert_recommendation_generation_lease(
        p_project_id, p_parent_job_id, p_parent_lease_token, p_parent_fence, p_activated_at
    );
    SELECT * INTO STRICT task FROM recommendation_model_tasks
    WHERE project_id = p_project_id AND parent_job_id = p_parent_job_id
      AND child_job_id = p_child_job_id FOR UPDATE;
    IF task.execution_backend <> p_execution_backend THEN
        RAISE EXCEPTION 'Recommendation task activation changed its frozen backend'
            USING ERRCODE = '40001';
    END IF;
    IF task.task_artifact_status = 'active' THEN
        IF (task.task_artifact_uri, task.task_artifact_manifest_hash,
            task.task_artifact_payload_uri, task.task_payload_hash,
            task.task_artifact_content_hash, task.task_artifact_byte_size)
           IS DISTINCT FROM
           (p_artifact_uri, p_artifact_manifest_hash, p_artifact_payload_uri,
            p_artifact_payload_hash, p_artifact_content_hash, p_artifact_byte_size) THEN
            RAISE EXCEPTION 'Recommendation task activation replay changed artifact identity'
                USING ERRCODE = '40001';
        END IF;
        RETURN;
    END IF;
    IF task.task_artifact_status <> 'uploading' THEN
        RAISE EXCEPTION 'Recommendation task is not awaiting artifact activation'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO STRICT parent_job FROM durable_jobs
    WHERE id = p_parent_job_id AND project_id = p_project_id;
    child_kind := CASE task.role WHEN 'primary' THEN 'recommendation.model.primary'
                                 WHEN 'arbiter' THEN 'recommendation.model.arbiter' END;
    child_key := 'recommendation-model:' || p_parent_job_id::text || ':' || task.role;
    INSERT INTO durable_jobs(
        id, project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, fencing_generation, parent_job_id, replay_nonce,
        campaign_id, created_at, updated_at
    ) VALUES (
        p_child_job_id, p_project_id, child_kind, 'queued', parent_job.priority,
        task.structured_input_hash, child_key, 3, p_activated_at, 0,
        p_parent_job_id, 0, parent_job.campaign_id, p_activated_at, p_activated_at
    ) ON CONFLICT (id) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1 FROM durable_jobs WHERE id = p_child_job_id
          AND project_id = p_project_id AND kind = child_kind
          AND parent_job_id = p_parent_job_id
          AND input_hash = task.structured_input_hash AND idempotency_key = child_key
    ) THEN
        RAISE EXCEPTION 'Recommendation task child durable Job identity changed'
            USING ERRCODE = '40001';
    END IF;
    UPDATE recommendation_model_tasks
    SET task_artifact_uri = p_artifact_uri,
        task_artifact_manifest_hash = p_artifact_manifest_hash,
        task_artifact_payload_uri = p_artifact_payload_uri,
        task_payload_hash = p_artifact_payload_hash,
        task_artifact_content_hash = p_artifact_content_hash,
        task_artifact_byte_size = p_artifact_byte_size,
        task_artifact_status = 'active'
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id;
    INSERT INTO recommendation_model_call_lineage(
        project_id, parent_job_id, child_job_id, role, execution_backend,
        task_artifact_status, task_artifact_expires_at, status, created_at, updated_at
    ) VALUES (
        p_project_id, p_parent_job_id, p_child_job_id, task.role,
        task.execution_backend, 'active', task.task_artifact_expires_at,
        'queued', p_activated_at, p_activated_at
    ) ON CONFLICT (project_id, child_job_id) DO NOTHING;
    INSERT INTO broker_outbox(
        id, project_id, job_id, topic, payload, idempotency_key, available_at, created_at
    ) VALUES (
        outbox_id, p_project_id, p_child_job_id, child_kind,
        jsonb_build_object('project_id', p_project_id::text,
                           'job_id', p_child_job_id::text,
                           'event_type', child_kind,
                           'payload_hash', task.structured_input_hash),
        child_key, p_activated_at, p_activated_at
    ) ON CONFLICT (project_id, idempotency_key) DO NOTHING;
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    ) VALUES (
        p_project_id, p_child_job_id, 'job_enqueued',
        'recommendation-task-activate', 0,
        jsonb_build_object('parent_job_id', p_parent_job_id::text,
                           'role', task.role,
                           'execution_backend', task.execution_backend),
        p_activated_at
    );
END;
$$;

ALTER FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
RENAME TO geo_resolve_recommendation_evidence_pre_0096;
REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence_pre_0096(uuid, text, text)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

CREATE FUNCTION geo_resolve_recommendation_evidence(
    p_project_id uuid, p_kind text, p_resource_id text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE resolved jsonb;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RETURN NULL;
    END IF;
    IF p_kind = 'model_call' THEN
        SELECT jsonb_build_object(
            'kind', 'model_call', 'project_id', attempt.project_id::text,
            'resource_id', result.attempt_id::text,
            'version', release.id::text, 'sha256', result.response_hash,
            'locator', jsonb_build_object(
                'dify_workflow_attempt_id', result.attempt_id::text
            ),
            'valid', true,
            'prompt_release_resource_id', release.prompt_release_id::text,
            'model_identity', concat_ws('/', 'dify', 'dify-workflow-api-v1',
                                        release.id::text, result.configured_model),
            'succeeded', true, 'summary', NULL
        ) INTO resolved
        FROM recommendation_model_call_lineage lineage
        JOIN recommendation_model_tasks task
          ON task.project_id = lineage.project_id
         AND task.child_job_id = lineage.child_job_id
         AND task.parent_job_id = lineage.parent_job_id
         AND task.role = lineage.role
         AND task.execution_backend = 'dify'
        JOIN dify_workflow_execution_attempts attempt
          ON attempt.id = lineage.dify_attempt_id
         AND attempt.project_id = lineage.project_id
         AND attempt.job_id = lineage.child_job_id
         AND attempt.release_id = task.workflow_release_id
        JOIN dify_workflow_execution_results result
          ON result.attempt_id = attempt.id AND result.project_id = attempt.project_id
         AND result.job_id = attempt.job_id
        JOIN dify_workflow_releases release
          ON release.id = attempt.release_id AND release.project_id = attempt.project_id
         AND release.release_hash = task.workflow_release_hash
         AND release.prompt_release_id = task.prompt_release_id
         AND release.prompt_release_hash = task.prompt_release_hash
         AND release.configured_model = task.configured_model
        WHERE attempt.project_id = p_project_id AND attempt.id::text = p_resource_id
          AND attempt.execution_kind = 'business' AND attempt.status = 'succeeded'
          AND lineage.status = 'succeeded'
          AND lineage.execution_backend = 'dify'
          AND lineage.response_hash = result.response_hash
          AND result.configured_model = task.configured_model
          AND task.prompt_purpose = 'recommendations.recommendation'
          AND release.purpose = task.prompt_purpose;
        IF resolved IS NOT NULL THEN
            RETURN resolved;
        END IF;

        SELECT jsonb_build_object(
            'kind', 'model_call', 'project_id', attempt.project_id::text,
            'resource_id', terminal.gateway_call_log_id::text,
            'version', coalesce(admission.model_release_id, terminal.configured_model),
            'sha256', terminal.response_hash,
            'locator', jsonb_build_object(
                'call_log_id', terminal.gateway_call_log_id::text
            ),
            'valid', terminal.status = 'succeeded',
            'prompt_release_resource_id', admission.prompt_release_id::text,
            'model_identity', concat_ws('/', admission.provider,
                admission.adapter_release_id, admission.model_release_id,
                terminal.configured_model),
            'succeeded', terminal.status = 'succeeded', 'summary', NULL
        ) INTO resolved
        FROM recommendation_model_call_lineage lineage
        JOIN recommendation_model_tasks task
          ON task.project_id = lineage.project_id
         AND task.child_job_id = lineage.child_job_id
         AND task.parent_job_id = lineage.parent_job_id
         AND task.role = lineage.role
         AND task.execution_backend = 'model_gateway'
        JOIN model_gateway_call_attempts attempt
          ON attempt.id = lineage.model_attempt_id
         AND attempt.project_id = lineage.project_id
         AND attempt.job_id = lineage.child_job_id
        JOIN model_gateway_terminal_events terminal
          ON terminal.attempt_id = attempt.id AND terminal.project_id = attempt.project_id
         AND terminal.job_id = attempt.job_id
        JOIN model_gateway_job_admissions admission
          ON admission.project_id = attempt.project_id AND admission.job_id = attempt.job_id
        WHERE attempt.project_id = p_project_id
          AND terminal.gateway_call_log_id::text = p_resource_id
          AND terminal.status = 'succeeded'
          AND lineage.status = 'succeeded'
          AND lineage.execution_backend = 'model_gateway'
          AND lineage.model_call_log_id = terminal.gateway_call_log_id
          AND lineage.response_hash = terminal.response_hash
          AND admission.prompt_release_id = task.prompt_release_id
          AND admission.prompt_release_hash = task.prompt_release_hash
          AND admission.provider = task.provider
          AND admission.adapter_release_id = task.adapter_release_id
          AND admission.adapter_release_hash = task.adapter_release_hash
          AND admission.model_release_id = task.model_release_id
          AND admission.model_release_hash = task.model_release_hash
          AND terminal.configured_model = task.configured_model;
        RETURN resolved;
    END IF;
    RETURN geo_resolve_recommendation_evidence_pre_0096(
        p_project_id, p_kind, p_resource_id
    );
END;
$$;

REVOKE ALL ON FUNCTION
    geo_reserve_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, uuid, uuid, text,
        uuid, text, uuid, integer, uuid, integer, uuid, integer,
        text, text, text, text, text, text, text,
        text, text, text, text, text, text, text,
        timestamptz, uuid, timestamptz
    ),
    geo_activate_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, bigint, timestamptz
    )
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION
    geo_reserve_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, text, uuid, text,
        uuid, uuid, text, uuid, text, uuid, integer, uuid, integer,
        uuid, integer, text, text, text, text, text, text, text, text,
        text, text, text, text, text, text, timestamptz, uuid, timestamptz
    ),
    geo_activate_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, text, bigint,
        timestamptz
    ),
    geo_resolve_recommendation_evidence(uuid, text, text)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_reserve_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, text, uuid, text,
        uuid, uuid, text, uuid, text, uuid, integer, uuid, integer,
        uuid, integer, text, text, text, text, text, text, text, text,
        text, text, text, text, text, text, timestamptz, uuid, timestamptz
    ),
    geo_activate_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, text, bigint,
        timestamptz
    )
TO geo_worker;
GRANT EXECUTE ON FUNCTION
    geo_reserve_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, uuid, uuid, text,
        uuid, text, uuid, integer, uuid, integer, uuid, integer,
        text, text, text, text, text, text, text,
        text, text, text, text, text, text, text,
        timestamptz, uuid, timestamptz
    ),
    geo_activate_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, bigint,
        timestamptz
    )
TO geo_worker;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
TO geo_app, geo_worker;

GRANT UPDATE (dify_attempt_id)
ON recommendation_model_call_lineage TO geo_worker;

COMMENT ON COLUMN recommendation_model_tasks.execution_backend IS
    'Frozen at child enqueue; legacy task artifacts remain model_gateway and cannot switch on retry.';
COMMENT ON COLUMN recommendation_model_tasks.workflow_release_id IS
    'Exact Dify Workflow Release selected before encrypted task artifact creation.';
