CREATE TABLE knowledge_question_generation_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    model_call_budget integer NOT NULL CHECK (model_call_budget BETWEEN 1 AND 1000),
    adapter_release text NOT NULL CHECK (adapter_release IN (
        'project-native-rag-v1', 'llamaindex-property-graph-v1'
    )),
    selection_manifest_hash text NOT NULL CHECK (
        selection_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    dimension_schema_version text NOT NULL
        CHECK (dimension_schema_version = 'geo-question-dimensions-v1'),
    embedding_model_key text NOT NULL
        CHECK (embedding_model_key = 'geo-question-semantic-hash-v1'),
    semantic_duplicate_threshold numeric(5,4) NOT NULL DEFAULT 0.9200
        CHECK (semantic_duplicate_threshold BETWEEN 0.8000 AND 1.0000),
    requested_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_question_specs_job_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_question_specs_campaign_fkey
        FOREIGN KEY (campaign_id, project_id)
        REFERENCES geo_campaigns(id, project_id),
    CONSTRAINT knowledge_question_specs_exact_context_key
        UNIQUE (job_id, project_id, campaign_id)
);

CREATE TRIGGER knowledge_question_generation_spec_kind
BEFORE INSERT OR UPDATE ON knowledge_question_generation_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('knowledge.question.generate');
CREATE TRIGGER knowledge_question_generation_specs_immutable
BEFORE UPDATE ON knowledge_question_generation_specs
FOR EACH ROW EXECUTE FUNCTION geo_reject_placement_job_spec_update();
CREATE CONSTRAINT TRIGGER knowledge_question_generation_specs_delete_guard
AFTER DELETE ON knowledge_question_generation_specs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();

CREATE TABLE knowledge_question_dimensions (
    job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    dimension_key text NOT NULL CHECK (btrim(dimension_key) <> ''),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    turn_index integer NOT NULL CHECK (turn_index BETWEEN 1 AND 3),
    parent_dimension_key text,
    persona text NOT NULL CHECK (btrim(persona) <> ''),
    scenario text NOT NULL CHECK (btrim(scenario) <> ''),
    intent text NOT NULL CHECK (btrim(intent) <> ''),
    funnel text NOT NULL CHECK (
        funnel IN ('awareness', 'consideration', 'decision', 'retention')
    ),
    region text NOT NULL CHECK (btrim(region) <> ''),
    language text NOT NULL CHECK (btrim(language) <> ''),
    brand_scope text NOT NULL CHECK (
        brand_scope IN ('brand', 'non_brand', 'competitor')
    ),
    platform text NOT NULL CHECK (platform IN (
        'chatgpt_search', 'google_ai_overviews', 'google_search',
        'perplexity', 'gemini', 'other'
    )),
    query_kind text NOT NULL CHECK (
        query_kind IN ('recommendation', 'comparison', 'research', 'support')
    ),
    subject text NOT NULL CHECK (btrim(subject) <> ''),
    competitor_entity_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (job_id, dimension_key),
    CONSTRAINT knowledge_question_dimensions_ordinal_key UNIQUE (job_id, ordinal),
    CONSTRAINT knowledge_question_dimensions_exact_context_key UNIQUE (
        job_id, project_id, campaign_id, dimension_key
    ),
    CONSTRAINT knowledge_question_dimensions_spec_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES knowledge_question_generation_specs(job_id, project_id, campaign_id),
    CONSTRAINT knowledge_question_dimensions_parent_fkey FOREIGN KEY (
        job_id, project_id, campaign_id, parent_dimension_key
    ) REFERENCES knowledge_question_dimensions(
        job_id, project_id, campaign_id, dimension_key
    ) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT knowledge_question_dimensions_competitor_fkey
        FOREIGN KEY (competitor_entity_id, project_id)
        REFERENCES product_entities(id, project_id),
    CONSTRAINT knowledge_question_dimensions_turn_shape_check CHECK (
        (turn_index = 1 AND parent_dimension_key IS NULL)
        OR (turn_index > 1 AND parent_dimension_key IS NOT NULL)
    ),
    CONSTRAINT knowledge_question_dimensions_competitor_shape_check CHECK (
        (brand_scope = 'competitor' AND competitor_entity_id IS NOT NULL)
        OR (brand_scope <> 'competitor' AND competitor_entity_id IS NULL)
    )
);

