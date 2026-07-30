CREATE TABLE connector_definitions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN (
        'google_search_console', 'google_analytics_4',
        'google_official_report', 'bing_official_report'
    )),
    adapter_release text NOT NULL CHECK (btrim(adapter_release) <> ''),
    runtime_release text NOT NULL CHECK (btrim(runtime_release) <> ''),
    capability jsonb NOT NULL CHECK (jsonb_typeof(capability) = 'object'),
    config_schema jsonb NOT NULL CHECK (jsonb_typeof(config_schema) = 'object'),
    config_schema_hash text NOT NULL CHECK (config_schema_hash ~ '^[0-9a-f]{64}$'),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('draft', 'approved', 'retired')),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    approved_by uuid REFERENCES identities(id),
    approved_at timestamptz,
    CONSTRAINT connector_definitions_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_definitions_release_key UNIQUE (
        project_id, kind, adapter_release
    ),
    CONSTRAINT connector_definitions_approval_shape CHECK (
        (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
        OR (status IN ('approved', 'retired')
            AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND approved_by <> created_by)
    )
);

CREATE TABLE connector_connections (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    definition_id uuid NOT NULL,
    name text NOT NULL CHECK (btrim(name) <> ''),
    secret_reference_id uuid NOT NULL,
    secret_purpose text NOT NULL,
    secret_version integer NOT NULL CHECK (secret_version > 0),
    auth_summary jsonb NOT NULL CHECK (jsonb_typeof(auth_summary) = 'object'),
    status text NOT NULL CHECK (status IN ('active', 'disabled', 'revoked')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    tested_at timestamptz,
    test_classification text CHECK (test_classification IN (
        'reachable', 'auth_failed', 'scope_denied', 'rate_limited',
        'revoked', 'transient_error'
    )),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT connector_connections_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_connections_name_key UNIQUE (project_id, name),
    CONSTRAINT connector_connections_definition_fkey FOREIGN KEY (
        definition_id, project_id
    ) REFERENCES connector_definitions(id, project_id),
    CONSTRAINT connector_connections_secret_fkey FOREIGN KEY (
        secret_reference_id, project_id, secret_purpose, secret_version
    ) REFERENCES secret_versions(reference_id, project_id, purpose, version),
    CONSTRAINT connector_connections_time_order CHECK (updated_at >= created_at),
    CONSTRAINT connector_connections_test_shape CHECK (
        (tested_at IS NULL) = (test_classification IS NULL)
    )
);

CREATE TABLE connector_scopes (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    connection_id uuid NOT NULL,
    source_locator text NOT NULL CHECK (btrim(source_locator) <> ''),
    streams jsonb NOT NULL CHECK (jsonb_typeof(streams) = 'array'),
    report_spec jsonb NOT NULL CHECK (jsonb_typeof(report_spec) = 'object'),
    locale text NOT NULL CHECK (btrim(locale) <> ''),
    date_policy jsonb NOT NULL CHECK (jsonb_typeof(date_policy) = 'object'),
    scope_hash text NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('active', 'disabled')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    CONSTRAINT connector_scopes_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_scopes_identity_key UNIQUE (
        project_id, connection_id, scope_hash
    ),
    CONSTRAINT connector_scopes_connection_fkey FOREIGN KEY (
        connection_id, project_id
    ) REFERENCES connector_connections(id, project_id)
);

CREATE TABLE connector_checkpoints (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    connection_id uuid NOT NULL,
    scope_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    cursor_state jsonb NOT NULL CHECK (jsonb_typeof(cursor_state) = 'object'),
    watermark timestamptz,
    state_hash text NOT NULL CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    advanced_by_run_id uuid,
    created_at timestamptz NOT NULL,
    CONSTRAINT connector_checkpoints_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_checkpoints_version_key UNIQUE (
        project_id, connection_id, scope_id, version
    ),
    CONSTRAINT connector_checkpoints_connection_fkey FOREIGN KEY (
        connection_id, project_id
    ) REFERENCES connector_connections(id, project_id),
    CONSTRAINT connector_checkpoints_scope_fkey FOREIGN KEY (
        scope_id, project_id
    ) REFERENCES connector_scopes(id, project_id)
);

CREATE TABLE connector_sync_runs (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    definition_id uuid NOT NULL,
    connection_id uuid NOT NULL,
    scope_id uuid NOT NULL,
    input_checkpoint_id uuid,
    input_checkpoint_hash text NOT NULL CHECK (input_checkpoint_hash ~ '^[0-9a-f]{64}$'),
    mode text NOT NULL CHECK (mode IN ('initial', 'incremental', 'backfill')),
    window_start timestamptz,
    window_end timestamptz,
    adapter_release text NOT NULL CHECK (btrim(adapter_release) <> ''),
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    durable_job_id uuid,
    status text NOT NULL CHECK (status IN (
        'planned', 'queued', 'running', 'succeeded', 'failed', 'cancelled'
    )),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    requested_by uuid NOT NULL REFERENCES identities(id),
    requested_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    error_class text,
    CONSTRAINT connector_sync_runs_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_sync_runs_idempotency_key UNIQUE (
        project_id, idempotency_key
    ),
    CONSTRAINT connector_sync_runs_definition_fkey FOREIGN KEY (
        definition_id, project_id
    ) REFERENCES connector_definitions(id, project_id),
    CONSTRAINT connector_sync_runs_connection_fkey FOREIGN KEY (
        connection_id, project_id
    ) REFERENCES connector_connections(id, project_id),
    CONSTRAINT connector_sync_runs_scope_fkey FOREIGN KEY (
        scope_id, project_id
    ) REFERENCES connector_scopes(id, project_id),
    CONSTRAINT connector_sync_runs_checkpoint_fkey FOREIGN KEY (
        input_checkpoint_id, project_id
    ) REFERENCES connector_checkpoints(id, project_id),
    CONSTRAINT connector_sync_runs_window_order CHECK (
        window_start IS NULL OR window_end IS NULL OR window_end >= window_start
    ),
    CONSTRAINT connector_sync_runs_terminal_shape CHECK (
        (status IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL)
    )
);

ALTER TABLE connector_checkpoints
ADD CONSTRAINT connector_checkpoints_run_fkey FOREIGN KEY (
    advanced_by_run_id, project_id
) REFERENCES connector_sync_runs(id, project_id);

CREATE TABLE connector_raw_artifacts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sync_run_id uuid NOT NULL,
    manifest_uri text NOT NULL CHECK (
        manifest_uri LIKE 'minio://%' OR manifest_uri LIKE 's3://%'
    ),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    schema_fingerprint text NOT NULL CHECK (schema_fingerprint ~ '^[0-9a-f]{64}$'),
    record_count bigint NOT NULL CHECK (record_count >= 0),
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    classification text NOT NULL CHECK (classification IN (
        'internal_raw', 'restricted_raw'
    )),
    retention_until timestamptz NOT NULL,
    encryption_key_reference text NOT NULL CHECK (btrim(encryption_key_reference) <> ''),
    producer_commit text NOT NULL CHECK (producer_commit ~ '^[0-9a-f]{40}$'),
    created_at timestamptz NOT NULL,
    tombstoned_at timestamptz,
    CONSTRAINT connector_raw_artifacts_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_raw_artifacts_manifest_key UNIQUE (project_id, manifest_hash),
    CONSTRAINT connector_raw_artifacts_run_fkey FOREIGN KEY (
        sync_run_id, project_id
    ) REFERENCES connector_sync_runs(id, project_id)
);

