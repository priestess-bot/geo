-- Do not put a live v2 Job back under the v1 worker contract.  Terminal v2
-- history is retained and is not executable, so it does not block rollback.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM connector_connection_tests test
          JOIN connector_connection_test_specs spec
            ON spec.project_id = test.project_id AND spec.test_id = test.id
         WHERE test.status IN ('queued', 'running')
           AND spec.spec_payload->>'schema_version' IS DISTINCT FROM '1'
    ) THEN
        RAISE EXCEPTION
            'cannot downgrade Connector connection-test scopes while nonterminal v2 Jobs exist'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION geo_enqueue_connector_connection_test(
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

COMMENT ON FUNCTION geo_enqueue_connector_connection_test(
    uuid, uuid, uuid, integer, uuid, timestamptz
) IS 'Enqueues a Connector connection test under the pre-scope v1 contract.';
