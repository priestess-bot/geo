ALTER TABLE knowledge_sources ADD COLUMN logical_source_id uuid;
UPDATE knowledge_sources SET logical_source_id = id;
ALTER TABLE knowledge_sources
    ALTER COLUMN logical_source_id SET NOT NULL,
    ADD COLUMN supersedes_source_id uuid,
    ADD CONSTRAINT knowledge_sources_exact_logical_key
        UNIQUE (id, project_id, logical_source_id),
    ADD CONSTRAINT knowledge_sources_logical_root_fkey
        FOREIGN KEY (logical_source_id, project_id)
        REFERENCES knowledge_sources(id, project_id),
    ADD CONSTRAINT knowledge_sources_supersedes_fkey
        FOREIGN KEY (supersedes_source_id, project_id, logical_source_id)
        REFERENCES knowledge_sources(id, project_id, logical_source_id),
    ADD CONSTRAINT knowledge_sources_single_successor_key
        UNIQUE (supersedes_source_id, project_id),
    ADD CONSTRAINT knowledge_sources_revision_shape_check CHECK (
        (id = logical_source_id AND supersedes_source_id IS NULL)
        OR (id <> logical_source_id AND supersedes_source_id IS NOT NULL)
    );

CREATE FUNCTION geo_protect_knowledge_source_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    IF (NEW.id, NEW.project_id, NEW.logical_source_id, NEW.supersedes_source_id)
       IS DISTINCT FROM
       (OLD.id, OLD.project_id, OLD.logical_source_id, OLD.supersedes_source_id) THEN
        RAISE EXCEPTION 'Knowledge source revision identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.content_hash IS NOT NULL AND (
        NEW.source_kind, NEW.title, NEW.source_url, NEW.filename, NEW.media_type,
        NEW.raw_content, NEW.content_hash
    ) IS DISTINCT FROM (
        OLD.source_kind, OLD.title, OLD.source_url, OLD.filename, OLD.media_type,
        OLD.raw_content, OLD.content_hash
    ) THEN
        RAISE EXCEPTION 'ready Knowledge source content identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.content_hash IS NULL AND NEW.content_hash IS NOT NULL
       AND NEW.status <> 'ready' THEN
        RAISE EXCEPTION 'Knowledge source content hash may only be frozen at ready'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.content_hash IS NOT NULL AND NEW.content_hash IS NULL THEN
        RAISE EXCEPTION 'Knowledge source content hash cannot be removed'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status IS DISTINCT FROM NEW.status AND NOT (
        NEW.status = 'archived'
        OR (OLD.status = 'queued' AND NEW.status IN ('processing', 'failed'))
        OR (OLD.status = 'processing' AND NEW.status IN ('ready', 'failed'))
        OR (OLD.status = 'failed' AND NEW.status = 'queued')
        OR (OLD.status = 'ready' AND NEW.status = 'queued')
    ) THEN
        RAISE EXCEPTION 'invalid Knowledge source lifecycle transition'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER knowledge_source_revision_guard
BEFORE INSERT OR UPDATE ON knowledge_sources
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_source_revision();

CREATE INDEX knowledge_sources_logical_lifecycle_idx
ON knowledge_sources (project_id, logical_source_id, status, created_at DESC, id DESC);
CREATE INDEX knowledge_sources_supersedes_fk_idx
ON knowledge_sources (supersedes_source_id, project_id, logical_source_id)
WHERE supersedes_source_id IS NOT NULL;

