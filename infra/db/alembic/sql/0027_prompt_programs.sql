CREATE TABLE prompt_programs (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    program_kind text NOT NULL CHECK (program_kind IN (
        'generation', 'claim_extraction', 'conflict_check', 'revision',
        'style_judge', 'arbiter', 'metric_judge', 'recommendation',
        'reference_translation', 'style_profile', 'offline_answer'
    )),
    purpose text NOT NULL CHECK (btrim(purpose) <> ''),
    owner_id uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT prompt_programs_project_key UNIQUE (id, project_id),
    CONSTRAINT prompt_programs_binding_key UNIQUE (
        id, project_id, program_kind, purpose
    ),
    CONSTRAINT prompt_programs_exact_identity_key UNIQUE (
        id, project_id, program_kind, purpose, owner_id
    )
);

CREATE TABLE prompt_program_releases (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    program_id uuid NOT NULL,
    program_kind text NOT NULL,
    purpose text NOT NULL CHECK (btrim(purpose) <> ''),
    version integer NOT NULL CHECK (version > 0),
    owner_id uuid NOT NULL REFERENCES identities(id),
    system_template text NOT NULL CHECK (btrim(system_template) <> ''),
    user_template text NOT NULL CHECK (btrim(user_template) <> ''),
    variable_schema_version text NOT NULL CHECK (btrim(variable_schema_version) <> ''),
    variable_schema jsonb NOT NULL CHECK (jsonb_typeof(variable_schema) = 'object'),
    input_schema_version text NOT NULL CHECK (btrim(input_schema_version) <> ''),
    input_schema jsonb NOT NULL CHECK (jsonb_typeof(input_schema) = 'object'),
    output_schema_version text NOT NULL CHECK (btrim(output_schema_version) <> ''),
    output_schema jsonb NOT NULL CHECK (jsonb_typeof(output_schema) = 'object'),
    output_schema_hash text NOT NULL CHECK (output_schema_hash ~ '^[0-9a-f]{64}$'),
    application_output_schema_version text NOT NULL CHECK (
        btrim(application_output_schema_version) <> ''
    ),
    application_output_schema jsonb NOT NULL CHECK (
        jsonb_typeof(application_output_schema) = 'object'
    ),
    application_output_schema_hash text NOT NULL CHECK (
        application_output_schema_hash ~ '^[0-9a-f]{64}$'
    ),
    model_policy_version text NOT NULL CHECK (btrim(model_policy_version) <> ''),
    model_policy jsonb NOT NULL CHECK (jsonb_typeof(model_policy) = 'object'),
    model_policy_hash text NOT NULL CHECK (model_policy_hash ~ '^[0-9a-f]{64}$'),
    test_set_id uuid NOT NULL,
    test_set_version integer NOT NULL CHECK (test_set_version > 0),
    test_set_hash text NOT NULL CHECK (test_set_hash ~ '^[0-9a-f]{64}$'),
    compiler_version text NOT NULL CHECK (btrim(compiler_version) <> ''),
    system_template_hash text NOT NULL CHECK (system_template_hash ~ '^[0-9a-f]{64}$'),
    user_template_hash text NOT NULL CHECK (user_template_hash ~ '^[0-9a-f]{64}$'),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT prompt_program_releases_program_fkey FOREIGN KEY (
        program_id, project_id, program_kind, purpose, owner_id
    ) REFERENCES prompt_programs(id, project_id, program_kind, purpose, owner_id)
        ON DELETE CASCADE,
    CONSTRAINT prompt_program_releases_project_key UNIQUE (id, project_id),
    CONSTRAINT prompt_program_releases_hash_key UNIQUE (
        id, project_id, release_hash
    ),
    CONSTRAINT prompt_program_releases_exact_key UNIQUE (
        id, project_id, program_id, release_hash, version
    ),
    CONSTRAINT prompt_program_releases_test_set_key UNIQUE (
        id, project_id, release_hash, test_set_id, test_set_version
    ),
    CONSTRAINT prompt_program_releases_test_set_hash_key UNIQUE (
        id, project_id, release_hash, test_set_id, test_set_version, test_set_hash
    ),
    CONSTRAINT prompt_program_releases_version_key UNIQUE (program_id, version)
);

