DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM monitoring_metric_snapshot_observations)
       OR EXISTS (
           SELECT 1 FROM monitoring_metric_snapshots
           WHERE observation_membership_version IS NOT NULL
              OR observation_membership_count IS NOT NULL
              OR observation_membership_hash IS NOT NULL
       ) THEN
        RAISE EXCEPTION 'cannot downgrade: frozen metric observation membership exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER monitoring_metric_membership_snapshot_manifest_check
ON monitoring_metric_snapshots;
DROP TRIGGER monitoring_metric_membership_header_guard
ON monitoring_metric_snapshots;
DROP TRIGGER monitoring_metric_membership_member_manifest_check
ON monitoring_metric_snapshot_observations;
DROP TRIGGER monitoring_metric_membership_member_guard
ON monitoring_metric_snapshot_observations;
DROP TRIGGER monitoring_metric_membership_members_immutable
ON monitoring_metric_snapshot_observations;
DROP FUNCTION geo_assert_metric_membership_manifest();
DROP FUNCTION geo_assert_metric_membership_member();
DROP FUNCTION geo_assert_new_metric_membership_header();

DROP TABLE monitoring_metric_snapshot_observations;
ALTER TABLE monitoring_observations
    DROP CONSTRAINT monitoring_observations_membership_context_key;
ALTER TABLE monitoring_metric_snapshots
    DROP CONSTRAINT monitoring_metric_membership_header_check,
    DROP COLUMN observation_membership_hash,
    DROP COLUMN observation_membership_count,
    DROP COLUMN observation_membership_version;
