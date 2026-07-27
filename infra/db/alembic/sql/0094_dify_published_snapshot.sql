CREATE TABLE dify_workflow_published_snapshots (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    release_id uuid NOT NULL,
    purpose text NOT NULL CHECK (purpose IN (
        'knowledge.question_generation',
        'knowledge.rag_grounding',
        'placements.generation',
        'placements.simulation'
    )),
    dify_app_id text NOT NULL CHECK (btrim(dify_app_id) <> ''),
    dify_workflow_id text NOT NULL CHECK (btrim(dify_workflow_id) <> ''),
    workflow_hash text NOT NULL CHECK (workflow_hash ~ '^[0-9a-f]{64}$'),
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    prompt_nodes jsonb NOT NULL CHECK (jsonb_typeof(prompt_nodes) = 'array'),
    input_variables jsonb NOT NULL CHECK (jsonb_typeof(input_variables) = 'array'),
    graph_nodes jsonb NOT NULL CHECK (jsonb_typeof(graph_nodes) = 'array'),
    published_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    CONSTRAINT dify_published_snapshots_project_key UNIQUE (
        id, project_id, release_id
    ),
    CONSTRAINT dify_published_snapshots_identity_key UNIQUE (
        project_id, release_id, purpose, dify_workflow_id, snapshot_hash
    ),
    CONSTRAINT dify_published_snapshots_release_fkey FOREIGN KEY (
        release_id, project_id
    ) REFERENCES dify_workflow_releases(id, project_id)
);

CREATE INDEX dify_published_snapshots_current_idx
ON dify_workflow_published_snapshots(project_id, purpose, observed_at DESC);

CREATE FUNCTION geo_reject_dify_snapshot_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Dify published workflow snapshots are append-only'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER dify_published_snapshots_immutable
BEFORE UPDATE OR DELETE ON dify_workflow_published_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_snapshot_mutation();

ALTER TABLE dify_workflow_published_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_published_snapshots FORCE ROW LEVEL SECURITY;

CREATE POLICY project_scope ON dify_workflow_published_snapshots
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON dify_workflow_published_snapshots FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON dify_workflow_published_snapshots TO geo_app, geo_worker;

ALTER TABLE dify_workflow_execution_attempts
ADD COLUMN published_snapshot_id uuid;

ALTER TABLE dify_workflow_execution_attempts
ADD CONSTRAINT dify_workflow_attempts_snapshot_fkey FOREIGN KEY (
    published_snapshot_id, project_id, release_id
) REFERENCES dify_workflow_published_snapshots(id, project_id, release_id);

CREATE INDEX dify_workflow_attempts_snapshot_idx
ON dify_workflow_execution_attempts(project_id, published_snapshot_id)
WHERE published_snapshot_id IS NOT NULL;

CREATE OR REPLACE FUNCTION geo_assert_dify_attempt_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'running' OR NEW.status NOT IN ('succeeded', 'failed')
       OR NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id
       OR NEW.release_id <> OLD.release_id OR NEW.job_id IS DISTINCT FROM OLD.job_id
       OR NEW.execution_kind <> OLD.execution_kind
       OR NEW.attempt_number <> OLD.attempt_number
       OR NEW.fencing_generation IS DISTINCT FROM OLD.fencing_generation
       OR NEW.published_snapshot_id IS DISTINCT FROM OLD.published_snapshot_id
       OR NEW.context_hash <> OLD.context_hash OR NEW.request_hash <> OLD.request_hash
       OR NEW.started_at <> OLD.started_at THEN
        RAISE EXCEPTION 'Dify attempt permits only one running-to-terminal transition'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;