CREATE FUNCTION geo_jsonb_canonical_text(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT CASE jsonb_typeof(value)
        WHEN 'object' THEN coalesce((
            SELECT '{' || string_agg(
                to_jsonb(item.key)::text || ':' || geo_jsonb_canonical_text(item.value),
                ',' ORDER BY item.key
            ) || '}'
            FROM jsonb_each(value) AS item
        ), '{}')
        WHEN 'array' THEN coalesce((
            SELECT '[' || string_agg(
                geo_jsonb_canonical_text(item.value), ',' ORDER BY item.ordinality
            ) || ']'
            FROM jsonb_array_elements(value) WITH ORDINALITY AS item(value, ordinality)
        ), '[]')
        ELSE value::text
    END
$$;

CREATE TABLE prompt_program_release_states (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    release_id uuid NOT NULL,
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    version integer NOT NULL CHECK (version > 0),
    previous_state_id uuid,
    status text NOT NULL CHECK (status IN ('draft', 'tested', 'approved', 'frozen')),
    acted_by uuid NOT NULL REFERENCES identities(id),
    acted_at timestamptz NOT NULL,
    evidence_ref text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT prompt_program_release_states_evidence_shape CHECK (
        (status = 'draft' AND evidence_ref IS NULL)
        OR (status <> 'draft' AND evidence_ref IS NOT NULL
            AND btrim(evidence_ref) <> '')
    ),
    CONSTRAINT prompt_program_release_states_initial_shape CHECK (
        (version = 1 AND previous_state_id IS NULL AND status = 'draft')
        OR (version > 1 AND previous_state_id IS NOT NULL AND status <> 'draft')
    ),
    CONSTRAINT prompt_program_release_states_release_fkey FOREIGN KEY (
        release_id, project_id, release_hash
    ) REFERENCES prompt_program_releases(id, project_id, release_hash)
        ON DELETE CASCADE,
    CONSTRAINT prompt_program_release_states_project_key UNIQUE (id, project_id),
    CONSTRAINT prompt_program_release_states_release_key UNIQUE (
        id, project_id, release_id, release_hash
    ),
    CONSTRAINT prompt_program_release_states_exact_key UNIQUE (
        id, project_id, release_id, release_hash, version
    ),
    CONSTRAINT prompt_program_release_states_version_key UNIQUE (release_id, version),
    CONSTRAINT prompt_program_release_states_successor_key UNIQUE (
        previous_state_id, project_id, release_id
    ),
    CONSTRAINT prompt_program_release_states_previous_fkey FOREIGN KEY (
        previous_state_id, project_id, release_id, release_hash
    ) REFERENCES prompt_program_release_states(id, project_id, release_id, release_hash)
        ON DELETE CASCADE
);

CREATE TABLE prompt_program_test_evidence (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    release_id uuid NOT NULL,
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    tested_state_id uuid NOT NULL,
    test_set_id uuid NOT NULL,
    test_set_version integer NOT NULL CHECK (test_set_version > 0),
    output_artifact_ref text NOT NULL CHECK (btrim(output_artifact_ref) <> ''),
    output_hash text NOT NULL CHECK (output_hash ~ '^[0-9a-f]{64}$'),
    tested_by uuid NOT NULL REFERENCES identities(id),
    tested_at timestamptz NOT NULL,
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT prompt_program_test_evidence_release_fkey FOREIGN KEY (
        release_id, project_id, release_hash, test_set_id, test_set_version
    ) REFERENCES prompt_program_releases(
        id, project_id, release_hash, test_set_id, test_set_version
    ) ON DELETE CASCADE,
    CONSTRAINT prompt_program_test_evidence_state_fkey FOREIGN KEY (
        tested_state_id, project_id, release_id, release_hash
    ) REFERENCES prompt_program_release_states(id, project_id, release_id, release_hash)
        ON DELETE CASCADE,
    CONSTRAINT prompt_program_test_evidence_state_key UNIQUE (
        tested_state_id, project_id
    ),
    CONSTRAINT prompt_program_test_evidence_project_key UNIQUE (id, project_id)
);

CREATE TABLE prompt_program_test_run_tasks (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    program_id uuid NOT NULL,
    release_id uuid NOT NULL,
    release_version integer NOT NULL CHECK (release_version > 0),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    expected_state_id uuid NOT NULL,
    expected_state_version integer NOT NULL CHECK (expected_state_version > 0),
    test_set_id uuid NOT NULL,
    test_set_version integer NOT NULL CHECK (test_set_version > 0),
    test_set_hash text NOT NULL CHECK (test_set_hash ~ '^[0-9a-f]{64}$'),
    spec_hash text NOT NULL CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    catalog_hash text NOT NULL CHECK (catalog_hash ~ '^[0-9a-f]{64}$'),
    requested_by uuid NOT NULL REFERENCES identities(id),
    requested_at timestamptz NOT NULL,
    task_payload jsonb NOT NULL CHECK (jsonb_typeof(task_payload) = 'object'),
    task_payload_hash text NOT NULL CHECK (task_payload_hash ~ '^[0-9a-f]{64}$'),
    expected_job_input_hash text NOT NULL CHECK (
        expected_job_input_hash ~ '^[0-9a-f]{64}$'
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, job_id),
    CONSTRAINT prompt_program_test_run_tasks_scope_key UNIQUE (job_id, project_id),
    CONSTRAINT prompt_program_test_run_tasks_job_fkey FOREIGN KEY (
        job_id, project_id
    ) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT prompt_program_test_run_tasks_release_fkey FOREIGN KEY (
        release_id, project_id, program_id, release_hash, release_version
    ) REFERENCES prompt_program_releases(
        id, project_id, program_id, release_hash, version
    ),
    CONSTRAINT prompt_program_test_run_tasks_state_fkey FOREIGN KEY (
        expected_state_id, project_id, release_id, release_hash, expected_state_version
    ) REFERENCES prompt_program_release_states(
        id, project_id, release_id, release_hash, version
    ),
    CONSTRAINT prompt_program_test_run_tasks_test_set_fkey FOREIGN KEY (
        release_id, project_id, release_hash,
        test_set_id, test_set_version, test_set_hash
    ) REFERENCES prompt_program_releases(
        id, project_id, release_hash,
        test_set_id, test_set_version, test_set_hash
    ),
    CONSTRAINT prompt_program_test_run_tasks_hash_identity CHECK (
        task_payload_hash = expected_job_input_hash
    ),
    CONSTRAINT prompt_program_test_run_tasks_time_order CHECK (
        requested_at <= created_at
    )
);

CREATE TABLE prompt_program_bindings (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    purpose text NOT NULL CHECK (btrim(purpose) <> ''),
    program_kind text NOT NULL,
    program_id uuid NOT NULL,
    release_id uuid NOT NULL,
    release_version integer NOT NULL CHECK (release_version > 0),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    frozen_state_id uuid NOT NULL,
    binding_version integer NOT NULL CHECK (binding_version > 0),
    previous_binding_id uuid,
    bound_by uuid NOT NULL REFERENCES identities(id),
    bound_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT prompt_program_bindings_initial_shape CHECK (
        (binding_version = 1 AND previous_binding_id IS NULL)
        OR (binding_version > 1 AND previous_binding_id IS NOT NULL)
    ),
    CONSTRAINT prompt_program_bindings_program_fkey FOREIGN KEY (
        program_id, project_id, program_kind, purpose
    ) REFERENCES prompt_programs(id, project_id, program_kind, purpose)
        ON DELETE CASCADE,
    CONSTRAINT prompt_program_bindings_release_fkey FOREIGN KEY (
        release_id, project_id, program_id, release_hash, release_version
    ) REFERENCES prompt_program_releases(
        id, project_id, program_id, release_hash, version
    ) ON DELETE CASCADE,
    CONSTRAINT prompt_program_bindings_state_fkey FOREIGN KEY (
        frozen_state_id, project_id, release_id, release_hash
    ) REFERENCES prompt_program_release_states(id, project_id, release_id, release_hash)
        ON DELETE CASCADE,
    CONSTRAINT prompt_program_bindings_project_key UNIQUE (id, project_id),
    CONSTRAINT prompt_program_bindings_previous_key UNIQUE (
        id, project_id, purpose
    ),
    CONSTRAINT prompt_program_bindings_exact_key UNIQUE (
        id, project_id, purpose, binding_version
    ),
    CONSTRAINT prompt_program_bindings_version_key UNIQUE (
        project_id, purpose, binding_version
    ),
    CONSTRAINT prompt_program_bindings_successor_key UNIQUE (
        previous_binding_id, project_id, purpose
    ),
    CONSTRAINT prompt_program_bindings_previous_fkey FOREIGN KEY (
        previous_binding_id, project_id, purpose
    ) REFERENCES prompt_program_bindings(id, project_id, purpose)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE prompt_program_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idempotency_key_hash text NOT NULL CHECK (
        idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    operation text NOT NULL CHECK (
        operation IN (
            'create', 'create_release', 'test', 'approve', 'freeze', 'bind', 'diff'
        )
    ),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    result_kind text NOT NULL CHECK (
        result_kind IN (
            'created', 'created_release', 'tested', 'transitioned', 'bound', 'diffed'
        )
    ),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, idempotency_key_hash),
    CONSTRAINT prompt_program_command_receipts_result_shape CHECK (
        (operation = 'create' AND result_kind = 'created')
        OR (operation = 'create_release' AND result_kind = 'created_release')
        OR (operation = 'test' AND result_kind = 'tested')
        OR (operation IN ('approve', 'freeze') AND result_kind = 'transitioned')
        OR (operation = 'bind' AND result_kind = 'bound')
        OR (operation = 'diff' AND result_kind = 'diffed')
    )
);

CREATE FUNCTION geo_assert_prompt_program_release_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_version integer;
BEGIN
    IF NEW.output_schema_hash <> encode(digest(convert_to(
            geo_jsonb_canonical_text(NEW.output_schema), 'UTF8'
        ), 'sha256'), 'hex')
       OR NEW.application_output_schema_hash <> encode(digest(convert_to(
            geo_jsonb_canonical_text(NEW.application_output_schema), 'UTF8'
        ), 'sha256'), 'hex') THEN
        RAISE EXCEPTION 'Prompt Program Release Schema hash is invalid'
            USING ERRCODE = '23514';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'prompt-program-release:' || NEW.project_id || ':' || NEW.program_id,
            0
        )
    );
    SELECT max(version) INTO current_version
    FROM prompt_program_releases
    WHERE project_id = NEW.project_id
      AND program_id = NEW.program_id;
    IF NEW.version <> coalesce(current_version, 0) + 1 THEN
        RAISE EXCEPTION 'Prompt Program Release version is not linear'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_prompt_program_state_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous_status text;
    previous_version integer;
    release_owner uuid;