CREATE TABLE connector_schema_versions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    definition_id uuid NOT NULL,
    source_fingerprint text NOT NULL CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
    schema_document jsonb NOT NULL CHECK (jsonb_typeof(schema_document) = 'object'),
    schema_hash text NOT NULL CHECK (schema_hash ~ '^[0-9a-f]{64}$'),
    compatibility text NOT NULL CHECK (compatibility IN (
        'initial', 'compatible', 'breaking'
    )),
    diff_summary jsonb NOT NULL CHECK (jsonb_typeof(diff_summary) = 'object'),
    created_at timestamptz NOT NULL,
    CONSTRAINT connector_schema_versions_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_schema_versions_identity_key UNIQUE (
        project_id, definition_id, source_fingerprint
    ),
    CONSTRAINT connector_schema_versions_definition_fkey FOREIGN KEY (
        definition_id, project_id
    ) REFERENCES connector_definitions(id, project_id)
);

CREATE TABLE connector_projection_batches (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sync_run_id uuid NOT NULL,
    raw_artifact_id uuid NOT NULL,
    schema_version_id uuid NOT NULL,
    projection_kind text NOT NULL CHECK (btrim(projection_kind) <> ''),
    row_count bigint NOT NULL CHECK (row_count >= 0),
    dataset_hash text NOT NULL CHECK (dataset_hash ~ '^[0-9a-f]{64}$'),
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    created_at timestamptz NOT NULL,
    CONSTRAINT connector_projection_batches_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_projection_batches_run_kind_key UNIQUE (
        project_id, sync_run_id, projection_kind
    ),
    CONSTRAINT connector_projection_batches_run_fkey FOREIGN KEY (
        sync_run_id, project_id
    ) REFERENCES connector_sync_runs(id, project_id),
    CONSTRAINT connector_projection_batches_raw_fkey FOREIGN KEY (
        raw_artifact_id, project_id
    ) REFERENCES connector_raw_artifacts(id, project_id),
    CONSTRAINT connector_projection_batches_schema_fkey FOREIGN KEY (
        schema_version_id, project_id
    ) REFERENCES connector_schema_versions(id, project_id)
);

