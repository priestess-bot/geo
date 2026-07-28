-- This migration revokes legacy worker write grants. Apply it in a maintenance
-- window after all old Dify writers are stopped; only the new image knows the
-- fenced finish RPCs introduced below.

ALTER TABLE dify_workflow_execution_attempts
DROP CONSTRAINT dify_workflow_execution_attempts_error_classification_check;
ALTER TABLE dify_workflow_execution_attempts
ADD CONSTRAINT dify_workflow_execution_attempts_error_classification_check CHECK (
    error_classification IS NULL OR error_classification IN (
        'retryable', 'unknown_outcome', 'authentication', 'configuration',
        'contract', 'provider', 'cancelled'
    )
);

-- Workflow-runtime hashes use one cross-language canonical form. In particular,
-- JSON numbers are rendered as their shortest fixed decimal (never exponent),
-- trailing fractional zeroes are removed, and negative zero is normalized.
CREATE FUNCTION geo_dify_canonical_text(p_value jsonb) RETURNS text
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
DECLARE
    value_kind text := jsonb_typeof(p_value);
    rendered text;
    number_value numeric;
BEGIN
    IF value_kind = 'null' THEN
        RETURN 'null';
    ELSIF value_kind = 'boolean' THEN
        RETURN p_value #>> '{}';
    ELSIF value_kind = 'number' THEN
        number_value := (p_value #>> '{}')::numeric;
        IF number_value = 0 THEN
            RETURN '0';
        END IF;
        RETURN trim_scale(number_value)::text;
    ELSIF value_kind = 'string' THEN
        RETURN to_jsonb(p_value #>> '{}')::text;
    ELSIF value_kind = 'array' THEN
        SELECT '[' || coalesce(
                   string_agg(geo_dify_canonical_text(item.value), ',' ORDER BY item.ordinality),
                   ''
               ) || ']'
          INTO rendered
        FROM jsonb_array_elements(p_value) WITH ORDINALITY AS item(value, ordinality);
        RETURN rendered;
    ELSIF value_kind = 'object' THEN
        SELECT '{' || coalesce(
                   string_agg(
                       to_jsonb(item.key)::text || ':' ||
                       geo_dify_canonical_text(item.value),
                       ',' ORDER BY item.key COLLATE "C"
                   ),
                   ''
               ) || '}'
          INTO rendered
        FROM jsonb_each(p_value) AS item(key, value);
        RETURN rendered;
    END IF;
    RAISE EXCEPTION 'unsupported Dify canonical JSON value'
        USING ERRCODE = '22023';
END;
$$;
REVOKE ALL ON FUNCTION geo_dify_canonical_text(jsonb)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

-- A release pins the exact graph observed by its first successful canary.
-- Dify apps can be published in place, so app/purpose identity is insufficient.
CREATE TABLE dify_workflow_release_snapshot_pins (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    release_id uuid NOT NULL,
    published_snapshot_id uuid NOT NULL,
    dify_workflow_id text NOT NULL CHECK (btrim(dify_workflow_id) <> ''),
    workflow_hash text NOT NULL CHECK (workflow_hash ~ '^[0-9a-f]{64}$'),
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    canary_attempt_id uuid NOT NULL REFERENCES dify_workflow_execution_attempts(id),
    pin_source text NOT NULL DEFAULT 'runtime_canary' CHECK (
        pin_source IN ('migration_backfill', 'runtime_canary')
    ),
    pinned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, release_id),
    CONSTRAINT dify_workflow_release_snapshot_pins_release_fkey FOREIGN KEY (
        release_id, project_id
    ) REFERENCES dify_workflow_releases(id, project_id),
    CONSTRAINT dify_workflow_release_snapshot_pins_snapshot_fkey FOREIGN KEY (
        published_snapshot_id, project_id, release_id
    ) REFERENCES dify_workflow_published_snapshots(id, project_id, release_id)
);

CREATE FUNCTION geo_assert_dify_release_snapshot_pin() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    attempt_row dify_workflow_execution_attempts%ROWTYPE;
    snapshot_row dify_workflow_published_snapshots%ROWTYPE;
    release_row dify_workflow_releases%ROWTYPE;
BEGIN
    SELECT * INTO STRICT attempt_row
    FROM dify_workflow_execution_attempts
    WHERE id = NEW.canary_attempt_id;
    SELECT * INTO STRICT snapshot_row
    FROM dify_workflow_published_snapshots
    WHERE id = NEW.published_snapshot_id
      AND project_id = NEW.project_id AND release_id = NEW.release_id;
    SELECT * INTO STRICT release_row
    FROM dify_workflow_releases
    WHERE id = NEW.release_id AND project_id = NEW.project_id;
    IF attempt_row.project_id <> NEW.project_id
       OR attempt_row.release_id <> NEW.release_id
       OR attempt_row.execution_kind <> 'canary'
       OR attempt_row.status <> 'succeeded'
       OR attempt_row.published_snapshot_id IS DISTINCT FROM NEW.published_snapshot_id
       OR snapshot_row.dify_workflow_id <> NEW.dify_workflow_id
       OR snapshot_row.workflow_hash <> NEW.workflow_hash
       OR snapshot_row.snapshot_hash <> NEW.snapshot_hash
       OR snapshot_row.purpose <> release_row.purpose
       OR snapshot_row.dify_app_id <> release_row.dify_app_id
       OR jsonb_array_length(snapshot_row.prompt_nodes) = 0
       OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(snapshot_row.prompt_nodes) node
            WHERE coalesce(node->>'model_provider', '') <> release_row.model_provider
               OR coalesce(node->>'model_name', '') <> release_row.configured_model
       ) THEN
        RAISE EXCEPTION 'Dify release snapshot pin is not backed by its successful canary and frozen model graph'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_assert_dify_release_snapshot_pin() FROM PUBLIC;

CREATE TRIGGER dify_workflow_release_snapshot_pin_guard
BEFORE INSERT ON dify_workflow_release_snapshot_pins
FOR EACH ROW EXECUTE FUNCTION geo_assert_dify_release_snapshot_pin();
CREATE TRIGGER dify_workflow_release_snapshot_pins_immutable
BEFORE UPDATE OR DELETE ON dify_workflow_release_snapshot_pins
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_runtime_mutation();

