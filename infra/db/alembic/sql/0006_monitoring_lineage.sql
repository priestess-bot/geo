CREATE FUNCTION geo_assert_monitoring_citation_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    observation_campaign_id uuid;
    submission_campaign_id uuid;
    submission_destination_id uuid;
    submission_url text;
    submission_verified_at timestamptz;
BEGIN
    SELECT campaign_id INTO observation_campaign_id
    FROM monitoring_observations
    WHERE id = NEW.observation_id AND project_id = NEW.project_id;

    IF NEW.submission_id IS NULL THEN
        IF NEW.destination_id IS NOT NULL OR NEW.verification_status = 'passed'
           OR NEW.verified_at IS NOT NULL THEN
            RAISE EXCEPTION 'trusted citation metadata requires verified submission lineage'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    SELECT opportunity.campaign_id, request.destination_id,
           submission.submitted_url, submission.verified_at
    INTO submission_campaign_id, submission_destination_id,
         submission_url, submission_verified_at
    FROM publication_submissions submission
    JOIN publication_requests request
      ON request.id = submission.publication_request_id
     AND request.project_id = submission.project_id
    JOIN placement_package_versions version
      ON version.id = request.package_version_id
     AND version.project_id = request.project_id
    JOIN placement_packages package
      ON package.id = version.package_id AND package.project_id = version.project_id
    JOIN placement_opportunities opportunity
      ON opportunity.id = package.opportunity_id
     AND opportunity.project_id = package.project_id
    WHERE submission.id = NEW.submission_id AND submission.project_id = NEW.project_id
      AND submission.status = 'verified' AND submission.submitted_url IS NOT NULL
      AND submission.verified_at IS NOT NULL;

    IF NOT FOUND OR submission_campaign_id IS DISTINCT FROM observation_campaign_id
       OR submission_destination_id IS DISTINCT FROM NEW.destination_id
       OR submission_url IS DISTINCT FROM NEW.url
       OR NEW.verification_status <> 'passed'
       OR submission_verified_at IS DISTINCT FROM NEW.verified_at THEN
        RAISE EXCEPTION 'citation does not match verified publication lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER monitoring_observation_citation_lineage_guard
BEFORE INSERT ON monitoring_observation_citations
FOR EACH ROW EXECUTE FUNCTION geo_assert_monitoring_citation_lineage();

REVOKE ALL ON FUNCTION geo_assert_monitoring_citation_lineage() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_assert_monitoring_citation_lineage()
TO geo_app, geo_worker, geo_readonly;
