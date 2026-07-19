ALTER TABLE monitoring_metric_snapshots
    ADD COLUMN observation_membership_version text,
    ADD COLUMN observation_membership_count integer,
    ADD COLUMN observation_membership_hash text,
    ADD CONSTRAINT monitoring_metric_membership_header_check CHECK (
        (observation_membership_version IS NULL
            AND observation_membership_count IS NULL
            AND observation_membership_hash IS NULL)
        OR (observation_membership_version = 'metric-observation-membership-v1'
            AND observation_membership_count >= 0
            AND sampled_sample_count IS NOT NULL
            AND observation_membership_count = sampled_sample_count
            AND observation_membership_hash ~ '^[0-9a-f]{64}$')
    );

ALTER TABLE monitoring_observations
    ADD CONSTRAINT monitoring_observations_membership_context_key
        UNIQUE (id, protocol_id, campaign_id, project_id);

CREATE TABLE monitoring_metric_snapshot_observations (
    snapshot_id uuid NOT NULL,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    protocol_id uuid NOT NULL,
    observation_id uuid NOT NULL,
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (snapshot_id, observation_id),
    CONSTRAINT monitoring_metric_members_snapshot_ordinal_key
        UNIQUE (snapshot_id, ordinal),
    CONSTRAINT monitoring_metric_members_snapshot_fkey FOREIGN KEY (
        snapshot_id, protocol_id, campaign_id, project_id
    ) REFERENCES monitoring_metric_snapshots(
        id, protocol_id, campaign_id, project_id
    ),
    CONSTRAINT monitoring_metric_members_observation_fkey FOREIGN KEY (
        observation_id, protocol_id, campaign_id, project_id
    ) REFERENCES monitoring_observations(
        id, protocol_id, campaign_id, project_id
    )
);

CREATE FUNCTION geo_assert_new_metric_membership_header() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.statistics_contract_version = 'geo-observation-statistics-v2' AND (
        NEW.observation_membership_version
            IS DISTINCT FROM 'metric-observation-membership-v1'
        OR NEW.observation_membership_count IS NULL
        OR NEW.observation_membership_count <> NEW.sampled_sample_count
        OR NEW.observation_membership_hash IS NULL
    ) THEN
        RAISE EXCEPTION 'new statistics v2 metric requires an observation membership manifest'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_metric_membership_member() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM monitoring_metric_snapshots AS snapshot
        JOIN monitoring_observations AS observation
          ON observation.id = NEW.observation_id
         AND observation.project_id = NEW.project_id
         AND observation.campaign_id = NEW.campaign_id
         AND observation.protocol_id = NEW.protocol_id
        WHERE snapshot.id = NEW.snapshot_id
          AND snapshot.project_id = NEW.project_id
          AND snapshot.campaign_id = NEW.campaign_id
          AND snapshot.protocol_id = NEW.protocol_id
          AND snapshot.observation_membership_version
                = 'metric-observation-membership-v1'
          AND observation.source_contract_version = 'geo-observation-source-v2'
          AND observation.measurement_window = snapshot.measurement_window
          AND observation.source_stratum_hash = snapshot.source_stratum_hash
          AND observation.query_cluster_key = snapshot.query_cluster_key
          AND observation.payload_hash = NEW.payload_hash
    ) THEN
        RAISE EXCEPTION 'metric observation member differs from its exact snapshot lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_metric_membership_manifest() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_snapshot_id uuid;
    snapshot_record record;
    actual_count integer;
    minimum_ordinal integer;
    maximum_ordinal integer;
    actual_hash text;
BEGIN
    target_snapshot_id := COALESCE(
        (to_jsonb(NEW) ->> 'snapshot_id')::uuid,
        (to_jsonb(NEW) ->> 'id')::uuid
    );
    SELECT snapshot.id, snapshot.observation_membership_version,
           snapshot.observation_membership_count,
           snapshot.observation_membership_hash,
           snapshot.sampled_sample_count
    INTO snapshot_record
    FROM monitoring_metric_snapshots AS snapshot
    WHERE snapshot.id = target_snapshot_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT count(*)::integer, min(member.ordinal), max(member.ordinal),
           encode(
               digest(
                   convert_to(
                       COALESCE(
                           string_agg(
                               member.ordinal::text || ':'
                               || member.observation_id::text || ':'
                               || member.payload_hash || E'\n',
                               '' ORDER BY member.ordinal
                           ),
                           ''
                       ),
                       'UTF8'
                   ),
                   'sha256'
               ),
               'hex'
           )
    INTO actual_count, minimum_ordinal, maximum_ordinal, actual_hash
    FROM monitoring_metric_snapshot_observations AS member
    WHERE member.snapshot_id = target_snapshot_id;

    IF snapshot_record.observation_membership_version IS NULL THEN
        IF actual_count <> 0 THEN
            RAISE EXCEPTION 'legacy metric snapshot cannot acquire fabricated membership'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    END IF;
    IF snapshot_record.observation_membership_version
            <> 'metric-observation-membership-v1'
       OR snapshot_record.observation_membership_count <> actual_count
       OR snapshot_record.sampled_sample_count <> actual_count
       OR snapshot_record.observation_membership_hash <> actual_hash
       OR (actual_count > 0 AND (
            minimum_ordinal <> 1 OR maximum_ordinal <> actual_count
       )) THEN
        RAISE EXCEPTION 'metric observation membership manifest count, ordinal or hash mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER monitoring_metric_membership_header_guard
BEFORE INSERT ON monitoring_metric_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_metric_membership_header();
CREATE TRIGGER monitoring_metric_membership_member_guard
BEFORE INSERT ON monitoring_metric_snapshot_observations
FOR EACH ROW EXECUTE FUNCTION geo_assert_metric_membership_member();
CREATE TRIGGER monitoring_metric_membership_members_immutable
BEFORE UPDATE OR DELETE ON monitoring_metric_snapshot_observations
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE CONSTRAINT TRIGGER monitoring_metric_membership_snapshot_manifest_check
AFTER INSERT ON monitoring_metric_snapshots
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_metric_membership_manifest();
CREATE CONSTRAINT TRIGGER monitoring_metric_membership_member_manifest_check
AFTER INSERT ON monitoring_metric_snapshot_observations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_metric_membership_manifest();

CREATE INDEX monitoring_metric_members_snapshot_fk_idx
ON monitoring_metric_snapshot_observations (
    snapshot_id, protocol_id, campaign_id, project_id
);
CREATE INDEX monitoring_metric_members_observation_fk_idx
ON monitoring_metric_snapshot_observations (
    observation_id, protocol_id, campaign_id, project_id
);
CREATE INDEX monitoring_metric_members_project_idx
ON monitoring_metric_snapshot_observations (
    project_id, campaign_id, protocol_id, snapshot_id, ordinal
);

ALTER TABLE monitoring_metric_snapshot_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitoring_metric_snapshot_observations FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON monitoring_metric_snapshot_observations
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON monitoring_metric_snapshot_observations
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON monitoring_metric_snapshot_observations TO geo_app;
GRANT SELECT ON monitoring_metric_snapshot_observations TO geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION
    geo_assert_new_metric_membership_header(),
    geo_assert_metric_membership_member(),
    geo_assert_metric_membership_manifest()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_assert_new_metric_membership_header(),
    geo_assert_metric_membership_member(),
    geo_assert_metric_membership_manifest()
TO geo_app;
