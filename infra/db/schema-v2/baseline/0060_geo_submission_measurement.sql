-- GEO placement submissions, public URL verification, and non-causal measurements.

CREATE TABLE placement_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_opportunity_id uuid NOT NULL,
    destination_id uuid NOT NULL,
    submission_method text NOT NULL DEFAULT 'manual',
    status text NOT NULL DEFAULT 'draft',
    submitted_by text,
    submitted_at timestamptz,
    submission_reference text,
    published_url text,
    published_at timestamptz,
    declined_reason text,
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_submissions_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_submissions_opportunity_project_fkey FOREIGN KEY (placement_opportunity_id, project_id)
        REFERENCES placement_opportunities(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_submissions_destination_project_fkey FOREIGN KEY (destination_id, project_id)
        REFERENCES project_destinations(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_submissions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_submissions_opportunity_unique UNIQUE (placement_opportunity_id),
    CONSTRAINT placement_submissions_method_canonical CHECK (submission_method = 'manual'),
    CONSTRAINT placement_submissions_status_canonical CHECK (status IN (
        'draft', 'submitted', 'accepted', 'declined', 'withdrawn', 'published'
    )),
    CONSTRAINT placement_submissions_lifecycle CHECK (
        (status = 'draft' AND submitted_by IS NULL AND submitted_at IS NULL
            AND submission_reference IS NULL AND published_url IS NULL AND published_at IS NULL
            AND declined_reason IS NULL)
        OR (status IN ('submitted', 'accepted') AND submitted_by IS NOT NULL
            AND btrim(submitted_by) <> '' AND submitted_at IS NOT NULL
            AND submission_reference IS NOT NULL AND btrim(submission_reference) <> ''
            AND published_url IS NULL AND published_at IS NULL AND declined_reason IS NULL)
        OR (status = 'declined' AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND submission_reference IS NOT NULL AND btrim(submission_reference) <> ''
            AND declined_reason IS NOT NULL AND btrim(declined_reason) <> ''
            AND published_url IS NULL AND published_at IS NULL)
        OR (status = 'withdrawn' AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND submission_reference IS NOT NULL AND btrim(submission_reference) <> ''
            AND published_url IS NULL AND published_at IS NULL)
        OR (status = 'published' AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND submission_reference IS NOT NULL AND btrim(submission_reference) <> ''
            AND published_url IS NOT NULL AND btrim(published_url) <> '' AND published_at IS NOT NULL
            AND declined_reason IS NULL)
    ),
    CONSTRAINT placement_submissions_actors_nonempty CHECK (btrim(created_by) <> '' AND btrim(updated_by) <> ''),
    CONSTRAINT placement_submissions_time_order CHECK (
        updated_at >= created_at AND (submitted_at IS NULL OR submitted_at >= created_at)
        AND (published_at IS NULL OR (submitted_at IS NOT NULL AND published_at >= submitted_at))
    )
);

CREATE TABLE placement_verification_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_submission_id uuid NOT NULL,
    published_url text NOT NULL,
    canonical_url text,
    page_content_hash text,
    indexability_status text NOT NULL,
    content_match_status text NOT NULL,
    verification_status text NOT NULL,
    verified_by text NOT NULL,
    verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    evidence_asset_id uuid,
    notes text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_verification_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_verification_submission_project_fkey FOREIGN KEY (placement_submission_id, project_id)
        REFERENCES placement_submissions(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_verification_asset_project_fkey FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_verification_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_verification_url_nonempty CHECK (btrim(published_url) <> ''),
    CONSTRAINT placement_verification_hash_valid CHECK (page_content_hash IS NULL OR page_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT placement_verification_indexability_canonical CHECK (indexability_status IN ('unknown', 'indexable', 'not_indexable', 'blocked')),
    CONSTRAINT placement_verification_match_canonical CHECK (content_match_status IN ('unknown', 'matched', 'mismatch', 'unavailable')),
    CONSTRAINT placement_verification_status_canonical CHECK (verification_status IN ('passed', 'failed', 'unavailable')),
    CONSTRAINT placement_verification_passed_coherent CHECK (
        verification_status <> 'passed' OR (indexability_status = 'indexable' AND content_match_status = 'matched')
    ),
    CONSTRAINT placement_verification_actor_nonempty CHECK (btrim(verified_by) <> '')
);

CREATE TABLE geo_measurement_windows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    window_kind text NOT NULL,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    sample_count_per_query integer NOT NULL DEFAULT 3,
    status text NOT NULL DEFAULT 'planned',
    frozen_methodology_hash text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT geo_measurement_windows_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT geo_measurement_windows_campaign_project_fkey FOREIGN KEY (campaign_id, project_id)
        REFERENCES geo_campaigns(id, project_id) ON DELETE CASCADE,
    CONSTRAINT geo_measurement_windows_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT geo_measurement_windows_campaign_kind_unique UNIQUE (campaign_id, window_kind),
    CONSTRAINT geo_measurement_windows_kind_canonical CHECK (window_kind IN ('baseline_28d', 'post_28d', 'post_56d', 'post_84d')),
    CONSTRAINT geo_measurement_windows_range_valid CHECK (ends_at > starts_at AND ends_at - starts_at = interval '28 days'),
    CONSTRAINT geo_measurement_windows_samples_positive CHECK (sample_count_per_query = 3),
    CONSTRAINT geo_measurement_windows_status_canonical CHECK (status IN ('planned', 'collecting', 'frozen', 'confounded')),
    CONSTRAINT geo_measurement_windows_hash_valid CHECK (frozen_methodology_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT geo_measurement_windows_actor_nonempty CHECK (btrim(created_by) <> '')
);

CREATE TABLE geo_measurements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    measurement_window_id uuid NOT NULL,
    geo_campaign_query_id uuid NOT NULL,
    platform text NOT NULL,
    collection_run_id uuid,
    valid_sample_count integer NOT NULL,
    recommendation_count integer NOT NULL,
    product_mention_count integer NOT NULL,
    placement_citation_count integer NOT NULL,
    total_citation_count integer NOT NULL,
    confounded boolean NOT NULL DEFAULT false,
    confounder_notes text,
    result_hash text NOT NULL,
    computed_by text NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT geo_measurements_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT geo_measurements_window_project_fkey FOREIGN KEY (measurement_window_id, project_id)
        REFERENCES geo_measurement_windows(id, project_id) ON DELETE CASCADE,
    CONSTRAINT geo_measurements_query_project_fkey FOREIGN KEY (geo_campaign_query_id, project_id)
        REFERENCES geo_campaign_queries(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT geo_measurements_collection_project_fkey FOREIGN KEY (collection_run_id, project_id)
        REFERENCES collection_runs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT geo_measurements_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT geo_measurements_window_query_platform_unique UNIQUE (measurement_window_id, geo_campaign_query_id, platform),
    CONSTRAINT geo_measurements_platform_canonical CHECK (platform IN ('chatgpt_search', 'google_search')),
    CONSTRAINT geo_measurements_counts_valid CHECK (
        valid_sample_count >= 0 AND recommendation_count BETWEEN 0 AND valid_sample_count
        AND product_mention_count BETWEEN 0 AND valid_sample_count
        AND placement_citation_count >= 0 AND total_citation_count >= placement_citation_count
    ),
    CONSTRAINT geo_measurements_confounder_coherent CHECK (
        (confounded AND confounder_notes IS NOT NULL AND btrim(confounder_notes) <> '')
        OR (NOT confounded AND confounder_notes IS NULL)
    ),
    CONSTRAINT geo_measurements_hash_valid CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT geo_measurements_actor_nonempty CHECK (btrim(computed_by) <> '')
);

CREATE FUNCTION geo_v2_reject_unqualified_destination_submission()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.project_destinations AS destination
        WHERE destination.id = NEW.destination_id
          AND destination.project_id = NEW.project_id
          AND destination.operation_mode = 'manual_submission'
          AND destination.qualification_status = 'approved'
    ) THEN
        RAISE EXCEPTION 'submission requires an approved manual-submission destination'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.placement_opportunities AS opportunity
        WHERE opportunity.id = NEW.placement_opportunity_id
          AND opportunity.project_id = NEW.project_id
          AND opportunity.destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'submission destination must match its placement opportunity'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER placement_submissions_destination_guard
    BEFORE INSERT OR UPDATE OF destination_id, placement_opportunity_id
    ON placement_submissions FOR EACH ROW
    EXECUTE FUNCTION geo_v2_reject_unqualified_destination_submission();

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'placement_submissions', 'placement_verification_runs',
        'geo_measurement_windows', 'geo_measurements'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
    END LOOP;
END;
$$;

ALTER FUNCTION geo_v2_reject_unqualified_destination_submission() OWNER TO geo_v2_result_owner;
REVOKE ALL ON placement_submissions, placement_verification_runs,
    geo_measurement_windows, geo_measurements FROM PUBLIC, geo_v2_runtime, geo_v2_worker;
REVOKE ALL ON FUNCTION geo_v2_reject_unqualified_destination_submission() FROM PUBLIC;

CREATE INDEX placement_submissions_destination_status_idx
    ON placement_submissions (destination_id, status, updated_at DESC);
CREATE INDEX geo_measurements_window_platform_idx
    ON geo_measurements (measurement_window_id, platform, computed_at DESC);
