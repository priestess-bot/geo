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

export type FactEvidenceLineage = {
  project_id: string; pipeline_run_id: string; knowledge_source_id: string;
  knowledge_document_id: string; knowledge_chunk_id: string; knowledge_fact_id: string;
  evidence_item_id: string; evidence_title: string; promoted_by: string; promoted_at: string;
  idempotency_key: string; promotion_request_hash: string;
  lineage_contract_version: "legacy-relational-v1" | "knowledge-fact-evidence-v1";
  source_content_hash: string; document_cleaned_text_hash: string; chunk_text_hash: string;
  fact_statement_hash: string; evidence_snapshot_hash: string;
};

export type PromotedFactEvidence = {
  id: string; project_id: string; title: string; item_type: "approved_fact";
  subject_entity_id: string | null; subject_role: string;
  snapshot: { kind: "text" | "minio"; text: string | null; uri: string | null; sha256: string };
  source_revision: { kind: string; value: string };
  usage_rights: string; confidentiality: string;
  public_citation: {
    disclosure_allowed: boolean; source_url: string | null; source_title: string | null;
    label: string | null; quotation_allowed: boolean; attribution_required: boolean;
  };
  eligible_for_generation: boolean; eligible_for_publication: boolean; created_at: string;
};

export type FactEvidenceProposal = {
  project_id: string; promotable: boolean; blockers: string[];
  fact: {
    id: string; status: string; statement: string; statement_hash: string;
    reviewed_by: string | null; reviewed_at: string | null;
  };
  source: {
    id: string; title: string; source_kind: string; source_url: string | null;
    status: string; content_hash: string | null;
  };
  document: { id: string; parser_version: string; cleaned_text_hash: string };
  chunk: {
    id: string; chunk_index: number; text: string; text_hash: string; status: string;
  };
  existing: { evidence: PromotedFactEvidence; lineage: FactEvidenceLineage } | null;
  defaults: {
    title: string; source_url: string | null; source_title: string; citation_label: string;
  };
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
  selectedFactId: string;
  sources: KnowledgeResource<KnowledgeSource[]>;
  runs: KnowledgeResource<KnowledgeRun[]>;
  stages: KnowledgeResource<KnowledgeStage[]>;
  chunks: KnowledgeResource<KnowledgeChunk[]>;
  facts: KnowledgeResource<KnowledgeFact[]>;
  findings: KnowledgeResource<KnowledgeFinding[]>;
  dashboard: KnowledgeResource<KnowledgeDashboard>;
  evidenceProposal: KnowledgeResource<FactEvidenceProposal | null>;
};

export type KnowledgeActionState = {
  kind: "idle" | "success" | "error";
  message: string;
  status?: number;
  correlationId?: string;
};
