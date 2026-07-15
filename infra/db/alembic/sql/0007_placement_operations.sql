ALTER TABLE publication_submissions
    ADD COLUMN idempotency_key text,
    ADD COLUMN payload_hash text,
    ADD COLUMN submitted_by uuid;

UPDATE publication_submissions submission
SET idempotency_key = 'legacy-submission:' || submission.id::text,
    payload_hash = encode(digest(
        jsonb_build_object(
            'publication_request_id', submission.publication_request_id::text,
            'provider_submission_id', submission.provider_submission_id,
            'submitted_url', submission.submitted_url
        )::text,
        'sha256'
    ), 'hex'),
    submitted_by = request.requested_by
FROM publication_requests request
WHERE request.id = submission.publication_request_id
  AND request.project_id = submission.project_id;

ALTER TABLE publication_submissions
    ALTER COLUMN idempotency_key SET NOT NULL,
    ALTER COLUMN payload_hash SET NOT NULL,
    ALTER COLUMN submitted_by SET NOT NULL,
    ADD CONSTRAINT publication_submissions_idempotency_key_check
        CHECK (btrim(idempotency_key) <> ''),
    ADD CONSTRAINT publication_submissions_payload_hash_check
        CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT publication_submissions_submitted_by_fkey
        FOREIGN KEY (submitted_by) REFERENCES identities(id),
    ADD CONSTRAINT publication_submissions_project_idempotency_key_key
        UNIQUE (project_id, idempotency_key);

ALTER TABLE measurement_job_specs
    DROP CONSTRAINT measurement_job_specs_submission_id_due_offset_days_key,
    DROP CONSTRAINT measurement_job_specs_device_check,
    ADD COLUMN protocol_id uuid,
    ADD COLUMN measurement_window text,
    ADD COLUMN expected_sample_count integer;

WITH ranked_protocols AS (
    SELECT spec.job_id, protocol.id AS protocol_id, protocol.sample_size,
           protocol.protocol_hash,
           count(query.id) AS query_count,
           row_number() OVER (PARTITION BY spec.job_id ORDER BY protocol.frozen_at, protocol.id) AS rank
    FROM measurement_job_specs spec
    JOIN publication_submissions submission
      ON submission.id = spec.submission_id AND submission.project_id = spec.project_id
    JOIN publication_requests request
      ON request.id = submission.publication_request_id
     AND request.project_id = submission.project_id
    JOIN placement_package_versions version
      ON version.id = request.package_version_id AND version.project_id = request.project_id
    JOIN placement_packages package
      ON package.id = version.package_id AND package.project_id = version.project_id
    JOIN placement_opportunities opportunity
      ON opportunity.id = package.opportunity_id AND opportunity.project_id = package.project_id
    JOIN monitoring_protocols protocol
      ON protocol.campaign_id = opportunity.campaign_id
     AND protocol.project_id = opportunity.project_id AND protocol.status = 'frozen'
    JOIN monitoring_protocol_queries query
      ON query.protocol_id = protocol.id AND query.project_id = protocol.project_id
    GROUP BY spec.job_id, protocol.id, protocol.sample_size,
             protocol.protocol_hash, protocol.frozen_at
)
UPDATE measurement_job_specs spec
SET protocol_id = candidate.protocol_id,
    measurement_window = 't' || spec.due_offset_days::text,
    expected_sample_count = candidate.sample_size * candidate.query_count,
    protocol_hash = candidate.protocol_hash
FROM ranked_protocols candidate
WHERE candidate.job_id = spec.job_id AND candidate.rank = 1;

DELETE FROM durable_jobs job
USING measurement_job_specs spec
WHERE job.id = spec.job_id AND job.project_id = spec.project_id
  AND spec.protocol_id IS NULL;

ALTER TABLE measurement_job_specs
    ALTER COLUMN protocol_id SET NOT NULL,
    ALTER COLUMN measurement_window SET NOT NULL,
    ALTER COLUMN expected_sample_count SET NOT NULL,
    ADD CONSTRAINT measurement_job_specs_protocol_fkey
        FOREIGN KEY (protocol_id, project_id)
        REFERENCES monitoring_protocols(id, project_id),
    ADD CONSTRAINT measurement_job_specs_window_check
        CHECK (measurement_window IN ('t28', 't56', 't84')),
    ADD CONSTRAINT measurement_job_specs_expected_sample_count_check
        CHECK (expected_sample_count > 0),
    ADD CONSTRAINT measurement_job_specs_device_check
        CHECK (device IN ('desktop', 'mobile', 'tablet')),
    ADD CONSTRAINT measurement_job_specs_submission_protocol_window_key
        UNIQUE (submission_id, protocol_id, measurement_window);

CREATE TABLE measurement_collection_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    submission_id uuid NOT NULL,
    protocol_id uuid NOT NULL,
    measurement_window text NOT NULL CHECK (measurement_window IN ('t28', 't56', 't84')),
    expected_sample_count integer NOT NULL CHECK (expected_sample_count > 0),
    actual_sample_count integer NOT NULL DEFAULT 0 CHECK (actual_sample_count >= 0),
    scheduled_for timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'cancelled')),
    opened_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    cancelled_at timestamptz,
    acted_by uuid REFERENCES identities(id),
    state_reason text,
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id),
    FOREIGN KEY (submission_id, project_id) REFERENCES publication_submissions(id, project_id),
    FOREIGN KEY (protocol_id, project_id) REFERENCES monitoring_protocols(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (job_id),
    UNIQUE (submission_id, protocol_id, measurement_window),
    CHECK (
        (status = 'open' AND completed_at IS NULL AND cancelled_at IS NULL
            AND acted_by IS NULL AND state_reason IS NULL)
        OR (status = 'completed' AND completed_at IS NOT NULL AND cancelled_at IS NULL
            AND acted_by IS NOT NULL AND state_reason IS NULL)
        OR (status = 'cancelled' AND completed_at IS NULL AND cancelled_at IS NOT NULL
            AND acted_by IS NOT NULL AND btrim(COALESCE(state_reason, '')) <> '')
    )
);

CREATE FUNCTION geo_assert_opportunity_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = NEW.status THEN
        RETURN NEW;
    END IF;
    IF NOT (
        (OLD.status = 'identified' AND NEW.status IN ('qualified', 'blocked', 'cancelled'))
        OR (OLD.status = 'qualified' AND NEW.status IN ('briefing', 'blocked', 'cancelled'))
        OR (OLD.status = 'briefing' AND NEW.status IN ('in_progress', 'blocked', 'cancelled'))
        OR (OLD.status = 'in_progress' AND NEW.status IN ('completed', 'blocked', 'cancelled'))
        OR (OLD.status = 'blocked' AND NEW.status IN ('identified', 'cancelled'))
    ) THEN
        RAISE EXCEPTION 'invalid placement opportunity transition: %% -> %%', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER placement_opportunity_transition_guard
BEFORE UPDATE OF status ON placement_opportunities
FOR EACH ROW EXECUTE FUNCTION geo_assert_opportunity_transition();

CREATE INDEX measurement_collection_tasks_open_idx
ON measurement_collection_tasks (project_id, scheduled_for, submission_id)
WHERE status = 'open';

ALTER TABLE measurement_collection_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE measurement_collection_tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON measurement_collection_tasks
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

GRANT SELECT, INSERT, UPDATE, DELETE ON measurement_collection_tasks TO geo_app, geo_worker;
GRANT SELECT ON measurement_collection_tasks TO geo_readonly;
GRANT EXECUTE ON FUNCTION geo_assert_opportunity_transition()
TO geo_app, geo_worker, geo_readonly;
