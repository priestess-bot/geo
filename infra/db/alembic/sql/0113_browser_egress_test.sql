CREATE TABLE browser_egress_tests (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    endpoint_id uuid NOT NULL,
    durable_job_id uuid NOT NULL,
    secret_reference_id uuid NOT NULL,
    secret_purpose text NOT NULL CHECK (secret_purpose LIKE 'browser_egress.%'),
    secret_version integer NOT NULL CHECK (secret_version > 0),
    status text NOT NULL CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled'
    )),
    version integer NOT NULL CHECK (version > 0),
    requested_by uuid NOT NULL REFERENCES identities(id),
    requested_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    outcome text CHECK (outcome IS NULL OR outcome IN (
        'au_consumer_representative', 'au_geo_verified', 'geo_mismatch',
        'geo_unverified', 'egress_changed'
    )),
    eligible boolean,
    verification_hash text CHECK (
        verification_hash IS NULL OR verification_hash ~ '^[0-9a-f]{64}$'
    ),
    pre_observations jsonb CHECK (
        pre_observations IS NULL OR jsonb_typeof(pre_observations) = 'array'
    ),
    post_observations jsonb CHECK (
        post_observations IS NULL OR jsonb_typeof(post_observations) = 'array'
    ),
    error_class text,
    UNIQUE (id, project_id),
    UNIQUE (project_id, durable_job_id),
    FOREIGN KEY (endpoint_id, project_id)
      REFERENCES browser_egress_endpoints(id, project_id),
    FOREIGN KEY (durable_job_id, project_id)
      REFERENCES durable_jobs(id, project_id),
    FOREIGN KEY (secret_reference_id, project_id, secret_purpose, secret_version)
      REFERENCES secret_versions(reference_id, project_id, purpose, version),
    CHECK ((outcome IS NULL) = (eligible IS NULL)),
    CHECK (eligible IS NULL OR eligible = (outcome = 'au_consumer_representative')),
    CHECK ((verification_hash IS NULL) = (pre_observations IS NULL)),
    CHECK ((verification_hash IS NULL) = (post_observations IS NULL))
);

CREATE TABLE browser_egress_test_specs (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    test_id uuid NOT NULL,
    spec_hash text NOT NULL CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    spec_payload jsonb NOT NULL CHECK (jsonb_typeof(spec_payload) = 'object'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, job_id),
    UNIQUE (project_id, test_id),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id),
    FOREIGN KEY (test_id, project_id) REFERENCES browser_egress_tests(id, project_id)
      DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX browser_egress_tests_endpoint_idx
ON browser_egress_tests(project_id, endpoint_id, requested_at DESC);

