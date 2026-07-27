CREATE TABLE dify_workflow_releases (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    purpose text NOT NULL CHECK (purpose IN (
        'knowledge.question_generation',
        'knowledge.rag_grounding',
        'placements.generation',
        'placements.simulation'
    )),
    version integer NOT NULL CHECK (version > 0),
    prompt_program_id uuid NOT NULL,
    prompt_release_id uuid NOT NULL,
    prompt_release_hash text NOT NULL CHECK (prompt_release_hash ~ '^[0-9a-f]{64}$'),
    dify_app_id text NOT NULL CHECK (btrim(dify_app_id) <> ''),
    dify_workflow_id text NOT NULL CHECK (btrim(dify_workflow_id) <> ''),
    dsl_hash text NOT NULL CHECK (dsl_hash ~ '^[0-9a-f]{64}$'),
    context_contract_version text NOT NULL CHECK (btrim(context_contract_version) <> ''),
    input_schema jsonb NOT NULL CHECK (jsonb_typeof(input_schema) = 'object'),
    input_schema_hash text NOT NULL CHECK (input_schema_hash ~ '^[0-9a-f]{64}$'),
    output_schema jsonb NOT NULL CHECK (jsonb_typeof(output_schema) = 'object'),
    output_schema_hash text NOT NULL CHECK (output_schema_hash ~ '^[0-9a-f]{64}$'),
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    model_provider text NOT NULL CHECK (btrim(model_provider) <> ''),
    api_secret_reference_id uuid NOT NULL,
    api_secret_purpose text NOT NULL CHECK (api_secret_purpose = 'workflow_runtime.dify'),
    api_secret_version integer NOT NULL CHECK (api_secret_version > 0),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT dify_workflow_releases_project_key UNIQUE (id, project_id),
    CONSTRAINT dify_workflow_releases_version_key UNIQUE (project_id, purpose, version),
    CONSTRAINT dify_workflow_releases_hash_key UNIQUE (project_id, purpose, release_hash),
    CONSTRAINT dify_workflow_releases_program_fkey FOREIGN KEY (
        prompt_program_id, project_id
    ) REFERENCES prompt_programs(id, project_id),
    CONSTRAINT dify_workflow_releases_prompt_release_fkey FOREIGN KEY (
        prompt_release_id, project_id
    ) REFERENCES prompt_program_releases(id, project_id),
    CONSTRAINT dify_workflow_releases_secret_fkey FOREIGN KEY (
        api_secret_reference_id, project_id, api_secret_purpose, api_secret_version
    ) REFERENCES secret_versions(reference_id, project_id, purpose, version)
);

CREATE INDEX dify_workflow_releases_prompt_idx
ON dify_workflow_releases(project_id, prompt_program_id, prompt_release_id);
CREATE INDEX dify_workflow_releases_secret_idx
ON dify_workflow_releases(api_secret_reference_id, api_secret_version);

CREATE TABLE dify_workflow_bindings (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    purpose text NOT NULL,
    release_id uuid NOT NULL,
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    binding_version integer NOT NULL CHECK (binding_version > 0),
    previous_binding_id uuid,
    activated_by uuid NOT NULL REFERENCES identities(id),
    activated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    CONSTRAINT dify_workflow_bindings_project_key UNIQUE (id, project_id),
    CONSTRAINT dify_workflow_bindings_version_key UNIQUE (
        project_id, purpose, binding_version
    ),
    CONSTRAINT dify_workflow_bindings_release_fkey FOREIGN KEY (
        release_id, project_id
    ) REFERENCES dify_workflow_releases(id, project_id),
    CONSTRAINT dify_workflow_bindings_previous_fkey FOREIGN KEY (
        previous_binding_id, project_id
    ) REFERENCES dify_workflow_bindings(id, project_id)
);

CREATE INDEX dify_workflow_bindings_current_idx
ON dify_workflow_bindings(project_id, purpose, binding_version DESC);
CREATE INDEX dify_workflow_bindings_release_idx
ON dify_workflow_bindings(project_id, release_id);

