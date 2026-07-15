-- Truthful Development Board projections sourced from GitHub, CI and runtime health.

CREATE TABLE engineering_repositories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    installation_id bigint NOT NULL CHECK (installation_id > 0),
    external_repository_id bigint NOT NULL CHECK (external_repository_id > 0),
    full_name text NOT NULL CHECK (btrim(full_name) <> ''),
    web_url text NOT NULL CHECK (web_url ~ '^https://'),
    default_branch text NOT NULL DEFAULT 'main' CHECK (btrim(default_branch) <> ''),
    reconciliation_interval_seconds integer NOT NULL DEFAULT 300
        CHECK (reconciliation_interval_seconds BETWEEN 30 AND 86400),
    status text NOT NULL DEFAULT 'configured' CHECK (status IN ('configured', 'disabled')),
    last_reconciled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, external_repository_id)
);

-- Minimal non-project-scoped ingress binding. It carries no GitHub content and exists
-- solely so a signed webhook can discover its project before setting the RLS context.
CREATE TABLE engineering_github_bindings (
    external_repository_id bigint PRIMARY KEY CHECK (external_repository_id > 0),
    project_id uuid NOT NULL,
    repository_id uuid NOT NULL,
    FOREIGN KEY (repository_id, project_id)
        REFERENCES engineering_repositories(id, project_id) ON DELETE CASCADE,
    UNIQUE (repository_id)
);

CREATE TABLE engineering_work_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    repository_id uuid NOT NULL,
    external_id text NOT NULL CHECK (btrim(external_id) <> ''),
    title text NOT NULL CHECK (btrim(title) <> ''),
    summary text,
    required_axes text[] NOT NULL DEFAULT ARRAY['planned','implemented','verified','deployed'],
    blockers text[] NOT NULL DEFAULT '{}',
    planned_status text NOT NULL DEFAULT 'unavailable',
    planned_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    planned_observed_at timestamptz,
    implemented_status text NOT NULL DEFAULT 'unavailable',
    implemented_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    implemented_observed_at timestamptz,
    verified_status text NOT NULL DEFAULT 'unavailable',
    verified_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    verified_observed_at timestamptz,
    deployed_status text NOT NULL DEFAULT 'unavailable',
    deployed_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    deployed_observed_at timestamptz,
    observed_at timestamptz NOT NULL,
    observation_interval_seconds integer NOT NULL DEFAULT 300
        CHECK (observation_interval_seconds BETWEEN 10 AND 86400),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (repository_id, project_id)
        REFERENCES engineering_repositories(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (repository_id, external_id),
    CHECK (required_axes <@ ARRAY['planned','implemented','verified','deployed']::text[]),
    CHECK (cardinality(required_axes) > 0),
    CHECK (planned_status IN ('satisfied','pending','blocked','unavailable')),
    CHECK (implemented_status IN ('satisfied','pending','blocked','unavailable')),
    CHECK (verified_status IN ('satisfied','pending','blocked','unavailable')),
    CHECK (deployed_status IN ('satisfied','pending','blocked','unavailable')),
    CHECK (jsonb_typeof(planned_evidence) = 'array'),
    CHECK (jsonb_typeof(implemented_evidence) = 'array'),
    CHECK (jsonb_typeof(verified_evidence) = 'array'),
    CHECK (jsonb_typeof(deployed_evidence) = 'array')
);

CREATE TABLE engineering_pull_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    repository_id uuid NOT NULL,
    external_number integer NOT NULL CHECK (external_number > 0),
    title text NOT NULL,
    web_url text NOT NULL CHECK (web_url ~ '^https://'),
    state text NOT NULL CHECK (state IN ('open','closed','merged','unknown')),
    draft boolean NOT NULL DEFAULT false,
    head_sha text NOT NULL CHECK (btrim(head_sha) <> ''),
    base_ref text NOT NULL CHECK (btrim(base_ref) <> ''),
    merged_at timestamptz,
    observed_at timestamptz NOT NULL,
    FOREIGN KEY (repository_id, project_id)
        REFERENCES engineering_repositories(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (repository_id, external_number)
);

