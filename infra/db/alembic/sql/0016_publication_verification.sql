ALTER TABLE verification_job_specs
    ADD CONSTRAINT verification_job_specs_attempt_context_key UNIQUE (
        job_id, project_id, campaign_id, opportunity_id, submission_id
    );

CREATE TABLE publication_verification_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    submission_id uuid NOT NULL,
    job_id uuid NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    verifier_version text NOT NULL CHECK (
        verifier_version = 'publication-url-verifier-v2'
    ),
    outcome text NOT NULL CHECK (outcome IN (
        'passed', 'failed', 'retryable_error', 'permanent_error'
    )),
    checked_at timestamptz NOT NULL,
    status_code integer CHECK (status_code BETWEEN 100 AND 599),
    final_url text CHECK (
        final_url IS NULL OR (btrim(final_url) <> '' AND final_url ~ '^https://')
    ),
    metadata_hash text CHECK (
        metadata_hash IS NULL OR metadata_hash ~ '^[0-9a-f]{64}$'
    ),
    body_hash text CHECK (body_hash IS NULL OR body_hash ~ '^[0-9a-f]{64}$'),
    visible_text_hash text CHECK (
        visible_text_hash IS NULL OR visible_text_hash ~ '^[0-9a-f]{64}$'
    ),
    content_rule_hash text CHECK (
        content_rule_hash IS NULL OR content_rule_hash ~ '^[0-9a-f]{64}$'
    ),
    verification_rule_hash text CHECK (
        verification_rule_hash IS NULL
        OR verification_rule_hash ~ '^[0-9a-f]{64}$'
    ),
    redirect_count integer NOT NULL CHECK (redirect_count >= 0),
    checks jsonb NOT NULL CHECK (jsonb_typeof(checks) = 'array'),
    failures jsonb NOT NULL CHECK (jsonb_typeof(failures) = 'array'),
    error_code text CHECK (
        error_code IS NULL OR (btrim(error_code) <> '' AND length(error_code) <= 160)
    ),
    failure_disposition text CHECK (
        failure_disposition IS NULL OR failure_disposition IN ('retryable', 'permanent')
    ),
    result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT publication_verification_attempts_spec_fkey FOREIGN KEY (
        job_id, project_id, campaign_id, opportunity_id, submission_id
    ) REFERENCES verification_job_specs(
        job_id, project_id, campaign_id, opportunity_id, submission_id
    ),
    CONSTRAINT publication_verification_attempts_submission_fkey
        FOREIGN KEY (submission_id, project_id, campaign_id, opportunity_id)
        REFERENCES publication_submissions(
            id, project_id, campaign_id, opportunity_id
        ),
    CONSTRAINT publication_verification_attempts_job_attempt_key
        UNIQUE (job_id, attempt_number),
    CONSTRAINT publication_verification_attempts_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, submission_id)
);

CREATE FUNCTION geo_assert_publication_verification_attempt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_attempt integer;
    item jsonb;
    check_names text[] := ARRAY[]::text[];
    check_name text;
    check_passed boolean;
    failed_check_count integer := 0;
    failure_count integer := 0;
    failure_code_value text;
    failure_disposition_value text;
    failure_check_value text;
    failure_retryable boolean;