CREATE TABLE connector_gsc_projection_rows (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    projection_batch_id uuid NOT NULL,
    row_index integer NOT NULL CHECK (row_index >= 0),
    stream text NOT NULL CHECK (btrim(stream) <> ''),
    observed_date date NOT NULL,
    query text,
    page text,
    country text,
    device text,
    clicks numeric,
    impressions numeric,
    ctr numeric,
    position numeric,
    row_data jsonb NOT NULL CHECK (jsonb_typeof(row_data) = 'object'),
    row_hash text NOT NULL CHECK (row_hash ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (project_id, projection_batch_id, row_index),
    CONSTRAINT connector_gsc_rows_batch_fkey FOREIGN KEY (
        projection_batch_id, project_id
    ) REFERENCES connector_projection_batches(id, project_id) ON DELETE CASCADE
);

CREATE TABLE connector_ga4_projection_rows (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    projection_batch_id uuid NOT NULL,
    row_index integer NOT NULL CHECK (row_index >= 0),
    observed_date date NOT NULL,
    dimensions jsonb NOT NULL CHECK (jsonb_typeof(dimensions) = 'object'),
    metrics jsonb NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
    row_data jsonb NOT NULL CHECK (jsonb_typeof(row_data) = 'object'),
    row_hash text NOT NULL CHECK (row_hash ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (project_id, projection_batch_id, row_index),
    CONSTRAINT connector_ga4_rows_batch_fkey FOREIGN KEY (
        projection_batch_id, project_id
    ) REFERENCES connector_projection_batches(id, project_id) ON DELETE CASCADE
);

CREATE TABLE connector_freshness (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    connection_id uuid NOT NULL,
    scope_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    expected_watermark timestamptz,
    observed_watermark timestamptz,
    lag_seconds bigint CHECK (lag_seconds IS NULL OR lag_seconds >= 0),
    status text NOT NULL CHECK (status IN ('fresh', 'stale', 'unknown')),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    observed_at timestamptz NOT NULL,
    CONSTRAINT connector_freshness_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_freshness_run_key UNIQUE (project_id, sync_run_id),
    CONSTRAINT connector_freshness_connection_fkey FOREIGN KEY (
        connection_id, project_id
    ) REFERENCES connector_connections(id, project_id),
    CONSTRAINT connector_freshness_scope_fkey FOREIGN KEY (
        scope_id, project_id
    ) REFERENCES connector_scopes(id, project_id),
    CONSTRAINT connector_freshness_run_fkey FOREIGN KEY (
        sync_run_id, project_id
    ) REFERENCES connector_sync_runs(id, project_id)
);

CREATE TABLE connector_errors (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sync_run_id uuid NOT NULL,
    error_class text NOT NULL CHECK (error_class IN (
        'auth', 'quota', 'rate', 'schema', 'revoked', 'transient', 'permanent'
    )),
    error_code text NOT NULL CHECK (btrim(error_code) <> ''),
    operator_action text NOT NULL CHECK (btrim(operator_action) <> ''),
    retryable boolean NOT NULL,
    sanitized_details jsonb NOT NULL CHECK (jsonb_typeof(sanitized_details) = 'object'),
    occurred_at timestamptz NOT NULL,
    CONSTRAINT connector_errors_scope_key UNIQUE (id, project_id),
    CONSTRAINT connector_errors_run_fkey FOREIGN KEY (
        sync_run_id, project_id
    ) REFERENCES connector_sync_runs(id, project_id)
);

CREATE TABLE connector_job_specs (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    run_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind = 'connector.sync'),
    spec_hash text NOT NULL CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    spec_payload jsonb NOT NULL CHECK (jsonb_typeof(spec_payload) = 'object'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, job_id),
    CONSTRAINT connector_job_specs_job_fkey FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT connector_job_specs_run_fkey FOREIGN KEY (run_id, project_id)
        REFERENCES connector_sync_runs(id, project_id)
);

CREATE FUNCTION geo_enqueue_connector_sync(
    p_project_id uuid,
    p_run_id uuid,
    p_expected_run_version integer,
    p_spec_hash text,
    p_spec_payload jsonb,
    p_max_attempts integer
) RETURNS TABLE (job_id uuid, input_hash text, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE run connector_sync_runs%ROWTYPE;
DECLARE durable durable_jobs%ROWTYPE;
DECLARE stored_spec connector_job_specs%ROWTYPE;
DECLARE outbox_key text;
DECLARE was_replayed boolean := false;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_run_id IS NULL
       OR p_expected_run_version IS NULL OR p_expected_run_version < 1
       OR p_spec_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_spec_payload) <> 'object'
       OR p_spec_payload->'schema_version' <> '1'::jsonb
       OR p_spec_payload->>'kind' <> 'connector.sync'
       OR p_spec_payload->>'run_id' <> p_run_id::text
       OR p_spec_payload->>'expected_run_version' <> p_expected_run_version::text
       OR p_spec_payload->>'plan_hash' !~ '^[0-9a-f]{64}$'
       OR (SELECT count(*) FROM jsonb_object_keys(p_spec_payload)) <> 6
       OR NOT (p_spec_payload ? 'project_id')
       OR p_spec_payload->>'project_id' <> p_project_id::text
       OR encode(digest(convert_to(geo_jsonb_canonical_text(p_spec_payload), 'UTF8'), 'sha256'), 'hex')
            <> p_spec_hash
       OR p_max_attempts IS NULL OR p_max_attempts < 1 OR p_max_attempts > 10 THEN
        RAISE EXCEPTION 'Connector sync enqueue input is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO run FROM connector_sync_runs
    WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Connector Sync Run does not exist' USING ERRCODE = 'P0002';
    END IF;
    IF run.idempotency_key <> 'connector.sync:' || (p_spec_payload->>'plan_hash') THEN
        RAISE EXCEPTION 'Connector Sync Run differs from frozen plan'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO durable FROM durable_jobs
    WHERE project_id = p_project_id AND kind = 'connector.sync'
      AND idempotency_key = run.idempotency_key AND replay_nonce = 0
    FOR SHARE;
    IF FOUND THEN
        was_replayed := true;
        IF durable.input_hash <> p_spec_hash OR durable.max_attempts <> p_max_attempts THEN
            RAISE EXCEPTION 'Connector Job idempotency key changed input'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO stored_spec FROM connector_job_specs AS spec
        WHERE spec.project_id = p_project_id AND spec.job_id = durable.id FOR SHARE;
        IF NOT FOUND OR stored_spec.run_id <> p_run_id
           OR stored_spec.spec_hash <> p_spec_hash
           OR stored_spec.spec_payload IS DISTINCT FROM p_spec_payload THEN
            RAISE EXCEPTION 'Connector Job replay differs from immutable spec'
                USING ERRCODE = '23505';
        END IF;
    ELSE
        IF run.status <> 'planned' OR run.version <> p_expected_run_version THEN
            RAISE EXCEPTION 'Connector Sync Run enqueue lost optimistic ownership'
                USING ERRCODE = '40001';
        END IF;
        INSERT INTO durable_jobs(
            project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, replay_nonce, created_at, updated_at
        ) VALUES (
            p_project_id, 'connector.sync', 'queued', 0, p_spec_hash,
            run.idempotency_key, p_max_attempts, clock_timestamp(), 0,
            clock_timestamp(), clock_timestamp()
        ) RETURNING * INTO durable;
        INSERT INTO connector_job_specs(
            project_id, job_id, run_id, kind, spec_hash, spec_payload, created_at
        ) VALUES (
            p_project_id, durable.id, p_run_id, 'connector.sync', p_spec_hash,
            p_spec_payload, clock_timestamp()
        );
        outbox_key := 'wake:connector.sync:' || run.idempotency_key;
        INSERT INTO broker_outbox(
            project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            p_project_id, durable.id, 'connector.sync',
            jsonb_build_object('job_id', durable.id::text, 'project_id', p_project_id::text),
            outbox_key, clock_timestamp()
        );
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
        ) VALUES (
            p_project_id, durable.id, 'job_enqueued', 'connector-producer', 0,
            jsonb_build_object('run_id', p_run_id, 'spec_hash', p_spec_hash),
            clock_timestamp()
        );
        UPDATE connector_sync_runs
        SET status = 'queued', durable_job_id = durable.id, version = version + 1
        WHERE project_id = p_project_id AND id = p_run_id
          AND status = 'planned' AND version = p_expected_run_version;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Connector Sync Run enqueue was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    RETURN QUERY SELECT durable.id, durable.input_hash, was_replayed;