CREATE TABLE dify_workflow_execution_attempts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    release_id uuid NOT NULL,
    job_id uuid,
    execution_kind text NOT NULL CHECK (execution_kind IN ('business', 'canary')),
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    fencing_generation integer,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    context_hash text NOT NULL CHECK (context_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    dify_task_id text,
    dify_run_id text,
    reported_workflow_id text,
    output_hash text CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    prompt_tokens integer CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
    completion_tokens integer CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
    total_steps integer CHECK (total_steps IS NULL OR total_steps >= 0),
    elapsed_seconds numeric CHECK (elapsed_seconds IS NULL OR elapsed_seconds >= 0),
    http_status integer CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
    error_classification text CHECK (error_classification IS NULL OR error_classification IN (
        'retryable', 'authentication', 'configuration', 'contract', 'provider', 'cancelled'
    )),
    error_code text,
    error_message text,
    retryable boolean,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    CONSTRAINT dify_workflow_attempts_release_fkey FOREIGN KEY (
        release_id, project_id
    ) REFERENCES dify_workflow_releases(id, project_id),
    CONSTRAINT dify_workflow_attempts_job_fkey FOREIGN KEY (
        job_id, project_id
    ) REFERENCES durable_jobs(id, project_id),
    CONSTRAINT dify_workflow_attempts_job_shape CHECK (
        (execution_kind = 'business' AND job_id IS NOT NULL AND fencing_generation IS NOT NULL)
        OR (execution_kind = 'canary' AND job_id IS NULL AND fencing_generation IS NULL)
    ),
    CONSTRAINT dify_workflow_attempts_terminal_shape CHECK (
        (status = 'running' AND finished_at IS NULL AND output_hash IS NULL
            AND error_classification IS NULL AND retryable IS NULL)
        OR (status = 'succeeded' AND finished_at IS NOT NULL AND output_hash IS NOT NULL
            AND dify_run_id IS NOT NULL AND error_classification IS NULL
            AND retryable = false)
        OR (status = 'failed' AND finished_at IS NOT NULL AND output_hash IS NULL
            AND error_classification IS NOT NULL AND error_code IS NOT NULL
            AND retryable IS NOT NULL)
    )
);

CREATE UNIQUE INDEX dify_workflow_attempts_business_number_key
ON dify_workflow_execution_attempts(project_id, job_id, attempt_number)
WHERE job_id IS NOT NULL;
CREATE INDEX dify_workflow_attempts_release_status_idx
ON dify_workflow_execution_attempts(project_id, release_id, status, started_at DESC);
CREATE INDEX dify_workflow_attempts_job_idx
ON dify_workflow_execution_attempts(project_id, job_id, started_at DESC)
WHERE job_id IS NOT NULL;
CREATE UNIQUE INDEX dify_workflow_attempts_run_key
ON dify_workflow_execution_attempts(release_id, dify_run_id)
WHERE dify_run_id IS NOT NULL;

CREATE FUNCTION geo_reject_dify_runtime_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Dify runtime releases and bindings are append-only'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER dify_workflow_releases_immutable
BEFORE UPDATE OR DELETE ON dify_workflow_releases
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_runtime_mutation();
CREATE TRIGGER dify_workflow_bindings_immutable
BEFORE UPDATE OR DELETE ON dify_workflow_bindings
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_runtime_mutation();

CREATE FUNCTION geo_assert_dify_binding_append() RETURNS trigger
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

CREATE TRIGGER dify_workflow_binding_append_guard
BEFORE INSERT ON dify_workflow_bindings
FOR EACH ROW EXECUTE FUNCTION geo_assert_dify_binding_append();

CREATE FUNCTION geo_assert_dify_attempt_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'running' OR NEW.status NOT IN ('succeeded', 'failed')
       OR NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id
       OR NEW.release_id <> OLD.release_id OR NEW.job_id IS DISTINCT FROM OLD.job_id
       OR NEW.execution_kind <> OLD.execution_kind
       OR NEW.attempt_number <> OLD.attempt_number
       OR NEW.fencing_generation IS DISTINCT FROM OLD.fencing_generation
       OR NEW.context_hash <> OLD.context_hash OR NEW.request_hash <> OLD.request_hash
       OR NEW.started_at <> OLD.started_at THEN
        RAISE EXCEPTION 'Dify attempt permits only one running-to-terminal transition'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER dify_workflow_attempt_transition_guard
BEFORE UPDATE ON dify_workflow_execution_attempts
FOR EACH ROW EXECUTE FUNCTION geo_assert_dify_attempt_transition();

CREATE FUNCTION geo_reject_dify_attempt_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Dify execution attempts cannot be deleted'
        USING ERRCODE = '55000';
END;
$$;
CREATE TRIGGER dify_workflow_attempt_delete_guard
BEFORE DELETE ON dify_workflow_execution_attempts
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_attempt_delete();

ALTER TABLE dify_workflow_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_releases FORCE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_execution_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_execution_attempts FORCE ROW LEVEL SECURITY;

CREATE POLICY project_scope ON dify_workflow_releases
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
CREATE POLICY project_scope ON dify_workflow_bindings
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
CREATE POLICY project_scope ON dify_workflow_execution_attempts
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON dify_workflow_releases, dify_workflow_bindings,
    dify_workflow_execution_attempts FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON dify_workflow_releases, dify_workflow_bindings TO geo_app;
GRANT SELECT ON dify_workflow_execution_attempts TO geo_app;
GRANT SELECT ON dify_workflow_releases, dify_workflow_bindings TO geo_worker;
GRANT SELECT, INSERT, UPDATE ON dify_workflow_execution_attempts TO geo_worker;
GRANT EXECUTE ON FUNCTION geo_assert_dify_binding_append() TO geo_app;
GRANT EXECUTE ON FUNCTION geo_assert_dify_attempt_transition() TO geo_worker;
