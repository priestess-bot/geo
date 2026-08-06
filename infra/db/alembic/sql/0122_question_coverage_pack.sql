ALTER TABLE knowledge_question_generation_specs
ADD COLUMN generation_mode text NOT NULL DEFAULT 'single_scenario'
    CHECK (generation_mode IN ('single_scenario', 'coverage_pack')),
ADD COLUMN coverage_profile text,
ADD COLUMN coverage_profile_hash text,
ADD COLUMN target_count integer,
ADD COLUMN product_entity_id uuid,
ADD COLUMN product_category text,
ADD COLUMN product_name_snapshot text,
ADD CONSTRAINT knowledge_question_specs_coverage_shape_check CHECK (
    (
        generation_mode = 'single_scenario'
        AND coverage_profile IS NULL
        AND coverage_profile_hash IS NULL
        AND target_count IS NULL
        AND product_entity_id IS NULL
        AND product_category IS NULL
        AND product_name_snapshot IS NULL
    ) OR (
        generation_mode = 'coverage_pack'
        AND coverage_profile IS NOT NULL
        AND btrim(coverage_profile) <> ''
        AND coverage_profile_hash IS NOT NULL
        AND coverage_profile_hash ~ '^[0-9a-f]{64}$'
        AND target_count BETWEEN 1 AND 200
        AND product_entity_id IS NOT NULL
        AND product_category IS NOT NULL
        AND btrim(product_category) <> ''
        AND product_name_snapshot IS NOT NULL
        AND btrim(product_name_snapshot) <> ''
    )
),
ADD CONSTRAINT knowledge_question_specs_product_fkey
    FOREIGN KEY (product_entity_id, project_id)
    REFERENCES product_entities(id, project_id);

ALTER TABLE knowledge_question_generation_results
DROP CONSTRAINT knowledge_question_results_model_identity_check,
ADD CONSTRAINT knowledge_question_results_model_identity_check CHECK (
    (execution_backend IS NULL AND actual_model IS NULL)
    OR (
        execution_backend IN ('dify', 'native', 'hybrid', 'deterministic')
        AND actual_model IS NOT NULL
        AND btrim(actual_model) <> ''
    )
);

ALTER TABLE knowledge_question_dimensions
ADD COLUMN coverage_role text CHECK (
    coverage_role IN ('category_benchmark', 'product_fit', 'brand_control')
),
ADD COLUMN topic_cluster text,
ADD COLUMN planned_query_text text,
ADD COLUMN planned_query_hash text,
ADD CONSTRAINT knowledge_question_dimensions_coverage_shape_check CHECK (
    (coverage_role IS NULL AND topic_cluster IS NULL
        AND planned_query_text IS NULL AND planned_query_hash IS NULL)
    OR (
        coverage_role IS NOT NULL
        AND topic_cluster IS NOT NULL
        AND btrim(topic_cluster) <> ''
        AND (
            (planned_query_text IS NULL AND planned_query_hash IS NULL)
            OR (
                btrim(planned_query_text) <> ''
                AND planned_query_hash ~ '^[0-9a-f]{64}$'
            )
        )
    )
);

CREATE TABLE knowledge_question_generation_batches (
    job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    batch_index integer NOT NULL CHECK (batch_index BETWEEN 1 AND 20),
    ordinal_start integer NOT NULL CHECK (ordinal_start > 0),
    ordinal_end integer NOT NULL CHECK (ordinal_end >= ordinal_start),
    slot_count integer NOT NULL CHECK (
        slot_count BETWEEN 1 AND 10
        AND slot_count = ordinal_end - ordinal_start + 1
    ),
    output jsonb NOT NULL CHECK (jsonb_typeof(output) = 'object'),
    output_hash text NOT NULL CHECK (output_hash ~ '^[0-9a-f]{64}$'),
    execution_backend text NOT NULL CHECK (
        execution_backend IN ('dify', 'native', 'hybrid', 'deterministic')
    ),
    actual_model text NOT NULL CHECK (btrim(actual_model) <> ''),
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (job_id, batch_index),
    CONSTRAINT knowledge_question_batches_exact_context_key UNIQUE (
        job_id, project_id, campaign_id, batch_index
    ),
    CONSTRAINT knowledge_question_batches_spec_fkey FOREIGN KEY (
        job_id, project_id, campaign_id
    ) REFERENCES knowledge_question_generation_specs(job_id, project_id, campaign_id)
);

CREATE TRIGGER knowledge_question_generation_batches_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_generation_batches
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE TABLE knowledge_question_candidate_revisions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    generated_by_job_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    revision_number integer NOT NULL CHECK (revision_number > 0),
    query_text text NOT NULL CHECK (btrim(query_text) <> ''),
    query_text_hash text NOT NULL CHECK (query_text_hash ~ '^[0-9a-f]{64}$'),
    normalized_text_hash text NOT NULL CHECK (
        normalized_text_hash ~ '^[0-9a-f]{64}$'
    ),
    edited_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (candidate_id, revision_number),
    UNIQUE (candidate_id, query_text_hash),
    CONSTRAINT knowledge_question_candidate_revisions_candidate_fkey FOREIGN KEY (
        candidate_id, generated_by_job_id, project_id, campaign_id
    ) REFERENCES knowledge_question_candidates(
        id, generated_by_job_id, project_id, campaign_id
    )
);