CREATE TABLE engineering_ci_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    repository_id uuid NOT NULL,
    external_id bigint NOT NULL CHECK (external_id > 0),
    name text NOT NULL CHECK (btrim(name) <> ''),
    web_url text NOT NULL CHECK (web_url ~ '^https://'),
    head_sha text NOT NULL CHECK (btrim(head_sha) <> ''),
    status text NOT NULL CHECK (status IN ('queued','in_progress','completed','unknown')),
    conclusion text CHECK (conclusion IS NULL OR conclusion IN (
        'success','failure','neutral','cancelled','skipped','timed_out','action_required','unknown'
    )),
    observed_at timestamptz NOT NULL,
    FOREIGN KEY (repository_id, project_id)
        REFERENCES engineering_repositories(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (repository_id, external_id)
);

CREATE TABLE engineering_ci_checks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ci_run_id uuid NOT NULL,
    external_id bigint NOT NULL CHECK (external_id > 0),
    name text NOT NULL CHECK (btrim(name) <> ''),
    web_url text CHECK (web_url IS NULL OR web_url ~ '^https://'),
    status text NOT NULL CHECK (status IN ('queued','in_progress','completed','unknown')),
    conclusion text,
    observed_at timestamptz NOT NULL,
    FOREIGN KEY (ci_run_id, project_id)
        REFERENCES engineering_ci_runs(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (ci_run_id, external_id)
);

CREATE TABLE engineering_service_health (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    service_key text NOT NULL CHECK (btrim(service_key) <> ''),
    status text NOT NULL CHECK (status IN ('healthy','degraded','unavailable','unknown')),
    detail text,
    evidence_url text,
    observation_interval_seconds integer NOT NULL DEFAULT 30
        CHECK (observation_interval_seconds BETWEEN 10 AND 86400),
    observed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, service_key)
);

CREATE TABLE engineering_webhook_deliveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    repository_id uuid NOT NULL,
    delivery_id text NOT NULL CHECK (btrim(delivery_id) <> ''),
    event_name text NOT NULL CHECK (btrim(event_name) <> ''),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','processing','processed','ignored','failed')),
    received_at timestamptz NOT NULL,
    processed_at timestamptz,
    error_code text,
    FOREIGN KEY (repository_id, project_id)
        REFERENCES engineering_repositories(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (project_id, delivery_id)
);

CREATE TABLE engineering_events (
    sequence bigserial PRIMARY KEY,
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_type text NOT NULL CHECK (btrim(event_type) <> ''),
    data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id)
);

CREATE TABLE engineering_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    operation text NOT NULL CHECK (operation IN ('github_project','reconcile','health_probe')),
    repository_id uuid,
    delivery_id uuid,
    service_key text,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (repository_id, project_id)
        REFERENCES engineering_repositories(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (delivery_id, project_id)
        REFERENCES engineering_webhook_deliveries(id, project_id) ON DELETE CASCADE,
    UNIQUE (job_id, project_id),
    CHECK ((operation = 'github_project') = (delivery_id IS NOT NULL)),
    CHECK ((operation = 'health_probe') = (service_key IS NOT NULL))
);

CREATE FUNCTION geo_assert_engineering_job_kind() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM durable_jobs j
        WHERE j.id = NEW.job_id AND j.project_id = NEW.project_id
          AND j.kind = CASE NEW.operation
              WHEN 'github_project' THEN 'engineering.github_project'
              WHEN 'reconcile' THEN 'engineering.reconcile'
              ELSE 'engineering.health_probe' END
    ) THEN
        RAISE EXCEPTION 'engineering job spec does not match durable job kind'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER engineering_job_spec_kind
BEFORE INSERT OR UPDATE ON engineering_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_engineering_job_kind();

CREATE INDEX engineering_events_project_sequence_idx
ON engineering_events (project_id, sequence);
CREATE INDEX engineering_webhook_pending_idx
ON engineering_webhook_deliveries (received_at) WHERE status = 'pending';

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'engineering_repositories', 'engineering_work_items', 'engineering_pull_requests',
        'engineering_ci_runs', 'engineering_ci_checks', 'engineering_service_health',
        'engineering_webhook_deliveries', 'engineering_events', 'engineering_job_specs'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = geo_current_project_id())'
            || ' WITH CHECK (project_id = geo_current_project_id())';
    END LOOP;
END;
$$;
