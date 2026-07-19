CREATE TABLE project_export_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    campaign_id uuid,
    audience text NOT NULL CHECK (audience IN ('admin', 'customer')),
    requested_by uuid NOT NULL REFERENCES identities(id),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT project_export_specs_exact_job_key UNIQUE (job_id, project_id),
    CONSTRAINT project_export_specs_job_fkey FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT project_export_specs_campaign_fkey FOREIGN KEY (
        campaign_id, project_id
    ) REFERENCES geo_campaigns(id, project_id),
    CONSTRAINT project_export_specs_customer_scope_check CHECK (
        audience <> 'customer' OR campaign_id IS NOT NULL
    )
);

CREATE FUNCTION geo_assert_project_export_spec() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    job_campaign_id uuid;
    job_input_hash text;
BEGIN
    SELECT job.campaign_id, job.input_hash
    INTO job_campaign_id, job_input_hash
    FROM durable_jobs AS job
    WHERE job.id = NEW.job_id
      AND job.project_id = NEW.project_id
      AND job.kind = 'project.export'
    FOR KEY SHARE;
    IF NOT FOUND
       OR job_campaign_id IS DISTINCT FROM NEW.campaign_id
       OR job_input_hash IS DISTINCT FROM NEW.input_hash THEN
        RAISE EXCEPTION
            'project export spec must match its exact project.export Job scope and input hash'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER project_export_spec_kind
BEFORE INSERT OR UPDATE ON project_export_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('project.export');
CREATE TRIGGER project_export_spec_contract_guard
BEFORE INSERT ON project_export_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_project_export_spec();
CREATE TRIGGER project_export_specs_immutable
BEFORE UPDATE ON project_export_specs
FOR EACH ROW EXECUTE FUNCTION geo_reject_placement_job_spec_update();
CREATE CONSTRAINT TRIGGER project_export_specs_delete_guard
AFTER DELETE ON project_export_specs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();

CREATE TABLE project_export_artifacts (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    campaign_id uuid,
    audience text NOT NULL CHECK (audience IN ('admin', 'customer')),
    storage_key text NOT NULL CHECK (btrim(storage_key) <> ''),
    artifact_uri text NOT NULL CHECK (artifact_uri ~ '^s3://[^/]+/.+$'),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    byte_count bigint NOT NULL CHECK (byte_count > 0),
    file_count integer NOT NULL CHECK (file_count > 0),
    finalized_at timestamptz NOT NULL,
    CONSTRAINT project_export_artifacts_exact_job_key UNIQUE (job_id, project_id),
    CONSTRAINT project_export_artifacts_job_fkey FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id),
    CONSTRAINT project_export_artifacts_spec_fkey FOREIGN KEY (job_id, project_id)
        REFERENCES project_export_specs(job_id, project_id),
    CONSTRAINT project_export_artifacts_campaign_fkey FOREIGN KEY (
        campaign_id, project_id
    ) REFERENCES geo_campaigns(id, project_id),
    CONSTRAINT project_export_artifacts_customer_scope_check CHECK (
        audience <> 'customer' OR campaign_id IS NOT NULL
    ),
    CONSTRAINT project_export_artifacts_storage_path_check CHECK (
        storage_key = 'project-exports/' || project_id::text || '/' || audience || '/'
            || COALESCE(campaign_id::text, 'all-campaigns') || '/'
            || manifest_hash || '.zip'
    ),
    CONSTRAINT project_export_artifacts_uri_key_check CHECK (
        right(artifact_uri, length(storage_key) + 1) = '/' || storage_key
    )
);

CREATE FUNCTION geo_assert_project_export_artifact() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    spec_campaign_id uuid;
    spec_audience text;
BEGIN
    SELECT spec.campaign_id, spec.audience
    INTO spec_campaign_id, spec_audience
    FROM project_export_specs AS spec
    WHERE spec.job_id = NEW.job_id
      AND spec.project_id = NEW.project_id;
    IF NOT FOUND
       OR spec_campaign_id IS DISTINCT FROM NEW.campaign_id
       OR spec_audience IS DISTINCT FROM NEW.audience THEN
        RAISE EXCEPTION
            'project export artifact must match its exact immutable request scope'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER project_export_artifact_contract_guard
BEFORE INSERT ON project_export_artifacts
FOR EACH ROW EXECUTE FUNCTION geo_assert_project_export_artifact();
CREATE TRIGGER project_export_artifacts_immutable
BEFORE UPDATE OR DELETE ON project_export_artifacts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX project_export_specs_project_created_idx
ON project_export_specs (project_id, created_at DESC, job_id DESC);
CREATE INDEX project_export_specs_campaign_idx
ON project_export_specs (project_id, campaign_id, created_at DESC, job_id DESC)
WHERE campaign_id IS NOT NULL;
CREATE INDEX project_export_specs_requester_idx
ON project_export_specs (requested_by, created_at DESC, job_id DESC);
CREATE INDEX project_export_specs_campaign_fk_idx
ON project_export_specs (campaign_id, project_id)
WHERE campaign_id IS NOT NULL;
CREATE INDEX project_export_artifacts_project_finalized_idx
ON project_export_artifacts (project_id, finalized_at DESC, job_id DESC);
CREATE INDEX project_export_artifacts_campaign_idx
ON project_export_artifacts (project_id, campaign_id, finalized_at DESC, job_id DESC)
WHERE campaign_id IS NOT NULL;
CREATE INDEX project_export_artifacts_campaign_fk_idx
ON project_export_artifacts (campaign_id, project_id)
WHERE campaign_id IS NOT NULL;

ALTER TABLE project_export_specs ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_export_specs FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON project_export_specs
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));
ALTER TABLE project_export_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_export_artifacts FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON project_export_artifacts
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON project_export_specs, project_export_artifacts
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON project_export_specs, project_export_artifacts
TO geo_app, geo_worker, geo_readonly;
GRANT INSERT ON project_export_specs TO geo_app;
GRANT INSERT ON project_export_artifacts TO geo_worker;

REVOKE ALL ON FUNCTION
    geo_assert_project_export_spec(), geo_assert_project_export_artifact()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_assert_project_export_spec() TO geo_app;
GRANT EXECUTE ON FUNCTION geo_assert_project_export_artifact() TO geo_worker;