BEGIN
    SELECT owner_id INTO STRICT release_owner
    FROM prompt_program_releases
    WHERE id = NEW.release_id
      AND project_id = NEW.project_id
      AND release_hash = NEW.release_hash;

    IF NEW.version = 1 THEN
        IF NEW.previous_state_id IS NOT NULL OR NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Prompt Program initial state must be draft'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    SELECT status, version INTO STRICT previous_status, previous_version
    FROM prompt_program_release_states
    WHERE id = NEW.previous_state_id
      AND project_id = NEW.project_id
      AND release_id = NEW.release_id
      AND release_hash = NEW.release_hash;

    IF NEW.version <> previous_version + 1
       OR NOT (
           (previous_status = 'draft' AND NEW.status = 'tested')
           OR (previous_status = 'tested' AND NEW.status = 'approved')
           OR (previous_status = 'approved' AND NEW.status = 'frozen')
       ) THEN
        RAISE EXCEPTION 'Prompt Program state transition is not linear'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'approved' AND NEW.acted_by = release_owner THEN
        RAISE EXCEPTION 'Prompt Program owner cannot approve own Release'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_prompt_program_binding_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    frozen_status text;
    previous_version integer;
BEGIN
    SELECT status INTO STRICT frozen_status
    FROM prompt_program_release_states
    WHERE id = NEW.frozen_state_id
      AND project_id = NEW.project_id
      AND release_id = NEW.release_id
      AND release_hash = NEW.release_hash;
    IF frozen_status <> 'frozen' THEN
        RAISE EXCEPTION 'Prompt Program binding requires a frozen Release state'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.binding_version = 1 THEN
        IF NEW.previous_binding_id IS NOT NULL THEN
            RAISE EXCEPTION 'Prompt Program initial binding cannot have a predecessor'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    SELECT binding_version INTO STRICT previous_version
    FROM prompt_program_bindings
    WHERE id = NEW.previous_binding_id
      AND project_id = NEW.project_id
      AND purpose = NEW.purpose;
    IF NEW.binding_version <> previous_version + 1 THEN
        RAISE EXCEPTION 'Prompt Program binding history is not linear'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_prompt_program_test_run_task() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    durable record;
    release_record record;
    state_record record;