ALTER TABLE dify_workflow_release_snapshot_pins ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_release_snapshot_pins FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON dify_workflow_release_snapshot_pins
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
REVOKE ALL ON dify_workflow_release_snapshot_pins
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON dify_workflow_release_snapshot_pins TO geo_app, geo_worker;

-- Existing releases pin their latest successful canary. A migration-backfill
-- pin may coexist with older successful attempts from another snapshot; those
-- results keep their own immutable attempt-level lineage and are replay-only.
INSERT INTO dify_workflow_release_snapshot_pins (
    project_id, release_id, published_snapshot_id, dify_workflow_id,
    workflow_hash, snapshot_hash, canary_attempt_id, pin_source, pinned_at
)
SELECT release.project_id, release.id, snapshot.id,
       snapshot.dify_workflow_id, snapshot.workflow_hash, snapshot.snapshot_hash,
       canary.id, 'migration_backfill', coalesce(canary.finished_at, canary.started_at)
FROM dify_workflow_releases release
JOIN LATERAL (
    SELECT attempt.*
    FROM dify_workflow_execution_attempts attempt
    WHERE attempt.project_id = release.project_id
      AND attempt.release_id = release.id
      AND attempt.execution_kind = 'canary'
      AND attempt.status = 'succeeded'
      AND attempt.published_snapshot_id IS NOT NULL
    ORDER BY attempt.attempt_number DESC
    LIMIT 1
) canary ON true
JOIN dify_workflow_published_snapshots snapshot
  ON snapshot.id = canary.published_snapshot_id
 AND snapshot.project_id = canary.project_id
 AND snapshot.release_id = canary.release_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM (
            SELECT DISTINCT ON (project_id, purpose) project_id, purpose, release_id
            FROM dify_workflow_bindings
            ORDER BY project_id, purpose, binding_version DESC
        ) binding
        LEFT JOIN dify_workflow_release_snapshot_pins pin
          ON pin.project_id = binding.project_id AND pin.release_id = binding.release_id
        WHERE pin.release_id IS NULL
    ) THEN
        RAISE EXCEPTION 'cannot migrate: an active Dify release lacks a successful canary published snapshot'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM recommendation_model_tasks task
        JOIN durable_jobs job
          ON job.id = task.child_job_id AND job.project_id = task.project_id
        LEFT JOIN dify_workflow_release_snapshot_pins pin
          ON pin.project_id = task.project_id
         AND pin.release_id = task.workflow_release_id
        WHERE task.execution_backend = 'dify'
          AND job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
          AND pin.release_id IS NULL
    ) OR EXISTS (
        SELECT 1
        FROM dify_workflow_execution_attempts attempt
        LEFT JOIN dify_workflow_release_snapshot_pins pin
          ON pin.project_id = attempt.project_id AND pin.release_id = attempt.release_id
        WHERE attempt.execution_kind = 'business' AND attempt.status = 'running'
          AND pin.release_id IS NULL
    ) THEN
        RAISE EXCEPTION 'cannot migrate: a non-terminal frozen Dify task lacks a successful-canary snapshot pin; drain it first'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM recommendation_model_tasks task
        JOIN durable_jobs job
          ON job.id = task.child_job_id AND job.project_id = task.project_id
        LEFT JOIN LATERAL (
            SELECT binding.release_id, binding.release_hash
            FROM dify_workflow_bindings binding
            WHERE binding.project_id = task.project_id
              AND binding.purpose = task.prompt_purpose
            ORDER BY binding.binding_version DESC
            LIMIT 1
        ) active_binding ON true
        WHERE task.role = 'primary'
          AND task.prompt_purpose = 'recommendations.recommendation'
          AND job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
          AND task.execution_backend = 'dify'
          AND (
              active_binding.release_id IS DISTINCT FROM task.workflow_release_id
              OR active_binding.release_hash IS DISTINCT FROM task.workflow_release_hash
          )
    ) THEN
        RAISE EXCEPTION 'cannot migrate: a non-terminal Recommendation task differs from its active Dify backend; drain it first'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        WITH ambiguous_release AS (
            SELECT attempt.project_id, attempt.release_id
            FROM dify_workflow_execution_attempts attempt
            WHERE attempt.execution_kind = 'canary'
              AND attempt.status = 'succeeded'
              AND attempt.published_snapshot_id IS NOT NULL
            GROUP BY attempt.project_id, attempt.release_id
            HAVING count(DISTINCT attempt.published_snapshot_id) > 1
            UNION
            SELECT business.project_id, business.release_id
            FROM dify_workflow_execution_attempts business
            JOIN dify_workflow_release_snapshot_pins pin
              ON pin.project_id = business.project_id
             AND pin.release_id = business.release_id
            WHERE business.execution_kind = 'business'
              AND business.status = 'succeeded'
              AND business.published_snapshot_id IS DISTINCT FROM pin.published_snapshot_id
        )
        SELECT 1
        FROM ambiguous_release ambiguous
        JOIN recommendation_model_tasks task
          ON task.project_id = ambiguous.project_id
         AND task.workflow_release_id = ambiguous.release_id
        JOIN durable_jobs job
          ON job.id = task.child_job_id AND job.project_id = task.project_id
        WHERE task.execution_backend = 'dify'
          AND job.status IN ('queued', 'running', 'retry_wait', 'finalizing')
    ) OR EXISTS (
        WITH ambiguous_release AS (
            SELECT attempt.project_id, attempt.release_id
            FROM dify_workflow_execution_attempts attempt
            WHERE attempt.execution_kind = 'canary'
              AND attempt.status = 'succeeded'
              AND attempt.published_snapshot_id IS NOT NULL
            GROUP BY attempt.project_id, attempt.release_id
            HAVING count(DISTINCT attempt.published_snapshot_id) > 1
            UNION
            SELECT business.project_id, business.release_id
            FROM dify_workflow_execution_attempts business
            JOIN dify_workflow_release_snapshot_pins pin
              ON pin.project_id = business.project_id
             AND pin.release_id = business.release_id
            WHERE business.execution_kind = 'business'
              AND business.status = 'succeeded'
              AND business.published_snapshot_id IS DISTINCT FROM pin.published_snapshot_id
        )
        SELECT 1
        FROM ambiguous_release ambiguous
        JOIN dify_workflow_execution_attempts attempt
          ON attempt.project_id = ambiguous.project_id
         AND attempt.release_id = ambiguous.release_id
        WHERE attempt.execution_kind = 'business' AND attempt.status = 'running'
    ) THEN
        RAISE EXCEPTION 'cannot migrate: an ambiguous legacy Dify release still has a non-terminal task or attempt; drain it or bind a replacement release first'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION geo_require_dify_release_snapshot_pin_for_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'dify-binding:' || NEW.project_id::text || ':' || NEW.purpose, 0
    ));
    IF NOT EXISTS (
        SELECT 1 FROM dify_workflow_release_snapshot_pins pin
        WHERE pin.project_id = NEW.project_id AND pin.release_id = NEW.release_id
    ) THEN
        RAISE EXCEPTION 'Dify release requires an immutable successful-canary snapshot pin before activation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_require_dify_release_snapshot_pin_for_binding() FROM PUBLIC;