CREATE TRIGGER knowledge_question_candidate_revisions_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_candidate_revisions
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE OR REPLACE FUNCTION geo_protect_question_candidate() RETURNS trigger
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
                   AND NEW.dedup_status = 'exact_duplicate') THEN
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
            OR NEW.nearest_similarity IS DISTINCT FROM 1.0000
            OR nearest_normalized_text_hash IS DISTINCT FROM NEW.normalized_text_hash
       )) THEN
        RAISE EXCEPTION 'Question candidate dedup result differs from its frozen threshold'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_question_set_item() RETURNS trigger
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
        LEFT JOIN LATERAL (
            SELECT value.query_text, value.query_text_hash,
                   value.normalized_text_hash
            FROM knowledge_question_candidate_revisions AS value
            WHERE value.candidate_id = candidate.id
              AND value.project_id = candidate.project_id
              AND value.campaign_id = candidate.campaign_id
            ORDER BY value.revision_number DESC
            LIMIT 1
        ) AS revision ON true
        WHERE question_set.id = NEW.question_set_id
          AND question_set.project_id = NEW.project_id
          AND question_set.campaign_id = NEW.campaign_id
          AND question_set.generated_by_job_id = NEW.generated_by_job_id
          AND question_set.status = 'draft'
          AND candidate.workflow_status = 'approved'
          AND candidate.dimension_key = NEW.dimension_key
          AND COALESCE(revision.query_text, candidate.query_text)
                = NEW.query_text_snapshot
          AND COALESCE(revision.query_text_hash, candidate.query_text_hash)
                = NEW.query_text_hash
          AND COALESCE(revision.normalized_text_hash, candidate.normalized_text_hash)
                = NEW.normalized_text_hash
          AND dimension.query_kind = NEW.query_kind_snapshot
          AND dimension.brand_scope = NEW.brand_scope_snapshot
          AND dimension.coverage_role IS NOT DISTINCT FROM NEW.coverage_role_snapshot
          AND dimension.topic_cluster IS NOT DISTINCT FROM NEW.topic_cluster_snapshot
          AND dimension.funnel = NEW.funnel_snapshot
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

ALTER TABLE knowledge_question_set_items
ADD COLUMN brand_scope_snapshot text CHECK (
    brand_scope_snapshot IN ('brand', 'non_brand', 'competitor')
),
ADD COLUMN coverage_role_snapshot text CHECK (
    coverage_role_snapshot IN ('category_benchmark', 'product_fit', 'brand_control')
),
ADD COLUMN topic_cluster_snapshot text,
ADD COLUMN funnel_snapshot text CHECK (
    funnel_snapshot IN ('awareness', 'consideration', 'decision', 'retention')
);

UPDATE knowledge_question_set_items item
SET brand_scope_snapshot = dimension.brand_scope,
    coverage_role_snapshot = dimension.coverage_role,
    topic_cluster_snapshot = dimension.topic_cluster,
    funnel_snapshot = dimension.funnel
FROM knowledge_question_dimensions dimension
WHERE dimension.job_id = item.generated_by_job_id
  AND dimension.project_id = item.project_id
  AND dimension.campaign_id = item.campaign_id
  AND dimension.dimension_key = item.dimension_key;

ALTER TABLE knowledge_question_set_items
ALTER COLUMN brand_scope_snapshot SET NOT NULL,
ALTER COLUMN funnel_snapshot SET NOT NULL;

CREATE INDEX knowledge_question_batches_progress_idx
ON knowledge_question_generation_batches (project_id, campaign_id, job_id, batch_index);
CREATE INDEX knowledge_question_candidate_revisions_latest_idx
ON knowledge_question_candidate_revisions (candidate_id, revision_number DESC);
CREATE INDEX knowledge_question_dimensions_coverage_idx
ON knowledge_question_dimensions (
    project_id, campaign_id, job_id, coverage_role, topic_cluster, ordinal
) WHERE coverage_role IS NOT NULL;

ALTER TABLE knowledge_question_generation_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_question_generation_batches FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON knowledge_question_generation_batches
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE knowledge_question_candidate_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_question_candidate_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON knowledge_question_candidate_revisions
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON knowledge_question_generation_batches,
    knowledge_question_candidate_revisions
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON knowledge_question_generation_batches,
    knowledge_question_candidate_revisions
TO geo_app, geo_worker, geo_readonly;
GRANT INSERT ON knowledge_question_candidate_revisions TO geo_app;
GRANT INSERT ON knowledge_question_generation_batches TO geo_worker;

COMMENT ON COLUMN knowledge_question_generation_specs.generation_mode IS
'single_scenario preserves the original flow; coverage_pack produces a fixed measurement library.';
COMMENT ON COLUMN knowledge_question_dimensions.planned_query_text IS
'Frozen category benchmark text. NULL means the model must generate the tailored query.';
COMMENT ON TABLE knowledge_question_generation_batches IS
'Append-only validated batch checkpoints retained across durable job attempts.';
COMMENT ON COLUMN knowledge_question_set_items.brand_scope_snapshot IS
'Frozen denominator stratum; brand controls never enter the primary non-brand denominator.';