CREATE TABLE knowledge_question_generation_fact_inputs (
    job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    fact_candidate_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    rag_revision_id uuid,
    statement_snapshot text NOT NULL CHECK (btrim(statement_snapshot) <> ''),
    statement_hash text NOT NULL CHECK (statement_hash ~ '^[0-9a-f]{64}$'),
    source_locator text,
    extractor_release text NOT NULL CHECK (btrim(extractor_release) <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (job_id, fact_candidate_id),
    CONSTRAINT knowledge_question_fact_inputs_exact_context_key UNIQUE (
        job_id, project_id, campaign_id, fact_candidate_id
    ),
    CONSTRAINT knowledge_question_fact_inputs_spec_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES knowledge_question_generation_specs(job_id, project_id, campaign_id),
    CONSTRAINT knowledge_question_fact_inputs_fact_fkey FOREIGN KEY (
        fact_candidate_id, project_id, pipeline_run_id, source_id,
        document_id, chunk_id, statement_hash
    ) REFERENCES knowledge_fact_candidates(
        id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
        statement_hash
    ),
    CONSTRAINT knowledge_question_fact_inputs_chunk_fkey FOREIGN KEY (
        chunk_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_chunks(
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_question_fact_inputs_revision_fkey FOREIGN KEY (
        rag_revision_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, pipeline_run_id, source_id, document_id
    )
);

CREATE TABLE knowledge_question_generation_entity_inputs (
    job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    graph_entity_id uuid NOT NULL,
    entity_type_snapshot text NOT NULL CHECK (entity_type_snapshot IN (
        'brand', 'product', 'competitor', 'feature', 'specification',
        'use_case', 'persona', 'pain_point', 'market', 'channel'
    )),
    canonical_name_snapshot text NOT NULL CHECK (btrim(canonical_name_snapshot) <> ''),
    name_hash text NOT NULL CHECK (name_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (job_id, graph_entity_id),
    CONSTRAINT knowledge_question_entity_inputs_exact_context_key UNIQUE (
        job_id, project_id, campaign_id, graph_entity_id
    ),
    CONSTRAINT knowledge_question_entity_inputs_spec_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES knowledge_question_generation_specs(job_id, project_id, campaign_id),
    CONSTRAINT knowledge_question_entity_inputs_graph_fkey
        FOREIGN KEY (graph_entity_id, project_id)
        REFERENCES knowledge_graph_entities(id, project_id)
);

CREATE TABLE knowledge_question_generation_results (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    output_hash text NOT NULL CHECK (output_hash ~ '^[0-9a-f]{64}$'),
    artifact_uri text NOT NULL CHECK (artifact_uri ~ '^s3://[^/]+/.+$'),
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    dimension_count integer NOT NULL CHECK (dimension_count >= 0),
    candidate_count integer NOT NULL CHECK (candidate_count >= 0),
    supported_dimension_count integer NOT NULL CHECK (
        supported_dimension_count >= 0 AND supported_dimension_count <= dimension_count
    ),
    possible_duplicate_count integer NOT NULL CHECK (
        possible_duplicate_count >= 0 AND possible_duplicate_count <= candidate_count
    ),
    generated_at timestamptz NOT NULL,
    CONSTRAINT knowledge_question_results_artifact_check CHECK (
        output_hash = artifact_hash
    ),
    CONSTRAINT knowledge_question_results_exact_context_key
        UNIQUE (job_id, project_id, campaign_id),
    CONSTRAINT knowledge_question_results_spec_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES knowledge_question_generation_specs(job_id, project_id, campaign_id)
);

CREATE TABLE knowledge_question_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    generated_by_job_id uuid NOT NULL,
    adapter_candidate_id text NOT NULL CHECK (btrim(adapter_candidate_id) <> ''),
    dimension_key text NOT NULL,
    variant_index integer NOT NULL CHECK (variant_index BETWEEN 1 AND 3),
    turn_index integer NOT NULL CHECK (turn_index BETWEEN 1 AND 3),
    parent_candidate_id uuid,
    query_text text NOT NULL CHECK (btrim(query_text) <> ''),
    query_text_hash text NOT NULL CHECK (query_text_hash ~ '^[0-9a-f]{64}$'),
    normalized_text_hash text NOT NULL CHECK (
        normalized_text_hash ~ '^[0-9a-f]{64}$'
    ),
    semantic_fingerprint text NOT NULL CHECK (btrim(semantic_fingerprint) <> ''),
    embedding vector(1024) NOT NULL,
    embedding_model_key text NOT NULL
        CHECK (embedding_model_key = 'geo-question-semantic-hash-v1'),
    nearest_candidate_id uuid,
    nearest_similarity numeric(5,4),
    dedup_status text NOT NULL CHECK (
        dedup_status IN ('unique', 'possible_duplicate', 'exact_duplicate')
    ),
    workflow_status text NOT NULL DEFAULT 'pending_review' CHECK (
        workflow_status IN ('pending_review', 'approved', 'rejected')
    ),
    reviewed_by uuid REFERENCES identities(id),
    review_notes text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_question_candidates_review_shape_check CHECK (
        (workflow_status = 'pending_review'
            AND reviewed_by IS NULL AND reviewed_at IS NULL)
        OR (workflow_status IN ('approved', 'rejected')
            AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
    ),
    CONSTRAINT knowledge_question_candidates_nearest_pair_check CHECK (
        (nearest_candidate_id IS NULL) = (nearest_similarity IS NULL)
        AND (nearest_similarity IS NULL OR nearest_similarity BETWEEN -1 AND 1)
    ),
    CONSTRAINT knowledge_question_candidates_turn_shape_check CHECK (
        (turn_index = 1 AND parent_candidate_id IS NULL)
        OR (turn_index > 1 AND parent_candidate_id IS NOT NULL)
    ),
    CONSTRAINT knowledge_question_candidates_exact_context_key UNIQUE (
        id, generated_by_job_id, project_id, campaign_id
    ),
    CONSTRAINT knowledge_question_candidates_adapter_key
        UNIQUE (generated_by_job_id, adapter_candidate_id),
    CONSTRAINT knowledge_question_candidates_variant_key
        UNIQUE (generated_by_job_id, dimension_key, variant_index),
    CONSTRAINT knowledge_question_candidates_spec_fkey
        FOREIGN KEY (generated_by_job_id, project_id, campaign_id)
        REFERENCES knowledge_question_generation_specs(job_id, project_id, campaign_id),
    CONSTRAINT knowledge_question_candidates_dimension_fkey FOREIGN KEY (
        generated_by_job_id, project_id, campaign_id, dimension_key
    ) REFERENCES knowledge_question_dimensions(
        job_id, project_id, campaign_id, dimension_key
    ),
    CONSTRAINT knowledge_question_candidates_parent_fkey FOREIGN KEY (
        parent_candidate_id, generated_by_job_id, project_id, campaign_id
    ) REFERENCES knowledge_question_candidates(
        id, generated_by_job_id, project_id, campaign_id
    ) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT knowledge_question_candidates_nearest_fkey FOREIGN KEY (
        nearest_candidate_id, generated_by_job_id, project_id, campaign_id
    ) REFERENCES knowledge_question_candidates(
        id, generated_by_job_id, project_id, campaign_id
    ) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE knowledge_question_candidate_fact_sources (
    candidate_id uuid NOT NULL,
    generated_by_job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    fact_candidate_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (candidate_id, fact_candidate_id),
    CONSTRAINT knowledge_question_candidate_fact_sources_candidate_fkey FOREIGN KEY (
        candidate_id, generated_by_job_id, project_id, campaign_id
    ) REFERENCES knowledge_question_candidates(
        id, generated_by_job_id, project_id, campaign_id
    ),
    CONSTRAINT knowledge_question_candidate_fact_sources_input_fkey FOREIGN KEY (
        generated_by_job_id, project_id, campaign_id, fact_candidate_id
    ) REFERENCES knowledge_question_generation_fact_inputs(
        job_id, project_id, campaign_id, fact_candidate_id
    )
);

CREATE TABLE knowledge_question_candidate_entity_sources (
    candidate_id uuid NOT NULL,
    generated_by_job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    graph_entity_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (candidate_id, graph_entity_id),
    CONSTRAINT knowledge_question_candidate_entity_sources_candidate_fkey FOREIGN KEY (
        candidate_id, generated_by_job_id, project_id, campaign_id
    ) REFERENCES knowledge_question_candidates(
        id, generated_by_job_id, project_id, campaign_id
    ),
    CONSTRAINT knowledge_question_candidate_entity_sources_input_fkey FOREIGN KEY (
        generated_by_job_id, project_id, campaign_id, graph_entity_id
    ) REFERENCES knowledge_question_generation_entity_inputs(
        job_id, project_id, campaign_id, graph_entity_id
    )
);

CREATE TABLE knowledge_question_sets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    series_id uuid NOT NULL,
    previous_version_id uuid,
    version_number integer NOT NULL CHECK (version_number > 0),
    generated_by_job_id uuid NOT NULL,
    name text NOT NULL CHECK (btrim(name) <> ''),
    status text NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'approved', 'frozen')
    ),
    dimension_count integer NOT NULL CHECK (dimension_count > 0),
    covered_dimension_count integer NOT NULL CHECK (
        covered_dimension_count > 0 AND covered_dimension_count <= dimension_count
    ),
    possible_duplicate_count integer NOT NULL CHECK (possible_duplicate_count >= 0),
    coverage_ratio numeric(5,4) NOT NULL CHECK (coverage_ratio BETWEEN 0 AND 1),
    duplicate_ratio numeric(5,4) NOT NULL CHECK (duplicate_ratio BETWEEN 0 AND 1),
    content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    approved_by uuid REFERENCES identities(id),
    approved_at timestamptz,
    frozen_by uuid REFERENCES identities(id),
    frozen_at timestamptz,
    CONSTRAINT knowledge_question_sets_status_shape_check CHECK (
        (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL
            AND frozen_by IS NULL AND frozen_at IS NULL AND content_hash IS NULL)
        OR (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND frozen_by IS NULL AND frozen_at IS NULL AND content_hash IS NULL)
        OR (status = 'frozen' AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND frozen_by IS NOT NULL AND frozen_at IS NOT NULL
            AND content_hash IS NOT NULL)
    ),
    CONSTRAINT knowledge_question_sets_version_shape_check CHECK (
        (id = series_id AND previous_version_id IS NULL AND version_number = 1)
        OR (id <> series_id AND previous_version_id IS NOT NULL AND version_number > 1)
    ),
    CONSTRAINT knowledge_question_sets_exact_context_key
        UNIQUE (id, campaign_id, project_id),
    CONSTRAINT knowledge_question_sets_exact_series_key
        UNIQUE (id, project_id, campaign_id, series_id),
    CONSTRAINT knowledge_question_sets_exact_hash_key
        UNIQUE (id, campaign_id, project_id, content_hash),
    CONSTRAINT knowledge_question_sets_series_version_key
        UNIQUE (series_id, version_number),
    CONSTRAINT knowledge_question_sets_single_successor_key
        UNIQUE (previous_version_id, project_id, campaign_id),
    CONSTRAINT knowledge_question_sets_spec_fkey
        FOREIGN KEY (generated_by_job_id, project_id, campaign_id)
        REFERENCES knowledge_question_generation_specs(job_id, project_id, campaign_id),
    CONSTRAINT knowledge_question_sets_previous_fkey FOREIGN KEY (
        previous_version_id, project_id, campaign_id, series_id
    ) REFERENCES knowledge_question_sets(id, project_id, campaign_id, series_id)
);

CREATE TABLE knowledge_question_set_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    question_set_id uuid NOT NULL,
    generated_by_job_id uuid NOT NULL,
    question_candidate_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    dimension_key text NOT NULL CHECK (btrim(dimension_key) <> ''),
    query_text_snapshot text NOT NULL CHECK (btrim(query_text_snapshot) <> ''),
    query_text_hash text NOT NULL CHECK (query_text_hash ~ '^[0-9a-f]{64}$'),
    normalized_text_hash text NOT NULL CHECK (
        normalized_text_hash ~ '^[0-9a-f]{64}$'
    ),
    query_kind_snapshot text NOT NULL CHECK (
        query_kind_snapshot IN ('recommendation', 'comparison', 'research', 'support')
    ),
    query_cluster_key text NOT NULL CHECK (btrim(query_cluster_key) <> ''),
    source_lineage_hash text NOT NULL CHECK (
        source_lineage_hash ~ '^[0-9a-f]{64}$'
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_question_set_items_ordinal_key
        UNIQUE (question_set_id, ordinal),
    CONSTRAINT knowledge_question_set_items_candidate_key
        UNIQUE (question_set_id, question_candidate_id),
    CONSTRAINT knowledge_question_set_items_normalized_key
        UNIQUE (question_set_id, normalized_text_hash),
    CONSTRAINT knowledge_question_set_items_exact_context_key UNIQUE (
        id, question_set_id, question_candidate_id, generated_by_job_id,
        project_id, campaign_id
    ),
    CONSTRAINT knowledge_question_set_items_protocol_lineage_key UNIQUE (
        id, question_candidate_id, project_id
    ),
    CONSTRAINT knowledge_question_set_items_simulation_lineage_key UNIQUE (
        id, question_candidate_id, project_id, campaign_id
    ),
    CONSTRAINT knowledge_question_set_items_set_fkey
        FOREIGN KEY (question_set_id, campaign_id, project_id)
        REFERENCES knowledge_question_sets(id, campaign_id, project_id),
    CONSTRAINT knowledge_question_set_items_candidate_fkey FOREIGN KEY (
        question_candidate_id, generated_by_job_id, project_id, campaign_id
    ) REFERENCES knowledge_question_candidates(
        id, generated_by_job_id, project_id, campaign_id
    )
);

ALTER TABLE knowledge_question_candidates
    ADD CONSTRAINT knowledge_question_candidates_project_campaign_key
        UNIQUE (id, project_id, campaign_id);

ALTER TABLE monitoring_protocols
    ADD COLUMN question_set_id uuid,
    ADD COLUMN question_set_hash text,
    ADD COLUMN question_set_bound_by uuid REFERENCES identities(id),
    ADD COLUMN question_set_bound_at timestamptz,
    ADD CONSTRAINT monitoring_protocols_question_set_shape_check CHECK (
        num_nonnulls(
            question_set_id, question_set_hash,
            question_set_bound_by, question_set_bound_at
        ) IN (0, 4)
        AND (question_set_hash IS NULL OR question_set_hash ~ '^[0-9a-f]{64}$')
    ),
    ADD CONSTRAINT monitoring_protocols_question_set_fkey FOREIGN KEY (
        question_set_id, campaign_id, project_id, question_set_hash
    ) REFERENCES knowledge_question_sets(
        id, campaign_id, project_id, content_hash
    );

ALTER TABLE monitoring_query_suggestions
    ADD COLUMN question_set_item_id uuid,
    ADD COLUMN question_candidate_id uuid,
    ADD CONSTRAINT monitoring_suggestions_question_lineage_pair_check CHECK (
        (question_set_item_id IS NULL) = (question_candidate_id IS NULL)
    ),
    ADD CONSTRAINT monitoring_suggestions_question_lineage_fkey FOREIGN KEY (
        question_set_item_id, question_candidate_id, project_id
    ) REFERENCES knowledge_question_set_items(
        id, question_candidate_id, project_id
    ),
    ADD CONSTRAINT monitoring_suggestions_question_item_key
        UNIQUE (protocol_id, question_set_item_id);

ALTER TABLE monitoring_protocol_queries
    ADD COLUMN question_set_item_id uuid,
    ADD COLUMN question_candidate_id uuid,
    ADD CONSTRAINT monitoring_protocol_queries_question_lineage_pair_check CHECK (
        (question_set_item_id IS NULL) = (question_candidate_id IS NULL)
    ),
    ADD CONSTRAINT monitoring_protocol_queries_question_lineage_fkey FOREIGN KEY (
        question_set_item_id, question_candidate_id, project_id
    ) REFERENCES knowledge_question_set_items(
        id, question_candidate_id, project_id
    ),
    ADD CONSTRAINT monitoring_protocol_queries_question_item_key
        UNIQUE (protocol_id, question_set_item_id);

ALTER TABLE prompt_simulations
    ADD COLUMN simulation_purpose text NOT NULL DEFAULT 'content_preview'
        CHECK (simulation_purpose IN ('content_preview', 'geo_question_test')),
    ADD COLUMN question_set_id uuid,
    ADD COLUMN question_set_hash text,
    ADD COLUMN question_set_item_id uuid,
    ADD COLUMN question_candidate_id uuid,
    ADD CONSTRAINT prompt_simulations_question_shape_check CHECK (
        (simulation_purpose = 'content_preview'
            AND num_nonnulls(
                question_set_id, question_set_hash,
                question_set_item_id, question_candidate_id
            ) = 0)
        OR (simulation_purpose = 'geo_question_test'
            AND num_nulls(
                question_set_id, question_set_hash,
                question_set_item_id, question_candidate_id
            ) = 0
            AND binding_contract_version = 'opportunity-binding-v2'
            AND test_only AND NOT publication_eligible)
    ),
    ADD CONSTRAINT prompt_simulations_question_set_hash_check CHECK (
        question_set_hash IS NULL OR question_set_hash ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT prompt_simulations_question_set_fkey FOREIGN KEY (
        question_set_id, campaign_id, project_id, question_set_hash
    ) REFERENCES knowledge_question_sets(
        id, campaign_id, project_id, content_hash
    ),
    ADD CONSTRAINT prompt_simulations_question_item_fkey FOREIGN KEY (
        question_set_item_id, question_candidate_id, project_id, campaign_id
    ) REFERENCES knowledge_question_set_items(
        id, question_candidate_id, project_id, campaign_id
    );

CREATE FUNCTION geo_assert_question_dimension() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_turn integer;
BEGIN
    IF (
        SELECT count(*) FROM knowledge_question_dimensions AS dimension
        WHERE dimension.job_id = NEW.job_id
    ) >= 200 THEN
        RAISE EXCEPTION 'Question generation supports at most 200 dimensions per job'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.parent_dimension_key IS NOT NULL THEN
        SELECT dimension.turn_index INTO parent_turn
        FROM knowledge_question_dimensions AS dimension
        WHERE dimension.job_id = NEW.job_id
          AND dimension.project_id = NEW.project_id
          AND dimension.campaign_id = NEW.campaign_id
          AND dimension.dimension_key = NEW.parent_dimension_key;
        IF parent_turn IS NULL OR parent_turn >= NEW.turn_index THEN
            RAISE EXCEPTION 'multi-turn Question dimension requires an earlier parent turn'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.competitor_entity_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM product_entities AS competitor
        WHERE competitor.id = NEW.competitor_entity_id
          AND competitor.project_id = NEW.project_id
          AND competitor.entity_type = 'competitor'
          AND competitor.status = 'active'
    ) THEN
        RAISE EXCEPTION 'competitor Question dimension requires an active Catalog competitor'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_question_fact_input() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (
        SELECT count(*) FROM knowledge_question_generation_fact_inputs AS input
        WHERE input.job_id = NEW.job_id
    ) >= 500 THEN
        RAISE EXCEPTION 'Question generation supports at most 500 Fact inputs per job'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM knowledge_fact_candidates AS fact
        WHERE fact.id = NEW.fact_candidate_id
          AND fact.project_id = NEW.project_id
          AND fact.pipeline_run_id = NEW.pipeline_run_id
          AND fact.source_id = NEW.source_id
          AND fact.document_id = NEW.document_id
          AND fact.chunk_id = NEW.chunk_id
          AND fact.rag_revision_id IS NOT DISTINCT FROM NEW.rag_revision_id
          AND fact.statement = NEW.statement_snapshot
          AND fact.statement_hash = NEW.statement_hash
          AND fact.source_locator IS NOT DISTINCT FROM NEW.source_locator
          AND fact.extractor_release = NEW.extractor_release
          AND fact.status = 'approved' AND fact.lifecycle_status = 'active'
    ) THEN
        RAISE EXCEPTION 'Question generation Fact input is not an active approved exact snapshot'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_question_entity_input() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (
        SELECT count(*) FROM knowledge_question_generation_entity_inputs AS input
        WHERE input.job_id = NEW.job_id
    ) >= 500 THEN
        RAISE EXCEPTION 'Question generation supports at most 500 Entity inputs per job'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM knowledge_graph_entities AS graph
        WHERE graph.id = NEW.graph_entity_id
          AND graph.project_id = NEW.project_id
          AND graph.entity_type = NEW.entity_type_snapshot
          AND graph.canonical_name = NEW.canonical_name_snapshot
          AND graph.name_hash = NEW.name_hash
          AND graph.status = 'current'
          AND EXISTS (
              SELECT 1 FROM knowledge_graph_entity_sources AS source
              WHERE source.graph_entity_id = graph.id
                AND source.project_id = graph.project_id
                AND source.lifecycle_status = 'active'
          )
    ) THEN
        RAISE EXCEPTION 'Question generation Entity input is not a current sourced graph snapshot'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_question_generation_inputs() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_job_id uuid;
    dimension_total integer;
    fact_total integer;
    entity_total integer;
