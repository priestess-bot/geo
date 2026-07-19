DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM monitoring_observations
        WHERE source_contract_version = 'geo-observation-source-v3'
    ) OR EXISTS (
        SELECT 1 FROM monitoring_metric_snapshots
        WHERE source_contract_version = 'geo-observation-source-v3'
    ) OR EXISTS (
        SELECT 1
        FROM monitoring_protocols AS protocol,
             LATERAL jsonb_array_elements(protocol.source_strata_snapshot) AS strata(item)
        WHERE strata.item ? 'platform_detail' OR strata.item ? 'surface_detail'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: observation source v3 data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

ALTER TABLE monitoring_observations
    DROP CONSTRAINT monitoring_observations_source_contract_version_check,
    ALTER COLUMN source_contract_version SET DEFAULT 'geo-observation-source-v2',
    ADD CONSTRAINT monitoring_observations_source_contract_version_check CHECK (
        source_contract_version IN ('legacy-v1', 'geo-observation-source-v2')
    );

ALTER TABLE monitoring_metric_snapshots
    DROP CONSTRAINT monitoring_metric_source_contract_check,
    ALTER COLUMN source_contract_version SET DEFAULT 'geo-observation-source-v2',
    ADD CONSTRAINT monitoring_metric_source_contract_check CHECK (
        source_contract_version IN ('legacy-v1', 'geo-observation-source-v2')
    );

CREATE OR REPLACE FUNCTION geo_assert_protocol_source_strata() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    item jsonb;
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.source_strata_snapshot IS NOT DISTINCT FROM OLD.source_strata_snapshot
       AND NEW.source_strata_hash IS NOT DISTINCT FROM OLD.source_strata_hash THEN
        RETURN NEW;
    END IF;
    IF jsonb_array_length(NEW.source_strata_snapshot) = 0
       OR NEW.source_strata_hash IS NULL THEN
        RAISE EXCEPTION 'new monitoring protocols require source strata'
            USING ERRCODE = '23514';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(NEW.source_strata_snapshot) LOOP
        IF NOT geo_source_stratum_json_valid(item) THEN
            RAISE EXCEPTION 'protocol source stratum is invalid'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF (
        SELECT count(DISTINCT geo_source_stratum_hash_from_json(value))
        FROM jsonb_array_elements(NEW.source_strata_snapshot)
    ) <> jsonb_array_length(NEW.source_strata_snapshot) THEN
        RAISE EXCEPTION 'protocol source strata must be unique'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.source_strata_hash <> geo_source_strata_inventory_hash(
        NEW.source_strata_snapshot
    ) THEN
        RAISE EXCEPTION 'protocol source strata inventory hash mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_new_observation_source() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_contract_version <> 'geo-observation-source-v2'
       OR NEW.capture_method IN ('unknown', 'official_report_import') THEN
        RAISE EXCEPTION 'new answer observations require a typed non-official source'
            USING ERRCODE = '23514';
    END IF;
    IF NOT geo_observation_surface_matches(
        NEW.capture_method, NEW.platform, NEW.platform_detail, NEW.surface,
        NEW.surface_kind, NEW.surface_detail
    ) OR NEW.ui_surface <> NEW.surface THEN
        RAISE EXCEPTION 'observation platform and surface contract mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NOT geo_ascii_nonempty(NEW.engine)
       OR NOT geo_ascii_nonempty(NEW.locale)
       OR NOT geo_ascii_nonempty(NEW.region)
       OR NOT geo_ascii_nonempty(NEW.language)
       OR NEW.observation_device IS NULL OR NEW.client_kind IS NULL
       OR NEW.search_enabled IS NULL OR NEW.search_mode IS NULL
       OR btrim(COALESCE(NEW.prompt_text, '')) = ''
       OR btrim(COALESCE(NEW.query_cluster_key, '')) = '' THEN
        RAISE EXCEPTION 'observation run parameters are incomplete'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.search_enabled AND NEW.search_mode IN ('disabled', 'not_applicable'))
       OR (NOT NEW.search_enabled
           AND NEW.search_mode NOT IN ('disabled', 'not_applicable')) THEN
        RAISE EXCEPTION 'observation search mode mismatch' USING ERRCODE = '23514';
    END IF;
    IF NEW.configured_model_state = 'not_applicable'
       OR (NEW.configured_model IS NOT NULL
           AND octet_length(NEW.configured_model) <> char_length(NEW.configured_model))
       OR (NEW.provider_reported_model IS NOT NULL
           AND octet_length(NEW.provider_reported_model)
               <> char_length(NEW.provider_reported_model)) THEN
        RAISE EXCEPTION 'observation model identity is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.capture_method IN ('provider_api', 'proxy_grounded_api', 'synthetic')
       AND (
           NEW.configured_model_state <> 'disclosed'
           OR btrim(COALESCE(NEW.adapter_name, '')) = ''
           OR btrim(COALESCE(NEW.adapter_version, '')) = ''
       ) THEN
        RAISE EXCEPTION 'API and synthetic observations require adapter identity'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.capture_method IN ('provider_api', 'proxy_grounded_api')
       AND btrim(COALESCE(NEW.provider_request_id, '')) = '' THEN
        RAISE EXCEPTION 'provider observations require a provider request id'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.capture_method = 'proxy_grounded_api' AND NOT NEW.search_enabled THEN
        RAISE EXCEPTION 'grounded proxy observations require search'
            USING ERRCODE = '23514';
    END IF;
    IF NOT NEW.citations_captured THEN
        RAISE EXCEPTION 'new observations must confirm citation capture'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.raw_evidence_kind = 'answer' AND (
            btrim(COALESCE(NEW.raw_answer, '')) = '' OR NEW.artifact_uri IS NOT NULL
        )) OR (NEW.raw_evidence_kind = 'inline_response' AND (
            NEW.raw_answer IS NOT NULL OR NEW.raw_result = '{}'::jsonb
            OR NEW.artifact_uri IS NOT NULL
        )) OR (NEW.raw_evidence_kind = 'artifact' AND (
            NEW.raw_answer IS NOT NULL OR NEW.artifact_uri IS NULL
        )) OR NEW.raw_evidence_kind = 'legacy_unknown' THEN
        RAISE EXCEPTION 'observation raw evidence does not match its kind'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.source_stratum_hash IS DISTINCT FROM geo_observation_source_stratum_hash(
        NEW.capture_method, NEW.platform, NEW.surface, NEW.surface_kind, NEW.engine,
        NEW.configured_model_state, NEW.configured_model,
        NEW.provider_reported_model_state, NEW.provider_reported_model,
        NEW.locale, NEW.region, NEW.language, NEW.observation_device,
        NEW.client_kind, NEW.search_enabled, NEW.search_mode
    ) THEN
        RAISE EXCEPTION 'observation source stratum hash mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM monitoring_protocol_queries AS query
        WHERE query.protocol_id = NEW.protocol_id
          AND query.project_id = NEW.project_id
          AND query.monitoring_query_id = NEW.monitoring_query_id
          AND query.query_cluster_key = NEW.query_cluster_key
    ) THEN
        RAISE EXCEPTION 'observation query cluster does not match the frozen query'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.eligible AND NOT EXISTS (
        SELECT 1
        FROM monitoring_protocols AS protocol,
             LATERAL jsonb_array_elements(protocol.source_strata_snapshot) AS strata(item)
        WHERE protocol.id = NEW.protocol_id AND protocol.project_id = NEW.project_id
          AND protocol.status = 'frozen'
          AND geo_source_stratum_hash_from_json(strata.item) = NEW.source_stratum_hash
    ) THEN
        RAISE EXCEPTION 'eligible observation stratum was not frozen into the protocol'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.eligible AND (
        NOT NEW.eligibility_requested OR NEW.result_status <> 'succeeded'
        OR cardinality(NEW.ineligible_reasons) <> 0
        OR NOT NEW.publication_eligible OR NEW.test_only
    ) THEN
        RAISE EXCEPTION 'stored observation eligibility is not server-derived'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.capture_method = 'synthetic' THEN
        IF NOT pg_has_role(session_user, 'geo_worker', 'USAGE')
           OR NOT NEW.test_only OR NEW.publication_eligible OR NEW.eligible
           OR NOT ('synthetic_test_only' = ANY(NEW.ineligible_reasons))
           OR NEW.raw_evidence_kind <> 'artifact'
           OR NEW.source_job_id IS NULL OR NEW.model_call_log_id IS NULL THEN
            RAISE EXCEPTION 'synthetic observations are worker-only and test-only'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM durable_jobs AS job
            JOIN prompt_simulation_job_specs AS spec
              ON spec.job_id = job.id AND spec.project_id = job.project_id
             AND spec.campaign_id = job.campaign_id
            JOIN prompt_simulations AS simulation
              ON simulation.id = spec.simulation_id
             AND simulation.project_id = spec.project_id
             AND simulation.campaign_id = spec.campaign_id
             AND simulation.opportunity_id = spec.opportunity_id
            JOIN prompt_simulation_results AS result
              ON result.simulation_id = simulation.id
             AND result.project_id = simulation.project_id
             AND result.campaign_id = simulation.campaign_id
             AND result.opportunity_id = simulation.opportunity_id
             AND result.generated_by_job_id = job.id
            JOIN model_call_logs AS model_call
              ON model_call.id = NEW.model_call_log_id
             AND model_call.project_id = job.project_id
             AND model_call.job_id = job.id
            JOIN artifact_finalize_outbox AS artifact
              ON artifact.project_id = simulation.project_id
             AND artifact.campaign_id = simulation.campaign_id
             AND artifact.opportunity_id = simulation.opportunity_id
             AND artifact.destination_id = simulation.destination_id
             AND artifact.resource_kind = 'prompt_simulation'
             AND artifact.resource_id = simulation.id
            WHERE job.id = NEW.source_job_id AND job.project_id = NEW.project_id
              AND job.campaign_id = NEW.campaign_id
              AND job.kind = 'prompt_simulation.generate' AND job.status = 'succeeded'
              AND simulation.binding_contract_version = 'opportunity-binding-v2'
              AND result.lineage_contract_version = 'opportunity-binding-v2'
              AND model_call.status = 'succeeded'
              AND model_call.configured_model = NEW.configured_model
              AND model_call.provider_reported_model
                    IS NOT DISTINCT FROM NEW.provider_reported_model
              AND artifact.status = 'finalized'
              AND artifact.final_uri = NEW.artifact_uri
              AND artifact.content_hash = NEW.artifact_hash
        ) THEN
            RAISE EXCEPTION 'synthetic observation lineage is incomplete'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.test_only OR NOT NEW.publication_eligible
          OR NEW.source_job_id IS NOT NULL OR NEW.model_call_log_id IS NOT NULL THEN
        RAISE EXCEPTION 'public answer observations cannot use synthetic flags'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_require_observation_citation_capture() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_contract_version = 'geo-observation-source-v2' AND (
        SELECT count(*) FROM monitoring_observation_citations AS citation
        WHERE citation.observation_id = NEW.id AND citation.project_id = NEW.project_id
    ) <> jsonb_array_length(NEW.raw_citations) THEN
        RAISE EXCEPTION 'captured citation rows do not match raw citation evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_new_metric_source_stratum() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_contract_version <> 'geo-observation-source-v2'
       OR NEW.capture_method NOT IN ('manual_ui', 'provider_api', 'proxy_grounded_api')
       OR NEW.source_stratum IS NULL
       OR NOT geo_source_stratum_json_valid(NEW.source_stratum)
       OR NEW.capture_method <> NEW.source_stratum ->> 'capture_method'
       OR NEW.source_stratum_hash IS DISTINCT FROM
            geo_source_stratum_hash_from_json(NEW.source_stratum)
       OR NOT EXISTS (
            SELECT 1
            FROM monitoring_protocols AS protocol,
                 LATERAL jsonb_array_elements(
                     protocol.source_strata_snapshot
                 ) AS strata(item)
            WHERE protocol.id = NEW.protocol_id AND protocol.project_id = NEW.project_id
              AND protocol.campaign_id = NEW.campaign_id
              AND protocol.status = 'frozen'
              AND geo_source_stratum_hash_from_json(strata.item)
                    = NEW.source_stratum_hash
       ) THEN
        RAISE EXCEPTION 'metric snapshot source stratum is not frozen and eligible'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_metric_membership_member() RETURNS trigger
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

DROP FUNCTION geo_source_strata_v3_inventory_hash(jsonb);
DROP FUNCTION geo_source_stratum_v3_hash_from_json(jsonb);
DROP FUNCTION geo_source_stratum_v3_json_valid(jsonb);
DROP FUNCTION geo_observation_source_stratum_v3_hash(
    text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,boolean,text
);
DROP FUNCTION geo_observation_source_stratum_v3_canonical(
    text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,boolean,text
);
