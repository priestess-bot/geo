DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM dify_workflow_releases
        WHERE purpose IN ('synthetic_lab.style_profile', 'recommendations.recommendation')
    ) OR EXISTS (
        SELECT 1 FROM recommendation_model_tasks WHERE execution_backend = 'dify'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade while Style Profile or Recommendation Dify lineage exists';
    END IF;
END;
$$;

DROP FUNCTION geo_resolve_recommendation_evidence(uuid, text, text);
ALTER FUNCTION geo_resolve_recommendation_evidence_pre_0096(uuid, text, text)
RENAME TO geo_resolve_recommendation_evidence;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
TO geo_app, geo_worker;

DROP TRIGGER synthetic_dify_child_binding_lock
ON synthetic_lab_model_call_children;
DROP FUNCTION geo_lock_synthetic_dify_child_binding();

CREATE OR REPLACE FUNCTION geo_assert_dify_binding_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous_version integer;
    selected_purpose text;
    selected_hash text;
BEGIN
    SELECT purpose, release_hash INTO STRICT selected_purpose, selected_hash
    FROM dify_workflow_releases
    WHERE id = NEW.release_id AND project_id = NEW.project_id;
    IF NEW.purpose <> selected_purpose OR NEW.release_hash <> selected_hash THEN
        RAISE EXCEPTION 'Dify binding release identity does not match'
            USING ERRCODE = '23514';
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
    RETURN NEW;
END;
$$;

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
    )
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_reserve_recommendation_model_task(
    uuid, uuid, uuid, bigint, uuid, text, text, text, uuid, text,
    uuid, uuid, text, uuid, text, uuid, integer, uuid, integer,
    uuid, integer, text, text, text, text, text, text, text, text,
    text, text, text, text, text, text, timestamptz, uuid, timestamptz
);
DROP FUNCTION geo_activate_recommendation_model_task(
    uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, text, bigint,
    timestamptz
);

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
           OR NEW.task_artifact_status <> 'uploading' THEN
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
    IF OLD.task_artifact_status = 'uploading'
       AND NEW.task_artifact_status = 'active' THEN
        RETURN NEW;
    END IF;
    IF OLD.task_artifact_status = 'active'
       AND NEW.task_artifact_status = 'deletion_pending' THEN
        RETURN NEW;
    END IF;
    IF OLD.task_artifact_status = 'deletion_pending'
       AND NEW.task_artifact_status = 'crypto_erased' THEN
        RETURN NEW;
    END IF;
    IF OLD.task_artifact_status = 'crypto_erased'
       AND NEW.task_artifact_status = 'deleted' THEN
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
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.task_artifact_status <> 'active'
           OR NOT EXISTS (
                SELECT 1 FROM recommendation_model_tasks AS task
                WHERE task.project_id = NEW.project_id
                  AND task.child_job_id = NEW.child_job_id
                  AND task.parent_job_id = NEW.parent_job_id
                  AND task.role = NEW.role
                  AND task.task_artifact_status = 'active'
           ) THEN
            RAISE EXCEPTION 'Recommendation model lineage requires an active task artifact'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation model result lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'model_attempt_id', 'model_call_log_id', 'response_hash', 'output_hash',
        'artifact_uri', 'artifact_manifest_hash', 'artifact_content_hash',
        'derived_artifact_uri', 'derived_artifact_manifest_hash',
        'derived_artifact_content_hash', 'task_artifact_status', 'status',
        'error_code', 'updated_at'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'model_attempt_id', 'model_call_log_id', 'response_hash', 'output_hash',
        'artifact_uri', 'artifact_manifest_hash', 'artifact_content_hash',
        'derived_artifact_uri', 'derived_artifact_manifest_hash',
        'derived_artifact_content_hash', 'task_artifact_status', 'status',
        'error_code', 'updated_at'
    ];
    IF old_fixed <> new_fixed OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'Recommendation model result immutable lineage changed'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE recommendation_model_call_lineage
DROP CONSTRAINT recommendation_model_call_lineage_success_check;
ALTER TABLE recommendation_model_call_lineage
DROP CONSTRAINT recommendation_model_call_lineage_backend_shape_check;
ALTER TABLE recommendation_model_call_lineage
ADD CONSTRAINT recommendation_model_call_lineage_check CHECK (
    (status = 'succeeded') = (
        model_attempt_id IS NOT NULL AND model_call_log_id IS NOT NULL
        AND response_hash ~ '^[0-9a-f]{64}$' AND output_hash ~ '^[0-9a-f]{64}$'
        AND derived_artifact_uri ~ '^s3://[^/]+/.+'
        AND derived_artifact_manifest_hash ~ '^[0-9a-f]{64}$'
        AND derived_artifact_content_hash ~ '^[0-9a-f]{64}$'
    )
);
ALTER TABLE recommendation_model_call_lineage
DROP CONSTRAINT recommendation_model_lineage_dify_result_fkey,
DROP COLUMN dify_attempt_id,
DROP COLUMN execution_backend;

ALTER TABLE recommendation_model_tasks
DROP CONSTRAINT recommendation_model_tasks_backend_shape_check,
DROP CONSTRAINT recommendation_model_tasks_workflow_release_fkey,
DROP COLUMN workflow_release_hash,
DROP COLUMN workflow_release_id,
DROP COLUMN execution_backend;

ALTER TABLE dify_workflow_releases
DROP CONSTRAINT dify_workflow_releases_frozen_identity_key;

ALTER TABLE dify_workflow_published_snapshots
DROP CONSTRAINT dify_workflow_published_snapshots_purpose_check;
ALTER TABLE dify_workflow_published_snapshots
ADD CONSTRAINT dify_workflow_published_snapshots_purpose_check CHECK (purpose IN (
    'knowledge.question_generation', 'knowledge.rag_grounding',
    'placements.generation', 'placements.simulation',
    'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
    'synthetic_lab.conflict_check', 'synthetic_lab.revision'
));
ALTER TABLE dify_workflow_releases
DROP CONSTRAINT dify_workflow_releases_purpose_check;
ALTER TABLE dify_workflow_releases
ADD CONSTRAINT dify_workflow_releases_purpose_check CHECK (purpose IN (
    'knowledge.question_generation', 'knowledge.rag_grounding',
    'placements.generation', 'placements.simulation',
    'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
    'synthetic_lab.conflict_check', 'synthetic_lab.revision'
));

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