BEGIN
    target_job_id := (to_jsonb(NEW) ->> 'job_id')::uuid;
    IF NOT EXISTS (
        SELECT 1 FROM knowledge_question_generation_specs AS spec
        WHERE spec.job_id = target_job_id
    ) THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO dimension_total
    FROM knowledge_question_dimensions WHERE job_id = target_job_id;
    SELECT count(*) INTO fact_total
    FROM knowledge_question_generation_fact_inputs WHERE job_id = target_job_id;
    SELECT count(*) INTO entity_total
    FROM knowledge_question_generation_entity_inputs WHERE job_id = target_job_id;
    IF dimension_total NOT BETWEEN 1 AND 200
       OR fact_total NOT BETWEEN 1 AND 500
       OR entity_total NOT BETWEEN 0 AND 500 THEN
        RAISE EXCEPTION 'Question generation requires 1-200 dimensions, 1-500 Facts and at most 500 Entities'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_protect_question_candidate() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    duplicate_threshold numeric(5,4);
    dimension_turn integer;
    parent_dimension text;
    nearest_normalized_text_hash text;
    parent_turn integer;
    parent_dimension_key text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Question candidates cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF to_jsonb(NEW) - ARRAY[
            'workflow_status', 'reviewed_by', 'review_notes', 'reviewed_at', 'updated_at'
        ] IS DISTINCT FROM to_jsonb(OLD) - ARRAY[
            'workflow_status', 'reviewed_by', 'review_notes', 'reviewed_at', 'updated_at'
        ] THEN
            RAISE EXCEPTION 'Question candidate identity and dedup evidence are immutable'
                USING ERRCODE = '55000';
        END IF;
        IF OLD.workflow_status IS DISTINCT FROM NEW.workflow_status THEN
            IF OLD.workflow_status <> 'pending_review'
               OR NEW.workflow_status NOT IN ('approved', 'rejected')
               OR (NEW.workflow_status = 'approved'
                   AND NEW.dedup_status = 'exact_duplicate')
               OR (NEW.workflow_status = 'approved'
                   AND NEW.dedup_status = 'possible_duplicate'
                   AND btrim(COALESCE(NEW.review_notes, '')) = '') THEN
                RAISE EXCEPTION 'invalid Question candidate review transition'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF (NEW.reviewed_by, NEW.review_notes, NEW.reviewed_at)
              IS DISTINCT FROM (OLD.reviewed_by, OLD.review_notes, OLD.reviewed_at) THEN
            RAISE EXCEPTION 'Question candidate review metadata is immutable after decision'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;

    SELECT spec.semantic_duplicate_threshold, dimension.turn_index,
           dimension.parent_dimension_key
    INTO duplicate_threshold, dimension_turn, parent_dimension
    FROM knowledge_question_generation_specs AS spec
    JOIN knowledge_question_dimensions AS dimension
      ON dimension.job_id = spec.job_id
     AND dimension.project_id = spec.project_id
     AND dimension.campaign_id = spec.campaign_id
    WHERE spec.job_id = NEW.generated_by_job_id
      AND spec.project_id = NEW.project_id
      AND spec.campaign_id = NEW.campaign_id
      AND dimension.dimension_key = NEW.dimension_key
      AND spec.embedding_model_key = NEW.embedding_model_key;
    IF duplicate_threshold IS NULL OR dimension_turn <> NEW.turn_index
       OR NEW.query_text_hash <> encode(
            digest(convert_to(NEW.query_text, 'UTF8'), 'sha256'), 'hex'
       ) THEN
        RAISE EXCEPTION 'Question candidate differs from its generation dimension or text hash'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.parent_candidate_id IS NOT NULL THEN
        SELECT candidate.turn_index, candidate.dimension_key
        INTO parent_turn, parent_dimension_key
        FROM knowledge_question_candidates AS candidate
        WHERE candidate.id = NEW.parent_candidate_id
          AND candidate.generated_by_job_id = NEW.generated_by_job_id
          AND candidate.project_id = NEW.project_id
          AND candidate.campaign_id = NEW.campaign_id;
        IF NOT FOUND OR parent_turn >= NEW.turn_index
           OR parent_dimension_key IS DISTINCT FROM parent_dimension THEN
            RAISE EXCEPTION 'multi-turn Question candidate parent is outside its dimension chain'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.nearest_candidate_id IS NOT NULL THEN
        SELECT candidate.normalized_text_hash
        INTO nearest_normalized_text_hash
        FROM knowledge_question_candidates AS candidate
        WHERE candidate.id = NEW.nearest_candidate_id
          AND candidate.generated_by_job_id = NEW.generated_by_job_id
          AND candidate.project_id = NEW.project_id
          AND candidate.campaign_id = NEW.campaign_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'nearest Question candidate is outside the generation job'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF (NEW.dedup_status = 'unique' AND NEW.nearest_similarity IS NOT NULL
            AND NEW.nearest_similarity >= duplicate_threshold)
       OR (NEW.dedup_status = 'possible_duplicate' AND (
            NEW.nearest_similarity IS NULL
            OR NEW.nearest_similarity < duplicate_threshold
       ))
       OR (NEW.dedup_status = 'exact_duplicate' AND (
            NEW.nearest_candidate_id IS NULL
            OR
            NEW.nearest_similarity IS DISTINCT FROM 1.0000
            OR nearest_normalized_text_hash IS DISTINCT FROM NEW.normalized_text_hash
       )) THEN
        RAISE EXCEPTION 'Question candidate dedup result differs from its frozen threshold'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_question_candidate_fact_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_candidate_id uuid;
