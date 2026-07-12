ALTER TABLE project_launch_configs
  ALTER COLUMN config_version SET DEFAULT 'project_launch_config_v1',
  ALTER COLUMN locale SET DEFAULT 'en',
  ALTER COLUMN country_code SET DEFAULT 'GLOBAL',
  ALTER COLUMN timezone SET DEFAULT 'UTC',
  ALTER COLUMN scoring_profile SET DEFAULT 'visibility_v1.0';

ALTER TABLE score_weight_profiles
  ALTER COLUMN base_formula_version SET DEFAULT 'visibility_v1.0';

ALTER TABLE knowledge_pipeline_runs
  ALTER COLUMN market_code SET DEFAULT 'GLOBAL',
  ALTER COLUMN locale SET DEFAULT 'en';

ALTER TABLE knowledge_source_assets
  ALTER COLUMN market_code SET DEFAULT 'GLOBAL',
  ALTER COLUMN locale SET DEFAULT 'en';

ALTER TABLE knowledge_chunks
  ALTER COLUMN market_code SET DEFAULT 'GLOBAL',
  ALTER COLUMN locale SET DEFAULT 'en';

ALTER TABLE knowledge_fact_candidates
  ALTER COLUMN market_code SET DEFAULT 'GLOBAL',
  ALTER COLUMN locale SET DEFAULT 'en';

ALTER TABLE localized_knowledge_facts
  ALTER COLUMN locale SET DEFAULT 'en';

ALTER TABLE embedding_jobs
  ALTER COLUMN qdrant_collection SET DEFAULT 'geo_knowledge_chunks_bge_m3_v1';

UPDATE embedding_jobs
SET qdrant_collection = 'geo_knowledge_chunks_bge_m3_v1'
WHERE qdrant_collection = 'geo_knowledge_chunks';

CREATE TABLE IF NOT EXISTS knowledge_trace_refs_dedup_archive
  (LIKE knowledge_trace_refs INCLUDING DEFAULTS);

ALTER TABLE knowledge_trace_refs_dedup_archive
  ADD COLUMN IF NOT EXISTS archived_at timestamptz NOT NULL DEFAULT now();

INSERT INTO knowledge_trace_refs_dedup_archive
SELECT older.*, now()
FROM knowledge_trace_refs older
WHERE EXISTS (
  SELECT 1
  FROM knowledge_trace_refs newer
  WHERE older.id > newer.id
    AND older.project_id = newer.project_id
    AND older.source_type = newer.source_type
    AND older.source_id = newer.source_id
    AND older.target_type = newer.target_type
    AND older.target_id = newer.target_id
    AND older.trace_role = newer.trace_role
)
AND NOT EXISTS (
  SELECT 1
  FROM knowledge_trace_refs_dedup_archive archived
  WHERE archived.id = older.id
);

DELETE FROM knowledge_trace_refs older
USING knowledge_trace_refs newer
WHERE older.id > newer.id
  AND older.project_id = newer.project_id
  AND older.source_type = newer.source_type
  AND older.source_id = newer.source_id
  AND older.target_type = newer.target_type
  AND older.target_id = newer.target_id
  AND older.trace_role = newer.trace_role;

CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_trace_refs_unique_edge
  ON knowledge_trace_refs(project_id, source_type, source_id, target_type, target_id, trace_role);
