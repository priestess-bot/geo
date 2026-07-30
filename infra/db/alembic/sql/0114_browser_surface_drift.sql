ALTER TABLE browser_surface_releases
DROP CONSTRAINT browser_surface_releases_status_check;
ALTER TABLE browser_surface_releases
DROP CONSTRAINT browser_surface_releases_check;
ALTER TABLE browser_surface_releases
ADD CONSTRAINT browser_surface_releases_status_check
CHECK (status IN ('draft', 'approved', 'suspended', 'retired'));
ALTER TABLE browser_surface_releases
ADD CONSTRAINT browser_surface_releases_lifecycle_check CHECK (
    (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
    OR (status IN ('approved', 'suspended', 'retired')
        AND approved_by IS NOT NULL AND approved_at IS NOT NULL
        AND approved_by <> created_by)
);
ALTER TABLE browser_surface_releases
ADD COLUMN suspended_at timestamptz,
ADD COLUMN suspension_reason text;
ALTER TABLE browser_surface_releases
ADD CONSTRAINT browser_surface_releases_suspension_check CHECK (
    (status = 'suspended' AND suspended_at IS NOT NULL AND suspension_reason IS NOT NULL)
    OR (status IN ('draft', 'approved')
        AND suspended_at IS NULL AND suspension_reason IS NULL)
    OR (status = 'retired' AND (
        (suspended_at IS NULL AND suspension_reason IS NULL)
        OR (suspended_at IS NOT NULL AND suspension_reason IS NOT NULL)
    ))
);

CREATE TABLE browser_surface_drift_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    surface_release_id uuid NOT NULL,
    sampling_attempt_id uuid,
    durable_job_id uuid,
    drift_kind text NOT NULL CHECK (drift_kind IN ('selector_parser', 'browser_build')),
    expected_value text NOT NULL CHECK (btrim(expected_value) <> ''),
    observed_value text NOT NULL CHECK (btrim(observed_value) <> ''),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
    detected_at timestamptz NOT NULL,
    release_suspended boolean NOT NULL,
    UNIQUE (project_id, sampling_attempt_id, drift_kind),
    UNIQUE (project_id, durable_job_id, drift_kind),
    FOREIGN KEY (surface_release_id, project_id)
      REFERENCES browser_surface_releases(id, project_id),
    FOREIGN KEY (sampling_attempt_id, project_id)
      REFERENCES workflow_c_sampling_attempts(id, project_id),
    FOREIGN KEY (durable_job_id, project_id)
      REFERENCES durable_jobs(id, project_id),
    CHECK (sampling_attempt_id IS NOT NULL OR durable_job_id IS NOT NULL)
);

CREATE INDEX browser_surface_drift_release_idx
ON browser_surface_drift_events(project_id, surface_release_id, detected_at DESC);

CREATE FUNCTION geo_detect_browser_parser_drift()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off
AS $$
DECLARE should_suspend boolean := false;
BEGIN
    IF NEW.result_class <> 'parser_failed' THEN
        RETURN NEW;
    END IF;
    SELECT count(*) = 3 AND count(*) FILTER (WHERE recent.result_class = 'parser_failed') = 3
      INTO should_suspend
      FROM (
          SELECT parsed.result_class
            FROM browser_parsed_observations parsed
           WHERE parsed.project_id = NEW.project_id
             AND parsed.surface_release_id = NEW.surface_release_id
           ORDER BY parsed.observed_at DESC, parsed.id DESC
           LIMIT 3
      ) recent;
    IF should_suspend THEN
        UPDATE browser_surface_releases
           SET status = 'suspended', suspended_at = NEW.observed_at,
               suspension_reason = 'selector_parser_drift'
         WHERE project_id = NEW.project_id AND id = NEW.surface_release_id
           AND status = 'approved';
    END IF;
    INSERT INTO browser_surface_drift_events(
        project_id, surface_release_id, sampling_attempt_id, drift_kind,
        expected_value, observed_value, evidence_hash, detected_at, release_suspended
    ) VALUES (
        NEW.project_id, NEW.surface_release_id, NEW.sampling_attempt_id,
        'selector_parser', 'captured_or_valid_missing', NEW.result_class,
        NEW.observation_hash, NEW.observed_at, should_suspend
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER browser_parser_drift_detect
AFTER INSERT ON browser_parsed_observations FOR EACH ROW
EXECUTE FUNCTION geo_detect_browser_parser_drift();

CREATE FUNCTION geo_suspend_browser_surface_for_runtime_drift(
    p_project_id uuid, p_job_id uuid, p_surface_release_id uuid,
    p_observed_browser_release text, p_detected_at timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off
AS $$
DECLARE surface browser_surface_releases%ROWTYPE;
DECLARE expected_job browser_capture_job_specs%ROWTYPE;
DECLARE was_suspended boolean := false;
DECLARE evidence text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL OR p_surface_release_id IS NULL
       OR btrim(COALESCE(p_observed_browser_release, '')) = ''
       OR p_detected_at IS NULL THEN
        RAISE EXCEPTION 'Browser runtime drift input is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO expected_job FROM browser_capture_job_specs
     WHERE project_id = p_project_id AND job_id = p_job_id;
    SELECT * INTO surface FROM browser_surface_releases
     WHERE project_id = p_project_id AND id = p_surface_release_id FOR UPDATE;
    IF expected_job.job_id IS NULL OR surface.id IS NULL
       OR expected_job.surface_release_id <> surface.id
       OR NOT EXISTS (
           SELECT 1 FROM durable_jobs job
            WHERE job.project_id = p_project_id AND job.id = p_job_id
              AND job.kind = 'browser.capture' AND job.status = 'running'
       ) THEN
        RAISE EXCEPTION 'Browser runtime drift lineage is stale' USING ERRCODE = '23514';
    END IF;
    IF surface.browser_release = p_observed_browser_release THEN
        RETURN false;
    END IF;
    evidence := encode(digest(convert_to(
        surface.browser_release || E'\n' || p_observed_browser_release || E'\n' ||
        p_job_id::text, 'UTF8'), 'sha256'), 'hex');
    UPDATE browser_surface_releases
       SET status = 'suspended', suspended_at = p_detected_at,
           suspension_reason = 'browser_build_drift'
     WHERE project_id = p_project_id AND id = p_surface_release_id
       AND status = 'approved';
    was_suspended := FOUND;
    INSERT INTO browser_surface_drift_events(
        project_id, surface_release_id, durable_job_id, drift_kind,
        expected_value, observed_value, evidence_hash, detected_at, release_suspended
    ) VALUES (
        p_project_id, surface.id, p_job_id, 'browser_build',
        surface.browser_release, p_observed_browser_release, evidence,
        p_detected_at, was_suspended
    ) ON CONFLICT (project_id, durable_job_id, drift_kind) DO NOTHING;
    RETURN was_suspended;
END;
$$;

ALTER TABLE browser_surface_drift_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE browser_surface_drift_events FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON browser_surface_drift_events
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
GRANT SELECT ON browser_surface_drift_events TO geo_app, geo_worker;
REVOKE ALL ON FUNCTION geo_detect_browser_parser_drift()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_suspend_browser_surface_for_runtime_drift(
    uuid, uuid, uuid, text, timestamptz
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_suspend_browser_surface_for_runtime_drift(
    uuid, uuid, uuid, text, timestamptz
) TO geo_worker;