CREATE TRIGGER dify_workflow_binding_snapshot_pin_guard
BEFORE INSERT ON dify_workflow_bindings
FOR EACH ROW EXECUTE FUNCTION geo_require_dify_release_snapshot_pin_for_binding();

-- Freeze the exact pre-upgrade V3 parents that cannot be routed through Dify.
-- The marker is migration-owned and immutable, so a new enqueue cannot claim
-- the legacy contract string to bypass an active Recommendation binding.
CREATE TABLE dify_legacy_recommendation_native_parents (
    project_id uuid NOT NULL,
    parent_job_id uuid NOT NULL,
    captured_contract_version text NOT NULL CHECK (
        captured_contract_version = 'recommendation-generation-spec-v3'
    ),
    captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, parent_job_id),
    FOREIGN KEY (project_id, parent_job_id)
        REFERENCES recommendation_generation_specs(project_id, job_id)
        ON DELETE RESTRICT
);

INSERT INTO dify_legacy_recommendation_native_parents (
    project_id, parent_job_id, captured_contract_version
)
SELECT spec.project_id, spec.job_id, spec.spec_payload->>'contract_version'
FROM recommendation_generation_specs spec
WHERE spec.spec_payload->>'contract_version' = 'recommendation-generation-spec-v3';

CREATE TRIGGER dify_legacy_recommendation_native_parents_immutable
BEFORE UPDATE OR DELETE ON dify_legacy_recommendation_native_parents
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_runtime_mutation();
ALTER TABLE dify_legacy_recommendation_native_parents ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_legacy_recommendation_native_parents FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON dify_legacy_recommendation_native_parents
USING (project_id = ANY(geo_current_project_ids()));
REVOKE ALL ON dify_legacy_recommendation_native_parents
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON dify_legacy_recommendation_native_parents TO geo_app, geo_worker;

-- Recommendation primary admission and Workflow activation share the same
-- transaction lock. The INSERT guard then resolves the latest binding again,
-- closing the Python resolve/reserve time-of-check/time-of-use window.
CREATE OR REPLACE FUNCTION geo_assert_recommendation_model_task_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
DECLARE workflow dify_workflow_releases%ROWTYPE;
DECLARE active_binding dify_workflow_bindings%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation model task lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.role = 'primary' THEN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                'dify-binding:' || NEW.project_id::text || ':' || NEW.prompt_purpose, 0
            ));
            SELECT binding.* INTO active_binding
            FROM dify_workflow_bindings binding
            WHERE binding.project_id = NEW.project_id
              AND binding.purpose = NEW.prompt_purpose
            ORDER BY binding.binding_version DESC
            LIMIT 1;
        END IF;
        IF (NEW.role = 'primary' AND NEW.prompt_purpose <> 'recommendations.recommendation')
           OR (NEW.role = 'arbiter' AND NEW.prompt_purpose <> 'synthetic_lab.arbiter')
           OR NEW.runtime_selection_id <> NEW.runtime_option_id
           OR NEW.task_artifact_expires_at <= NEW.created_at
           OR NEW.task_artifact_status <> 'uploading'
           OR (NEW.role = 'arbiter' AND NEW.execution_backend <> 'model_gateway') THEN
            RAISE EXCEPTION 'Recommendation model task frozen lineage is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.role = 'primary' AND NEW.execution_backend = 'dify' THEN
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
                RAISE EXCEPTION 'Recommendation Dify task differs from the active pinned Workflow Release'
                    USING ERRCODE = '40001';
            END IF;
        ELSIF NEW.role = 'primary' AND NEW.execution_backend = 'model_gateway' THEN
            IF NEW.workflow_release_id IS NOT NULL OR NEW.workflow_release_hash IS NOT NULL THEN
                RAISE EXCEPTION 'native Recommendation task cannot carry Dify release identity'
                    USING ERRCODE = '23514';
            END IF;
            IF active_binding.id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM dify_legacy_recommendation_native_parents legacy
                WHERE legacy.project_id = NEW.project_id
                  AND legacy.parent_job_id = NEW.parent_job_id
                  AND legacy.captured_contract_version =
                      'recommendation-generation-spec-v3'
            ) THEN
                RAISE EXCEPTION 'Recommendation Prompt purpose is bound to Dify; deploy the backend-aware worker before enqueue'
                    USING ERRCODE = '40001';
            END IF;
        ELSIF NEW.role = 'primary' THEN
            RAISE EXCEPTION 'Recommendation primary execution backend is unsupported'
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