CREATE FUNCTION geo_enqueue_browser_egress_test(
    p_project_id uuid, p_test_id uuid, p_endpoint_id uuid,
    p_requested_by uuid, p_requested_at timestamptz
) RETURNS TABLE(test_id uuid, job_id uuid, status text, replayed boolean)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off
AS $$
DECLARE endpoint browser_egress_endpoints%ROWTYPE;
DECLARE stored browser_egress_tests%ROWTYPE;
DECLARE durable durable_jobs%ROWTYPE;
DECLARE payload jsonb;
DECLARE payload_hash text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_test_id IS NULL OR p_endpoint_id IS NULL OR p_requested_by IS NULL
       OR p_requested_at IS NULL THEN
        RAISE EXCEPTION 'Browser Egress test command is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'browser-egress-test:' || p_project_id::text || ':' || p_test_id::text, 0
    ));
    SELECT * INTO stored FROM browser_egress_tests
     WHERE project_id = p_project_id AND id = p_test_id;
    IF FOUND THEN
        RETURN QUERY SELECT stored.id, stored.durable_job_id, stored.status, true;
        RETURN;
    END IF;
    SELECT * INTO endpoint FROM browser_egress_endpoints
     WHERE project_id = p_project_id AND id = p_endpoint_id FOR SHARE;
    IF endpoint.id IS NULL OR endpoint.status <> 'approved'
       OR endpoint.expected_country <> 'AU'
       OR NOT EXISTS (
            SELECT 1 FROM secret_versions secret
             WHERE secret.reference_id = endpoint.secret_reference_id
               AND secret.project_id = p_project_id
               AND secret.purpose = endpoint.secret_purpose
               AND secret.version = endpoint.secret_version
               AND secret.status = 'active'
       ) THEN
        RAISE EXCEPTION 'Browser Egress Endpoint or its exact Secret is not active'
            USING ERRCODE = '23514';
    END IF;
    payload := jsonb_build_object(
        'schema_version', 1, 'kind', 'browser.egress_test',
        'project_id', p_project_id, 'test_id', p_test_id,
        'endpoint_id', endpoint.id, 'protocol', endpoint.protocol,
        'endpoint_host', endpoint.endpoint_host, 'endpoint_port', endpoint.endpoint_port,
        'network_type', endpoint.network_type, 'sticky_mode', endpoint.sticky_mode,
        'expected_country', endpoint.expected_country,
        'expected_region', endpoint.expected_region,
        'egress_policy_version', endpoint.egress_policy_version,
        'egress_cohort_key', endpoint.egress_cohort_key,
        'secret_reference_id', endpoint.secret_reference_id,
        'secret_purpose', endpoint.secret_purpose,
        'secret_version', endpoint.secret_version
    );
    payload_hash := encode(digest(convert_to(
        geo_jsonb_sampling_canonical_text(payload), 'UTF8'), 'sha256'), 'hex');
    INSERT INTO durable_jobs(
        project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, replay_nonce, created_at, updated_at
    ) VALUES (
        p_project_id, 'browser.egress_test', 'queued', 0, payload_hash,
        'browser.egress_test:' || p_test_id::text, 2, p_requested_at,
        0, p_requested_at, p_requested_at
    ) RETURNING * INTO durable;
    INSERT INTO browser_egress_tests(
        id, project_id, endpoint_id, durable_job_id, secret_reference_id,
        secret_purpose, secret_version, status, version, requested_by, requested_at
    ) VALUES (
        p_test_id, p_project_id, endpoint.id, durable.id, endpoint.secret_reference_id,
        endpoint.secret_purpose, endpoint.secret_version, 'queued', 1,
        p_requested_by, p_requested_at
    );
    INSERT INTO browser_egress_test_specs(
        project_id, job_id, test_id, spec_hash, spec_payload, created_at
    ) VALUES (p_project_id, durable.id, p_test_id, payload_hash, payload, p_requested_at);
    INSERT INTO broker_outbox(
        project_id, job_id, topic, payload, idempotency_key, available_at
    ) VALUES (
        p_project_id, durable.id, 'browser.egress_test',
        jsonb_build_object('job_id', durable.id::text, 'project_id', p_project_id::text),
        'wake:browser.egress_test:' || p_test_id::text, p_requested_at
    );
    RETURN QUERY SELECT p_test_id, durable.id, 'queued'::text, false;
END;
$$;

CREATE FUNCTION geo_reconcile_browser_egress_test_status()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off
AS $$
BEGIN
    IF NEW.kind <> 'browser.egress_test'
       OR NEW.status NOT IN ('failed', 'dead_lettered', 'cancelled') THEN
        RETURN NEW;
    END IF;
    UPDATE browser_egress_tests
       SET status = CASE WHEN NEW.status = 'cancelled' THEN 'cancelled' ELSE 'failed' END,
           version = version + 1, finished_at = clock_timestamp(),
           error_class = CASE WHEN NEW.status = 'cancelled' THEN NULL
                              ELSE COALESCE(NEW.error_detail->>'classification', 'unknown') END
     WHERE project_id = NEW.project_id AND durable_job_id = NEW.id
       AND status IN ('queued', 'running');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Browser Egress test terminal state was not projected'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER browser_egress_test_status_reconcile
AFTER UPDATE OF status ON durable_jobs FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION geo_reconcile_browser_egress_test_status();

ALTER TABLE browser_egress_tests ENABLE ROW LEVEL SECURITY;
ALTER TABLE browser_egress_tests FORCE ROW LEVEL SECURITY;
ALTER TABLE browser_egress_test_specs ENABLE ROW LEVEL SECURITY;
ALTER TABLE browser_egress_test_specs FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON browser_egress_tests
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
CREATE POLICY project_scope ON browser_egress_test_specs
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

GRANT SELECT ON browser_egress_tests TO geo_app, geo_worker;
GRANT SELECT ON browser_egress_test_specs TO geo_worker;
GRANT UPDATE (
    status, version, started_at, finished_at, outcome, eligible,
    verification_hash, pre_observations, post_observations, error_class
) ON browser_egress_tests TO geo_worker;
REVOKE ALL ON FUNCTION geo_enqueue_browser_egress_test(
    uuid, uuid, uuid, uuid, timestamptz
) FROM PUBLIC, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_browser_egress_test(
    uuid, uuid, uuid, uuid, timestamptz
) TO geo_app;
REVOKE ALL ON FUNCTION geo_reconcile_browser_egress_test_status()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
