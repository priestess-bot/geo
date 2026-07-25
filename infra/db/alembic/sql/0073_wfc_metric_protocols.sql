-- Metric definitions and their evidence context are a governed release, not
-- arbitrary JSON embedded by an analysis caller. Analysis manifests are
-- immutable, secret-free membership records. Answer bytes remain in their
-- governed Provider/Workflow C artifact stores.

CREATE TABLE workflow_c_metric_protocol_versions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    series_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    supersedes_protocol_id uuid,
    status text NOT NULL CHECK (status IN ('draft', 'in_review', 'approved', 'retired')),
    protocol_hash text NOT NULL CHECK (protocol_hash ~ '^[0-9a-f]{64}$'),
    definition jsonb NOT NULL CHECK (
        jsonb_typeof(definition) = 'object'
        AND definition->'schema_version' = '1'::jsonb
    ),
    created_by text NOT NULL CHECK (btrim(created_by) <> ''),
    submitted_by text,
    submitted_at timestamptz,
    approved_by text,
    approved_at timestamptz,
    retired_by text,
    retired_at timestamptz,
    decision_reason text,
    aggregate_version integer NOT NULL DEFAULT 1 CHECK (aggregate_version > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, protocol_hash),
    UNIQUE (project_id, series_id, version),
    FOREIGN KEY (supersedes_protocol_id, project_id)
        REFERENCES workflow_c_metric_protocol_versions(id, project_id),
    CHECK ((version = 1) = (supersedes_protocol_id IS NULL)),
    CHECK (created_at <= updated_at),
    CHECK (
        (status = 'draft'
            AND submitted_by IS NULL AND submitted_at IS NULL
            AND approved_by IS NULL AND approved_at IS NULL
            AND retired_by IS NULL AND retired_at IS NULL AND decision_reason IS NULL)
        OR (status = 'in_review'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND approved_by IS NULL AND approved_at IS NULL
            AND retired_by IS NULL AND retired_at IS NULL AND decision_reason IS NULL)
        OR (status = 'approved'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND retired_by IS NULL AND retired_at IS NULL
            AND decision_reason IS NOT NULL)
        OR (status = 'retired'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND retired_by IS NOT NULL AND retired_at IS NOT NULL
            AND decision_reason IS NOT NULL)
    )
);

CREATE TABLE workflow_c_metric_protocol_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_id uuid NOT NULL,
    command_scope text NOT NULL CHECK (command_scope IN ('create', 'submit', 'approve', 'retire')),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    result_status text NOT NULL CHECK (
        result_status IN ('draft', 'in_review', 'approved', 'retired')
    ),
    result_aggregate_version integer NOT NULL CHECK (result_aggregate_version > 0),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, protocol_id, command_scope, idempotency_key_hash),
    FOREIGN KEY (protocol_id, project_id)
        REFERENCES workflow_c_metric_protocol_versions(id, project_id)
);

CREATE TABLE workflow_c_analysis_input_manifests (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    sampling_run_id uuid NOT NULL,
    sampling_run_version integer NOT NULL CHECK (sampling_run_version > 0),
    sampling_suite_hash text NOT NULL CHECK (sampling_suite_hash ~ '^[0-9a-f]{64}$'),
    metric_protocol_id uuid NOT NULL,
    metric_protocol_hash text NOT NULL CHECK (metric_protocol_hash ~ '^[0-9a-f]{64}$'),
    fact_snapshot_id uuid NOT NULL,
    fact_snapshot_hash text NOT NULL CHECK (fact_snapshot_hash ~ '^[0-9a-f]{64}$'),
    prompt_release_id uuid NOT NULL,
    prompt_release_hash text NOT NULL CHECK (prompt_release_hash ~ '^[0-9a-f]{64}$'),
    corpus_version_id uuid NOT NULL,
    corpus_version_hash text NOT NULL CHECK (corpus_version_hash ~ '^[0-9a-f]{64}$'),
    baseline_snapshot_hash text CHECK (
        baseline_snapshot_hash IS NULL OR baseline_snapshot_hash ~ '^[0-9a-f]{64}$'
    ),
    source_stratum_hash text NOT NULL CHECK (source_stratum_hash ~ '^[0-9a-f]{64}$'),
    capture_method text NOT NULL CHECK (capture_method IN (
        'provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui'
    )),
    planned_slot_count integer NOT NULL CHECK (planned_slot_count > 0),
    observation_count integer NOT NULL CHECK (
        observation_count >= 0 AND observation_count <= planned_slot_count
    ),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND payload->'schema_version' = '1'::jsonb
    ),
    frozen_by text NOT NULL CHECK (btrim(frozen_by) <> ''),
    frozen_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, manifest_hash),
    FOREIGN KEY (sampling_run_id, project_id)
        REFERENCES workflow_c_sampling_runs(id, project_id),
    FOREIGN KEY (metric_protocol_id, project_id)
        REFERENCES workflow_c_metric_protocol_versions(id, project_id)
);

