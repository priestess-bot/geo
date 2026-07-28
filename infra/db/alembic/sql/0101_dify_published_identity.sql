ALTER TABLE dify_workflow_releases
ADD COLUMN registered_workflow_hash text,
ADD COLUMN registered_snapshot_hash text,
ADD COLUMN registered_identity_source text;

-- Existing pinned releases inherit the exact graph that their successful
-- canary froze. Merely observed snapshots are not release truth: unpinned
-- legacy releases remain NULL and must be re-enrolled.
ALTER TABLE dify_workflow_releases
DISABLE TRIGGER dify_workflow_releases_immutable;
UPDATE dify_workflow_releases release
SET registered_workflow_hash = snapshot.workflow_hash,
    registered_snapshot_hash = snapshot.snapshot_hash,
    registered_identity_source = 'migration_backfill'
FROM dify_workflow_release_snapshot_pins pin
JOIN dify_workflow_published_snapshots snapshot
  ON snapshot.id = pin.published_snapshot_id
 AND snapshot.project_id = pin.project_id
 AND snapshot.release_id = pin.release_id
JOIN dify_workflow_execution_attempts attempt
  ON attempt.id = pin.canary_attempt_id
 AND attempt.project_id = pin.project_id
 AND attempt.release_id = pin.release_id
 AND attempt.status = 'succeeded'
WHERE release.project_id = pin.project_id
  AND release.id = pin.release_id;
ALTER TABLE dify_workflow_releases
ENABLE TRIGGER dify_workflow_releases_immutable;

ALTER TABLE dify_workflow_releases
ADD CONSTRAINT dify_workflow_releases_registered_identity_shape CHECK (
    (registered_workflow_hash IS NULL
     AND registered_snapshot_hash IS NULL
     AND registered_identity_source IS NULL)
    OR (
        registered_workflow_hash ~ '^[0-9a-f]{64}$'
        AND registered_snapshot_hash ~ '^[0-9a-f]{64}$'
        AND registered_identity_source IN ('migration_backfill', 'runtime_enrollment')
    )
);

CREATE FUNCTION geo_require_dify_release_registered_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.registered_workflow_hash IS NULL
       OR NEW.registered_snapshot_hash IS NULL
       OR NEW.registered_identity_source <> 'runtime_enrollment' THEN
        RAISE EXCEPTION 'new Dify Release requires a trusted runtime enrollment identity'
            USING ERRCODE = '23514',
                  HINT = 'Read the current Dify console graph and re-run enrollment.';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_require_dify_release_registered_identity() FROM PUBLIC;
CREATE TRIGGER dify_workflow_release_registered_identity_guard
BEFORE INSERT ON dify_workflow_releases
FOR EACH ROW EXECUTE FUNCTION geo_require_dify_release_registered_identity();

CREATE FUNCTION geo_assert_dify_snapshot_registered_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    release_row dify_workflow_releases%ROWTYPE;
BEGIN
    SELECT * INTO release_row
    FROM dify_workflow_releases release
    WHERE release.id = NEW.release_id AND release.project_id = NEW.project_id;
    IF NOT FOUND
       OR release_row.registered_workflow_hash IS NULL
       OR release_row.registered_snapshot_hash IS NULL
       OR NEW.workflow_hash <> release_row.registered_workflow_hash
       OR NEW.snapshot_hash <> release_row.registered_snapshot_hash THEN
        RAISE EXCEPTION 'published Dify graph differs from its registered GEO Release identity'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_assert_dify_snapshot_registered_identity() FROM PUBLIC;
CREATE TRIGGER dify_workflow_snapshot_registered_identity_guard
BEFORE INSERT ON dify_workflow_published_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_assert_dify_snapshot_registered_identity();

COMMENT ON COLUMN dify_workflow_releases.registered_workflow_hash IS
    'Trusted Dify console workflow hash observed before this immutable GEO Release was registered.';
COMMENT ON COLUMN dify_workflow_releases.registered_snapshot_hash IS
    'GEO canonical hash of the full trusted published workflow snapshot registered for canary.';
COMMENT ON COLUMN dify_workflow_releases.registered_identity_source IS
    'How the trusted published identity was established: migration_backfill or runtime_enrollment.';