BEGIN
    SELECT job.attempt_count INTO current_attempt
    FROM durable_jobs AS job
    JOIN verification_job_specs AS spec
      ON spec.job_id = job.id AND spec.project_id = job.project_id
     AND spec.campaign_id = job.campaign_id
    WHERE job.id = NEW.job_id
      AND job.project_id = NEW.project_id
      AND job.campaign_id = NEW.campaign_id
      AND job.kind = 'publication.verify'
      AND spec.opportunity_id = NEW.opportunity_id
      AND spec.submission_id = NEW.submission_id
    FOR KEY SHARE OF job;
    IF NOT FOUND OR NEW.attempt_number <> current_attempt OR current_attempt <= 0 THEN
        RAISE EXCEPTION 'verification attempt does not match the current job attempt'
            USING ERRCODE = '23514';
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(NEW.checks) LOOP
        IF jsonb_typeof(item) <> 'object'
           OR NOT item ?& ARRAY['name', 'passed', 'failure_code']
           OR (SELECT count(*) FROM jsonb_object_keys(item)) <> 3
           OR jsonb_typeof(item -> 'name') <> 'string'
           OR jsonb_typeof(item -> 'passed') <> 'boolean' THEN
            RAISE EXCEPTION 'verification check shape is invalid'
                USING ERRCODE = '23514';
        END IF;
        check_name := item ->> 'name';
        IF check_name NOT IN (
            'input_contract', 'public_url', 'redirect_policy', 'http_2xx',
            'html_response', 'approved_content', 'required_disclosures',
            'expected_links'
        ) OR check_name = ANY(check_names) THEN
            RAISE EXCEPTION 'verification check name is invalid or duplicated'
                USING ERRCODE = '23514';
        END IF;
        check_names := array_append(check_names, check_name);
        check_passed := (item ->> 'passed')::boolean;
        IF check_passed AND item -> 'failure_code' <> 'null'::jsonb THEN
            RAISE EXCEPTION 'passing verification checks cannot have failure codes'
                USING ERRCODE = '23514';
        END IF;
        IF NOT check_passed AND (
            jsonb_typeof(item -> 'failure_code') <> 'string'
            OR btrim(item ->> 'failure_code') = ''
        ) THEN
            RAISE EXCEPTION 'failed verification checks require a failure code'
                USING ERRCODE = '23514';
        END IF;
        failed_check_count := failed_check_count + (NOT check_passed)::integer;
    END LOOP;

    FOR item IN SELECT value FROM jsonb_array_elements(NEW.failures) LOOP
        IF jsonb_typeof(item) <> 'object'
           OR NOT item ?& ARRAY['code', 'disposition', 'check', 'retryable']
           OR (SELECT count(*) FROM jsonb_object_keys(item)) <> 4
           OR jsonb_typeof(item -> 'code') <> 'string'
           OR btrim(item ->> 'code') = ''
           OR jsonb_typeof(item -> 'disposition') <> 'string'
           OR jsonb_typeof(item -> 'check') <> 'string'
           OR jsonb_typeof(item -> 'retryable') <> 'boolean' THEN
            RAISE EXCEPTION 'verification failure shape is invalid'
                USING ERRCODE = '23514';
        END IF;
        failure_code_value := item ->> 'code';
        failure_disposition_value := item ->> 'disposition';
        failure_check_value := item ->> 'check';
        failure_retryable := (item ->> 'retryable')::boolean;
        IF failure_disposition_value NOT IN ('retryable', 'permanent')
           OR failure_check_value NOT IN (
                'input_contract', 'public_url', 'redirect_policy', 'http_2xx',
                'html_response', 'approved_content', 'required_disclosures',
                'expected_links'
           )
           OR failure_retryable IS DISTINCT FROM
                (failure_disposition_value = 'retryable') THEN
            RAISE EXCEPTION 'verification failure semantics are invalid'
                USING ERRCODE = '23514';
        END IF;
        failure_count := failure_count + 1;
    END LOOP;

    IF NEW.outcome IN ('passed', 'failed') THEN
        IF cardinality(check_names) <> 8
           OR NOT check_names @> ARRAY[
                'input_contract', 'public_url', 'redirect_policy', 'http_2xx',
                'html_response', 'approved_content', 'required_disclosures',
                'expected_links'
           ]
           OR NEW.status_code IS NULL OR NEW.final_url IS NULL
           OR num_nulls(
                NEW.metadata_hash, NEW.body_hash, NEW.visible_text_hash,
                NEW.content_rule_hash, NEW.verification_rule_hash
           ) <> 0 THEN
            RAISE EXCEPTION 'completed verification evidence is incomplete'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.outcome = 'passed' THEN
        IF failed_check_count <> 0 OR failure_count <> 0
           OR NEW.error_code IS NOT NULL OR NEW.failure_disposition IS NOT NULL
           OR NEW.status_code NOT BETWEEN 200 AND 299 THEN
            RAISE EXCEPTION 'passed verification evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.outcome = 'failed' THEN
        IF failed_check_count = 0 OR failure_count <> failed_check_count
           OR NEW.failure_disposition <> 'permanent'
           OR btrim(COALESCE(NEW.error_code, '')) = ''
           OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements(NEW.failures) AS failure(value)
                WHERE failure.value ->> 'disposition' <> 'permanent'
                   OR NOT EXISTS (
                        SELECT 1 FROM jsonb_array_elements(NEW.checks) AS checked(value)
                        WHERE checked.value ->> 'name' = failure.value ->> 'check'
                          AND NOT (checked.value ->> 'passed')::boolean
                          AND checked.value ->> 'failure_code' = failure.value ->> 'code'
                   )
           )
           OR NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(NEW.failures) AS failure(value)
                WHERE failure.value ->> 'code' = NEW.error_code
           ) THEN
            RAISE EXCEPTION 'failed verification evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF jsonb_array_length(NEW.checks) <> 0 OR failure_count <> 1
           OR btrim(COALESCE(NEW.error_code, '')) = ''
           OR NEW.failure_disposition IS NULL
           OR NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(NEW.failures) AS failure(value)
                WHERE failure.value ->> 'code' = NEW.error_code
                  AND failure.value ->> 'disposition' = NEW.failure_disposition
           )
           OR (NEW.outcome = 'retryable_error'
                AND NEW.failure_disposition <> 'retryable')
           OR (NEW.outcome = 'permanent_error'
                AND NEW.failure_disposition <> 'permanent') THEN
            RAISE EXCEPTION 'verification error evidence is inconsistent'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER publication_verification_attempt_insert_guard
BEFORE INSERT ON publication_verification_attempts
FOR EACH ROW EXECUTE FUNCTION geo_assert_publication_verification_attempt();
CREATE TRIGGER publication_verification_attempts_immutable
BEFORE UPDATE OR DELETE ON publication_verification_attempts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX publication_verification_attempts_submission_idx
ON publication_verification_attempts (
    project_id, campaign_id, opportunity_id, submission_id, checked_at DESC, id DESC
);
CREATE INDEX publication_verification_attempts_job_idx
ON publication_verification_attempts (
    project_id, campaign_id, job_id, checked_at DESC, id DESC
);
CREATE INDEX publication_verification_attempts_spec_fk_idx
ON publication_verification_attempts (
    job_id, project_id, campaign_id, opportunity_id, submission_id
);
CREATE INDEX publication_verification_attempts_submission_fk_idx
ON publication_verification_attempts (
    submission_id, project_id, campaign_id, opportunity_id
);

ALTER TABLE publication_verification_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE publication_verification_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON publication_verification_attempts
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON publication_verification_attempts
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON publication_verification_attempts TO geo_worker;
GRANT SELECT ON publication_verification_attempts TO geo_app, geo_readonly;
REVOKE ALL ON FUNCTION geo_assert_publication_verification_attempt()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_assert_publication_verification_attempt() TO geo_worker;