BEGIN
    target_candidate_id := COALESCE(
        (to_jsonb(NEW) ->> 'candidate_id')::uuid,
        (to_jsonb(NEW) ->> 'id')::uuid
    );
    IF EXISTS (
        SELECT 1 FROM knowledge_question_candidates AS candidate
        WHERE candidate.id = target_candidate_id
    ) AND NOT EXISTS (
        SELECT 1 FROM knowledge_question_candidate_fact_sources AS source
        WHERE source.candidate_id = target_candidate_id
    ) THEN
        RAISE EXCEPTION 'Question candidate requires at least one frozen Fact source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_question_generation_result_counts() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_job_id uuid;
    result_record record;
    actual_dimension_count integer;
    actual_candidate_count integer;
    actual_supported_count integer;
    actual_duplicate_count integer;
BEGIN
    target_job_id := COALESCE(
        (to_jsonb(NEW) ->> 'job_id')::uuid,
        (to_jsonb(NEW) ->> 'generated_by_job_id')::uuid
    );
    SELECT * INTO result_record
    FROM knowledge_question_generation_results WHERE job_id = target_job_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO actual_dimension_count
    FROM knowledge_question_dimensions WHERE job_id = target_job_id;
    SELECT count(*) INTO actual_candidate_count
    FROM knowledge_question_candidates WHERE generated_by_job_id = target_job_id;
    SELECT count(DISTINCT candidate.dimension_key) INTO actual_supported_count
    FROM knowledge_question_candidates AS candidate
    WHERE candidate.generated_by_job_id = target_job_id
      AND EXISTS (
          SELECT 1 FROM knowledge_question_candidate_fact_sources AS source
          WHERE source.candidate_id = candidate.id
      );
    SELECT count(*) INTO actual_duplicate_count
    FROM knowledge_question_candidates
    WHERE generated_by_job_id = target_job_id
      AND dedup_status = 'possible_duplicate';
    IF result_record.dimension_count <> actual_dimension_count
       OR result_record.candidate_count <> actual_candidate_count
       OR result_record.supported_dimension_count <> actual_supported_count
       OR result_record.possible_duplicate_count <> actual_duplicate_count THEN
        RAISE EXCEPTION 'Question generation result counts differ from persisted candidates'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER knowledge_question_dimensions_insert_guard
BEFORE INSERT ON knowledge_question_dimensions
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_dimension();
CREATE TRIGGER knowledge_question_dimensions_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_dimensions
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER knowledge_question_fact_inputs_insert_guard
BEFORE INSERT ON knowledge_question_generation_fact_inputs
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_fact_input();
CREATE TRIGGER knowledge_question_fact_inputs_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_generation_fact_inputs
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER knowledge_question_entity_inputs_insert_guard
BEFORE INSERT ON knowledge_question_generation_entity_inputs
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_entity_input();
CREATE TRIGGER knowledge_question_entity_inputs_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_generation_entity_inputs
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER knowledge_question_results_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_generation_results
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER knowledge_question_candidates_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_question_candidates
FOR EACH ROW EXECUTE FUNCTION geo_protect_question_candidate();
CREATE TRIGGER knowledge_question_candidate_fact_sources_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_candidate_fact_sources
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER knowledge_question_candidate_entity_sources_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_candidate_entity_sources
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE CONSTRAINT TRIGGER knowledge_question_specs_input_inventory_check
AFTER INSERT ON knowledge_question_generation_specs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_generation_inputs();
CREATE CONSTRAINT TRIGGER knowledge_question_dimensions_input_inventory_check
AFTER INSERT ON knowledge_question_dimensions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_generation_inputs();
CREATE CONSTRAINT TRIGGER knowledge_question_facts_input_inventory_check
AFTER INSERT ON knowledge_question_generation_fact_inputs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_generation_inputs();
CREATE CONSTRAINT TRIGGER knowledge_question_entities_input_inventory_check
AFTER INSERT ON knowledge_question_generation_entity_inputs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_generation_inputs();
CREATE CONSTRAINT TRIGGER knowledge_question_candidates_fact_source_check
AFTER INSERT ON knowledge_question_candidates
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_candidate_fact_source();
CREATE CONSTRAINT TRIGGER knowledge_question_fact_sources_candidate_check
AFTER INSERT ON knowledge_question_candidate_fact_sources
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_candidate_fact_source();
CREATE CONSTRAINT TRIGGER knowledge_question_results_count_check
AFTER INSERT ON knowledge_question_generation_results
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_generation_result_counts();
CREATE CONSTRAINT TRIGGER knowledge_question_candidates_result_count_check
AFTER INSERT ON knowledge_question_candidates
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_generation_result_counts();
CREATE CONSTRAINT TRIGGER knowledge_question_fact_sources_result_count_check
AFTER INSERT ON knowledge_question_candidate_fact_sources
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_generation_result_counts();

