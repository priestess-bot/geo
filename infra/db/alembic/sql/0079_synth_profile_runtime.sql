ALTER TABLE synthetic_lab_job_metadata
    DROP CONSTRAINT synthetic_lab_job_runtime_shape;

ALTER TABLE synthetic_lab_job_metadata
    ADD CONSTRAINT synthetic_lab_job_runtime_shape CHECK (
        (fact_snapshot_id IS NULL AND fact_snapshot_hash IS NULL
            AND profile_version_id IS NULL AND profile_hash IS NULL
            AND prompt_release_id IS NULL AND prompt_release_hash IS NULL
            AND facts_current_approved IS NULL AND profile_frozen IS NULL
            AND prompt_frozen IS NULL)
        OR (fact_snapshot_id IS NOT NULL AND fact_snapshot_hash IS NOT NULL
            AND profile_version_id IS NOT NULL AND profile_hash IS NOT NULL
            AND prompt_release_id IS NOT NULL AND prompt_release_hash IS NOT NULL
            AND facts_current_approved AND prompt_frozen
            AND (profile_frozen OR domain_job_kind = 'style_profile_build'))
    );
