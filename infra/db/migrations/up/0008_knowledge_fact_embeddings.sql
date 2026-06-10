CREATE TABLE IF NOT EXISTS knowledge_fact_embeddings (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id uuid NOT NULL,
  knowledge_fact_id uuid NOT NULL REFERENCES localized_knowledge_facts(id) ON DELETE CASCADE,
  embedding_model text NOT NULL,
  embedding vector(8) NOT NULL,
  content_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(knowledge_fact_id, embedding_model)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_fact_embeddings_project
  ON knowledge_fact_embeddings(project_id, embedding_model, updated_at);