CREATE FUNCTION geo_question_candidate_source_lineage_hash(target_candidate_id uuid)
RETURNS text
LANGUAGE sql STABLE AS $$
    WITH source_lines AS (
        SELECT 'fact:' || input.fact_candidate_id::text || ':'
            || input.statement_hash || ':' || input.extractor_release || ':'
            || COALESCE(input.source_locator, '') AS value
        FROM knowledge_question_candidate_fact_sources AS source
        JOIN knowledge_question_generation_fact_inputs AS input
          ON input.job_id = source.generated_by_job_id
         AND input.project_id = source.project_id
         AND input.campaign_id = source.campaign_id
         AND input.fact_candidate_id = source.fact_candidate_id
        WHERE source.candidate_id = target_candidate_id
        UNION ALL
        SELECT 'entity:' || input.graph_entity_id::text || ':' || input.name_hash
        FROM knowledge_question_candidate_entity_sources AS source
        JOIN knowledge_question_generation_entity_inputs AS input
          ON input.job_id = source.generated_by_job_id
         AND input.project_id = source.project_id
         AND input.campaign_id = source.campaign_id
         AND input.graph_entity_id = source.graph_entity_id
        WHERE source.candidate_id = target_candidate_id
    )
    SELECT encode(
        digest(
            convert_to(
                'geo-question-source-lineage-v1' || E'\n'
                || COALESCE(string_agg(value || E'\n', '' ORDER BY value), ''),
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
    FROM source_lines
$$;

CREATE FUNCTION geo_question_candidate_sources_current(target_candidate_id uuid)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT
        EXISTS (
            SELECT 1 FROM knowledge_question_candidate_fact_sources AS source
            WHERE source.candidate_id = target_candidate_id
        )
        AND NOT EXISTS (
            SELECT 1
            FROM knowledge_question_candidate_fact_sources AS source
            JOIN knowledge_question_generation_fact_inputs AS input
              ON input.job_id = source.generated_by_job_id
             AND input.project_id = source.project_id
             AND input.campaign_id = source.campaign_id
             AND input.fact_candidate_id = source.fact_candidate_id
            LEFT JOIN knowledge_fact_candidates AS fact
              ON fact.id = input.fact_candidate_id
             AND fact.project_id = input.project_id
             AND fact.pipeline_run_id = input.pipeline_run_id
             AND fact.source_id = input.source_id
             AND fact.document_id = input.document_id
             AND fact.chunk_id = input.chunk_id
            WHERE source.candidate_id = target_candidate_id
              AND (
                  fact.id IS NULL OR fact.status <> 'approved'
                  OR fact.lifecycle_status <> 'active'
                  OR fact.rag_revision_id IS DISTINCT FROM input.rag_revision_id
                  OR fact.statement IS DISTINCT FROM input.statement_snapshot
                  OR fact.statement_hash IS DISTINCT FROM input.statement_hash
                  OR fact.source_locator IS DISTINCT FROM input.source_locator
                  OR fact.extractor_release IS DISTINCT FROM input.extractor_release
              )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM knowledge_question_candidate_entity_sources AS source
            JOIN knowledge_question_generation_entity_inputs AS input
              ON input.job_id = source.generated_by_job_id
             AND input.project_id = source.project_id
             AND input.campaign_id = source.campaign_id
             AND input.graph_entity_id = source.graph_entity_id
            LEFT JOIN knowledge_graph_entities AS graph
              ON graph.id = input.graph_entity_id
             AND graph.project_id = input.project_id
            WHERE source.candidate_id = target_candidate_id
              AND (
                  graph.id IS NULL OR graph.status <> 'current'
                  OR graph.entity_type IS DISTINCT FROM input.entity_type_snapshot
                  OR graph.canonical_name IS DISTINCT FROM input.canonical_name_snapshot
                  OR graph.name_hash IS DISTINCT FROM input.name_hash
                  OR NOT EXISTS (
                      SELECT 1 FROM knowledge_graph_entity_sources AS lineage
                      WHERE lineage.graph_entity_id = graph.id
                        AND lineage.project_id = graph.project_id
                        AND lineage.lifecycle_status = 'active'
                  )
              )
        )
$$;

CREATE FUNCTION geo_question_set_content_hash(target_set_id uuid) RETURNS text
LANGUAGE sql STABLE AS $$
    WITH header AS (
        SELECT question_set.id, question_set.project_id, question_set.campaign_id,
               question_set.series_id, question_set.previous_version_id,
               question_set.version_number, question_set.generated_by_job_id,
               question_set.name, question_set.dimension_count,
               question_set.covered_dimension_count,
               question_set.possible_duplicate_count,
               question_set.coverage_ratio, question_set.duplicate_ratio,
               job.input_hash
        FROM knowledge_question_sets AS question_set
        JOIN durable_jobs AS job
          ON job.id = question_set.generated_by_job_id
         AND job.project_id = question_set.project_id
         AND job.campaign_id = question_set.campaign_id
        WHERE question_set.id = target_set_id
    ), item_lines AS (
        SELECT item.ordinal, item.ordinal::text || ':' || item.id::text || ':'
            || item.question_candidate_id::text || ':' || item.dimension_key || ':'
            || item.query_text_hash || ':' || item.normalized_text_hash || ':'
            || item.query_kind_snapshot || ':' || item.query_cluster_key || ':'
            || item.source_lineage_hash AS value
        FROM knowledge_question_set_items AS item
        WHERE item.question_set_id = target_set_id
    )
    SELECT encode(
        digest(
            convert_to(
                'geo-question-set-v1' || E'\n'
                || header.id::text || ':' || header.project_id::text || ':'
                || header.campaign_id::text || ':' || header.series_id::text || ':'
                || COALESCE(header.previous_version_id::text, '') || ':'
                || header.version_number::text || ':'
                || header.generated_by_job_id::text || ':' || header.name || ':'
                || header.dimension_count::text || ':'
                || header.covered_dimension_count::text || ':'
                || header.possible_duplicate_count::text || ':'
                || header.coverage_ratio::text || ':'
                || header.duplicate_ratio::text || ':' || header.input_hash || E'\n'
                || COALESCE(
                    (SELECT string_agg(value || E'\n', '' ORDER BY ordinal) FROM item_lines),
                    ''
                ),
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
    FROM header
$$;

CREATE FUNCTION geo_assert_question_set_item() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM knowledge_question_sets AS question_set
        JOIN knowledge_question_candidates AS candidate
          ON candidate.id = NEW.question_candidate_id
         AND candidate.generated_by_job_id = NEW.generated_by_job_id
         AND candidate.project_id = NEW.project_id
         AND candidate.campaign_id = NEW.campaign_id
        JOIN knowledge_question_dimensions AS dimension
          ON dimension.job_id = candidate.generated_by_job_id
         AND dimension.project_id = candidate.project_id
         AND dimension.campaign_id = candidate.campaign_id
         AND dimension.dimension_key = candidate.dimension_key
        WHERE question_set.id = NEW.question_set_id
          AND question_set.project_id = NEW.project_id
          AND question_set.campaign_id = NEW.campaign_id
          AND question_set.generated_by_job_id = NEW.generated_by_job_id
          AND question_set.status = 'draft'
          AND candidate.workflow_status = 'approved'
          AND candidate.dimension_key = NEW.dimension_key
          AND candidate.query_text = NEW.query_text_snapshot
          AND candidate.query_text_hash = NEW.query_text_hash
          AND candidate.normalized_text_hash = NEW.normalized_text_hash
          AND dimension.query_kind = NEW.query_kind_snapshot
          AND geo_question_candidate_source_lineage_hash(candidate.id)
                = NEW.source_lineage_hash
          AND geo_question_candidate_sources_current(candidate.id)
    ) THEN
        RAISE EXCEPTION 'QuestionSet item differs from its approved sourced candidate snapshot'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_question_set_inventory() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_set_id uuid;
    question_set_record record;
    item_total integer;
    actual_dimension_count integer;
    actual_covered_count integer;
    actual_duplicate_count integer;
BEGIN
    target_set_id := COALESCE(
        (to_jsonb(NEW) ->> 'question_set_id')::uuid,
        (to_jsonb(NEW) ->> 'id')::uuid
    );
    SELECT * INTO question_set_record
    FROM knowledge_question_sets WHERE id = target_set_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO actual_dimension_count
    FROM knowledge_question_dimensions
    WHERE job_id = question_set_record.generated_by_job_id;
    SELECT count(*), count(DISTINCT item.dimension_key),
           count(*) FILTER (WHERE candidate.dedup_status = 'possible_duplicate')
    INTO item_total, actual_covered_count, actual_duplicate_count
    FROM knowledge_question_set_items AS item
    JOIN knowledge_question_candidates AS candidate
      ON candidate.id = item.question_candidate_id
    WHERE item.question_set_id = target_set_id;
    IF item_total = 0 OR actual_dimension_count = 0
       OR question_set_record.dimension_count <> actual_dimension_count
       OR question_set_record.covered_dimension_count <> actual_covered_count
       OR question_set_record.possible_duplicate_count <> actual_duplicate_count
       OR question_set_record.coverage_ratio <> round(
            actual_covered_count::numeric / actual_dimension_count, 4
       )
       OR question_set_record.duplicate_ratio <> round(
            actual_duplicate_count::numeric / item_total, 4
       ) THEN
        RAISE EXCEPTION 'QuestionSet measurements differ from immutable item inventory'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_protect_question_set() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous_record record;
    item_total integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'new QuestionSet version must start as draft'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.previous_version_id IS NOT NULL THEN
            SELECT version_number, status INTO previous_record
            FROM knowledge_question_sets
            WHERE id = NEW.previous_version_id
              AND project_id = NEW.project_id
              AND campaign_id = NEW.campaign_id
              AND series_id = NEW.series_id;
            IF NOT FOUND OR previous_record.status <> 'frozen'
               OR NEW.version_number <> previous_record.version_number + 1 THEN
                RAISE EXCEPTION 'QuestionSet version must follow its frozen exact predecessor'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'QuestionSet versions cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF to_jsonb(NEW) - ARRAY[
        'status', 'approved_by', 'approved_at', 'frozen_by', 'frozen_at', 'content_hash'
    ] IS DISTINCT FROM to_jsonb(OLD) - ARRAY[
        'status', 'approved_by', 'approved_at', 'frozen_by', 'frozen_at', 'content_hash'
    ] THEN
        RAISE EXCEPTION 'QuestionSet identity and measurements are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NOT (
        (OLD.status = 'draft' AND NEW.status = 'approved')
        OR (OLD.status = 'approved' AND NEW.status = 'frozen')
    ) THEN
        RAISE EXCEPTION 'invalid QuestionSet state transition'
            USING ERRCODE = '23514';
    END IF;
    SELECT count(*) INTO item_total
    FROM knowledge_question_set_items AS item
    JOIN knowledge_question_candidates AS candidate
      ON candidate.id = item.question_candidate_id
    WHERE item.question_set_id = NEW.id
      AND candidate.workflow_status = 'approved'
      AND geo_question_candidate_sources_current(candidate.id);
    IF item_total = 0 OR item_total <> (
        SELECT count(*) FROM knowledge_question_set_items
        WHERE question_set_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'QuestionSet state requires all candidate sources to remain approved and current'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'frozen' AND (
        NEW.coverage_ratio < 0.9000 OR NEW.duplicate_ratio > 0.1000
        OR EXISTS (
            SELECT 1
            FROM knowledge_question_set_items AS item
            JOIN knowledge_question_candidates AS candidate
              ON candidate.id = item.question_candidate_id
            WHERE item.question_set_id = NEW.id
              AND candidate.dedup_status = 'exact_duplicate'
        )
        OR NEW.content_hash IS DISTINCT FROM geo_question_set_content_hash(NEW.id)
    ) THEN
        RAISE EXCEPTION 'QuestionSet freeze coverage, duplicate, or content hash gate failed'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER knowledge_question_sets_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_question_sets
FOR EACH ROW EXECUTE FUNCTION geo_protect_question_set();
CREATE TRIGGER knowledge_question_set_items_insert_guard
BEFORE INSERT ON knowledge_question_set_items
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_set_item();
CREATE TRIGGER knowledge_question_set_items_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_set_items
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE CONSTRAINT TRIGGER knowledge_question_sets_inventory_check
AFTER INSERT ON knowledge_question_sets
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_set_inventory();
CREATE CONSTRAINT TRIGGER knowledge_question_set_items_inventory_check
AFTER INSERT ON knowledge_question_set_items
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_question_set_inventory();

CREATE OR REPLACE FUNCTION geo_protect_monitoring_protocol() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'monitoring protocols cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'frozen' THEN
        RAISE EXCEPTION 'frozen monitoring protocols are immutable' USING ERRCODE = '55000';
    END IF;
    IF OLD.question_set_id IS NOT NULL AND (
        NEW.question_set_id, NEW.question_set_hash,
        NEW.question_set_bound_by, NEW.question_set_bound_at
    ) IS DISTINCT FROM (
        OLD.question_set_id, OLD.question_set_hash,
        OLD.question_set_bound_by, OLD.question_set_bound_at
    ) THEN
        RAISE EXCEPTION 'Monitoring Protocol QuestionSet binding is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.question_set_id IS NULL AND NEW.question_set_id IS NOT NULL THEN
        IF OLD.status <> 'draft' OR NEW.status <> 'draft'
           OR NOT EXISTS (
               SELECT 1 FROM knowledge_question_sets AS question_set
               WHERE question_set.id = NEW.question_set_id
                 AND question_set.project_id = NEW.project_id
                 AND question_set.campaign_id = NEW.campaign_id
                 AND question_set.content_hash = NEW.question_set_hash
                 AND question_set.status = 'frozen'
           ) THEN
            RAISE EXCEPTION 'draft Protocol may bind only one frozen exact QuestionSet'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NOT ((OLD.status = 'draft' AND NEW.status IN ('draft', 'approved'))
            OR (OLD.status = 'approved' AND NEW.status IN ('approved', 'frozen'))) THEN
        RAISE EXCEPTION 'invalid monitoring protocol transition' USING ERRCODE = '23514';
    END IF;
    IF NEW.status IN ('approved', 'frozen') AND NOT EXISTS (
        SELECT 1 FROM monitoring_protocol_queries AS query
        WHERE query.protocol_id = NEW.id AND query.project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'approved monitoring protocols require an approved query'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status IN ('approved', 'frozen') AND NEW.question_set_id IS NOT NULL
       AND NOT geo_protocol_question_inventory_complete(NEW.id) THEN
        RAISE EXCEPTION 'bound Protocol QuestionSet inventory is incomplete'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_protocol_question_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    protocol_record record;
    item_record record;
    item_id uuid;
    candidate_id uuid;
BEGIN
    item_id := (to_jsonb(NEW) ->> 'question_set_item_id')::uuid;
    candidate_id := (to_jsonb(NEW) ->> 'question_candidate_id')::uuid;
    SELECT protocol.question_set_id, protocol.project_id, protocol.campaign_id,
           protocol.locale
    INTO protocol_record
    FROM monitoring_protocols AS protocol
    WHERE protocol.id = NEW.protocol_id AND protocol.project_id = NEW.project_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
    IF protocol_record.question_set_id IS NULL THEN
        IF item_id IS NOT NULL OR candidate_id IS NOT NULL THEN
            RAISE EXCEPTION 'manual Protocol cannot claim QuestionSet item lineage'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT item.query_text_snapshot, item.query_kind_snapshot,
           item.query_cluster_key, item.question_candidate_id
    INTO item_record
    FROM knowledge_question_set_items AS item
    WHERE item.id = item_id
      AND item.question_candidate_id = candidate_id
      AND item.question_set_id = protocol_record.question_set_id
      AND item.project_id = protocol_record.project_id
      AND item.campaign_id = protocol_record.campaign_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'bound Protocol query is outside its frozen QuestionSet'
            USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'monitoring_query_suggestions' THEN
        IF NEW.query_text IS DISTINCT FROM item_record.query_text_snapshot
           OR NEW.query_kind IS DISTINCT FROM item_record.query_kind_snapshot
           OR NEW.query_cluster_key IS DISTINCT FROM item_record.query_cluster_key THEN
            RAISE EXCEPTION 'Protocol suggestion snapshot differs from QuestionSet item'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.query_text_snapshot IS DISTINCT FROM item_record.query_text_snapshot
           OR NEW.query_kind_snapshot IS DISTINCT FROM item_record.query_kind_snapshot
           OR NEW.query_cluster_key IS DISTINCT FROM item_record.query_cluster_key
           OR NEW.locale_snapshot IS DISTINCT FROM protocol_record.locale THEN
            RAISE EXCEPTION 'Protocol query snapshot differs from QuestionSet item'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_protocol_question_inventory_complete(target_protocol_id uuid)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT protocol.question_set_id IS NULL OR (
        (SELECT count(*) FROM knowledge_question_set_items AS item
         WHERE item.question_set_id = protocol.question_set_id)
        =
        (SELECT count(*) FROM monitoring_query_suggestions AS suggestion
         WHERE suggestion.protocol_id = protocol.id
           AND suggestion.project_id = protocol.project_id
           AND suggestion.question_set_item_id IS NOT NULL
           AND suggestion.status = 'approved')
        AND
        (SELECT count(*) FROM knowledge_question_set_items AS item
         WHERE item.question_set_id = protocol.question_set_id)
        =
        (SELECT count(*) FROM monitoring_protocol_queries AS query
         WHERE query.protocol_id = protocol.id
           AND query.project_id = protocol.project_id
           AND query.question_set_item_id IS NOT NULL)
        AND NOT EXISTS (
            SELECT 1
            FROM knowledge_question_set_items AS item
            WHERE item.question_set_id = protocol.question_set_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM monitoring_query_suggestions AS suggestion
                  JOIN monitoring_protocol_queries AS query
                    ON query.protocol_id = suggestion.protocol_id
                   AND query.project_id = suggestion.project_id
                   AND query.suggestion_id = suggestion.id
                   AND query.question_set_item_id = suggestion.question_set_item_id
                   AND query.question_candidate_id = suggestion.question_candidate_id
                  WHERE suggestion.protocol_id = protocol.id
                    AND suggestion.project_id = protocol.project_id
                    AND suggestion.question_set_item_id = item.id
                    AND suggestion.question_candidate_id = item.question_candidate_id
                    AND suggestion.status = 'approved'
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM monitoring_query_suggestions AS suggestion
            WHERE suggestion.protocol_id = protocol.id
              AND suggestion.project_id = protocol.project_id
              AND suggestion.question_set_item_id IS NULL
        )
        AND NOT EXISTS (
            SELECT 1 FROM monitoring_protocol_queries AS query
            WHERE query.protocol_id = protocol.id
              AND query.project_id = protocol.project_id
              AND query.question_set_item_id IS NULL
        )
    )
    FROM monitoring_protocols AS protocol
    WHERE protocol.id = target_protocol_id
$$;

CREATE FUNCTION geo_assert_protocol_question_inventory() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_protocol_id uuid;
BEGIN
    target_protocol_id := (to_jsonb(NEW) ->> 'protocol_id')::uuid;
    IF target_protocol_id IS NULL AND TG_TABLE_NAME = 'monitoring_protocols' THEN
        target_protocol_id := NEW.id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM monitoring_protocols AS protocol
        WHERE protocol.id = target_protocol_id
          AND protocol.question_set_id IS NOT NULL
    ) AND NOT geo_protocol_question_inventory_complete(target_protocol_id) THEN
        RAISE EXCEPTION 'bound Protocol inventory must equal its QuestionSet items'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_protect_protocol_question_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.question_set_item_id, NEW.question_candidate_id)
       IS DISTINCT FROM (OLD.question_set_item_id, OLD.question_candidate_id) THEN
        RAISE EXCEPTION 'Protocol QuestionSet lineage is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER monitoring_suggestions_question_lineage_guard
BEFORE INSERT ON monitoring_query_suggestions
FOR EACH ROW EXECUTE FUNCTION geo_assert_protocol_question_lineage();
CREATE TRIGGER monitoring_protocol_queries_question_lineage_guard
BEFORE INSERT ON monitoring_protocol_queries
FOR EACH ROW EXECUTE FUNCTION geo_assert_protocol_question_lineage();
CREATE TRIGGER monitoring_suggestions_question_lineage_immutable
BEFORE UPDATE OF question_set_item_id, question_candidate_id
ON monitoring_query_suggestions
FOR EACH ROW EXECUTE FUNCTION geo_protect_protocol_question_lineage();
CREATE TRIGGER monitoring_protocol_queries_question_lineage_immutable
BEFORE UPDATE OF question_set_item_id, question_candidate_id
ON monitoring_protocol_queries
FOR EACH ROW EXECUTE FUNCTION geo_protect_protocol_question_lineage();
CREATE CONSTRAINT TRIGGER monitoring_protocol_question_inventory_check
AFTER INSERT OR UPDATE ON monitoring_protocols
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_protocol_question_inventory();
CREATE CONSTRAINT TRIGGER monitoring_suggestion_question_inventory_check
AFTER INSERT OR UPDATE ON monitoring_query_suggestions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_protocol_question_inventory();
CREATE CONSTRAINT TRIGGER monitoring_protocol_query_question_inventory_check
AFTER INSERT OR UPDATE ON monitoring_protocol_queries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_protocol_question_inventory();

CREATE OR REPLACE FUNCTION geo_assert_prompt_simulation_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM product_entities AS entity
        WHERE entity.id = NEW.primary_brand_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'brand' AND entity.status = 'active'
    ) OR NOT EXISTS (
        SELECT 1 FROM product_entities AS entity
        WHERE entity.id = NEW.product_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'product' AND entity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'prompt simulation subjects must be active brand and product entities'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.destination_policy_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM destination_policy_versions AS policy
        WHERE policy.id = NEW.destination_policy_version_id
          AND policy.project_id = NEW.project_id
          AND policy.destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'prompt simulation policy does not belong to its destination'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.binding_contract_version <> 'opportunity-binding-v2' THEN
        RAISE EXCEPTION 'new prompt simulations require an Opportunity binding'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM current_opportunity_prompt_release_bindings AS binding
        JOIN current_generation_template_release_states AS state
          ON state.template_release_id = binding.template_release_id
         AND state.project_id = binding.project_id
        WHERE binding.id = NEW.binding_id AND binding.project_id = NEW.project_id
          AND binding.campaign_id = NEW.campaign_id
          AND binding.opportunity_id = NEW.opportunity_id
          AND binding.destination_id = NEW.destination_id
          AND binding.binding_version = NEW.binding_version
          AND binding.binding_state = 'bound'
          AND binding.template_release_id = NEW.template_release_id
          AND binding.skill_version_id = NEW.template_skill_version_id
          AND binding.release_number = NEW.template_release_number
          AND binding.release_hash = NEW.template_release_hash
          AND state.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'prompt simulation binding is stale, unbound, or not approved'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.simulation_purpose = 'geo_question_test' THEN
        IF NOT EXISTS (
            SELECT 1
            FROM knowledge_question_sets AS question_set
            JOIN knowledge_question_set_items AS item
              ON item.question_set_id = question_set.id
             AND item.project_id = question_set.project_id
             AND item.campaign_id = question_set.campaign_id
            JOIN knowledge_question_candidates AS candidate
              ON candidate.id = item.question_candidate_id
             AND candidate.project_id = item.project_id
             AND candidate.campaign_id = item.campaign_id
            WHERE question_set.id = NEW.question_set_id
              AND question_set.project_id = NEW.project_id
              AND question_set.campaign_id = NEW.campaign_id
              AND question_set.content_hash = NEW.question_set_hash
              AND question_set.status = 'frozen'
              AND item.id = NEW.question_set_item_id
              AND item.question_candidate_id = NEW.question_candidate_id
              AND candidate.workflow_status = 'approved'
              AND geo_question_candidate_sources_current(candidate.id)
              AND NEW.input_snapshot -> 'question_binding' IS NOT NULL
              AND NEW.input_snapshot -> 'question_binding' ->> 'question_set_id'
                    = question_set.id::text
              AND NEW.input_snapshot -> 'question_binding' ->> 'question_set_hash'
                    = question_set.content_hash
              AND NEW.input_snapshot -> 'question_binding' ->> 'item_id' = item.id::text
              AND NEW.input_snapshot -> 'question_binding' ->> 'candidate_id'
                    = candidate.id::text
              AND NEW.input_snapshot -> 'question_binding' ->> 'question_text'
                    = item.query_text_snapshot
              AND NEW.input_snapshot -> 'question_binding' ->> 'dimension_key'
                    = item.dimension_key
              AND jsonb_typeof(
                    NEW.input_snapshot -> 'question_binding' -> 'source_fact_ids'
                  ) = 'array'
              AND ARRAY(
                    SELECT value::uuid
                    FROM jsonb_array_elements_text(
                        NEW.input_snapshot -> 'question_binding' -> 'source_fact_ids'
                    )
                    ORDER BY value::uuid
                  ) = ARRAY(
                    SELECT source.fact_candidate_id
                    FROM knowledge_question_candidate_fact_sources AS source
                    WHERE source.candidate_id = candidate.id
                    ORDER BY source.fact_candidate_id
                  )
              AND jsonb_typeof(
                    NEW.input_snapshot -> 'question_binding' -> 'source_entity_ids'
                  ) = 'array'
              AND ARRAY(
                    SELECT value::uuid
                    FROM jsonb_array_elements_text(
                        NEW.input_snapshot -> 'question_binding' -> 'source_entity_ids'
                    )
                    ORDER BY value::uuid
                  ) = ARRAY(
                    SELECT source.graph_entity_id
                    FROM knowledge_question_candidate_entity_sources AS source
                    WHERE source.candidate_id = candidate.id
                    ORDER BY source.graph_entity_id
                  )
        ) THEN
            RAISE EXCEPTION 'GEO simulation QuestionSet binding is stale or incomplete'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_geo_simulation_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_simulation_id uuid;
    simulation_record record;
BEGIN
    target_simulation_id := COALESCE(
        (to_jsonb(NEW) ->> 'simulation_id')::uuid,
        (to_jsonb(NEW) ->> 'id')::uuid
    );
    SELECT simulation.id, simulation.project_id, simulation.question_candidate_id,
           simulation.simulation_purpose
    INTO simulation_record
    FROM prompt_simulations AS simulation
    WHERE simulation.id = target_simulation_id;
    IF NOT FOUND OR simulation_record.simulation_purpose <> 'geo_question_test' THEN
        RETURN NULL;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM knowledge_question_candidate_fact_sources AS source
        WHERE source.candidate_id = simulation_record.question_candidate_id
          AND NOT EXISTS (
              SELECT 1
              FROM knowledge_fact_evidence_lineages AS lineage
              JOIN prompt_simulation_evidence AS evidence
                ON evidence.evidence_item_id = lineage.evidence_item_id
               AND evidence.project_id = lineage.project_id
               AND evidence.simulation_id = simulation_record.id
              WHERE lineage.knowledge_fact_id = source.fact_candidate_id
                AND lineage.project_id = simulation_record.project_id
          )
    ) THEN
        RAISE EXCEPTION 'GEO simulation requires approved Evidence for every Question Fact source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_new_prompt_simulation_result() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    simulation_record record;
BEGIN
    IF NEW.lineage_contract_version <> 'opportunity-binding-v2'
       AND NOT (
           NEW.lineage_contract_version = 'legacy-v1'
           AND EXISTS (
               SELECT 1
               FROM prompt_simulations AS simulation
               JOIN prompt_simulation_job_specs AS spec
                 ON spec.simulation_id = simulation.id
                AND spec.project_id = simulation.project_id
               WHERE simulation.id = NEW.simulation_id
                 AND simulation.project_id = NEW.project_id
                 AND spec.job_id = NEW.generated_by_job_id
                 AND simulation.binding_contract_version = 'legacy-v1'
                 AND simulation.campaign_id IS NULL
                 AND simulation.opportunity_id IS NULL
                 AND spec.campaign_id IS NULL
                 AND spec.opportunity_id IS NULL
           )
       ) THEN
        RAISE EXCEPTION 'prompt simulation result lineage is not exact'
            USING ERRCODE = '23514';
    END IF;
    SELECT simulation.simulation_purpose, simulation.input_snapshot
    INTO simulation_record
    FROM prompt_simulations AS simulation
    WHERE simulation.id = NEW.simulation_id AND simulation.project_id = NEW.project_id;
    IF simulation_record.simulation_purpose = 'geo_question_test' AND (
        NEW.artifact_manifest -> 'question_binding'
            IS DISTINCT FROM simulation_record.input_snapshot -> 'question_binding'
        OR NEW.artifact_manifest ->> 'test_only' IS DISTINCT FROM 'true'
        OR NEW.artifact_manifest ->> 'publication_eligible' IS DISTINCT FROM 'false'
    ) THEN
        RAISE EXCEPTION 'GEO simulation artifact lost its non-publishable Question binding'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER prompt_simulation_geo_evidence_check
AFTER INSERT ON prompt_simulations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_geo_simulation_evidence();
CREATE CONSTRAINT TRIGGER prompt_simulation_evidence_geo_check
AFTER INSERT ON prompt_simulation_evidence
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_geo_simulation_evidence();

CREATE INDEX knowledge_question_specs_project_idx
ON knowledge_question_generation_specs (project_id, campaign_id, created_at DESC, job_id);
CREATE INDEX knowledge_question_specs_requester_idx
ON knowledge_question_generation_specs (requested_by, created_at DESC);
CREATE INDEX knowledge_question_dimensions_spec_fk_idx
ON knowledge_question_dimensions (job_id, project_id, campaign_id);
CREATE INDEX knowledge_question_dimensions_parent_fk_idx
ON knowledge_question_dimensions (
    job_id, project_id, campaign_id, parent_dimension_key
) WHERE parent_dimension_key IS NOT NULL;
CREATE INDEX knowledge_question_dimensions_competitor_fk_idx
ON knowledge_question_dimensions (competitor_entity_id, project_id)
WHERE competitor_entity_id IS NOT NULL;
CREATE INDEX knowledge_question_fact_inputs_fact_fk_idx
ON knowledge_question_generation_fact_inputs (
    fact_candidate_id, project_id, pipeline_run_id, source_id,
    document_id, chunk_id, statement_hash
);
CREATE INDEX knowledge_question_fact_inputs_chunk_fk_idx
ON knowledge_question_generation_fact_inputs (
    chunk_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_question_fact_inputs_revision_fk_idx
ON knowledge_question_generation_fact_inputs (
    rag_revision_id, project_id, pipeline_run_id, source_id, document_id
) WHERE rag_revision_id IS NOT NULL;
CREATE INDEX knowledge_question_entity_inputs_graph_fk_idx
ON knowledge_question_generation_entity_inputs (graph_entity_id, project_id);
CREATE INDEX knowledge_question_results_spec_fk_idx
ON knowledge_question_generation_results (job_id, project_id, campaign_id);
CREATE INDEX knowledge_question_candidates_review_idx
ON knowledge_question_candidates (
    project_id, campaign_id, workflow_status, created_at, id
);
CREATE INDEX knowledge_question_candidates_spec_fk_idx
ON knowledge_question_candidates (generated_by_job_id, project_id, campaign_id);
CREATE INDEX knowledge_question_candidates_dimension_fk_idx
ON knowledge_question_candidates (
    generated_by_job_id, project_id, campaign_id, dimension_key
);
CREATE INDEX knowledge_question_candidates_parent_fk_idx
ON knowledge_question_candidates (
    parent_candidate_id, generated_by_job_id, project_id, campaign_id
) WHERE parent_candidate_id IS NOT NULL;
CREATE INDEX knowledge_question_candidates_nearest_fk_idx
ON knowledge_question_candidates (
    nearest_candidate_id, generated_by_job_id, project_id, campaign_id
) WHERE nearest_candidate_id IS NOT NULL;
CREATE INDEX knowledge_question_candidates_embedding_hnsw_idx
ON knowledge_question_candidates USING hnsw (embedding vector_cosine_ops);
CREATE INDEX knowledge_question_candidate_fact_sources_candidate_idx
ON knowledge_question_candidate_fact_sources (
    candidate_id, generated_by_job_id, project_id, campaign_id
);
CREATE INDEX knowledge_question_candidate_fact_sources_input_idx
ON knowledge_question_candidate_fact_sources (
    generated_by_job_id, project_id, campaign_id, fact_candidate_id
);
CREATE INDEX knowledge_question_candidate_entity_sources_candidate_idx
ON knowledge_question_candidate_entity_sources (
    candidate_id, generated_by_job_id, project_id, campaign_id
);
CREATE INDEX knowledge_question_candidate_entity_sources_input_idx
ON knowledge_question_candidate_entity_sources (
    generated_by_job_id, project_id, campaign_id, graph_entity_id
);
CREATE INDEX knowledge_question_sets_project_status_idx
ON knowledge_question_sets (
    project_id, campaign_id, status, created_at DESC, id DESC
);
CREATE INDEX knowledge_question_sets_series_idx
ON knowledge_question_sets (series_id, version_number DESC);
CREATE INDEX knowledge_question_sets_job_fk_idx
ON knowledge_question_sets (generated_by_job_id, project_id, campaign_id);
CREATE INDEX knowledge_question_sets_previous_fk_idx
ON knowledge_question_sets (
    previous_version_id, project_id, campaign_id, series_id
) WHERE previous_version_id IS NOT NULL;
CREATE INDEX knowledge_question_set_items_set_idx
ON knowledge_question_set_items (question_set_id, project_id, campaign_id, ordinal);
CREATE INDEX knowledge_question_set_items_candidate_fk_idx
ON knowledge_question_set_items (
    question_candidate_id, generated_by_job_id, project_id, campaign_id
);
CREATE INDEX monitoring_protocols_question_set_fk_idx
ON monitoring_protocols (
    question_set_id, campaign_id, project_id, question_set_hash
) WHERE question_set_id IS NOT NULL;
CREATE INDEX monitoring_suggestions_question_lineage_fk_idx
ON monitoring_query_suggestions (
    question_set_item_id, question_candidate_id, project_id
) WHERE question_set_item_id IS NOT NULL;
CREATE INDEX monitoring_protocol_queries_question_lineage_fk_idx
ON monitoring_protocol_queries (
    question_set_item_id, question_candidate_id, project_id
) WHERE question_set_item_id IS NOT NULL;
CREATE INDEX prompt_simulations_question_set_fk_idx
ON prompt_simulations (
    question_set_id, campaign_id, project_id, question_set_hash
) WHERE question_set_id IS NOT NULL;
CREATE INDEX prompt_simulations_question_item_fk_idx
ON prompt_simulations (
    question_set_item_id, question_candidate_id, project_id, campaign_id
) WHERE question_set_item_id IS NOT NULL;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'knowledge_question_generation_specs', 'knowledge_question_dimensions',
        'knowledge_question_generation_fact_inputs',
        'knowledge_question_generation_entity_inputs',
        'knowledge_question_generation_results', 'knowledge_question_candidates',
        'knowledge_question_candidate_fact_sources',
        'knowledge_question_candidate_entity_sources',
        'knowledge_question_sets', 'knowledge_question_set_items'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

REVOKE ALL ON
    knowledge_question_generation_specs, knowledge_question_dimensions,
    knowledge_question_generation_fact_inputs,
    knowledge_question_generation_entity_inputs,
    knowledge_question_generation_results, knowledge_question_candidates,
    knowledge_question_candidate_fact_sources,
    knowledge_question_candidate_entity_sources,
    knowledge_question_sets, knowledge_question_set_items
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON
    knowledge_question_generation_specs, knowledge_question_dimensions,
    knowledge_question_generation_fact_inputs,
    knowledge_question_generation_entity_inputs,
    knowledge_question_generation_results, knowledge_question_candidates,
    knowledge_question_candidate_fact_sources,
    knowledge_question_candidate_entity_sources,
    knowledge_question_sets, knowledge_question_set_items
TO geo_app, geo_worker, geo_readonly;
GRANT INSERT ON
    knowledge_question_generation_specs, knowledge_question_dimensions,
    knowledge_question_generation_fact_inputs,
    knowledge_question_generation_entity_inputs,
    knowledge_question_sets, knowledge_question_set_items
TO geo_app;
GRANT UPDATE ON knowledge_question_candidates, knowledge_question_sets TO geo_app;
GRANT INSERT ON
    knowledge_question_generation_results, knowledge_question_candidates,
    knowledge_question_candidate_fact_sources,
    knowledge_question_candidate_entity_sources
TO geo_worker;

REVOKE ALL ON FUNCTION
    geo_assert_question_dimension(), geo_assert_question_fact_input(),
    geo_assert_question_entity_input(), geo_assert_question_generation_inputs(),
    geo_protect_question_candidate(), geo_assert_question_candidate_fact_source(),
    geo_assert_question_generation_result_counts(),
    geo_question_candidate_source_lineage_hash(uuid),
    geo_question_candidate_sources_current(uuid),
    geo_question_set_content_hash(uuid), geo_assert_question_set_item(),
    geo_assert_question_set_inventory(), geo_protect_question_set(),
    geo_assert_protocol_question_lineage(),
    geo_protocol_question_inventory_complete(uuid),
    geo_assert_protocol_question_inventory(),
    geo_protect_protocol_question_lineage(), geo_assert_geo_simulation_evidence()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_assert_question_dimension(), geo_assert_question_fact_input(),
    geo_assert_question_entity_input(), geo_assert_question_generation_inputs(),
    geo_protect_question_candidate(), geo_assert_question_candidate_fact_source(),
    geo_assert_question_generation_result_counts(),
    geo_question_candidate_source_lineage_hash(uuid),
    geo_question_candidate_sources_current(uuid),
    geo_question_set_content_hash(uuid), geo_assert_question_set_item(),
    geo_assert_question_set_inventory(), geo_protect_question_set(),
    geo_assert_protocol_question_lineage(),
    geo_protocol_question_inventory_complete(uuid),
    geo_assert_protocol_question_inventory(),
    geo_protect_protocol_question_lineage(), geo_assert_geo_simulation_evidence()
TO geo_app, geo_worker;
