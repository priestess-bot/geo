DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM publication_verification_attempts) THEN
        RAISE EXCEPTION 'cannot downgrade: publication verification attempts exist'
            USING ERRCODE = '55000';
    END IF;
END $$;

DROP TRIGGER IF EXISTS publication_verification_attempts_immutable
ON publication_verification_attempts;
DROP TRIGGER IF EXISTS publication_verification_attempt_insert_guard
ON publication_verification_attempts;
DROP FUNCTION IF EXISTS geo_assert_publication_verification_attempt();
DROP TABLE publication_verification_attempts;
ALTER TABLE verification_job_specs
    DROP CONSTRAINT verification_job_specs_attempt_context_key;
