export type KnowledgeProblem = { status?: number; detail: string; correlationId?: string };
export type KnowledgeResource<T> = { data: T; problem?: KnowledgeProblem };

export type KnowledgeSource = {
  id: string; project_id: string; source_kind: string; title: string;
  source_url: string | null; filename: string | null; media_type: string;
  status: string; content_hash: string | null; error_code: string | null;
  error_detail: string | null; content_bytes: number | null; created_at: string; updated_at: string;
};

export type KnowledgeRun = {
  id: string; project_id: string; source_id: string; source_title: string;
  status: string; input_hash: string; error_code: string | null; error_detail: string | null;
  started_at: string | null; completed_at: string | null; created_at: string;
  job_id: string | null; job_status: string | null;
};

export type KnowledgeStage = {
  id: string; pipeline_run_id: string; stage_key: string; ordinal: number; status: string;
  metrics: Record<string, unknown>; error_detail: string | null;
  started_at: string | null; completed_at: string | null;
};

export type KnowledgeChunk = {
  id: string; pipeline_run_id: string; source_id: string; source_title: string;
  document_id: string; chunk_index: number; text: string; text_hash: string;
  char_count: number; status: string; quality_flags: string[]; created_at: string;
};

export type KnowledgeFact = {
  id: string; pipeline_run_id: string; source_id: string; source_title: string;
  chunk_id: string; statement: string; statement_hash: string; status: string;
  reviewed_by: string | null; review_notes: string | null; reviewed_at: string | null; created_at: string;
};

export type KnowledgeFinding = {
  id: string; pipeline_run_id: string; source_id: string; source_title: string;
  chunk_id: string | null; finding_code: string; severity: string; status: string;
  message: string; details: Record<string, unknown>; created_at: string;
};

export type KnowledgeDashboard = {
  sources: number; succeeded_runs: number; failed_runs: number;
  active_chunks: number; pending_facts: number; open_findings: number;
};

export type KnowledgeWorkspaceData = {
  activeView: string;
  query: string;
  sources: KnowledgeResource<KnowledgeSource[]>;
  runs: KnowledgeResource<KnowledgeRun[]>;
  stages: KnowledgeResource<KnowledgeStage[]>;
  chunks: KnowledgeResource<KnowledgeChunk[]>;
  facts: KnowledgeResource<KnowledgeFact[]>;
  findings: KnowledgeResource<KnowledgeFinding[]>;
  dashboard: KnowledgeResource<KnowledgeDashboard>;
};

export type KnowledgeActionState = {
  kind: "idle" | "success" | "error";
  message: string;
  status?: number;
  correlationId?: string;
};
