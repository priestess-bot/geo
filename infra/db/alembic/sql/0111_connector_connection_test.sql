CREATE TABLE connector_connection_tests (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    connection_id uuid NOT NULL,
    definition_id uuid NOT NULL,
    durable_job_id uuid NOT NULL,
    adapter_release text NOT NULL CHECK (btrim(adapter_release) <> ''),
    secret_reference_id uuid NOT NULL,
    secret_purpose text NOT NULL CHECK (secret_purpose LIKE 'connector.%'),
    secret_version integer NOT NULL CHECK (secret_version > 0),
    status text NOT NULL CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled'
    )),
    version integer NOT NULL CHECK (version > 0),
    requested_by uuid NOT NULL REFERENCES identities(id),
    requested_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    result_hash text CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
    error_class text,
    UNIQUE (id, project_id),
    UNIQUE (project_id, durable_job_id),
    FOREIGN KEY (connection_id, project_id)
      REFERENCES connector_connections(id, project_id),
    FOREIGN KEY (definition_id, project_id)
      REFERENCES connector_definitions(id, project_id),
    FOREIGN KEY (durable_job_id, project_id)
      REFERENCES durable_jobs(id, project_id),
    FOREIGN KEY (secret_reference_id, project_id, secret_purpose, secret_version)
      REFERENCES secret_versions(reference_id, project_id, purpose, version),
    CHECK (requested_at <= COALESCE(started_at, requested_at)),
    CHECK (COALESCE(started_at, requested_at) <= COALESCE(finished_at, started_at, requested_at))
);

CREATE TABLE connector_connection_test_specs (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    test_id uuid NOT NULL,
    spec_hash text NOT NULL CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    spec_payload jsonb NOT NULL CHECK (jsonb_typeof(spec_payload) = 'object'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, job_id),
    UNIQUE (project_id, test_id),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id),
    FOREIGN KEY (test_id, project_id) REFERENCES connector_connection_tests(id, project_id)
      DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX connector_connection_tests_connection_idx
ON connector_connection_tests(project_id, connection_id, requested_at DESC);