-- Terminal business writes validate the live Durable Job lease and persist the
-- result plus attempt transition atomically. No direct worker write remains.
CREATE FUNCTION geo_finish_dify_business_attempt(
    p_project_id uuid, p_job_id uuid, p_lease_token uuid,
    p_fencing_generation bigint, p_attempt_id uuid, p_values jsonb
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    durable_row durable_jobs%ROWTYPE;
    attempt_row dify_workflow_execution_attempts%ROWTYPE;
    release_row dify_workflow_releases%ROWTYPE;
    pin_row dify_workflow_release_snapshot_pins%ROWTYPE;
    terminal_status text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL OR p_lease_token IS NULL
       OR p_fencing_generation IS NULL OR p_fencing_generation < 1
       OR p_attempt_id IS NULL
       OR p_values IS NULL OR jsonb_typeof(p_values) <> 'object' THEN
        RAISE EXCEPTION 'invalid or out-of-scope Dify business finish request'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO durable_row FROM durable_jobs
    WHERE id = p_job_id AND project_id = p_project_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Dify business Durable Job is missing or out of scope'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO attempt_row FROM dify_workflow_execution_attempts
    WHERE id = p_attempt_id AND project_id = p_project_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Dify business attempt is missing or out of scope'
            USING ERRCODE = '40001';
    END IF;
    IF attempt_row.job_id IS DISTINCT FROM p_job_id
       OR attempt_row.execution_kind <> 'business' THEN
        RAISE EXCEPTION 'Dify business attempt lease or attempt was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF attempt_row.status <> 'running' THEN
        RAISE EXCEPTION 'Dify business attempt is already finalized'
            USING ERRCODE = '23514';
    END IF;
    IF durable_row.status NOT IN ('running', 'finalizing')
       OR durable_row.lease_token IS DISTINCT FROM p_lease_token
       OR durable_row.fencing_generation IS DISTINCT FROM p_fencing_generation
       OR durable_row.lease_expires_at IS NULL
       OR durable_row.lease_expires_at <= clock_timestamp()
       OR durable_row.cancel_requested_at IS NOT NULL
       OR attempt_row.fencing_generation IS DISTINCT FROM p_fencing_generation THEN
        RAISE EXCEPTION 'Dify business attempt lease or attempt was fenced'
            USING ERRCODE = '40001';
    END IF;

    terminal_status := p_values->>'status';
    IF terminal_status = 'succeeded' THEN
        SELECT * INTO STRICT release_row FROM dify_workflow_releases
        WHERE id = attempt_row.release_id AND project_id = attempt_row.project_id;
        SELECT * INTO STRICT pin_row FROM dify_workflow_release_snapshot_pins
        WHERE release_id = attempt_row.release_id AND project_id = attempt_row.project_id;
        IF attempt_row.published_snapshot_id IS DISTINCT FROM pin_row.published_snapshot_id
           OR p_values->>'reported_workflow_id' IS DISTINCT FROM pin_row.dify_workflow_id
           OR p_values->>'configured_model' IS DISTINCT FROM release_row.configured_model
           OR jsonb_typeof(p_values->'output') <> 'object'
           OR coalesce(p_values->>'response_hash', '') !~ '^[0-9a-f]{64}$'
           OR p_values->>'response_hash' IS DISTINCT FROM p_values->>'output_hash'
           OR p_values->>'response_hash' IS DISTINCT FROM encode(
                digest(
                    convert_to(geo_dify_canonical_text(p_values->'output'), 'UTF8'),
                    'sha256'
                ),
                'hex'
           )
           OR btrim(coalesce(p_values->>'dify_run_id', '')) = '' THEN
            RAISE EXCEPTION 'Dify business success does not match its frozen release, pin, or output'
                USING ERRCODE = '23514';
        END IF;
        INSERT INTO dify_workflow_execution_results (
            attempt_id, project_id, job_id, output, response_hash,
            configured_model, provider_reported_model
        ) VALUES (
            p_attempt_id, p_project_id, p_job_id, p_values->'output',
            p_values->>'response_hash', p_values->>'configured_model',
            nullif(p_values->>'provider_reported_model', '')
        );
        UPDATE dify_workflow_execution_attempts
        SET status = 'succeeded', dify_task_id = nullif(p_values->>'dify_task_id', ''),
            dify_run_id = p_values->>'dify_run_id',
            reported_workflow_id = p_values->>'reported_workflow_id',
            output_hash = p_values->>'output_hash',
            prompt_tokens = (p_values->>'prompt_tokens')::integer,
            completion_tokens = (p_values->>'completion_tokens')::integer,
            total_steps = (p_values->>'total_steps')::integer,
            elapsed_seconds = (p_values->>'elapsed_seconds')::numeric,
            http_status = (p_values->>'http_status')::integer,
            retryable = false, finished_at = clock_timestamp()
        WHERE id = p_attempt_id AND project_id = p_project_id AND status = 'running';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Dify business success transition was fenced'
                USING ERRCODE = '40001';
        END IF;
    ELSIF terminal_status = 'failed' THEN
        UPDATE dify_workflow_execution_attempts
        SET status = 'failed', dify_task_id = nullif(p_values->>'dify_task_id', ''),
            dify_run_id = nullif(p_values->>'dify_run_id', ''),
            reported_workflow_id = nullif(p_values->>'reported_workflow_id', ''),
            http_status = (p_values->>'http_status')::integer,
            error_classification = p_values->>'error_classification',
            error_code = p_values->>'error_code',
            error_message = left(coalesce(p_values->>'error_message', ''), 2000),
            retryable = coalesce((p_values->>'retryable')::boolean, false),
            finished_at = clock_timestamp()
        WHERE id = p_attempt_id AND project_id = p_project_id AND status = 'running';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Dify business failure transition was fenced'
                USING ERRCODE = '40001';
        END IF;
    ELSE
        RAISE EXCEPTION 'Dify business terminal status is invalid'
            USING ERRCODE = '22023';
    END IF;
END;
$$;

-- Canary completion has no Durable Job lease. It is a separate RPC and pins
-- the exact published graph in the same transaction as the successful canary.
CREATE FUNCTION geo_finish_dify_canary_attempt(
    p_project_id uuid, p_attempt_id uuid, p_values jsonb
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    attempt_row dify_workflow_execution_attempts%ROWTYPE;
    snapshot_row dify_workflow_published_snapshots%ROWTYPE;
    release_row dify_workflow_releases%ROWTYPE;
    pin_row dify_workflow_release_snapshot_pins%ROWTYPE;
    terminal_status text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_attempt_id IS NULL OR p_values IS NULL
       OR jsonb_typeof(p_values) <> 'object' THEN
        RAISE EXCEPTION 'invalid or out-of-scope Dify canary finish request'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO attempt_row FROM dify_workflow_execution_attempts
    WHERE id = p_attempt_id AND project_id = p_project_id FOR UPDATE;
    IF NOT FOUND OR attempt_row.execution_kind <> 'canary'
       OR attempt_row.status <> 'running' OR attempt_row.job_id IS NOT NULL
       OR attempt_row.published_snapshot_id IS NULL THEN
        RAISE EXCEPTION 'Dify canary attempt is missing or already terminal'
            USING ERRCODE = '40001';
    END IF;

    terminal_status := p_values->>'status';
    IF terminal_status = 'succeeded' THEN
        SELECT * INTO STRICT snapshot_row FROM dify_workflow_published_snapshots
        WHERE id = attempt_row.published_snapshot_id
          AND project_id = attempt_row.project_id AND release_id = attempt_row.release_id;
        SELECT * INTO STRICT release_row FROM dify_workflow_releases
        WHERE id = attempt_row.release_id AND project_id = attempt_row.project_id;
        IF p_values->>'reported_workflow_id' IS DISTINCT FROM snapshot_row.dify_workflow_id
           OR btrim(coalesce(p_values->>'dify_run_id', '')) = ''
           OR coalesce(p_values->>'output_hash', '') !~ '^[0-9a-f]{64}$'
           OR snapshot_row.purpose <> release_row.purpose
           OR snapshot_row.dify_app_id <> release_row.dify_app_id
           OR jsonb_array_length(snapshot_row.prompt_nodes) = 0
           OR EXISTS (
                SELECT 1 FROM jsonb_array_elements(snapshot_row.prompt_nodes) node
                WHERE coalesce(node->>'model_provider', '') <> release_row.model_provider
                   OR coalesce(node->>'model_name', '') <> release_row.configured_model
           ) THEN
            RAISE EXCEPTION 'Dify canary success does not match its published model graph'
                USING ERRCODE = '23514';
        END IF;
        UPDATE dify_workflow_execution_attempts
        SET status = 'succeeded', dify_task_id = nullif(p_values->>'dify_task_id', ''),
            dify_run_id = p_values->>'dify_run_id',
            reported_workflow_id = p_values->>'reported_workflow_id',
            output_hash = p_values->>'output_hash',
            prompt_tokens = (p_values->>'prompt_tokens')::integer,
            completion_tokens = (p_values->>'completion_tokens')::integer,
            total_steps = (p_values->>'total_steps')::integer,
            elapsed_seconds = (p_values->>'elapsed_seconds')::numeric,
            http_status = (p_values->>'http_status')::integer,
            retryable = false, finished_at = clock_timestamp()
        WHERE id = p_attempt_id AND project_id = p_project_id AND status = 'running';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Dify canary success transition was fenced'
                USING ERRCODE = '40001';
        END IF;
        INSERT INTO dify_workflow_release_snapshot_pins (
            project_id, release_id, published_snapshot_id, dify_workflow_id,
            workflow_hash, snapshot_hash, canary_attempt_id
        ) VALUES (
            attempt_row.project_id, attempt_row.release_id, snapshot_row.id,
            snapshot_row.dify_workflow_id, snapshot_row.workflow_hash,
            snapshot_row.snapshot_hash, attempt_row.id
        ) ON CONFLICT (project_id, release_id) DO NOTHING;
        SELECT * INTO STRICT pin_row FROM dify_workflow_release_snapshot_pins
        WHERE project_id = attempt_row.project_id AND release_id = attempt_row.release_id;
        IF pin_row.published_snapshot_id <> snapshot_row.id
           OR pin_row.dify_workflow_id <> snapshot_row.dify_workflow_id
           OR pin_row.workflow_hash <> snapshot_row.workflow_hash
           OR pin_row.snapshot_hash <> snapshot_row.snapshot_hash THEN
            RAISE EXCEPTION 'Dify canary graph differs from the release snapshot pin; register a new release'
                USING ERRCODE = '23514';
        END IF;
    ELSIF terminal_status = 'failed' THEN
        UPDATE dify_workflow_execution_attempts
        SET status = 'failed', dify_task_id = nullif(p_values->>'dify_task_id', ''),
            dify_run_id = nullif(p_values->>'dify_run_id', ''),
            reported_workflow_id = nullif(p_values->>'reported_workflow_id', ''),
            http_status = (p_values->>'http_status')::integer,
            error_classification = p_values->>'error_classification',
            error_code = p_values->>'error_code',
            error_message = left(coalesce(p_values->>'error_message', ''), 2000),
            retryable = coalesce((p_values->>'retryable')::boolean, false),
            finished_at = clock_timestamp()
        WHERE id = p_attempt_id AND project_id = p_project_id AND status = 'running';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Dify canary failure transition was fenced'
                USING ERRCODE = '40001';
        END IF;
    ELSE
        RAISE EXCEPTION 'Dify canary terminal status is invalid'
            USING ERRCODE = '22023';
    END IF;
END;
$$;

REVOKE UPDATE ON dify_workflow_execution_attempts FROM geo_worker;
REVOKE INSERT ON dify_workflow_execution_results FROM geo_worker;
REVOKE ALL ON FUNCTION geo_finish_dify_business_attempt(
    uuid, uuid, uuid, bigint, uuid, jsonb
), geo_finish_dify_canary_attempt(uuid, uuid, jsonb)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_finish_dify_business_attempt(
    uuid, uuid, uuid, bigint, uuid, jsonb
), geo_finish_dify_canary_attempt(uuid, uuid, jsonb)
TO geo_worker;

-- Unknown provider outcomes require human verification. The operator receives
-- a random token once; only its SHA-256 is stored. Reissuing a token appends a
-- new decision and invalidates every older unconsumed token for that attempt.
CREATE TABLE dify_workflow_attempt_reconciliations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    attempt_id uuid NOT NULL REFERENCES dify_workflow_execution_attempts(id),
    release_id uuid NOT NULL,
    job_id uuid NOT NULL,
    issuance_number integer NOT NULL CHECK (issuance_number > 0),
    resubmission_token_hash text NOT NULL UNIQUE CHECK (
        resubmission_token_hash ~ '^[0-9a-f]{64}$'
    ),
    business_fingerprint text NOT NULL CHECK (
        business_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    provider_outcome text NOT NULL CHECK (provider_outcome IN (
        'not_found', 'failed_without_output', 'succeeded_output_unrecoverable'
    )),
    provider_run_id text,
    evidence_reference text NOT NULL CHECK (btrim(evidence_reference) <> ''),
    verification_conclusion text NOT NULL CHECK (
        verification_conclusion = 'resubmit_new_parent_required'
    ),
    decision text NOT NULL CHECK (decision = 'new_parent_token_issued'),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    authorized_by uuid NOT NULL REFERENCES identities(id),
    authorized_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT dify_workflow_attempt_reconciliations_project_key UNIQUE (
        id, project_id, attempt_id
    ),
    CONSTRAINT dify_workflow_attempt_reconciliations_issue_key UNIQUE (
        project_id, attempt_id, issuance_number
    ),
    CONSTRAINT dify_workflow_attempt_reconciliations_run_shape CHECK (
        (provider_outcome = 'not_found' AND provider_run_id IS NULL)
        OR (provider_outcome <> 'not_found' AND btrim(provider_run_id) <> '')
    ),
    CONSTRAINT dify_workflow_attempt_reconciliations_release_fkey FOREIGN KEY (
        release_id, project_id
    ) REFERENCES dify_workflow_releases(id, project_id),
    CONSTRAINT dify_workflow_attempt_reconciliations_job_fkey FOREIGN KEY (
        job_id, project_id
    ) REFERENCES durable_jobs(id, project_id)
);

CREATE TABLE dify_workflow_reconciliation_consumptions (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    attempt_id uuid NOT NULL REFERENCES dify_workflow_execution_attempts(id),
    reconciliation_id uuid NOT NULL,
    new_parent_job_id uuid NOT NULL,
    consumed_by uuid NOT NULL REFERENCES identities(id),
    consumed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, attempt_id),
    CONSTRAINT dify_workflow_reconciliation_consumptions_parent_key UNIQUE (
        project_id, new_parent_job_id
    ),
    CONSTRAINT dify_workflow_reconciliation_consumptions_issue_fkey FOREIGN KEY (
        reconciliation_id, project_id, attempt_id
    ) REFERENCES dify_workflow_attempt_reconciliations(id, project_id, attempt_id),
    CONSTRAINT dify_workflow_reconciliation_consumptions_job_fkey FOREIGN KEY (
        new_parent_job_id, project_id
    ) REFERENCES durable_jobs(id, project_id)
);

CREATE FUNCTION geo_reject_dify_attempt_reconciliation_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Dify reconciliation and token-consumption evidence is append-only'
        USING ERRCODE = '55000';
END;
$$;
REVOKE ALL ON FUNCTION geo_reject_dify_attempt_reconciliation_change() FROM PUBLIC;
CREATE TRIGGER dify_workflow_attempt_reconciliations_immutable
BEFORE UPDATE OR DELETE ON dify_workflow_attempt_reconciliations
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_attempt_reconciliation_change();
CREATE TRIGGER dify_workflow_reconciliation_consumptions_immutable
BEFORE UPDATE OR DELETE ON dify_workflow_reconciliation_consumptions
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_attempt_reconciliation_change();

ALTER TABLE dify_workflow_attempt_reconciliations ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_attempt_reconciliations FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON dify_workflow_attempt_reconciliations
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
ALTER TABLE dify_workflow_reconciliation_consumptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_reconciliation_consumptions FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON dify_workflow_reconciliation_consumptions
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
REVOKE ALL ON dify_workflow_attempt_reconciliations,
    dify_workflow_reconciliation_consumptions
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON dify_workflow_attempt_reconciliations,
    dify_workflow_reconciliation_consumptions TO geo_app, geo_worker;

CREATE FUNCTION geo_issue_dify_resubmission_token(
    p_project_id uuid, p_attempt_id uuid, p_authorized_by uuid,
    p_provider_outcome text, p_provider_run_id text,
    p_evidence_reference text, p_reason text
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    attempt_row dify_workflow_execution_attempts%ROWTYPE;
    durable_row durable_jobs%ROWTYPE;
    next_issuance integer;
    raw_token text;
    business_fingerprint text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_attempt_id IS NULL OR p_authorized_by IS NULL
       OR geo_current_identity_id() IS DISTINCT FROM p_authorized_by
       OR p_provider_outcome NOT IN (
            'not_found', 'failed_without_output', 'succeeded_output_unrecoverable'
       )
       OR btrim(coalesce(p_evidence_reference, '')) = ''
       OR btrim(coalesce(p_reason, '')) = ''
       OR (p_provider_outcome = 'not_found' AND p_provider_run_id IS NOT NULL)
       OR (p_provider_outcome <> 'not_found'
           AND btrim(coalesce(p_provider_run_id, '')) = '') THEN
        RAISE EXCEPTION 'invalid, unverified, or out-of-scope Dify reconciliation request'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM project_memberships membership
        JOIN identities identity ON identity.id = membership.identity_id
        WHERE membership.project_id = p_project_id
          AND membership.identity_id = p_authorized_by
          AND membership.status = 'active'
          AND membership.role IN ('owner', 'admin')
          AND identity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'Dify reconciliation requires an active project owner or admin'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO attempt_row FROM dify_workflow_execution_attempts
    WHERE id = p_attempt_id AND project_id = p_project_id FOR UPDATE;
    IF NOT FOUND OR attempt_row.execution_kind <> 'business'
       OR attempt_row.job_id IS NULL
       OR NOT (
            attempt_row.status = 'running'
            OR (attempt_row.status = 'failed'
                AND attempt_row.error_classification = 'unknown_outcome')
       ) THEN
        RAISE EXCEPTION 'Dify attempt is not an unresolved business outcome'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM dify_workflow_reconciliation_consumptions consumption
        WHERE consumption.project_id = p_project_id
          AND consumption.attempt_id = p_attempt_id
    ) THEN
        RAISE EXCEPTION 'Dify attempt reconciliation token was already consumed by a new parent'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT durable_row FROM durable_jobs
    WHERE id = attempt_row.job_id AND project_id = attempt_row.project_id FOR SHARE;
    IF NOT EXISTS (
        SELECT 1
        FROM durable_jobs parent
        JOIN dify_workflow_releases release
          ON release.id = attempt_row.release_id
         AND release.project_id = attempt_row.project_id
        WHERE parent.id = coalesce(durable_row.parent_job_id, durable_row.id)
          AND parent.project_id = attempt_row.project_id
          AND (
              (parent.kind = 'style.profile.build'
               AND release.purpose = 'synthetic_lab.style_profile')
              OR (parent.kind = 'recommendation.generate'
                  AND release.purpose = 'recommendations.recommendation')
          )
    ) THEN
        RAISE EXCEPTION 'Dify reconciliation supports only Style Profile and Recommendation parent flows'
            USING ERRCODE = '23514';
    END IF;
    IF durable_row.status IN ('running', 'finalizing')
       AND durable_row.lease_expires_at > clock_timestamp() THEN
        RAISE EXCEPTION 'Dify attempt cannot be reconciled while its Durable Job lease is active'
            USING ERRCODE = '40001';
    END IF;
    business_fingerprint := geo_dify_recovery_parent_fingerprint(
        p_project_id, coalesce(durable_row.parent_job_id, durable_row.id)
    );
    IF business_fingerprint IS NULL THEN
        RAISE EXCEPTION 'Dify attempt has no supported frozen parent business fingerprint'
            USING ERRCODE = '23514';
    END IF;
    SELECT coalesce(max(reconciliation.issuance_number), 0) + 1
      INTO next_issuance
    FROM dify_workflow_attempt_reconciliations reconciliation
    WHERE reconciliation.project_id = p_project_id
      AND reconciliation.attempt_id = p_attempt_id;
    raw_token := encode(gen_random_bytes(32), 'hex');
    INSERT INTO dify_workflow_attempt_reconciliations (
        project_id, attempt_id, release_id, job_id, issuance_number,
        resubmission_token_hash, business_fingerprint,
        provider_outcome, provider_run_id,
        evidence_reference, verification_conclusion, decision, reason,
        authorized_by, authorized_at
    ) VALUES (
        p_project_id, p_attempt_id, attempt_row.release_id, attempt_row.job_id,
        next_issuance,
        encode(digest(convert_to(raw_token, 'UTF8'), 'sha256'), 'hex'),
        business_fingerprint,
        p_provider_outcome, nullif(p_provider_run_id, ''), p_evidence_reference,
        'resubmit_new_parent_required', 'new_parent_token_issued', p_reason,
        p_authorized_by, clock_timestamp()
    );
    RETURN raw_token;
END;
$$;

-- Compare the immutable business request behind a parent Job while excluding
-- values that necessarily change when an operator creates a fresh parent after
-- an unknown provider outcome.
CREATE FUNCTION geo_dify_recovery_parent_fingerprint(
    p_project_id uuid, p_parent_job_id uuid
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    parent_kind text;
    fingerprint_payload jsonb;
BEGIN
    SELECT job.kind INTO parent_kind
    FROM durable_jobs job
    WHERE job.project_id = p_project_id AND job.id = p_parent_job_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF parent_kind = 'style.profile.build' THEN
        SELECT jsonb_build_object(
                   '$type', task.task_payload->'$type',
                   'fields', (task.task_payload->'fields') - 'job_id' - 'requested_by'
               )
          INTO fingerprint_payload
        FROM synthetic_lab_execution_tasks task
        WHERE task.project_id = p_project_id
          AND task.job_id = p_parent_job_id
          AND task.execution_kind = 'style.profile.build'
          AND jsonb_typeof(task.task_payload->'fields') = 'object';
    ELSIF parent_kind = 'recommendation.generate' THEN
        SELECT spec.spec_payload - 'valid_until' - 'created_by'
          INTO fingerprint_payload
        FROM recommendation_generation_specs spec
        WHERE spec.project_id = p_project_id AND spec.job_id = p_parent_job_id;
    ELSE
        RETURN NULL;
    END IF;
    IF fingerprint_payload IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN encode(
        digest(convert_to(geo_dify_canonical_text(fingerprint_payload), 'UTF8'), 'sha256'),
        'hex'
    );
END;
$$;
REVOKE ALL ON FUNCTION geo_dify_recovery_parent_fingerprint(uuid, uuid)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

-- Called in the same transaction that inserts the new parent Job. With no
-- prior unresolved parent this is a no-op and a supplied token is rejected.
-- With a prior unresolved parent the latest token is mandatory and consumed.
CREATE FUNCTION geo_bind_dify_resubmission(
    p_project_id uuid, p_new_parent_job_id uuid, p_consumed_by uuid,
    p_recovery_attempt_id uuid, p_raw_token text
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    new_parent durable_jobs%ROWTYPE;
    old_child durable_jobs%ROWTYPE;
    old_parent durable_jobs%ROWTYPE;
    old_attempt dify_workflow_execution_attempts%ROWTYPE;
    old_release dify_workflow_releases%ROWTYPE;
    reconciliation dify_workflow_attempt_reconciliations%ROWTYPE;
    existing_consumption dify_workflow_reconciliation_consumptions%ROWTYPE;
    new_fingerprint text;
    old_fingerprint text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_new_parent_job_id IS NULL OR p_consumed_by IS NULL
       OR geo_current_identity_id() IS DISTINCT FROM p_consumed_by THEN
        RAISE EXCEPTION 'invalid or out-of-scope Dify resubmission binding request'
            USING ERRCODE = '22023';
    END IF;
    IF (p_recovery_attempt_id IS NULL) <> (p_raw_token IS NULL) THEN
        RAISE EXCEPTION 'Dify recovery attempt and reconciliation token must be supplied together'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM project_memberships membership
        JOIN identities identity ON identity.id = membership.identity_id
        WHERE membership.project_id = p_project_id
          AND membership.identity_id = p_consumed_by
          AND membership.status = 'active'
          AND membership.role IN ('owner', 'admin', 'analyst')
          AND identity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'Dify resubmission requires an active project contributor'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO new_parent FROM durable_jobs
    WHERE id = p_new_parent_job_id AND project_id = p_project_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'new Dify parent Job must exist in the enqueue transaction'
            USING ERRCODE = '23514';
    END IF;
    new_fingerprint := geo_dify_recovery_parent_fingerprint(
        p_project_id, p_new_parent_job_id
    );
    IF new_fingerprint IS NULL THEN
        RAISE EXCEPTION 'new Dify parent Job has no supported frozen business fingerprint'
            USING ERRCODE = '23514';
    END IF;
    IF p_recovery_attempt_id IS NULL THEN
        IF EXISTS (
            SELECT 1
            FROM dify_workflow_execution_attempts unresolved
            JOIN durable_jobs old_child_candidate
              ON old_child_candidate.id = unresolved.job_id
             AND old_child_candidate.project_id = unresolved.project_id
            JOIN durable_jobs old_parent_candidate
              ON old_parent_candidate.id = coalesce(
                    old_child_candidate.parent_job_id, old_child_candidate.id
                 )
             AND old_parent_candidate.project_id = unresolved.project_id
            JOIN dify_workflow_releases old_release_candidate
              ON old_release_candidate.id = unresolved.release_id
             AND old_release_candidate.project_id = unresolved.project_id
            LEFT JOIN dify_workflow_reconciliation_consumptions consumed
              ON consumed.project_id = unresolved.project_id
             AND consumed.attempt_id = unresolved.id
            WHERE unresolved.project_id = p_project_id
              AND unresolved.execution_kind = 'business'
              AND (
                    unresolved.status = 'running'
                    OR (
                        unresolved.status = 'failed'
                        AND unresolved.error_classification = 'unknown_outcome'
                    )
              )
              AND consumed.attempt_id IS NULL
              AND old_parent_candidate.id <> new_parent.id
              AND old_parent_candidate.kind = new_parent.kind
              AND (
                    (new_parent.kind = 'style.profile.build'
                     AND old_release_candidate.purpose = 'synthetic_lab.style_profile')
                    OR (new_parent.kind = 'recommendation.generate'
                        AND old_release_candidate.purpose = 'recommendations.recommendation')
              )
              AND geo_dify_recovery_parent_fingerprint(
                    p_project_id, old_parent_candidate.id
                  ) = new_fingerprint
        ) THEN
            RAISE EXCEPTION 'unresolved prior Dify outcome requires recovery_of_attempt_id and a one-time reconciliation token'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;

    SELECT * INTO old_attempt
    FROM dify_workflow_execution_attempts
    WHERE id = p_recovery_attempt_id AND project_id = p_project_id FOR SHARE;
    IF NOT FOUND OR old_attempt.execution_kind <> 'business'
       OR old_attempt.job_id IS NULL
       OR NOT (
            old_attempt.status = 'running'
            OR (old_attempt.status = 'failed'
                AND old_attempt.error_classification = 'unknown_outcome')
       ) THEN
        RAISE EXCEPTION 'Dify recovery attempt is not an unresolved business outcome in this project'
            USING ERRCODE = '23514';
    END IF;
    IF p_raw_token !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'unresolved Dify outcome requires a one-time reconciliation token'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT old_child FROM durable_jobs
    WHERE id = old_attempt.job_id AND project_id = p_project_id FOR SHARE;
    SELECT * INTO STRICT old_parent FROM durable_jobs
    WHERE id = coalesce(old_child.parent_job_id, old_child.id)
      AND project_id = p_project_id FOR SHARE;
    SELECT * INTO STRICT old_release FROM dify_workflow_releases
    WHERE id = old_attempt.release_id AND project_id = p_project_id;
    old_fingerprint := geo_dify_recovery_parent_fingerprint(
        p_project_id, old_parent.id
    );
    IF old_parent.id = new_parent.id
       OR old_parent.kind <> new_parent.kind
       OR old_fingerprint IS NULL
       OR old_fingerprint IS DISTINCT FROM new_fingerprint
       OR NOT (
            (new_parent.kind = 'style.profile.build'
             AND old_release.purpose = 'synthetic_lab.style_profile')
            OR (new_parent.kind = 'recommendation.generate'
                AND old_release.purpose = 'recommendations.recommendation')
       ) THEN
        RAISE EXCEPTION 'Dify recovery attempt does not match the new parent kind, input, or purpose'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO reconciliation
    FROM dify_workflow_attempt_reconciliations item
    WHERE item.project_id = p_project_id
      AND item.attempt_id = old_attempt.id
    ORDER BY item.issuance_number DESC
    LIMIT 1;
    IF NOT FOUND
       OR reconciliation.business_fingerprint IS DISTINCT FROM old_fingerprint
       OR reconciliation.business_fingerprint IS DISTINCT FROM new_fingerprint
       OR reconciliation.resubmission_token_hash <>
          encode(digest(convert_to(p_raw_token, 'UTF8'), 'sha256'), 'hex') THEN
        RAISE EXCEPTION 'Dify reconciliation token is invalid, stale, or for another attempt'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO existing_consumption
    FROM dify_workflow_reconciliation_consumptions consumption
    WHERE consumption.project_id = p_project_id
      AND consumption.attempt_id = old_attempt.id;
    IF FOUND THEN
        IF existing_consumption.reconciliation_id = reconciliation.id
           AND existing_consumption.new_parent_job_id = new_parent.id THEN
            RETURN old_attempt.id;
        END IF;
        RAISE EXCEPTION 'Dify reconciliation token was already consumed by another parent'
            USING ERRCODE = '23514';
    END IF;
    IF new_parent.status <> 'queued' OR new_parent.attempt_count <> 0 THEN
        RAISE EXCEPTION 'Dify reconciliation token can bind only a newly queued parent Job'
            USING ERRCODE = '23514';
    END IF;
    INSERT INTO dify_workflow_reconciliation_consumptions (
        project_id, attempt_id, reconciliation_id, new_parent_job_id,
        consumed_by, consumed_at
    ) VALUES (
        p_project_id, old_attempt.id, reconciliation.id, new_parent.id,
        p_consumed_by, clock_timestamp()
    );
    RETURN old_attempt.id;
END;
$$;

REVOKE ALL ON FUNCTION geo_issue_dify_resubmission_token(
    uuid, uuid, uuid, text, text, text, text
), geo_bind_dify_resubmission(uuid, uuid, uuid, uuid, text)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_issue_dify_resubmission_token(
    uuid, uuid, uuid, text, text, text, text
), geo_bind_dify_resubmission(uuid, uuid, uuid, uuid, text)
TO geo_app;