BEGIN
    SELECT kind, status, input_hash INTO STRICT durable
    FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id;
    IF durable.kind <> 'prompt.test.execute'
       OR durable.status <> 'queued'
       OR durable.input_hash <> NEW.expected_job_input_hash
       OR NEW.task_payload_hash <> encode(
            digest(convert_to(geo_jsonb_canonical_text(NEW.task_payload), 'UTF8'), 'sha256'),
            'hex'
       ) THEN
        RAISE EXCEPTION 'Prompt test task does not match its queued Durable Job'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT release_record
    FROM prompt_program_releases
    WHERE id = NEW.release_id AND project_id = NEW.project_id
      AND program_id = NEW.program_id AND version = NEW.release_version
      AND release_hash = NEW.release_hash;
    IF release_record.test_set_id <> NEW.test_set_id
       OR release_record.test_set_version <> NEW.test_set_version
       OR release_record.test_set_hash <> NEW.test_set_hash THEN
        RAISE EXCEPTION 'Prompt test task changed frozen test-set lineage'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT state_record
    FROM prompt_program_release_states
    WHERE id = NEW.expected_state_id AND project_id = NEW.project_id
      AND release_id = NEW.release_id AND release_hash = NEW.release_hash
      AND version = NEW.expected_state_version;
    IF state_record.status <> 'draft'
       OR EXISTS (
            SELECT 1 FROM prompt_program_release_states newer
            WHERE newer.project_id = NEW.project_id
              AND newer.release_id = NEW.release_id
              AND newer.version > NEW.expected_state_version
       ) THEN
        RAISE EXCEPTION 'Prompt test task requires the current draft state'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.task_payload ->> 'project_id') IS DISTINCT FROM NEW.project_id::text
       OR (NEW.task_payload ->> 'job_id') IS DISTINCT FROM NEW.job_id::text
       OR (NEW.task_payload ->> 'program_id') IS DISTINCT FROM NEW.program_id::text
       OR (NEW.task_payload ->> 'release_id') IS DISTINCT FROM NEW.release_id::text
       OR (NEW.task_payload ->> 'release_version')::integer
            IS DISTINCT FROM NEW.release_version
       OR (NEW.task_payload ->> 'release_hash') IS DISTINCT FROM NEW.release_hash
       OR (NEW.task_payload ->> 'expected_state_id')
            IS DISTINCT FROM NEW.expected_state_id::text
       OR (NEW.task_payload ->> 'expected_state_version')::integer
            IS DISTINCT FROM NEW.expected_state_version
       OR (NEW.task_payload ->> 'test_set_id') IS DISTINCT FROM NEW.test_set_id::text
       OR (NEW.task_payload ->> 'test_set_version')::integer
            IS DISTINCT FROM NEW.test_set_version
       OR (NEW.task_payload ->> 'test_set_hash') IS DISTINCT FROM NEW.test_set_hash
       OR (NEW.task_payload ->> 'spec_hash') IS DISTINCT FROM NEW.spec_hash
       OR (NEW.task_payload ->> 'catalog_hash') IS DISTINCT FROM NEW.catalog_hash THEN
        RAISE EXCEPTION 'Prompt test task payload changed frozen identity'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_prompt_program_state_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous record;
    evidence record;
    release_record record;