CREATE FUNCTION geo_enqueue_connector_connection_test(
    p_project_id uuid, p_test_id uuid, p_connection_id uuid,
    p_expected_connection_version integer, p_requested_by uuid,
    p_requested_at timestamptz
) RETURNS TABLE(test_id uuid, job_id uuid, status text, replayed boolean)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off
AS $$
DECLARE connection_row connector_connections%ROWTYPE;
DECLARE definition connector_definitions%ROWTYPE;
DECLARE stored connector_connection_tests%ROWTYPE;
DECLARE durable durable_jobs%ROWTYPE;
DECLARE payload jsonb;
DECLARE payload_hash text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_test_id IS NULL OR p_connection_id IS NULL OR p_requested_by IS NULL
       OR p_expected_connection_version < 1 OR p_requested_at IS NULL THEN
        RAISE EXCEPTION 'Connector connection test command is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'connector-connection-test:' || p_project_id::text || ':' || p_test_id::text, 0
    ));
    SELECT * INTO stored FROM connector_connection_tests
     WHERE project_id = p_project_id AND id = p_test_id;
    IF FOUND THEN
        RETURN QUERY SELECT stored.id, stored.durable_job_id, stored.status, true;
        RETURN;
    END IF;
    SELECT * INTO connection_row FROM connector_connections
     WHERE project_id = p_project_id AND id = p_connection_id FOR SHARE;
    SELECT * INTO definition FROM connector_definitions
     WHERE project_id = p_project_id AND id = connection_row.definition_id FOR SHARE;
    IF connection_row.id IS NULL OR definition.id IS NULL
       OR connection_row.status <> 'active'
       OR connection_row.version <> p_expected_connection_version
       OR definition.status <> 'approved'
       OR NOT EXISTS (
            SELECT 1 FROM secret_versions secret
             WHERE secret.reference_id = connection_row.secret_reference_id
               AND secret.project_id = p_project_id
               AND secret.purpose = connection_row.secret_purpose
               AND secret.version = connection_row.secret_version
               AND secret.status = 'active'
       ) THEN
        RAISE EXCEPTION 'Connector Connection changed or its exact Secret is not active'
            USING ERRCODE = '23514';
    END IF;
    payload := jsonb_build_object(
        'schema_version', 1, 'kind', 'connector.connection_test',
        'project_id', p_project_id, 'test_id', p_test_id,
        'connection_id', connection_row.id, 'connection_version', connection_row.version,
        'definition_id', definition.id, 'connector_kind', definition.kind,
        'adapter_release', definition.adapter_release,
        'secret_reference_id', connection_row.secret_reference_id,
        'secret_purpose', connection_row.secret_purpose,
        'secret_version', connection_row.secret_version
    );
    payload_hash := encode(digest(convert_to(
        geo_jsonb_sampling_canonical_text(payload), 'UTF8'), 'sha256'), 'hex');
    INSERT INTO durable_jobs(
        project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, replay_nonce, created_at, updated_at
    ) VALUES (
        p_project_id, 'connector.connection_test', 'queued', 0, payload_hash,
        'connector.connection_test:' || p_test_id::text, 2, p_requested_at,
        0, p_requested_at, p_requested_at
    ) RETURNING * INTO durable;
    INSERT INTO connector_connection_tests(
        id, project_id, connection_id, definition_id, durable_job_id,
        adapter_release, secret_reference_id, secret_purpose, secret_version,
        status, version, requested_by, requested_at
    ) VALUES (
        p_test_id, p_project_id, connection_row.id, definition.id, durable.id,
        definition.adapter_release, connection_row.secret_reference_id,
        connection_row.secret_purpose, connection_row.secret_version,
        'queued', 1, p_requested_by, p_requested_at
    );
    INSERT INTO connector_connection_test_specs(
        project_id, job_id, test_id, spec_hash, spec_payload, created_at
    ) VALUES (p_project_id, durable.id, p_test_id, payload_hash, payload, p_requested_at);
    INSERT INTO broker_outbox(
        project_id, job_id, topic, payload, idempotency_key, available_at
    ) VALUES (
        p_project_id, durable.id, 'connector.connection_test.queued',
        jsonb_build_object('job_id', durable.id::text, 'project_id', p_project_id::text),
        'wake:connector.connection_test:' || p_test_id::text, p_requested_at
    );
    RETURN QUERY SELECT p_test_id, durable.id, 'queued'::text, false;
END;
$$;

CREATE FUNCTION geo_reconcile_connector_connection_test_status()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off
AS $$
BEGIN
    IF NEW.kind <> 'connector.connection_test'
       OR NEW.status NOT IN ('failed', 'dead_lettered', 'cancelled') THEN
        RETURN NEW;
    END IF;
    UPDATE connector_connection_tests
       SET status = CASE WHEN NEW.status = 'cancelled' THEN 'cancelled' ELSE 'failed' END,
           version = version + 1, finished_at = clock_timestamp(),
           error_class = CASE WHEN NEW.status = 'cancelled' THEN NULL
                              ELSE COALESCE(NEW.error_detail->>'classification', 'unknown') END
     WHERE project_id = NEW.project_id AND durable_job_id = NEW.id
       AND status IN ('queued', 'running');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Connector connection test terminal state was not projected'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER connector_connection_test_status_reconcile
AFTER UPDATE OF status ON durable_jobs FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION geo_reconcile_connector_connection_test_status();

ALTER TABLE connector_connection_tests ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_connection_tests FORCE ROW LEVEL SECURITY;
ALTER TABLE connector_connection_test_specs ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_connection_test_specs FORCE ROW LEVEL SECURITY;

CREATE POLICY connector_connection_tests_scope ON connector_connection_tests
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
CREATE POLICY connector_connection_test_specs_scope ON connector_connection_test_specs
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

GRANT SELECT ON connector_connection_tests TO geo_app, geo_worker;
GRANT SELECT ON connector_connection_test_specs TO geo_worker;
GRANT UPDATE (status, version, started_at, finished_at, result_hash, error_class)
ON connector_connection_tests TO geo_worker;
REVOKE ALL ON FUNCTION geo_enqueue_connector_connection_test(
    uuid, uuid, uuid, integer, uuid, timestamptz
) FROM PUBLIC, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_connector_connection_test(
    uuid, uuid, uuid, integer, uuid, timestamptz
) TO geo_app;
REVOKE ALL ON FUNCTION geo_reconcile_connector_connection_test_status()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
