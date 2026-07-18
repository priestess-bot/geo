CREATE TABLE knowledge_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_kind text NOT NULL CHECK (source_kind IN ('url', 'file', 'text')),
    title text NOT NULL CHECK (btrim(title) <> ''),
    source_url text,
    filename text,
    media_type text NOT NULL CHECK (btrim(media_type) <> ''),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'ready', 'failed', 'archived')),
    raw_content bytea,
    content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
    error_code text,
    error_detail text,
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    CHECK (source_kind <> 'url' OR source_url IS NOT NULL),
    CHECK (source_kind = 'url' OR raw_content IS NOT NULL),
    CHECK (raw_content IS NULL OR octet_length(raw_content) <= 5242880)
);

CREATE TABLE knowledge_pipeline_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    error_code text,
    error_detail text,
    started_at timestamptz,
    completed_at timestamptz,
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (source_id, project_id) REFERENCES knowledge_sources(id, project_id),
    UNIQUE (id, project_id)
);

CREATE TABLE knowledge_pipeline_stages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    stage_key text NOT NULL CHECK (
        stage_key IN ('ingest', 'parse', 'clean', 'chunk', 'fact_extract', 'quality')
    ),
    ordinal integer NOT NULL CHECK (ordinal BETWEEN 1 AND 6),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metrics) = 'object'),
    error_detail text,
    started_at timestamptz,
    completed_at timestamptz,
    FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (pipeline_run_id, stage_key),
    UNIQUE (pipeline_run_id, ordinal)
);

CREATE TABLE knowledge_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    parser_version text NOT NULL CHECK (btrim(parser_version) <> ''),
    raw_text text NOT NULL,
    cleaned_text text NOT NULL,
    raw_text_hash text NOT NULL CHECK (raw_text_hash ~ '^[0-9a-f]{64}$'),
    cleaned_text_hash text NOT NULL CHECK (cleaned_text_hash ~ '^[0-9a-f]{64}$'),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (source_id, project_id) REFERENCES knowledge_sources(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (pipeline_run_id)
);

CREATE TABLE knowledge_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    text text NOT NULL CHECK (btrim(text) <> ''),
    text_hash text NOT NULL CHECK (text_hash ~ '^[0-9a-f]{64}$'),
    char_count integer NOT NULL CHECK (char_count > 0),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    quality_flags text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (source_id, project_id) REFERENCES knowledge_sources(id, project_id),
    FOREIGN KEY (document_id, project_id) REFERENCES knowledge_documents(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (document_id, chunk_index)
);

CREATE TABLE knowledge_fact_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    statement text NOT NULL CHECK (btrim(statement) <> ''),
    statement_hash text NOT NULL CHECK (statement_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'approved', 'rejected')),
    reviewed_by uuid REFERENCES identities(id),
    review_notes text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (source_id, project_id) REFERENCES knowledge_sources(id, project_id),
    FOREIGN KEY (chunk_id, project_id) REFERENCES knowledge_chunks(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (pipeline_run_id, statement_hash)
);

CREATE TABLE knowledge_quality_findings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    chunk_id uuid,
    finding_code text NOT NULL CHECK (btrim(finding_code) <> ''),
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'resolved')),
    message text NOT NULL CHECK (btrim(message) <> ''),
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (source_id, project_id) REFERENCES knowledge_sources(id, project_id),
    FOREIGN KEY (chunk_id, project_id) REFERENCES knowledge_chunks(id, project_id),
    UNIQUE (id, project_id)
);

CREATE TABLE knowledge_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    requested_by uuid NOT NULL REFERENCES identities(id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id),
    UNIQUE (job_id, project_id),
    UNIQUE (pipeline_run_id)
);

CREATE TRIGGER knowledge_job_spec_kind
BEFORE INSERT OR UPDATE ON knowledge_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('knowledge.process');

CREATE TRIGGER knowledge_documents_immutable
BEFORE UPDATE OR DELETE ON knowledge_documents
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX knowledge_sources_project_created_idx
ON knowledge_sources (project_id, created_at DESC, id DESC);
CREATE INDEX knowledge_runs_project_created_idx
ON knowledge_pipeline_runs (project_id, created_at DESC, id DESC);
CREATE INDEX knowledge_chunks_project_search_idx
ON knowledge_chunks (project_id, status, created_at DESC, id DESC);
CREATE INDEX knowledge_facts_project_status_idx
ON knowledge_fact_candidates (project_id, status, created_at DESC, id DESC);
CREATE INDEX knowledge_findings_project_severity_idx
ON knowledge_quality_findings (project_id, severity, created_at DESC, id DESC);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'knowledge_sources', 'knowledge_pipeline_runs', 'knowledge_pipeline_stages',
        'knowledge_documents', 'knowledge_chunks', 'knowledge_fact_candidates',
        'knowledge_quality_findings', 'knowledge_job_specs'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    knowledge_sources, knowledge_pipeline_runs, knowledge_pipeline_stages,
    knowledge_documents, knowledge_chunks, knowledge_fact_candidates,
    knowledge_quality_findings, knowledge_job_specs
TO geo_app, geo_worker;
GRANT SELECT ON
    knowledge_sources, knowledge_pipeline_runs, knowledge_pipeline_stages,
    knowledge_documents, knowledge_chunks, knowledge_fact_candidates,
    knowledge_quality_findings, knowledge_job_specs
TO geo_readonly;