BEGIN
    IF NEW.status = 'draft' THEN
        RETURN NULL;
    END IF;
    IF NEW.status = 'tested' THEN
        SELECT * INTO STRICT release_record
        FROM prompt_program_releases
        WHERE id = NEW.release_id
          AND project_id = NEW.project_id
          AND release_hash = NEW.release_hash;
        SELECT * INTO STRICT evidence
        FROM prompt_program_test_evidence
        WHERE project_id = NEW.project_id
          AND release_id = NEW.release_id
          AND release_hash = NEW.release_hash
          AND tested_state_id = NEW.id;
        IF NEW.evidence_ref <> 'prompt-test:' || evidence.id || ':' || evidence.evidence_hash
           OR evidence.tested_by IS DISTINCT FROM NEW.acted_by
           OR evidence.tested_at IS DISTINCT FROM NEW.acted_at
           OR evidence.test_set_id IS DISTINCT FROM release_record.test_set_id
           OR evidence.test_set_version IS DISTINCT FROM release_record.test_set_version THEN
            RAISE EXCEPTION 'Prompt Program tested state evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;

    SELECT * INTO STRICT previous
    FROM prompt_program_release_states
    WHERE id = NEW.previous_state_id
      AND project_id = NEW.project_id
      AND release_id = NEW.release_id
      AND release_hash = NEW.release_hash;
    IF NEW.status = 'approved' THEN
        SELECT * INTO STRICT release_record
        FROM prompt_program_releases
        WHERE id = previous.release_id
          AND project_id = previous.project_id
          AND release_hash = previous.release_hash;
        SELECT * INTO STRICT evidence
        FROM prompt_program_test_evidence
        WHERE project_id = previous.project_id
          AND release_id = previous.release_id
          AND release_hash = previous.release_hash
          AND tested_state_id = previous.id;
        IF previous.evidence_ref <> 'prompt-test:' || evidence.id || ':' || evidence.evidence_hash
           OR NEW.evidence_ref <> 'approval:' || evidence.id || ':' || evidence.evidence_hash
           OR evidence.tested_by IS DISTINCT FROM previous.acted_by
           OR evidence.tested_at IS DISTINCT FROM previous.acted_at
           OR evidence.test_set_id IS DISTINCT FROM release_record.test_set_id
           OR evidence.test_set_version IS DISTINCT FROM release_record.test_set_version THEN
            RAISE EXCEPTION 'Prompt Program approval evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'frozen'
       AND NEW.evidence_ref <> 'freeze:' || previous.id || ':' || previous.release_hash THEN
        RAISE EXCEPTION 'Prompt Program freeze evidence is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER prompt_programs_immutable
