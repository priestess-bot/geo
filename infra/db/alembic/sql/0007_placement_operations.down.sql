DROP TRIGGER IF EXISTS placement_opportunity_transition_guard ON placement_opportunities;
DROP FUNCTION IF EXISTS geo_assert_opportunity_transition();
DROP TABLE IF EXISTS measurement_collection_tasks;

DELETE FROM durable_jobs WHERE kind = 'placement.measure';

ALTER TABLE measurement_job_specs
    DROP CONSTRAINT IF EXISTS measurement_job_specs_submission_protocol_window_key,
    DROP CONSTRAINT IF EXISTS measurement_job_specs_expected_sample_count_check,
    DROP CONSTRAINT IF EXISTS measurement_job_specs_window_check,
    DROP CONSTRAINT IF EXISTS measurement_job_specs_protocol_fkey,
    DROP CONSTRAINT IF EXISTS measurement_job_specs_device_check,
    DROP COLUMN IF EXISTS expected_sample_count,
    DROP COLUMN IF EXISTS measurement_window,
    DROP COLUMN IF EXISTS protocol_id,
    ADD CONSTRAINT measurement_job_specs_device_check
        CHECK (device IN ('desktop', 'mobile')),
    ADD CONSTRAINT measurement_job_specs_submission_id_due_offset_days_key
        UNIQUE (submission_id, due_offset_days);

ALTER TABLE publication_submissions
    DROP CONSTRAINT IF EXISTS publication_submissions_project_idempotency_key_key,
    DROP CONSTRAINT IF EXISTS publication_submissions_submitted_by_fkey,
    DROP CONSTRAINT IF EXISTS publication_submissions_payload_hash_check,
    DROP CONSTRAINT IF EXISTS publication_submissions_idempotency_key_check,
    DROP COLUMN IF EXISTS submitted_by,
    DROP COLUMN IF EXISTS payload_hash,
    DROP COLUMN IF EXISTS idempotency_key;