CREATE TABLE workflow_c_analysis_input_manifest_items (
    manifest_id uuid NOT NULL,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    task_id uuid NOT NULL,
    task_key text NOT NULL CHECK (task_key ~ '^[0-9a-f]{64}$'),
    question_id text NOT NULL CHECK (btrim(question_id) <> ''),
    question_version text NOT NULL CHECK (btrim(question_version) <> ''),
    question_cluster text NOT NULL CHECK (btrim(question_cluster) <> ''),
    repetition integer NOT NULL CHECK (repetition > 0),
    observation_id uuid,
    observation_hash text CHECK (
        observation_hash IS NULL OR observation_hash ~ '^[0-9a-f]{64}$'
    ),
    observation_status text NOT NULL CHECK (
        observation_status IN ('complete', 'ineligible', 'missing')
    ),
    attempt_id uuid,
    source_job_id uuid,
    provider_model_attempt_id uuid,
    output_hash text CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    artifact_kind text NOT NULL CHECK (
        artifact_kind IN ('provider', 'manual', 'unavailable')
    ),
    artifact_id uuid,
    artifact_manifest_hash text CHECK (
        artifact_manifest_hash IS NULL OR artifact_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    artifact_content_hash text CHECK (
        artifact_content_hash IS NULL OR artifact_content_hash ~ '^[0-9a-f]{64}$'
    ),
    actual_location_hash text CHECK (
        actual_location_hash IS NULL OR actual_location_hash ~ '^[0-9a-f]{64}$'
    ),
    item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (manifest_id, ordinal),
    UNIQUE (manifest_id, task_id),
    UNIQUE (manifest_id, task_key),
    FOREIGN KEY (manifest_id, project_id)
        REFERENCES workflow_c_analysis_input_manifests(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, project_id)
        REFERENCES workflow_c_sampling_tasks(id, project_id),
    FOREIGN KEY (observation_id, project_id)
        REFERENCES workflow_c_sampling_observations(id, project_id),
    FOREIGN KEY (attempt_id, project_id)
        REFERENCES workflow_c_sampling_attempts(id, project_id),
    FOREIGN KEY (source_job_id, project_id)
        REFERENCES durable_jobs(id, project_id),
    CHECK ((observation_status = 'missing') = (observation_id IS NULL)),
    CHECK ((observation_id IS NULL) = (observation_hash IS NULL)),
    CHECK ((attempt_id IS NULL) = (source_job_id IS NULL)),
    CHECK (
        (artifact_kind = 'provider' AND provider_model_attempt_id IS NOT NULL
            AND output_hash IS NOT NULL AND artifact_id IS NULL
            AND artifact_manifest_hash IS NOT NULL AND artifact_content_hash IS NOT NULL)
        OR (artifact_kind = 'manual' AND provider_model_attempt_id IS NULL
            AND output_hash IS NULL AND artifact_id IS NOT NULL
            AND artifact_manifest_hash IS NOT NULL AND artifact_content_hash IS NOT NULL)
        OR (artifact_kind = 'unavailable' AND provider_model_attempt_id IS NULL
            AND output_hash IS NULL AND artifact_id IS NULL
            AND artifact_manifest_hash IS NULL AND artifact_content_hash IS NULL)
    )
);

CREATE FUNCTION geo_assert_workflow_c_metric_protocol_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE predecessor workflow_c_metric_protocol_versions%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Metric Protocol history cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' OR NEW.aggregate_version <> 1
           OR NEW.created_at <> NEW.updated_at THEN
            RAISE EXCEPTION 'Metric Protocol must begin as draft version one'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.version = 1 THEN
            IF NEW.series_id <> NEW.id OR NEW.supersedes_protocol_id IS NOT NULL THEN
                RAISE EXCEPTION 'Metric Protocol initial series identity is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            SELECT * INTO predecessor FROM workflow_c_metric_protocol_versions
             WHERE project_id = NEW.project_id AND id = NEW.supersedes_protocol_id;
            IF predecessor.id IS NULL OR predecessor.series_id <> NEW.series_id
               OR predecessor.version + 1 <> NEW.version
               OR predecessor.status NOT IN ('approved', 'retired') THEN
                RAISE EXCEPTION 'Metric Protocol predecessor is not an approved exact version'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(NEW.id, NEW.project_id, NEW.series_id, NEW.version,
           NEW.supersedes_protocol_id, NEW.protocol_hash, NEW.definition,
           NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.project_id, OLD.series_id, OLD.version,
           OLD.supersedes_protocol_id, OLD.protocol_hash, OLD.definition,
           OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'Metric Protocol definition is immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.aggregate_version <> OLD.aggregate_version + 1 OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'Metric Protocol aggregate version is stale' USING ERRCODE = '40001';
    END IF;
    IF OLD.status = 'draft' AND NEW.status = 'in_review'
       AND NEW.submitted_by IS NOT NULL AND NEW.submitted_at IS NOT NULL
       AND NEW.approved_by IS NULL AND NEW.approved_at IS NULL
       AND NEW.retired_by IS NULL AND NEW.retired_at IS NULL
       AND NEW.decision_reason IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'in_review' AND NEW.status = 'approved'
       AND NEW.submitted_by = OLD.submitted_by AND NEW.submitted_at = OLD.submitted_at
       AND NEW.approved_by IS NOT NULL AND NEW.approved_by <> NEW.created_by
       AND NEW.approved_at IS NOT NULL AND NEW.decision_reason IS NOT NULL
       AND NEW.retired_by IS NULL AND NEW.retired_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'approved' AND NEW.status = 'retired'
       AND NEW.submitted_by = OLD.submitted_by AND NEW.submitted_at = OLD.submitted_at
       AND NEW.approved_by = OLD.approved_by AND NEW.approved_at = OLD.approved_at
       AND NEW.retired_by IS NOT NULL AND NEW.retired_at IS NOT NULL
       AND NEW.decision_reason IS NOT NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Metric Protocol lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER workflow_c_metric_protocol_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON workflow_c_metric_protocol_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_metric_protocol_change();

CREATE TRIGGER workflow_c_metric_protocol_receipts_immutable
BEFORE UPDATE OR DELETE ON workflow_c_metric_protocol_command_receipts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER workflow_c_analysis_manifests_immutable
BEFORE UPDATE OR DELETE ON workflow_c_analysis_input_manifests
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER workflow_c_analysis_manifest_items_immutable
BEFORE UPDATE OR DELETE ON workflow_c_analysis_input_manifest_items
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE FUNCTION geo_create_workflow_c_metric_protocol(
    p_project_id uuid, p_protocol_id uuid, p_series_id uuid, p_version integer,
    p_supersedes_protocol_id uuid, p_protocol_hash text, p_definition jsonb,
    p_created_by text, p_idempotency_key_hash text, p_input_hash text,
    p_occurred_at timestamptz
) RETURNS SETOF workflow_c_metric_protocol_versions
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE existing workflow_c_metric_protocol_command_receipts%ROWTYPE;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_protocol_id IS NULL OR p_series_id IS NULL OR p_version IS NULL OR p_version < 1
       OR p_protocol_hash !~ '^[0-9a-f]{64}$'
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR btrim(coalesce(p_created_by, '')) = ''
       OR p_occurred_at IS NULL OR jsonb_typeof(p_definition) <> 'object'
       OR p_definition->'schema_version' <> '1'::jsonb
       OR encode(digest(convert_to(geo_workflow_c_python_canonical_text(p_definition), 'UTF8'), 'sha256'), 'hex') <> p_protocol_hash THEN
        RAISE EXCEPTION 'Metric Protocol create input is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM workflow_c_metric_protocol_command_receipts
     WHERE project_id = p_project_id AND protocol_id = p_protocol_id
       AND command_scope = 'create' AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash THEN
            RAISE EXCEPTION 'Metric Protocol Idempotency-Key was reused with different input'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT * FROM workflow_c_metric_protocol_versions
         WHERE project_id = p_project_id AND id = p_protocol_id;
        RETURN;
    END IF;
    INSERT INTO workflow_c_metric_protocol_versions(
        id, project_id, series_id, version, supersedes_protocol_id, status,
        protocol_hash, definition, created_by, created_at, updated_at
    ) VALUES (
        p_protocol_id, p_project_id, p_series_id, p_version, p_supersedes_protocol_id,
        'draft', p_protocol_hash, p_definition, p_created_by, p_occurred_at, p_occurred_at
    );
    INSERT INTO workflow_c_metric_protocol_command_receipts(
        project_id, protocol_id, command_scope, idempotency_key_hash, input_hash,
        result_status, result_aggregate_version, created_at
    ) VALUES (p_project_id, p_protocol_id, 'create', p_idempotency_key_hash,
        p_input_hash, 'draft', 1, p_occurred_at);
    RETURN QUERY SELECT * FROM workflow_c_metric_protocol_versions
     WHERE project_id = p_project_id AND id = p_protocol_id;
END;
$$;

CREATE FUNCTION geo_transition_workflow_c_metric_protocol(
    p_project_id uuid, p_protocol_id uuid, p_expected_aggregate_version integer,
    p_target_status text, p_actor_id text, p_reason text,
    p_idempotency_key_hash text, p_input_hash text, p_occurred_at timestamptz
) RETURNS SETOF workflow_c_metric_protocol_versions
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE current_row workflow_c_metric_protocol_versions%ROWTYPE;
DECLARE existing workflow_c_metric_protocol_command_receipts%ROWTYPE;
DECLARE command_name text;
BEGIN
    command_name := CASE p_target_status
        WHEN 'in_review' THEN 'submit' WHEN 'approved' THEN 'approve'
        WHEN 'retired' THEN 'retire' ELSE NULL END;
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_protocol_id IS NULL OR p_expected_aggregate_version IS NULL
       OR p_expected_aggregate_version < 1 OR command_name IS NULL
       OR btrim(coalesce(p_actor_id, '')) = ''
       OR (p_target_status IN ('approved', 'retired') AND btrim(coalesce(p_reason, '')) = '')
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_occurred_at IS NULL THEN
        RAISE EXCEPTION 'Metric Protocol transition input is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM workflow_c_metric_protocol_command_receipts
     WHERE project_id = p_project_id AND protocol_id = p_protocol_id
       AND command_scope = command_name AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash THEN
            RAISE EXCEPTION 'Metric Protocol Idempotency-Key was reused with different input'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT * FROM workflow_c_metric_protocol_versions
         WHERE project_id = p_project_id AND id = p_protocol_id;
        RETURN;
    END IF;
    SELECT * INTO current_row FROM workflow_c_metric_protocol_versions
     WHERE project_id = p_project_id AND id = p_protocol_id FOR UPDATE;
    IF current_row.id IS NULL OR current_row.aggregate_version <> p_expected_aggregate_version THEN
        RAISE EXCEPTION 'Metric Protocol optimistic version check failed' USING ERRCODE = '40001';
    END IF;
    UPDATE workflow_c_metric_protocol_versions SET
        status = p_target_status,
        submitted_by = CASE WHEN p_target_status = 'in_review' THEN p_actor_id ELSE submitted_by END,
        submitted_at = CASE WHEN p_target_status = 'in_review' THEN p_occurred_at ELSE submitted_at END,
        approved_by = CASE WHEN p_target_status = 'approved' THEN p_actor_id ELSE approved_by END,
        approved_at = CASE WHEN p_target_status = 'approved' THEN p_occurred_at ELSE approved_at END,
        retired_by = CASE WHEN p_target_status = 'retired' THEN p_actor_id ELSE retired_by END,
        retired_at = CASE WHEN p_target_status = 'retired' THEN p_occurred_at ELSE retired_at END,
        decision_reason = CASE WHEN p_target_status IN ('approved', 'retired') THEN p_reason ELSE decision_reason END,
        aggregate_version = aggregate_version + 1,
        updated_at = p_occurred_at
     WHERE project_id = p_project_id AND id = p_protocol_id;
    INSERT INTO workflow_c_metric_protocol_command_receipts(
        project_id, protocol_id, command_scope, idempotency_key_hash, input_hash,
        result_status, result_aggregate_version, created_at
    ) VALUES (p_project_id, p_protocol_id, command_name, p_idempotency_key_hash,
        p_input_hash, p_target_status, p_expected_aggregate_version + 1, p_occurred_at);
    RETURN QUERY SELECT * FROM workflow_c_metric_protocol_versions
     WHERE project_id = p_project_id AND id = p_protocol_id;
END;
$$;

CREATE INDEX workflow_c_metric_protocol_project_status_idx
ON workflow_c_metric_protocol_versions(project_id, status, updated_at DESC);
CREATE INDEX workflow_c_analysis_manifest_run_idx
ON workflow_c_analysis_input_manifests(project_id, sampling_run_id, frozen_at DESC);
CREATE INDEX workflow_c_analysis_manifest_protocol_idx
ON workflow_c_analysis_input_manifests(project_id, metric_protocol_id, frozen_at DESC);
CREATE INDEX workflow_c_analysis_manifest_item_observation_idx
ON workflow_c_analysis_input_manifest_items(project_id, observation_id)
WHERE observation_id IS NOT NULL;
CREATE INDEX workflow_c_analysis_manifest_item_source_job_idx
ON workflow_c_analysis_input_manifest_items(project_id, source_job_id)
WHERE source_job_id IS NOT NULL;

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'workflow_c_metric_protocol_versions',
        'workflow_c_metric_protocol_command_receipts',
        'workflow_c_analysis_input_manifests',
        'workflow_c_analysis_input_manifest_items'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

REVOKE ALL ON workflow_c_metric_protocol_versions,
    workflow_c_metric_protocol_command_receipts,
    workflow_c_analysis_input_manifests,
    workflow_c_analysis_input_manifest_items
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON workflow_c_metric_protocol_versions TO geo_app, geo_worker;
GRANT SELECT ON workflow_c_analysis_input_manifests,
    workflow_c_analysis_input_manifest_items TO geo_app, geo_worker;

REVOKE ALL ON FUNCTION geo_create_workflow_c_metric_protocol(
    uuid, uuid, uuid, integer, uuid, text, jsonb, text, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_transition_workflow_c_metric_protocol(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_create_workflow_c_metric_protocol(
    uuid, uuid, uuid, integer, uuid, text, jsonb, text, text, text, timestamptz
) TO geo_app;
GRANT EXECUTE ON FUNCTION geo_transition_workflow_c_metric_protocol(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
) TO geo_app;

REVOKE ALL ON FUNCTION geo_assert_workflow_c_metric_protocol_change()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

COMMENT ON TABLE workflow_c_analysis_input_manifests IS
    'Immutable secret-free membership frozen before a Workflow C analysis Job is admitted.';