END;
$$;

CREATE INDEX connector_sync_runs_queue_idx
ON connector_sync_runs(project_id, status, requested_at, id);
CREATE INDEX connector_freshness_status_idx
ON connector_freshness(project_id, status, observed_at DESC);
CREATE INDEX connector_errors_run_idx
ON connector_errors(project_id, sync_run_id, occurred_at DESC);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'connector_definitions', 'connector_connections', 'connector_scopes',
        'connector_checkpoints', 'connector_sync_runs', 'connector_raw_artifacts',
        'connector_schema_versions', 'connector_projection_batches',
        'connector_gsc_projection_rows', 'connector_ga4_projection_rows',
        'connector_freshness', 'connector_errors', 'connector_job_specs'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

REVOKE ALL ON connector_definitions, connector_connections, connector_scopes,
    connector_checkpoints, connector_sync_runs, connector_raw_artifacts,
    connector_schema_versions, connector_projection_batches,
    connector_gsc_projection_rows, connector_ga4_projection_rows,
    connector_freshness, connector_errors, connector_job_specs
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

GRANT SELECT, INSERT, UPDATE ON connector_definitions, connector_connections,
    connector_scopes, connector_checkpoints, connector_sync_runs,
    connector_raw_artifacts, connector_schema_versions,
    connector_projection_batches, connector_freshness, connector_errors,
    connector_job_specs, connector_gsc_projection_rows, connector_ga4_projection_rows
TO geo_app, geo_worker;
GRANT SELECT ON connector_definitions, connector_connections, connector_scopes,
    connector_checkpoints, connector_sync_runs, connector_raw_artifacts,
    connector_schema_versions, connector_projection_batches,
    connector_gsc_projection_rows, connector_ga4_projection_rows,
    connector_freshness, connector_errors, connector_job_specs
TO geo_readonly;

REVOKE ALL ON FUNCTION geo_enqueue_connector_sync(
    uuid, uuid, integer, text, jsonb, integer
) FROM PUBLIC, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_connector_sync(
    uuid, uuid, integer, text, jsonb, integer
) TO geo_app;