BEFORE UPDATE OR DELETE ON prompt_programs
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_program_releases_append_guard
BEFORE INSERT ON prompt_program_releases
FOR EACH ROW EXECUTE FUNCTION geo_assert_prompt_program_release_append();
CREATE TRIGGER prompt_program_releases_immutable
BEFORE UPDATE OR DELETE ON prompt_program_releases
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_program_release_states_append_guard
BEFORE INSERT ON prompt_program_release_states
FOR EACH ROW EXECUTE FUNCTION geo_assert_prompt_program_state_append();
CREATE CONSTRAINT TRIGGER prompt_program_release_states_evidence_guard
AFTER INSERT ON prompt_program_release_states
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_prompt_program_state_evidence();
CREATE TRIGGER prompt_program_release_states_immutable
BEFORE UPDATE OR DELETE ON prompt_program_release_states
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_program_test_evidence_immutable
BEFORE UPDATE OR DELETE ON prompt_program_test_evidence
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_program_test_run_tasks_insert_guard
BEFORE INSERT ON prompt_program_test_run_tasks
FOR EACH ROW EXECUTE FUNCTION geo_assert_prompt_program_test_run_task();
CREATE TRIGGER prompt_program_test_run_tasks_immutable
BEFORE UPDATE OR DELETE ON prompt_program_test_run_tasks
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_program_bindings_append_guard
BEFORE INSERT ON prompt_program_bindings
FOR EACH ROW EXECUTE FUNCTION geo_assert_prompt_program_binding_append();
CREATE TRIGGER prompt_program_bindings_immutable
BEFORE UPDATE OR DELETE ON prompt_program_bindings
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_program_command_receipts_immutable
BEFORE UPDATE OR DELETE ON prompt_program_command_receipts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX prompt_program_releases_lookup_idx
ON prompt_program_releases(project_id, program_id, version DESC);
CREATE INDEX prompt_programs_project_created_idx
ON prompt_programs(project_id, created_at DESC);
CREATE INDEX prompt_programs_owner_idx
ON prompt_programs(owner_id);
CREATE INDEX prompt_program_releases_program_fkey_idx
ON prompt_program_releases(program_id, project_id, program_kind, purpose, owner_id);
CREATE INDEX prompt_program_releases_owner_idx
ON prompt_program_releases(owner_id);
CREATE INDEX prompt_program_release_states_current_idx
ON prompt_program_release_states(project_id, release_id, version DESC);
CREATE INDEX prompt_program_release_states_release_fkey_idx
ON prompt_program_release_states(release_id, project_id, release_hash);
CREATE INDEX prompt_program_release_states_previous_fkey_idx
ON prompt_program_release_states(
    previous_state_id, project_id, release_id, release_hash
);
CREATE INDEX prompt_program_release_states_acted_by_idx
ON prompt_program_release_states(acted_by);
CREATE INDEX prompt_program_test_evidence_release_idx
ON prompt_program_test_evidence(project_id, release_id);
CREATE INDEX prompt_program_test_evidence_release_fkey_idx
ON prompt_program_test_evidence(
    release_id, project_id, release_hash, test_set_id, test_set_version
);
CREATE INDEX prompt_program_test_evidence_state_fkey_idx
ON prompt_program_test_evidence(
    tested_state_id, project_id, release_id, release_hash
);
CREATE INDEX prompt_program_test_evidence_tested_by_idx
ON prompt_program_test_evidence(tested_by);
CREATE INDEX prompt_program_test_run_tasks_release_idx
ON prompt_program_test_run_tasks(project_id, release_id, created_at DESC, job_id);
CREATE INDEX prompt_program_test_run_tasks_release_fkey_idx
ON prompt_program_test_run_tasks(
    release_id, project_id, program_id, release_hash, release_version
);
CREATE INDEX prompt_program_test_run_tasks_state_fkey_idx
ON prompt_program_test_run_tasks(
    expected_state_id, project_id, release_id, release_hash, expected_state_version
);
CREATE INDEX prompt_program_test_run_tasks_requested_by_idx
ON prompt_program_test_run_tasks(requested_by);
CREATE INDEX prompt_program_bindings_current_idx
ON prompt_program_bindings(project_id, purpose, binding_version DESC);
CREATE INDEX prompt_program_bindings_program_fkey_idx
ON prompt_program_bindings(program_id, project_id, program_kind, purpose);
CREATE INDEX prompt_program_bindings_release_idx
ON prompt_program_bindings(project_id, release_id);
CREATE INDEX prompt_program_bindings_release_fkey_idx
ON prompt_program_bindings(
    release_id, project_id, program_id, release_hash, release_version
);
CREATE INDEX prompt_program_bindings_state_fkey_idx
ON prompt_program_bindings(frozen_state_id, project_id, release_id, release_hash);
CREATE INDEX prompt_program_bindings_bound_by_idx
ON prompt_program_bindings(bound_by);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'prompt_programs', 'prompt_program_releases',
        'prompt_program_release_states', 'prompt_program_test_evidence',
        'prompt_program_test_run_tasks',
        'prompt_program_bindings', 'prompt_program_command_receipts'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