CREATE TABLE knowledge_rag_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    model_call_budget integer NOT NULL CHECK (model_call_budget > 0),
    adapter_release text NOT NULL CHECK (adapter_release IN (
        'project-native-rag-v1', 'llamaindex-property-graph-v1'
    )),
    selection_manifest_hash text NOT NULL CHECK (
        selection_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    requested_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_rag_job_specs_job_fkey
        FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_rag_job_specs_run_fkey
        FOREIGN KEY (pipeline_run_id, project_id, source_id)
        REFERENCES knowledge_pipeline_runs(id, project_id, source_id),
    CONSTRAINT knowledge_rag_job_specs_document_fkey
        FOREIGN KEY (document_id, project_id, pipeline_run_id, source_id)
        REFERENCES knowledge_documents(id, project_id, pipeline_run_id, source_id),
    CONSTRAINT knowledge_rag_job_specs_exact_context_key UNIQUE (
        job_id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_rag_job_specs_run_document_key
        UNIQUE (pipeline_run_id, document_id)
);

CREATE TRIGGER knowledge_rag_job_spec_kind
BEFORE INSERT OR UPDATE ON knowledge_rag_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('knowledge.rag.extract');
CREATE TRIGGER knowledge_rag_job_specs_immutable
BEFORE UPDATE ON knowledge_rag_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_reject_placement_job_spec_update();
CREATE CONSTRAINT TRIGGER knowledge_rag_job_specs_delete_guard
AFTER DELETE ON knowledge_rag_job_specs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();

CREATE INDEX knowledge_rag_job_specs_project_idx
ON knowledge_rag_job_specs (project_id, pipeline_run_id, document_id, job_id);
CREATE INDEX knowledge_rag_job_specs_run_fk_idx
ON knowledge_rag_job_specs (pipeline_run_id, project_id, source_id);
CREATE INDEX knowledge_rag_job_specs_document_fk_idx
ON knowledge_rag_job_specs (document_id, project_id, pipeline_run_id, source_id);
CREATE INDEX knowledge_rag_job_specs_requester_idx
ON knowledge_rag_job_specs (requested_by, created_at DESC);

CREATE TABLE knowledge_rag_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    logical_source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    adapter_release text NOT NULL CHECK (adapter_release IN (
        'project-native-rag-v1', 'llamaindex-property-graph-v1'
    )),
    selection_manifest_hash text NOT NULL CHECK (
        selection_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    output_hash text NOT NULL CHECK (output_hash ~ '^[0-9a-f]{64}$'),
    artifact_uri text NOT NULL CHECK (artifact_uri ~ '^s3://[^/]+/.+$'),
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    lifecycle_status text NOT NULL CHECK (
        lifecycle_status IN ('active', 'superseded', 'withdrawn')
    ),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz NOT NULL,
    superseded_at timestamptz,
    withdrawn_at timestamptz,
    CONSTRAINT knowledge_rag_revisions_artifact_identity_check CHECK (
        output_hash = artifact_hash
    ),
    CONSTRAINT knowledge_rag_revisions_lifecycle_check CHECK (
        (lifecycle_status = 'active'
            AND superseded_at IS NULL AND withdrawn_at IS NULL)
        OR (lifecycle_status = 'superseded'
            AND superseded_at IS NOT NULL AND withdrawn_at IS NULL)
        OR (lifecycle_status = 'withdrawn'
            AND superseded_at IS NULL AND withdrawn_at IS NOT NULL)
    ),
    CONSTRAINT knowledge_rag_revisions_spec_fkey FOREIGN KEY (
        job_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_rag_job_specs(
        job_id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_rag_revisions_run_fkey
        FOREIGN KEY (pipeline_run_id, project_id, source_id)
        REFERENCES knowledge_pipeline_runs(id, project_id, source_id),
    CONSTRAINT knowledge_rag_revisions_source_fkey
        FOREIGN KEY (source_id, project_id, logical_source_id)
        REFERENCES knowledge_sources(id, project_id, logical_source_id),
    CONSTRAINT knowledge_rag_revisions_document_fkey
        FOREIGN KEY (document_id, project_id, pipeline_run_id, source_id)
        REFERENCES knowledge_documents(id, project_id, pipeline_run_id, source_id),
    CONSTRAINT knowledge_rag_revisions_job_key UNIQUE (job_id, project_id),
    CONSTRAINT knowledge_rag_revisions_input_key UNIQUE (
        pipeline_run_id, document_id, adapter_release, input_hash
    ),
    CONSTRAINT knowledge_rag_revisions_exact_context_key UNIQUE (
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_rag_revisions_exact_job_context_key UNIQUE (
        id, project_id, job_id, pipeline_run_id, source_id, document_id
    )
);

CREATE UNIQUE INDEX knowledge_rag_revisions_active_source_key
ON knowledge_rag_revisions (project_id, logical_source_id)
WHERE lifecycle_status = 'active';
CREATE INDEX knowledge_rag_revisions_source_idx
ON knowledge_rag_revisions (
    project_id, logical_source_id, lifecycle_status, completed_at DESC, id DESC
);
CREATE INDEX knowledge_rag_revisions_spec_fk_idx
ON knowledge_rag_revisions (
    job_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_rag_revisions_run_fk_idx
ON knowledge_rag_revisions (pipeline_run_id, project_id, source_id);
CREATE INDEX knowledge_rag_revisions_source_fk_idx
ON knowledge_rag_revisions (source_id, project_id, logical_source_id);
CREATE INDEX knowledge_rag_revisions_document_fk_idx
ON knowledge_rag_revisions (document_id, project_id, pipeline_run_id, source_id);

CREATE FUNCTION geo_protect_knowledge_rag_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Knowledge RAG revisions cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF to_jsonb(NEW) - ARRAY['lifecycle_status', 'superseded_at', 'withdrawn_at']
       IS DISTINCT FROM
       to_jsonb(OLD) - ARRAY['lifecycle_status', 'superseded_at', 'withdrawn_at'] THEN
        RAISE EXCEPTION 'Knowledge RAG revision evidence is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.lifecycle_status <> 'active'
       OR NEW.lifecycle_status NOT IN ('superseded', 'withdrawn') THEN
        RAISE EXCEPTION 'invalid Knowledge RAG revision lifecycle transition'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER knowledge_rag_revisions_lifecycle_guard
BEFORE UPDATE OR DELETE ON knowledge_rag_revisions
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_rag_revision();

ALTER TABLE knowledge_fact_candidates
    DROP CONSTRAINT knowledge_fact_candidates_pipeline_run_id_statement_hash_key,
    ADD COLUMN rag_revision_id uuid,
    ADD COLUMN extractor_release text NOT NULL DEFAULT 'legacy-sentence-v1',
    ADD COLUMN source_locator text,
    ADD COLUMN lifecycle_status text NOT NULL DEFAULT 'active',
    ADD CONSTRAINT knowledge_facts_lifecycle_status_check CHECK (
        lifecycle_status IN ('active', 'superseded', 'withdrawn')
    ),
    ADD CONSTRAINT knowledge_facts_extractor_contract_check CHECK (
        (rag_revision_id IS NULL
            AND extractor_release = 'legacy-sentence-v1'
            AND source_locator IS NULL)
        OR (rag_revision_id IS NOT NULL
            AND extractor_release IN (
                'project-native-rag-v1', 'llamaindex-property-graph-v1'
            )
            AND source_locator ~ '^line:[1-9][0-9]*$')
    ),
    ADD CONSTRAINT knowledge_facts_review_shape_check CHECK (
        (status = 'pending_review' AND reviewed_by IS NULL AND reviewed_at IS NULL)
        OR (status IN ('approved', 'rejected')
            AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
    ),
    ADD CONSTRAINT knowledge_facts_rag_revision_fkey FOREIGN KEY (
        rag_revision_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    ADD CONSTRAINT knowledge_facts_rag_identity_key
        UNIQUE (rag_revision_id, statement_hash),
    ADD CONSTRAINT knowledge_facts_candidate_context_key
        UNIQUE (id, project_id, pipeline_run_id, source_id, document_id),
    ADD CONSTRAINT knowledge_facts_candidate_revision_context_key UNIQUE (
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id
    );

CREATE UNIQUE INDEX knowledge_facts_legacy_statement_key
ON knowledge_fact_candidates (pipeline_run_id, statement_hash)
WHERE rag_revision_id IS NULL;
CREATE INDEX knowledge_facts_rag_revision_idx
ON knowledge_fact_candidates (
    project_id, rag_revision_id, lifecycle_status, status, created_at DESC, id DESC
)
WHERE rag_revision_id IS NOT NULL;

CREATE FUNCTION geo_protect_knowledge_fact_candidate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.rag_revision_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM knowledge_rag_revisions AS revision
            WHERE revision.id = NEW.rag_revision_id
              AND revision.project_id = NEW.project_id
              AND revision.pipeline_run_id = NEW.pipeline_run_id
              AND revision.source_id = NEW.source_id
              AND revision.document_id = NEW.document_id
              AND revision.adapter_release = NEW.extractor_release
              AND revision.lifecycle_status = 'active'
        ) THEN
            RAISE EXCEPTION 'RAG Fact requires its active matching extractor revision'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Knowledge Fact candidates cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF to_jsonb(NEW) - ARRAY[
        'status', 'reviewed_by', 'review_notes', 'reviewed_at',
        'lifecycle_status', 'updated_at'
    ] IS DISTINCT FROM to_jsonb(OLD) - ARRAY[
        'status', 'reviewed_by', 'review_notes', 'reviewed_at',
        'lifecycle_status', 'updated_at'
    ] THEN
        RAISE EXCEPTION 'Knowledge Fact candidate identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.lifecycle_status IS DISTINCT FROM NEW.lifecycle_status AND NOT (
        OLD.lifecycle_status = 'active'
        AND NEW.lifecycle_status IN ('superseded', 'withdrawn')
    ) THEN
        RAISE EXCEPTION 'invalid Knowledge Fact candidate lifecycle transition'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status IS DISTINCT FROM NEW.status AND NOT (
        OLD.status = 'pending_review' AND NEW.status IN ('approved', 'rejected')
        AND OLD.lifecycle_status = 'active' AND NEW.lifecycle_status = 'active'
    ) THEN
        RAISE EXCEPTION 'invalid Knowledge Fact candidate review transition'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status IS NOT DISTINCT FROM NEW.status AND (
        NEW.reviewed_by, NEW.review_notes, NEW.reviewed_at
    ) IS DISTINCT FROM (
        OLD.reviewed_by, OLD.review_notes, OLD.reviewed_at
    ) THEN
        RAISE EXCEPTION 'Knowledge Fact review metadata is immutable after decision'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER knowledge_fact_candidate_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_fact_candidates
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_fact_candidate();

CREATE FUNCTION geo_require_active_fact_for_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.item_type = 'approved_fact' AND NOT EXISTS (
        SELECT 1 FROM knowledge_fact_candidates AS fact
        WHERE fact.id = NEW.source_id AND fact.project_id = NEW.project_id
          AND fact.status = 'approved' AND fact.lifecycle_status = 'active'
    ) THEN
        RAISE EXCEPTION 'approved Fact Evidence requires an active approved candidate'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER evidence_items_active_fact_guard
BEFORE INSERT ON evidence_items
FOR EACH ROW EXECUTE FUNCTION geo_require_active_fact_for_evidence();

CREATE TABLE knowledge_fact_candidate_sources (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    fact_candidate_id uuid NOT NULL,
    rag_revision_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    source_locator text NOT NULL CHECK (source_locator ~ '^line:[1-9][0-9]*$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (
        project_id, fact_candidate_id, rag_revision_id, chunk_id, source_locator
    ),
    CONSTRAINT knowledge_fact_candidate_sources_fact_fkey FOREIGN KEY (
        fact_candidate_id, project_id, rag_revision_id, pipeline_run_id,
        source_id, document_id
    ) REFERENCES knowledge_fact_candidates(
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_fact_candidate_sources_revision_fkey FOREIGN KEY (
        rag_revision_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_fact_candidate_sources_chunk_fkey FOREIGN KEY (
        chunk_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_chunks(
        id, project_id, pipeline_run_id, source_id, document_id
    )
);

CREATE TRIGGER knowledge_fact_candidate_sources_immutable
BEFORE UPDATE OR DELETE ON knowledge_fact_candidate_sources
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE INDEX knowledge_fact_candidate_sources_fact_idx
ON knowledge_fact_candidate_sources (
    fact_candidate_id, project_id, rag_revision_id, pipeline_run_id,
    source_id, document_id
);
CREATE INDEX knowledge_fact_candidate_sources_revision_idx
ON knowledge_fact_candidate_sources (
    rag_revision_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_fact_candidate_sources_chunk_idx
ON knowledge_fact_candidate_sources (
    chunk_id, project_id, pipeline_run_id, source_id, document_id
);

CREATE TABLE knowledge_entity_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rag_revision_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    adapter_candidate_id text NOT NULL CHECK (btrim(adapter_candidate_id) <> ''),
    entity_type text NOT NULL CHECK (entity_type IN (
        'brand', 'product', 'competitor', 'feature', 'specification',
        'use_case', 'persona', 'pain_point', 'market', 'channel'
    )),
    name text NOT NULL CHECK (btrim(name) <> ''),
    name_hash text NOT NULL CHECK (name_hash ~ '^[0-9a-f]{64}$'),
    workflow_status text NOT NULL DEFAULT 'pending_review' CHECK (
        workflow_status IN ('pending_review', 'approved', 'rejected')
    ),
    lifecycle_status text NOT NULL DEFAULT 'active' CHECK (
        lifecycle_status IN ('active', 'superseded', 'withdrawn')
    ),
    reviewed_by uuid REFERENCES identities(id),
    review_notes text,
    reviewed_at timestamptz,
    graph_entity_id uuid,
    generated_by_job_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_entity_candidates_review_shape_check CHECK (
        (workflow_status = 'pending_review'
            AND reviewed_by IS NULL AND reviewed_at IS NULL
            AND graph_entity_id IS NULL)
        OR (workflow_status = 'rejected'
            AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL
            AND graph_entity_id IS NULL)
        OR (workflow_status = 'approved'
            AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL
            AND graph_entity_id IS NOT NULL)
    ),
    CONSTRAINT knowledge_entity_candidates_revision_job_fkey FOREIGN KEY (
        rag_revision_id, project_id, generated_by_job_id, pipeline_run_id,
        source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, job_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_entity_candidates_exact_context_key UNIQUE (
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_entity_candidates_name_key
        UNIQUE (rag_revision_id, entity_type, name_hash),
    CONSTRAINT knowledge_entity_candidates_adapter_key
        UNIQUE (rag_revision_id, adapter_candidate_id)
);

CREATE TABLE knowledge_entity_candidate_sources (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_candidate_id uuid NOT NULL,
    rag_revision_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    source_locator text NOT NULL CHECK (source_locator ~ '^line:[1-9][0-9]*$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (
        project_id, entity_candidate_id, rag_revision_id, chunk_id, source_locator
    ),
    CONSTRAINT knowledge_entity_candidate_sources_candidate_fkey FOREIGN KEY (
        entity_candidate_id, project_id, rag_revision_id, pipeline_run_id,
        source_id, document_id
    ) REFERENCES knowledge_entity_candidates(
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_entity_candidate_sources_revision_fkey FOREIGN KEY (
        rag_revision_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_entity_candidate_sources_chunk_fkey FOREIGN KEY (
        chunk_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_chunks(
        id, project_id, pipeline_run_id, source_id, document_id
    )
);

CREATE TABLE knowledge_relation_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rag_revision_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    adapter_candidate_id text NOT NULL CHECK (btrim(adapter_candidate_id) <> ''),
    subject_entity_candidate_id uuid NOT NULL,
    predicate text NOT NULL CHECK (predicate IN (
        'belongs_to', 'has_feature', 'has_specification', 'competes_with',
        'belongs_to_market', 'uses_channel', 'compatible_with',
        'has_pain_point', 'supports_use_case'
    )),
    object_entity_candidate_id uuid NOT NULL,
    source_locator text NOT NULL CHECK (source_locator ~ '^line:[1-9][0-9]*$'),
    workflow_status text NOT NULL DEFAULT 'pending_review' CHECK (
        workflow_status IN ('pending_review', 'approved', 'rejected')
    ),
    lifecycle_status text NOT NULL DEFAULT 'active' CHECK (
        lifecycle_status IN ('active', 'superseded', 'withdrawn')
    ),
    reviewed_by uuid REFERENCES identities(id),
    review_notes text,
    reviewed_at timestamptz,
    graph_relation_id uuid,
    generated_by_job_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_relation_candidates_distinct_endpoints_check CHECK (
        subject_entity_candidate_id <> object_entity_candidate_id
    ),
    CONSTRAINT knowledge_relation_candidates_review_shape_check CHECK (
        (workflow_status = 'pending_review'
            AND reviewed_by IS NULL AND reviewed_at IS NULL
            AND graph_relation_id IS NULL)
        OR (workflow_status = 'rejected'
            AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL
            AND graph_relation_id IS NULL)
        OR (workflow_status = 'approved'
            AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL
            AND graph_relation_id IS NOT NULL)
    ),
    CONSTRAINT knowledge_relation_candidates_revision_job_fkey FOREIGN KEY (
        rag_revision_id, project_id, generated_by_job_id, pipeline_run_id,
        source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, job_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_relation_candidates_chunk_fkey FOREIGN KEY (
        chunk_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_chunks(
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_relation_candidates_subject_fkey FOREIGN KEY (
        subject_entity_candidate_id, project_id, rag_revision_id,
        pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_entity_candidates(
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_relation_candidates_object_fkey FOREIGN KEY (
        object_entity_candidate_id, project_id, rag_revision_id,
        pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_entity_candidates(
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_relation_candidates_exact_context_key UNIQUE (
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id,
        chunk_id
    ),
    CONSTRAINT knowledge_relation_candidates_identity_key UNIQUE (
        rag_revision_id, subject_entity_candidate_id, predicate,
        object_entity_candidate_id, chunk_id
    ),
    CONSTRAINT knowledge_relation_candidates_adapter_key
        UNIQUE (rag_revision_id, adapter_candidate_id)
);

CREATE FUNCTION geo_protect_knowledge_graph_candidate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.lifecycle_status <> 'active' OR NOT EXISTS (
            SELECT 1 FROM knowledge_rag_revisions AS revision
            WHERE revision.id = NEW.rag_revision_id
              AND revision.project_id = NEW.project_id
              AND revision.job_id = NEW.generated_by_job_id
              AND revision.pipeline_run_id = NEW.pipeline_run_id
              AND revision.source_id = NEW.source_id
              AND revision.document_id = NEW.document_id
              AND revision.lifecycle_status = 'active'
        ) THEN
            RAISE EXCEPTION 'Knowledge graph candidate requires its active RAG revision'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Knowledge graph candidates cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF to_jsonb(NEW) - ARRAY[
        'workflow_status', 'lifecycle_status', 'reviewed_by', 'review_notes',
        'reviewed_at', 'graph_entity_id', 'graph_relation_id', 'updated_at'
    ] IS DISTINCT FROM to_jsonb(OLD) - ARRAY[
        'workflow_status', 'lifecycle_status', 'reviewed_by', 'review_notes',
        'reviewed_at', 'graph_entity_id', 'graph_relation_id', 'updated_at'
    ] THEN
        RAISE EXCEPTION 'Knowledge graph candidate identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.lifecycle_status IS DISTINCT FROM NEW.lifecycle_status AND NOT (
        OLD.lifecycle_status = 'active'
        AND NEW.lifecycle_status IN ('superseded', 'withdrawn')
    ) THEN
        RAISE EXCEPTION 'invalid Knowledge graph candidate lifecycle transition'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.workflow_status IS DISTINCT FROM NEW.workflow_status AND NOT (
        OLD.workflow_status = 'pending_review'
        AND NEW.workflow_status IN ('approved', 'rejected')
        AND OLD.lifecycle_status = 'active' AND NEW.lifecycle_status = 'active'
    ) THEN
        RAISE EXCEPTION 'invalid Knowledge graph candidate review transition'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.workflow_status IS NOT DISTINCT FROM NEW.workflow_status
       AND jsonb_build_object(
           'reviewed_by', to_jsonb(NEW) -> 'reviewed_by',
           'review_notes', to_jsonb(NEW) -> 'review_notes',
           'reviewed_at', to_jsonb(NEW) -> 'reviewed_at',
           'graph_entity_id', to_jsonb(NEW) -> 'graph_entity_id',
           'graph_relation_id', to_jsonb(NEW) -> 'graph_relation_id'
       ) IS DISTINCT FROM jsonb_build_object(
           'reviewed_by', to_jsonb(OLD) -> 'reviewed_by',
           'review_notes', to_jsonb(OLD) -> 'review_notes',
           'reviewed_at', to_jsonb(OLD) -> 'reviewed_at',
           'graph_entity_id', to_jsonb(OLD) -> 'graph_entity_id',
           'graph_relation_id', to_jsonb(OLD) -> 'graph_relation_id'
       ) THEN
        RAISE EXCEPTION 'Knowledge graph review metadata is immutable after decision'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER knowledge_entity_candidates_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_entity_candidates
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_graph_candidate();
CREATE TRIGGER knowledge_relation_candidates_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_relation_candidates
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_graph_candidate();
CREATE TRIGGER knowledge_entity_candidate_sources_immutable
BEFORE UPDATE OR DELETE ON knowledge_entity_candidate_sources
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX knowledge_entity_candidates_review_idx
ON knowledge_entity_candidates (
    project_id, lifecycle_status, workflow_status, created_at, id
);
CREATE INDEX knowledge_entity_candidates_revision_idx
ON knowledge_entity_candidates (rag_revision_id, project_id, generated_by_job_id);
CREATE INDEX knowledge_entity_candidates_reviewer_idx
ON knowledge_entity_candidates (reviewed_by, reviewed_at DESC)
WHERE reviewed_by IS NOT NULL;
CREATE INDEX knowledge_entity_candidate_sources_candidate_idx
ON knowledge_entity_candidate_sources (
    entity_candidate_id, project_id, rag_revision_id, pipeline_run_id,
    source_id, document_id
);
CREATE INDEX knowledge_entity_candidate_sources_revision_idx
ON knowledge_entity_candidate_sources (
    rag_revision_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_entity_candidate_sources_chunk_idx
ON knowledge_entity_candidate_sources (
    chunk_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_relation_candidates_review_idx
ON knowledge_relation_candidates (
    project_id, lifecycle_status, workflow_status, created_at, id
);
CREATE INDEX knowledge_relation_candidates_revision_idx
ON knowledge_relation_candidates (rag_revision_id, project_id, generated_by_job_id);
CREATE INDEX knowledge_relation_candidates_chunk_idx
ON knowledge_relation_candidates (
    chunk_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_relation_candidates_subject_idx
ON knowledge_relation_candidates (
    subject_entity_candidate_id, project_id, rag_revision_id,
    pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_relation_candidates_object_idx
ON knowledge_relation_candidates (
    object_entity_candidate_id, project_id, rag_revision_id,
    pipeline_run_id, source_id, document_id
);

CREATE TABLE knowledge_rag_validation_findings (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rag_revision_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    candidate_kind text NOT NULL CHECK (btrim(candidate_kind) <> ''),
    reason_code text NOT NULL CHECK (btrim(reason_code) <> ''),
    candidate_hash text NOT NULL CHECK (candidate_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (
        project_id, rag_revision_id, chunk_id, candidate_kind,
        reason_code, candidate_hash
    ),
    CONSTRAINT knowledge_rag_validation_findings_revision_fkey FOREIGN KEY (
        rag_revision_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_rag_validation_findings_chunk_fkey FOREIGN KEY (
        chunk_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_chunks(
        id, project_id, pipeline_run_id, source_id, document_id
    )
);

CREATE TRIGGER knowledge_rag_validation_findings_immutable
BEFORE UPDATE OR DELETE ON knowledge_rag_validation_findings
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE INDEX knowledge_rag_validation_findings_revision_idx
ON knowledge_rag_validation_findings (
    rag_revision_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_rag_validation_findings_chunk_idx
ON knowledge_rag_validation_findings (
    chunk_id, project_id, pipeline_run_id, source_id, document_id
);

CREATE TABLE knowledge_graph_entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_type text NOT NULL CHECK (entity_type IN (
        'brand', 'product', 'competitor', 'feature', 'specification',
        'use_case', 'persona', 'pain_point', 'market', 'channel'
    )),
    canonical_name text NOT NULL CHECK (btrim(canonical_name) <> ''),
    name_hash text NOT NULL CHECK (name_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('current', 'archived')),
    approved_by uuid NOT NULL REFERENCES identities(id),
    approved_at timestamptz NOT NULL,
    catalog_entity_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_graph_entities_exact_context_key UNIQUE (id, project_id),
    CONSTRAINT knowledge_graph_entities_identity_key
        UNIQUE (project_id, entity_type, name_hash),
    CONSTRAINT knowledge_graph_entities_catalog_fkey
        FOREIGN KEY (catalog_entity_id, project_id)
        REFERENCES product_entities(id, project_id)
);

CREATE TABLE knowledge_graph_entity_sources (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    graph_entity_id uuid NOT NULL,
    rag_revision_id uuid NOT NULL,
    entity_candidate_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    source_locator text NOT NULL CHECK (source_locator ~ '^line:[1-9][0-9]*$'),
    approved_by uuid NOT NULL REFERENCES identities(id),
    lifecycle_status text NOT NULL CHECK (
        lifecycle_status IN ('active', 'superseded', 'withdrawn')
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (
        project_id, graph_entity_id, entity_candidate_id,
        rag_revision_id, chunk_id, source_locator
    ),
    CONSTRAINT knowledge_graph_entity_sources_graph_fkey
        FOREIGN KEY (graph_entity_id, project_id)
        REFERENCES knowledge_graph_entities(id, project_id),
    CONSTRAINT knowledge_graph_entity_sources_candidate_fkey FOREIGN KEY (
        entity_candidate_id, project_id, rag_revision_id, pipeline_run_id,
        source_id, document_id
    ) REFERENCES knowledge_entity_candidates(
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_graph_entity_sources_revision_fkey FOREIGN KEY (
        rag_revision_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_graph_entity_sources_chunk_fkey FOREIGN KEY (
        chunk_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_chunks(
        id, project_id, pipeline_run_id, source_id, document_id
    )
);

CREATE TABLE knowledge_graph_relations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject_graph_entity_id uuid NOT NULL,
    predicate text NOT NULL CHECK (predicate IN (
        'belongs_to', 'has_feature', 'has_specification', 'competes_with',
        'belongs_to_market', 'uses_channel', 'compatible_with',
        'has_pain_point', 'supports_use_case'
    )),
    object_graph_entity_id uuid NOT NULL,
    status text NOT NULL CHECK (status IN ('current', 'archived')),
    approved_by uuid NOT NULL REFERENCES identities(id),
    approved_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_graph_relations_distinct_endpoints_check CHECK (
        subject_graph_entity_id <> object_graph_entity_id
    ),
    CONSTRAINT knowledge_graph_relations_subject_fkey
        FOREIGN KEY (subject_graph_entity_id, project_id)
        REFERENCES knowledge_graph_entities(id, project_id),
    CONSTRAINT knowledge_graph_relations_object_fkey
        FOREIGN KEY (object_graph_entity_id, project_id)
        REFERENCES knowledge_graph_entities(id, project_id),
    CONSTRAINT knowledge_graph_relations_exact_context_key UNIQUE (id, project_id),
    CONSTRAINT knowledge_graph_relations_identity_key UNIQUE (
        project_id, subject_graph_entity_id, predicate, object_graph_entity_id
    )
);

CREATE TABLE knowledge_graph_relation_sources (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    graph_relation_id uuid NOT NULL,
    rag_revision_id uuid NOT NULL,
    relation_candidate_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    source_locator text NOT NULL CHECK (source_locator ~ '^line:[1-9][0-9]*$'),
    approved_by uuid NOT NULL REFERENCES identities(id),
    lifecycle_status text NOT NULL CHECK (
        lifecycle_status IN ('active', 'superseded', 'withdrawn')
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (
        project_id, graph_relation_id, relation_candidate_id,
        rag_revision_id, chunk_id, source_locator
    ),
    CONSTRAINT knowledge_graph_relation_sources_graph_fkey
        FOREIGN KEY (graph_relation_id, project_id)
        REFERENCES knowledge_graph_relations(id, project_id),
    CONSTRAINT knowledge_graph_relation_sources_candidate_fkey FOREIGN KEY (
        relation_candidate_id, project_id, rag_revision_id, pipeline_run_id,
        source_id, document_id, chunk_id
    ) REFERENCES knowledge_relation_candidates(
        id, project_id, rag_revision_id, pipeline_run_id, source_id, document_id,
        chunk_id
    ),
    CONSTRAINT knowledge_graph_relation_sources_revision_fkey FOREIGN KEY (
        rag_revision_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_rag_revisions(
        id, project_id, pipeline_run_id, source_id, document_id
    ),
    CONSTRAINT knowledge_graph_relation_sources_chunk_fkey FOREIGN KEY (
        chunk_id, project_id, pipeline_run_id, source_id, document_id
    ) REFERENCES knowledge_chunks(
        id, project_id, pipeline_run_id, source_id, document_id
    )
);

ALTER TABLE knowledge_entity_candidates
    ADD CONSTRAINT knowledge_entity_candidates_graph_fkey
        FOREIGN KEY (graph_entity_id, project_id)
        REFERENCES knowledge_graph_entities(id, project_id);
ALTER TABLE knowledge_relation_candidates
    ADD CONSTRAINT knowledge_relation_candidates_graph_fkey
        FOREIGN KEY (graph_relation_id, project_id)
        REFERENCES knowledge_graph_relations(id, project_id);

CREATE FUNCTION geo_protect_knowledge_graph_entity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'approved Knowledge graph entities cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF to_jsonb(NEW) - ARRAY['status', 'catalog_entity_id', 'updated_at']
           IS DISTINCT FROM
           to_jsonb(OLD) - ARRAY['status', 'catalog_entity_id', 'updated_at'] THEN
            RAISE EXCEPTION 'approved Knowledge graph entity identity is immutable'
                USING ERRCODE = '55000';
        END IF;
        IF OLD.status IS DISTINCT FROM NEW.status
           AND (OLD.status, NEW.status) NOT IN (
               ('current', 'archived'), ('archived', 'current')
           ) THEN
            RAISE EXCEPTION 'invalid approved Knowledge graph entity transition'
                USING ERRCODE = '55000';
        END IF;
        IF OLD.catalog_entity_id IS DISTINCT FROM NEW.catalog_entity_id
           AND NOT (OLD.catalog_entity_id IS NULL AND NEW.catalog_entity_id IS NOT NULL) THEN
            RAISE EXCEPTION 'Knowledge graph Catalog mapping is immutable once set'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF NEW.catalog_entity_id IS NOT NULL THEN
        IF NEW.entity_type NOT IN ('brand', 'product', 'competitor', 'market')
           OR NOT EXISTS (
               SELECT 1 FROM product_entities AS catalog
               WHERE catalog.id = NEW.catalog_entity_id
                 AND catalog.project_id = NEW.project_id
                 AND catalog.entity_type = NEW.entity_type
                 AND catalog.canonical_name = NEW.canonical_name
                 AND catalog.status = 'active'
           ) THEN
            RAISE EXCEPTION 'Knowledge graph Catalog mapping must match project, type, name and active status'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_protect_knowledge_graph_relation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'approved Knowledge graph relations cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF to_jsonb(NEW) - ARRAY['status', 'updated_at']
           IS DISTINCT FROM to_jsonb(OLD) - ARRAY['status', 'updated_at'] THEN
            RAISE EXCEPTION 'approved Knowledge graph relation identity is immutable'
                USING ERRCODE = '55000';
        END IF;
        IF OLD.status IS DISTINCT FROM NEW.status
           AND (OLD.status, NEW.status) NOT IN (
               ('current', 'archived'), ('archived', 'current')
           ) THEN
            RAISE EXCEPTION 'invalid approved Knowledge graph relation transition'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF NEW.status = 'current' AND NOT EXISTS (
        SELECT 1
        FROM knowledge_graph_entities AS subject
        JOIN knowledge_graph_entities AS object
          ON object.id = NEW.object_graph_entity_id
         AND object.project_id = NEW.project_id
        WHERE subject.id = NEW.subject_graph_entity_id
          AND subject.project_id = NEW.project_id
          AND subject.status = 'current' AND object.status = 'current'
    ) THEN
        RAISE EXCEPTION 'current Knowledge graph relation requires current approved endpoints'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_protect_knowledge_graph_source() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.lifecycle_status <> 'active' THEN
            RAISE EXCEPTION 'new approved Knowledge graph source must be active'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'approved Knowledge graph sources cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF to_jsonb(NEW) - 'lifecycle_status'
       IS DISTINCT FROM to_jsonb(OLD) - 'lifecycle_status' THEN
        RAISE EXCEPTION 'approved Knowledge graph source identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.lifecycle_status IS DISTINCT FROM NEW.lifecycle_status AND NOT (
        OLD.lifecycle_status = 'active'
        AND NEW.lifecycle_status IN ('superseded', 'withdrawn')
    ) THEN
        RAISE EXCEPTION 'invalid approved Knowledge graph source transition'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER knowledge_graph_entities_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_graph_entities
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_graph_entity();
CREATE TRIGGER knowledge_graph_relations_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_graph_relations
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_graph_relation();
CREATE TRIGGER knowledge_graph_entity_sources_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_graph_entity_sources
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_graph_source();
CREATE TRIGGER knowledge_graph_relation_sources_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON knowledge_graph_relation_sources
FOR EACH ROW EXECUTE FUNCTION geo_protect_knowledge_graph_source();

CREATE FUNCTION geo_assert_knowledge_entity_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    candidate record;
BEGIN
    SELECT * INTO candidate
    FROM knowledge_entity_candidates
    WHERE id = NEW.id AND project_id = NEW.project_id;
    IF NOT FOUND OR candidate.workflow_status <> 'approved' THEN
        RETURN NULL;
    END IF;
    IF NOT EXISTS (
           SELECT 1 FROM knowledge_graph_entities AS graph
           WHERE graph.id = candidate.graph_entity_id
             AND graph.project_id = candidate.project_id
             AND graph.entity_type = candidate.entity_type
             AND graph.canonical_name = candidate.name
             AND graph.name_hash = candidate.name_hash
       )
       OR NOT EXISTS (
           SELECT 1 FROM knowledge_graph_entity_sources AS source
           WHERE source.project_id = candidate.project_id
             AND source.graph_entity_id = candidate.graph_entity_id
             AND source.entity_candidate_id = candidate.id
             AND source.rag_revision_id = candidate.rag_revision_id
       ) THEN
        RAISE EXCEPTION 'approved entity candidate requires its exact approved graph row and source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_knowledge_entity_graph_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    source_row record;
BEGIN
    SELECT * INTO source_row
    FROM knowledge_graph_entity_sources
    WHERE project_id = NEW.project_id
      AND graph_entity_id = NEW.graph_entity_id
      AND entity_candidate_id = NEW.entity_candidate_id
      AND rag_revision_id = NEW.rag_revision_id
      AND chunk_id = NEW.chunk_id
      AND source_locator = NEW.source_locator;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM knowledge_entity_candidates AS candidate
        JOIN knowledge_graph_entities AS graph
          ON graph.id = source_row.graph_entity_id
         AND graph.project_id = source_row.project_id
        WHERE candidate.id = source_row.entity_candidate_id
          AND candidate.project_id = source_row.project_id
          AND candidate.rag_revision_id = source_row.rag_revision_id
          AND candidate.workflow_status = 'approved'
          AND candidate.graph_entity_id = source_row.graph_entity_id
          AND graph.entity_type = candidate.entity_type
          AND graph.canonical_name = candidate.name
          AND graph.name_hash = candidate.name_hash
          AND (source_row.lifecycle_status <> 'active' OR graph.status = 'current')
    ) THEN
        RAISE EXCEPTION 'approved graph entity source must match an approved candidate'
            USING ERRCODE = '23514';
    END IF;
    IF source_row.lifecycle_status <> 'active'
       AND NOT EXISTS (
           SELECT 1 FROM knowledge_graph_entity_sources AS other
           WHERE other.project_id = source_row.project_id
             AND other.graph_entity_id = source_row.graph_entity_id
             AND other.lifecycle_status = 'active'
       )
       AND EXISTS (
           SELECT 1 FROM knowledge_graph_entities AS graph
           WHERE graph.id = source_row.graph_entity_id
             AND graph.project_id = source_row.project_id
             AND graph.status = 'current'
       ) THEN
        RAISE EXCEPTION 'graph entity without active sources must be archived'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_knowledge_relation_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    candidate record;
BEGIN
    SELECT * INTO candidate
    FROM knowledge_relation_candidates
    WHERE id = NEW.id AND project_id = NEW.project_id;
    IF NOT FOUND OR candidate.workflow_status <> 'approved' THEN
        RETURN NULL;
    END IF;
    IF NOT EXISTS (
           SELECT 1
           FROM knowledge_entity_candidates AS subject
           JOIN knowledge_entity_candidates AS object
             ON object.id = candidate.object_entity_candidate_id
            AND object.project_id = candidate.project_id
            AND object.rag_revision_id = candidate.rag_revision_id
           JOIN knowledge_graph_relations AS graph
             ON graph.id = candidate.graph_relation_id
            AND graph.project_id = candidate.project_id
            AND graph.subject_graph_entity_id = subject.graph_entity_id
            AND graph.object_graph_entity_id = object.graph_entity_id
            AND graph.predicate = candidate.predicate
           WHERE subject.id = candidate.subject_entity_candidate_id
             AND subject.project_id = candidate.project_id
             AND subject.rag_revision_id = candidate.rag_revision_id
             AND subject.workflow_status = 'approved'
             AND object.workflow_status = 'approved'
       )
       OR NOT EXISTS (
           SELECT 1 FROM knowledge_graph_relation_sources AS source
           WHERE source.project_id = candidate.project_id
             AND source.graph_relation_id = candidate.graph_relation_id
             AND source.relation_candidate_id = candidate.id
             AND source.rag_revision_id = candidate.rag_revision_id
       ) THEN
        RAISE EXCEPTION 'approved relation candidate requires approved graph endpoints and source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_knowledge_relation_graph_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    source_row record;
BEGIN
    SELECT * INTO source_row
    FROM knowledge_graph_relation_sources
    WHERE project_id = NEW.project_id
      AND graph_relation_id = NEW.graph_relation_id
      AND relation_candidate_id = NEW.relation_candidate_id
      AND rag_revision_id = NEW.rag_revision_id
      AND chunk_id = NEW.chunk_id
      AND source_locator = NEW.source_locator;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM knowledge_relation_candidates AS candidate
        JOIN knowledge_entity_candidates AS subject
          ON subject.id = candidate.subject_entity_candidate_id
         AND subject.project_id = candidate.project_id
         AND subject.rag_revision_id = candidate.rag_revision_id
        JOIN knowledge_entity_candidates AS object
          ON object.id = candidate.object_entity_candidate_id
         AND object.project_id = candidate.project_id
         AND object.rag_revision_id = candidate.rag_revision_id
        JOIN knowledge_graph_relations AS graph
          ON graph.id = source_row.graph_relation_id
         AND graph.project_id = source_row.project_id
         AND graph.subject_graph_entity_id = subject.graph_entity_id
         AND graph.object_graph_entity_id = object.graph_entity_id
         AND graph.predicate = candidate.predicate
        WHERE candidate.id = source_row.relation_candidate_id
          AND candidate.project_id = source_row.project_id
          AND candidate.rag_revision_id = source_row.rag_revision_id
          AND candidate.workflow_status = 'approved'
          AND candidate.graph_relation_id = source_row.graph_relation_id
          AND subject.workflow_status = 'approved'
          AND object.workflow_status = 'approved'
          AND (source_row.lifecycle_status <> 'active' OR graph.status = 'current')
    ) THEN
        RAISE EXCEPTION 'approved graph relation source must match an approved relation candidate'
            USING ERRCODE = '23514';
    END IF;
    IF source_row.lifecycle_status <> 'active'
       AND NOT EXISTS (
           SELECT 1 FROM knowledge_graph_relation_sources AS other
           WHERE other.project_id = source_row.project_id
             AND other.graph_relation_id = source_row.graph_relation_id
             AND other.lifecycle_status = 'active'
       )
       AND EXISTS (
           SELECT 1 FROM knowledge_graph_relations AS graph
           WHERE graph.id = source_row.graph_relation_id
             AND graph.project_id = source_row.project_id
             AND graph.status = 'current'
       ) THEN
        RAISE EXCEPTION 'graph relation without active sources must be archived'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_current_graph_entity_has_source() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM knowledge_graph_entity_sources AS source
        WHERE source.project_id = NEW.project_id
          AND source.graph_entity_id = NEW.id
    ) OR (NEW.status = 'current' AND NOT EXISTS (
        SELECT 1 FROM knowledge_graph_entity_sources AS source
        WHERE source.project_id = NEW.project_id
          AND source.graph_entity_id = NEW.id
          AND source.lifecycle_status = 'active'
    )) THEN
        RAISE EXCEPTION 'approved graph entity requires source lineage and current requires an active source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_current_graph_relation_has_source() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM knowledge_graph_relation_sources AS source
        WHERE source.project_id = NEW.project_id
          AND source.graph_relation_id = NEW.id
    ) OR (NEW.status = 'current' AND NOT EXISTS (
        SELECT 1 FROM knowledge_graph_relation_sources AS source
        WHERE source.project_id = NEW.project_id
          AND source.graph_relation_id = NEW.id
          AND source.lifecycle_status = 'active'
    )) THEN
        RAISE EXCEPTION 'approved graph relation requires source lineage and current requires an active source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER knowledge_entity_candidates_approval_check
AFTER INSERT OR UPDATE ON knowledge_entity_candidates
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_knowledge_entity_approval();
CREATE CONSTRAINT TRIGGER knowledge_graph_entity_sources_context_check
AFTER INSERT OR UPDATE ON knowledge_graph_entity_sources
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_knowledge_entity_graph_source();
CREATE CONSTRAINT TRIGGER knowledge_relation_candidates_approval_check
AFTER INSERT OR UPDATE ON knowledge_relation_candidates
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_knowledge_relation_approval();
CREATE CONSTRAINT TRIGGER knowledge_graph_relation_sources_context_check
AFTER INSERT OR UPDATE ON knowledge_graph_relation_sources
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_knowledge_relation_graph_source();
CREATE CONSTRAINT TRIGGER knowledge_graph_entities_source_check
AFTER INSERT OR UPDATE ON knowledge_graph_entities
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_current_graph_entity_has_source();
CREATE CONSTRAINT TRIGGER knowledge_graph_relations_source_check
AFTER INSERT OR UPDATE ON knowledge_graph_relations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_current_graph_relation_has_source();

CREATE INDEX knowledge_entity_candidates_graph_fk_idx
ON knowledge_entity_candidates (graph_entity_id, project_id)
WHERE graph_entity_id IS NOT NULL;
CREATE INDEX knowledge_relation_candidates_graph_fk_idx
ON knowledge_relation_candidates (graph_relation_id, project_id)
WHERE graph_relation_id IS NOT NULL;
CREATE INDEX knowledge_graph_entities_project_status_idx
ON knowledge_graph_entities (project_id, status, entity_type, canonical_name, id);
CREATE INDEX knowledge_graph_entities_catalog_fk_idx
ON knowledge_graph_entities (catalog_entity_id, project_id)
WHERE catalog_entity_id IS NOT NULL;
CREATE INDEX knowledge_graph_entities_approver_idx
ON knowledge_graph_entities (approved_by, approved_at DESC);
CREATE INDEX knowledge_graph_entity_sources_graph_idx
ON knowledge_graph_entity_sources (
    graph_entity_id, project_id, lifecycle_status, created_at DESC
);
CREATE INDEX knowledge_graph_entity_sources_candidate_idx
ON knowledge_graph_entity_sources (
    entity_candidate_id, project_id, rag_revision_id, pipeline_run_id,
    source_id, document_id
);
CREATE INDEX knowledge_graph_entity_sources_revision_idx
ON knowledge_graph_entity_sources (
    rag_revision_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_graph_entity_sources_chunk_idx
ON knowledge_graph_entity_sources (
    chunk_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_graph_relations_project_status_idx
ON knowledge_graph_relations (project_id, status, predicate, id);
CREATE INDEX knowledge_graph_relations_subject_fk_idx
ON knowledge_graph_relations (subject_graph_entity_id, project_id);
CREATE INDEX knowledge_graph_relations_object_fk_idx
ON knowledge_graph_relations (object_graph_entity_id, project_id);
CREATE INDEX knowledge_graph_relations_approver_idx
ON knowledge_graph_relations (approved_by, approved_at DESC);
CREATE INDEX knowledge_graph_relation_sources_graph_idx
ON knowledge_graph_relation_sources (
    graph_relation_id, project_id, lifecycle_status, created_at DESC
);
CREATE INDEX knowledge_graph_relation_sources_candidate_idx
ON knowledge_graph_relation_sources (
    relation_candidate_id, project_id, rag_revision_id, pipeline_run_id,
    source_id, document_id, chunk_id
);
CREATE INDEX knowledge_graph_relation_sources_revision_idx
ON knowledge_graph_relation_sources (
    rag_revision_id, project_id, pipeline_run_id, source_id, document_id
);
CREATE INDEX knowledge_graph_relation_sources_chunk_idx
ON knowledge_graph_relation_sources (
    chunk_id, project_id, pipeline_run_id, source_id, document_id
);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'knowledge_rag_job_specs', 'knowledge_rag_revisions',
        'knowledge_fact_candidate_sources', 'knowledge_entity_candidates',
        'knowledge_entity_candidate_sources', 'knowledge_relation_candidates',
        'knowledge_rag_validation_findings', 'knowledge_graph_entities',
        'knowledge_graph_entity_sources', 'knowledge_graph_relations',
        'knowledge_graph_relation_sources'
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
    knowledge_rag_job_specs, knowledge_rag_revisions,
    knowledge_fact_candidate_sources, knowledge_entity_candidates,
    knowledge_entity_candidate_sources, knowledge_relation_candidates,
    knowledge_rag_validation_findings, knowledge_graph_entities,
    knowledge_graph_entity_sources, knowledge_graph_relations,
    knowledge_graph_relation_sources
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON
    knowledge_rag_job_specs, knowledge_rag_revisions,
    knowledge_fact_candidate_sources, knowledge_entity_candidates,
    knowledge_entity_candidate_sources, knowledge_relation_candidates,
    knowledge_rag_validation_findings, knowledge_graph_entities,
    knowledge_graph_entity_sources, knowledge_graph_relations,
    knowledge_graph_relation_sources
TO geo_app, geo_worker, geo_readonly;
GRANT INSERT ON
    knowledge_rag_job_specs, knowledge_rag_revisions,
    knowledge_fact_candidate_sources, knowledge_entity_candidates,
    knowledge_entity_candidate_sources, knowledge_relation_candidates,
    knowledge_rag_validation_findings
TO geo_worker;
GRANT UPDATE ON
    knowledge_rag_revisions, knowledge_entity_candidates,
    knowledge_relation_candidates, knowledge_graph_entities,
    knowledge_graph_entity_sources, knowledge_graph_relations,
    knowledge_graph_relation_sources
TO geo_worker;
GRANT INSERT, UPDATE ON
    knowledge_graph_entities, knowledge_graph_entity_sources,
    knowledge_graph_relations, knowledge_graph_relation_sources
TO geo_app;
GRANT UPDATE ON
    knowledge_rag_revisions, knowledge_entity_candidates,
    knowledge_relation_candidates
TO geo_app;

REVOKE ALL ON FUNCTION
    geo_protect_knowledge_source_revision(),
    geo_protect_knowledge_rag_revision(),
    geo_protect_knowledge_fact_candidate(),
    geo_require_active_fact_for_evidence(),
    geo_protect_knowledge_graph_candidate(),
    geo_protect_knowledge_graph_entity(),
    geo_protect_knowledge_graph_relation(),
    geo_protect_knowledge_graph_source(),
    geo_assert_knowledge_entity_approval(),
    geo_assert_knowledge_entity_graph_source(),
    geo_assert_knowledge_relation_approval(),
    geo_assert_knowledge_relation_graph_source(),
    geo_assert_current_graph_entity_has_source(),
    geo_assert_current_graph_relation_has_source()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_protect_knowledge_source_revision(),
    geo_protect_knowledge_rag_revision(),
    geo_protect_knowledge_fact_candidate(),
    geo_require_active_fact_for_evidence(),
    geo_protect_knowledge_graph_candidate(),
    geo_protect_knowledge_graph_entity(),
    geo_protect_knowledge_graph_relation(),
    geo_protect_knowledge_graph_source(),
    geo_assert_knowledge_entity_approval(),
    geo_assert_knowledge_entity_graph_source(),
    geo_assert_knowledge_relation_approval(),
    geo_assert_knowledge_relation_graph_source(),
    geo_assert_current_graph_entity_has_source(),
    geo_assert_current_graph_relation_has_source()
TO geo_app, geo_worker;