REVOKE ALL ON
    prompt_programs, prompt_program_releases, prompt_program_release_states,
    prompt_program_test_evidence, prompt_program_test_run_tasks, prompt_program_bindings,
    prompt_program_command_receipts
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON
    prompt_programs, prompt_program_releases, prompt_program_release_states,
    prompt_program_test_evidence, prompt_program_test_run_tasks, prompt_program_bindings,
    prompt_program_command_receipts
TO geo_app;
GRANT SELECT ON
    prompt_programs, prompt_program_releases, prompt_program_release_states,
    prompt_program_test_evidence, prompt_program_bindings, prompt_program_test_run_tasks
TO geo_worker;
GRANT INSERT ON
    prompt_programs, prompt_program_releases, prompt_program_release_states,
    prompt_program_test_evidence, prompt_program_test_run_tasks, prompt_program_bindings,
    prompt_program_command_receipts
TO geo_app;
GRANT INSERT ON prompt_program_release_states, prompt_program_test_evidence
TO geo_worker;

REVOKE ALL ON FUNCTION
    geo_assert_prompt_program_release_append(),
    geo_jsonb_canonical_text(jsonb),
    geo_assert_prompt_program_state_append(),
    geo_assert_prompt_program_test_run_task(),
    geo_assert_prompt_program_binding_append(),
    geo_assert_prompt_program_state_evidence()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_assert_prompt_program_release_append(),
    geo_jsonb_canonical_text(jsonb),
    geo_assert_prompt_program_state_append(),
    geo_assert_prompt_program_test_run_task(),
    geo_assert_prompt_program_binding_append(),
    geo_assert_prompt_program_state_evidence()
TO geo_app, geo_worker;
