import { revalidatePath } from "next/cache";
import type { ReactNode } from "react";

type PageResponse<T> = {
  total_count: number;
  sort?: string;
  records: T[];
};

type RuntimeProject = {
  project: {
    id: string;
    name: string;
    market_code: string;
    industry_code: string;
    target_brand: string;
    category: string;
    prompt_version: string;
    status: string;
  };
  tenant: { id: string; name: string };
  brand: { id?: string; canonical_name: string; official_domains?: string[]; status?: string } | null;
  competitors: Array<{ id?: string; canonical_name: string; official_domains?: string[]; status?: string }>;
  prompt_count: number;
  audit_events: Array<{ event_type: string; method_version?: string | null }>;
};

type RuntimeProjectMember = {
  member: {
    id: string;
    project_id: string;
    user_id: string;
    role: string;
    created_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null; after_hash?: string | null }>;
};

type RuntimeProjectMemberInvitation = {
  invitation: {
    id: string;
    project_id: string;
    email: string;
    role: string;
    status: string;
    invite_token_hash?: string;
    invite_token?: string;
    invited_by?: string;
    expires_at?: string | null;
    accepted_at?: string | null;
    revoked_at?: string | null;
    created_at?: string;
    updated_at?: string;
    member?: { id?: string; user_id?: string; role?: string };
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null; after_hash?: string | null }>;
};

type RuntimeProjectLifecycleEvent = {
  lifecycle_event: {
    id?: string;
    project_id?: string;
    event_type?: string;
    actor_type?: string;
    actor_id?: string;
    target_id?: string;
    method_version?: string | null;
    reason?: string | null;
    created_at?: string | null;
    before_hash?: string | null;
    after_hash?: string | null;
    action?: string | null;
    status_before?: string | null;
    status_after?: string | null;
    changed_fields?: string[];
  };
  audit_events: Array<{ event_type?: string; method_version?: string | null; after_hash?: string | null }>;
};

type RuntimePrompt = {
  id: string;
  market_code: string;
  industry_code: string;
  text: string;
  intent_type: string;
  city: string;
  language: string;
  target_brand: string;
  competitors: string[];
  priority: number;
  intent_weight: number;
  prompt_version: string;
  status: string;
};

type RuntimePromptImportHistoryItem = {
  prompt_import: {
    id?: string;
    project_id?: string;
    actor_id?: string;
    source_format?: string;
    source_filename?: string | null;
    source_content_type?: string | null;
    csv_sha256?: string | null;
    prompt_count?: number;
    prompt_question_ids?: string[];
    method_version?: string | null;
    after_hash?: string | null;
    created_at?: string | null;
  };
  audit_events: Array<{ event_type?: string; method_version?: string | null; after_hash?: string | null; created_at?: string | null }>;
};

type EvidenceRun = {
  answer_run: {
    id: string;
    project_id?: string;
    prompt_question_id?: string;
    platform: string;
    surface: string;
    access_method?: string;
    market_code?: string;
    city: string;
    language?: string;
    device?: string;
    status: string;
    answer_present?: boolean;
    surface_triggered?: boolean;
    sample_index?: number;
    sample_size?: number;
    model_or_surface?: string;
    account_state?: string | null;
    collector_backend_id?: string;
    collector_version?: string;
    prompt_text?: string;
    prompt_intent_type?: string;
    prompt_priority?: number;
    prompt_version?: string;
    collected_at: string;
  };
  raw_answer?: {
    answer_text?: string;
    raw_payload_hash?: string;
  } | null;
  citations: Array<{ domain?: string; url?: string; source_type?: string; position?: number }>;
  evidence_assets: Array<{ asset_type?: string; url?: string; content_hash?: string | null }>;
  collector_logs: Array<{ event_type?: string; collector_backend_id?: string; payload?: Record<string, unknown> }>;
  collection_cost?: {
    total_cost?: number;
    llm_provider?: string;
    llm_tokens?: number;
    duration_ms?: number;
  } | null;
  audit_events: Array<{ event_type?: string; method_version?: string | null; target_type?: string }>;
};

type CollectionRun = {
  collection_run: {
    id: string;
    project_id?: string;
    run_type?: string;
    mode?: string;
    planned_runs?: number;
    attempted_runs?: number;
    success_count?: number;
    failure_count?: number;
    success_rate?: number;
    trigger_rate?: number;
    answer_present_rate?: number;
    total_cost?: number;
    average_cost_per_run?: number;
    total_duration_ms?: number;
    average_duration_ms?: number;
    collector_backend_ids?: string[];
    platform_distribution?: Record<string, number>;
    city_distribution?: Record<string, number>;
    access_method_distribution?: Record<string, number>;
    failure_summary?: Record<string, number>;
    answer_run_ids?: string[];
    started_at?: string;
    completed_at?: string;
    created_at?: string;
  };
  audit_events: Array<{ event_type?: string; method_version?: string | null; target_type?: string }>;
};

type ScoreSnapshot = {
  snapshot: {
    id?: string;
    final_score: number;
    trigger_rate: number;
    mention_rate: number;
    recommendation_rate: number;
    dispersion?: number;
    scope_type?: string;
    scope_value?: string;
    formula_version: string;
    component_weights_snapshot?: Record<string, number>;
  };
  contributions: Array<{
    id?: string;
    component_name: string;
    component_score: number;
    weight?: number;
    weighted_contribution: number;
    denominator?: string;
    evidence_answer_run_ids?: string[];
    positive_evidence_summary?: string;
    negative_evidence_summary?: string;
    confidence_note?: string;
  }>;
  answer_runs: Array<{
    answer_run: {
      id: string;
      platform?: string;
      city?: string;
      prompt_text?: string;
      prompt_intent_type?: string;
    };
    analysis?: {
      confidence?: number;
      parser_engine_id?: string;
      analysis_version?: string;
      payload?: {
        parser_comparison?: {
          secondary_parser_engine_id?: string;
          secondary_analysis_version?: string;
          secondary_prompt_version?: string;
          comparison_method_version?: string;
          agreement_rate?: number;
          mismatched_fields?: Record<string, unknown>;
          secondary_result?: {
            llm_call_log?: {
              provider?: string;
              model?: string;
              prompt_version?: string;
              total_tokens?: number;
              estimated_cost?: number;
              latency_ms?: number;
              status?: string;
              request_hash?: string;
            };
          };
        };
      } & Record<string, unknown>;
    } | null;
  }>;
  audit_events: Array<{ event_type?: string; method_version?: string | null }>;
};

type CitationGraph = {
  project_id: string;
  nodes: Array<{
    node: {
      id: string;
      source_url?: string;
      source_domain?: string;
      source_type?: string;
      topic?: string | null;
      source_gap_type?: string | null;
      answer_run_ids?: string[];
      citation_count?: number;
    };
    answer_runs: Array<{
      id: string;
      platform?: string;
      city?: string;
      prompt_text?: string;
      prompt_intent_type?: string;
    }>;
  }>;
  evidence_links: Array<{
    source_graph_id?: string;
    answer_run_id?: string;
    answer_citation_id?: string | null;
    relation_type?: string;
  }>;
  source_gaps: Array<{
    source_type: string;
    gap_type: string;
    observed_count?: number;
    expected_weight?: number;
    recommendation: string;
  }>;
  competitor_benchmarks: Array<{
    competitor_name: string;
    metric_scope?: string;
    payload?: {
      mention_count?: number;
      mention_rate?: number;
      recommendation_count?: number;
      citation_overlap_count?: number;
      local_relevance_average?: number;
    };
    answer_run_ids?: string[];
  }>;
};

type ReportExport = {
  report_export: {
    id: string;
    market_code?: string;
    report_version: string;
    report_type?: string;
    sample_size: number;
    prompt_version?: string;
    scoring_formula_version?: string;
    platform_weights_snapshot?: Record<string, number>;
    method_disclosure?: {
      google_coverage?: string;
      google_spike_gate?: {
        gate_status?: string;
        limited_coverage?: boolean;
      };
      api_browser_fidelity?: {
        status?: string;
        official_api_records?: number;
        browser_records?: number;
        comparable_prompt_city_pairs?: number;
        mismatch_count?: number;
        difference_rate?: number | null;
      };
      score_rate_denominators?: {
        definitions?: Record<
          string,
          {
            label?: string;
            numerator?: string;
            denominator?: string;
            formula?: string;
            note?: string;
          }
        >;
        evidence_denominators?: {
          attempted_records?: number;
          surface_triggered_records?: number;
        };
        evidence_trigger_rate?: number;
      };
      access_method_distribution?: Record<string, number>;
      platform_distribution?: Record<string, number>;
      evidence_asset_coverage?: {
        screenshot_records?: number;
        html_snapshot_records?: number;
      };
    };
    window_start?: string;
    window_end?: string;
    methodology_hash?: string;
    exported_at: string;
    markdown_url?: string | null;
    pdf_url?: string | null;
    csv_url?: string | null;
  };
  score_snapshots: Array<{
    final_score?: number;
    trigger_rate?: number;
    mention_rate?: number;
    recommendation_rate?: number;
    dispersion?: number;
    formula_version?: string;
  }>;
  answer_runs: Array<{
    id: string;
    prompt_text?: string;
    prompt_intent_type?: string;
    prompt_version?: string;
    platform?: string;
    surface?: string;
    access_method?: string;
    market_code?: string;
    city?: string;
    language?: string;
    device?: string;
    sample_index?: number;
    sample_size?: number;
    answer_present?: boolean;
    surface_triggered?: boolean;
    status?: string;
  }>;
  citation_graph?: CitationGraph | null;
  audit_events: Array<{
    event_type?: string;
    target_type?: string;
    actor_id?: string;
    method_version?: string | null;
    reason?: string | null;
  }>;
};

type ActionPlan = {
  retest_schedule: {
    id?: string;
    project_id?: string;
    prompt_version: string;
    sample_size?: number;
    offsets_days: number[];
    scheduled_dates?: string[];
    answer_run_ids?: string[];
    created_at?: string;
  };
  action_recommendations: Array<{
    id?: string;
    title: string;
    description?: string;
    priority: string;
    status: string;
    owner_id?: string;
    source_gap_type?: string | null;
    evidence_answer_run_ids?: string[];
    related_source_types?: string[];
    next_check_date?: string;
    created_at?: string;
  }>;
  retest_comparisons: Array<{
    id?: string;
    baseline_score?: number;
    retest_score?: number;
    score_delta: number;
    baseline_answer_run_ids?: string[];
    retest_answer_run_ids?: string[];
    trend: string;
    created_at?: string;
  }>;
  answer_runs: Array<{
    id: string;
    platform?: string;
    surface?: string;
    city?: string;
    access_method?: string;
    prompt_text?: string;
    prompt_intent_type?: string;
    prompt_version?: string;
    sample_index?: number;
    sample_size?: number;
    answer_present?: boolean;
    surface_triggered?: boolean;
  }>;
  audit_events: Array<{ event_type?: string; target_type?: string; method_version?: string | null }>;
};

type AuRetestSchedulerPlan = {
  plan_version: string;
  generated_at?: string;
  status: string;
  retest_scheduler_plan_ready: boolean;
  project_id: string;
  scope: {
    market_code?: string;
    locale?: string;
    industry_code?: string;
    prompt_version: string;
    prompt_count: number;
    platform_surfaces: string[];
    geo_cities: string[];
    sample_size: number;
    offsets_days: number[];
    window_count: number;
    planned_runs_per_window: number;
    total_planned_runs: number;
  };
  scheduler_policy: {
    scheduler_status?: string;
    execution_mode?: string;
    replay_key?: Record<string, unknown>;
    immutability_requirements?: string[];
  };
  timeline: Array<{
    id: string;
    label: string;
    offset_day: number;
    planned_runs: number;
    prompt_version: string;
    sample_size: number;
    platform_surfaces: string[];
    geo_cities: string[];
    commands?: Array<{ id?: string; shell_command?: string; output_path?: string }>;
    evidence_outputs?: string[];
  }>;
  verification_commands: Array<{ shell?: string }>;
  runtime_endpoints: Record<string, string>;
  current_boundary: {
    real_external_runs_completed?: boolean;
    temporal_scheduler_implemented?: boolean;
    requires_p0a_environment_ready?: boolean;
    requires_design_partner_ready_baseline?: boolean;
    notes?: string[];
  };
  retest_scheduler_plan_hash: string;
};

type AuRetestExecutionStatus = {
  status_version: string;
  generated_at?: string;
  status: string;
  execution_status_report_ready: boolean;
  retest_execution_ready: boolean;
  comparison_allowed: boolean;
  next_action: string;
  plan_summary: {
    prompt_version?: string;
    planned_runs_per_window?: number;
    total_planned_runs?: number;
    retest_scheduler_plan_hash?: string;
  };
  summary: {
    window_count: number;
    ready_window_count: number;
    ready_retest_window_count: number;
    missing_window_count: number;
    missing_artifact_count: number;
    baseline_ready: boolean;
    comparison_allowed: boolean;
    next_window_id?: string | null;
  };
  windows: Array<{
    id: string;
    label: string;
    offset_day: number;
    planned_runs: number;
    prompt_version: string;
    sample_size: number;
    window_ready: boolean;
    missing_artifact_count: number;
    payload?: {
      exists?: boolean;
      status?: string;
      path?: string;
      ready_for_design_partner?: boolean;
      hash_valid?: boolean;
    };
    manifest?: {
      exists?: boolean;
      status?: string;
      path?: string;
      ready_for_design_partner?: boolean;
      hash_valid?: boolean;
    };
    blocking_reasons?: string[];
  }>;
  runtime_endpoints: Record<string, string>;
  current_boundary: {
    real_external_runs_completed?: boolean;
    temporal_scheduler_implemented?: boolean;
    requires_p0a_environment_ready?: boolean;
    requires_design_partner_ready_baseline?: boolean;
    notes?: string[];
  };
  retest_execution_status_hash: string;
};

type RuntimeAlert = {
  alert: {
    id: string;
    project_id: string;
    alert_type: string;
    severity: string;
    title: string;
    summary?: string;
    metric_name?: string;
    metric_value?: number;
    threshold?: number;
    rule_version?: string;
    source?: string;
    source_id?: string;
    created_at?: string;
  };
  evidence_refs: Array<{ target_type?: string; target_id?: string }>;
  related_actions: Array<{
    id?: string;
    title?: string;
    priority?: string;
    status?: string;
    source_gap_type?: string | null;
  }>;
  management_events: Array<{
    id?: string;
    status?: string;
    updated_by?: string;
    note?: string | null;
    created_at?: string;
  }>;
  audit_events: Array<{ event_type?: string; method_version?: string | null; after_hash?: string | null }>;
};

type ContentEngine = {
  project_id?: string;
  knowledge_facts: Array<{
    id: string;
    market_code?: string;
    fact_type?: string;
    subject?: string;
    predicate?: string;
    object_value?: string;
    city?: string | null;
    evidence_source_id?: string | null;
    confidence?: number;
    status?: string;
  }>;
  content_drafts: Array<{
    draft: {
      id?: string;
      title: string;
      content_type?: string;
      content_template_id?: string;
      target_city: string;
      target_platform?: string;
      target_source_type?: string;
      source_gap_types?: string[];
      evidence_answer_run_ids?: string[];
      draft_markdown?: string;
      review_status: string;
      created_by?: string;
      created_at?: string;
    };
    target_questions: Array<{ text: string; intent_type?: string; city?: string }>;
    knowledge_facts: Array<{
      id: string;
      market_code?: string;
      fact_type?: string;
      object_value?: string;
      confidence?: number;
    }>;
    answer_runs: Array<{
      id: string;
      platform?: string;
      city?: string;
      prompt_text?: string;
      prompt_intent_type?: string;
    }>;
    action_recommendation?: {
      title?: string;
      priority?: string;
      status?: string;
      source_gap_type?: string | null;
    } | null;
    manual_distribution_records: Array<{
      platform?: string;
      target_url?: string;
      status?: string;
      submitted_at?: string | null;
      checked_at?: string | null;
      notes?: string;
    }>;
    audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null; created_at?: string | null }>;
  }>;
  integration_connectors: Array<{
    provider: string;
    connection_status: string;
    capabilities?: string[];
    auth_mode?: string;
  }>;
  manual_distribution_records: Array<{ platform?: string; status?: string; target_url?: string; notes?: string }>;
  audit_events: Array<{ event_type?: string; target_type?: string; method_version?: string | null }>;
};

type TraceabilityDetail = {
  traceability_bundle: {
    explanation_summary: string;
    report_export_ids: string[];
    score_snapshot_ids: string[];
    score_contribution_ids: string[];
    answer_run_ids: string[];
    raw_answer_ids: string[];
    answer_citation_ids: string[];
    evidence_asset_ids: string[];
    source_graph_ids: string[];
    source_gap_types: string[];
    action_recommendation_ids: string[];
    content_draft_ids: string[];
    audit_event_ids: string[];
  };
  report_exports: Array<{ id?: string; report_version: string }>;
  score_snapshots: ScoreSnapshot[];
  evidence_runs: EvidenceRun[];
  action_recommendations: Array<{
    id?: string;
    title: string;
    priority: string;
    status: string;
    source_gap_type?: string | null;
  }>;
  content_drafts: Array<{
    draft: { id?: string; title: string; review_status: string; target_city?: string; target_platform?: string };
    target_questions?: Array<{ text: string }>;
    answer_runs?: Array<{ prompt_text?: string; platform?: string; city?: string }>;
  }>;
  audit_events: Array<{ event_type: string; target_type: string; method_version?: string | null }>;
  evidence_links: Array<{
    source_type: string;
    target_type: string;
    relation_type: string;
    answer_run_ids: string[];
  }>;
};

type RuntimeAuditEvent = {
  audit_event: {
    id?: string;
    project_id?: string;
    event_type?: string;
    actor_type?: string;
    actor_id?: string;
    target_type?: string;
    target_id?: string;
    method_version?: string | null;
    reason?: string | null;
    before_hash?: string | null;
    after_hash?: string | null;
    created_at?: string | null;
  };
};

type RuntimeData = {
  launchStatus: AuLaunchStatus | null;
  launchRemediationPlan: AuLaunchRemediationPlan | null;
  p0aEnvironmentChecklist: AuP0aEnvironmentChecklist | null;
  p0aExecutionChecklist: AuP0aExecutionChecklist | null;
  p0aCredentialRequest: AuP0aCredentialRequest | null;
  p0aCredentialFulfillment: AuP0aCredentialFulfillment | null;
  p0aCredentialClearance: AuP0aCredentialClearance | null;
  p0aRealBatchRequest: AuP0aRealBatchRequest | null;
  p0aRealBatchFulfillment: AuP0aRealBatchFulfillment | null;
  p0aRealBatchClearance: AuP0aRealBatchClearance | null;
  p0bGoogleExecutionChecklist: AuP0bGoogleExecutionChecklist | null;
  p0bGoogleEnvironmentRequest: AuP0bGoogleEnvironmentRequest | null;
  p0bGoogleEnvironmentFulfillment: AuP0bGoogleEnvironmentFulfillment | null;
  p0bGoogleEnvironmentClearance: AuP0bGoogleEnvironmentClearance | null;
  p0bGoogleManualBackfillRequest: AuP0bGoogleManualBackfillRequest | null;
  p0bGoogleManualBackfillFulfillment: AuP0bGoogleManualBackfillFulfillment | null;
  p0bGoogleManualBackfillClearance: AuP0bGoogleManualBackfillClearance | null;
  p0bGooglePhaseExecutionRequest: AuP0bGooglePhaseExecutionRequest | null;
  p0bGooglePhaseExecutionFulfillment: AuP0bGooglePhaseExecutionFulfillment | null;
  p0bGooglePhaseExecutionClearance: AuP0bGooglePhaseExecutionClearance | null;
  externalDependencyHandoff: AuExternalDependencyHandoff | null;
  externalDependencyClearance: AuExternalDependencyClearance | null;
  broaderPlatformRegistry: AuBroaderPlatformRegistry | null;
  retestSchedulerPlan: AuRetestSchedulerPlan | null;
  retestExecutionStatus: AuRetestExecutionStatus | null;
  handoffDossier: AuHandoffDossier | null;
  customerHandoffReadiness: AuCustomerHandoffReadiness | null;
  customerHandoffClearance: AuCustomerHandoffClearance | null;
  nextWorkItemPacket: AuNextWorkItemPacket | null;
  deliveryProgress: AuDeliveryProgress | null;
  projects: PageResponse<RuntimeProject>;
  projectLifecycleEvents: PageResponse<RuntimeProjectLifecycleEvent>;
  auditEvents: PageResponse<RuntimeAuditEvent>;
  projectMembers: PageResponse<RuntimeProjectMember>;
  projectMemberInvitations: PageResponse<RuntimeProjectMemberInvitation>;
  brandKit: RuntimeProjectBrandKit | null;
  brandAssets: PageResponse<RuntimeProjectBrandAssetVersion>;
  brandAssetLibrary: PageResponse<RuntimeProjectBrandAsset>;
  scoreWeights: RuntimeScoreWeightConfig | null;
  scoreFormulas: RuntimeScoreFormulaCatalog;
  humanReviews: PageResponse<RuntimeHumanReview>;
  humanReviewQueue: PageResponse<RuntimeHumanReviewQueueItem>;
  knowledgeSearch: RuntimeKnowledgeSearch | null;
  prompts: PageResponse<RuntimePrompt>;
  promptImports: PageResponse<RuntimePromptImportHistoryItem>;
  evidence: PageResponse<EvidenceRun>;
  questionEvidence: PageResponse<EvidenceRun>;
  collectionRuns: PageResponse<CollectionRun>;
  fidelityChecks: PageResponse<RuntimeFidelityCheck>;
  fidelityTrend: RuntimeFidelityTrend | null;
  entityAliases: PageResponse<RuntimeEntityAlias>;
  entityAliasCandidates: PageResponse<RuntimeEntityAliasCandidate>;
  entityAliasCandidateReviews: PageResponse<RuntimeEntityAliasCandidateReview>;
  entityAliasAssignmentQueue: PageResponse<RuntimeEntityAliasCandidateReview>;
  entityAliasAssignmentStats: RuntimeEntityAliasCandidateAssignmentQueueStats;
  entityAliasAssignmentWorkbench: RuntimeEntityAliasAssignmentWorkbench;
  entityAliasAssignmentWorkload: RuntimeEntityAliasAssignmentWorkloadSummary;
  entityAliasAssignmentDispatchPlan: RuntimeEntityAliasAssignmentDispatchPlan;
  savedViews: PageResponse<RuntimeSavedView>;
  scores: PageResponse<ScoreSnapshot>;
  graphs: PageResponse<CitationGraph>;
  reports: PageResponse<ReportExport>;
  reportJobs: PageResponse<RuntimeReportExportJob>;
  reportJobStats: RuntimeReportExportJobQueueStats;
  notifications: RuntimeNotificationPage;
  notificationSubscriptions: PageResponse<RuntimeNotificationSubscription>;
  notificationDeliveries: PageResponse<RuntimeNotificationDelivery>;
  notificationEmailFeedback: PageResponse<RuntimeNotificationEmailFeedback>;
  notificationEmailSuppressions: PageResponse<RuntimeNotificationEmailSuppression>;
  actions: PageResponse<ActionPlan>;
  alerts: PageResponse<RuntimeAlert>;
  content: PageResponse<ContentEngine>;
  traceability: TraceabilityDetail | null;
};

type RuntimePaths = Record<keyof typeof endpoints, string> & {
  questionEvidence: string;
};

type AuLaunchStatus = {
  launch_status_version: string;
  generated_at: string;
  status: string;
  ready_for_customer_report_handoff: boolean;
  next_action: string;
  remaining_blockers: string[];
  launch_status_hash: string;
  p0a_design_partner?: {
    status?: string;
    ready_for_design_partner?: boolean;
    next_action?: string;
    completion?: {
      completion_percent?: number;
      design_ready_artifact_percent?: number;
    };
    remaining_blockers?: string[];
  };
  p0b_google?: {
    status?: string;
    google_main_scoring_allowed?: boolean;
    limited_coverage?: boolean;
    next_action?: string;
    remaining_blockers?: string[];
    package_summary?: {
      artifact_count?: number;
      missing_artifacts?: string[];
      failed_artifacts?: string[];
      ready_artifacts?: string[];
    };
  };
  p0c_customer_report?: {
    status?: string;
    report_contract_version?: string;
    google_coverage?: string;
    audit_event_count?: number;
    checks?: Record<string, boolean>;
    errors?: string[];
  };
};

type AuLaunchRemediationPlan = {
  remediation_plan_version: string;
  generated_at: string;
  status: string;
  remediation_plan_ready: boolean;
  next_work_item_id: string;
  remediation_plan_hash: string;
  summary?: {
    blocker_count?: number;
    covered_blocker_count?: number;
    unmapped_blocker_count?: number;
    work_item_count?: number;
    external_dependency_blocker_count?: number;
    runnable_now_work_item_count?: number;
    runnable_now_work_items?: string[];
    unmapped_blockers?: string[];
  };
  work_items?: Array<{
    id: string;
    stage?: string;
    title?: string;
    status?: string;
    external_dependency?: boolean;
    dependency_class?: string;
    commands?: Array<{ shell?: string }>;
    verification_commands?: Array<{ shell?: string }>;
    evidence_outputs?: string[];
    clears_blockers?: string[];
    blocker_count?: number;
    acceptance?: string;
  }>;
  blocker_remediations?: Array<{
    blocker?: string;
    work_item_id?: string;
    mapped?: boolean;
    next_command?: string;
    dependency_class?: string;
  }>;
};

type AuP0aEnvironmentChecklist = {
  environment_checklist_version: string;
  generated_at: string;
  status: string;
  environment_checklist_ready: boolean;
  next_action: string;
  environment_checklist_hash: string;
  summary?: {
    required_count?: number;
    required_present_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    recommended_count?: number;
    missing_recommended_count?: number;
    missing_recommended?: string[];
    runbook_verifier_status?: string;
    environment_verifier_status?: string;
    environment_report_ready?: boolean;
    env_file_hygiene_ready?: boolean;
    env_file_hygiene_error_count?: number;
    env_file_hygiene_warning_count?: number;
  };
  required_environment?: Array<{
    name?: string;
    required?: boolean;
    present?: boolean;
    source?: string;
    value_length?: number;
    sha256_prefix?: string;
    secret_redacted?: boolean;
    action?: string;
  }>;
  recommended_environment?: Array<{
    name?: string;
    required?: boolean;
    present?: boolean;
    source?: string;
    value_length?: number;
    sha256_prefix?: string;
    secret_redacted?: boolean;
    action?: string;
  }>;
  verification_commands?: Array<{ id?: string; shell?: string; purpose?: string }>;
  evidence_outputs?: string[];
};

type AuP0bGoogleExecutionChecklist = {
  execution_checklist_version: string;
  generated_at: string;
  status: string;
  google_execution_checklist_ready: boolean;
  google_main_scoring_allowed: boolean;
  limited_coverage: boolean;
  next_action: string;
  google_execution_checklist_hash: string;
  summary?: {
    planned_runs?: number;
    step_count?: number;
    missing_required_environment_count?: number;
    missing_required_environment?: string[];
    missing_full_run_required_environment_count?: number;
    missing_full_run_required_environment?: string[];
    missing_selector_group_count?: number;
    missing_selector_groups?: string[];
    missing_dependency_count?: number;
    missing_dependencies?: string[];
    file_gate_issue_count?: number;
    file_gate_issues?: string[];
    env_file_hygiene_ready?: boolean;
    env_file_hygiene_error_count?: number;
    env_file_hygiene_warning_count?: number;
    environment_handoff_ready?: boolean;
    environment_handoff_missing_required_count?: number;
    environment_handoff_missing_required?: string[];
    environment_handoff_target_env_file?: string;
    environment_handoff_setup_command_count?: number;
    environment_handoff_verification_command_count?: number;
    environment_handoff_secret_redacted?: boolean;
    manual_backfill_handoff_ready?: boolean;
    manual_backfill_handoff_status?: string;
    manual_backfill_handoff_expected_record_count?: number;
    manual_backfill_handoff_record_count?: number;
    manual_backfill_handoff_expected_prompt_city_count?: number;
    manual_backfill_handoff_covered_prompt_city_count?: number;
    manual_backfill_handoff_missing_reason_count?: number;
    manual_backfill_handoff_missing_reasons?: string[];
    manual_backfill_handoff_template_path?: string;
    manual_backfill_handoff_verification_path?: string;
    manual_backfill_handoff_content_redacted?: boolean;
    google_spike_phase_handoff_ready?: boolean;
    google_spike_phase_handoff_next_phase?: string;
    google_spike_phase_handoff_ready_phase_count?: number;
    google_spike_phase_handoff_blocked_phase_count?: number;
    google_spike_phase_handoff_full_spike_planned_runs?: number;
    google_spike_phase_order?: string[];
    remaining_blocker_count?: number;
    remaining_blockers?: string[];
    runbook_verifier_status?: string;
    playwright_env_verifier_status?: string;
    status_verifier_status?: string;
    package_verifier_status?: string;
  };
  verification_commands?: Array<{ id?: string; shell?: string; purpose?: string }>;
  evidence_outputs?: string[];
};

type AuP0aExecutionChecklist = {
  execution_checklist_version: string;
  generated_at: string;
  status: string;
  p0a_execution_checklist_ready: boolean;
  ready_for_design_partner: boolean;
  next_action: string;
  p0a_execution_checklist_hash: string;
  summary?: {
    small_batch_planned_runs?: number;
    full_batch_planned_runs?: number;
    step_count?: number;
    artifact_count?: number;
    missing_artifact_count?: number;
    missing_artifacts?: string[];
    failed_artifact_count?: number;
    failed_artifacts?: string[];
    ready_artifact_count?: number;
    remaining_blocker_count?: number;
    remaining_blockers?: string[];
    completion_percent?: number;
    design_ready_artifact_percent?: number;
    runbook_verifier_status?: string;
    environment_verifier_status?: string;
    runbook_execution_verifier_status?: string;
    package_verifier_status?: string;
    status_verifier_status?: string;
    credential_handoff_ready?: boolean;
    credential_handoff_missing_required_count?: number;
    credential_handoff_missing_required?: string[];
    credential_handoff_target_env_file?: string;
    credential_handoff_setup_command_count?: number;
    credential_handoff_verification_command_count?: number;
    credential_handoff_secret_redacted?: boolean;
    real_batch_phase_handoff_ready?: boolean;
    real_batch_phase_handoff_next_phase?: string;
    real_batch_phase_handoff_ready_phase_count?: number;
    real_batch_phase_handoff_blocked_phase_count?: number;
    real_batch_phase_handoff_total_planned_runs?: number;
  };
  real_batch_phase_handoff?: {
    ready?: boolean;
    next_phase?: string;
    ready_phase_count?: number;
    blocked_phase_count?: number;
    total_planned_runs?: number;
    phase_order?: string[];
  };
  verification_commands?: Array<{ id?: string; shell?: string; purpose?: string }>;
  evidence_outputs?: string[];
};

type AuBroaderPlatformRegistry = {
  registry_version: string;
  generated_at: string;
  status: string;
  broader_platform_registry_ready: boolean;
  broader_platform_registry_hash: string;
  summary?: {
    candidate_count?: number;
    registered_candidate_count?: number;
    enabled_candidate_count?: number;
    disabled_candidate_count?: number;
    stage_counts?: Record<string, number>;
    role_counts?: Record<string, number>;
    p0a_enabled_platform_surfaces?: string[];
    p0b_platform_surfaces?: string[];
    candidate_platform_surfaces?: string[];
    adapter_status_counts?: Record<string, number>;
  };
  candidate_platforms?: Array<{
    id: string;
    platform: string;
    surface: string;
    build_stage: string;
    platform_role: string;
    default_weight: number;
    enabled: boolean;
    priority: number;
    access_methods?: string[];
    adapter_status?: string;
    required_environment?: string[];
    evidence_requirements?: string[];
    scoring_policy?: string;
    source_signal_types?: string[];
    next_work_item?: string;
    market_profile_registered?: boolean;
  }>;
  recommended_sequence?: string[];
  current_boundary?: string[];
};

type AuHandoffDossier = {
  handoff_dossier_version: string;
  generated_at: string;
  status: string;
  handoff_dossier_ready: boolean;
  ready_for_customer_report_handoff: boolean;
  handoff_dossier_hash: string;
  summary?: {
    handoff_posture?: string;
    next_action?: string;
    next_work_item_id?: string;
    remaining_blocker_count?: number;
    covered_blocker_count?: number;
    unmapped_blocker_count?: number;
    work_item_count?: number;
    external_dependency_blocker_count?: number;
    p0a_execution_checklist_ready?: boolean;
    p0a_execution_remaining_blocker_count?: number;
    p0a_credential_handoff_ready?: boolean;
    p0a_credential_handoff_missing_required_count?: number;
    p0a_credential_handoff_secret_redacted?: boolean;
    p0a_real_batch_phase_handoff_ready?: boolean;
    p0a_real_batch_phase_handoff_next_phase?: string;
    p0a_real_batch_phase_handoff_blocked_phase_count?: number;
    p0a_env_file_hygiene_ready?: boolean;
    p0a_env_file_hygiene_error_count?: number;
    p0a_env_file_hygiene_warning_count?: number;
    p0b_google_execution_checklist_ready?: boolean;
    p0b_google_remaining_blocker_count?: number;
    p0b_google_env_file_hygiene_ready?: boolean;
    p0b_google_env_file_hygiene_error_count?: number;
    p0b_google_env_file_hygiene_warning_count?: number;
    p0b_google_environment_handoff_ready?: boolean;
    p0b_google_environment_handoff_missing_required_count?: number;
    p0b_google_environment_handoff_secret_redacted?: boolean;
    p0b_google_manual_backfill_handoff_ready?: boolean;
    p0b_google_manual_backfill_handoff_expected_record_count?: number;
    p0b_google_manual_backfill_handoff_record_count?: number;
    p0b_google_manual_backfill_handoff_missing_reason_count?: number;
    p0b_google_manual_backfill_handoff_content_redacted?: boolean;
    p0b_google_spike_phase_handoff_ready?: boolean;
    p0b_google_spike_phase_handoff_next_phase?: string;
    p0b_google_spike_phase_handoff_blocked_phase_count?: number;
    p0b_google_spike_phase_handoff_full_spike_planned_runs?: number;
  };
  markdown_report?: {
    path?: string;
    size_bytes?: number;
    content_sha256?: string;
    media_type?: string;
  };
  customer_handoff_readiness_audit?: {
    audit_version?: string;
    customer_report_handoff_ready?: boolean;
    customer_report_handoff_readiness_percent?: number;
    customer_ready_gate_count?: number;
    customer_total_gate_count?: number;
    blocked_customer_gate_count?: number;
    blocked_customer_gate_ids?: string[];
    structural_auditability_percent?: number;
    structural_ready_gate_count?: number;
    structural_total_gate_count?: number;
    next_action?: string;
    next_work_item_id?: string;
    remaining_blocker_count?: number;
    external_dependency_blocker_count?: number;
    readiness_statement?: string;
  };
  runtime_endpoints?: {
    launch_status?: string;
    launch_remediation_plan?: string;
    p0a_environment_checklist?: string;
    p0a_execution_checklist?: string;
    p0b_google_execution_checklist?: string;
    project_lifecycle_events?: string;
    project_lifecycle_events_export?: string;
    runtime_audit_events?: string;
    runtime_audit_events_export?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
  };
  next_work_item?: {
    id?: string;
    stage?: string;
    title?: string;
    dependency_class?: string;
    blocker_count?: number;
    commands?: string[];
    verification_commands?: string[];
  };
};

type AuCustomerHandoffReadiness = {
  customer_handoff_readiness_version: string;
  generated_at: string;
  status: string;
  readiness_audit_ready: boolean;
  ready_for_customer_report_handoff: boolean;
  customer_handoff_readiness_hash: string;
  summary?: {
    customer_report_handoff_readiness_percent?: number;
    structural_auditability_percent?: number;
    customer_ready_gate_count?: number;
    customer_total_gate_count?: number;
    blocked_customer_gate_count?: number;
    blocked_customer_gate_ids?: string[];
    structural_ready_gate_count?: number;
    structural_total_gate_count?: number;
    next_action?: string;
    next_work_item_id?: string;
    remaining_blocker_count?: number;
    external_dependency_blocker_count?: number;
    readiness_statement?: string;
  };
  source_handoff_dossier?: {
    handoff_dossier_hash?: string;
    handoff_dossier_ready?: boolean;
    ready_for_customer_report_handoff?: boolean;
    path?: string;
  };
  readiness_audit?: {
    audit_version?: string;
    customer_gates?: Array<{
      id?: string;
      label?: string;
      stage?: string;
      ready?: boolean;
      status?: string;
      next_action?: string;
      evidence_ref?: string;
    }>;
    structural_gates?: Array<{
      id?: string;
      label?: string;
      ready?: boolean;
      status?: string;
      evidence_ref?: string;
    }>;
  };
  runtime_endpoints?: {
    customer_handoff_readiness?: string;
    handoff_dossier?: string;
    launch_status?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
  };
  hard_gate_commands?: string[];
};

type AuDeliveryProgress = {
  delivery_progress_version: string;
  generated_at: string;
  status: string;
  delivery_progress_ready: boolean;
  ready_for_customer_report_handoff: boolean;
  delivery_progress_hash: string;
  summary?: {
    engineering_progress_percent?: number;
    customer_report_handoff_readiness_percent?: number;
    structural_auditability_percent?: number;
    ready_progress_gate_count?: number;
    total_progress_gate_count?: number;
    blocked_progress_gate_count?: number;
    blocked_progress_gate_ids?: string[];
    blocked_customer_gate_count?: number;
    blocked_customer_gate_ids?: string[];
    remaining_blocker_count?: number;
    external_dependency_blocker_count?: number;
    next_action?: string;
    next_work_item_id?: string;
    next_work_item_title?: string;
    next_work_item_stage?: string;
    next_command?: string;
    current_clearance_step_id?: string;
    would_execute_step_count?: number;
    external_dependency_handoff_ready?: boolean;
    handoff_posture?: string;
    launch_status_hash?: string;
    handoff_dossier_hash?: string;
    customer_handoff_readiness_hash?: string;
    next_work_item_packet_hash?: string;
    external_dependency_handoff_hash?: string;
    clearance_execution_hash?: string;
  };
  progress_gates?: Array<{
    id?: string;
    label?: string;
    ready?: boolean;
    status?: string;
    source?: string;
    evidence_ref?: string;
    customer_gate_ids?: string[];
    blocking_reasons?: string[];
  }>;
  runtime_endpoints?: {
    delivery_progress?: string;
    launch_status?: string;
    handoff_dossier?: string;
    customer_handoff_readiness?: string;
    next_work_item?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
  };
  hard_gate_commands?: string[];
};

type AuCustomerHandoffClearance = {
  customer_handoff_clearance_version: string;
  generated_at: string;
  status: string;
  customer_handoff_clearance_packet_ready: boolean;
  customer_handoff_ready: boolean;
  customer_handoff_clearance_ready: boolean;
  ready_for_report_export_handoff: boolean;
  blocked_by_prerequisite_step: boolean;
  customer_handoff_clearance_hash: string;
  summary?: {
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    blocking_reason_count?: number;
    blocking_reasons?: string[];
    customer_report_handoff_readiness_percent?: number;
    engineering_progress_percent?: number;
    structural_auditability_percent?: number;
    customer_gate_count?: number;
    ready_customer_gate_count?: number;
    blocked_customer_gate_count?: number;
    blocked_customer_gate_ids?: string[];
    blocked_progress_gate_ids?: string[];
    prerequisite_step_ids?: string[];
    prerequisite_steps_ready?: boolean;
    current_global_clearance_step_id?: string;
    target_clearance_step_id?: string;
    target_clearance_step_can_start?: boolean;
    target_clearance_step_ready?: boolean;
    customer_handoff_clearance_ready?: boolean;
    ready_for_report_export_handoff?: boolean;
    next_action?: string;
    next_command?: string;
    operator_step_count?: number;
    post_update_validation_command_count?: number;
    handoff_dossier_hash?: string;
    customer_handoff_readiness_hash?: string;
    delivery_progress_hash?: string;
    external_dependency_handoff_hash?: string;
    clearance_execution_hash?: string;
  };
  clearance_step?: {
    id?: string;
    step_ready?: boolean;
    step_can_start?: boolean;
    step_status?: string;
    blocked_by?: string[];
    strict_gate_command?: string;
  };
  prerequisite_steps?: Array<{
    id?: string;
    ready?: boolean;
    status?: string;
    blocked_by?: string[];
    runtime_endpoint?: string;
  }>;
  customer_handoff_clearance_items?: Array<{
    key?: string;
    gate_id?: string;
    title?: string;
    stage?: string;
    fulfilled?: boolean;
    ready?: boolean;
    status?: string;
    evidence_ref?: string;
    blocking_reasons?: string[];
  }>;
  operator_steps?: Array<{ order?: number; id?: string; command?: string; purpose?: string; blocked?: boolean }>;
  post_update_validation_sequence?: string[];
  runtime_endpoints?: {
    customer_handoff_clearance?: string;
    handoff_dossier?: string;
    customer_handoff_readiness?: string;
    delivery_progress?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
  };
  hard_gate_commands?: string[];
};

type AuNextWorkItemPacket = {
  next_work_item_packet_version: string;
  generated_at: string;
  status: string;
  next_work_item_packet_ready: boolean;
  ready_for_customer_report_handoff: boolean;
  next_work_item_packet_hash: string;
  summary?: {
    next_work_item_id?: string;
    next_action?: string;
    stage?: string;
    title?: string;
    status?: string;
    dependency_class?: string;
    external_dependency?: boolean;
    blocker_count?: number;
    remaining_blocker_count?: number;
    external_dependency_blocker_count?: number;
    customer_report_handoff_readiness_percent?: number;
    structural_auditability_percent?: number;
    runnable_now?: boolean;
    command_count?: number;
    verification_command_count?: number;
    evidence_output_count?: number;
    work_item_command_count?: number;
    work_item_verification_command_count?: number;
    work_item_evidence_output_count?: number;
    group_command_count?: number;
    group_verification_command_count?: number;
    group_evidence_output_count?: number;
    blocked_customer_gate_count?: number;
    blocked_customer_gate_ids?: string[];
    linked_dependency_group_id?: string;
    linked_dependency_group_status?: string;
    linked_dependency_group_next_command?: string;
    linked_dependency_group_blocking_reason_count?: number;
    linked_request_packet_id?: string;
    linked_request_artifact_type?: string;
    linked_request_packet_hash?: string;
    linked_request_packet_exists?: boolean;
    recommended_sequence_count?: number;
    request_packet_hash_available?: boolean;
  };
  source_handoff_dossier?: {
    handoff_dossier_hash?: string;
    handoff_dossier_ready?: boolean;
    ready_for_customer_report_handoff?: boolean;
    path?: string;
  };
  handoff_dossier_verifier?: {
    status?: string;
    hash_valid?: boolean;
    handoff_dossier_hash?: string;
    handoff_posture?: string;
    remaining_blocker_count?: number;
    work_item_count?: number;
    next_work_item_id?: string;
  };
  next_work_item?: {
    id?: string;
    stage?: string;
    title?: string;
    status?: string;
    external_dependency?: boolean;
    dependency_class?: string;
    blocker_count?: number;
  };
  execution_context?: {
    execution_context_version?: string;
    linked_dependency_group_id?: string;
    linked_dependency_group?: {
      id?: string;
      source?: string;
      source_path?: string;
      source_external_dependency_handoff_hash?: string;
      status?: string;
      dependency_class?: string;
      ready?: boolean;
      target_env_file?: string;
      next_command?: string;
      commands?: string[];
      verification_commands?: string[];
      evidence_outputs?: string[];
      command_count?: number;
      verification_command_count?: number;
      evidence_output_count?: number;
      blocking_reason_count?: number;
      blocking_reasons?: string[];
    };
    linked_request_packet?: {
      request_packet_id?: string;
      request_packet_title?: string;
      artifact_type?: string;
      output_path?: string;
      exists?: boolean;
      hash_field?: string;
      packet_hash?: string;
      build_command?: string;
      verify_command?: string;
      strict_gate_command?: string;
      runtime_endpoint?: string;
    };
    work_item_commands?: string[];
    work_item_verification_commands?: string[];
    work_item_evidence_outputs?: string[];
    group_commands?: string[];
    group_verification_commands?: string[];
    group_evidence_outputs?: string[];
    combined_commands?: string[];
    combined_verification_commands?: string[];
    combined_evidence_outputs?: string[];
    group_command_count?: number;
    group_verification_command_count?: number;
    group_evidence_output_count?: number;
    recommended_sequence?: string[];
    recommended_sequence_count?: number;
    strict_gate_command?: string;
    requires_request_packet_before_execution?: boolean;
    request_packet_hash_available?: boolean;
  };
  commands?: string[];
  verification_commands?: string[];
  evidence_outputs?: string[];
  runtime_endpoints?: {
    next_work_item?: string;
    handoff_dossier?: string;
    launch_remediation_plan?: string;
    customer_handoff_readiness?: string;
    external_dependency_clearance?: string;
  };
  hard_gate_commands?: string[];
};

type AuP0aCredentialRequest = {
  p0a_credential_request_packet_version: string;
  generated_at: string;
  status: string;
  credential_request_packet_ready: boolean;
  credential_handoff_ready: boolean;
  ready_for_design_partner: boolean;
  p0a_credential_request_packet_hash: string;
  summary?: {
    target_env_file?: string;
    credential_handoff_ready?: boolean;
    missing_required_count?: number;
    missing_required?: string[];
    credential_item_count?: number;
    required_item_count?: number;
    present_required_count?: number;
    owner_counts?: Record<string, number>;
    missing_required_by_owner?: Record<string, string[]>;
    setup_command_count?: number;
    verification_command_count?: number;
    evidence_output_count?: number;
    raw_secret_values_allowed?: boolean;
    forbidden_exact_secret_fields_redacted?: boolean;
    next_command?: string;
    post_update_verification_command?: string;
  };
  requested_credentials?: Array<{
    name: string;
    required?: boolean;
    present?: boolean;
    source?: string;
    owner_hint?: string;
    accepted_injection_methods?: string[];
    env_file_key?: string;
    value_length?: number;
    sha256_prefix?: string;
    secret_redacted?: boolean;
    post_update_checks?: string[];
  }>;
  setup_commands?: string[];
  verification_commands?: string[];
  evidence_outputs?: string[];
  runtime_endpoints?: {
    p0a_credential_request?: string;
    p0a_execution_checklist?: string;
    p0a_environment_checklist?: string;
    next_work_item?: string;
    external_dependency_handoff?: string;
  };
  hard_gate_commands?: string[];
  source_p0a_execution_checklist?: {
    p0a_execution_checklist_hash?: string;
    p0a_execution_checklist_ready?: boolean;
    ready_for_design_partner?: boolean;
    path?: string;
  };
};

type AuP0aCredentialFulfillment = {
  p0a_credential_fulfillment_version: string;
  generated_at: string;
  status: string;
  credential_fulfillment_ready: boolean;
  credentials_fulfilled: boolean;
  ready_for_design_partner: boolean;
  p0a_credential_fulfillment_hash: string;
  summary?: {
    credentials_fulfilled?: boolean;
    credential_handoff_ready?: boolean;
    environment_ready?: boolean;
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    presence_mismatch_count?: number;
    presence_mismatches?: string[];
    owner_counts?: Record<string, number>;
    missing_required_by_owner?: Record<string, string[]>;
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    raw_secret_values_allowed?: boolean;
  };
  credential_fulfillment_items?: Array<{
    name: string;
    required?: boolean;
    fulfilled?: boolean;
    requested_present?: boolean;
    environment_present?: boolean;
    presence_mismatch?: boolean;
    request_source?: string;
    environment_source?: string;
    owner_hint?: string;
    env_file_key?: string;
    value_length?: number;
    sha256_prefix?: string;
    secret_redacted?: boolean;
    blocking_reasons?: string[];
  }>;
  verification_commands?: string[];
  hard_gate_commands?: string[];
  runtime_endpoints?: {
    p0a_credential_fulfillment?: string;
    p0a_credential_request?: string;
    p0a_environment_checklist?: string;
    external_dependency_clearance?: string;
  };
  source_p0a_credential_request?: {
    p0a_credential_request_packet_hash?: string;
    credential_handoff_ready?: boolean;
  };
  source_p0a_env_report?: {
    environment_report_hash?: string;
    ready_for_real_batch?: boolean;
    missing_required?: string[];
  };
};

type AuP0aCredentialClearance = {
  p0a_credential_clearance_version: string;
  generated_at: string;
  status: string;
  credential_clearance_packet_ready: boolean;
  credentials_fulfilled: boolean;
  credential_clearance_ready: boolean;
  ready_for_next_clearance_step: boolean;
  p0a_credential_clearance_hash: string;
  clearance_step?: {
    id?: string;
    current_step_id?: string;
    current_step_matches?: boolean;
    would_execute_step_count?: number;
    next_command?: string;
    current_strict_gate_command?: string;
  };
  summary?: {
    target_env_file?: string;
    credentials_fulfilled?: boolean;
    missing_required_count?: number;
    missing_required?: string[];
    provider_missing_required?: string[];
    runtime_database_missing_required?: string[];
    credential_handoff_ready?: boolean;
    credential_fulfillment_ready?: boolean;
    environment_ready?: boolean;
    current_clearance_step_id?: string;
    clearance_step_matches?: boolean;
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    operator_step_count?: number;
    post_update_validation_command_count?: number;
    raw_secret_values_allowed?: boolean;
  };
  missing_credential_items?: Array<{
    name: string;
    owner_hint?: string;
    env_file_key?: string;
    target_env_file?: string;
    request_present?: boolean;
    environment_present?: boolean;
    accepted_injection_methods?: string[];
    post_update_checks?: string[];
    blocking_reasons?: string[];
    raw_value_required_in_packet?: boolean;
  }>;
  operator_steps?: Array<{
    order?: number;
    id?: string;
    command?: string;
    purpose?: string;
    external_call_risk?: string;
    missing_required?: string[];
    target_env_file?: string;
    allowed_injection_methods?: string[];
  }>;
  post_update_validation_sequence?: string[];
  runtime_endpoints?: {
    p0a_credential_clearance?: string;
    p0a_credential_request?: string;
    p0a_credential_fulfillment?: string;
    external_dependency_clearance?: string;
    delivery_progress?: string;
  };
  hard_gate_commands?: string[];
  source_artifacts?: {
    credential_request?: { hash?: string };
    credential_fulfillment?: { hash?: string };
    external_dependency_clearance?: { hash?: string };
  };
};

type AuP0aRealBatchRequest = {
  p0a_real_batch_request_packet_version: string;
  generated_at: string;
  status: string;
  real_batch_request_packet_ready: boolean;
  real_batch_phase_handoff_ready: boolean;
  ready_for_design_partner: boolean;
  p0a_real_batch_request_packet_hash: string;
  summary?: {
    source_real_batch_phase_handoff_version?: string;
    real_batch_phase_handoff_ready?: boolean;
    phase_count?: number;
    ready_phase_count?: number;
    blocked_phase_count?: number;
    next_phase?: string;
    total_planned_runs?: number;
    phase_order?: string[];
    phase_request_count?: number;
    command_count?: number;
    setup_command_count?: number;
    verification_command_count?: number;
    evidence_output_count?: number;
    blocking_reason_count?: number;
    blocking_reasons?: string[];
    raw_secret_values_allowed?: boolean;
    phase_entries_reference_command_ids_and_artifact_paths_only?: boolean;
    next_command?: string;
    post_update_verification_command?: string;
    p0a_next_action?: string;
  };
  phase_requests?: Array<{
    id: string;
    title?: string;
    planned_runs?: number;
    ready?: boolean;
    can_start?: boolean;
    command_ids?: string[];
    commands?: string[];
    artifact_keys?: string[];
    artifacts?: Array<{
      key: string;
      path?: string;
      exists?: boolean;
      status?: string;
      ready_for_design_partner?: boolean;
      hash_valid?: boolean | null;
      ready?: boolean;
      errors?: string[];
    }>;
    evidence_outputs?: string[];
    prerequisite_gate_ids?: string[];
    blocking_reasons?: string[];
  }>;
  setup_commands?: string[];
  phase_commands?: string[];
  verification_commands?: string[];
  evidence_outputs?: string[];
  runtime_endpoints?: {
    p0a_real_batch_request?: string;
    p0a_credential_request?: string;
    p0a_execution_checklist?: string;
    p0a_environment_checklist?: string;
    external_dependency_handoff?: string;
    next_work_item?: string;
  };
  hard_gate_commands?: string[];
  source_p0a_execution_checklist?: {
    p0a_execution_checklist_hash?: string;
    p0a_execution_checklist_ready?: boolean;
    ready_for_design_partner?: boolean;
    path?: string;
  };
};

type AuP0aRealBatchFulfillment = {
  p0a_real_batch_fulfillment_version: string;
  generated_at: string;
  status: string;
  real_batch_fulfillment_ready: boolean;
  real_batches_fulfilled: boolean;
  real_batch_phase_handoff_ready: boolean;
  ready_for_design_partner: boolean;
  p0a_real_batch_fulfillment_hash: string;
  summary?: {
    real_batches_fulfilled?: boolean;
    real_batch_request_ready?: boolean;
    execution_checklist_ready?: boolean;
    source_checklist_hash_aligned?: boolean;
    real_batch_phase_handoff_ready?: boolean;
    ready_for_design_partner?: boolean;
    phase_count?: number;
    phase_order?: string[];
    ready_phase_count?: number;
    blocked_phase_count?: number;
    next_phase?: string;
    total_planned_runs?: number;
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    presence_mismatch_count?: number;
    presence_mismatches?: string[];
    blocking_reason_count?: number;
    blocking_reasons?: string[];
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    request_strict_gate_command?: string;
    design_partner_strict_gate_command?: string;
    raw_secret_values_allowed?: boolean;
  };
  real_batch_fulfillment_items?: Array<{
    key: string;
    phase_id: string;
    title?: string;
    required?: boolean;
    fulfilled?: boolean;
    request_ready?: boolean;
    checklist_ready?: boolean;
    request_can_start?: boolean;
    checklist_can_start?: boolean;
    presence_mismatch?: boolean;
    planned_runs?: number;
    command_ids?: string[];
    commands?: string[];
    artifact_keys?: string[];
    prerequisite_gate_ids?: string[];
    evidence_outputs?: string[];
    owner_hint?: string;
    blocking_reasons?: string[];
  }>;
  phase_commands?: string[];
  verification_commands?: string[];
  evidence_outputs?: string[];
  hard_gate_commands?: string[];
  runtime_endpoints?: {
    p0a_real_batch_fulfillment?: string;
    p0a_real_batch_request?: string;
    p0a_execution_checklist?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
  };
  source_p0a_real_batch_request?: {
    p0a_real_batch_request_packet_hash?: string;
    source_p0a_execution_checklist_hash?: string;
    real_batch_request_packet_ready?: boolean;
    real_batch_phase_handoff_ready?: boolean;
    ready_for_design_partner?: boolean;
  };
  source_p0a_execution_checklist?: {
    p0a_execution_checklist_hash?: string;
    p0a_execution_checklist_ready?: boolean;
    real_batch_phase_handoff_ready?: boolean;
    ready_for_design_partner?: boolean;
  };
};

type AuP0aRealBatchClearance = {
  p0a_real_batch_clearance_version: string;
  generated_at: string;
  status: string;
  real_batch_clearance_packet_ready: boolean;
  real_batches_fulfilled: boolean;
  real_batch_clearance_ready: boolean;
  ready_for_next_clearance_step: boolean;
  blocked_by_prerequisite_step: boolean;
  p0a_real_batch_clearance_hash: string;
  clearance_step?: {
    id?: string;
    current_global_step_id?: string;
    current_global_step_is_prerequisite?: boolean;
    step_recorded?: boolean;
    step_ready?: boolean;
    step_can_start?: boolean;
    step_status?: string;
    blocked_by?: string[];
    would_execute?: boolean;
    strict_gate_command?: string;
  };
  prerequisite_step?: {
    id?: string;
    ready?: boolean;
    status?: string;
    would_execute?: boolean;
    strict_gate_command?: string;
    blocked_by?: string[];
    runtime_endpoint?: string;
  };
  summary?: {
    phase_order?: string[];
    phase_count?: number;
    ready_phase_count?: number;
    blocked_phase_count?: number;
    total_planned_runs?: number;
    next_phase?: string;
    real_batches_fulfilled?: boolean;
    real_batch_fulfillment_ready?: boolean;
    ready_for_design_partner?: boolean;
    blocked_by_prerequisite_step?: boolean;
    prerequisite_step_id?: string;
    prerequisite_step_ready?: boolean;
    current_global_clearance_step_id?: string;
    target_clearance_step_id?: string;
    target_clearance_step_can_start?: boolean;
    target_clearance_step_ready?: boolean;
    missing_required_count?: number;
    missing_required?: string[];
    missing_required_by_owner?: Record<string, string[]>;
    blocking_reason_count?: number;
    blocking_reasons?: string[];
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    design_partner_strict_gate_command?: string;
    operator_step_count?: number;
    post_update_validation_command_count?: number;
    raw_secret_values_allowed?: boolean;
    provider_response_values_allowed?: boolean;
  };
  phase_clearance_items?: Array<{
    key: string;
    phase_id: string;
    title?: string;
    owner_hint?: string;
    fulfilled?: boolean;
    request_ready?: boolean;
    checklist_ready?: boolean;
    can_start?: boolean;
    planned_runs?: number;
    command_ids?: string[];
    artifact_keys?: string[];
    evidence_outputs?: string[];
    blocking_reasons?: string[];
  }>;
  operator_steps?: Array<{
    order?: number;
    id?: string;
    command?: string;
    purpose?: string;
    external_call_risk?: string;
    next_phase?: string;
    blocked?: boolean;
  }>;
  post_update_validation_sequence?: string[];
  runtime_endpoints?: {
    p0a_real_batch_clearance?: string;
    p0a_real_batch_request?: string;
    p0a_real_batch_fulfillment?: string;
    p0a_execution_checklist?: string;
    p0a_credential_clearance?: string;
    external_dependency_clearance?: string;
    delivery_progress?: string;
  };
  hard_gate_commands?: string[];
  source_artifacts?: {
    real_batch_request?: { hash?: string };
    p0a_execution_checklist?: { hash?: string };
    real_batch_fulfillment?: { hash?: string };
    external_dependency_clearance?: { hash?: string };
  };
};

type AuP0bGoogleEnvironmentRequest = {
  p0b_google_environment_request_packet_version: string;
  generated_at: string;
  status: string;
  google_environment_request_packet_ready: boolean;
  environment_handoff_ready: boolean;
  google_main_scoring_allowed: boolean;
  p0b_google_environment_request_packet_hash: string;
  summary?: {
    source_environment_handoff_version?: string;
    target_env_file?: string;
    environment_handoff_ready?: boolean;
    missing_required_count?: number;
    missing_required?: string[];
    environment_item_count?: number;
    selector_item_count?: number;
    file_item_count?: number;
    dependency_item_count?: number;
    owner_counts?: Record<string, number>;
    missing_required_by_owner?: Record<string, string[]>;
    setup_command_count?: number;
    verification_command_count?: number;
    evidence_output_count?: number;
    cross_stage_reuse_hint_count?: number;
    database_url_reuse_available?: boolean;
    env_file_hygiene_ready?: boolean;
    raw_secret_values_allowed?: boolean;
    forbidden_exact_secret_fields_redacted?: boolean;
    next_command?: string;
    post_update_verification_command?: string;
    google_next_action?: string;
  };
  environment_items?: Array<{
    name: string;
    gate?: string;
    required?: boolean;
    present?: boolean;
    truthy?: boolean | null;
    source?: string;
    owner_hint?: string;
    accepted_injection_methods?: string[];
    env_file_key?: string;
    value_length?: number;
    sha256_prefix?: string;
    secret_redacted?: boolean;
    post_update_checks?: string[];
  }>;
  selector_items?: Array<{
    group: string;
    candidate_names?: string[];
    present?: boolean;
    selected_name?: string;
    source?: string;
    owner_hint?: string;
    accepted_injection_methods?: string[];
    value_length?: number;
    sha256_prefix?: string;
    secret_redacted?: boolean;
    post_update_checks?: string[];
  }>;
  file_items?: Array<{
    name: string;
    expected_type?: string;
    present?: boolean;
    exists?: boolean;
    is_file?: boolean;
    is_dir?: boolean;
    source?: string;
    owner_hint?: string;
    secret_redacted?: boolean;
  }>;
  dependency_items?: Array<{
    name: string;
    present?: boolean;
    source?: string;
    owner_hint?: string;
    secret_redacted?: boolean;
  }>;
  cross_stage_reuse_hints?: Array<{
    id?: string;
    source_stage?: string;
    target_stage?: string;
    source_artifact?: string;
    source_environment_report_hash?: string;
    source_verifier_status?: string;
    source_hash_valid?: boolean;
    source_key?: string;
    target_env_file?: string;
    target_key?: string;
    target_missing_id?: string;
    reuse_available?: boolean;
    secret_redacted?: boolean;
    value_length?: number;
    sha256_prefix?: string;
    copy_raw_value_required?: boolean;
    operator_action?: string;
    post_update_checks?: string[];
  }>;
  setup_commands?: string[];
  verification_commands?: string[];
  evidence_outputs?: string[];
  runtime_endpoints?: {
    p0b_google_environment_request?: string;
    p0b_google_execution_checklist?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
    next_work_item?: string;
  };
  hard_gate_commands?: string[];
  source_p0b_google_execution_checklist?: {
    google_execution_checklist_hash?: string;
    google_execution_checklist_ready?: boolean;
    google_main_scoring_allowed?: boolean;
    path?: string;
  };
  source_p0a_env_report?: {
    environment_report_hash?: string;
    ready_for_real_batch?: boolean;
    path?: string;
  };
  p0a_env_report_verifier?: {
    status?: string;
    hash_valid?: boolean;
    environment_report_hash?: string;
    ready_for_real_batch?: boolean;
    missing_required?: string[];
  };
};

type AuP0bGoogleEnvironmentFulfillment = {
  p0b_google_environment_fulfillment_version: string;
  generated_at: string;
  status: string;
  environment_fulfillment_ready: boolean;
  environment_fulfilled: boolean;
  ready_for_playwright_smoke: boolean;
  ready_for_full_google_run: boolean;
  google_main_scoring_allowed: boolean;
  p0b_google_environment_fulfillment_hash: string;
  summary?: {
    environment_fulfilled?: boolean;
    environment_handoff_ready?: boolean;
    playwright_env_ready_for_smoke?: boolean;
    playwright_env_ready_for_full_google_run?: boolean;
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    presence_mismatch_count?: number;
    presence_mismatches?: string[];
    missing_required_by_owner?: Record<string, string[]>;
    cross_stage_reuse_hint_count?: number;
    database_url_reuse_available?: boolean;
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    ready_smoke_strict_gate_command?: string;
  };
  environment_fulfillment_items?: Array<{
    key?: string;
    item_type?: string;
    name?: string;
    required?: boolean;
    fulfilled?: boolean;
    requested_present?: boolean;
    environment_present?: boolean;
    presence_mismatch?: boolean;
    request_source?: string;
    environment_source?: string;
    owner_hint?: string;
    env_file_key?: string;
    value_length?: number;
    sha256_prefix?: string;
    secret_redacted?: boolean;
    blocking_reasons?: string[];
  }>;
  source_p0b_google_environment_request?: {
    p0b_google_environment_request_packet_hash?: string;
    google_environment_request_packet_ready?: boolean;
    environment_handoff_ready?: boolean;
  };
  source_p0b_google_playwright_env_report?: {
    environment_report_hash?: string;
    ready_for_playwright_smoke?: boolean;
    ready_for_full_google_run?: boolean;
  };
  runtime_endpoints?: {
    p0b_google_environment_fulfillment?: string;
    p0b_google_environment_request?: string;
    p0b_google_execution_checklist?: string;
    external_dependency_clearance?: string;
  };
  hard_gate_commands?: string[];
};

type AuP0bGoogleEnvironmentClearance = {
  p0b_google_environment_clearance_version: string;
  generated_at: string;
  status: string;
  environment_clearance_packet_ready: boolean;
  environment_fulfilled: boolean;
  environment_clearance_ready: boolean;
  ready_for_next_clearance_step: boolean;
  blocked_by_prerequisite_step: boolean;
  p0b_google_environment_clearance_hash: string;
  summary?: {
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    presence_mismatch_count?: number;
    presence_mismatches?: string[];
    missing_required_by_owner?: Record<string, string[]>;
    environment_fulfilled?: boolean;
    environment_fulfillment_ready?: boolean;
    ready_for_playwright_smoke?: boolean;
    ready_for_full_google_run?: boolean;
    google_main_scoring_allowed?: boolean;
    environment_handoff_ready?: boolean;
    database_url_reuse_available?: boolean;
    blocked_by_prerequisite_step?: boolean;
    prerequisite_step_id?: string;
    prerequisite_step_ready?: boolean;
    current_global_clearance_step_id?: string;
    target_clearance_step_id?: string;
    target_clearance_step_can_start?: boolean;
    target_clearance_step_ready?: boolean;
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    ready_smoke_strict_gate_command?: string;
    operator_step_count?: number;
    post_update_validation_command_count?: number;
    raw_secret_values_allowed?: boolean;
    selector_values_allowed?: boolean;
    database_urls_allowed?: boolean;
  };
  environment_clearance_items?: Array<{
    key?: string;
    item_type?: string;
    name?: string;
    required?: boolean;
    fulfilled?: boolean;
    requested_present?: boolean;
    environment_present?: boolean;
    presence_mismatch?: boolean;
    request_source?: string;
    environment_source?: string;
    owner_hint?: string;
    env_file_key?: string;
    value_length?: number;
    sha256_prefix?: string;
    secret_redacted?: boolean;
    blocking_reasons?: string[];
  }>;
  operator_steps?: Array<{
    order?: number;
    id?: string;
    command?: string;
    purpose?: string;
    external_call_risk?: string;
    next_action?: string;
    blocked?: boolean;
  }>;
  post_update_validation_sequence?: string[];
  runtime_endpoints?: {
    p0b_google_environment_clearance?: string;
    p0b_google_environment_request?: string;
    p0b_google_environment_fulfillment?: string;
    p0b_google_execution_checklist?: string;
    p0a_real_batch_clearance?: string;
    external_dependency_clearance?: string;
    delivery_progress?: string;
  };
  hard_gate_commands?: string[];
  source_artifacts?: {
    environment_request?: { hash?: string };
    playwright_env_report?: { hash?: string };
    environment_fulfillment?: { hash?: string };
    external_dependency_clearance?: { hash?: string };
  };
};

type AuP0bGoogleManualBackfillRequest = {
  p0b_google_manual_backfill_request_packet_version: string;
  generated_at: string;
  status: string;
  manual_backfill_request_packet_ready: boolean;
  manual_backfill_handoff_ready: boolean;
  google_main_scoring_allowed: boolean;
  p0b_google_manual_backfill_request_packet_hash: string;
  summary?: {
    source_manual_backfill_handoff_version?: string;
    manual_backfill_handoff_status?: string;
    hash_valid?: boolean;
    manual_backfill_ready?: boolean;
    manual_backfill_handoff_ready?: boolean;
    manual_jsonl_env_var?: string;
    target_jsonl_path?: string;
    target_jsonl_path_source?: string;
    manual_jsonl_path_redacted?: boolean;
    template_path?: string;
    template_manifest_path?: string;
    verification_path?: string;
    expected_record_count?: number;
    record_count?: number;
    expected_prompt_city_count?: number;
    covered_prompt_city_count?: number;
    expected_sample_size?: number;
    prompt_count?: number;
    geo_city_count?: number;
    geo_cities?: string[];
    missing_reason_count?: number;
    missing_reasons?: string[];
    required_field_count?: number;
    operator_requirement_count?: number;
    setup_command_count?: number;
    verification_command_count?: number;
    evidence_output_count?: number;
    raw_answer_values_allowed?: boolean;
    raw_citation_values_allowed?: boolean;
    raw_asset_urls_allowed?: boolean;
    content_redacted?: boolean;
    next_command?: string;
    post_update_verification_command?: string;
    google_next_action?: string;
  };
  manual_backfill_request?: {
    source_manual_backfill_handoff_version?: string;
    status?: string;
    hash_valid?: boolean;
    manual_backfill_ready?: boolean;
    ready?: boolean;
    manual_jsonl_env_var?: string;
    target_jsonl_path?: string;
    target_jsonl_path_source?: string;
    manual_jsonl_path_redacted?: boolean;
    template_path?: string;
    template_manifest_path?: string;
    verification_path?: string;
    expected_record_count?: number;
    record_count?: number;
    expected_prompt_city_count?: number;
    covered_prompt_city_count?: number;
    expected_sample_size?: number;
    prompt_count?: number;
    geo_cities?: string[];
    file_sha256?: string;
    verification_hash?: string;
    missing_reason_count?: number;
    missing_reasons?: string[];
  };
  required_fields?: string[];
  operator_requirements?: string[];
  setup_commands?: string[];
  verification_commands?: string[];
  evidence_outputs?: string[];
  runtime_endpoints?: {
    p0b_google_manual_backfill_request?: string;
    p0b_google_execution_checklist?: string;
    p0b_google_environment_request?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
    next_work_item?: string;
  };
  hard_gate_commands?: string[];
  source_p0b_google_execution_checklist?: {
    google_execution_checklist_hash?: string;
    google_execution_checklist_ready?: boolean;
    google_main_scoring_allowed?: boolean;
    path?: string;
  };
};

type AuP0bGoogleManualBackfillFulfillment = {
  p0b_google_manual_backfill_fulfillment_version: string;
  generated_at: string;
  status: string;
  manual_backfill_fulfillment_ready: boolean;
  manual_backfill_fulfilled: boolean;
  google_main_scoring_allowed: boolean;
  p0b_google_manual_backfill_fulfillment_hash: string;
  summary?: {
    manual_backfill_fulfilled?: boolean;
    manual_backfill_request_ready?: boolean;
    manual_backfill_handoff_ready?: boolean;
    manual_backfill_verification_ready?: boolean;
    manual_backfill_verification_status?: string;
    expected_record_count?: number;
    record_count?: number;
    expected_prompt_city_count?: number;
    covered_prompt_city_count?: number;
    expected_sample_size?: number;
    verification_expected_sample_size?: number;
    verification_error_count?: number;
    verification_errors?: string[];
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    missing_required_by_owner?: Record<string, string[]>;
    target_jsonl_path?: string;
    resolved_manual_jsonl_path?: string;
    verification_path?: string;
    file_sha256_present?: boolean;
    verification_hash_present?: boolean;
    content_redacted?: boolean;
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    request_strict_gate_command?: string;
  };
  manual_backfill_fulfillment_items?: Array<{
    key?: string;
    category?: string;
    required?: boolean;
    fulfilled?: boolean;
    expected_value?: string | number | boolean;
    actual_value?: string | number | boolean;
    owner_hint?: string;
    source_request_field?: string;
    source_verification_field?: string;
    blocking_reasons?: string[];
  }>;
  source_p0b_google_manual_backfill_request?: {
    p0b_google_manual_backfill_request_packet_hash?: string;
    manual_backfill_request_packet_ready?: boolean;
    manual_backfill_handoff_ready?: boolean;
  };
  source_p0b_google_manual_backfill_verification?: {
    verification_hash?: string;
    manual_backfill_status?: string;
    file_sha256?: string;
    manual_jsonl_path?: string;
  };
  runtime_endpoints?: {
    p0b_google_manual_backfill_fulfillment?: string;
    p0b_google_manual_backfill_request?: string;
    p0b_google_execution_checklist?: string;
    external_dependency_clearance?: string;
  };
  hard_gate_commands?: string[];
};

type AuP0bGoogleManualBackfillClearance = {
  p0b_google_manual_backfill_clearance_version: string;
  generated_at: string;
  status: string;
  manual_backfill_clearance_packet_ready: boolean;
  manual_backfill_fulfilled: boolean;
  manual_backfill_clearance_ready: boolean;
  ready_for_next_clearance_step: boolean;
  blocked_by_prerequisite_step: boolean;
  p0b_google_manual_backfill_clearance_hash: string;
  summary?: {
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    presence_mismatch_count?: number;
    presence_mismatches?: string[];
    missing_required_by_owner?: Record<string, string[]>;
    manual_backfill_fulfilled?: boolean;
    manual_backfill_fulfillment_ready?: boolean;
    manual_backfill_request_ready?: boolean;
    manual_backfill_handoff_ready?: boolean;
    manual_backfill_verification_ready?: boolean;
    manual_backfill_verification_status?: string;
    expected_record_count?: number;
    record_count?: number;
    expected_prompt_city_count?: number;
    covered_prompt_city_count?: number;
    expected_sample_size?: number;
    verification_expected_sample_size?: number;
    verification_error_count?: number;
    verification_errors?: string[];
    file_sha256_present?: boolean;
    verification_hash_present?: boolean;
    content_redacted?: boolean;
    google_main_scoring_allowed?: boolean;
    blocked_by_prerequisite_step?: boolean;
    prerequisite_step_id?: string;
    prerequisite_step_ready?: boolean;
    current_global_clearance_step_id?: string;
    target_clearance_step_id?: string;
    target_clearance_step_can_start?: boolean;
    target_clearance_step_ready?: boolean;
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    request_strict_gate_command?: string;
    operator_step_count?: number;
    post_update_validation_command_count?: number;
    raw_answer_values_allowed?: boolean;
    raw_citation_values_allowed?: boolean;
    raw_asset_urls_allowed?: boolean;
    manual_jsonl_raw_path_allowed?: boolean;
  };
  manual_backfill_clearance_items?: Array<{
    key?: string;
    category?: string;
    required?: boolean;
    fulfilled?: boolean;
    expected_value?: string | number | boolean;
    actual_value?: string | number | boolean;
    presence_mismatch?: boolean;
    owner_hint?: string;
    source_request_field?: string;
    source_verification_field?: string;
    blocking_reasons?: string[];
  }>;
  operator_steps?: Array<{
    order?: number;
    id?: string;
    command?: string;
    purpose?: string;
    external_call_risk?: string;
    next_action?: string;
    blocked?: boolean;
  }>;
  post_update_validation_sequence?: string[];
  runtime_endpoints?: {
    p0b_google_manual_backfill_clearance?: string;
    p0b_google_manual_backfill_request?: string;
    p0b_google_manual_backfill_fulfillment?: string;
    p0b_google_execution_checklist?: string;
    p0b_google_environment_clearance?: string;
    external_dependency_clearance?: string;
    delivery_progress?: string;
  };
  hard_gate_commands?: string[];
  source_artifacts?: {
    manual_backfill_request?: { hash?: string };
    manual_backfill_verification?: { hash?: string; manual_backfill_status?: string };
    manual_backfill_fulfillment?: { hash?: string };
    external_dependency_clearance?: { hash?: string };
  };
};

type AuP0bGooglePhaseExecutionRequest = {
  p0b_google_phase_execution_request_packet_version: string;
  generated_at: string;
  status: string;
  phase_execution_request_packet_ready: boolean;
  google_spike_phase_handoff_ready: boolean;
  google_main_scoring_allowed: boolean;
  p0b_google_phase_execution_request_packet_hash: string;
  summary?: {
    source_google_spike_phase_handoff_version?: string;
    source_google_spike_phase_handoff_status?: string;
    hash_valid?: boolean;
    phase_count?: number;
    phase_order?: string[];
    ready_phase_count?: number;
    blocked_phase_count?: number;
    next_phase?: string;
    next_command?: string;
    post_update_verification_command?: string;
    full_spike_planned_runs?: number;
    manual_expected_record_count?: number;
    setup_command_count?: number;
    phase_command_count?: number;
    verification_command_count?: number;
    evidence_output_count?: number;
    blocking_reason_count?: number;
    blocking_reasons?: string[];
    raw_secret_values_allowed?: boolean;
    raw_answer_values_allowed?: boolean;
    raw_citation_values_allowed?: boolean;
    raw_asset_urls_allowed?: boolean;
    phase_entries_reference_command_ids_and_artifact_paths_only?: boolean;
  };
  phase_requests?: Array<{
    id: string;
    title?: string;
    planned_runs?: number;
    ready?: boolean;
    can_start?: boolean;
    command_ids?: string[];
    commands?: string[];
    artifact_keys?: string[];
    artifacts?: Array<{
      key?: string;
      path?: string;
      exists?: boolean;
      status?: string;
      ready?: boolean;
      hash_valid?: boolean;
    }>;
    evidence_outputs?: string[];
    prerequisite_gate_ids?: string[];
    prerequisite_phase_id?: string | null;
    blocking_reasons?: string[];
  }>;
  setup_commands?: string[];
  phase_commands?: string[];
  verification_commands?: string[];
  evidence_outputs?: string[];
  runtime_endpoints?: {
    p0b_google_phase_execution_request?: string;
    p0b_google_execution_checklist?: string;
    p0b_google_environment_request?: string;
    p0b_google_manual_backfill_request?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
    next_work_item?: string;
  };
  hard_gate_commands?: string[];
  source_p0b_google_execution_checklist?: {
    google_execution_checklist_hash?: string;
    google_execution_checklist_ready?: boolean;
    google_spike_phase_handoff_ready?: boolean;
    google_main_scoring_allowed?: boolean;
    path?: string;
  };
};

type AuP0bGooglePhaseExecutionFulfillment = {
  p0b_google_phase_execution_fulfillment_version: string;
  generated_at: string;
  status: string;
  phase_execution_fulfillment_ready: boolean;
  phase_execution_fulfilled: boolean;
  google_spike_phase_handoff_ready: boolean;
  google_main_scoring_allowed: boolean;
  p0b_google_phase_execution_fulfillment_hash: string;
  summary?: {
    phase_execution_fulfilled?: boolean;
    phase_execution_request_ready?: boolean;
    execution_checklist_ready?: boolean;
    google_spike_phase_handoff_ready?: boolean;
    google_main_scoring_allowed?: boolean;
    phase_count?: number;
    phase_order?: string[];
    ready_phase_count?: number;
    blocked_phase_count?: number;
    next_phase?: string;
    next_action?: string;
    next_command?: string;
    full_spike_planned_runs?: number;
    manual_expected_record_count?: number;
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    presence_mismatch_count?: number;
    presence_mismatches?: string[];
    blocking_reason_count?: number;
    blocking_reasons?: string[];
    strict_gate_command?: string;
    request_strict_gate_command?: string;
    scoring_strict_gate_command?: string;
    raw_secret_values_allowed?: boolean;
    raw_answer_values_allowed?: boolean;
    raw_citation_values_allowed?: boolean;
    raw_asset_urls_allowed?: boolean;
    phase_entries_reference_command_ids_and_artifact_paths_only?: boolean;
  };
  phase_fulfillment_items?: Array<{
    key?: string;
    phase_id?: string;
    title?: string;
    required?: boolean;
    fulfilled?: boolean;
    request_ready?: boolean;
    checklist_ready?: boolean;
    request_can_start?: boolean;
    checklist_can_start?: boolean;
    planned_runs?: number;
    command_ids?: string[];
    commands?: string[];
    artifact_keys?: string[];
    evidence_outputs?: string[];
    owner_hint?: string;
    blocking_reasons?: string[];
  }>;
  phase_commands?: string[];
  verification_commands?: string[];
  evidence_outputs?: string[];
  hard_gate_commands?: string[];
  runtime_endpoints?: {
    p0b_google_phase_execution_fulfillment?: string;
    p0b_google_phase_execution_request?: string;
    p0b_google_execution_checklist?: string;
    external_dependency_handoff?: string;
    external_dependency_clearance?: string;
  };
  source_p0b_google_phase_execution_request?: {
    p0b_google_phase_execution_request_packet_hash?: string;
    phase_execution_request_packet_ready?: boolean;
  };
  source_p0b_google_execution_checklist?: {
    google_execution_checklist_hash?: string;
    google_execution_checklist_ready?: boolean;
  };
};

type AuP0bGooglePhaseExecutionClearance = {
  p0b_google_phase_execution_clearance_version: string;
  generated_at: string;
  status: string;
  phase_execution_clearance_packet_ready: boolean;
  phase_execution_fulfilled: boolean;
  phase_execution_clearance_ready: boolean;
  ready_for_next_clearance_step: boolean;
  blocked_by_prerequisite_step: boolean;
  p0b_google_phase_execution_clearance_hash: string;
  summary?: {
    required_count?: number;
    fulfilled_required_count?: number;
    missing_required_count?: number;
    missing_required?: string[];
    presence_mismatch_count?: number;
    presence_mismatches?: string[];
    missing_required_by_owner?: Record<string, string[]>;
    blocking_reason_count?: number;
    blocking_reasons?: string[];
    phase_execution_fulfilled?: boolean;
    phase_execution_fulfillment_ready?: boolean;
    phase_execution_request_ready?: boolean;
    execution_checklist_ready?: boolean;
    source_checklist_hash_aligned?: boolean;
    google_spike_phase_handoff_ready?: boolean;
    google_main_scoring_allowed?: boolean;
    phase_count?: number;
    phase_order?: string[];
    ready_phase_count?: number;
    blocked_phase_count?: number;
    next_phase?: string;
    full_spike_planned_runs?: number;
    manual_expected_record_count?: number;
    blocked_by_prerequisite_step?: boolean;
    prerequisite_step_id?: string;
    prerequisite_step_ready?: boolean;
    current_global_clearance_step_id?: string;
    target_clearance_step_id?: string;
    target_clearance_step_can_start?: boolean;
    target_clearance_step_ready?: boolean;
    phase_execution_clearance_ready?: boolean;
    ready_for_next_clearance_step?: boolean;
    next_action?: string;
    next_command?: string;
    strict_gate_command?: string;
    request_strict_gate_command?: string;
    scoring_strict_gate_command?: string;
    operator_step_count?: number;
    post_update_validation_command_count?: number;
    raw_secret_values_allowed?: boolean;
    raw_answer_values_allowed?: boolean;
    raw_citation_values_allowed?: boolean;
    raw_asset_urls_allowed?: boolean;
    raw_provider_response_allowed?: boolean;
    phase_entries_reference_command_ids_and_artifact_paths_only?: boolean;
  };
  phase_execution_clearance_items?: Array<{
    key?: string;
    phase_id?: string;
    title?: string;
    required?: boolean;
    fulfilled?: boolean;
    request_ready?: boolean;
    checklist_ready?: boolean;
    request_can_start?: boolean;
    checklist_can_start?: boolean;
    planned_runs?: number;
    command_ids?: string[];
    commands?: string[];
    artifact_keys?: string[];
    evidence_outputs?: string[];
    owner_hint?: string;
    blocking_reasons?: string[];
  }>;
  operator_steps?: Array<{
    order?: number;
    id?: string;
    command?: string;
    purpose?: string;
    external_call_risk?: string;
    next_action?: string;
    next_phase?: string;
    blocked?: boolean;
  }>;
  post_update_validation_sequence?: string[];
  runtime_endpoints?: {
    p0b_google_phase_execution_clearance?: string;
    p0b_google_phase_execution_fulfillment?: string;
    p0b_google_phase_execution_request?: string;
    p0b_google_execution_checklist?: string;
    p0b_google_manual_backfill_clearance?: string;
    external_dependency_clearance?: string;
    customer_handoff_readiness?: string;
    delivery_progress?: string;
  };
  hard_gate_commands?: string[];
  source_artifacts?: {
    phase_execution_request?: { hash?: string };
    p0b_google_execution_checklist?: { hash?: string };
    phase_execution_fulfillment?: { hash?: string };
    external_dependency_clearance?: { hash?: string };
  };
};

type AuExternalDependencyHandoff = {
  external_dependency_handoff_version: string;
  generated_at: string;
  status: string;
  external_dependency_handoff_ready: boolean;
  ready_for_customer_report_handoff: boolean;
  next_dependency_item_id: string;
  external_dependency_handoff_hash: string;
  summary?: {
    handoff_posture?: string;
    structural_ready?: boolean;
    external_dependency_handoff_ready?: boolean;
    all_blockers_mapped?: boolean;
    blocker_count?: number;
    external_dependency_blocker_count?: number;
    work_item_count?: number;
    dependency_group_count?: number;
    clearance_step_count?: number;
    clearance_ready_step_count?: number;
    clearance_blocked_step_count?: number;
    clearance_current_step_id?: string;
    requires_external_input_work_item_count?: number;
    pending_after_external_input_work_item_count?: number;
    runnable_now_work_item_count?: number;
    p0a_required_secret_missing_count?: number;
    p0a_required_secret_missing?: string[];
    p0a_real_batch_phase_next_phase?: string;
    p0a_real_batch_blocked_phase_count?: number;
    p0a_real_batch_total_planned_runs?: number;
    p0b_google_required_input_missing_count?: number;
    p0b_google_environment_missing_required_count?: number;
    p0b_google_manual_backfill_missing_reason_count?: number;
    p0b_google_manual_backfill_record_count?: number;
    p0b_google_manual_backfill_expected_record_count?: number;
    p0b_google_phase_next_phase?: string;
    p0b_google_phase_blocked_phase_count?: number;
    p0b_google_full_spike_planned_runs?: number;
  };
  dependency_groups?: Array<{
    id: string;
    stage?: string;
    title?: string;
    status?: string;
    ready?: boolean;
    dependency_class?: string;
    missing_required_count?: number;
    missing_required?: string[];
    missing_reason_count?: number;
    missing_reasons?: string[];
    next_phase?: string;
    blocked_phase_count?: number;
    total_planned_runs?: number;
    full_spike_planned_runs?: number;
    expected_record_count?: number;
    record_count?: number;
    work_item_ids?: string[];
    commands?: string[];
    next_command?: string | null;
    blocking_reasons?: string[];
  }>;
  clearance_sequence?: {
    version?: string;
    current_step_id?: string;
    next_command?: string;
    step_count?: number;
    ready_step_count?: number;
    blocked_step_count?: number;
    steps?: Array<{
      id: string;
      order?: number;
      title?: string;
      status?: string;
      ready?: boolean;
      can_start?: boolean;
      blocked_by?: string[];
      verification_commands?: string[];
    }>;
  };
  work_items?: Array<{
    id: string;
    stage?: string;
    status?: string;
    title?: string;
    dependency_class?: string;
    blocker_count?: number;
    required_inputs?: string[];
  }>;
  next_dependency_item?: {
    id?: string;
    stage?: string;
    title?: string;
    status?: string;
    dependency_class?: string;
    blocker_count?: number;
  };
};

type AuExternalDependencyClearance = {
  clearance_execution_version: string;
  generated_at: string;
  mode: string;
  status: string;
  ready_to_execute: boolean;
  external_dependency_handoff_ready: boolean;
  clearance_execution_hash: string;
  clearance_sequence_version: string;
  planned_step_count: number;
  recorded_step_count: number;
  ready_step_count: number;
  blocked_step_count: number;
  would_execute_step_count: number;
  current_step_id: string;
  next_command: string;
  current_step_request_context?: ClearanceRequestContext;
  current_recommended_sequence?: string[];
  current_recommended_sequence_count?: number;
  current_strict_gate_command?: string;
  hard_gate_commands?: string[];
  errors?: string[];
  steps?: Array<{
    id: string;
    index?: number;
    title?: string;
    status?: string;
    ready?: boolean;
    can_start?: boolean;
    would_execute?: boolean;
    blocked_by?: string[];
    verification_commands?: string[];
    evidence_outputs?: string[];
    linked_request_context?: ClearanceRequestContext;
    recommended_sequence?: string[];
    recommended_sequence_count?: number;
    strict_gate_command?: string;
  }>;
};

type ClearanceRequestContext = {
  request_context_version?: string;
  clearance_step_id?: string;
  request_context_available?: boolean;
  artifact_type?: string;
  request_artifact_id?: string;
  request_artifact_title?: string;
  output_path?: string;
  exists?: boolean;
  hash_field?: string;
  artifact_hash?: string;
  file_sha256?: string;
  build_command?: string;
  verify_command?: string;
  strict_gate_command?: string;
  runtime_endpoint?: string;
};

type RuntimeProjectBrandKit = {
  brand_kit: {
    id: string;
    project_id: string;
    client_name: string;
    prepared_by: string;
    logo_url?: string | null;
    primary_color?: string | null;
    secondary_color?: string | null;
    footer_text?: string | null;
    updated_by: string;
    created_at?: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeProjectBrandAssetVersion = {
  version_id: string;
  project_id: string;
  asset_type: string;
  asset_url: string;
  source_filename?: string | null;
  source_content_type?: string | null;
  content_hash?: string | null;
  uploaded_by?: string | null;
  uploaded_at?: string | null;
  is_active: boolean;
  audit_event?: { event_type?: string; method_version?: string | null };
};

type RuntimeProjectBrandAsset = {
  asset: {
    id: string;
    project_id: string;
    asset_type: string;
    asset_url: string;
    category: string;
    preview_url?: string | null;
    source_filename?: string | null;
    source_content_type?: string | null;
    content_hash?: string | null;
    storage_version?: string | null;
    status: string;
    scan_status?: string;
    scan_checked_at?: string | null;
    scan_method_version?: string | null;
    scan_notes?: string | null;
    uploaded_by: string;
    metadata?: Record<string, unknown>;
    created_at?: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null; after_hash?: string | null }>;
};

type RuntimeReportExportJob = {
  report_export_job: {
    id: string;
    project_id: string;
    report_export_id?: string | null;
    status: string;
    artifact_type: string;
    template: string;
    filters: Record<string, unknown>;
    sort: string;
    requested_by: string;
    requested_at?: string;
    started_at?: string | null;
    completed_at?: string | null;
    attempt_count?: number;
    max_attempts?: number;
    lease_expires_at?: string | null;
    next_attempt_at?: string | null;
    artifact_url?: string | null;
    error_message?: string | null;
    updated_by: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; reason?: string | null; method_version?: string | null }>;
};

type RuntimeReportExportJobQueueStats = {
  total_count: number;
  status_counts: Record<string, number>;
  retryable_count: number;
  expired_running_count: number;
  max_attempts_reached_count: number;
  oldest_queued_at?: string | null;
  generated_at?: string;
};

type RuntimeNotificationPage = PageResponse<RuntimeNotification> & {
  unread_count: number;
};

type RuntimeNotification = {
  notification: {
    id: string;
    project_id: string;
    notification_type: string;
    severity: string;
    title: string;
    message: string;
    target_type: string;
    target_id: string;
    recipient_role: string;
    status: string;
    payload: Record<string, unknown>;
    created_by: string;
    created_at?: string;
    read_at?: string | null;
    updated_by: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null }>;
};

type RuntimeNotificationSubscription = {
  subscription: {
    id: string;
    project_id: string;
    channel: string;
    endpoint_url: string;
    event_types: string[];
    severity_threshold: string;
    status: string;
    metadata?: Record<string, unknown>;
    created_by: string;
    created_at?: string;
    updated_by: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null }>;
};

type RuntimeNotificationDelivery = {
  delivery: {
    id: string;
    project_id: string;
    notification_id: string;
    subscription_id: string;
    channel: string;
    endpoint_url: string;
    status: string;
    attempt_count: number;
    max_attempts: number;
    lease_expires_at?: string | null;
    next_attempt_at?: string | null;
    response_status?: number | null;
    response_body_hash?: string | null;
    error_message?: string | null;
    payload?: Record<string, unknown>;
    created_at?: string;
    updated_by: string;
    updated_at?: string;
  };
  notification?: RuntimeNotification["notification"] | null;
  subscription?: RuntimeNotificationSubscription["subscription"] | null;
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null }>;
};

type RuntimeNotificationEmailFeedback = {
  feedback_event: {
    id: string;
    project_id: string;
    delivery_id: string;
    notification_id: string;
    subscription_id: string;
    feedback_type: string;
    recipient_hash?: string | null;
    provider?: string | null;
    provider_event_id_hash?: string | null;
    occurred_at?: string;
    metadata?: Record<string, unknown>;
    recorded_by: string;
    created_at?: string;
  };
  delivery: RuntimeNotificationDelivery["delivery"];
  notification?: RuntimeNotification["notification"] | null;
  subscription?: RuntimeNotificationSubscription["subscription"] | null;
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null }>;
};

type RuntimeNotificationEmailSuppression = {
  suppression: {
    id: string;
    project_id: string;
    recipient_hash: string;
    status: string;
    source: string;
    source_ref?: string | null;
    metadata?: Record<string, unknown>;
    created_by: string;
    created_at?: string;
    updated_by: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; method_version?: string | null }>;
};

type RuntimeScoreWeightConfig = {
  score_weight_config: {
    id?: string | null;
    project_id: string;
    formula_version: string;
    weights: Record<string, number>;
    updated_by: string;
    notes?: string | null;
    created_at?: string;
    updated_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeScoreFormulaCatalog = {
  formulas: Array<{
    formula_version: string;
    weights: Record<string, number>;
    description: string;
    status: string;
    supersedes?: string | null;
  }>;
};

type RuntimeHumanReview = {
  human_review: {
    id: string;
    project_id: string;
    target_type: string;
    target_id: string;
    review_status: string;
    decision: string;
    reviewer_id: string;
    notes?: string | null;
    payload?: Record<string, unknown>;
    created_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeHumanReviewQueueItem = {
  project_id: string;
  target_type: string;
  target_id: string;
  title: string;
  queue_status: string;
  priority: number;
  reason: string;
  created_at?: string | null;
  latest_review?: {
    id?: string;
    review_status?: string;
    decision?: string;
    reviewer_id?: string;
    notes?: string | null;
    created_at?: string | null;
  } | null;
  evidence_refs: Record<string, unknown>;
};

type RuntimeKnowledgeSearch = {
  total_count: number;
  limit: number;
  offset: number;
  query: string;
  market_code: string;
  city?: string | null;
  embedding_model: string;
  records: Array<{
    fact: {
      id: string;
      market_code?: string;
      fact_type?: string;
      subject?: string;
      predicate?: string;
      object_value?: string;
      city?: string | null;
      evidence_source_id?: string | null;
      confidence?: number;
      status?: string;
    };
    score: number;
    fallback_used: boolean;
    embedding_model: string;
  }>;
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeFidelityCheck = {
  fidelity_check: {
    id: string;
    project_id: string;
    report_export_id?: string | null;
    status: string;
    official_api_records: number;
    browser_records: number;
    comparable_prompt_city_pairs: number;
    mismatch_count: number;
    difference_rate?: number | null;
    payload?: {
      summary?: string;
      status?: string;
      official_api_records?: number;
      browser_records?: number;
      comparable_prompt_city_pairs?: number;
      mismatch_count?: number;
      difference_rate?: number | null;
    } & Record<string, unknown>;
    payload_hash?: string;
    answer_run_ids?: string[];
    checked_by: string;
    checked_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeFidelityTrend = {
  project_id?: string | null;
  report_export_id?: string | null;
  total_count: number;
  sampled_count: number;
  limit: number;
  latest_status?: string | null;
  latest_checked_at?: string | null;
  earliest_checked_at?: string | null;
  latest_difference_rate?: number | null;
  earliest_difference_rate?: number | null;
  average_difference_rate?: number | null;
  max_difference_rate?: number | null;
  trend_direction: string;
  points: Array<{
    id: string;
    project_id: string;
    report_export_id?: string | null;
    status: string;
    official_api_records: number;
    browser_records: number;
    comparable_prompt_city_pairs: number;
    mismatch_count: number;
    difference_rate?: number | null;
    payload_hash?: string | null;
    checked_at?: string | null;
  }>;
};

type RuntimeEntityAlias = {
  entity_alias: {
    id: string;
    entity_id: string;
    entity_kind: string;
    alias: string;
    alias_type: string;
    confidence?: number;
    confirmed_by?: string | null;
    created_at?: string;
  };
  entity: {
    id: string;
    project_id: string;
    entity_kind: string;
    canonical_name: string;
    official_domains?: string[];
    status?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeEntityAliasBatchItem = {
  entity_id: string;
  entity_kind: string;
  alias: string;
  alias_type: string;
  confidence?: number;
  notes?: string;
};

type RuntimeEntityAliasCandidateBatchReviewItem = {
  project_id: string;
  candidate_id: string;
  entity_id: string;
  entity_kind: string;
  alias: string;
  alias_type: string;
  source?: string;
  confidence?: number;
  evidence_answer_run_ids?: string[];
  evidence_urls?: string[];
};

type RuntimeEntityAliasCandidate = {
  candidate: {
    id: string;
    entity_id: string;
    entity_kind: string;
    alias: string;
    alias_type: string;
    source: string;
    confidence?: number;
    reason?: string;
    evidence_count?: number;
    evidence_answer_run_ids?: string[];
    evidence_urls?: string[];
    latest_review?: {
      decision?: string;
      reviewed_by?: string;
      notes?: string | null;
      updated_at?: string;
    };
  };
  entity: {
    id: string;
    project_id: string;
    entity_kind: string;
    canonical_name: string;
    status?: string;
  };
  confirmed_aliases: string[];
};

type RuntimeEntityAliasCandidateReview = {
  review: {
    id: string;
    project_id: string;
    candidate_id: string;
    entity_id: string;
    entity_kind: string;
    alias: string;
    alias_type: string;
    source?: string | null;
    confidence?: number | null;
    decision: string;
    reviewed_by?: string | null;
    reason?: string | null;
    notes?: string | null;
    assigned_to?: string | null;
    assigned_by?: string | null;
    assignment_status?: string | null;
    assignment_note?: string | null;
    assigned_at?: string | null;
    due_at?: string | null;
    priority?: string | null;
    evidence_answer_run_ids?: string[];
    evidence_urls?: string[];
    updated_at?: string;
    created_at?: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type RuntimeEntityAliasCandidateAssignmentQueueStats = {
  project_id: string;
  generated_at: string;
  method_version: string;
  active_statuses: string[];
  total_count: number;
  active_count: number;
  unassigned_count: number;
  overdue_count: number;
  due_soon_count: number;
  status_counts: Record<string, number>;
  priority_counts: Record<string, number>;
  oldest_due_at?: string | null;
  next_due_at?: string | null;
};

type RuntimeEntityAliasAssignmentWorkbench = {
  project_id: string;
  reviewer_id?: string | null;
  generated_at: string;
  method_version: string;
  active_statuses: string[];
  total_count: number;
  active_count: number;
  overdue_count: number;
  due_soon_count: number;
  escalated_count: number;
  blocked_count: number;
  status_counts: Record<string, number>;
  priority_counts: Record<string, number>;
  oldest_due_at?: string | null;
  next_due_at?: string | null;
  records: RuntimeEntityAliasCandidateReview[];
};

type RuntimeEntityAliasAssignmentWorkloadReviewer = {
  reviewer_id: string;
  active_count: number;
  overdue_count: number;
  due_soon_count: number;
  escalated_count: number;
  blocked_count: number;
  urgent_count: number;
  high_count: number;
  oldest_due_at?: string | null;
  next_due_at?: string | null;
  status_counts: Record<string, number>;
  priority_counts: Record<string, number>;
};

type RuntimeEntityAliasAssignmentWorkloadSummary = {
  project_id: string;
  generated_at: string;
  method_version: string;
  active_statuses: string[];
  total_active_count: number;
  unassigned_count: number;
  reviewer_count: number;
  overdue_count: number;
  due_soon_count: number;
  escalated_count: number;
  blocked_count: number;
  reviewer_loads: RuntimeEntityAliasAssignmentWorkloadReviewer[];
};

type RuntimeEntityAliasAssignmentDispatchPlan = {
  project_id: string;
  generated_at: string;
  method_version: string;
  dry_run: boolean;
  strategy: string;
  include_statuses: string[];
  reviewer_ids: string[];
  active_statuses: string[];
  max_per_reviewer: number;
  candidate_count: number;
  planned_assignment_count: number;
  skipped_count: number;
  reviewer_loads: Array<{
    reviewer_id: string;
    current_active_count: number;
    planned_assignment_count: number;
    planned_active_count: number;
    capacity_remaining: number;
    over_capacity: boolean;
  }>;
  proposed_assignments: Array<{
    order: number;
    review_id: string;
    candidate_id: string;
    alias?: string | null;
    current_assigned_to?: string | null;
    current_assignment_status?: string | null;
    priority?: string | null;
    due_at?: string | null;
    recommended_assigned_to: string;
    recommended_assignment_status: string;
    reason: string;
  }>;
  skipped_candidates: Array<{ candidate_id?: string | null; assignment_status?: string | null; reason: string }>;
  source_summary: Record<string, unknown>;
};

type RuntimeFilters = {
  project_id?: string;
  platform?: string;
  city?: string;
  intent_type?: string;
  sort?: string;
};

type RuntimeSavedView = {
  saved_view: {
    id: string;
    project_id: string;
    name: string;
    view_type: string;
    filters: Record<string, unknown>;
    sort: string;
    query_path: string;
    export_path: string;
    created_by: string;
    created_at: string;
    updated_at: string;
  };
  audit_events: Array<{ event_type?: string; actor_id?: string; after_hash?: string | null; method_version?: string | null }>;
};

type QuestionCoverageStatus = "covered" | "no_evidence" | "platform_gap" | "trigger_gap" | "answer_gap" | "source_gap";

type QuestionDetailRow = {
  prompt: RuntimePrompt;
  evidenceRuns: EvidenceRun[];
  runCount: number;
  answerCount: number;
  triggeredCount: number;
  citationCount: number;
  assetCount: number;
  auditCount: number;
  totalCost: number;
  averageDurationMs: number;
  platforms: string[];
  requiredPlatforms: string[];
  missingPlatforms: string[];
  cities: string[];
  accessMethods: string[];
  surfaceCounts: Record<string, number>;
  statusCounts: Record<string, number>;
  latestRun?: EvidenceRun;
  status: QuestionCoverageStatus;
  gapLabel: string;
};

const endpoints = {
  launchStatus: "/v1/launch-status/au",
  launchRemediationPlan: "/v1/launch-remediation-plan/au",
  p0aEnvironmentChecklist: "/v1/p0a-environment-checklist/au",
  p0aExecutionChecklist: "/v1/p0a-execution-checklist/au",
  p0aCredentialRequest: "/v1/p0a-credential-request/au",
  p0aCredentialFulfillment: "/v1/p0a-credential-fulfillment/au",
  p0aCredentialClearance: "/v1/p0a-credential-clearance/au",
  p0aRealBatchRequest: "/v1/p0a-real-batch-request/au",
  p0aRealBatchFulfillment: "/v1/p0a-real-batch-fulfillment/au",
  p0aRealBatchClearance: "/v1/p0a-real-batch-clearance/au",
  p0bGoogleExecutionChecklist: "/v1/p0b-google-execution-checklist/au",
  p0bGoogleEnvironmentRequest: "/v1/p0b-google-environment-request/au",
  p0bGoogleEnvironmentFulfillment: "/v1/p0b-google-environment-fulfillment/au",
  p0bGoogleEnvironmentClearance: "/v1/p0b-google-environment-clearance/au",
  p0bGoogleManualBackfillRequest: "/v1/p0b-google-manual-backfill-request/au",
  p0bGoogleManualBackfillFulfillment: "/v1/p0b-google-manual-backfill-fulfillment/au",
  p0bGoogleManualBackfillClearance: "/v1/p0b-google-manual-backfill-clearance/au",
  p0bGooglePhaseExecutionRequest: "/v1/p0b-google-phase-execution-request/au",
  p0bGooglePhaseExecutionFulfillment: "/v1/p0b-google-phase-execution-fulfillment/au",
  p0bGooglePhaseExecutionClearance: "/v1/p0b-google-phase-execution-clearance/au",
  externalDependencyHandoff: "/v1/external-dependency-handoff/au",
  externalDependencyClearance: "/v1/external-dependency-clearance/au",
  broaderPlatformRegistry: "/v1/au-broader-platform-registry",
  retestSchedulerPlan: "/v1/au-retest-scheduler-plan",
  retestExecutionStatus: "/v1/au-retest-execution-status",
  handoffDossier: "/v1/handoff-dossier/au",
  customerHandoffReadiness: "/v1/customer-handoff-readiness/au",
  customerHandoffClearance: "/v1/customer-handoff-clearance/au",
  nextWorkItem: "/v1/next-work-item/au",
  deliveryProgress: "/v1/delivery-progress/au",
  projects: "/v1/projects/runtime",
  projectAction: "/v1/projects/runtime/action",
  projectLifecycleEvents: "/v1/projects/runtime/lifecycle-events",
  projectLifecycleExport: "/v1/projects/runtime/lifecycle-events/export.csv",
  auditEvents: "/v1/audit-events/runtime",
  auditEventsExport: "/v1/audit-events/runtime/export.csv",
  projectMembers: "/v1/project-members/runtime",
  projectMemberInvitations: "/v1/project-member-invitations/runtime",
  projectMemberInvitationAction: "/v1/project-member-invitations/runtime/action",
  projectMemberInvitationEmail: "/v1/project-member-invitations/runtime/email",
  projectMemberInvitationAccept: "/v1/project-member-invitations/runtime/accept",
  prompts: "/v1/prompts/runtime",
  promptImports: "/v1/prompts/runtime/imports",
  evidence: "/v1/evidence-runs/runtime",
  collectionRuns: "/v1/collection-runs/runtime",
  fidelityChecks: "/v1/fidelity-checks/runtime",
  fidelityTrend: "/v1/fidelity-checks/runtime/trend",
  evidenceExport: "/v1/evidence-runs/runtime/export.csv",
  entityAliases: "/v1/entity-aliases/runtime",
  entityAliasCandidates: "/v1/entity-aliases/runtime/candidates",
  entityAliasCandidateReviews: "/v1/entity-aliases/runtime/candidates/reviews",
  entityAliasAssignmentQueue: "/v1/entity-aliases/runtime/candidates/reviews",
  entityAliasAssignmentStats: "/v1/entity-aliases/runtime/candidates/assignment-stats",
  entityAliasAssignmentWorkbench: "/v1/entity-aliases/runtime/candidates/assignment-workbench",
  entityAliasAssignmentWorkload: "/v1/entity-aliases/runtime/candidates/assignment-workload",
  entityAliasAssignmentDispatchPlan: "/v1/entity-aliases/runtime/candidates/assignment-dispatch-plan",
  entityAliasAssignmentDispatchApply: "/v1/entity-aliases/runtime/candidates/assignment-dispatch-apply",
  entityAliasAssignmentAction: "/v1/entity-aliases/runtime/candidates/assignment-action",
  entityAliasAssignmentBatchAction: "/v1/entity-aliases/runtime/candidates/assignment-actions",
  entityAliasConfirmBatch: "/v1/entity-aliases/runtime/confirm-batch",
  savedViews: "/v1/runtime-saved-views",
  brandKit: "/v1/project-brand-kits/runtime",
  brandAssets: "/v1/project-brand-kits/runtime/assets",
  brandAssetLibrary: "/v1/project-brand-assets/runtime",
  scoreWeights: "/v1/score-weight-configs/runtime",
  scoreFormulas: "/v1/score-formulas/runtime",
  humanReviews: "/v1/human-reviews/runtime",
  humanReviewQueue: "/v1/human-reviews/runtime/queue",
  knowledgeSearch: "/v1/knowledge-facts/runtime/search",
  scores: "/v1/visibility-scores/runtime",
  graphs: "/v1/citation-graphs/runtime",
  reports: "/v1/reports/runtime",
  reportJobs: "/v1/report-export-jobs/runtime",
  reportJobsExport: "/v1/report-export-jobs/runtime/export.csv",
  reportJobStats: "/v1/report-export-jobs/runtime/stats",
  notifications: "/v1/runtime-notifications",
  notificationsExport: "/v1/runtime-notifications/export.csv",
  notificationSubscriptions: "/v1/runtime-notification-subscriptions",
  notificationSubscriptionsExport: "/v1/runtime-notification-subscriptions/export.csv",
  notificationDeliveries: "/v1/runtime-notification-deliveries",
  notificationDeliveriesExport: "/v1/runtime-notification-deliveries/export.csv",
  notificationEmailFeedback: "/v1/runtime-notification-email-feedback-events",
  notificationEmailSuppressions: "/v1/runtime-notification-email-suppressions",
  notificationEmailSuppressionsExport: "/v1/runtime-notification-email-suppressions/export.csv",
  notificationEmailFeedbackWebhook: "/v1/runtime-notification-email-feedback-webhooks/geno",
  notificationEmailPreferenceStatus: "/v1/runtime-notification-email-preferences/status",
  notificationEmailPreferenceResubscribe: "/v1/runtime-notification-email-preferences/resubscribe",
  notificationEmailPreferenceUnsubscribe: "/v1/runtime-notification-email-preferences/unsubscribe",
  actions: "/v1/action-plans/runtime",
  alerts: "/v1/runtime-alerts",
  alertNotifications: "/v1/runtime-alerts/notifications",
  entityAliasAssignmentNotifications: "/v1/entity-aliases/runtime/candidates/assignment-notifications",
  entityAliasAssignmentEscalations: "/v1/entity-aliases/runtime/candidates/assignment-escalations",
  entityAliasAssignmentReassignments: "/v1/entity-aliases/runtime/candidates/assignment-reassignments",
  content: "/v1/content-engines/runtime",
  traceability: "/v1/traceability/runtime"
} as const;

const brandLogoEndpoint = "/v1/project-brand-kits/runtime/logo";

function projectBrandAssetScanPath(assetId: string) {
  return `/v1/project-brand-assets/runtime/${assetId}/scan-status`;
}

function runtimeAlertEventPath(alertId: string) {
  return `/v1/runtime-alerts/${alertId}/events`;
}

const emptyPage = <T,>(): PageResponse<T> => ({ total_count: 0, records: [] });

const emptyAliasAssignmentStats = (): RuntimeEntityAliasCandidateAssignmentQueueStats => ({
  project_id: "",
  generated_at: "",
  method_version: "entity_alias_assignment_queue_stats_v1",
  active_statuses: ["assigned", "in_progress", "blocked", "escalated"],
  total_count: 0,
  active_count: 0,
  unassigned_count: 0,
  overdue_count: 0,
  due_soon_count: 0,
  status_counts: {},
  priority_counts: {},
  oldest_due_at: null,
  next_due_at: null
});

const emptyAliasAssignmentWorkbench = (): RuntimeEntityAliasAssignmentWorkbench => ({
  project_id: "",
  reviewer_id: "runtime-console",
  generated_at: "",
  method_version: "entity_alias_assignment_workbench_v1",
  active_statuses: ["assigned", "in_progress", "blocked", "escalated"],
  total_count: 0,
  active_count: 0,
  overdue_count: 0,
  due_soon_count: 0,
  escalated_count: 0,
  blocked_count: 0,
  status_counts: {},
  priority_counts: {},
  oldest_due_at: null,
  next_due_at: null,
  records: []
});

const emptyAliasAssignmentWorkload = (): RuntimeEntityAliasAssignmentWorkloadSummary => ({
  project_id: "",
  generated_at: "",
  method_version: "entity_alias_assignment_workload_v1",
  active_statuses: ["assigned", "in_progress", "blocked", "escalated"],
  total_active_count: 0,
  unassigned_count: 0,
  reviewer_count: 0,
  overdue_count: 0,
  due_soon_count: 0,
  escalated_count: 0,
  blocked_count: 0,
  reviewer_loads: []
});

const emptyAliasAssignmentDispatchPlan = (): RuntimeEntityAliasAssignmentDispatchPlan => ({
  project_id: "",
  generated_at: "",
  method_version: "entity_alias_assignment_dispatch_plan_v1",
  dry_run: true,
  strategy: "least_loaded_round_robin",
  include_statuses: ["unassigned", "escalated"],
  reviewer_ids: [],
  active_statuses: ["assigned", "in_progress", "blocked", "escalated"],
  max_per_reviewer: 10,
  candidate_count: 0,
  planned_assignment_count: 0,
  skipped_count: 0,
  reviewer_loads: [],
  proposed_assignments: [],
  skipped_candidates: [],
  source_summary: {}
});

const scoreComponentNames = [
  "MentionScore",
  "RecommendationScore",
  "PositionScore",
  "CitationScore",
  "LocalRelevanceScore",
  "SentimentScore",
  "FreshnessScore",
  "CompetitorShareScore"
] as const;

const defaultScoreWeights: Record<string, number> = {
  MentionScore: 0.18,
  RecommendationScore: 0.22,
  PositionScore: 0.12,
  CitationScore: 0.16,
  LocalRelevanceScore: 0.14,
  SentimentScore: 0.08,
  FreshnessScore: 0.05,
  CompetitorShareScore: 0.05
};

export const dynamic = "force-dynamic";

async function createAuRuntimeProject(formData?: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const itemList = (field: string): string[] =>
    String(formData?.get(field) || "")
      .split(/\r?\n|,/)
      .map((item) => item.trim())
      .filter(Boolean);
  const payload = formData
    ? {
        tenant_name: String(formData.get("tenant_name") || "Design Partner AU").trim(),
        project_name: String(formData.get("project_name") || "AU DTC Evidence Pilot").trim(),
        target_brand: String(formData.get("target_brand") || "ExampleBrand").trim(),
        category: String(formData.get("category") || "DTC ecommerce products").trim(),
        competitors: itemList("competitors"),
        brand_official_domains: itemList("brand_official_domains"),
        brand_parent_company: String(formData.get("brand_parent_company") || "").trim() || undefined,
        brand_product_lines: itemList("brand_product_lines"),
        owner_user_id: String(formData.get("owner_user_id") || "runtime-console").trim()
      }
    : undefined;
  const response = await fetch(`${baseUrl}/v1/projects/runtime/au/dtc-ecommerce`, {
    method: "POST",
    headers: payload ? { "content-type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/projects/runtime/au/dtc-ecommerce returned ${response.status}`);
  }
  revalidatePath("/");
}

async function updateRuntimeProject(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  if (!projectId) {
    throw new Error("project_id is required to update a runtime project");
  }
  const payload = {
    project_id: projectId,
    name: String(formData.get("name") || "").trim(),
    target_brand: String(formData.get("target_brand") || "").trim(),
    category: String(formData.get("category") || "").trim(),
    status: String(formData.get("status") || "").trim(),
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "Update runtime project metadata").trim()
  };
  const response = await fetch(`${baseUrl}/v1/projects/runtime`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/projects/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function actionRuntimeProject(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const action = String(formData.get("action") || "").trim();
  if (!projectId || !action) {
    throw new Error("project_id and action are required to change a runtime project lifecycle state");
  }
  const payload = {
    project_id: projectId,
    action,
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || `Runtime project ${action}`).trim()
  };
  const response = await fetch(`${baseUrl}${endpoints.projectAction}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${endpoints.projectAction} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveCurrentRuntimeView(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const name = String(formData.get("name") || "").trim() || "Runtime evidence view";
  if (!projectId) {
    throw new Error("project_id is required to save a runtime view");
  }
  const payload = {
    project_id: projectId,
    name,
    view_type: "runtime_evidence",
    filters: {
      platform: String(formData.get("platform") || "").trim() || undefined,
      city: String(formData.get("city") || "").trim() || undefined,
      intent_type: String(formData.get("intent_type") || "").trim() || undefined
    },
    sort: String(formData.get("sort") || "collected_at_desc").trim(),
    query_path: String(formData.get("query_path") || "").trim(),
    export_path: String(formData.get("export_path") || "").trim(),
    created_by: "runtime-console"
  };
  const response = await fetch(`${baseUrl}/v1/runtime-saved-views`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/runtime-saved-views returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveProjectBrandKit(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const clientName = String(formData.get("client_name") || "").trim();
  if (!projectId || !clientName) {
    throw new Error("project_id and client_name are required to save a project brand kit");
  }
  const optionalText = (field: string): string | undefined =>
    String(formData.get(field) || "").trim() || undefined;
  const payload = {
    project_id: projectId,
    client_name: clientName,
    prepared_by: String(formData.get("prepared_by") || "GENO SaaS AU").trim(),
    logo_url: optionalText("logo_url"),
    primary_color: optionalText("primary_color"),
    secondary_color: optionalText("secondary_color"),
    footer_text: optionalText("footer_text"),
    updated_by: "runtime-console"
  };
  const response = await fetch(`${baseUrl}/v1/project-brand-kits/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-brand-kits/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function activateProjectBrandAssetVersion(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const assetUrl = String(formData.get("asset_url") || "").trim();
  if (!projectId || !assetUrl) {
    throw new Error("project_id and asset_url are required to activate a brand asset version");
  }
  const payload = {
    project_id: projectId,
    asset_url: assetUrl,
    activated_by: String(formData.get("activated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-brand-kits/runtime/assets/activate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-brand-kits/runtime/assets/activate returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveProjectBrandAsset(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const assetUrl = String(formData.get("asset_url") || "").trim();
  if (!projectId || !assetUrl) {
    throw new Error("project_id and asset_url are required to register a brand asset");
  }
  const optionalText = (field: string): string | undefined =>
    String(formData.get(field) || "").trim() || undefined;
  const payload = {
    project_id: projectId,
    asset_type: String(formData.get("asset_type") || "image").trim(),
    asset_url: assetUrl,
    category: String(formData.get("category") || "uncategorized").trim(),
    preview_url: optionalText("preview_url"),
    source_filename: optionalText("source_filename"),
    source_content_type: optionalText("source_content_type"),
    content_hash: optionalText("content_hash"),
    storage_version: optionalText("storage_version"),
    status: String(formData.get("status") || "active").trim(),
    uploaded_by: String(formData.get("uploaded_by") || "runtime-console").trim(),
    metadata: {
      source: "runtime_console_asset_register",
      preview_hint: optionalText("preview_hint")
    },
    reason: optionalText("reason")
  };
  const response = await fetch(`${baseUrl}/v1/project-brand-assets/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-brand-assets/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function updateProjectBrandAssetScanStatus(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const assetId = String(formData.get("asset_id") || "").trim();
  if (!assetId) {
    throw new Error("asset_id is required to update project brand asset scan status");
  }
  const optionalText = (field: string): string | undefined =>
    String(formData.get(field) || "").trim() || undefined;
  const payload = {
    scan_status: String(formData.get("scan_status") || "pending").trim(),
    scanned_by: String(formData.get("scanned_by") || "runtime-console").trim(),
    scan_method_version: String(formData.get("scan_method_version") || "manual_asset_scan_v1").trim(),
    scan_notes: optionalText("scan_notes"),
    reason: optionalText("reason")
  };
  const response = await fetch(`${baseUrl}${projectBrandAssetScanPath(assetId)}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${projectBrandAssetScanPath(assetId)} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function recordRuntimeReportManagementEvent(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const reportExportId = String(formData.get("report_export_id") || "").trim();
  if (!reportExportId) {
    throw new Error("report_export_id is required to record report management event");
  }
  const payload = {
    status: String(formData.get("status") || "internal_review").trim(),
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    note: String(formData.get("note") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/reports/runtime/${reportExportId}/management-events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/reports/runtime/${reportExportId}/management-events returned ${response.status}`);
  }
  revalidatePath("/");
}

async function recordRuntimeAlertEvent(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const alertId = String(formData.get("alert_id") || "").trim();
  const projectId = String(formData.get("project_id") || "").trim();
  if (!alertId || !projectId) {
    throw new Error("alert_id and project_id are required to record runtime alert event");
  }
  const payload = {
    project_id: projectId,
    alert_type: String(formData.get("alert_type") || "").trim(),
    source: String(formData.get("source") || "").trim(),
    source_id: String(formData.get("source_id") || "").trim(),
    status: String(formData.get("status") || "acknowledged").trim(),
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    note: String(formData.get("note") || "").trim() || undefined,
    metadata: {
      source: "runtime_console_alert_event",
      severity: String(formData.get("severity") || "").trim() || undefined
    }
  };
  const response = await fetch(`${baseUrl}${runtimeAlertEventPath(alertId)}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${runtimeAlertEventPath(alertId)} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function enqueueRuntimeAlertNotifications(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  if (!projectId) {
    throw new Error("project_id is required to enqueue runtime alert notifications");
  }
  const payload = {
    project_id: projectId,
    alert_type: String(formData.get("alert_type") || "").trim() || undefined,
    severity: String(formData.get("severity") || "").trim() || undefined,
    created_by: String(formData.get("created_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined,
    include_resolved: String(formData.get("include_resolved") || "") === "on"
  };
  const response = await fetch(`${baseUrl}${endpoints.alertNotifications}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${endpoints.alertNotifications} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function enqueueEntityAliasAssignmentNotifications(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  if (!projectId) {
    throw new Error("project_id is required to enqueue alias assignment notifications");
  }
  const payload = {
    project_id: projectId,
    assigned_to: String(formData.get("assigned_to") || "").trim() || undefined,
    priority: String(formData.get("priority") || "").trim() || undefined,
    due_before: String(formData.get("due_before") || "").trim() || undefined,
    created_by: String(formData.get("created_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}${endpoints.entityAliasAssignmentNotifications}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${endpoints.entityAliasAssignmentNotifications} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function escalateEntityAliasAssignmentReviews(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  if (!projectId) {
    throw new Error("project_id is required to escalate alias assignment reviews");
  }
  const payload = {
    project_id: projectId,
    assigned_to: String(formData.get("assigned_to") || "").trim() || undefined,
    priority: String(formData.get("priority") || "").trim() || undefined,
    due_before: String(formData.get("due_before") || "").trim() || undefined,
    escalated_by: String(formData.get("escalated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}${endpoints.entityAliasAssignmentEscalations}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${endpoints.entityAliasAssignmentEscalations} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function reassignEntityAliasAssignmentReviews(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const assignedTo = String(formData.get("assigned_to") || "").trim();
  if (!projectId || !assignedTo) {
    throw new Error("project_id and assigned_to are required to reassign alias assignment reviews");
  }
  const payload = {
    project_id: projectId,
    assigned_to: assignedTo,
    reassigned_by: String(formData.get("reassigned_by") || "runtime-console").trim(),
    from_assigned_to: String(formData.get("from_assigned_to") || "").trim() || undefined,
    from_assignment_status: String(formData.get("from_assignment_status") || "").trim() || undefined,
    from_priority: String(formData.get("from_priority") || "").trim() || undefined,
    due_before: String(formData.get("due_before") || "").trim() || undefined,
    assignment_status: String(formData.get("assignment_status") || "assigned").trim(),
    priority: String(formData.get("priority") || "high").trim(),
    due_at: String(formData.get("due_at") || "").trim() || undefined,
    assignment_note: String(formData.get("assignment_note") || "").trim() || undefined,
    reason: String(formData.get("reason") || "").trim() || undefined,
    limit: Number(String(formData.get("limit") || "50").trim() || "50")
  };
  const response = await fetch(`${baseUrl}${endpoints.entityAliasAssignmentReassignments}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${endpoints.entityAliasAssignmentReassignments} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function enqueueRuntimeReportExportJob(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  if (!projectId) {
    throw new Error("project_id is required to enqueue report export job");
  }
  const filters = {
    platform: String(formData.get("platform") || "").trim() || undefined,
    city: String(formData.get("city") || "").trim() || undefined,
    intent_type: String(formData.get("intent_type") || "").trim() || undefined,
    status: String(formData.get("evidence_status") || "").trim() || undefined
  };
  const payload = {
    project_id: projectId,
    report_export_id: String(formData.get("report_export_id") || "").trim() || undefined,
    artifact_type: String(formData.get("artifact_type") || "pdf").trim(),
    template: String(formData.get("template") || "standard").trim(),
    filters,
    sort: String(formData.get("sort") || "collected_at_desc").trim(),
    requested_by: String(formData.get("requested_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/report-export-jobs/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/report-export-jobs/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function updateRuntimeReportExportJobStatus(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const jobId = String(formData.get("job_id") || "").trim();
  if (!jobId) {
    throw new Error("job_id is required to update report export job status");
  }
  const payload = {
    status: String(formData.get("status") || "cancelled").trim(),
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    report_export_id: String(formData.get("report_export_id") || "").trim() || undefined,
    artifact_url: String(formData.get("artifact_url") || "").trim() || undefined,
    error_message: String(formData.get("error_message") || "").trim() || undefined,
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/report-export-jobs/runtime/${jobId}/status`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/report-export-jobs/runtime/${jobId}/status returned ${response.status}`);
  }
  revalidatePath("/");
}

async function updateRuntimeNotificationStatus(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const notificationId = String(formData.get("notification_id") || "").trim();
  if (!notificationId) {
    throw new Error("notification_id is required to update notification status");
  }
  const payload = {
    status: String(formData.get("status") || "read").trim(),
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/runtime-notifications/${notificationId}/status`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/runtime-notifications/${notificationId}/status returned ${response.status}`);
  }
  revalidatePath("/");
}

async function recordRuntimeNotificationEmailFeedback(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const deliveryId = String(formData.get("delivery_id") || "").trim();
  if (!deliveryId) {
    throw new Error("delivery_id is required to record notification email feedback");
  }
  const payload = {
    feedback_type: String(formData.get("feedback_type") || "bounce").trim(),
    recipient: String(formData.get("recipient") || "").trim() || undefined,
    recipient_hash: String(formData.get("recipient_hash") || "").trim() || undefined,
    provider: String(formData.get("provider") || "").trim() || undefined,
    provider_event_id: String(formData.get("provider_event_id") || "").trim() || undefined,
    provider_event_id_hash: String(formData.get("provider_event_id_hash") || "").trim() || undefined,
    recorded_by: String(formData.get("recorded_by") || "runtime-console").trim(),
    metadata: {
      source: "runtime_console_email_feedback",
      note: String(formData.get("note") || "").trim() || undefined
    },
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/runtime-notification-deliveries/${deliveryId}/email-feedback`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/runtime-notification-deliveries/${deliveryId}/email-feedback returned ${response.status}`);
  }
  revalidatePath("/");
}

async function applyRuntimeNotificationEmailFeedbackSuppression(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const feedbackEventId = String(formData.get("feedback_event_id") || "").trim();
  if (!feedbackEventId) {
    throw new Error("feedback_event_id is required to apply notification email suppression");
  }
  const payload = {
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(
    `${baseUrl}/v1/runtime-notification-email-feedback-events/${feedbackEventId}/suppress-recipient`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store"
    }
  );
  if (!response.ok) {
    throw new Error(
      `/v1/runtime-notification-email-feedback-events/${feedbackEventId}/suppress-recipient returned ${response.status}`
    );
  }
  revalidatePath("/");
}

async function applyRuntimeNotificationEmailFeedbackProjectSuppression(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const feedbackEventId = String(formData.get("feedback_event_id") || "").trim();
  if (!feedbackEventId) {
    throw new Error("feedback_event_id is required to apply notification email project suppression");
  }
  const payload = {
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    metadata: {
      source: "runtime_console_email_feedback_project_suppression"
    },
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(
    `${baseUrl}/v1/runtime-notification-email-feedback-events/${feedbackEventId}/project-suppression`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store"
    }
  );
  if (!response.ok) {
    throw new Error(
      `/v1/runtime-notification-email-feedback-events/${feedbackEventId}/project-suppression returned ${response.status}`
    );
  }
  revalidatePath("/");
}

async function saveRuntimeNotificationEmailSuppression(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const recipientHash = String(formData.get("recipient_hash") || "").trim().toLowerCase();
  if (!projectId || !recipientHash) {
    throw new Error("project_id and recipient_hash are required to save notification email suppression");
  }
  const payload = {
    project_id: projectId,
    recipient_hash: recipientHash,
    status: String(formData.get("status") || "active").trim(),
    source: String(formData.get("source") || "manual").trim(),
    source_ref: String(formData.get("source_ref") || "").trim() || undefined,
    metadata: {
      source: "runtime_console_project_email_suppression",
      note: String(formData.get("note") || "").trim() || undefined
    },
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/runtime-notification-email-suppressions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/runtime-notification-email-suppressions returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveRuntimeProjectMember(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const userId = String(formData.get("user_id") || "").trim();
  if (!projectId || !userId) {
    throw new Error("project_id and user_id are required to save a project member");
  }
  const payload = {
    project_id: projectId,
    user_id: userId,
    role: String(formData.get("role") || "viewer").trim(),
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-members/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-members/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function deleteRuntimeProjectMember(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const userId = String(formData.get("user_id") || "").trim();
  if (!projectId || !userId) {
    throw new Error("project_id and user_id are required to delete a project member");
  }
  const payload = {
    project_id: projectId,
    user_id: userId,
    deleted_by: String(formData.get("deleted_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-members/runtime`, {
    method: "DELETE",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-members/runtime DELETE returned ${response.status}`);
  }
  revalidatePath("/");
}

async function createRuntimeProjectMemberInvitation(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const email = String(formData.get("email") || "").trim();
  if (!projectId || !email) {
    throw new Error("project_id and email are required to create a project member invitation");
  }
  const expiresAt = String(formData.get("expires_at") || "").trim();
  const payload = {
    project_id: projectId,
    email,
    role: String(formData.get("role") || "viewer").trim(),
    invited_by: String(formData.get("invited_by") || "runtime-console").trim(),
    expires_at: expiresAt || undefined,
    metadata: {
      source: "runtime-console",
      invite_note: String(formData.get("invite_note") || "").trim() || undefined
    },
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-member-invitations/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-member-invitations/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function actionRuntimeProjectMemberInvitation(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const invitationId = String(formData.get("invitation_id") || "").trim();
  const action = String(formData.get("action") || "").trim();
  if (!projectId || !invitationId || !action) {
    throw new Error("project_id, invitation_id and action are required to update a project member invitation");
  }
  const payload = {
    project_id: projectId,
    invitation_id: invitationId,
    action,
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-member-invitations/runtime/action`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-member-invitations/runtime/action returned ${response.status}`);
  }
  revalidatePath("/");
}

async function emailRuntimeProjectMemberInvitation(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const invitationId = String(formData.get("invitation_id") || "").trim();
  const inviteToken = String(formData.get("invite_token") || "").trim();
  if (!projectId || !invitationId || !inviteToken) {
    throw new Error("project_id, invitation_id and invite_token are required to email a project member invitation");
  }
  const acceptBaseUrl =
    String(formData.get("accept_base_url") || "").trim() ||
    `${process.env.NEXT_PUBLIC_APP_BASE_URL || "http://localhost:3000"}/invite/accept`;
  const payload = {
    project_id: projectId,
    invitation_id: invitationId,
    invite_token: inviteToken,
    accept_base_url: acceptBaseUrl,
    sent_by: String(formData.get("sent_by") || "runtime-console").trim(),
    smtp_env_prefix: String(formData.get("smtp_env_prefix") || "GENO_NOTIFICATION_SMTP").trim(),
    subject: String(formData.get("subject") || "").trim() || undefined,
    message: String(formData.get("message") || "").trim() || undefined,
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-member-invitations/runtime/email`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-member-invitations/runtime/email returned ${response.status}`);
  }
  revalidatePath("/");
}

async function acceptRuntimeProjectMemberInvitation(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const invitationId = String(formData.get("invitation_id") || "").trim();
  const inviteToken = String(formData.get("invite_token") || "").trim();
  if (!invitationId || !inviteToken) {
    throw new Error("invitation_id and invite_token are required to accept a project member invitation");
  }
  const payload = {
    invitation_id: invitationId,
    invite_token: inviteToken,
    accepted_by: String(formData.get("accepted_by") || "").trim() || undefined,
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/project-member-invitations/runtime/accept`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/project-member-invitations/runtime/accept returned ${response.status}`);
  }
  revalidatePath("/");
}

async function uploadProjectBrandLogo(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const uploadedBy = String(formData.get("uploaded_by") || "runtime-console").trim();
  const file = formData.get("brand_logo");
  if (!projectId || !(file instanceof File) || file.size === 0) {
    throw new Error("project_id and brand_logo file are required to upload a project logo");
  }
  const params = new URLSearchParams({
    project_id: projectId,
    filename: file.name || "logo.bin",
    uploaded_by: uploadedBy || "runtime-console"
  });
  const response = await fetch(`${baseUrl}${brandLogoEndpoint}?${params.toString()}`, {
    method: "POST",
    headers: { "content-type": file.type || "application/octet-stream" },
    body: Buffer.from(await file.arrayBuffer()),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${brandLogoEndpoint} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveScoreWeightConfig(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  if (!projectId) {
    throw new Error("project_id is required to save score weights");
  }
  const weights = Object.fromEntries(
    scoreComponentNames.map((component) => [component, Number(formData.get(component) || 0)])
  );
  const payload = {
    project_id: projectId,
    formula_version: String(formData.get("formula_version") || "au_visibility_v1").trim(),
    weights,
    updated_by: "runtime-console",
    notes: String(formData.get("notes") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/score-weight-configs/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/score-weight-configs/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function submitHumanReview(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const targetType = String(formData.get("target_type") || "").trim();
  const targetId = String(formData.get("target_id") || "").trim();
  const decision = String(formData.get("decision") || "").trim();
  if (!projectId || !targetType || !targetId || !decision) {
    throw new Error("project_id, target_type, target_id and decision are required for human review");
  }
  const payload = {
    project_id: projectId,
    target_type: targetType,
    target_id: targetId,
    review_status: String(formData.get("review_status") || "approved").trim(),
    decision,
    reviewer_id: String(formData.get("reviewer_id") || "runtime-console").trim(),
    notes: String(formData.get("notes") || "").trim() || undefined,
    payload: {
      source: "runtime-console",
      target_label: String(formData.get("target_label") || "").trim() || undefined
    }
  };
  const response = await fetch(`${baseUrl}/v1/human-reviews/runtime`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/human-reviews/runtime returned ${response.status}`);
  }
  revalidatePath("/");
}

async function submitManualBackfill(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const promptQuestionId = String(formData.get("prompt_question_id") || "").trim();
  const answerText = String(formData.get("answer_text") || "").trim();
  if (!promptQuestionId || !answerText) {
    throw new Error("prompt_question_id and answer_text are required for manual backfill");
  }
  const citationUrls = String(formData.get("citation_urls") || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
  const payload = {
    prompt_question_id: promptQuestionId,
    platform: String(formData.get("platform") || "google").trim(),
    surface: String(formData.get("surface") || "google_ai_mode").trim(),
    answer_text: answerText,
    citation_urls: citationUrls,
    screenshot_url: String(formData.get("screenshot_url") || "").trim() || undefined,
    html_snapshot_url: String(formData.get("html_snapshot_url") || "").trim() || undefined,
    submitted_by: String(formData.get("submitted_by") || "runtime-console").trim(),
    notes: String(formData.get("notes") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/evidence-runs/runtime/manual-backfill`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/evidence-runs/runtime/manual-backfill returned ${response.status}`);
  }
  revalidatePath("/");
}

async function importManualBackfillCsv(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const csvContent = String(formData.get("csv_content") || "").trim();
  if (!projectId || !csvContent) {
    throw new Error("project_id and csv_content are required for manual backfill CSV import");
  }
  const response = await fetch(`${baseUrl}/v1/evidence-runs/runtime/manual-backfill/import.csv`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      csv_content: csvContent,
      submitted_by: String(formData.get("submitted_by") || "runtime-console").trim(),
      notes: String(formData.get("notes") || "").trim() || undefined,
      max_rows: Number(formData.get("max_rows") || 120)
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/evidence-runs/runtime/manual-backfill/import.csv returned ${response.status}`);
  }
  revalidatePath("/");
}

async function importRuntimePromptsCsv(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const csvContent = String(formData.get("csv_content") || "").trim();
  if (!projectId || !csvContent) {
    throw new Error("project_id and csv_content are required to import prompts");
  }
  const response = await fetch(`${baseUrl}/v1/prompts/runtime/import.csv`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      csv_content: csvContent,
      imported_by: "runtime-console",
      max_rows: 100
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/prompts/runtime/import.csv returned ${response.status}`);
  }
  revalidatePath("/");
}

async function importRuntimePromptsFile(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const promptFile = formData.get("prompt_file");
  if (!projectId || !(promptFile instanceof File) || !promptFile.name) {
    throw new Error("project_id and prompt_file are required to import prompt files");
  }
  const params = new URLSearchParams({
    project_id: projectId,
    filename: promptFile.name,
    imported_by: "runtime-console",
    max_rows: "100"
  });
  const response = await fetch(`${baseUrl}/v1/prompts/runtime/import.file?${params.toString()}`, {
    method: "POST",
    headers: { "content-type": promptFile.type || "application/octet-stream" },
    body: Buffer.from(await promptFile.arrayBuffer()),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/prompts/runtime/import.file returned ${response.status}`);
  }
  revalidatePath("/");
}

async function confirmEntityAlias(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const entityRef = String(formData.get("entity_ref") || "").trim();
  const alias = String(formData.get("alias") || "").trim();
  const [entityKind, entityId] = entityRef.split(":");
  if (!entityKind || !entityId || !alias) {
    throw new Error("entity_ref and alias are required for entity alias confirmation");
  }
  const payload = {
    entity_id: entityId,
    entity_kind: entityKind,
    alias,
    alias_type: String(formData.get("alias_type") || "alias").trim(),
    confidence: Number(String(formData.get("confidence") || "1")),
    confirmed_by: String(formData.get("confirmed_by") || "runtime-console").trim(),
    notes: String(formData.get("notes") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/entity-aliases/runtime/confirm`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/entity-aliases/runtime/confirm returned ${response.status}`);
  }
  revalidatePath("/");
}

async function confirmEntityAliasBatch(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const aliases = formData
    .getAll("candidate")
    .map((value) => {
      try {
        return JSON.parse(String(value)) as RuntimeEntityAliasBatchItem;
      } catch {
        return null;
      }
    })
    .filter((value): value is RuntimeEntityAliasBatchItem => {
      return Boolean(value?.entity_id && value?.entity_kind && value?.alias && value?.alias_type);
    });
  if (!aliases.length) {
    throw new Error("at least one alias candidate is required for batch confirmation");
  }
  const response = await fetch(`${baseUrl}/v1/entity-aliases/runtime/confirm-batch`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      aliases,
      confirmed_by: String(formData.get("confirmed_by") || "runtime-console").trim(),
      notes:
        String(formData.get("notes") || "").trim() ||
        `Batch confirm ${aliases.length} generated entity alias candidates`,
      continue_on_error: false
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/entity-aliases/runtime/confirm-batch returned ${response.status}`);
  }
  revalidatePath("/");
}

async function reviewEntityAliasCandidate(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const decision = String(formData.get("decision") || "").trim();
  const candidateId = String(formData.get("candidate_id") || "").trim();
  const entityId = String(formData.get("entity_id") || "").trim();
  const entityKind = String(formData.get("entity_kind") || "").trim();
  const alias = String(formData.get("alias") || "").trim();
  const aliasType = String(formData.get("alias_type") || "alias").trim();
  if (!projectId || !candidateId || !entityId || !entityKind || !alias || !decision) {
    throw new Error("project, candidate, entity, alias, and decision are required for alias candidate review");
  }
  const payload = {
    project_id: projectId,
    candidate_id: candidateId,
    entity_id: entityId,
    entity_kind: entityKind,
    alias,
    alias_type: aliasType,
    decision,
    reviewed_by: String(formData.get("reviewed_by") || "runtime-console").trim(),
    source: String(formData.get("source") || "").trim() || undefined,
    confidence: Number(String(formData.get("confidence") || "0")),
    reason: String(formData.get("reason") || "").trim() || undefined,
    notes: String(formData.get("notes") || "").trim() || undefined,
    evidence_answer_run_ids: String(formData.get("evidence_answer_run_ids") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    evidence_urls: String(formData.get("evidence_urls") || "")
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean),
    payload: {
      source_panel: "runtime_entity_alias_candidates",
      candidate_source: String(formData.get("source") || "").trim()
    }
  };
  const response = await fetch(`${baseUrl}/v1/entity-aliases/runtime/candidates/review`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/entity-aliases/runtime/candidates/review returned ${response.status}`);
  }
  revalidatePath("/");
}

async function reviewEntityAliasCandidatesBatch(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const decision = String(formData.get("decision") || "").trim();
  if (!decision) {
    throw new Error("decision is required for batch alias candidate review");
  }
  const reviews = formData
    .getAll("candidate_review")
    .map((value) => {
      try {
        return JSON.parse(String(value)) as RuntimeEntityAliasCandidateBatchReviewItem;
      } catch {
        return null;
      }
    })
    .filter((value): value is RuntimeEntityAliasCandidateBatchReviewItem => {
      return Boolean(value?.project_id && value?.candidate_id && value?.entity_id && value?.entity_kind && value?.alias);
    })
    .map((candidate) => ({
      project_id: candidate.project_id,
      candidate_id: candidate.candidate_id,
      entity_id: candidate.entity_id,
      entity_kind: candidate.entity_kind,
      alias: candidate.alias,
      alias_type: candidate.alias_type || "alias",
      decision,
      reviewed_by: String(formData.get("reviewed_by") || "runtime-console").trim(),
      source: candidate.source || undefined,
      confidence: candidate.confidence ?? 0,
      reason: `Alias candidate ${decision} from Runtime Console batch action`,
      notes:
        String(formData.get("notes") || "").trim() ||
        `Batch ${decision} decision for generated alias candidates`,
      evidence_answer_run_ids: candidate.evidence_answer_run_ids || [],
      evidence_urls: candidate.evidence_urls || [],
      payload: {
        source_panel: "runtime_entity_alias_candidates",
        batch_action: "entity_alias_candidate_review_batch_v1",
        candidate_source: candidate.source || "unknown"
      }
    }));
  if (!reviews.length) {
    throw new Error("at least one alias candidate is required for batch candidate review");
  }
  const response = await fetch(`${baseUrl}/v1/entity-aliases/runtime/candidates/review-batch`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      reviews,
      reviewed_by: String(formData.get("reviewed_by") || "runtime-console").trim(),
      notes:
        String(formData.get("notes") || "").trim() ||
        `Batch ${decision} generated entity alias candidates`,
      continue_on_error: false
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/entity-aliases/runtime/candidates/review-batch returned ${response.status}`);
  }
  revalidatePath("/");
}

async function assignEntityAliasCandidateReview(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const candidateId = String(formData.get("candidate_id") || "").trim();
  const assignedTo = String(formData.get("assigned_to") || "").trim();
  if (!projectId || !candidateId || !assignedTo) {
    throw new Error("project, candidate, and assigned_to are required for alias candidate assignment");
  }
  const payload = {
    project_id: projectId,
    candidate_id: candidateId,
    assigned_to: assignedTo,
    assigned_by: String(formData.get("assigned_by") || "runtime-console").trim(),
    assignment_status: String(formData.get("assignment_status") || "assigned").trim(),
    priority: String(formData.get("priority") || "normal").trim(),
    due_at: String(formData.get("due_at") || "").trim() || undefined,
    assignment_note: String(formData.get("assignment_note") || "").trim() || undefined,
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/entity-aliases/runtime/candidates/assign`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/entity-aliases/runtime/candidates/assign returned ${response.status}`);
  }
  revalidatePath("/");
}

async function actionEntityAliasCandidateAssignment(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const candidateId = String(formData.get("candidate_id") || "").trim();
  const action = String(formData.get("action") || "").trim();
  if (!projectId || !candidateId || !action) {
    throw new Error("project, candidate, and assignment action are required");
  }
  const response = await fetch(`${baseUrl}${endpoints.entityAliasAssignmentAction}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      candidate_id: candidateId,
      action,
      updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
      note: String(formData.get("note") || "").trim() || undefined,
      force: String(formData.get("force") || "").trim() === "true"
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${endpoints.entityAliasAssignmentAction} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function actionEntityAliasCandidateAssignmentsBatch(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const candidateIds = formData
    .getAll("candidate_id")
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  const action = String(formData.get("action") || "").trim();
  if (!projectId || !candidateIds.length || !action) {
    throw new Error("project, candidate_ids, and assignment action are required");
  }
  const response = await fetch(`${baseUrl}${endpoints.entityAliasAssignmentBatchAction}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      candidate_ids: candidateIds,
      action,
      updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
      note: String(formData.get("note") || "").trim() || undefined,
      force: String(formData.get("force") || "").trim() === "true",
      continue_on_error: String(formData.get("continue_on_error") || "true").trim() !== "false"
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${endpoints.entityAliasAssignmentBatchAction} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function applyEntityAliasAssignmentDispatchPlan(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  if (!projectId) {
    throw new Error("project_id is required for alias assignment dispatch apply");
  }
  const includeStatuses = String(formData.get("include_statuses") || "unassigned,escalated")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const reviewerIds = String(formData.get("reviewer_ids") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const response = await fetch(`${baseUrl}${endpoints.entityAliasAssignmentDispatchApply}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      reviewer_ids: reviewerIds,
      include_statuses: includeStatuses,
      max_per_reviewer: Number(formData.get("max_per_reviewer") || 10),
      limit: Number(formData.get("limit") || 20),
      applied_by: String(formData.get("applied_by") || "runtime-console").trim(),
      assignment_status: String(formData.get("assignment_status") || "assigned").trim(),
      priority: String(formData.get("priority") || "").trim() || undefined,
      due_at: String(formData.get("due_at") || "").trim() || undefined,
      assignment_note: String(formData.get("assignment_note") || "").trim() || undefined,
      reason: String(formData.get("reason") || "").trim() || undefined,
      continue_on_error: String(formData.get("continue_on_error") || "true").trim() !== "false"
    }),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`${endpoints.entityAliasAssignmentDispatchApply} returned ${response.status}`);
  }
  revalidatePath("/");
}

async function saveRuntimeNotificationSubscription(formData: FormData) {
  "use server";
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const projectId = String(formData.get("project_id") || "").trim();
  const channel = String(formData.get("channel") || "webhook").trim().toLowerCase();
  const endpointUrl = String(formData.get("endpoint_url") || "").trim();
  if (!projectId || !endpointUrl) {
    throw new Error("project_id and endpoint_url are required to save notification subscription");
  }
  const eventTypes = String(
    formData.get("event_types") || "report_export_job,runtime_alert,entity_alias_assignment_overdue"
  )
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const payload = {
    project_id: projectId,
    channel,
    endpoint_url: endpointUrl,
    event_types: eventTypes.length
      ? eventTypes
      : ["report_export_job", "runtime_alert", "entity_alias_assignment_overdue"],
    severity_threshold: String(formData.get("severity_threshold") || "info").trim(),
    status: String(formData.get("status") || "active").trim(),
    metadata: {
      source: "runtime_console_notification_subscription",
      signing_secret_env:
        channel === "webhook" ? String(formData.get("signing_secret_env") || "").trim() || undefined : undefined,
      signing_secret_key_id:
        channel === "webhook" ? String(formData.get("signing_secret_key_id") || "").trim() || undefined : undefined,
      previous_signing_secret_env:
        channel === "webhook"
          ? String(formData.get("previous_signing_secret_env") || "").trim() || undefined
          : undefined,
      previous_signing_secret_key_id:
        channel === "webhook"
          ? String(formData.get("previous_signing_secret_key_id") || "").trim() || undefined
          : undefined,
      slack_channel: channel === "slack" ? String(formData.get("slack_channel") || "").trim() || undefined : undefined,
      email_reply_to: channel === "email" ? String(formData.get("email_reply_to") || "").trim() || undefined : undefined,
      email_unsubscribe_url:
        channel === "email" ? String(formData.get("email_unsubscribe_url") || "").trim() || undefined : undefined,
      email_unsubscribe_mailto:
        channel === "email" ? String(formData.get("email_unsubscribe_mailto") || "").trim() || undefined : undefined,
      email_preferences_url:
        channel === "email" ? String(formData.get("email_preferences_url") || "").trim() || undefined : undefined,
      email_suppressed_recipients:
        channel === "email"
          ? String(formData.get("email_suppressed_recipients") || "").trim() || undefined
          : undefined
    },
    updated_by: String(formData.get("updated_by") || "runtime-console").trim(),
    reason: String(formData.get("reason") || "").trim() || undefined
  };
  const response = await fetch(`${baseUrl}/v1/runtime-notification-subscriptions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`/v1/runtime-notification-subscriptions returned ${response.status}`);
  }
  revalidatePath("/");
}

async function fetchRuntimeEndpoint<T>(
  baseUrl: string,
  path: string,
  fallback: T,
  options: { optionalNotFound?: boolean } = {}
): Promise<{ payload: T; error: string | null }> {
  try {
    const response = await fetch(`${baseUrl}${path}`, { cache: "no-store" });
    if (response.status === 404 && options.optionalNotFound) {
      return { payload: fallback, error: null };
    }
    if (!response.ok) {
      return { payload: fallback, error: `${path} returned ${response.status}` };
    }
    return { payload: (await response.json()) as T, error: null };
  } catch (error) {
    return {
      payload: fallback,
      error: error instanceof Error ? `${path} failed: ${error.message}` : `${path} failed`
    };
  }
}

function cleanFilter(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed || undefined;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

function runtimePath(path: string, params: Record<string, string | number | undefined>): string {
  return `${path}${buildQuery(params)}`;
}

function reportArtifactPath(
  reportArtifactBase: string | null,
  artifactType: "markdown" | "csv" | "pdf",
  filters: RuntimeFilters,
  extras: Record<string, string | number | undefined> = {}
): string | null {
  if (!reportArtifactBase) return null;
  return runtimePath(reportArtifactBase, {
    type: artifactType,
    platform: filters.platform,
    city: filters.city,
    intent_type: filters.intent_type,
    sort: filters.sort,
    ...extras
  });
}

function reportArtifactSignedUrlPath(
  reportArtifactBase: string | null,
  artifactType: "markdown" | "csv" | "pdf",
  filters: RuntimeFilters,
  extras: Record<string, string | number | undefined> = {}
): string | null {
  if (!reportArtifactBase) return null;
  return reportArtifactPath(`${reportArtifactBase}/signed-url`, artifactType, filters, extras);
}

async function fetchRuntimeData(filters: RuntimeFilters = {}): Promise<{
  data: RuntimeData;
  error: string | null;
  fetchUrl: string;
  displayUrl: string;
  paths: RuntimePaths;
}> {
  const baseUrl =
    process.env.API_INTERNAL_BASE_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    "http://localhost:8000";
  const displayUrl = process.env.NEXT_PUBLIC_API_BASE_URL || baseUrl;
  const projectListParams = { market_code: "AU", limit: 20 };
  const paths: RuntimePaths = {
    launchStatus: endpoints.launchStatus,
    launchRemediationPlan: endpoints.launchRemediationPlan,
    p0aEnvironmentChecklist: endpoints.p0aEnvironmentChecklist,
    p0aExecutionChecklist: endpoints.p0aExecutionChecklist,
    p0aCredentialRequest: endpoints.p0aCredentialRequest,
    p0aCredentialFulfillment: endpoints.p0aCredentialFulfillment,
    p0aCredentialClearance: endpoints.p0aCredentialClearance,
    p0aRealBatchRequest: endpoints.p0aRealBatchRequest,
    p0aRealBatchFulfillment: endpoints.p0aRealBatchFulfillment,
    p0aRealBatchClearance: endpoints.p0aRealBatchClearance,
    p0bGoogleExecutionChecklist: endpoints.p0bGoogleExecutionChecklist,
    p0bGoogleEnvironmentRequest: endpoints.p0bGoogleEnvironmentRequest,
    p0bGoogleEnvironmentFulfillment: endpoints.p0bGoogleEnvironmentFulfillment,
    p0bGoogleEnvironmentClearance: endpoints.p0bGoogleEnvironmentClearance,
    p0bGoogleManualBackfillRequest: endpoints.p0bGoogleManualBackfillRequest,
    p0bGoogleManualBackfillFulfillment: endpoints.p0bGoogleManualBackfillFulfillment,
    p0bGoogleManualBackfillClearance: endpoints.p0bGoogleManualBackfillClearance,
    p0bGooglePhaseExecutionRequest: endpoints.p0bGooglePhaseExecutionRequest,
    p0bGooglePhaseExecutionFulfillment: endpoints.p0bGooglePhaseExecutionFulfillment,
    p0bGooglePhaseExecutionClearance: endpoints.p0bGooglePhaseExecutionClearance,
    externalDependencyHandoff: endpoints.externalDependencyHandoff,
    externalDependencyClearance: endpoints.externalDependencyClearance,
    broaderPlatformRegistry: endpoints.broaderPlatformRegistry,
    retestSchedulerPlan: endpoints.retestSchedulerPlan,
    retestExecutionStatus: endpoints.retestExecutionStatus,
    handoffDossier: endpoints.handoffDossier,
    customerHandoffReadiness: endpoints.customerHandoffReadiness,
    customerHandoffClearance: endpoints.customerHandoffClearance,
    nextWorkItem: endpoints.nextWorkItem,
    deliveryProgress: endpoints.deliveryProgress,
    projects: runtimePath(endpoints.projects, projectListParams),
    projectAction: endpoints.projectAction,
    projectLifecycleEvents: endpoints.projectLifecycleEvents,
    projectLifecycleExport: endpoints.projectLifecycleExport,
    auditEvents: endpoints.auditEvents,
    auditEventsExport: endpoints.auditEventsExport,
    projectMembers: endpoints.projectMembers,
    projectMemberInvitations: endpoints.projectMemberInvitations,
    projectMemberInvitationAction: endpoints.projectMemberInvitationAction,
    projectMemberInvitationEmail: endpoints.projectMemberInvitationEmail,
    projectMemberInvitationAccept: endpoints.projectMemberInvitationAccept,
    prompts: runtimePath(endpoints.prompts, {
      market_code: "AU",
      intent_type: filters.intent_type,
      limit: 200
    }),
    promptImports: runtimePath(endpoints.promptImports, {
      limit: 5
    }),
    evidence: runtimePath(endpoints.evidence, {
      platform: filters.platform,
      city: filters.city,
      intent_type: filters.intent_type,
      sort: filters.sort,
      limit: 5
    }),
    questionEvidence: runtimePath(endpoints.evidence, {
      platform: filters.platform,
      city: filters.city,
      intent_type: filters.intent_type,
      sort: filters.sort,
      limit: 200
    }),
    collectionRuns: runtimePath(endpoints.collectionRuns, {
      limit: 5
    }),
    evidenceExport: runtimePath(endpoints.evidenceExport, {
      platform: filters.platform,
      city: filters.city,
      intent_type: filters.intent_type,
      sort: filters.sort,
      limit: 200
    }),
    entityAliases: runtimePath(endpoints.entityAliases, {
      limit: 5
    }),
    entityAliasCandidates: runtimePath(endpoints.entityAliasCandidates, {
      limit: 5
    }),
    entityAliasCandidateReviews: endpoints.entityAliasCandidateReviews,
    entityAliasAssignmentQueue: endpoints.entityAliasAssignmentQueue,
    entityAliasAssignmentStats: endpoints.entityAliasAssignmentStats,
    entityAliasAssignmentWorkbench: endpoints.entityAliasAssignmentWorkbench,
    entityAliasAssignmentWorkload: endpoints.entityAliasAssignmentWorkload,
    entityAliasAssignmentDispatchPlan: endpoints.entityAliasAssignmentDispatchPlan,
    entityAliasAssignmentDispatchApply: endpoints.entityAliasAssignmentDispatchApply,
    entityAliasAssignmentAction: endpoints.entityAliasAssignmentAction,
    entityAliasAssignmentBatchAction: endpoints.entityAliasAssignmentBatchAction,
    entityAliasAssignmentReassignments: endpoints.entityAliasAssignmentReassignments,
    entityAliasConfirmBatch: endpoints.entityAliasConfirmBatch,
    fidelityChecks: runtimePath(endpoints.fidelityChecks, {
      limit: 5
    }),
    fidelityTrend: runtimePath(endpoints.fidelityTrend, {
      limit: 20
    }),
    savedViews: runtimePath(endpoints.savedViews, {
      view_type: "runtime_evidence",
      limit: 5
    }),
    brandKit: endpoints.brandKit,
    brandAssets: endpoints.brandAssets,
    brandAssetLibrary: endpoints.brandAssetLibrary,
    scoreWeights: endpoints.scoreWeights,
    scoreFormulas: endpoints.scoreFormulas,
    humanReviews: runtimePath(endpoints.humanReviews, {
      limit: 5
    }),
    humanReviewQueue: runtimePath(endpoints.humanReviewQueue, {
      limit: 5
    }),
    knowledgeSearch: endpoints.knowledgeSearch,
    scores: runtimePath(endpoints.scores, { limit: 1 }),
    graphs: runtimePath(endpoints.graphs, { limit: 1 }),
    reports: runtimePath(endpoints.reports, { limit: 5 }),
    reportJobs: runtimePath(endpoints.reportJobs, { limit: 5 }),
    reportJobsExport: runtimePath(endpoints.reportJobsExport, { limit: 200 }),
    reportJobStats: endpoints.reportJobStats,
    notifications: runtimePath(endpoints.notifications, { limit: 8 }),
    notificationsExport: runtimePath(endpoints.notificationsExport, { limit: 200 }),
    notificationSubscriptions: runtimePath(endpoints.notificationSubscriptions, { limit: 5 }),
    notificationSubscriptionsExport: runtimePath(endpoints.notificationSubscriptionsExport, { limit: 200 }),
    notificationDeliveries: runtimePath(endpoints.notificationDeliveries, { limit: 5 }),
    notificationDeliveriesExport: runtimePath(endpoints.notificationDeliveriesExport, { limit: 200 }),
    notificationEmailFeedback: runtimePath(endpoints.notificationEmailFeedback, { limit: 5 }),
    notificationEmailSuppressions: runtimePath(endpoints.notificationEmailSuppressions, { limit: 5 }),
    notificationEmailSuppressionsExport: runtimePath(endpoints.notificationEmailSuppressionsExport, { limit: 200 }),
    notificationEmailFeedbackWebhook: endpoints.notificationEmailFeedbackWebhook,
    notificationEmailPreferenceStatus: endpoints.notificationEmailPreferenceStatus,
    notificationEmailPreferenceResubscribe: endpoints.notificationEmailPreferenceResubscribe,
    notificationEmailPreferenceUnsubscribe: endpoints.notificationEmailPreferenceUnsubscribe,
    actions: runtimePath(endpoints.actions, { limit: 1 }),
    alerts: runtimePath(endpoints.alerts, { limit: 10 }),
    alertNotifications: endpoints.alertNotifications,
    entityAliasAssignmentNotifications: endpoints.entityAliasAssignmentNotifications,
    entityAliasAssignmentEscalations: endpoints.entityAliasAssignmentEscalations,
    content: runtimePath(endpoints.content, { limit: 1 }),
    traceability: endpoints.traceability
  };
  const projects = await fetchRuntimeEndpoint<PageResponse<RuntimeProject>>(
    baseUrl,
    paths.projects,
    emptyPage<RuntimeProject>()
  );
  let projectRecords = projects.payload.records;
  if (filters.project_id && !projectRecords.some((record) => record.project.id === filters.project_id)) {
    const selectedProject = await fetchRuntimeEndpoint<PageResponse<RuntimeProject>>(
      baseUrl,
      runtimePath(endpoints.projects, {
        project_id: filters.project_id,
        market_code: "AU",
        include_archived: "true",
        limit: 1
      }),
      emptyPage<RuntimeProject>()
    );
    if (selectedProject.payload.records.length) {
      projectRecords = [...selectedProject.payload.records, ...projectRecords];
      projects.payload = {
        ...projects.payload,
        records: projectRecords,
        total_count: Math.max(projects.payload.total_count, projectRecords.length)
      };
    }
  }
  const selectedProjectId =
    (filters.project_id && projectRecords.some((record) => record.project.id === filters.project_id)
      ? filters.project_id
      : undefined) || projectRecords[0]?.project.id;
  const selectedProjectParams = selectedProjectId ? { project_id: selectedProjectId } : {};
  paths.projectLifecycleEvents = selectedProjectId
    ? runtimePath(endpoints.projectLifecycleEvents, { project_id: selectedProjectId, limit: 20 })
    : endpoints.projectLifecycleEvents;
  paths.projectLifecycleExport = selectedProjectId
    ? runtimePath(endpoints.projectLifecycleExport, { project_id: selectedProjectId, limit: 200 })
    : endpoints.projectLifecycleExport;
  paths.auditEvents = selectedProjectId
    ? runtimePath(endpoints.auditEvents, { project_id: selectedProjectId, limit: 20 })
    : endpoints.auditEvents;
  paths.auditEventsExport = selectedProjectId
    ? runtimePath(endpoints.auditEventsExport, { project_id: selectedProjectId, limit: 200 })
    : endpoints.auditEventsExport;
  paths.projectMembers = selectedProjectId
    ? runtimePath(endpoints.projectMembers, { project_id: selectedProjectId, limit: 20 })
    : endpoints.projectMembers;
  paths.projectMemberInvitations = selectedProjectId
    ? runtimePath(endpoints.projectMemberInvitations, {
        project_id: selectedProjectId,
        status: "pending",
        limit: 20
      })
    : endpoints.projectMemberInvitations;
  paths.prompts = runtimePath(endpoints.prompts, {
    ...selectedProjectParams,
    market_code: "AU",
    intent_type: filters.intent_type,
    limit: 200
  });
  paths.promptImports = runtimePath(endpoints.promptImports, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.evidence = runtimePath(endpoints.evidence, {
    ...selectedProjectParams,
    platform: filters.platform,
    city: filters.city,
    intent_type: filters.intent_type,
    sort: filters.sort,
    limit: 5
  });
  paths.questionEvidence = runtimePath(endpoints.evidence, {
    ...selectedProjectParams,
    platform: filters.platform,
    city: filters.city,
    intent_type: filters.intent_type,
    sort: filters.sort,
    limit: 200
  });
  paths.collectionRuns = runtimePath(endpoints.collectionRuns, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.fidelityChecks = runtimePath(endpoints.fidelityChecks, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.fidelityTrend = runtimePath(endpoints.fidelityTrend, {
    ...selectedProjectParams,
    limit: 20
  });
  paths.evidenceExport = runtimePath(endpoints.evidenceExport, {
    ...selectedProjectParams,
    platform: filters.platform,
    city: filters.city,
    intent_type: filters.intent_type,
    sort: filters.sort,
    limit: 200
  });
  paths.entityAliases = runtimePath(endpoints.entityAliases, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.entityAliasCandidates = selectedProjectId
    ? runtimePath(endpoints.entityAliasCandidates, {
        project_id: selectedProjectId,
        limit: 5
      })
    : paths.entityAliasCandidates;
  paths.entityAliasCandidateReviews = selectedProjectId
    ? runtimePath(endpoints.entityAliasCandidateReviews, {
        project_id: selectedProjectId,
        limit: 8
      })
    : paths.entityAliasCandidateReviews;
  paths.entityAliasAssignmentQueue = selectedProjectId
    ? runtimePath(endpoints.entityAliasAssignmentQueue, {
        project_id: selectedProjectId,
        assignment_status: "assigned",
        limit: 8
      })
    : paths.entityAliasAssignmentQueue;
  paths.entityAliasAssignmentStats = selectedProjectId
    ? runtimePath(endpoints.entityAliasAssignmentStats, {
        project_id: selectedProjectId
      })
    : paths.entityAliasAssignmentStats;
  paths.entityAliasAssignmentWorkbench = selectedProjectId
    ? runtimePath(endpoints.entityAliasAssignmentWorkbench, {
        project_id: selectedProjectId,
        reviewer_id: "runtime-console",
        limit: 8
      })
    : paths.entityAliasAssignmentWorkbench;
  paths.entityAliasAssignmentWorkload = selectedProjectId
    ? runtimePath(endpoints.entityAliasAssignmentWorkload, {
        project_id: selectedProjectId
      })
    : paths.entityAliasAssignmentWorkload;
  paths.entityAliasAssignmentDispatchPlan = selectedProjectId
    ? runtimePath(endpoints.entityAliasAssignmentDispatchPlan, {
        project_id: selectedProjectId,
        include_statuses: "unassigned,escalated",
        max_per_reviewer: 10,
        limit: 20
      })
    : paths.entityAliasAssignmentDispatchPlan;
  paths.entityAliasAssignmentDispatchApply = endpoints.entityAliasAssignmentDispatchApply;
  paths.entityAliasAssignmentEscalations = endpoints.entityAliasAssignmentEscalations;
  paths.entityAliasAssignmentReassignments = endpoints.entityAliasAssignmentReassignments;
  paths.savedViews = runtimePath(endpoints.savedViews, {
    ...selectedProjectParams,
    view_type: "runtime_evidence",
    limit: 5
  });
  paths.brandKit = selectedProjectId
    ? runtimePath(endpoints.brandKit, { project_id: selectedProjectId })
    : endpoints.brandKit;
  paths.brandAssets = selectedProjectId
    ? runtimePath(endpoints.brandAssets, { project_id: selectedProjectId, limit: 8 })
    : endpoints.brandAssets;
  paths.brandAssetLibrary = selectedProjectId
    ? runtimePath(endpoints.brandAssetLibrary, { project_id: selectedProjectId, limit: 8 })
    : endpoints.brandAssetLibrary;
  paths.scoreWeights = selectedProjectId
    ? runtimePath(endpoints.scoreWeights, { project_id: selectedProjectId })
    : endpoints.scoreWeights;
  paths.scoreFormulas = endpoints.scoreFormulas;
  paths.humanReviews = runtimePath(endpoints.humanReviews, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.humanReviewQueue = runtimePath(endpoints.humanReviewQueue, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.knowledgeSearch = selectedProjectId
    ? runtimePath(endpoints.knowledgeSearch, {
        project_id: selectedProjectId,
        query: "Australia shipping returns local reviews",
        market_code: "AU",
        city: filters.city,
        limit: 5
      })
    : endpoints.knowledgeSearch;
  paths.scores = runtimePath(endpoints.scores, {
    ...selectedProjectParams,
    limit: 1
  });
  paths.graphs = runtimePath(endpoints.graphs, {
    ...selectedProjectParams,
    limit: 1
  });
  paths.reports = runtimePath(endpoints.reports, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.reportJobs = runtimePath(endpoints.reportJobs, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.reportJobsExport = runtimePath(endpoints.reportJobsExport, {
    ...selectedProjectParams,
    limit: 200
  });
  paths.reportJobStats = runtimePath(endpoints.reportJobStats, {
    ...selectedProjectParams
  });
  paths.notifications = runtimePath(endpoints.notifications, {
    ...selectedProjectParams,
    limit: 8
  });
  paths.notificationsExport = runtimePath(endpoints.notificationsExport, {
    ...selectedProjectParams,
    limit: 200
  });
  paths.notificationSubscriptions = runtimePath(endpoints.notificationSubscriptions, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.notificationSubscriptionsExport = runtimePath(endpoints.notificationSubscriptionsExport, {
    ...selectedProjectParams,
    status: "active",
    limit: 200
  });
  paths.notificationDeliveries = runtimePath(endpoints.notificationDeliveries, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.notificationDeliveriesExport = runtimePath(endpoints.notificationDeliveriesExport, {
    ...selectedProjectParams,
    limit: 200
  });
  paths.notificationEmailFeedback = runtimePath(endpoints.notificationEmailFeedback, {
    ...selectedProjectParams,
    limit: 5
  });
  paths.notificationEmailSuppressions = runtimePath(endpoints.notificationEmailSuppressions, {
    ...selectedProjectParams,
    status: "active",
    limit: 5
  });
  paths.notificationEmailSuppressionsExport = runtimePath(endpoints.notificationEmailSuppressionsExport, {
    ...selectedProjectParams,
    status: "active",
    limit: 200
  });
  paths.actions = runtimePath(endpoints.actions, {
    ...selectedProjectParams,
    limit: 1
  });
  paths.alerts = runtimePath(endpoints.alerts, {
    ...selectedProjectParams,
    limit: 10
  });
  paths.alertNotifications = endpoints.alertNotifications;
  paths.entityAliasAssignmentNotifications = endpoints.entityAliasAssignmentNotifications;
  paths.entityAliasAssignmentAction = endpoints.entityAliasAssignmentAction;
  paths.content = runtimePath(endpoints.content, {
    ...selectedProjectParams,
    limit: 1
  });
  paths.traceability = runtimePath(endpoints.traceability, selectedProjectParams);

  const [
    launchStatus,
    launchRemediationPlan,
    p0aEnvironmentChecklist,
    p0aExecutionChecklist,
    p0aCredentialRequest,
    p0aCredentialFulfillment,
    p0aCredentialClearance,
    p0aRealBatchRequest,
    p0aRealBatchFulfillment,
    p0aRealBatchClearance,
    p0bGoogleExecutionChecklist,
    p0bGoogleEnvironmentRequest,
    p0bGoogleEnvironmentFulfillment,
    p0bGoogleEnvironmentClearance,
    p0bGoogleManualBackfillRequest,
    p0bGoogleManualBackfillFulfillment,
    p0bGoogleManualBackfillClearance,
    p0bGooglePhaseExecutionRequest,
    p0bGooglePhaseExecutionFulfillment,
    p0bGooglePhaseExecutionClearance,
    externalDependencyHandoff,
    externalDependencyClearance,
    broaderPlatformRegistry,
    retestSchedulerPlan,
    retestExecutionStatus,
    handoffDossier,
    customerHandoffReadiness,
    customerHandoffClearance,
    nextWorkItemPacket,
    deliveryProgress,
    prompts,
    projectLifecycleEvents,
    auditEvents,
    projectMembers,
    projectMemberInvitations,
    promptImports,
    evidence,
    questionEvidence,
    collectionRuns,
    fidelityChecks,
    fidelityTrend,
    entityAliases,
    entityAliasCandidates,
    entityAliasCandidateReviews,
    entityAliasAssignmentQueue,
    entityAliasAssignmentStats,
    entityAliasAssignmentWorkbench,
    entityAliasAssignmentWorkload,
    entityAliasAssignmentDispatchPlan,
    savedViews,
    brandKit,
    brandAssets,
    brandAssetLibrary,
    scoreWeights,
    scoreFormulas,
    humanReviews,
    humanReviewQueue,
    knowledgeSearch,
    scores,
    graphs,
    reports,
    reportJobs,
    reportJobStats,
    notifications,
    notificationSubscriptions,
    notificationDeliveries,
    notificationEmailFeedback,
    notificationEmailSuppressions,
    actions,
    alerts,
    content,
    traceability
  ] = await Promise.all([
    fetchRuntimeEndpoint<AuLaunchStatus | null>(baseUrl, paths.launchStatus, null),
    fetchRuntimeEndpoint<AuLaunchRemediationPlan | null>(baseUrl, paths.launchRemediationPlan, null),
    fetchRuntimeEndpoint<AuP0aEnvironmentChecklist | null>(baseUrl, paths.p0aEnvironmentChecklist, null),
    fetchRuntimeEndpoint<AuP0aExecutionChecklist | null>(baseUrl, paths.p0aExecutionChecklist, null),
    fetchRuntimeEndpoint<AuP0aCredentialRequest | null>(baseUrl, paths.p0aCredentialRequest, null),
    fetchRuntimeEndpoint<AuP0aCredentialFulfillment | null>(baseUrl, paths.p0aCredentialFulfillment, null),
    fetchRuntimeEndpoint<AuP0aCredentialClearance | null>(baseUrl, paths.p0aCredentialClearance, null),
    fetchRuntimeEndpoint<AuP0aRealBatchRequest | null>(baseUrl, paths.p0aRealBatchRequest, null),
    fetchRuntimeEndpoint<AuP0aRealBatchFulfillment | null>(baseUrl, paths.p0aRealBatchFulfillment, null),
    fetchRuntimeEndpoint<AuP0aRealBatchClearance | null>(baseUrl, paths.p0aRealBatchClearance, null),
    fetchRuntimeEndpoint<AuP0bGoogleExecutionChecklist | null>(baseUrl, paths.p0bGoogleExecutionChecklist, null),
    fetchRuntimeEndpoint<AuP0bGoogleEnvironmentRequest | null>(baseUrl, paths.p0bGoogleEnvironmentRequest, null),
    fetchRuntimeEndpoint<AuP0bGoogleEnvironmentFulfillment | null>(
      baseUrl,
      paths.p0bGoogleEnvironmentFulfillment,
      null
    ),
    fetchRuntimeEndpoint<AuP0bGoogleEnvironmentClearance | null>(
      baseUrl,
      paths.p0bGoogleEnvironmentClearance,
      null
    ),
    fetchRuntimeEndpoint<AuP0bGoogleManualBackfillRequest | null>(
      baseUrl,
      paths.p0bGoogleManualBackfillRequest,
      null
    ),
    fetchRuntimeEndpoint<AuP0bGoogleManualBackfillFulfillment | null>(
      baseUrl,
      paths.p0bGoogleManualBackfillFulfillment,
      null
    ),
    fetchRuntimeEndpoint<AuP0bGoogleManualBackfillClearance | null>(
      baseUrl,
      paths.p0bGoogleManualBackfillClearance,
      null
    ),
    fetchRuntimeEndpoint<AuP0bGooglePhaseExecutionRequest | null>(
      baseUrl,
      paths.p0bGooglePhaseExecutionRequest,
      null
    ),
    fetchRuntimeEndpoint<AuP0bGooglePhaseExecutionFulfillment | null>(
      baseUrl,
      paths.p0bGooglePhaseExecutionFulfillment,
      null
    ),
    fetchRuntimeEndpoint<AuP0bGooglePhaseExecutionClearance | null>(
      baseUrl,
      paths.p0bGooglePhaseExecutionClearance,
      null
    ),
    fetchRuntimeEndpoint<AuExternalDependencyHandoff | null>(baseUrl, paths.externalDependencyHandoff, null),
    fetchRuntimeEndpoint<AuExternalDependencyClearance | null>(baseUrl, paths.externalDependencyClearance, null),
    fetchRuntimeEndpoint<AuBroaderPlatformRegistry | null>(baseUrl, paths.broaderPlatformRegistry, null),
    fetchRuntimeEndpoint<AuRetestSchedulerPlan | null>(baseUrl, paths.retestSchedulerPlan, null),
    fetchRuntimeEndpoint<AuRetestExecutionStatus | null>(baseUrl, paths.retestExecutionStatus, null),
    fetchRuntimeEndpoint<AuHandoffDossier | null>(baseUrl, paths.handoffDossier, null),
    fetchRuntimeEndpoint<AuCustomerHandoffReadiness | null>(baseUrl, paths.customerHandoffReadiness, null),
    fetchRuntimeEndpoint<AuCustomerHandoffClearance | null>(baseUrl, paths.customerHandoffClearance, null),
    fetchRuntimeEndpoint<AuNextWorkItemPacket | null>(baseUrl, paths.nextWorkItem, null),
    fetchRuntimeEndpoint<AuDeliveryProgress | null>(baseUrl, paths.deliveryProgress, null),
    fetchRuntimeEndpoint<PageResponse<RuntimePrompt>>(baseUrl, paths.prompts, emptyPage<RuntimePrompt>()),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeProjectLifecycleEvent>>(
          baseUrl,
          paths.projectLifecycleEvents,
          emptyPage<RuntimeProjectLifecycleEvent>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeProjectLifecycleEvent>(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeAuditEvent>>(
          baseUrl,
          paths.auditEvents,
          emptyPage<RuntimeAuditEvent>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeAuditEvent>(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeProjectMember>>(
          baseUrl,
          paths.projectMembers,
          emptyPage<RuntimeProjectMember>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeProjectMember>(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeProjectMemberInvitation>>(
          baseUrl,
          paths.projectMemberInvitations,
          emptyPage<RuntimeProjectMemberInvitation>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeProjectMemberInvitation>(), error: null }),
    fetchRuntimeEndpoint<PageResponse<RuntimePromptImportHistoryItem>>(
      baseUrl,
      paths.promptImports,
      emptyPage<RuntimePromptImportHistoryItem>()
    ),
    fetchRuntimeEndpoint<PageResponse<EvidenceRun>>(baseUrl, paths.evidence, emptyPage<EvidenceRun>()),
    fetchRuntimeEndpoint<PageResponse<EvidenceRun>>(baseUrl, paths.questionEvidence, emptyPage<EvidenceRun>()),
    fetchRuntimeEndpoint<PageResponse<CollectionRun>>(baseUrl, paths.collectionRuns, emptyPage<CollectionRun>()),
    fetchRuntimeEndpoint<PageResponse<RuntimeFidelityCheck>>(
      baseUrl,
      paths.fidelityChecks,
      emptyPage<RuntimeFidelityCheck>()
    ),
    fetchRuntimeEndpoint<RuntimeFidelityTrend | null>(baseUrl, paths.fidelityTrend, null),
    fetchRuntimeEndpoint<PageResponse<RuntimeEntityAlias>>(
      baseUrl,
      paths.entityAliases,
      emptyPage<RuntimeEntityAlias>()
    ),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeEntityAliasCandidate>>(
          baseUrl,
          paths.entityAliasCandidates,
          emptyPage<RuntimeEntityAliasCandidate>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeEntityAliasCandidate>(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeEntityAliasCandidateReview>>(
          baseUrl,
          paths.entityAliasCandidateReviews,
          emptyPage<RuntimeEntityAliasCandidateReview>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeEntityAliasCandidateReview>(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeEntityAliasCandidateReview>>(
          baseUrl,
          paths.entityAliasAssignmentQueue,
          emptyPage<RuntimeEntityAliasCandidateReview>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeEntityAliasCandidateReview>(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeEntityAliasCandidateAssignmentQueueStats>(
          baseUrl,
          paths.entityAliasAssignmentStats,
          emptyAliasAssignmentStats()
        )
      : Promise.resolve({ payload: emptyAliasAssignmentStats(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeEntityAliasAssignmentWorkbench>(
          baseUrl,
          paths.entityAliasAssignmentWorkbench,
          emptyAliasAssignmentWorkbench()
        )
      : Promise.resolve({ payload: emptyAliasAssignmentWorkbench(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeEntityAliasAssignmentWorkloadSummary>(
          baseUrl,
          paths.entityAliasAssignmentWorkload,
          emptyAliasAssignmentWorkload()
        )
      : Promise.resolve({ payload: emptyAliasAssignmentWorkload(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeEntityAliasAssignmentDispatchPlan>(
          baseUrl,
          paths.entityAliasAssignmentDispatchPlan,
          emptyAliasAssignmentDispatchPlan()
        )
      : Promise.resolve({ payload: emptyAliasAssignmentDispatchPlan(), error: null }),
    fetchRuntimeEndpoint<PageResponse<RuntimeSavedView>>(baseUrl, paths.savedViews, emptyPage<RuntimeSavedView>()),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeProjectBrandKit | null>(baseUrl, paths.brandKit, null, { optionalNotFound: true })
      : Promise.resolve({ payload: null, error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeProjectBrandAssetVersion>>(
          baseUrl,
          paths.brandAssets,
          emptyPage<RuntimeProjectBrandAssetVersion>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeProjectBrandAssetVersion>(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeProjectBrandAsset>>(
          baseUrl,
          paths.brandAssetLibrary,
          emptyPage<RuntimeProjectBrandAsset>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeProjectBrandAsset>(), error: null }),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeScoreWeightConfig | null>(baseUrl, paths.scoreWeights, null)
      : Promise.resolve({ payload: null, error: null }),
    fetchRuntimeEndpoint<RuntimeScoreFormulaCatalog>(baseUrl, paths.scoreFormulas, { formulas: [] }),
    fetchRuntimeEndpoint<PageResponse<RuntimeHumanReview>>(
      baseUrl,
      paths.humanReviews,
      emptyPage<RuntimeHumanReview>()
    ),
    fetchRuntimeEndpoint<PageResponse<RuntimeHumanReviewQueueItem>>(
      baseUrl,
      paths.humanReviewQueue,
      emptyPage<RuntimeHumanReviewQueueItem>()
    ),
    selectedProjectId
      ? fetchRuntimeEndpoint<RuntimeKnowledgeSearch | null>(baseUrl, paths.knowledgeSearch, null, {
          optionalNotFound: true
        })
      : Promise.resolve({ payload: null, error: null }),
    fetchRuntimeEndpoint<PageResponse<ScoreSnapshot>>(baseUrl, paths.scores, emptyPage<ScoreSnapshot>()),
    fetchRuntimeEndpoint<PageResponse<CitationGraph>>(baseUrl, paths.graphs, emptyPage<CitationGraph>()),
    fetchRuntimeEndpoint<PageResponse<ReportExport>>(baseUrl, paths.reports, emptyPage<ReportExport>()),
    fetchRuntimeEndpoint<PageResponse<RuntimeReportExportJob>>(
      baseUrl,
      paths.reportJobs,
      emptyPage<RuntimeReportExportJob>()
    ),
    fetchRuntimeEndpoint<RuntimeReportExportJobQueueStats>(baseUrl, paths.reportJobStats, {
      total_count: 0,
      status_counts: {},
      retryable_count: 0,
      expired_running_count: 0,
      max_attempts_reached_count: 0,
      oldest_queued_at: null
    }),
    fetchRuntimeEndpoint<RuntimeNotificationPage>(baseUrl, paths.notifications, {
      total_count: 0,
      unread_count: 0,
      records: []
    }),
    fetchRuntimeEndpoint<PageResponse<RuntimeNotificationSubscription>>(
      baseUrl,
      paths.notificationSubscriptions,
      emptyPage<RuntimeNotificationSubscription>()
    ),
    fetchRuntimeEndpoint<PageResponse<RuntimeNotificationDelivery>>(
      baseUrl,
      paths.notificationDeliveries,
      emptyPage<RuntimeNotificationDelivery>()
    ),
    fetchRuntimeEndpoint<PageResponse<RuntimeNotificationEmailFeedback>>(
      baseUrl,
      paths.notificationEmailFeedback,
      emptyPage<RuntimeNotificationEmailFeedback>()
    ),
    selectedProjectId
      ? fetchRuntimeEndpoint<PageResponse<RuntimeNotificationEmailSuppression>>(
          baseUrl,
          paths.notificationEmailSuppressions,
          emptyPage<RuntimeNotificationEmailSuppression>()
        )
      : Promise.resolve({ payload: emptyPage<RuntimeNotificationEmailSuppression>(), error: null }),
    fetchRuntimeEndpoint<PageResponse<ActionPlan>>(baseUrl, paths.actions, emptyPage<ActionPlan>()),
    fetchRuntimeEndpoint<PageResponse<RuntimeAlert>>(baseUrl, paths.alerts, emptyPage<RuntimeAlert>()),
    fetchRuntimeEndpoint<PageResponse<ContentEngine>>(baseUrl, paths.content, emptyPage<ContentEngine>()),
    fetchRuntimeEndpoint<TraceabilityDetail | null>(baseUrl, paths.traceability, null, { optionalNotFound: true })
  ]);
  const errors = [
    launchStatus,
    launchRemediationPlan,
    p0aEnvironmentChecklist,
    p0aExecutionChecklist,
    p0aCredentialRequest,
    p0aCredentialFulfillment,
    p0aCredentialClearance,
    p0aRealBatchRequest,
    p0aRealBatchFulfillment,
    p0bGoogleExecutionChecklist,
    p0bGoogleEnvironmentRequest,
    p0bGoogleEnvironmentFulfillment,
    p0bGoogleEnvironmentClearance,
    p0bGoogleManualBackfillRequest,
    p0bGoogleManualBackfillFulfillment,
    p0bGoogleManualBackfillClearance,
    p0bGooglePhaseExecutionRequest,
    p0bGooglePhaseExecutionFulfillment,
    externalDependencyHandoff,
    externalDependencyClearance,
    broaderPlatformRegistry,
    retestSchedulerPlan,
    retestExecutionStatus,
    handoffDossier,
    customerHandoffReadiness,
    customerHandoffClearance,
    nextWorkItemPacket,
    deliveryProgress,
    projects,
    prompts,
    projectLifecycleEvents,
    auditEvents,
    projectMembers,
    projectMemberInvitations,
    promptImports,
    evidence,
    questionEvidence,
    collectionRuns,
    fidelityChecks,
    fidelityTrend,
    entityAliases,
    entityAliasCandidates,
    entityAliasCandidateReviews,
    entityAliasAssignmentQueue,
    entityAliasAssignmentStats,
    entityAliasAssignmentWorkbench,
    entityAliasAssignmentWorkload,
    entityAliasAssignmentDispatchPlan,
    savedViews,
    brandKit,
    brandAssets,
    brandAssetLibrary,
    scoreWeights,
    scoreFormulas,
    humanReviews,
    humanReviewQueue,
    knowledgeSearch,
    scores,
    graphs,
    reports,
    reportJobs,
    reportJobStats,
    notifications,
    notificationSubscriptions,
    notificationDeliveries,
    notificationEmailFeedback,
    notificationEmailSuppressions,
    actions,
    alerts,
    content,
    traceability
  ]
    .map((result) => result.error)
    .filter((item): item is string => Boolean(item));
  return {
    data: {
      launchStatus: launchStatus.payload,
      launchRemediationPlan: launchRemediationPlan.payload,
      p0aEnvironmentChecklist: p0aEnvironmentChecklist.payload,
      p0aExecutionChecklist: p0aExecutionChecklist.payload,
      p0aCredentialRequest: p0aCredentialRequest.payload,
      p0aCredentialFulfillment: p0aCredentialFulfillment.payload,
      p0aCredentialClearance: p0aCredentialClearance.payload,
      p0aRealBatchRequest: p0aRealBatchRequest.payload,
      p0aRealBatchFulfillment: p0aRealBatchFulfillment.payload,
      p0aRealBatchClearance: p0aRealBatchClearance.payload,
      p0bGoogleExecutionChecklist: p0bGoogleExecutionChecklist.payload,
      p0bGoogleEnvironmentRequest: p0bGoogleEnvironmentRequest.payload,
      p0bGoogleEnvironmentFulfillment: p0bGoogleEnvironmentFulfillment.payload,
      p0bGoogleEnvironmentClearance: p0bGoogleEnvironmentClearance.payload,
      p0bGoogleManualBackfillRequest: p0bGoogleManualBackfillRequest.payload,
      p0bGoogleManualBackfillFulfillment: p0bGoogleManualBackfillFulfillment.payload,
      p0bGoogleManualBackfillClearance: p0bGoogleManualBackfillClearance.payload,
      p0bGooglePhaseExecutionRequest: p0bGooglePhaseExecutionRequest.payload,
      p0bGooglePhaseExecutionFulfillment: p0bGooglePhaseExecutionFulfillment.payload,
      p0bGooglePhaseExecutionClearance: p0bGooglePhaseExecutionClearance.payload,
      externalDependencyHandoff: externalDependencyHandoff.payload,
      externalDependencyClearance: externalDependencyClearance.payload,
      broaderPlatformRegistry: broaderPlatformRegistry.payload,
      retestSchedulerPlan: retestSchedulerPlan.payload,
      retestExecutionStatus: retestExecutionStatus.payload,
      handoffDossier: handoffDossier.payload,
      customerHandoffReadiness: customerHandoffReadiness.payload,
      customerHandoffClearance: customerHandoffClearance.payload,
      nextWorkItemPacket: nextWorkItemPacket.payload,
      deliveryProgress: deliveryProgress.payload,
      projects: projects.payload,
      projectLifecycleEvents: projectLifecycleEvents.payload,
      auditEvents: auditEvents.payload,
      projectMembers: projectMembers.payload,
      projectMemberInvitations: projectMemberInvitations.payload,
      brandKit: brandKit.payload,
      brandAssets: brandAssets.payload,
      brandAssetLibrary: brandAssetLibrary.payload,
      scoreWeights: scoreWeights.payload,
      scoreFormulas: scoreFormulas.payload,
      humanReviews: humanReviews.payload,
      humanReviewQueue: humanReviewQueue.payload,
      knowledgeSearch: knowledgeSearch.payload,
      prompts: prompts.payload,
      promptImports: promptImports.payload,
      evidence: evidence.payload,
      questionEvidence: questionEvidence.payload,
      collectionRuns: collectionRuns.payload,
      fidelityChecks: fidelityChecks.payload,
      fidelityTrend: fidelityTrend.payload,
      entityAliases: entityAliases.payload,
      entityAliasCandidates: entityAliasCandidates.payload,
      entityAliasCandidateReviews: entityAliasCandidateReviews.payload,
      entityAliasAssignmentQueue: entityAliasAssignmentQueue.payload,
      entityAliasAssignmentStats: entityAliasAssignmentStats.payload,
      entityAliasAssignmentWorkbench: entityAliasAssignmentWorkbench.payload,
      entityAliasAssignmentWorkload: entityAliasAssignmentWorkload.payload,
      entityAliasAssignmentDispatchPlan: entityAliasAssignmentDispatchPlan.payload,
      savedViews: savedViews.payload,
      scores: scores.payload,
      graphs: graphs.payload,
      reports: reports.payload,
      reportJobs: reportJobs.payload,
      reportJobStats: reportJobStats.payload,
      notifications: notifications.payload,
      notificationSubscriptions: notificationSubscriptions.payload,
      notificationDeliveries: notificationDeliveries.payload,
      notificationEmailFeedback: notificationEmailFeedback.payload,
      notificationEmailSuppressions: notificationEmailSuppressions.payload,
      actions: actions.payload,
      alerts: alerts.payload,
      content: content.payload,
      traceability: traceability.payload
    },
    error: errors.length ? errors.join("; ") : null,
    fetchUrl: baseUrl,
    displayUrl,
    paths
  };
}

function pct(value: number | undefined): string {
  return `${Math.round((value || 0) * 100)}%`;
}

function optionalPct(value: number | null | undefined): string {
  return value === null || value === undefined ? "n/a" : pct(value);
}

function num(value: number | undefined): string {
  return Number(value || 0).toFixed(2);
}

function parserAgreement(run: ScoreSnapshot["answer_runs"][number] | undefined): string {
  return num(run?.analysis?.payload?.parser_comparison?.agreement_rate);
}

function parserMismatchCount(run: ScoreSnapshot["answer_runs"][number]): number {
  return Object.keys(run.analysis?.payload?.parser_comparison?.mismatched_fields || {}).length;
}

function parserComparisonText(run: ScoreSnapshot["answer_runs"][number]): string {
  const comparison = run.analysis?.payload?.parser_comparison;
  if (!comparison) return "No parser comparison";
  const callLog = comparison.secondary_result?.llm_call_log;
  const llmText = callLog
    ? ` · LLM call ${callLog.status || "unknown"}/${callLog.model || comparison.secondary_parser_engine_id || "model"} · tokens ${
        callLog.total_tokens || 0
      }`
    : "";
  return `${comparison.comparison_method_version || "parser_ab_compare_v1"} · ${
    comparison.secondary_parser_engine_id || "judge"
  } · agreement ${num(
    comparison.agreement_rate,
  )} · mismatches ${parserMismatchCount(run)}${llmText}`;
}

function shortId(value: string | undefined): string {
  return value ? value.slice(0, 8) : "unknown";
}

function boolText(value: boolean | undefined): string {
  if (value === true) return "yes";
  if (value === false) return "no";
  return "unknown";
}

function dateText(value: string | undefined): string {
  if (!value) return "unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString();
}

function uniqueText(values: Array<string | undefined>): string {
  const items = Array.from(new Set(values.filter((item): item is string => Boolean(item))));
  return items.length ? items.join(", ") : "unknown";
}

function savedViewHref(savedView: RuntimeSavedView["saved_view"]): string {
  const params = new URLSearchParams();
  const filters = savedView.filters || {};
  if (savedView.project_id) {
    params.set("project_id", savedView.project_id);
  }
  ["platform", "city", "intent_type"].forEach((key) => {
    const value = filters[key];
    if (typeof value === "string" && value) {
      params.set(key, value);
    }
  });
  if (savedView.sort) {
    params.set("sort", savedView.sort);
  }
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

function alertTone(severity: string | undefined): string {
  if (severity === "critical") return "critical";
  if (severity === "high") return "high";
  if (severity === "medium") return "medium";
  return "low";
}

function anchorId(kind: string, value: string | undefined): string {
  const raw = value || "unknown";
  return `${kind}-${raw.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function anchorHref(kind: string, value: string | undefined): string {
  return `#${anchorId(kind, value)}`;
}

function clipText(value: string | undefined, maxLength: number): string {
  const text = value || "unknown";
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

function safeHexColor(value: string | null | undefined, fallback: string): string {
  const color = (value || "").trim();
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color : fallback;
}

function countBy<T>(items: T[], selector: (item: T) => string | undefined): Record<string, number> {
  return items.reduce<Record<string, number>>((counts, item) => {
    const key = selector(item) || "unknown";
    counts[key] = (counts[key] || 0) + 1;
    return counts;
  }, {});
}

function formatCounts(counts: Record<string, number>): string {
  const entries = Object.entries(counts);
  return entries.length ? entries.map(([key, value]) => `${key}:${value}`).join(", ") : "none";
}

function launchStageText(status: AuLaunchStatus | null): string {
  if (!status) return "not loaded";
  return status.ready_for_customer_report_handoff ? "ready for customer report handoff" : "not ready";
}

function shortHash(value: string | undefined): string {
  return value ? value.slice(0, 12) : "unknown";
}

const p0aRequiredPlatforms = ["chatgpt", "perplexity"];

function questionCoverageStatus(row: Omit<QuestionDetailRow, "status" | "gapLabel">): {
  status: QuestionCoverageStatus;
  gapLabel: string;
} {
  if (row.runCount === 0) {
    return { status: "no_evidence", gapLabel: "No evidence runs" };
  }
  if (row.missingPlatforms.length) {
    return { status: "platform_gap", gapLabel: `Missing ${row.missingPlatforms.join(", ")}` };
  }
  if (row.triggeredCount === 0) {
    return { status: "trigger_gap", gapLabel: "No triggered answer" };
  }
  if (row.answerCount === 0) {
    return { status: "answer_gap", gapLabel: "No answer present" };
  }
  if (row.citationCount === 0 && row.assetCount === 0) {
    return { status: "source_gap", gapLabel: "No citation or asset" };
  }
  return { status: "covered", gapLabel: "Covered" };
}

function buildQuestionDetailRows(
  prompts: RuntimePrompt[],
  evidenceRuns: EvidenceRun[],
  filters: RuntimeFilters
): QuestionDetailRow[] {
  const promptIdByText = new Map(prompts.map((prompt) => [prompt.text, prompt.id]));
  const evidenceByPrompt = new Map<string, EvidenceRun[]>();
  evidenceRuns.forEach((run) => {
    const promptId =
      run.answer_run.prompt_question_id ||
      (run.answer_run.prompt_text ? promptIdByText.get(run.answer_run.prompt_text) : undefined);
    if (!promptId) return;
    const records = evidenceByPrompt.get(promptId) || [];
    records.push(run);
    evidenceByPrompt.set(promptId, records);
  });

  return prompts.map((prompt) => {
    const records = evidenceByPrompt.get(prompt.id) || [];
    const platforms = Array.from(new Set(records.map((run) => run.answer_run.platform).filter(Boolean))).sort();
    const requiredPlatforms = filters.platform ? [filters.platform] : p0aRequiredPlatforms;
    const missingPlatforms = requiredPlatforms.filter((platform) => !platforms.includes(platform));
    const durations = records
      .map((run) => run.collection_cost?.duration_ms || 0)
      .filter((duration) => duration > 0);
    const latestRun = records
      .slice()
      .sort(
        (left, right) =>
          new Date(right.answer_run.collected_at || "").getTime() -
          new Date(left.answer_run.collected_at || "").getTime()
      )[0];
    const baseRow = {
      prompt,
      evidenceRuns: records,
      runCount: records.length,
      answerCount: records.filter((run) => run.answer_run.answer_present === true).length,
      triggeredCount: records.filter((run) => run.answer_run.surface_triggered === true).length,
      citationCount: records.reduce((total, run) => total + run.citations.length, 0),
      assetCount: records.reduce((total, run) => total + run.evidence_assets.length, 0),
      auditCount: records.reduce((total, run) => total + run.audit_events.length, 0),
      totalCost: records.reduce((total, run) => total + Number(run.collection_cost?.total_cost || 0), 0),
      averageDurationMs: durations.length
        ? Math.round(durations.reduce((total, duration) => total + duration, 0) / durations.length)
        : 0,
      platforms,
      requiredPlatforms,
      missingPlatforms,
      cities: Array.from(new Set(records.map((run) => run.answer_run.city).filter(Boolean))).sort(),
      accessMethods: Array.from(new Set(records.map((run) => run.answer_run.access_method || "unknown"))).sort(),
      surfaceCounts: countBy(records, (run) => run.answer_run.surface),
      statusCounts: countBy(records, (run) => run.answer_run.status),
      latestRun
    };
    const status = questionCoverageStatus(baseRow);
    return { ...baseRow, ...status };
  });
}

export default async function Home({
  searchParams
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = (await searchParams) || {};
  const filters: RuntimeFilters = {
    project_id: cleanFilter(resolvedSearchParams.project_id),
    platform: cleanFilter(resolvedSearchParams.platform),
    city: cleanFilter(resolvedSearchParams.city),
    intent_type: cleanFilter(resolvedSearchParams.intent_type),
    sort: cleanFilter(resolvedSearchParams.sort)
  };
  const { data, error, displayUrl, paths } = await fetchRuntimeData(filters);
  const selectedProject =
    (filters.project_id && data.projects.records.find((record) => record.project.id === filters.project_id)) ||
    data.projects.records[0];
  const selectedProjectId = selectedProject?.project.id;
  const latestProject = selectedProject;
  const projectBrandKit = data.brandKit?.brand_kit || null;
  const entityAliasOptions = latestProject
    ? [
        ...(latestProject.brand?.id
          ? [
              {
                ref: `brand:${latestProject.brand.id}`,
                label: `${latestProject.brand.canonical_name} · brand`,
                defaultAlias:
                  latestProject.brand.official_domains?.[0] ||
                  latestProject.brand.canonical_name ||
                  latestProject.project.target_brand
              }
            ]
          : []),
        ...latestProject.competitors
          .filter((competitor) => competitor.id)
          .map((competitor) => ({
            ref: `competitor:${competitor.id}`,
            label: `${competitor.canonical_name} · competitor`,
            defaultAlias: competitor.official_domains?.[0] || competitor.canonical_name
          }))
      ]
    : [];
  const defaultEntityAlias = entityAliasOptions[0]?.defaultAlias || latestProject?.project.target_brand || "";
  const visibleAliasCandidates = data.entityAliasCandidates.records.slice(0, 5);
  const visibleAliasCandidateReviews = data.entityAliasCandidateReviews.records.slice(0, 8);
  const visibleAliasAssignmentQueue = data.entityAliasAssignmentQueue.records.slice(0, 8);
  const latestPrompt = data.prompts.records[0];
  const latestEvidence = data.evidence.records[0];
  const latestCollectionRun = data.collectionRuns.records[0];
  const latestScore = data.scores.records[0];
  const latestGraph = data.graphs.records[0];
  const latestReport = data.reports.records[0];
  const latestAction = data.actions.records[0];
  const latestContent = data.content.records[0];
  const traceability = data.traceability;
  const launchStatus = data.launchStatus;
  const launchBlockers = launchStatus?.remaining_blockers || [];
  const launchP0a = launchStatus?.p0a_design_partner;
  const launchP0b = launchStatus?.p0b_google;
  const launchP0c = launchStatus?.p0c_customer_report;
  const launchRemediationPlan = data.launchRemediationPlan;
  const remediationSummary = launchRemediationPlan?.summary;
  const remediationWorkItems = launchRemediationPlan?.work_items || [];
  const topRemediationItems = remediationWorkItems.slice(0, 4);
  const p0aEnvironmentChecklist = data.p0aEnvironmentChecklist;
  const p0aEnvironmentSummary = p0aEnvironmentChecklist?.summary;
  const missingP0aRequired = p0aEnvironmentSummary?.missing_required || [];
  const missingP0aRecommended = p0aEnvironmentSummary?.missing_recommended || [];
  const p0aEnvFileHygieneReady = p0aEnvironmentSummary?.env_file_hygiene_ready;
  const p0aEnvFileHygieneErrorCount = p0aEnvironmentSummary?.env_file_hygiene_error_count || 0;
  const p0aEnvFileHygieneWarningCount = p0aEnvironmentSummary?.env_file_hygiene_warning_count || 0;
  const p0aExecutionChecklist = data.p0aExecutionChecklist;
  const p0aExecutionSummary = p0aExecutionChecklist?.summary;
  const missingP0aArtifacts = p0aExecutionSummary?.missing_artifacts || [];
  const p0aExecutionBlockers = p0aExecutionSummary?.remaining_blockers || [];
  const missingP0aCredentials = p0aExecutionSummary?.credential_handoff_missing_required || [];
  const p0aCredentialRequest = data.p0aCredentialRequest;
  const p0aCredentialRequestSummary = p0aCredentialRequest?.summary;
  const requestedP0aCredentials = p0aCredentialRequest?.requested_credentials || [];
  const p0aCredentialRequestMissing = p0aCredentialRequestSummary?.missing_required || [];
  const p0aCredentialRequestEvidenceOutputs = p0aCredentialRequest?.evidence_outputs || [];
  const p0aCredentialFulfillment = data.p0aCredentialFulfillment;
  const p0aCredentialFulfillmentSummary = p0aCredentialFulfillment?.summary;
  const p0aCredentialFulfillmentItems = p0aCredentialFulfillment?.credential_fulfillment_items || [];
  const p0aCredentialFulfillmentMissing = p0aCredentialFulfillmentSummary?.missing_required || [];
  const p0aCredentialFulfillmentMismatches = p0aCredentialFulfillmentSummary?.presence_mismatches || [];
  const p0aCredentialClearance = data.p0aCredentialClearance;
  const p0aCredentialClearanceSummary = p0aCredentialClearance?.summary;
  const p0aCredentialClearanceMissing = p0aCredentialClearanceSummary?.missing_required || [];
  const p0aCredentialClearanceItems = p0aCredentialClearance?.missing_credential_items || [];
  const p0aCredentialClearanceSteps = p0aCredentialClearance?.operator_steps || [];
  const p0aCredentialClearanceValidation = p0aCredentialClearance?.post_update_validation_sequence || [];
  const p0aRealBatchRequest = data.p0aRealBatchRequest;
  const p0aRealBatchRequestSummary = p0aRealBatchRequest?.summary;
  const p0aRealBatchPhases = p0aRealBatchRequest?.phase_requests || [];
  const p0aRealBatchBlockingReasons = p0aRealBatchRequestSummary?.blocking_reasons || [];
  const p0aRealBatchEvidenceOutputs = p0aRealBatchRequest?.evidence_outputs || [];
  const p0aRealBatchFulfillment = data.p0aRealBatchFulfillment;
  const p0aRealBatchFulfillmentSummary = p0aRealBatchFulfillment?.summary;
  const p0aRealBatchFulfillmentItems = p0aRealBatchFulfillment?.real_batch_fulfillment_items || [];
  const p0aRealBatchFulfillmentMissing = p0aRealBatchFulfillmentSummary?.missing_required || [];
  const p0aRealBatchFulfillmentBlockers = p0aRealBatchFulfillmentSummary?.blocking_reasons || [];
  const p0aRealBatchClearance = data.p0aRealBatchClearance;
  const p0aRealBatchClearanceSummary = p0aRealBatchClearance?.summary;
  const p0aRealBatchClearanceItems = p0aRealBatchClearance?.phase_clearance_items || [];
  const p0aRealBatchClearanceMissing = p0aRealBatchClearanceSummary?.missing_required || [];
  const p0aRealBatchClearanceSteps = p0aRealBatchClearance?.operator_steps || [];
  const p0aRealBatchClearanceValidation = p0aRealBatchClearance?.post_update_validation_sequence || [];
  const p0bGoogleExecutionChecklist = data.p0bGoogleExecutionChecklist;
  const p0bGoogleExecutionSummary = p0bGoogleExecutionChecklist?.summary;
  const missingP0bSmokeEnv = p0bGoogleExecutionSummary?.missing_required_environment || [];
  const missingP0bFullRunEnv = p0bGoogleExecutionSummary?.missing_full_run_required_environment || [];
  const missingP0bSelectors = p0bGoogleExecutionSummary?.missing_selector_groups || [];
  const missingP0bEnvironmentHandoff = p0bGoogleExecutionSummary?.environment_handoff_missing_required || [];
  const missingP0bManualBackfill = p0bGoogleExecutionSummary?.manual_backfill_handoff_missing_reasons || [];
  const p0bChecklistBlockers = p0bGoogleExecutionSummary?.remaining_blockers || [];
  const p0bEnvFileHygieneReady = p0bGoogleExecutionSummary?.env_file_hygiene_ready;
  const p0bEnvFileHygieneErrorCount = p0bGoogleExecutionSummary?.env_file_hygiene_error_count || 0;
  const p0bEnvFileHygieneWarningCount = p0bGoogleExecutionSummary?.env_file_hygiene_warning_count || 0;
  const p0bGoogleEnvironmentRequest = data.p0bGoogleEnvironmentRequest;
  const p0bGoogleEnvironmentRequestSummary = p0bGoogleEnvironmentRequest?.summary;
  const p0bGoogleEnvironmentRequestMissing = p0bGoogleEnvironmentRequestSummary?.missing_required || [];
  const p0bGoogleEnvironmentItems = p0bGoogleEnvironmentRequest?.environment_items || [];
  const p0bGoogleSelectorItems = p0bGoogleEnvironmentRequest?.selector_items || [];
  const p0bGoogleFileItems = p0bGoogleEnvironmentRequest?.file_items || [];
  const p0bGoogleDependencyItems = p0bGoogleEnvironmentRequest?.dependency_items || [];
  const p0bGoogleCrossStageReuseHints = p0bGoogleEnvironmentRequest?.cross_stage_reuse_hints || [];
  const p0bGoogleEnvironmentFulfillment = data.p0bGoogleEnvironmentFulfillment;
  const p0bGoogleEnvironmentFulfillmentSummary = p0bGoogleEnvironmentFulfillment?.summary;
  const p0bGoogleEnvironmentFulfillmentMissing =
    p0bGoogleEnvironmentFulfillmentSummary?.missing_required || [];
  const p0bGoogleEnvironmentFulfillmentMismatches =
    p0bGoogleEnvironmentFulfillmentSummary?.presence_mismatches || [];
  const p0bGoogleEnvironmentFulfillmentItems =
    p0bGoogleEnvironmentFulfillment?.environment_fulfillment_items || [];
  const p0bGoogleEnvironmentClearance = data.p0bGoogleEnvironmentClearance;
  const p0bGoogleEnvironmentClearanceSummary = p0bGoogleEnvironmentClearance?.summary;
  const p0bGoogleEnvironmentClearanceMissing =
    p0bGoogleEnvironmentClearanceSummary?.missing_required || [];
  const p0bGoogleEnvironmentClearanceMismatches =
    p0bGoogleEnvironmentClearanceSummary?.presence_mismatches || [];
  const p0bGoogleEnvironmentClearanceItems =
    p0bGoogleEnvironmentClearance?.environment_clearance_items || [];
  const p0bGoogleEnvironmentClearanceSteps = p0bGoogleEnvironmentClearance?.operator_steps || [];
  const p0bGoogleEnvironmentClearanceValidation =
    p0bGoogleEnvironmentClearance?.post_update_validation_sequence || [];
  const p0bGoogleManualBackfillRequest = data.p0bGoogleManualBackfillRequest;
  const p0bGoogleManualBackfillRequestSummary = p0bGoogleManualBackfillRequest?.summary;
  const p0bGoogleManualBackfillRequestMissing = p0bGoogleManualBackfillRequestSummary?.missing_reasons || [];
  const p0bGoogleManualBackfillRequiredFields = p0bGoogleManualBackfillRequest?.required_fields || [];
  const p0bGoogleManualBackfillOperatorRequirements = p0bGoogleManualBackfillRequest?.operator_requirements || [];
  const p0bGoogleManualBackfillEvidenceOutputs = p0bGoogleManualBackfillRequest?.evidence_outputs || [];
  const p0bGoogleManualBackfillFulfillment = data.p0bGoogleManualBackfillFulfillment;
  const p0bGoogleManualBackfillFulfillmentSummary = p0bGoogleManualBackfillFulfillment?.summary;
  const p0bGoogleManualBackfillFulfillmentMissing =
    p0bGoogleManualBackfillFulfillmentSummary?.missing_required || [];
  const p0bGoogleManualBackfillFulfillmentErrors =
    p0bGoogleManualBackfillFulfillmentSummary?.verification_errors || [];
  const p0bGoogleManualBackfillFulfillmentItems =
    p0bGoogleManualBackfillFulfillment?.manual_backfill_fulfillment_items || [];
  const p0bGoogleManualBackfillClearance = data.p0bGoogleManualBackfillClearance;
  const p0bGoogleManualBackfillClearanceSummary = p0bGoogleManualBackfillClearance?.summary;
  const p0bGoogleManualBackfillClearanceMissing =
    p0bGoogleManualBackfillClearanceSummary?.missing_required || [];
  const p0bGoogleManualBackfillClearanceErrors =
    p0bGoogleManualBackfillClearanceSummary?.verification_errors || [];
  const p0bGoogleManualBackfillClearanceItems =
    p0bGoogleManualBackfillClearance?.manual_backfill_clearance_items || [];
  const p0bGoogleManualBackfillClearanceSteps = p0bGoogleManualBackfillClearance?.operator_steps || [];
  const p0bGoogleManualBackfillClearanceValidation =
    p0bGoogleManualBackfillClearance?.post_update_validation_sequence || [];
  const p0bGooglePhaseExecutionRequest = data.p0bGooglePhaseExecutionRequest;
  const p0bGooglePhaseExecutionRequestSummary = p0bGooglePhaseExecutionRequest?.summary;
  const p0bGooglePhaseExecutionPhases = p0bGooglePhaseExecutionRequest?.phase_requests || [];
  const p0bGooglePhaseExecutionBlockingReasons =
    p0bGooglePhaseExecutionRequestSummary?.blocking_reasons || [];
  const p0bGooglePhaseExecutionEvidenceOutputs = p0bGooglePhaseExecutionRequest?.evidence_outputs || [];
  const p0bGooglePhaseExecutionFulfillment = data.p0bGooglePhaseExecutionFulfillment;
  const p0bGooglePhaseExecutionFulfillmentSummary = p0bGooglePhaseExecutionFulfillment?.summary;
  const p0bGooglePhaseExecutionFulfillmentItems =
    p0bGooglePhaseExecutionFulfillment?.phase_fulfillment_items || [];
  const p0bGooglePhaseExecutionFulfillmentMissing =
    p0bGooglePhaseExecutionFulfillmentSummary?.missing_required || [];
  const p0bGooglePhaseExecutionFulfillmentBlockers =
    p0bGooglePhaseExecutionFulfillmentSummary?.blocking_reasons || [];
  const p0bGooglePhaseExecutionClearance = data.p0bGooglePhaseExecutionClearance;
  const p0bGooglePhaseExecutionClearanceSummary = p0bGooglePhaseExecutionClearance?.summary;
  const p0bGooglePhaseExecutionClearanceItems =
    p0bGooglePhaseExecutionClearance?.phase_execution_clearance_items || [];
  const p0bGooglePhaseExecutionClearanceMissing =
    p0bGooglePhaseExecutionClearanceSummary?.missing_required || [];
  const p0bGooglePhaseExecutionClearanceBlockers =
    p0bGooglePhaseExecutionClearanceSummary?.blocking_reasons || [];
  const p0bGooglePhaseExecutionClearanceSteps = p0bGooglePhaseExecutionClearance?.operator_steps || [];
  const p0bGooglePhaseExecutionClearanceValidation =
    p0bGooglePhaseExecutionClearance?.post_update_validation_sequence || [];
  const externalDependencyHandoff = data.externalDependencyHandoff;
  const externalDependencySummary = externalDependencyHandoff?.summary;
  const externalDependencyGroups = externalDependencyHandoff?.dependency_groups || [];
  const topExternalDependencyGroups = externalDependencyGroups.slice(0, 5);
  const externalNextDependencyItem = externalDependencyHandoff?.next_dependency_item;
  const externalClearanceSequence = externalDependencyHandoff?.clearance_sequence;
  const externalClearanceSteps = externalClearanceSequence?.steps || [];
  const topExternalClearanceSteps = externalClearanceSteps.slice(0, 6);
  const externalDependencyClearance = data.externalDependencyClearance;
  const externalDependencyClearanceSteps = externalDependencyClearance?.steps || [];
  const topExternalDependencyClearanceSteps = externalDependencyClearanceSteps.slice(0, 6);
  const externalDependencyWouldExecuteStep = externalDependencyClearanceSteps.find((step) => step.would_execute);
  const externalDependencyCurrentRequest = externalDependencyClearance?.current_step_request_context;
  const externalDependencyCurrentSequence = externalDependencyClearance?.current_recommended_sequence || [];
  const broaderPlatformRegistry = data.broaderPlatformRegistry;
  const broaderPlatformSummary = broaderPlatformRegistry?.summary;
  const broaderPlatformCandidates = broaderPlatformRegistry?.candidate_platforms || [];
  const broaderPlatformSequence = broaderPlatformRegistry?.recommended_sequence || [];
  const retestSchedulerPlan = data.retestSchedulerPlan;
  const retestSchedulerScope = retestSchedulerPlan?.scope;
  const retestSchedulerTimeline = retestSchedulerPlan?.timeline || [];
  const retestExecutionStatus = data.retestExecutionStatus;
  const retestExecutionSummary = retestExecutionStatus?.summary;
  const retestExecutionWindows = retestExecutionStatus?.windows || [];
  const handoffDossier = data.handoffDossier;
  const handoffSummary = handoffDossier?.summary;
  const handoffReadinessAudit = handoffDossier?.customer_handoff_readiness_audit;
  const handoffNextWorkItem = handoffDossier?.next_work_item;
  const customerHandoffReadiness = data.customerHandoffReadiness;
  const customerHandoffReadinessSummary = customerHandoffReadiness?.summary;
  const customerHandoffReadinessBlockedGateIds =
    customerHandoffReadinessSummary?.blocked_customer_gate_ids || [];
  const customerHandoffClearance = data.customerHandoffClearance;
  const customerHandoffClearanceSummary = customerHandoffClearance?.summary;
  const customerHandoffClearanceItems = customerHandoffClearance?.customer_handoff_clearance_items || [];
  const topCustomerHandoffClearanceItems = customerHandoffClearanceItems.slice(0, 8);
  const customerHandoffClearanceSteps = customerHandoffClearance?.operator_steps || [];
  const topCustomerHandoffClearanceSteps = customerHandoffClearanceSteps.slice(0, 5);
  const customerHandoffClearanceValidation =
    customerHandoffClearance?.post_update_validation_sequence || [];
  const nextWorkItemPacket = data.nextWorkItemPacket;
  const nextWorkItemSummary = nextWorkItemPacket?.summary;
  const nextWorkItemCommands = nextWorkItemPacket?.commands || [];
  const nextWorkItemVerificationCommands = nextWorkItemPacket?.verification_commands || [];
  const nextWorkItemEvidenceOutputs = nextWorkItemPacket?.evidence_outputs || [];
  const nextWorkItemExecutionContext = nextWorkItemPacket?.execution_context;
  const nextWorkItemLinkedRequest = nextWorkItemExecutionContext?.linked_request_packet;
  const nextWorkItemLinkedDependencyGroup = nextWorkItemExecutionContext?.linked_dependency_group;
  const nextWorkItemRecommendedSequence = nextWorkItemExecutionContext?.recommended_sequence || [];
  const deliveryProgress = data.deliveryProgress;
  const deliveryProgressSummary = deliveryProgress?.summary;
  const deliveryProgressGates = deliveryProgress?.progress_gates || [];
  const blockedDeliveryProgressGateIds = deliveryProgressSummary?.blocked_progress_gate_ids || [];
  const topDeliveryProgressGates = deliveryProgressGates.slice(0, 8);
  const scoreWeightConfig = data.scoreWeights?.score_weight_config || null;
  const savedScoreWeightConfig = scoreWeightConfig?.id ? scoreWeightConfig : null;
  const scoreWeightAuditEvent = data.scoreWeights?.audit_events[0]?.event_type || "default weights";
  const scoreFormulaOptions = data.scoreFormulas.formulas.length
    ? data.scoreFormulas.formulas
    : [
        {
          formula_version: "au_visibility_v1",
          weights: defaultScoreWeights,
          description: "Default AU visibility score weights",
          status: "active",
          supersedes: null
        }
      ];
  const selectedFormulaVersion =
    savedScoreWeightConfig?.formula_version ||
    latestScore?.snapshot.formula_version ||
    scoreWeightConfig?.formula_version ||
    scoreFormulaOptions[0].formula_version;
  const selectedFormula =
    scoreFormulaOptions.find((formula) => formula.formula_version === selectedFormulaVersion) || scoreFormulaOptions[0];
  const configuredScoreWeights =
    savedScoreWeightConfig?.weights ||
    latestScore?.snapshot.component_weights_snapshot ||
    scoreWeightConfig?.weights ||
    selectedFormula.weights ||
    defaultScoreWeights;
  const scoreWeightTotal = scoreComponentNames.reduce(
    (total, component) => total + Number(configuredScoreWeights[component] || 0),
    0
  );
  const latestScoreWeightTotal = scoreComponentNames.reduce(
    (total, component) => total + Number(latestScore?.snapshot.component_weights_snapshot?.[component] || 0),
    0
  );
  const reportArtifactBase = latestReport
    ? `${displayUrl}/v1/reports/runtime/${latestReport.report_export.id}/artifact`
    : null;
  const totalAuditEvents =
    data.auditEvents.total_count ||
    (latestEvidence?.audit_events.length || 0) +
    data.collectionRuns.records.reduce((total, item) => total + item.audit_events.length, 0) +
    data.fidelityChecks.records.reduce((total, item) => total + item.audit_events.length, 0) +
    data.entityAliases.records.reduce((total, item) => total + item.audit_events.length, 0) +
    data.humanReviews.records.reduce((total, item) => total + item.audit_events.length, 0) +
    (latestScore?.audit_events.length || 0) +
    (latestReport?.audit_events.length || 0) +
    (latestAction?.audit_events.length || 0) +
    (latestContent?.audit_events.length || 0) +
    (traceability?.audit_events.length || 0);
  const promptIntentCount = new Set(data.prompts.records.map((prompt) => prompt.intent_type)).size;
  const promptCityCount = new Set(data.prompts.records.map((prompt) => prompt.city)).size;
  const questionDetailRows = buildQuestionDetailRows(data.prompts.records, data.questionEvidence.records, filters);
  const coveredQuestionCount = questionDetailRows.filter((row) => row.status === "covered").length;
  const questionCoverageRate = questionDetailRows.length ? coveredQuestionCount / questionDetailRows.length : 0;
  const questionGapRows = questionDetailRows.filter((row) => row.status !== "covered");
  const questionStatusCounts = countBy(questionDetailRows, (row) => row.status);
  const latestReportScore = latestReport?.score_snapshots[0];
  const latestReportGraph = latestReport?.citation_graph;
  const reportPlatformWeights = latestReport?.report_export.platform_weights_snapshot || {};
  const reportPlatforms = latestReport ? uniqueText(latestReport.answer_runs.map((run) => run.platform)) : "unknown";
  const reportAccessMethods = latestReport
    ? uniqueText(latestReport.answer_runs.map((run) => run.access_method))
    : "unknown";
  const reportCities = latestReport ? uniqueText(latestReport.answer_runs.map((run) => run.city)) : "unknown";
  const reportAccessMethodCounts = latestReport ? countBy(latestReport.answer_runs, (run) => run.access_method) : {};
  const reportPlatformCounts = latestReport ? countBy(latestReport.answer_runs, (run) => run.platform) : {};
  const reportMethodDisclosure = latestReport?.report_export.method_disclosure;
  const latestFidelityCheck =
    data.fidelityChecks.records.find((item) => item.fidelity_check.report_export_id === latestReport?.report_export.id) ||
    data.fidelityChecks.records[0];
  const reportFrozenAccessMethodCounts = reportMethodDisclosure?.access_method_distribution || reportAccessMethodCounts;
  const reportFrozenPlatformCounts = reportMethodDisclosure?.platform_distribution || reportPlatformCounts;
  const reportFidelity = reportMethodDisclosure?.api_browser_fidelity;
  const reportScoreRateDisclosure = reportMethodDisclosure?.score_rate_denominators;
  const reportRateDefinitions = reportScoreRateDisclosure?.definitions || {};
  const reportRateEvidenceDenominators = reportScoreRateDisclosure?.evidence_denominators || {};
  const runtimeFidelity = latestFidelityCheck?.fidelity_check;
  const reportGate = reportMethodDisclosure?.google_spike_gate;
  const reportOfficialApiCount =
    runtimeFidelity?.official_api_records ?? reportFidelity?.official_api_records ?? reportFrozenAccessMethodCounts.official_api ?? 0;
  const reportBrowserCount =
    runtimeFidelity?.browser_records ?? reportFidelity?.browser_records ?? reportFrozenAccessMethodCounts.browser ?? 0;
  const reportFidelityStatus =
    runtimeFidelity?.status || reportFidelity?.status || (reportOfficialApiCount && reportBrowserCount ? "sample_required" : "not_run");
  const reportGoogleCoverage =
    reportMethodDisclosure?.google_coverage ||
    ((reportPlatformCounts.google || 0) > 0 ? "limited_coverage_appendix_only" : "limited_coverage_no_google_rows");
  const reportGoogleGateStatus = reportGate?.gate_status || "not_run";
  const reportLimitedCoverage = reportGate?.limited_coverage ?? true;
  const reportComparablePairs = runtimeFidelity?.comparable_prompt_city_pairs ?? reportFidelity?.comparable_prompt_city_pairs ?? 0;
  const reportDifferenceRateValue = runtimeFidelity?.difference_rate ?? reportFidelity?.difference_rate;
  const reportDifferenceRate: string | number =
    reportDifferenceRateValue === null || reportDifferenceRateValue === undefined ? "n/a" : reportDifferenceRateValue;
  const reportFidelityMismatchCount = runtimeFidelity?.mismatch_count ?? reportFidelity?.mismatch_count ?? 0;
  const fidelityTrend = data.fidelityTrend;
  const fidelityTrendSampleText = fidelityTrend
    ? `${fidelityTrend.sampled_count}/${fidelityTrend.total_count}`
    : "0/0";
  const fidelityTrendWindow = fidelityTrend
    ? `${dateText(fidelityTrend.earliest_checked_at || undefined)} -> ${dateText(
        fidelityTrend.latest_checked_at || undefined,
      )}`
    : "unknown";
  const reportFidelityAudit =
    latestFidelityCheck?.audit_events[0]?.event_type || (latestFidelityCheck ? "api_browser_fidelity_checked" : "no check");
  const reportScreenshotCount =
    reportMethodDisclosure?.evidence_asset_coverage?.screenshot_records ??
    (latestReport?.answer_runs.filter((run) => run.access_method === "browser" || run.access_method === "manual").length || 0);
  const reportHtmlSnapshotCount = reportMethodDisclosure?.evidence_asset_coverage?.html_snapshot_records ?? 0;
  const reportTriggerDenominator =
    reportRateDefinitions.trigger_rate?.denominator || "all attempted evidence records in this report window";
  const reportMentionDenominator =
    reportRateDefinitions.mention_rate?.denominator || "surface_triggered evidence records, not all attempted records";
  const reportRecommendationDenominator =
    reportRateDefinitions.recommendation_rate?.denominator ||
    "surface_triggered evidence records, not all attempted records";
  const reportEvidenceAttemptedRecords = reportRateEvidenceDenominators.attempted_records ?? latestReport?.answer_runs.length ?? 0;
  const reportEvidenceTriggeredRecords =
    reportRateEvidenceDenominators.surface_triggered_records ??
    latestReport?.answer_runs.filter((run) => run.surface_triggered).length ??
    0;
  const reportEvidenceTriggerRate =
    reportScoreRateDisclosure?.evidence_trigger_rate ??
    (reportEvidenceAttemptedRecords ? reportEvidenceTriggeredRecords / reportEvidenceAttemptedRecords : 0);
  const latestRetestComparison = latestAction?.retest_comparisons[0];
  const activeFilterCount = [filters.platform, filters.city, filters.intent_type].filter(Boolean).length;
  const filterLabel = activeFilterCount
    ? [filters.platform, filters.city, filters.intent_type].filter(Boolean).join(" / ")
    : "All runtime evidence";
  const selectedProjectLabel = selectedProject
    ? `${selectedProject.tenant.name} / ${selectedProject.project.name}`
    : "No runtime project";
  const evidenceExportUrl = `${displayUrl}${paths.evidenceExport}`;
  const projectLifecycleExportUrl = `${displayUrl}${paths.projectLifecycleExport}`;
  const auditEventsExportUrl = `${displayUrl}${paths.auditEventsExport}`;
  const evidenceSort = data.evidence.sort || filters.sort || "collected_at_desc";
  const runtimeViewName = activeFilterCount
    ? `${selectedProject?.project.name || "Runtime project"} · ${filterLabel} · ${evidenceSort}`
    : `${selectedProject?.project.name || "Runtime project"} · All runtime evidence · ${evidenceSort}`;
  const reportMarkdownUrl = reportArtifactPath(reportArtifactBase, "markdown", { ...filters, sort: evidenceSort });
  const reportCsvUrl = reportArtifactPath(reportArtifactBase, "csv", { ...filters, sort: evidenceSort });
  const reportPdfUrl = reportArtifactPath(reportArtifactBase, "pdf", { ...filters, sort: evidenceSort });
  const reportSignedPdfUrl = reportArtifactSignedUrlPath(reportArtifactBase, "pdf", { ...filters, sort: evidenceSort });
  const whiteLabelClientName =
    projectBrandKit?.client_name || latestProject?.brand?.canonical_name || latestProject?.project.target_brand || "Client";
  const whiteLabelPreparedBy = projectBrandKit?.prepared_by || "GENO SaaS AU";
  const whiteLabelLogoUrl = projectBrandKit?.logo_url || "https://examplebrand.example/logo.png";
  const whiteLabelPrimaryColor = safeHexColor(projectBrandKit?.primary_color, "#0f766e");
  const whiteLabelSecondaryColor = safeHexColor(projectBrandKit?.secondary_color, "#111827");
  const whiteLabelFooterText = projectBrandKit?.footer_text || "Prepared for AU GEO visibility review";
  const brandKitAudit = data.brandKit?.audit_events[0];
  const reportWhiteLabelPdfUrl = reportArtifactPath(
    reportArtifactBase,
    "pdf",
    { ...filters, sort: evidenceSort },
    {
      template: "white_label",
      client_name: whiteLabelClientName,
      prepared_by: whiteLabelPreparedBy
    }
  );
  const reportSignedWhiteLabelPdfUrl = reportArtifactSignedUrlPath(
    reportArtifactBase,
    "pdf",
    { ...filters, sort: evidenceSort },
    {
      template: "white_label",
      client_name: whiteLabelClientName,
      prepared_by: whiteLabelPreparedBy
    }
  );
  const reportArtifactFilters = { ...filters, sort: evidenceSort };
  const latestContentDraft = latestContent?.content_drafts[0];
  const topReviewQueueItem = data.humanReviewQueue.records[0];
  const reviewTarget =
    topReviewQueueItem
      ? {
          targetType: topReviewQueueItem.target_type,
          targetId: topReviewQueueItem.target_id,
          label: topReviewQueueItem.title
        }
      : latestScore?.snapshot.id
      ? {
          targetType: "visibility_score_snapshot",
          targetId: latestScore.snapshot.id,
          label: `score ${num(latestScore.snapshot.final_score)}`
        }
      : latestContentDraft?.draft.id
        ? {
            targetType: "content_draft",
            targetId: latestContentDraft.draft.id,
            label: latestContentDraft.draft.title
          }
        : latestEvidence?.answer_run.id
          ? {
              targetType: "answer_run",
              targetId: latestEvidence.answer_run.id,
              label: latestEvidence.answer_run.prompt_text || latestEvidence.answer_run.id
            }
          : latestProject?.project.id
            ? {
                targetType: "project",
                targetId: latestProject.project.id,
                label: latestProject.project.name
              }
            : null;

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">GENO SaaS AU</p>
          <h1>Runtime Evidence Console</h1>
        </div>
        <div className="apiBox">
          <span>Runtime API</span>
          <strong>{displayUrl}</strong>
        </div>
      </section>

      {error ? (
        <section className="notice">
          <strong>Runtime data unavailable.</strong>
          <span>{error}</span>
          <code>docker compose -f infra/docker-compose.yml --profile worker run --rm collector-worker</code>
        </section>
      ) : null}

      <section className="filterBar" aria-label="runtime filters">
        <div>
          <h2>Runtime Filters</h2>
          <span>
            {selectedProjectLabel} · {filterLabel}
          </span>
        </div>
        <form className="filterForm">
          <label>
            <span>Project</span>
            <select name="project_id" defaultValue={selectedProjectId || ""}>
              {data.projects.records.length ? (
                data.projects.records.map((record) => (
                  <option key={record.project.id} value={record.project.id}>
                    {record.tenant.name} / {record.project.name}
                  </option>
                ))
              ) : (
                <option value="">No runtime project</option>
              )}
            </select>
          </label>
          <label>
            <span>Platform</span>
            <select name="platform" defaultValue={filters.platform || ""}>
              <option value="">All platforms</option>
              <option value="chatgpt">chatgpt</option>
              <option value="google">google</option>
              <option value="perplexity">perplexity</option>
              <option value="gemini">gemini</option>
              <option value="bing_copilot">bing_copilot</option>
              <option value="claude">claude</option>
              <option value="youtube">youtube</option>
              <option value="reddit">reddit</option>
              <option value="productreview">productreview</option>
            </select>
          </label>
          <label>
            <span>Evidence city</span>
            <select name="city" defaultValue={filters.city || ""}>
              <option value="">All cities</option>
              <option value="Australia">Australia</option>
              <option value="Sydney">Sydney</option>
              <option value="Melbourne">Melbourne</option>
              <option value="Brisbane">Brisbane</option>
            </select>
          </label>
          <label>
            <span>Intent</span>
            <select name="intent_type" defaultValue={filters.intent_type || ""}>
              <option value="">All intents</option>
              <option value="brand_awareness">brand_awareness</option>
              <option value="category_recommendation">category_recommendation</option>
              <option value="city_category_recommendation">city_category_recommendation</option>
              <option value="competitor_comparison">competitor_comparison</option>
              <option value="purchase_decision">purchase_decision</option>
              <option value="review_reputation">review_reputation</option>
              <option value="price">price</option>
              <option value="service_coverage">service_coverage</option>
              <option value="local_trust">local_trust</option>
              <option value="alternative">alternative</option>
            </select>
          </label>
          <label>
            <span>Sort evidence</span>
            <select name="sort" defaultValue={filters.sort || "collected_at_desc"}>
              <option value="collected_at_desc">Newest first</option>
              <option value="collected_at_asc">Oldest first</option>
              <option value="cost_desc">Highest cost</option>
              <option value="cost_asc">Lowest cost</option>
              <option value="citation_count_desc">Most citations</option>
              <option value="audit_count_desc">Most audit events</option>
            </select>
          </label>
          <button className="actionButton" type="submit">
            Apply filters
          </button>
          <a className="resetLink" href="/">
            Reset
          </a>
          <a className="resetLink" href={evidenceExportUrl}>
            Export Evidence CSV
          </a>
        </form>
        <dl className="facts filterFacts">
          <Fact label="Project query" value={paths.projects} />
          <Fact label="Selected project" value={selectedProjectId || "No project selected"} />
          <Fact label="Prompts query" value={paths.prompts} />
          <Fact label="Evidence query" value={paths.evidence} />
          <Fact label="Export query" value={paths.evidenceExport} />
          <Fact label="Saved views query" value={paths.savedViews} />
          <Fact label="Brand kit query" value={paths.brandKit} />
          <Fact label="Report query" value={paths.reports} />
          <Fact label="Evidence sort" value={evidenceSort} />
        </dl>
        <div className="savedViews">
          <form action={saveCurrentRuntimeView} className="saveViewForm">
            <input type="hidden" name="project_id" value={selectedProjectId || ""} />
            <input type="hidden" name="platform" value={filters.platform || ""} />
            <input type="hidden" name="city" value={filters.city || ""} />
            <input type="hidden" name="intent_type" value={filters.intent_type || ""} />
            <input type="hidden" name="sort" value={evidenceSort} />
            <input type="hidden" name="query_path" value={paths.evidence} />
            <input type="hidden" name="export_path" value={paths.evidenceExport} />
            <label>
              <span>Saved view name</span>
              <input name="name" defaultValue={runtimeViewName} />
            </label>
            <button className="actionButton" type="submit" disabled={!latestProject}>
              Save view
            </button>
          </form>
          <div className="savedViewList">
            <h3>Saved Views</h3>
            {data.savedViews.records.length ? (
              <ul className="plainList">
                {data.savedViews.records.map((item) => (
                  <li key={item.saved_view.id}>
                    <strong>{item.saved_view.name}</strong>
                    <a href={savedViewHref(item.saved_view)}>{item.saved_view.query_path}</a>
                    <small>
                      {item.saved_view.sort} · {item.audit_events[0]?.event_type || "no audit"} ·{" "}
                      {item.audit_events[0]?.after_hash || "no hash"}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <small>No saved runtime views yet.</small>
            )}
          </div>
        </div>
      </section>

      <section className="launchStatusPanel" aria-label="AU launch status gate">
        <div className="launchStatusHeader">
          <div>
            <p className="eyebrow">AU Launch Gate</p>
            <h2>{launchStageText(launchStatus)}</h2>
            <span>
              {launchStatus?.launch_status_version || "au_launch_status_v1"} · hash{" "}
              {shortHash(launchStatus?.launch_status_hash)}
            </span>
          </div>
          <div className={`launchBadge ${launchStatus?.ready_for_customer_report_handoff ? "ready" : "blocked"}`}>
            {launchStatus?.status || "unknown"}
          </div>
        </div>
        <div className="launchStageGrid">
          <Fact
            label="P0a design partner"
            value={launchP0a?.ready_for_design_partner ? "ready" : launchP0a?.status || "not ready"}
          />
          <Fact
            label="P0b Google scoring"
            value={
              launchP0b?.google_main_scoring_allowed
                ? "allowed"
                : launchP0b?.limited_coverage
                  ? "limited coverage"
                  : "not ready"
            }
          />
          <Fact label="P0c report contract" value={launchP0c?.status || "unknown"} />
          <Fact label="Next action" value={launchStatus?.next_action || "run au-launch-status"} />
        </div>
        <div className="launchEvidenceGrid">
          <span>
            P0a completion {pct((launchP0a?.completion?.completion_percent || 0) / 100)} · design-ready{" "}
            {pct((launchP0a?.completion?.design_ready_artifact_percent || 0) / 100)}
          </span>
          <span>
            P0b package artifacts {launchP0b?.package_summary?.artifact_count || 0} · failed{" "}
            {launchP0b?.package_summary?.failed_artifacts?.length || 0}
          </span>
          <span>
            P0c audit events {launchP0c?.audit_event_count || 0} · {launchP0c?.google_coverage || "coverage unknown"}
          </span>
          <span>Generated {dateText(launchStatus?.generated_at)}</span>
        </div>
        <div className="launchBlockers">
          <strong>Remaining blockers</strong>
          {launchBlockers.length ? (
            <ul>
              {launchBlockers.slice(0, 6).map((blocker) => (
                <li key={blocker}>{blocker}</li>
              ))}
            </ul>
          ) : (
            <span>No launch blockers recorded.</span>
          )}
          {launchBlockers.length > 6 ? <span>{launchBlockers.length - 6} more blockers in API payload</span> : null}
        </div>
        <div className="launchRemediation">
          <div className="launchRemediationHeader">
            <strong>Remediation plan</strong>
            <span>
              {launchRemediationPlan?.remediation_plan_version || "au_launch_remediation_plan_v1"} · hash{" "}
              {shortHash(launchRemediationPlan?.remediation_plan_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Next work item {launchRemediationPlan?.next_work_item_id || "run remediation plan"}</span>
            <span>
              Covered blockers {remediationSummary?.covered_blocker_count || 0}/
              {remediationSummary?.blocker_count || 0}
            </span>
            <span>Work items {remediationSummary?.work_item_count || 0}</span>
            <span>Unmapped blockers {remediationSummary?.unmapped_blocker_count || 0}</span>
          </div>
          {topRemediationItems.length ? (
            <div className="remediationList">
              {topRemediationItems.map((item) => (
                <div className="remediationItem" key={item.id}>
                  <div>
                    <strong>{item.id}</strong>
                    <span>
                      {item.stage || "stage"} · {item.status || "status"} · {item.dependency_class || "dependency"}
                    </span>
                  </div>
                  <p>{item.title || item.acceptance || "No title"}</p>
                  <code>{item.commands?.[0]?.shell || "no command"}</code>
                  <small>
                    verifies {item.verification_commands?.[0]?.shell || "no verifier"} · clears{" "}
                    {item.blocker_count || item.clears_blockers?.length || 0}
                  </small>
                </div>
              ))}
            </div>
          ) : (
            <span className="remediationEmpty">No remediation work items recorded.</span>
          )}
          <code>{paths.launchRemediationPlan}</code>
        </div>
        <div className="p0aEnvironmentChecklist">
          <div className="launchRemediationHeader">
            <strong>P0a environment checklist</strong>
            <span>
              {p0aEnvironmentChecklist?.environment_checklist_version || "au_p0a_environment_checklist_v1"} · hash{" "}
              {shortHash(p0aEnvironmentChecklist?.environment_checklist_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Ready {p0aEnvironmentChecklist?.environment_checklist_ready ? "yes" : "no"}</span>
            <span>Next action {p0aEnvironmentChecklist?.next_action || "run checklist"}</span>
            <span>
              Required {p0aEnvironmentSummary?.required_present_count || 0}/
              {p0aEnvironmentSummary?.required_count || 0}
            </span>
            <span>Recommended missing {p0aEnvironmentSummary?.missing_recommended_count || 0}</span>
            <span>
              Env-file hygiene {p0aEnvFileHygieneReady ? "ready" : "blocked"} · errors{" "}
              {p0aEnvFileHygieneErrorCount} · warnings {p0aEnvFileHygieneWarningCount}
            </span>
          </div>
          <div className="environmentChecklistGrid">
            <div>
              <strong>Missing required</strong>
              {missingP0aRequired.length ? (
                <ul className="plainList">
                  {missingP0aRequired.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <small>All required variables are present.</small>
              )}
            </div>
            <div>
              <strong>Missing recommended</strong>
              {missingP0aRecommended.length ? (
                <ul className="plainList">
                  {missingP0aRecommended.slice(0, 4).map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <small>Recommended object store variables are present.</small>
              )}
            </div>
          </div>
          <div className="handoffBoundary">
            <span>
              Hard gate{" "}
              {p0aEnvironmentChecklist?.verification_commands?.find((command) => command.id === "hard_env_gate")
                ?.shell || "python3 scripts/verify_au_p0a_env_report.py --require-ready-environment"}
            </span>
            <span>
              Verifiers: runbook {p0aEnvironmentSummary?.runbook_verifier_status || "unknown"} · environment{" "}
              {p0aEnvironmentSummary?.environment_verifier_status || "unknown"}
            </span>
            <span>Evidence outputs {p0aEnvironmentChecklist?.evidence_outputs?.length || 0}</span>
          </div>
          <code>{paths.p0aEnvironmentChecklist}</code>
        </div>
        <div className="p0aExecutionChecklist">
          <div className="launchRemediationHeader">
            <strong>P0a execution checklist</strong>
            <span>
              {p0aExecutionChecklist?.execution_checklist_version || "au_p0a_execution_checklist_v1"} · hash{" "}
              {shortHash(p0aExecutionChecklist?.p0a_execution_checklist_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Ready {p0aExecutionChecklist?.p0a_execution_checklist_ready ? "yes" : "no"}</span>
            <span>Design partner {p0aExecutionChecklist?.ready_for_design_partner ? "ready" : "blocked"}</span>
            <span>Next action {p0aExecutionChecklist?.next_action || "run checklist"}</span>
            <span>Full batch runs {p0aExecutionSummary?.full_batch_planned_runs || 0}</span>
          </div>
          <div className="environmentChecklistGrid">
            <div>
              <strong>Missing artifacts</strong>
              {missingP0aArtifacts.length ? (
                <ul className="plainList">
                  {missingP0aArtifacts.slice(0, 5).map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <small>All P0a execution artifacts are present.</small>
              )}
            </div>
            <div>
              <strong>Execution blockers</strong>
              {p0aExecutionBlockers.length ? (
                <ul className="plainList">
                  {p0aExecutionBlockers.slice(0, 5).map((blocker) => (
                    <li key={blocker}>{blocker}</li>
                  ))}
                </ul>
              ) : (
                <small>No P0a execution blockers recorded.</small>
              )}
            </div>
            <div>
              <strong>Credential handoff</strong>
              <small>
                {p0aExecutionSummary?.credential_handoff_ready ? "ready" : "blocked"} · missing{" "}
                {p0aExecutionSummary?.credential_handoff_missing_required_count || 0} · redacted{" "}
                {p0aExecutionSummary?.credential_handoff_secret_redacted ? "yes" : "no"}
              </small>
              {missingP0aCredentials.length ? (
                <ul className="plainList">
                  {missingP0aCredentials.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <small>All required P0a credentials are recorded as present.</small>
              )}
            </div>
          </div>
          <div className="handoffBoundary">
            <span>
              Completion {p0aExecutionSummary?.completion_percent || 0}% · design-ready{" "}
              {p0aExecutionSummary?.design_ready_artifact_percent || 0}%
            </span>
            <span>Credential target env file {p0aExecutionSummary?.credential_handoff_target_env_file || "none"}</span>
            <span>
              Real batch phase handoff{" "}
              {p0aExecutionSummary?.real_batch_phase_handoff_ready ? "ready" : "blocked"} · next{" "}
              {p0aExecutionSummary?.real_batch_phase_handoff_next_phase || "none"} · blocked phases{" "}
              {p0aExecutionSummary?.real_batch_phase_handoff_blocked_phase_count || 0}
            </span>
            <span>Real batch planned runs {p0aExecutionSummary?.real_batch_phase_handoff_total_planned_runs || 0}</span>
            <span>
              Verifiers: execution {p0aExecutionSummary?.runbook_execution_verifier_status || "unknown"} · package{" "}
              {p0aExecutionSummary?.package_verifier_status || "unknown"} · status{" "}
              {p0aExecutionSummary?.status_verifier_status || "unknown"}
            </span>
            <span>
              Hard gate{" "}
              {p0aExecutionChecklist?.verification_commands?.find((command) => command.id === "hard_status_gate")
                ?.shell || "python3 scripts/verify_au_p0a_status_report.py --require-design-partner-ready"}
            </span>
            <span>Evidence outputs {p0aExecutionChecklist?.evidence_outputs?.length || 0}</span>
          </div>
          <code>{paths.p0aExecutionChecklist}</code>
        </div>
        <div className="p0bGoogleExecutionChecklist">
          <div className="launchRemediationHeader">
            <strong>P0b Google execution checklist</strong>
            <span>
              {p0bGoogleExecutionChecklist?.execution_checklist_version ||
                "au_p0b_google_execution_checklist_v1"} · hash{" "}
              {shortHash(p0bGoogleExecutionChecklist?.google_execution_checklist_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Ready {p0bGoogleExecutionChecklist?.google_execution_checklist_ready ? "yes" : "no"}</span>
            <span>Google scoring {p0bGoogleExecutionChecklist?.google_main_scoring_allowed ? "allowed" : "blocked"}</span>
            <span>Next action {p0bGoogleExecutionChecklist?.next_action || "run checklist"}</span>
            <span>Planned runs {p0bGoogleExecutionSummary?.planned_runs || 0}</span>
            <span>
              Env-file hygiene {p0bEnvFileHygieneReady ? "ready" : "blocked"} · errors{" "}
              {p0bEnvFileHygieneErrorCount} · warnings {p0bEnvFileHygieneWarningCount}
            </span>
            <span>
              Manual backfill rows {p0bGoogleExecutionSummary?.manual_backfill_handoff_record_count || 0}/
              {p0bGoogleExecutionSummary?.manual_backfill_handoff_expected_record_count || 0}
            </span>
            <span>
              Google phase next {p0bGoogleExecutionSummary?.google_spike_phase_handoff_next_phase || "none"} · blocked{" "}
              {p0bGoogleExecutionSummary?.google_spike_phase_handoff_blocked_phase_count || 0}
            </span>
          </div>
          <div className="environmentChecklistGrid">
            <div>
              <strong>Missing env</strong>
              {missingP0bSmokeEnv.length || missingP0bFullRunEnv.length ? (
                <ul className="plainList">
                  {[...missingP0bSmokeEnv, ...missingP0bFullRunEnv].slice(0, 5).map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <small>Required Google env is present.</small>
              )}
            </div>
            <div>
              <strong>Missing selectors</strong>
              {missingP0bSelectors.length ? (
                <ul className="plainList">
                  {missingP0bSelectors.slice(0, 4).map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <small>Selector groups are present.</small>
              )}
            </div>
            <div>
              <strong>Environment handoff</strong>
              <small>
                {p0bGoogleExecutionSummary?.environment_handoff_ready ? "ready" : "blocked"} · missing{" "}
                {p0bGoogleExecutionSummary?.environment_handoff_missing_required_count || 0} · redacted{" "}
                {p0bGoogleExecutionSummary?.environment_handoff_secret_redacted ? "yes" : "no"}
              </small>
              {missingP0bEnvironmentHandoff.length ? (
                <ul className="plainList">
                  {missingP0bEnvironmentHandoff.slice(0, 6).map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <small>Google smoke/full-run handoff inputs are recorded as present.</small>
              )}
            </div>
            <div>
              <strong>Manual backfill handoff</strong>
              <small>
                {p0bGoogleExecutionSummary?.manual_backfill_handoff_ready ? "ready" : "blocked"} · prompt-city{" "}
                {p0bGoogleExecutionSummary?.manual_backfill_handoff_covered_prompt_city_count || 0}/
                {p0bGoogleExecutionSummary?.manual_backfill_handoff_expected_prompt_city_count || 0} · missing{" "}
                {p0bGoogleExecutionSummary?.manual_backfill_handoff_missing_reason_count || 0}
              </small>
              {missingP0bManualBackfill.length ? (
                <ul className="plainList">
                  {missingP0bManualBackfill.slice(0, 4).map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              ) : (
                <small>Manual JSONL verification is ready.</small>
              )}
            </div>
          </div>
          <div className="handoffBoundary">
            <span>
              Remaining blockers {p0bGoogleExecutionSummary?.remaining_blocker_count || 0} · shown{" "}
              {Math.min(p0bChecklistBlockers.length, 4)}
            </span>
            <span>
              Environment target env file {p0bGoogleExecutionSummary?.environment_handoff_target_env_file || "none"}
            </span>
            <span>
              Manual backfill redacted {p0bGoogleExecutionSummary?.manual_backfill_handoff_content_redacted ? "yes" : "no"} · template{" "}
              {p0bGoogleExecutionSummary?.manual_backfill_handoff_template_path || "none"}
            </span>
            <span>
              Manual verification {p0bGoogleExecutionSummary?.manual_backfill_handoff_verification_path || "none"}
            </span>
            <span>
              Google phase handoff {p0bGoogleExecutionSummary?.google_spike_phase_handoff_ready ? "ready" : "blocked"} · full spike runs{" "}
              {p0bGoogleExecutionSummary?.google_spike_phase_handoff_full_spike_planned_runs || 0}
            </span>
            <span>Google phase order {(p0bGoogleExecutionSummary?.google_spike_phase_order || []).join(" / ") || "none"}</span>
            <span>
              Verifiers: env {p0bGoogleExecutionSummary?.playwright_env_verifier_status || "unknown"} · status{" "}
              {p0bGoogleExecutionSummary?.status_verifier_status || "unknown"} · package{" "}
              {p0bGoogleExecutionSummary?.package_verifier_status || "unknown"}
            </span>
            <span>
              Hard gate{" "}
              {p0bGoogleExecutionChecklist?.verification_commands?.find((command) => command.id === "hard_package_gate")
                ?.shell || "python3 scripts/verify_au_p0b_google_evidence_package.py --require-google-main-scoring-allowed"}
            </span>
            <span>Evidence outputs {p0bGoogleExecutionChecklist?.evidence_outputs?.length || 0}</span>
          </div>
          {p0bChecklistBlockers.length ? (
            <ul className="plainList compactList">
              {p0bChecklistBlockers.slice(0, 4).map((blocker) => (
                <li key={blocker}>{blocker}</li>
              ))}
            </ul>
          ) : null}
          <code>{paths.p0bGoogleExecutionChecklist}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google environment request packet</strong>
            <span>
              {p0bGoogleEnvironmentRequest?.p0b_google_environment_request_packet_version ||
                "au_p0b_google_environment_request_packet_v1"} · p0b_google_environment_request_packet_hash{" "}
              {shortHash(p0bGoogleEnvironmentRequest?.p0b_google_environment_request_packet_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Packet ready {p0bGoogleEnvironmentRequest?.google_environment_request_packet_ready ? "yes" : "no"}
            </span>
            <span>
              Environment handoff {p0bGoogleEnvironmentRequest?.environment_handoff_ready ? "ready" : "blocked"}
            </span>
            <span>
              Google scoring {p0bGoogleEnvironmentRequest?.google_main_scoring_allowed ? "allowed" : "blocked"}
            </span>
            <span>Missing required {p0bGoogleEnvironmentRequestSummary?.missing_required_count || 0}</span>
            <span>Env items {p0bGoogleEnvironmentRequestSummary?.environment_item_count || 0}</span>
            <span>Selector groups {p0bGoogleEnvironmentRequestSummary?.selector_item_count || 0}</span>
            <span>File gates {p0bGoogleEnvironmentRequestSummary?.file_item_count || 0}</span>
            <span>Reuse hints {p0bGoogleEnvironmentRequestSummary?.cross_stage_reuse_hint_count || 0}</span>
            <span>
              DB reuse {p0bGoogleEnvironmentRequestSummary?.database_url_reuse_available ? "available" : "not available"}
            </span>
            <span>Raw secret allowed {p0bGoogleEnvironmentRequestSummary?.raw_secret_values_allowed ? "yes" : "no"}</span>
          </div>
          <div className="handoffBoundary">
            <span>Target env file {p0bGoogleEnvironmentRequestSummary?.target_env_file || "none"}</span>
            <span>
              Missing {p0bGoogleEnvironmentRequestMissing.slice(0, 5).join(", ") || "none"}
            </span>
            <span>
              Browser owner missing{" "}
              {(p0bGoogleEnvironmentRequestSummary?.missing_required_by_owner?.browser_automation_operator || [])
                .slice(0, 4)
                .join(", ") || "none"}
            </span>
            <span>
              Manual owner missing{" "}
              {(p0bGoogleEnvironmentRequestSummary?.missing_required_by_owner?.google_manual_backfill_operator || [])
                .slice(0, 3)
                .join(", ") || "none"}
            </span>
            <span>Next command {p0bGoogleEnvironmentRequestSummary?.next_command || "none"}</span>
            <span>
              Post-update verifier {p0bGoogleEnvironmentRequestSummary?.post_update_verification_command || "none"}
            </span>
            <span>Google next action {p0bGoogleEnvironmentRequestSummary?.google_next_action || "none"}</span>
            <span>
              Source checklist hash{" "}
              {shortHash(
                p0bGoogleEnvironmentRequest?.source_p0b_google_execution_checklist?.google_execution_checklist_hash
              )}
            </span>
            <span>
              P0a env hash{" "}
              {shortHash(p0bGoogleEnvironmentRequest?.source_p0a_env_report?.environment_report_hash)}
            </span>
            <span>
              P0a env verifier {p0bGoogleEnvironmentRequest?.p0a_env_report_verifier?.status || "unknown"} · hash{" "}
              {p0bGoogleEnvironmentRequest?.p0a_env_report_verifier?.hash_valid ? "valid" : "invalid"}
            </span>
            <span>
              {p0bGoogleEnvironmentRequest?.runtime_endpoints?.p0b_google_environment_request ||
                "GET /v1/p0b-google-environment-request/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-environment-request</span>
            <span>
              Ready smoke hard gate:{" "}
              {p0bGoogleEnvironmentRequest?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-ready-smoke")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_playwright_env_report.py docs/runtime_preflight/au-p0b-google-playwright-env-latest.json --require-ready-smoke"}
            </span>
          </div>
          {p0bGoogleCrossStageReuseHints.length ? (
            <div className="dependencyGroupGrid">
              {p0bGoogleCrossStageReuseHints.map((hint) => (
                <div className="dependencyGroup" key={hint.id || `${hint.source_key}-${hint.target_key}`}>
                  <strong>{hint.operator_action || hint.id}</strong>
                  <span>
                    {hint.source_stage || "source"} to {hint.target_stage || "target"} ·{" "}
                    {hint.reuse_available ? "available" : "blocked"}
                  </span>
                  <small>
                    {hint.source_key || "source"} to {hint.target_key || "target"} · missing{" "}
                    {hint.target_missing_id || "none"}
                  </small>
                  <small>
                    len {hint.value_length || 0} · sha {shortHash(hint.sha256_prefix)} · raw copy{" "}
                    {hint.copy_raw_value_required ? "required" : "not stored"}
                  </small>
                </div>
              ))}
            </div>
          ) : null}
          <div className="dependencyGroupGrid">
            {p0bGoogleEnvironmentItems.slice(0, 4).map((item) => (
              <div className="dependencyGroup" key={`env-${item.name}`}>
                <strong>{item.name}</strong>
                <span>
                  {item.owner_hint || "owner"} · {item.present && item.truthy !== false ? "present" : "missing"}
                </span>
                <small>
                  {item.gate || "gate"} · source {item.source || "missing"}
                </small>
                <small>{item.env_file_key || item.name} · redacted {item.secret_redacted ? "yes" : "no"}</small>
              </div>
            ))}
            {p0bGoogleSelectorItems.slice(0, 2).map((item) => (
              <div className="dependencyGroup" key={`selector-${item.group}`}>
                <strong>{item.group}</strong>
                <span>
                  {item.owner_hint || "owner"} · {item.present ? "present" : "missing"}
                </span>
                <small>{(item.candidate_names || []).slice(0, 2).join(" · ") || "selector"}</small>
                <small>redacted {item.secret_redacted ? "yes" : "no"}</small>
              </div>
            ))}
            {p0bGoogleFileItems.slice(0, 3).map((item) => (
              <div className="dependencyGroup" key={`file-${item.name}`}>
                <strong>{item.name}</strong>
                <span>
                  {item.owner_hint || "owner"} · {item.present && (item.is_file || item.is_dir) ? "present" : "missing"}
                </span>
                <small>{item.expected_type || "path"} · source {item.source || "missing"}</small>
                <small>redacted {item.secret_redacted ? "yes" : "no"}</small>
              </div>
            ))}
            {p0bGoogleDependencyItems.slice(0, 2).map((item) => (
              <div className="dependencyGroup" key={`dependency-${item.name}`}>
                <strong>{item.name}</strong>
                <span>
                  {item.owner_hint || "owner"} · {item.present ? "present" : "missing"}
                </span>
                <small>source {item.source || "unknown"}</small>
                <small>redacted {item.secret_redacted ? "yes" : "no"}</small>
              </div>
            ))}
          </div>
          <code>{paths.p0bGoogleEnvironmentRequest}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google environment fulfillment</strong>
            <span>
              {p0bGoogleEnvironmentFulfillment?.p0b_google_environment_fulfillment_version ||
                "au_p0b_google_environment_fulfillment_v1"}{" "}
              · p0b_google_environment_fulfillment_hash{" "}
              {shortHash(p0bGoogleEnvironmentFulfillment?.p0b_google_environment_fulfillment_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Fulfillment ready {p0bGoogleEnvironmentFulfillment?.environment_fulfillment_ready ? "yes" : "no"}
            </span>
            <span>Environment fulfilled {p0bGoogleEnvironmentFulfillment?.environment_fulfilled ? "yes" : "no"}</span>
            <span>Smoke ready {p0bGoogleEnvironmentFulfillment?.ready_for_playwright_smoke ? "yes" : "no"}</span>
            <span>Full run ready {p0bGoogleEnvironmentFulfillment?.ready_for_full_google_run ? "yes" : "no"}</span>
            <span>
              Fulfilled required {p0bGoogleEnvironmentFulfillmentSummary?.fulfilled_required_count || 0}/
              {p0bGoogleEnvironmentFulfillmentSummary?.required_count || 0}
            </span>
            <span>Missing required {p0bGoogleEnvironmentFulfillmentSummary?.missing_required_count || 0}</span>
            <span>Presence mismatches {p0bGoogleEnvironmentFulfillmentSummary?.presence_mismatch_count || 0}</span>
            <span>
              DB reuse{" "}
              {p0bGoogleEnvironmentFulfillmentSummary?.database_url_reuse_available ? "available" : "not available"}
            </span>
          </div>
          <div className="handoffBoundary">
            <span>Missing {p0bGoogleEnvironmentFulfillmentMissing.slice(0, 6).join(", ") || "none"}</span>
            <span>Mismatches {p0bGoogleEnvironmentFulfillmentMismatches.join(", ") || "none"}</span>
            <span>Next action {p0bGoogleEnvironmentFulfillmentSummary?.next_action || "none"}</span>
            <span>Next command {p0bGoogleEnvironmentFulfillmentSummary?.next_command || "none"}</span>
            <span>
              Request hash{" "}
              {shortHash(
                p0bGoogleEnvironmentFulfillment?.source_p0b_google_environment_request
                  ?.p0b_google_environment_request_packet_hash
              )}
            </span>
            <span>
              Env report hash{" "}
              {shortHash(p0bGoogleEnvironmentFulfillment?.source_p0b_google_playwright_env_report?.environment_report_hash)}
            </span>
            <span>
              {p0bGoogleEnvironmentFulfillment?.runtime_endpoints?.p0b_google_environment_fulfillment ||
                "GET /v1/p0b-google-environment-fulfillment/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-environment-fulfillment</span>
            <span>
              Strict gate:{" "}
              {p0bGoogleEnvironmentFulfillmentSummary?.strict_gate_command ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_environment_fulfillment.py docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json --require-fulfilled"}
            </span>
          </div>
          {p0bGoogleEnvironmentFulfillmentItems.length ? (
            <div className="dependencyGroupGrid">
              {p0bGoogleEnvironmentFulfillmentItems.slice(0, 8).map((item) => (
                <div className="dependencyGroup" key={item.key || item.name}>
                  <strong>{item.key || item.name}</strong>
                  <span>
                    {item.owner_hint || "owner"} · {item.fulfilled ? "fulfilled" : "missing"}
                  </span>
                  <small>
                    request {item.requested_present ? "present" : "missing"} · env{" "}
                    {item.environment_present ? "present" : "missing"}
                  </small>
                  <small>
                    source {item.environment_source || "missing"} · hash {shortHash(item.sha256_prefix)}
                  </small>
                  <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
          ) : null}
          <code>{paths.p0bGoogleEnvironmentFulfillment}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google environment clearance</strong>
            <span>
              {p0bGoogleEnvironmentClearance?.p0b_google_environment_clearance_version ||
                "au_p0b_google_environment_clearance_v1"}{" "}
              · p0b_google_environment_clearance_hash{" "}
              {shortHash(p0bGoogleEnvironmentClearance?.p0b_google_environment_clearance_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Clearance packet{" "}
              {p0bGoogleEnvironmentClearance?.environment_clearance_packet_ready ? "ready" : "blocked"}
            </span>
            <span>
              Environment {p0bGoogleEnvironmentClearance?.environment_fulfilled ? "fulfilled" : "blocked"}
            </span>
            <span>
              Clearance ready {p0bGoogleEnvironmentClearance?.environment_clearance_ready ? "yes" : "no"}
            </span>
            <span>
              Next clearance {p0bGoogleEnvironmentClearance?.ready_for_next_clearance_step ? "ready" : "blocked"}
            </span>
            <span>
              Prerequisite blocked {p0bGoogleEnvironmentClearance?.blocked_by_prerequisite_step ? "yes" : "no"}
            </span>
            <span>
              Fulfilled required {p0bGoogleEnvironmentClearanceSummary?.fulfilled_required_count || 0}/
              {p0bGoogleEnvironmentClearanceSummary?.required_count || 0}
            </span>
            <span>Missing required {p0bGoogleEnvironmentClearanceSummary?.missing_required_count || 0}</span>
            <span>Presence mismatches {p0bGoogleEnvironmentClearanceSummary?.presence_mismatch_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>
              Current global step {p0bGoogleEnvironmentClearanceSummary?.current_global_clearance_step_id || "none"}
            </span>
            <span>Target step {p0bGoogleEnvironmentClearanceSummary?.target_clearance_step_id || "none"}</span>
            <span>Prerequisite {p0bGoogleEnvironmentClearanceSummary?.prerequisite_step_id || "none"}</span>
            <span>Next action {p0bGoogleEnvironmentClearanceSummary?.next_action || "none"}</span>
            <span>Next command {p0bGoogleEnvironmentClearanceSummary?.next_command || "none"}</span>
            <span>Missing {p0bGoogleEnvironmentClearanceMissing.slice(0, 6).join(", ") || "none"}</span>
            <span>Mismatches {p0bGoogleEnvironmentClearanceMismatches.join(", ") || "none"}</span>
            <span>
              Raw secret allowed {p0bGoogleEnvironmentClearanceSummary?.raw_secret_values_allowed ? "yes" : "no"}
            </span>
            <span>
              Selector allowed {p0bGoogleEnvironmentClearanceSummary?.selector_values_allowed ? "yes" : "no"}
            </span>
            <span>
              DB URL allowed {p0bGoogleEnvironmentClearanceSummary?.database_urls_allowed ? "yes" : "no"}
            </span>
            <span>
              Request hash {shortHash(p0bGoogleEnvironmentClearance?.source_artifacts?.environment_request?.hash)}
            </span>
            <span>
              Env hash {shortHash(p0bGoogleEnvironmentClearance?.source_artifacts?.playwright_env_report?.hash)}
            </span>
            <span>
              Fulfillment hash{" "}
              {shortHash(p0bGoogleEnvironmentClearance?.source_artifacts?.environment_fulfillment?.hash)}
            </span>
            <span>
              {p0bGoogleEnvironmentClearance?.runtime_endpoints?.p0b_google_environment_clearance ||
                "GET /v1/p0b-google-environment-clearance/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-environment-clearance</span>
            <span>
              Strict gate:{" "}
              {p0bGoogleEnvironmentClearance?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-cleared")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_environment_clearance.py docs/runtime_preflight/au-p0b-google-environment-clearance-latest.json --require-cleared"}
            </span>
          </div>
          {p0bGoogleEnvironmentClearanceItems.length ? (
            <div className="dependencyGroupGrid">
              {p0bGoogleEnvironmentClearanceItems.slice(0, 8).map((item) => (
                <div className="dependencyGroup" key={item.key || item.name}>
                  <strong>{item.key || item.name}</strong>
                  <span>
                    {item.owner_hint || "owner"} · {item.fulfilled ? "fulfilled" : "missing"}
                  </span>
                  <small>
                    request {item.requested_present ? "present" : "missing"} · env{" "}
                    {item.environment_present ? "present" : "missing"}
                  </small>
                  <small>
                    source {item.environment_source || "missing"} · hash {shortHash(item.sha256_prefix)}
                  </small>
                  <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
          ) : null}
          {p0bGoogleEnvironmentClearanceSteps.length ? (
            <div className="handoffBoundary">
              {p0bGoogleEnvironmentClearanceSteps.slice(0, 6).map((step) => (
                <span key={step.id || step.order}>
                  {step.order}. {step.id}: {step.command || "none"}
                </span>
              ))}
            </div>
          ) : null}
          {p0bGoogleEnvironmentClearanceValidation.length ? (
            <div className="handoffBoundary">
              <span>
                Validation sequence{" "}
                {p0bGoogleEnvironmentClearanceValidation.slice(0, 5).join(" -> ") || "none"}
              </span>
            </div>
          ) : null}
          <code>{paths.p0bGoogleEnvironmentClearance}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google manual backfill request packet</strong>
            <span>
              {p0bGoogleManualBackfillRequest?.p0b_google_manual_backfill_request_packet_version ||
                "au_p0b_google_manual_backfill_request_packet_v1"}{" "}
              · p0b_google_manual_backfill_request_packet_hash{" "}
              {shortHash(p0bGoogleManualBackfillRequest?.p0b_google_manual_backfill_request_packet_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Packet ready {p0bGoogleManualBackfillRequest?.manual_backfill_request_packet_ready ? "yes" : "no"}
            </span>
            <span>
              Manual handoff {p0bGoogleManualBackfillRequest?.manual_backfill_handoff_ready ? "ready" : "blocked"}
            </span>
            <span>
              Google scoring {p0bGoogleManualBackfillRequest?.google_main_scoring_allowed ? "allowed" : "blocked"}
            </span>
            <span>
              Records {p0bGoogleManualBackfillRequestSummary?.record_count || 0}/
              {p0bGoogleManualBackfillRequestSummary?.expected_record_count || 0}
            </span>
            <span>
              Prompt-city coverage {p0bGoogleManualBackfillRequestSummary?.covered_prompt_city_count || 0}/
              {p0bGoogleManualBackfillRequestSummary?.expected_prompt_city_count || 0}
            </span>
            <span>Sample size {p0bGoogleManualBackfillRequestSummary?.expected_sample_size || 0}</span>
            <span>Missing reasons {p0bGoogleManualBackfillRequestSummary?.missing_reason_count || 0}</span>
            <span>Content redacted {p0bGoogleManualBackfillRequestSummary?.content_redacted ? "yes" : "no"}</span>
          </div>
          <div className="handoffBoundary">
            <span>Manual JSONL env {p0bGoogleManualBackfillRequestSummary?.manual_jsonl_env_var || "none"}</span>
            <span>Target JSONL {p0bGoogleManualBackfillRequestSummary?.target_jsonl_path || "none"}</span>
            <span>Template {p0bGoogleManualBackfillRequestSummary?.template_path || "none"}</span>
            <span>Template manifest {p0bGoogleManualBackfillRequestSummary?.template_manifest_path || "none"}</span>
            <span>Verification {p0bGoogleManualBackfillRequestSummary?.verification_path || "none"}</span>
            <span>
              Missing {p0bGoogleManualBackfillRequestMissing.slice(0, 4).join(", ") || "none"}
            </span>
            <span>Next command {p0bGoogleManualBackfillRequestSummary?.next_command || "none"}</span>
            <span>
              Post-update verifier {p0bGoogleManualBackfillRequestSummary?.post_update_verification_command || "none"}
            </span>
            <span>Google next action {p0bGoogleManualBackfillRequestSummary?.google_next_action || "none"}</span>
            <span>
              Source checklist hash{" "}
              {shortHash(
                p0bGoogleManualBackfillRequest?.source_p0b_google_execution_checklist?.google_execution_checklist_hash
              )}
            </span>
            <span>
              {p0bGoogleManualBackfillRequest?.runtime_endpoints?.p0b_google_manual_backfill_request ||
                "GET /v1/p0b-google-manual-backfill-request/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-manual-backfill-request</span>
            <span>
              Ready manual hard gate:{" "}
              {p0bGoogleManualBackfillRequest?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-manual-backfill-ready")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_manual_backfill_request_packet.py docs/runtime_preflight/au-p0b-google-manual-backfill-request-latest.json --require-manual-backfill-ready"}
            </span>
          </div>
          <div className="dependencyGroupGrid">
            <div className="dependencyGroup">
              <strong>Required fields</strong>
              <span>{p0bGoogleManualBackfillRequestSummary?.required_field_count || 0} fields</span>
              <small>{p0bGoogleManualBackfillRequiredFields.slice(0, 4).join(" · ") || "none"}</small>
              <small>{p0bGoogleManualBackfillRequiredFields.slice(4).join(" · ") || "all listed"}</small>
            </div>
            <div className="dependencyGroup">
              <strong>Operator requirements</strong>
              <span>{p0bGoogleManualBackfillRequestSummary?.operator_requirement_count || 0} checks</span>
              <small>{p0bGoogleManualBackfillOperatorRequirements.slice(0, 2).join(" · ") || "none"}</small>
              <small>{p0bGoogleManualBackfillOperatorRequirements.slice(2).join(" · ") || "all listed"}</small>
            </div>
            <div className="dependencyGroup">
              <strong>Evidence outputs</strong>
              <span>{p0bGoogleManualBackfillRequestSummary?.evidence_output_count || 0} files</span>
              <small>{p0bGoogleManualBackfillEvidenceOutputs.slice(0, 2).join(" · ") || "none"}</small>
              <small>{p0bGoogleManualBackfillEvidenceOutputs.slice(2).join(" · ") || "all listed"}</small>
            </div>
            <div className="dependencyGroup">
              <strong>Redaction policy</strong>
              <span>
                answer {p0bGoogleManualBackfillRequestSummary?.raw_answer_values_allowed ? "allowed" : "blocked"} ·
                citations {p0bGoogleManualBackfillRequestSummary?.raw_citation_values_allowed ? "allowed" : "blocked"}
              </span>
              <small>
                assets {p0bGoogleManualBackfillRequestSummary?.raw_asset_urls_allowed ? "allowed" : "blocked"} · path
                redacted {p0bGoogleManualBackfillRequestSummary?.manual_jsonl_path_redacted ? "yes" : "no"}
              </small>
              <small>status {p0bGoogleManualBackfillRequestSummary?.manual_backfill_handoff_status || "unknown"}</small>
            </div>
          </div>
          <code>{paths.p0bGoogleManualBackfillRequest}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google manual backfill fulfillment</strong>
            <span>
              {p0bGoogleManualBackfillFulfillment?.p0b_google_manual_backfill_fulfillment_version ||
                "au_p0b_google_manual_backfill_fulfillment_v1"}{" "}
              · p0b_google_manual_backfill_fulfillment_hash{" "}
              {shortHash(p0bGoogleManualBackfillFulfillment?.p0b_google_manual_backfill_fulfillment_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Fulfillment ready{" "}
              {p0bGoogleManualBackfillFulfillment?.manual_backfill_fulfillment_ready ? "yes" : "no"}
            </span>
            <span>
              Manual fulfilled {p0bGoogleManualBackfillFulfillment?.manual_backfill_fulfilled ? "yes" : "no"}
            </span>
            <span>
              Verification{" "}
              {p0bGoogleManualBackfillFulfillmentSummary?.manual_backfill_verification_status || "unknown"}
            </span>
            <span>
              Records {p0bGoogleManualBackfillFulfillmentSummary?.record_count || 0}/
              {p0bGoogleManualBackfillFulfillmentSummary?.expected_record_count || 0}
            </span>
            <span>
              Prompt-city {p0bGoogleManualBackfillFulfillmentSummary?.covered_prompt_city_count || 0}/
              {p0bGoogleManualBackfillFulfillmentSummary?.expected_prompt_city_count || 0}
            </span>
            <span>
              Fulfilled required {p0bGoogleManualBackfillFulfillmentSummary?.fulfilled_required_count || 0}/
              {p0bGoogleManualBackfillFulfillmentSummary?.required_count || 0}
            </span>
            <span>Missing required {p0bGoogleManualBackfillFulfillmentSummary?.missing_required_count || 0}</span>
            <span>Errors {p0bGoogleManualBackfillFulfillmentSummary?.verification_error_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>Missing {p0bGoogleManualBackfillFulfillmentMissing.slice(0, 6).join(", ") || "none"}</span>
            <span>Verification errors {p0bGoogleManualBackfillFulfillmentErrors.slice(0, 4).join(", ") || "none"}</span>
            <span>Next action {p0bGoogleManualBackfillFulfillmentSummary?.next_action || "none"}</span>
            <span>Next command {p0bGoogleManualBackfillFulfillmentSummary?.next_command || "none"}</span>
            <span>Target JSONL {p0bGoogleManualBackfillFulfillmentSummary?.target_jsonl_path || "none"}</span>
            <span>Verification {p0bGoogleManualBackfillFulfillmentSummary?.verification_path || "none"}</span>
            <span>
              Request hash{" "}
              {shortHash(
                p0bGoogleManualBackfillFulfillment?.source_p0b_google_manual_backfill_request
                  ?.p0b_google_manual_backfill_request_packet_hash
              )}
            </span>
            <span>
              Verification hash{" "}
              {shortHash(
                p0bGoogleManualBackfillFulfillment?.source_p0b_google_manual_backfill_verification?.verification_hash
              )}
            </span>
            <span>
              {p0bGoogleManualBackfillFulfillment?.runtime_endpoints?.p0b_google_manual_backfill_fulfillment ||
                "GET /v1/p0b-google-manual-backfill-fulfillment/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-manual-backfill-fulfillment</span>
            <span>
              Strict gate:{" "}
              {p0bGoogleManualBackfillFulfillmentSummary?.strict_gate_command ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_manual_backfill_fulfillment.py docs/runtime_preflight/au-p0b-google-manual-backfill-fulfillment-latest.json --require-fulfilled"}
            </span>
          </div>
          {p0bGoogleManualBackfillFulfillmentItems.length ? (
            <div className="dependencyGroupGrid">
              {p0bGoogleManualBackfillFulfillmentItems.slice(0, 8).map((item) => (
                <div className="dependencyGroup" key={item.key || item.category}>
                  <strong>{item.key || item.category}</strong>
                  <span>
                    {item.owner_hint || "owner"} · {item.fulfilled ? "fulfilled" : "missing"}
                  </span>
                  <small>
                    expected {String(item.expected_value ?? "none")} · actual {String(item.actual_value ?? "none")}
                  </small>
                  <small>
                    request {item.source_request_field || "none"} · verifier{" "}
                    {item.source_verification_field || "none"}
                  </small>
                  <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
          ) : null}
          <code>{paths.p0bGoogleManualBackfillFulfillment}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google manual backfill clearance</strong>
            <span>
              {p0bGoogleManualBackfillClearance?.p0b_google_manual_backfill_clearance_version ||
                "au_p0b_google_manual_backfill_clearance_v1"}{" "}
              · p0b_google_manual_backfill_clearance_hash{" "}
              {shortHash(p0bGoogleManualBackfillClearance?.p0b_google_manual_backfill_clearance_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Clearance packet{" "}
              {p0bGoogleManualBackfillClearance?.manual_backfill_clearance_packet_ready ? "ready" : "blocked"}
            </span>
            <span>
              Manual backfill{" "}
              {p0bGoogleManualBackfillClearance?.manual_backfill_fulfilled ? "fulfilled" : "blocked"}
            </span>
            <span>
              Clearance ready {p0bGoogleManualBackfillClearance?.manual_backfill_clearance_ready ? "yes" : "no"}
            </span>
            <span>
              Next clearance {p0bGoogleManualBackfillClearance?.ready_for_next_clearance_step ? "ready" : "blocked"}
            </span>
            <span>
              Prerequisite blocked {p0bGoogleManualBackfillClearance?.blocked_by_prerequisite_step ? "yes" : "no"}
            </span>
            <span>
              Records {p0bGoogleManualBackfillClearanceSummary?.record_count || 0}/
              {p0bGoogleManualBackfillClearanceSummary?.expected_record_count || 0}
            </span>
            <span>
              Prompt-city {p0bGoogleManualBackfillClearanceSummary?.covered_prompt_city_count || 0}/
              {p0bGoogleManualBackfillClearanceSummary?.expected_prompt_city_count || 0}
            </span>
            <span>Errors {p0bGoogleManualBackfillClearanceSummary?.verification_error_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>
              Current global step {p0bGoogleManualBackfillClearanceSummary?.current_global_clearance_step_id || "none"}
            </span>
            <span>Target step {p0bGoogleManualBackfillClearanceSummary?.target_clearance_step_id || "none"}</span>
            <span>Prerequisite {p0bGoogleManualBackfillClearanceSummary?.prerequisite_step_id || "none"}</span>
            <span>Next action {p0bGoogleManualBackfillClearanceSummary?.next_action || "none"}</span>
            <span>Next command {p0bGoogleManualBackfillClearanceSummary?.next_command || "none"}</span>
            <span>Missing {p0bGoogleManualBackfillClearanceMissing.slice(0, 6).join(", ") || "none"}</span>
            <span>Verification errors {p0bGoogleManualBackfillClearanceErrors.slice(0, 4).join(", ") || "none"}</span>
            <span>
              Raw answer allowed {p0bGoogleManualBackfillClearanceSummary?.raw_answer_values_allowed ? "yes" : "no"}
            </span>
            <span>
              Citation allowed {p0bGoogleManualBackfillClearanceSummary?.raw_citation_values_allowed ? "yes" : "no"}
            </span>
            <span>
              Asset URL allowed {p0bGoogleManualBackfillClearanceSummary?.raw_asset_urls_allowed ? "yes" : "no"}
            </span>
            <span>
              Request hash{" "}
              {shortHash(p0bGoogleManualBackfillClearance?.source_artifacts?.manual_backfill_request?.hash)}
            </span>
            <span>
              Verification hash{" "}
              {shortHash(p0bGoogleManualBackfillClearance?.source_artifacts?.manual_backfill_verification?.hash)}
            </span>
            <span>
              Fulfillment hash{" "}
              {shortHash(p0bGoogleManualBackfillClearance?.source_artifacts?.manual_backfill_fulfillment?.hash)}
            </span>
            <span>
              {p0bGoogleManualBackfillClearance?.runtime_endpoints?.p0b_google_manual_backfill_clearance ||
                "GET /v1/p0b-google-manual-backfill-clearance/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-manual-backfill-clearance</span>
            <span>
              Strict gate:{" "}
              {p0bGoogleManualBackfillClearance?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-cleared")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_manual_backfill_clearance.py docs/runtime_preflight/au-p0b-google-manual-backfill-clearance-latest.json --require-cleared"}
            </span>
          </div>
          {p0bGoogleManualBackfillClearanceItems.length ? (
            <div className="dependencyGroupGrid">
              {p0bGoogleManualBackfillClearanceItems.slice(0, 8).map((item) => (
                <div className="dependencyGroup" key={item.key || item.category}>
                  <strong>{item.key || item.category}</strong>
                  <span>
                    {item.owner_hint || "owner"} · {item.fulfilled ? "fulfilled" : "missing"}
                  </span>
                  <small>
                    expected {String(item.expected_value ?? "none")} · actual {String(item.actual_value ?? "none")}
                  </small>
                  <small>
                    request {item.source_request_field || "none"} · verifier{" "}
                    {item.source_verification_field || "none"}
                  </small>
                  <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
          ) : null}
          {p0bGoogleManualBackfillClearanceSteps.length ? (
            <div className="handoffBoundary">
              {p0bGoogleManualBackfillClearanceSteps.slice(0, 6).map((step) => (
                <span key={step.id || step.order}>
                  {step.order}. {step.id}: {step.command || "none"}
                </span>
              ))}
            </div>
          ) : null}
          {p0bGoogleManualBackfillClearanceValidation.length ? (
            <div className="handoffBoundary">
              <span>
                Validation sequence{" "}
                {p0bGoogleManualBackfillClearanceValidation.slice(0, 5).join(" -> ") || "none"}
              </span>
            </div>
          ) : null}
          <code>{paths.p0bGoogleManualBackfillClearance}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google phase execution request packet</strong>
            <span>
              {p0bGooglePhaseExecutionRequest?.p0b_google_phase_execution_request_packet_version ||
                "au_p0b_google_phase_execution_request_packet_v1"}{" "}
              · p0b_google_phase_execution_request_packet_hash{" "}
              {shortHash(p0bGooglePhaseExecutionRequest?.p0b_google_phase_execution_request_packet_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Packet ready {p0bGooglePhaseExecutionRequest?.phase_execution_request_packet_ready ? "yes" : "no"}
            </span>
            <span>
              Phase handoff {p0bGooglePhaseExecutionRequest?.google_spike_phase_handoff_ready ? "ready" : "blocked"}
            </span>
            <span>
              Google scoring {p0bGooglePhaseExecutionRequest?.google_main_scoring_allowed ? "allowed" : "blocked"}
            </span>
            <span>Phases {p0bGooglePhaseExecutionRequestSummary?.phase_count || 0}</span>
            <span>Ready {p0bGooglePhaseExecutionRequestSummary?.ready_phase_count || 0}</span>
            <span>Blocked {p0bGooglePhaseExecutionRequestSummary?.blocked_phase_count || 0}</span>
            <span>Full spike runs {p0bGooglePhaseExecutionRequestSummary?.full_spike_planned_runs || 0}</span>
            <span>Manual records {p0bGooglePhaseExecutionRequestSummary?.manual_expected_record_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>Next phase {p0bGooglePhaseExecutionRequestSummary?.next_phase || "none"}</span>
            <span>Next command {p0bGooglePhaseExecutionRequestSummary?.next_command || "none"}</span>
            <span>
              Post-update verifier {p0bGooglePhaseExecutionRequestSummary?.post_update_verification_command || "none"}
            </span>
            <span>
              Blocking {p0bGooglePhaseExecutionBlockingReasons.slice(0, 4).join(", ") || "none"}
            </span>
            <span>
              Source checklist hash{" "}
              {shortHash(
                p0bGooglePhaseExecutionRequest?.source_p0b_google_execution_checklist
                  ?.google_execution_checklist_hash
              )}
            </span>
            <span>
              {p0bGooglePhaseExecutionRequest?.runtime_endpoints?.p0b_google_phase_execution_request ||
                "GET /v1/p0b-google-phase-execution-request/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-phase-execution-request</span>
            <span>
              Strict phase gate:{" "}
              {p0bGooglePhaseExecutionRequest?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-google-phases-ready")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_phase_execution_request_packet.py docs/runtime_preflight/au-p0b-google-phase-execution-request-latest.json --require-google-phases-ready"}
            </span>
            <span>
              Strict scoring gate:{" "}
              {p0bGooglePhaseExecutionRequest?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-google-main-scoring-ready")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_execution_checklist.py docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json --require-google-main-scoring-ready"}
            </span>
          </div>
          <div className="dependencyGroupGrid">
            {p0bGooglePhaseExecutionPhases.map((phase) => (
              <div className="dependencyGroup" key={`p0b-google-phase-${phase.id}`}>
                <strong>{phase.title || phase.id}</strong>
                <span>
                  {phase.id} · {phase.ready ? "ready" : "blocked"} · can start {phase.can_start ? "yes" : "no"}
                </span>
                <small>
                  runs {phase.planned_runs || 0} · commands {(phase.command_ids || []).join(" · ") || "none"}
                </small>
                <small>{(phase.blocking_reasons || []).slice(0, 2).join(" · ") || "no blockers"}</small>
              </div>
            ))}
            <div className="dependencyGroup">
              <strong>Evidence outputs</strong>
              <span>{p0bGooglePhaseExecutionRequestSummary?.evidence_output_count || 0} files</span>
              <small>{p0bGooglePhaseExecutionEvidenceOutputs.slice(0, 2).join(" · ") || "none"}</small>
              <small>{p0bGooglePhaseExecutionEvidenceOutputs.slice(2, 5).join(" · ") || "all listed"}</small>
            </div>
            <div className="dependencyGroup">
              <strong>Redaction policy</strong>
              <span>
                secret {p0bGooglePhaseExecutionRequestSummary?.raw_secret_values_allowed ? "allowed" : "blocked"} ·
                answer {p0bGooglePhaseExecutionRequestSummary?.raw_answer_values_allowed ? "allowed" : "blocked"}
              </span>
              <small>
                citations {p0bGooglePhaseExecutionRequestSummary?.raw_citation_values_allowed ? "allowed" : "blocked"} ·
                assets {p0bGooglePhaseExecutionRequestSummary?.raw_asset_urls_allowed ? "allowed" : "blocked"}
              </small>
              <small>
                refs only{" "}
                {p0bGooglePhaseExecutionRequestSummary?.phase_entries_reference_command_ids_and_artifact_paths_only
                  ? "yes"
                  : "no"}
              </small>
            </div>
          </div>
          <code>{paths.p0bGooglePhaseExecutionRequest}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google phase execution fulfillment</strong>
            <span>
              {p0bGooglePhaseExecutionFulfillment?.p0b_google_phase_execution_fulfillment_version ||
                "au_p0b_google_phase_execution_fulfillment_v1"}{" "}
              · p0b_google_phase_execution_fulfillment_hash{" "}
              {shortHash(p0bGooglePhaseExecutionFulfillment?.p0b_google_phase_execution_fulfillment_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Fulfillment ready{" "}
              {p0bGooglePhaseExecutionFulfillment?.phase_execution_fulfillment_ready ? "yes" : "no"}
            </span>
            <span>
              Phase fulfilled {p0bGooglePhaseExecutionFulfillment?.phase_execution_fulfilled ? "yes" : "no"}
            </span>
            <span>
              Google scoring{" "}
              {p0bGooglePhaseExecutionFulfillment?.google_main_scoring_allowed ? "allowed" : "blocked"}
            </span>
            <span>Ready {p0bGooglePhaseExecutionFulfillmentSummary?.ready_phase_count || 0}</span>
            <span>Blocked {p0bGooglePhaseExecutionFulfillmentSummary?.blocked_phase_count || 0}</span>
            <span>Missing {p0bGooglePhaseExecutionFulfillmentSummary?.missing_required_count || 0}</span>
            <span>Full spike runs {p0bGooglePhaseExecutionFulfillmentSummary?.full_spike_planned_runs || 0}</span>
            <span>Manual records {p0bGooglePhaseExecutionFulfillmentSummary?.manual_expected_record_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>Next phase {p0bGooglePhaseExecutionFulfillmentSummary?.next_phase || "none"}</span>
            <span>Next action {p0bGooglePhaseExecutionFulfillmentSummary?.next_action || "none"}</span>
            <span>Next command {p0bGooglePhaseExecutionFulfillmentSummary?.next_command || "none"}</span>
            <span>
              Missing {p0bGooglePhaseExecutionFulfillmentMissing.slice(0, 4).join(", ") || "none"}
            </span>
            <span>
              Request hash{" "}
              {shortHash(
                p0bGooglePhaseExecutionFulfillment?.source_p0b_google_phase_execution_request
                  ?.p0b_google_phase_execution_request_packet_hash
              )}
            </span>
            <span>
              Checklist hash{" "}
              {shortHash(
                p0bGooglePhaseExecutionFulfillment?.source_p0b_google_execution_checklist
                  ?.google_execution_checklist_hash
              )}
            </span>
            <span>
              {p0bGooglePhaseExecutionFulfillment?.runtime_endpoints?.p0b_google_phase_execution_fulfillment ||
                "GET /v1/p0b-google-phase-execution-fulfillment/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-phase-execution-fulfillment</span>
            <span>
              Strict fulfillment gate:{" "}
              {p0bGooglePhaseExecutionFulfillment?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-fulfilled")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_phase_execution_fulfillment.py docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json --require-fulfilled"}
            </span>
          </div>
          <div className="dependencyGroupGrid">
            {p0bGooglePhaseExecutionFulfillmentItems.map((item) => (
              <div className="dependencyGroup" key={`p0b-google-phase-fulfillment-${item.key || item.phase_id}`}>
                <strong>{item.title || item.phase_id || item.key}</strong>
                <span>
                  {item.phase_id || item.key} · {item.fulfilled ? "fulfilled" : "blocked"}
                </span>
                <small>
                  request {item.request_ready ? "ready" : "blocked"} · checklist{" "}
                  {item.checklist_ready ? "ready" : "blocked"} · runs {item.planned_runs || 0}
                </small>
                <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
              </div>
            ))}
            <div className="dependencyGroup">
              <strong>Fulfillment blockers</strong>
              <span>{p0bGooglePhaseExecutionFulfillmentSummary?.blocking_reason_count || 0} reasons</span>
              <small>{p0bGooglePhaseExecutionFulfillmentBlockers.slice(0, 2).join(" · ") || "none"}</small>
              <small>{p0bGooglePhaseExecutionFulfillmentBlockers.slice(2, 5).join(" · ") || "all listed"}</small>
            </div>
            <div className="dependencyGroup">
              <strong>Redaction policy</strong>
              <span>
                secret {p0bGooglePhaseExecutionFulfillmentSummary?.raw_secret_values_allowed ? "allowed" : "blocked"} ·
                answer {p0bGooglePhaseExecutionFulfillmentSummary?.raw_answer_values_allowed ? "allowed" : "blocked"}
              </span>
              <small>
                citations {p0bGooglePhaseExecutionFulfillmentSummary?.raw_citation_values_allowed ? "allowed" : "blocked"} ·
                assets {p0bGooglePhaseExecutionFulfillmentSummary?.raw_asset_urls_allowed ? "allowed" : "blocked"}
              </small>
              <small>
                refs only{" "}
                {p0bGooglePhaseExecutionFulfillmentSummary?.phase_entries_reference_command_ids_and_artifact_paths_only
                  ? "yes"
                  : "no"}
              </small>
            </div>
          </div>
          <code>{paths.p0bGooglePhaseExecutionFulfillment}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0b Google phase execution clearance</strong>
            <span>
              {p0bGooglePhaseExecutionClearance?.p0b_google_phase_execution_clearance_version ||
                "au_p0b_google_phase_execution_clearance_v1"}{" "}
              · p0b_google_phase_execution_clearance_hash{" "}
              {shortHash(p0bGooglePhaseExecutionClearance?.p0b_google_phase_execution_clearance_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Clearance packet{" "}
              {p0bGooglePhaseExecutionClearance?.phase_execution_clearance_packet_ready ? "ready" : "blocked"}
            </span>
            <span>
              Phase execution{" "}
              {p0bGooglePhaseExecutionClearance?.phase_execution_fulfilled ? "fulfilled" : "blocked"}
            </span>
            <span>
              Clearance ready {p0bGooglePhaseExecutionClearance?.phase_execution_clearance_ready ? "yes" : "no"}
            </span>
            <span>
              Next clearance {p0bGooglePhaseExecutionClearance?.ready_for_next_clearance_step ? "ready" : "blocked"}
            </span>
            <span>
              Prerequisite blocked {p0bGooglePhaseExecutionClearance?.blocked_by_prerequisite_step ? "yes" : "no"}
            </span>
            <span>Ready {p0bGooglePhaseExecutionClearanceSummary?.ready_phase_count || 0}</span>
            <span>Blocked {p0bGooglePhaseExecutionClearanceSummary?.blocked_phase_count || 0}</span>
            <span>Missing {p0bGooglePhaseExecutionClearanceSummary?.missing_required_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>
              Current global step {p0bGooglePhaseExecutionClearanceSummary?.current_global_clearance_step_id || "none"}
            </span>
            <span>Target step {p0bGooglePhaseExecutionClearanceSummary?.target_clearance_step_id || "none"}</span>
            <span>Prerequisite {p0bGooglePhaseExecutionClearanceSummary?.prerequisite_step_id || "none"}</span>
            <span>Next phase {p0bGooglePhaseExecutionClearanceSummary?.next_phase || "none"}</span>
            <span>Next action {p0bGooglePhaseExecutionClearanceSummary?.next_action || "none"}</span>
            <span>Next command {p0bGooglePhaseExecutionClearanceSummary?.next_command || "none"}</span>
            <span>
              Missing {p0bGooglePhaseExecutionClearanceMissing.slice(0, 6).join(", ") || "none"}
            </span>
            <span>
              Blocking {p0bGooglePhaseExecutionClearanceBlockers.slice(0, 4).join(", ") || "none"}
            </span>
            <span>
              Raw provider response{" "}
              {p0bGooglePhaseExecutionClearanceSummary?.raw_provider_response_allowed ? "allowed" : "blocked"}
            </span>
            <span>
              Raw answer {p0bGooglePhaseExecutionClearanceSummary?.raw_answer_values_allowed ? "allowed" : "blocked"}
            </span>
            <span>
              Request hash{" "}
              {shortHash(p0bGooglePhaseExecutionClearance?.source_artifacts?.phase_execution_request?.hash)}
            </span>
            <span>
              Fulfillment hash{" "}
              {shortHash(p0bGooglePhaseExecutionClearance?.source_artifacts?.phase_execution_fulfillment?.hash)}
            </span>
            <span>
              {p0bGooglePhaseExecutionClearance?.runtime_endpoints?.p0b_google_phase_execution_clearance ||
                "GET /v1/p0b-google-phase-execution-clearance/au"}
            </span>
            <span>Hard gate: make verify-au-p0b-google-phase-execution-clearance</span>
            <span>
              Strict clearance gate:{" "}
              {p0bGooglePhaseExecutionClearance?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-cleared")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_phase_execution_clearance.py docs/runtime_preflight/au-p0b-google-phase-execution-clearance-latest.json --require-cleared"}
            </span>
          </div>
          {p0bGooglePhaseExecutionClearanceItems.length ? (
            <div className="dependencyGroupGrid">
              {p0bGooglePhaseExecutionClearanceItems.map((item) => (
                <div className="dependencyGroup" key={`p0b-google-phase-clearance-${item.key || item.phase_id}`}>
                  <strong>{item.title || item.phase_id || item.key}</strong>
                  <span>
                    {item.phase_id || item.key} · {item.fulfilled ? "fulfilled" : "blocked"}
                  </span>
                  <small>
                    request {item.request_ready ? "ready" : "blocked"} · checklist{" "}
                    {item.checklist_ready ? "ready" : "blocked"} · runs {item.planned_runs || 0}
                  </small>
                  <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
          ) : null}
          {p0bGooglePhaseExecutionClearanceSteps.length ? (
            <div className="handoffBoundary">
              {p0bGooglePhaseExecutionClearanceSteps.slice(0, 6).map((step) => (
                <span key={step.id || step.order}>
                  {step.order}. {step.id}: {step.command || "none"}
                </span>
              ))}
            </div>
          ) : null}
          {p0bGooglePhaseExecutionClearanceValidation.length ? (
            <div className="handoffBoundary">
              <span>
                Validation sequence{" "}
                {p0bGooglePhaseExecutionClearanceValidation.slice(0, 5).join(" -> ") || "none"}
              </span>
            </div>
          ) : null}
          <code>{paths.p0bGooglePhaseExecutionClearance}</code>
        </div>
        <div className="broaderPlatformRegistry">
          <div className="launchRemediationHeader">
            <strong>Broader platform registry</strong>
            <span>
              {broaderPlatformRegistry?.registry_version || "au_broader_platform_registry_v1"} · hash{" "}
              {shortHash(broaderPlatformRegistry?.broader_platform_registry_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Ready {broaderPlatformRegistry?.broader_platform_registry_ready ? "yes" : "no"}</span>
            <span>Candidates {broaderPlatformSummary?.candidate_count || 0}</span>
            <span>Registered {broaderPlatformSummary?.registered_candidate_count || 0}</span>
            <span>Enabled {broaderPlatformSummary?.enabled_candidate_count || 0}</span>
          </div>
          <div className="platformRegistryGrid">
            {broaderPlatformCandidates.slice(0, 6).map((candidate) => (
              <div className="platformCandidate" key={candidate.id}>
                <div>
                  <strong>{candidate.platform}</strong>
                  <span>
                    {candidate.surface} · {candidate.build_stage} · {candidate.platform_role}
                  </span>
                </div>
                <small>
                  {candidate.adapter_status || "status"} · {candidate.enabled ? "enabled" : "disabled"} · weight{" "}
                  {num(candidate.default_weight || 0)}
                </small>
                <code>{candidate.next_work_item || candidate.id}</code>
              </div>
            ))}
          </div>
          <div className="handoffBoundary">
            <span>P0a enabled {broaderPlatformSummary?.p0a_enabled_platform_surfaces?.join(", ") || "none"}</span>
            <span>P0b isolated {broaderPlatformSummary?.p0b_platform_surfaces?.join(", ") || "none"}</span>
            <span>Sequence {broaderPlatformSequence.slice(0, 3).join(" -> ") || "not planned"}</span>
          </div>
          <code>{paths.broaderPlatformRegistry}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>Handoff dossier</strong>
            <span>
              {handoffDossier?.handoff_dossier_version || "au_handoff_dossier_v1"} · hash{" "}
              {shortHash(handoffDossier?.handoff_dossier_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Dossier ready {handoffDossier?.handoff_dossier_ready ? "yes" : "no"}</span>
            <span>Customer handoff {handoffDossier?.ready_for_customer_report_handoff ? "ready" : "blocked"}</span>
            <span>Posture {handoffSummary?.handoff_posture || "unknown"}</span>
            <span>Markdown hash {shortHash(handoffDossier?.markdown_report?.content_sha256)}</span>
            <span>
              Customer readiness {handoffReadinessAudit?.customer_report_handoff_readiness_percent ?? 0}%
            </span>
            <span>Auditability {handoffReadinessAudit?.structural_auditability_percent ?? 0}%</span>
          </div>
          <div className="handoffBoundary">
            <span>Readiness audit {handoffReadinessAudit?.audit_version || "au_customer_handoff_readiness_audit_v1"}</span>
            <span>
              Customer gates {handoffReadinessAudit?.customer_ready_gate_count || 0}/
              {handoffReadinessAudit?.customer_total_gate_count || 0} · blocked{" "}
              {handoffReadinessAudit?.blocked_customer_gate_count || 0}
            </span>
            <span>
              Blocked gate ids{" "}
              {handoffReadinessAudit?.blocked_customer_gate_ids?.slice(0, 4).join(", ") || "none"}
            </span>
            <span>Readiness statement {handoffReadinessAudit?.readiness_statement || "unknown"}</span>
            <span>Next work item {handoffSummary?.next_work_item_id || handoffNextWorkItem?.id || "none"}</span>
            <span>
              Blockers {handoffSummary?.remaining_blocker_count || 0} · work items{" "}
              {handoffSummary?.work_item_count || 0} · unmapped {handoffSummary?.unmapped_blocker_count || 0}
            </span>
            <span>
              P0a env-file hygiene {handoffSummary?.p0a_env_file_hygiene_ready ? "ready" : "blocked"} · errors{" "}
              {handoffSummary?.p0a_env_file_hygiene_error_count || 0} · warnings{" "}
              {handoffSummary?.p0a_env_file_hygiene_warning_count || 0}
            </span>
            <span>
              P0a credential handoff {handoffSummary?.p0a_credential_handoff_ready ? "ready" : "blocked"} · missing{" "}
              {handoffSummary?.p0a_credential_handoff_missing_required_count || 0} · redacted{" "}
              {handoffSummary?.p0a_credential_handoff_secret_redacted ? "yes" : "no"}
            </span>
            <span>
              P0a real batch phase handoff{" "}
              {handoffSummary?.p0a_real_batch_phase_handoff_ready ? "ready" : "blocked"} · next{" "}
              {handoffSummary?.p0a_real_batch_phase_handoff_next_phase || "none"} · blocked phases{" "}
              {handoffSummary?.p0a_real_batch_phase_handoff_blocked_phase_count || 0}
            </span>
            <span>
              P0b env-file hygiene{" "}
              {handoffSummary?.p0b_google_env_file_hygiene_ready ? "ready" : "blocked"} · errors{" "}
              {handoffSummary?.p0b_google_env_file_hygiene_error_count || 0} · warnings{" "}
              {handoffSummary?.p0b_google_env_file_hygiene_warning_count || 0}
            </span>
            <span>
              P0b environment handoff{" "}
              {handoffSummary?.p0b_google_environment_handoff_ready ? "ready" : "blocked"} · missing{" "}
              {handoffSummary?.p0b_google_environment_handoff_missing_required_count || 0} · redacted{" "}
              {handoffSummary?.p0b_google_environment_handoff_secret_redacted ? "yes" : "no"}
            </span>
            <span>
              P0b manual backfill handoff{" "}
              {handoffSummary?.p0b_google_manual_backfill_handoff_ready ? "ready" : "blocked"} · rows{" "}
              {handoffSummary?.p0b_google_manual_backfill_handoff_record_count || 0}/
              {handoffSummary?.p0b_google_manual_backfill_handoff_expected_record_count || 0} · missing{" "}
              {handoffSummary?.p0b_google_manual_backfill_handoff_missing_reason_count || 0} · redacted{" "}
              {handoffSummary?.p0b_google_manual_backfill_handoff_content_redacted ? "yes" : "no"}
            </span>
            <span>
              P0b Google phase handoff{" "}
              {handoffSummary?.p0b_google_spike_phase_handoff_ready ? "ready" : "blocked"} · next{" "}
              {handoffSummary?.p0b_google_spike_phase_handoff_next_phase || "none"} · blocked phases{" "}
              {handoffSummary?.p0b_google_spike_phase_handoff_blocked_phase_count || 0} · full spike runs{" "}
              {handoffSummary?.p0b_google_spike_phase_handoff_full_spike_planned_runs || 0}
            </span>
            <span>Hard gate: scripts/verify_au_handoff_dossier.py --require-customer-ready</span>
            <span>{handoffDossier?.runtime_endpoints?.launch_remediation_plan || "GET /v1/launch-remediation-plan/au"}</span>
            <span>
              Lifecycle replay{" "}
              {handoffDossier?.runtime_endpoints?.project_lifecycle_events ||
                "GET /v1/projects/runtime/lifecycle-events?project_id={project_id}"}
            </span>
            <span>
              Lifecycle CSV{" "}
              {handoffDossier?.runtime_endpoints?.project_lifecycle_events_export ||
                "GET /v1/projects/runtime/lifecycle-events/export.csv?project_id={project_id}"}
            </span>
            <span>
              Audit replay{" "}
              {handoffDossier?.runtime_endpoints?.runtime_audit_events ||
                "GET /v1/audit-events/runtime?project_id={project_id}"}
            </span>
            <span>
              Audit CSV{" "}
              {handoffDossier?.runtime_endpoints?.runtime_audit_events_export ||
                "GET /v1/audit-events/runtime/export.csv?project_id={project_id}"}
            </span>
            <span>
              External dependency replay{" "}
              {handoffDossier?.runtime_endpoints?.external_dependency_handoff ||
                "GET /v1/external-dependency-handoff/au"}
            </span>
            <span>
              External clearance dry-run{" "}
              {handoffDossier?.runtime_endpoints?.external_dependency_clearance ||
                "GET /v1/external-dependency-clearance/au"}
            </span>
          </div>
          <code>{paths.handoffDossier}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>AU delivery progress</strong>
            <span>
              {deliveryProgress?.delivery_progress_version || "au_delivery_progress_v1"} · delivery_progress_hash{" "}
              {shortHash(deliveryProgress?.delivery_progress_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Engineering progress {deliveryProgressSummary?.engineering_progress_percent ?? 0}%</span>
            <span>
              Customer readiness {deliveryProgressSummary?.customer_report_handoff_readiness_percent ?? 0}%
            </span>
            <span>Auditability {deliveryProgressSummary?.structural_auditability_percent ?? 0}%</span>
            <span>Progress ready {deliveryProgress?.delivery_progress_ready ? "yes" : "no"}</span>
            <span>
              Customer report {deliveryProgress?.ready_for_customer_report_handoff ? "ready" : "blocked"}
            </span>
            <span>Status {deliveryProgress?.status || "unknown"}</span>
          </div>
          <div className="handoffBoundary">
            <span>
              Progress gates {deliveryProgressSummary?.ready_progress_gate_count || 0}/
              {deliveryProgressSummary?.total_progress_gate_count || 0} · blocked{" "}
              {deliveryProgressSummary?.blocked_progress_gate_count || 0}
            </span>
            <span>
              Customer gates blocked {deliveryProgressSummary?.blocked_customer_gate_count || 0}
            </span>
            <span>Remaining blockers {deliveryProgressSummary?.remaining_blocker_count || 0}</span>
            <span>External blockers {deliveryProgressSummary?.external_dependency_blocker_count || 0}</span>
            <span>Next work item {deliveryProgressSummary?.next_work_item_id || "none"}</span>
            <span>Next stage {deliveryProgressSummary?.next_work_item_stage || "none"}</span>
            <span>Next command {deliveryProgressSummary?.next_command || "none"}</span>
            <span>Clearance step {deliveryProgressSummary?.current_clearance_step_id || "none"}</span>
            <span>Would execute {deliveryProgressSummary?.would_execute_step_count || 0}</span>
            <span>Handoff posture {deliveryProgressSummary?.handoff_posture || "unknown"}</span>
            <span>
              Blocked progress gates {blockedDeliveryProgressGateIds.slice(0, 6).join(", ") || "none"}
            </span>
            <span>Launch hash {shortHash(deliveryProgressSummary?.launch_status_hash)}</span>
            <span>Readiness hash {shortHash(deliveryProgressSummary?.customer_handoff_readiness_hash)}</span>
            <span>Next item hash {shortHash(deliveryProgressSummary?.next_work_item_packet_hash)}</span>
            <span>
              {deliveryProgress?.runtime_endpoints?.delivery_progress || "GET /v1/delivery-progress/au"}
            </span>
            <span>Hard gate: make verify-au-delivery-progress</span>
          </div>
          {topDeliveryProgressGates.length ? (
            <div className="dependencyGroupGrid">
              {topDeliveryProgressGates.map((gate) => (
                <div className="dependencyGroup" key={gate.id || gate.label}>
                  <strong>{gate.label || gate.id}</strong>
                  <span>
                    {gate.ready ? "ready" : "blocked"} · {gate.source || "source"}
                  </span>
                  <small>{gate.evidence_ref || "no evidence ref"}</small>
                  <small>{(gate.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
          ) : null}
          <code>{paths.deliveryProgress}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>Customer handoff clearance</strong>
            <span>
              {customerHandoffClearance?.customer_handoff_clearance_version ||
                "au_customer_handoff_clearance_v1"} · customer_handoff_clearance_hash{" "}
              {shortHash(customerHandoffClearance?.customer_handoff_clearance_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Packet ready {customerHandoffClearance?.customer_handoff_clearance_packet_ready ? "yes" : "no"}
            </span>
            <span>
              Customer handoff {customerHandoffClearance?.customer_handoff_ready ? "ready" : "blocked"}
            </span>
            <span>
              Clearance {customerHandoffClearance?.customer_handoff_clearance_ready ? "ready" : "blocked"}
            </span>
            <span>
              Report export handoff {customerHandoffClearance?.ready_for_report_export_handoff ? "ready" : "blocked"}
            </span>
            <span>
              Prerequisites {customerHandoffClearanceSummary?.prerequisite_steps_ready ? "ready" : "blocked"}
            </span>
            <span>Status {customerHandoffClearance?.status || "unknown"}</span>
          </div>
          <div className="handoffBoundary">
            <span>
              Customer gates {customerHandoffClearanceSummary?.fulfilled_required_count || 0}/
              {customerHandoffClearanceSummary?.required_count || 0} · blocked{" "}
              {customerHandoffClearanceSummary?.missing_required_count || 0}
            </span>
            <span>Engineering progress {customerHandoffClearanceSummary?.engineering_progress_percent ?? 0}%</span>
            <span>
              Customer readiness{" "}
              {customerHandoffClearanceSummary?.customer_report_handoff_readiness_percent ?? 0}%
            </span>
            <span>Clearance step {customerHandoffClearanceSummary?.target_clearance_step_id || "none"}</span>
            <span>Current global step {customerHandoffClearanceSummary?.current_global_clearance_step_id || "none"}</span>
            <span>Next action {customerHandoffClearanceSummary?.next_action || "none"}</span>
            <span>Next command {customerHandoffClearanceSummary?.next_command || "none"}</span>
            <span>
              Missing gates {customerHandoffClearanceSummary?.missing_required?.slice(0, 5).join(", ") || "none"}
            </span>
            <span>Handoff hash {shortHash(customerHandoffClearanceSummary?.handoff_dossier_hash)}</span>
            <span>Readiness hash {shortHash(customerHandoffClearanceSummary?.customer_handoff_readiness_hash)}</span>
            <span>Progress hash {shortHash(customerHandoffClearanceSummary?.delivery_progress_hash)}</span>
            <span>External hash {shortHash(customerHandoffClearanceSummary?.external_dependency_handoff_hash)}</span>
            <span>
              {customerHandoffClearance?.runtime_endpoints?.customer_handoff_clearance ||
                "GET /v1/customer-handoff-clearance/au"}
            </span>
            <span>Hard gate: make verify-au-customer-handoff-clearance</span>
            <span>
              Hard gate:{" "}
              {customerHandoffClearance?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-cleared")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_clearance.py docs/runtime_preflight/au-customer-handoff-clearance-latest.json --require-cleared"}
            </span>
          </div>
          {topCustomerHandoffClearanceItems.length ? (
            <div className="dependencyGroupGrid">
              {topCustomerHandoffClearanceItems.map((item) => (
                <div className="dependencyGroup" key={item.key || item.gate_id}>
                  <strong>{item.title || item.gate_id}</strong>
                  <span>
                    {item.fulfilled ? "ready" : "blocked"} · {item.stage || "handoff"}
                  </span>
                  <small>{item.evidence_ref || "no evidence ref"}</small>
                  <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
          ) : null}
          {topCustomerHandoffClearanceSteps.length ? (
            <div className="handoffBoundary">
              {topCustomerHandoffClearanceSteps.map((step) => (
                <span key={step.id || step.command}>
                  {step.id}: {step.command}
                </span>
              ))}
              <span>Validation commands {customerHandoffClearanceValidation.length}</span>
            </div>
          ) : null}
          <code>{paths.customerHandoffClearance}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>Customer handoff readiness</strong>
            <span>
              {customerHandoffReadiness?.customer_handoff_readiness_version ||
                "au_customer_handoff_readiness_v1"} · customer_handoff_readiness_hash{" "}
              {shortHash(customerHandoffReadiness?.customer_handoff_readiness_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              customer_report_handoff_readiness_percent{" "}
              {customerHandoffReadinessSummary?.customer_report_handoff_readiness_percent ?? 0}%
            </span>
            <span>
              structural_auditability_percent{" "}
              {customerHandoffReadinessSummary?.structural_auditability_percent ?? 0}%
            </span>
            <span>
              Audit ready {customerHandoffReadiness?.readiness_audit_ready ? "yes" : "no"}
            </span>
            <span>
              Customer report {customerHandoffReadiness?.ready_for_customer_report_handoff ? "ready" : "blocked"}
            </span>
          </div>
          <div className="handoffBoundary">
            <span>
              Customer gates {customerHandoffReadinessSummary?.customer_ready_gate_count || 0}/
              {customerHandoffReadinessSummary?.customer_total_gate_count || 0} · blocked{" "}
              {customerHandoffReadinessSummary?.blocked_customer_gate_count || 0}
            </span>
            <span>
              Structural gates {customerHandoffReadinessSummary?.structural_ready_gate_count || 0}/
              {customerHandoffReadinessSummary?.structural_total_gate_count || 0}
            </span>
            <span>
              Blocked gate ids {customerHandoffReadinessBlockedGateIds.slice(0, 5).join(", ") || "none"}
            </span>
            <span>Next work item {customerHandoffReadinessSummary?.next_work_item_id || "none"}</span>
            <span>
              Source dossier hash {shortHash(customerHandoffReadiness?.source_handoff_dossier?.handoff_dossier_hash)}
            </span>
            <span>
              {customerHandoffReadiness?.runtime_endpoints?.customer_handoff_readiness ||
                "GET /v1/customer-handoff-readiness/au"}
            </span>
            <span>Hard gate: make verify-au-customer-handoff-readiness</span>
            <span>
              Hard gate:{" "}
              {customerHandoffReadiness?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-customer-ready")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py docs/runtime_preflight/au-customer-handoff-readiness-latest.json --require-customer-ready"}
            </span>
          </div>
          <code>{paths.customerHandoffReadiness}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0a credential request packet</strong>
            <span>
              {p0aCredentialRequest?.p0a_credential_request_packet_version ||
                "au_p0a_credential_request_packet_v1"} · p0a_credential_request_packet_hash{" "}
              {shortHash(p0aCredentialRequest?.p0a_credential_request_packet_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Packet ready {p0aCredentialRequest?.credential_request_packet_ready ? "yes" : "no"}</span>
            <span>Credential handoff {p0aCredentialRequest?.credential_handoff_ready ? "ready" : "blocked"}</span>
            <span>Design partner {p0aCredentialRequest?.ready_for_design_partner ? "ready" : "blocked"}</span>
            <span>Missing required {p0aCredentialRequestSummary?.missing_required_count || 0}</span>
            <span>Requested items {p0aCredentialRequestSummary?.credential_item_count || 0}</span>
            <span>Raw secret allowed {p0aCredentialRequestSummary?.raw_secret_values_allowed ? "yes" : "no"}</span>
          </div>
          <div className="handoffBoundary">
            <span>Target env file {p0aCredentialRequestSummary?.target_env_file || "none"}</span>
            <span>
              Missing {p0aCredentialRequestMissing.join(", ") || "none"}
            </span>
            <span>
              Provider owner missing{" "}
              {(p0aCredentialRequestSummary?.missing_required_by_owner?.provider_admin || []).join(", ") || "none"}
            </span>
            <span>
              Runtime DB owner missing{" "}
              {(p0aCredentialRequestSummary?.missing_required_by_owner?.runtime_database_admin || []).join(", ") ||
                "none"}
            </span>
            <span>Next command {p0aCredentialRequestSummary?.next_command || "none"}</span>
            <span>Post-update verifier {p0aCredentialRequestSummary?.post_update_verification_command || "none"}</span>
            <span>
              Source checklist hash{" "}
              {shortHash(p0aCredentialRequest?.source_p0a_execution_checklist?.p0a_execution_checklist_hash)}
            </span>
            <span>
              {p0aCredentialRequest?.runtime_endpoints?.p0a_credential_request ||
                "GET /v1/p0a-credential-request/au"}
            </span>
            <span>Hard gate: make verify-au-p0a-credential-request</span>
            <span>
              Ready env hard gate:{" "}
              {p0aCredentialRequest?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-ready-environment")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_env_report.py docs/runtime_preflight/au-p0a-env-latest.json --require-ready-environment"}
            </span>
          </div>
          {requestedP0aCredentials.length ? (
            <div className="dependencyGroupGrid">
              {requestedP0aCredentials.map((credential) => (
                <div className="dependencyGroup" key={credential.name}>
                  <strong>{credential.name}</strong>
                  <span>
                    {credential.owner_hint || "owner"} · {credential.present ? "present" : "missing"}
                  </span>
                  <small>
                    {credential.env_file_key || credential.name} · source {credential.source || "missing"}
                  </small>
                  <small>
                    methods {(credential.accepted_injection_methods || []).slice(0, 3).join(" · ") || "none"}
                  </small>
                  <small>redacted {credential.secret_redacted ? "yes" : "no"}</small>
                </div>
              ))}
            </div>
          ) : null}
          {p0aCredentialRequestEvidenceOutputs.length ? (
            <ul className="plainList compactList">
              {p0aCredentialRequestEvidenceOutputs.slice(0, 5).map((output) => (
                <li key={output}>{output}</li>
              ))}
            </ul>
          ) : null}
          <code>{paths.p0aCredentialRequest}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0a credential fulfillment</strong>
            <span>
              {p0aCredentialFulfillment?.p0a_credential_fulfillment_version ||
                "au_p0a_credential_fulfillment_v1"}{" "}
              · p0a_credential_fulfillment_hash{" "}
              {shortHash(p0aCredentialFulfillment?.p0a_credential_fulfillment_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Fulfillment ready {p0aCredentialFulfillment?.credential_fulfillment_ready ? "yes" : "no"}</span>
            <span>Credentials fulfilled {p0aCredentialFulfillment?.credentials_fulfilled ? "yes" : "no"}</span>
            <span>Environment ready {p0aCredentialFulfillmentSummary?.environment_ready ? "yes" : "no"}</span>
            <span>
              Fulfilled required {p0aCredentialFulfillmentSummary?.fulfilled_required_count || 0}/
              {p0aCredentialFulfillmentSummary?.required_count || 0}
            </span>
            <span>Missing required {p0aCredentialFulfillmentSummary?.missing_required_count || 0}</span>
            <span>Presence mismatches {p0aCredentialFulfillmentSummary?.presence_mismatch_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>Missing {p0aCredentialFulfillmentMissing.join(", ") || "none"}</span>
            <span>Mismatches {p0aCredentialFulfillmentMismatches.join(", ") || "none"}</span>
            <span>Next action {p0aCredentialFulfillmentSummary?.next_action || "none"}</span>
            <span>Next command {p0aCredentialFulfillmentSummary?.next_command || "none"}</span>
            <span>
              Request hash{" "}
              {shortHash(p0aCredentialFulfillment?.source_p0a_credential_request?.p0a_credential_request_packet_hash)}
            </span>
            <span>Env hash {shortHash(p0aCredentialFulfillment?.source_p0a_env_report?.environment_report_hash)}</span>
            <span>
              {p0aCredentialFulfillment?.runtime_endpoints?.p0a_credential_fulfillment ||
                "GET /v1/p0a-credential-fulfillment/au"}
            </span>
            <span>Hard gate: make verify-au-p0a-credential-fulfillment</span>
            <span>
              Strict gate:{" "}
              {p0aCredentialFulfillmentSummary?.strict_gate_command ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_credential_fulfillment.py docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json --require-fulfilled"}
            </span>
          </div>
          {p0aCredentialFulfillmentItems.length ? (
            <div className="dependencyGroupGrid">
              {p0aCredentialFulfillmentItems.map((item) => (
                <div className="dependencyGroup" key={item.name}>
                  <strong>{item.name}</strong>
                  <span>
                    {item.owner_hint || "owner"} · {item.fulfilled ? "fulfilled" : "missing"}
                  </span>
                  <small>
                    request {item.requested_present ? "present" : "missing"} · env{" "}
                    {item.environment_present ? "present" : "missing"}
                  </small>
                  <small>
                    source {item.environment_source || "missing"} · hash {shortHash(item.sha256_prefix)}
                  </small>
                  <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
          ) : null}
          <code>{paths.p0aCredentialFulfillment}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0a credential clearance</strong>
            <span>
              {p0aCredentialClearance?.p0a_credential_clearance_version ||
                "au_p0a_credential_clearance_v1"}{" "}
              · p0a_credential_clearance_hash{" "}
              {shortHash(p0aCredentialClearance?.p0a_credential_clearance_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Clearance packet {p0aCredentialClearance?.credential_clearance_packet_ready ? "ready" : "blocked"}
            </span>
            <span>Credentials cleared {p0aCredentialClearance?.credential_clearance_ready ? "yes" : "no"}</span>
            <span>Credentials fulfilled {p0aCredentialClearance?.credentials_fulfilled ? "yes" : "no"}</span>
            <span>Next clearance {p0aCredentialClearance?.ready_for_next_clearance_step ? "ready" : "blocked"}</span>
            <span>Missing required {p0aCredentialClearanceSummary?.missing_required_count || 0}</span>
            <span>Operator steps {p0aCredentialClearanceSummary?.operator_step_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>Target env file {p0aCredentialClearanceSummary?.target_env_file || "none"}</span>
            <span>Missing {p0aCredentialClearanceMissing.join(", ") || "none"}</span>
            <span>
              Provider missing {(p0aCredentialClearanceSummary?.provider_missing_required || []).join(", ") || "none"}
            </span>
            <span>
              Runtime DB missing{" "}
              {(p0aCredentialClearanceSummary?.runtime_database_missing_required || []).join(", ") || "none"}
            </span>
            <span>Current clearance step {p0aCredentialClearanceSummary?.current_clearance_step_id || "none"}</span>
            <span>Next action {p0aCredentialClearanceSummary?.next_action || "none"}</span>
            <span>Next command {p0aCredentialClearanceSummary?.next_command || "none"}</span>
            <span>Raw secret allowed {p0aCredentialClearanceSummary?.raw_secret_values_allowed ? "yes" : "no"}</span>
            <span>
              Request hash {shortHash(p0aCredentialClearance?.source_artifacts?.credential_request?.hash)}
            </span>
            <span>
              Fulfillment hash {shortHash(p0aCredentialClearance?.source_artifacts?.credential_fulfillment?.hash)}
            </span>
            <span>
              {p0aCredentialClearance?.runtime_endpoints?.p0a_credential_clearance ||
                "GET /v1/p0a-credential-clearance/au"}
            </span>
            <span>Hard gate: make verify-au-p0a-credential-clearance</span>
            <span>
              Strict gate:{" "}
              {p0aCredentialClearance?.hard_gate_commands?.find((command) => command.endsWith("--require-cleared")) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_credential_clearance.py docs/runtime_preflight/au-p0a-credential-clearance-latest.json --require-cleared"}
            </span>
          </div>
          {p0aCredentialClearanceItems.length ? (
            <div className="dependencyGroupGrid">
              {p0aCredentialClearanceItems.map((item) => (
                <div className="dependencyGroup" key={item.name}>
                  <strong>{item.name}</strong>
                  <span>
                    {item.owner_hint || "owner"} · env {item.environment_present ? "present" : "missing"}
                  </span>
                  <small>{item.env_file_key || item.name} · {item.target_env_file || "target env"}</small>
                  <small>
                    methods {(item.accepted_injection_methods || []).slice(0, 3).join(" · ") || "none"}
                  </small>
                  <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "no blocking reasons"}</small>
                </div>
              ))}
            </div>
          ) : null}
          {p0aCredentialClearanceSteps.length ? (
            <ul className="plainList compactList">
              {p0aCredentialClearanceSteps.slice(0, 6).map((step) => (
                <li key={step.id || step.command}>
                  {step.order || 0}. {step.command || step.id} · {step.external_call_risk || "risk unknown"}
                </li>
              ))}
            </ul>
          ) : null}
          {p0aCredentialClearanceValidation.length ? (
            <div className="handoffBoundary">
              <span>
                Validation sequence{" "}
                {p0aCredentialClearanceValidation.slice(0, 5).join(" -> ") || "none"}
              </span>
            </div>
          ) : null}
          <code>{paths.p0aCredentialClearance}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0a real batch request packet</strong>
            <span>
              {p0aRealBatchRequest?.p0a_real_batch_request_packet_version ||
                "au_p0a_real_batch_request_packet_v1"}{" "}
              · p0a_real_batch_request_packet_hash {shortHash(p0aRealBatchRequest?.p0a_real_batch_request_packet_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Packet ready {p0aRealBatchRequest?.real_batch_request_packet_ready ? "yes" : "no"}</span>
            <span>Real batch handoff {p0aRealBatchRequest?.real_batch_phase_handoff_ready ? "ready" : "blocked"}</span>
            <span>Design partner {p0aRealBatchRequest?.ready_for_design_partner ? "ready" : "blocked"}</span>
            <span>Total planned runs {p0aRealBatchRequestSummary?.total_planned_runs || 0}</span>
            <span>
              Phases {p0aRealBatchRequestSummary?.ready_phase_count || 0}/
              {p0aRealBatchRequestSummary?.phase_count || 0}
            </span>
            <span>Next phase {p0aRealBatchRequestSummary?.next_phase || "none"}</span>
            <span>Blocking reasons {p0aRealBatchRequestSummary?.blocking_reason_count || 0}</span>
            <span>Raw secret allowed {p0aRealBatchRequestSummary?.raw_secret_values_allowed ? "yes" : "no"}</span>
          </div>
          <div className="handoffBoundary">
            <span>Next command {p0aRealBatchRequestSummary?.next_command || "none"}</span>
            <span>
              Post-update verifier {p0aRealBatchRequestSummary?.post_update_verification_command || "none"}
            </span>
            <span>P0a next action {p0aRealBatchRequestSummary?.p0a_next_action || "none"}</span>
            <span>
              Blocking {p0aRealBatchBlockingReasons.slice(0, 4).join(", ") || "none"}
            </span>
            <span>
              Source checklist hash{" "}
              {shortHash(p0aRealBatchRequest?.source_p0a_execution_checklist?.p0a_execution_checklist_hash)}
            </span>
            <span>
              {p0aRealBatchRequest?.runtime_endpoints?.p0a_real_batch_request ||
                "GET /v1/p0a-real-batch-request/au"}
            </span>
            <span>Hard gate: make verify-au-p0a-real-batch-request</span>
            <span>
              Ready batch hard gate:{" "}
              {p0aRealBatchRequest?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-real-batches-ready")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_real_batch_request_packet.py docs/runtime_preflight/au-p0a-real-batch-request-latest.json --require-real-batches-ready"}
            </span>
          </div>
          <div className="dependencyGroupGrid">
            {p0aRealBatchPhases.map((phase) => (
              <div className="dependencyGroup" key={phase.id}>
                <strong>{phase.title || phase.id}</strong>
                <span>
                  {phase.ready ? "ready" : "blocked"} · can start {phase.can_start ? "yes" : "no"} · runs{" "}
                  {phase.planned_runs || 0}
                </span>
                <small>{(phase.command_ids || []).slice(0, 3).join(" · ") || "no commands"}</small>
                <small>{(phase.blocking_reasons || []).slice(0, 2).join(" · ") || "no blockers"}</small>
              </div>
            ))}
          </div>
          {p0aRealBatchEvidenceOutputs.length ? (
            <ul className="plainList compactList">
              {p0aRealBatchEvidenceOutputs.slice(0, 6).map((output) => (
                <li key={output}>{output}</li>
              ))}
            </ul>
          ) : null}
          <code>{paths.p0aRealBatchRequest}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0a real batch fulfillment</strong>
            <span>
              {p0aRealBatchFulfillment?.p0a_real_batch_fulfillment_version ||
                "au_p0a_real_batch_fulfillment_v1"}{" "}
              · p0a_real_batch_fulfillment_hash{" "}
              {shortHash(p0aRealBatchFulfillment?.p0a_real_batch_fulfillment_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Fulfillment ready {p0aRealBatchFulfillment?.real_batch_fulfillment_ready ? "yes" : "no"}</span>
            <span>Real batches {p0aRealBatchFulfillment?.real_batches_fulfilled ? "fulfilled" : "blocked"}</span>
            <span>Design partner {p0aRealBatchFulfillment?.ready_for_design_partner ? "ready" : "blocked"}</span>
            <span>
              Phases {p0aRealBatchFulfillmentSummary?.ready_phase_count || 0}/
              {p0aRealBatchFulfillmentSummary?.phase_count || 0}
            </span>
            <span>Next phase {p0aRealBatchFulfillmentSummary?.next_phase || "none"}</span>
            <span>Missing required {p0aRealBatchFulfillmentSummary?.missing_required_count || 0}</span>
            <span>Presence mismatches {p0aRealBatchFulfillmentSummary?.presence_mismatch_count || 0}</span>
            <span>Total planned runs {p0aRealBatchFulfillmentSummary?.total_planned_runs || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>Next action {p0aRealBatchFulfillmentSummary?.next_action || "none"}</span>
            <span>Next command {p0aRealBatchFulfillmentSummary?.next_command || "none"}</span>
            <span>Missing {p0aRealBatchFulfillmentMissing.slice(0, 4).join(", ") || "none"}</span>
            <span>Blocking {p0aRealBatchFulfillmentBlockers.slice(0, 4).join(", ") || "none"}</span>
            <span>
              Request hash{" "}
              {shortHash(p0aRealBatchFulfillment?.source_p0a_real_batch_request?.p0a_real_batch_request_packet_hash)}
            </span>
            <span>
              Checklist hash{" "}
              {shortHash(p0aRealBatchFulfillment?.source_p0a_execution_checklist?.p0a_execution_checklist_hash)}
            </span>
            <span>
              {p0aRealBatchFulfillment?.runtime_endpoints?.p0a_real_batch_fulfillment ||
                "GET /v1/p0a-real-batch-fulfillment/au"}
            </span>
            <span>Hard gate: make verify-au-p0a-real-batch-fulfillment</span>
            <span>
              Strict gate:{" "}
              {p0aRealBatchFulfillmentSummary?.strict_gate_command ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_real_batch_fulfillment.py docs/runtime_preflight/au-p0a-real-batch-fulfillment-latest.json --require-fulfilled"}
            </span>
          </div>
          <div className="dependencyGroupGrid">
            {p0aRealBatchFulfillmentItems.map((item) => (
              <div className="dependencyGroup" key={item.key}>
                <strong>{item.title || item.phase_id}</strong>
                <span>
                  {item.fulfilled ? "fulfilled" : "blocked"} · request {item.request_ready ? "ready" : "blocked"} ·
                  checklist {item.checklist_ready ? "ready" : "blocked"}
                </span>
                <small>
                  can start request {item.request_can_start ? "yes" : "no"} · checklist{" "}
                  {item.checklist_can_start ? "yes" : "no"} · runs {item.planned_runs || 0}
                </small>
                <small>{(item.command_ids || []).slice(0, 3).join(" · ") || "no commands"}</small>
                <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
              </div>
            ))}
          </div>
          <code>{paths.p0aRealBatchFulfillment}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>P0a real batch clearance</strong>
            <span>
              {p0aRealBatchClearance?.p0a_real_batch_clearance_version ||
                "au_p0a_real_batch_clearance_v1"}{" "}
              · p0a_real_batch_clearance_hash {shortHash(p0aRealBatchClearance?.p0a_real_batch_clearance_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>
              Clearance packet {p0aRealBatchClearance?.real_batch_clearance_packet_ready ? "ready" : "blocked"}
            </span>
            <span>Real batches {p0aRealBatchClearance?.real_batches_fulfilled ? "fulfilled" : "blocked"}</span>
            <span>Clearance ready {p0aRealBatchClearance?.real_batch_clearance_ready ? "yes" : "no"}</span>
            <span>Next clearance {p0aRealBatchClearance?.ready_for_next_clearance_step ? "ready" : "blocked"}</span>
            <span>Prerequisite blocked {p0aRealBatchClearance?.blocked_by_prerequisite_step ? "yes" : "no"}</span>
            <span>Total planned runs {p0aRealBatchClearanceSummary?.total_planned_runs || 0}</span>
            <span>
              Phases {p0aRealBatchClearanceSummary?.ready_phase_count || 0}/
              {p0aRealBatchClearanceSummary?.phase_count || 0}
            </span>
            <span>Missing required {p0aRealBatchClearanceSummary?.missing_required_count || 0}</span>
          </div>
          <div className="handoffBoundary">
            <span>Current global step {p0aRealBatchClearanceSummary?.current_global_clearance_step_id || "none"}</span>
            <span>Target step {p0aRealBatchClearanceSummary?.target_clearance_step_id || "none"}</span>
            <span>Prerequisite {p0aRealBatchClearanceSummary?.prerequisite_step_id || "none"}</span>
            <span>Next phase {p0aRealBatchClearanceSummary?.next_phase || "none"}</span>
            <span>Next action {p0aRealBatchClearanceSummary?.next_action || "none"}</span>
            <span>Next command {p0aRealBatchClearanceSummary?.next_command || "none"}</span>
            <span>Missing {p0aRealBatchClearanceMissing.slice(0, 4).join(", ") || "none"}</span>
            <span>Raw secret allowed {p0aRealBatchClearanceSummary?.raw_secret_values_allowed ? "yes" : "no"}</span>
            <span>
              Request hash {shortHash(p0aRealBatchClearance?.source_artifacts?.real_batch_request?.hash)}
            </span>
            <span>
              Fulfillment hash {shortHash(p0aRealBatchClearance?.source_artifacts?.real_batch_fulfillment?.hash)}
            </span>
            <span>
              {p0aRealBatchClearance?.runtime_endpoints?.p0a_real_batch_clearance ||
                "GET /v1/p0a-real-batch-clearance/au"}
            </span>
            <span>Hard gate: make verify-au-p0a-real-batch-clearance</span>
            <span>
              Strict gate:{" "}
              {p0aRealBatchClearance?.hard_gate_commands?.find((command) => command.endsWith("--require-cleared")) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_real_batch_clearance.py docs/runtime_preflight/au-p0a-real-batch-clearance-latest.json --require-cleared"}
            </span>
          </div>
          <div className="dependencyGroupGrid">
            {p0aRealBatchClearanceItems.map((item) => (
              <div className="dependencyGroup" key={item.key}>
                <strong>{item.title || item.phase_id}</strong>
                <span>
                  {item.fulfilled ? "fulfilled" : "blocked"} · can start {item.can_start ? "yes" : "no"} · runs{" "}
                  {item.planned_runs || 0}
                </span>
                <small>
                  request {item.request_ready ? "ready" : "blocked"} · checklist{" "}
                  {item.checklist_ready ? "ready" : "blocked"}
                </small>
                <small>{(item.command_ids || []).slice(0, 3).join(" · ") || "no commands"}</small>
                <small>{(item.blocking_reasons || []).slice(0, 2).join(" · ") || "gate clear"}</small>
              </div>
            ))}
          </div>
          {p0aRealBatchClearanceSteps.length ? (
            <ul className="plainList compactList">
              {p0aRealBatchClearanceSteps.slice(0, 6).map((step) => (
                <li key={step.id || step.order}>
                  {step.order}. {step.id}: {step.command}
                </li>
              ))}
            </ul>
          ) : null}
          {p0aRealBatchClearanceValidation.length ? (
            <div className="handoffBoundary">
              <span>
                post_update_validation_sequence{" "}
                {p0aRealBatchClearanceValidation.slice(0, 5).join(" -> ") || "none"}
              </span>
            </div>
          ) : null}
          <code>{paths.p0aRealBatchClearance}</code>
        </div>
        <div className="handoffDossier">
          <div className="launchRemediationHeader">
            <strong>Next work item packet</strong>
            <span>
              {nextWorkItemPacket?.next_work_item_packet_version || "au_next_work_item_packet_v1"} · next_work_item_packet_hash{" "}
              {shortHash(nextWorkItemPacket?.next_work_item_packet_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Packet ready {nextWorkItemPacket?.next_work_item_packet_ready ? "yes" : "no"}</span>
            <span>
              Customer report {nextWorkItemPacket?.ready_for_customer_report_handoff ? "ready" : "blocked"}
            </span>
            <span>Work item {nextWorkItemSummary?.next_work_item_id || "none"}</span>
            <span>Stage {nextWorkItemSummary?.stage || "unknown"}</span>
            <span>External dependency {nextWorkItemSummary?.external_dependency ? "yes" : "no"}</span>
            <span>Runnable now {nextWorkItemSummary?.runnable_now ? "yes" : "no"}</span>
          </div>
          <div className="handoffBoundary">
            <span>Title {nextWorkItemSummary?.title || nextWorkItemPacket?.next_work_item?.title || "none"}</span>
            <span>Dependency class {nextWorkItemSummary?.dependency_class || "none"}</span>
            <span>
              Blockers {nextWorkItemSummary?.blocker_count || 0} · remaining{" "}
              {nextWorkItemSummary?.remaining_blocker_count || 0} · external{" "}
              {nextWorkItemSummary?.external_dependency_blocker_count || 0}
            </span>
            <span>
              Customer readiness {nextWorkItemSummary?.customer_report_handoff_readiness_percent ?? 0}% · auditability{" "}
              {nextWorkItemSummary?.structural_auditability_percent ?? 0}%
            </span>
            <span>
              Commands {nextWorkItemSummary?.command_count || 0} · verifiers{" "}
              {nextWorkItemSummary?.verification_command_count || 0} · evidence outputs{" "}
              {nextWorkItemSummary?.evidence_output_count || 0}
            </span>
            <span>
              Work item counts {nextWorkItemSummary?.work_item_command_count || 0}/
              {nextWorkItemSummary?.work_item_verification_command_count || 0}/
              {nextWorkItemSummary?.work_item_evidence_output_count || 0}
            </span>
            <span>
              Dependency group counts {nextWorkItemSummary?.group_command_count || 0}/
              {nextWorkItemSummary?.group_verification_command_count || 0}/
              {nextWorkItemSummary?.group_evidence_output_count || 0}
            </span>
            <span>Linked group {nextWorkItemSummary?.linked_dependency_group_id || "none"}</span>
            <span>
              Linked artifact {nextWorkItemSummary?.linked_request_packet_id || "none"} ·{" "}
              {nextWorkItemSummary?.linked_request_artifact_type || nextWorkItemLinkedRequest?.artifact_type || "unknown"} ·{" "}
              {shortHash(nextWorkItemSummary?.linked_request_packet_hash)}
            </span>
            <span>Linked artifact exists {nextWorkItemSummary?.linked_request_packet_exists ? "yes" : "no"}</span>
            <span>Sequence steps {nextWorkItemSummary?.recommended_sequence_count || 0}</span>
            <span>Next command {nextWorkItemCommands[0] || "none"}</span>
            <span>Next verifier {nextWorkItemVerificationCommands[0] || "none"}</span>
            <span>First evidence output {nextWorkItemEvidenceOutputs[0] || "none"}</span>
            <span>Artifact build {nextWorkItemLinkedRequest?.build_command || "none"}</span>
            <span>Artifact verifier {nextWorkItemLinkedRequest?.verify_command || "none"}</span>
            <span>Artifact strict gate {nextWorkItemLinkedRequest?.strict_gate_command || "none"}</span>
            <span>
              Artifact endpoint {nextWorkItemLinkedRequest?.runtime_endpoint || "none"}
            </span>
            <span>
              Dependency group status {nextWorkItemLinkedDependencyGroup?.status || "none"} · blockers{" "}
              {nextWorkItemLinkedDependencyGroup?.blocking_reason_count || 0}
            </span>
            <span>Dependency group next {nextWorkItemLinkedDependencyGroup?.next_command || "none"}</span>
            <span>
              Group verifiers {nextWorkItemLinkedDependencyGroup?.verification_command_count || 0} · evidence{" "}
              {nextWorkItemLinkedDependencyGroup?.evidence_output_count || 0}
            </span>
            <span>
              Fulfillment gate{" "}
              {nextWorkItemVerificationCommands.find((command) => command.includes("--require-fulfilled")) ||
                "pending"}
            </span>
            <span>
              Dependency group source{" "}
              {shortHash(nextWorkItemLinkedDependencyGroup?.source_external_dependency_handoff_hash)}
            </span>
            <span>
              Source dossier hash {shortHash(nextWorkItemPacket?.source_handoff_dossier?.handoff_dossier_hash)}
            </span>
            <span>
              {nextWorkItemPacket?.runtime_endpoints?.next_work_item || "GET /v1/next-work-item/au"}
            </span>
            <span>Hard gate: make verify-au-next-work-item</span>
            <span>
              Customer hard gate:{" "}
              {nextWorkItemPacket?.hard_gate_commands?.find((command) =>
                command.endsWith("--require-customer-ready")
              ) ||
                "PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py docs/runtime_preflight/au-customer-handoff-readiness-latest.json --require-customer-ready"}
            </span>
          </div>
          {nextWorkItemEvidenceOutputs.length ? (
            <ul className="plainList compactList">
              {nextWorkItemEvidenceOutputs.slice(0, 5).map((output) => (
                <li key={output}>{output}</li>
              ))}
            </ul>
          ) : null}
          {nextWorkItemRecommendedSequence.length ? (
            <ul className="plainList compactList">
              {nextWorkItemRecommendedSequence.slice(0, 10).map((command) => (
                <li key={command}>{command}</li>
              ))}
            </ul>
          ) : null}
          <code>{paths.nextWorkItem}</code>
        </div>
        <div className="externalDependencyHandoff">
          <div className="launchRemediationHeader">
            <strong>External dependency handoff</strong>
            <span>
              {externalDependencyHandoff?.external_dependency_handoff_version ||
                "au_external_dependency_handoff_v1"} · hash{" "}
              {shortHash(externalDependencyHandoff?.external_dependency_handoff_hash)}
            </span>
          </div>
          <div className="launchEvidenceGrid">
            <span>Structural ready {externalDependencySummary?.structural_ready ? "yes" : "no"}</span>
            <span>
              External ready {externalDependencyHandoff?.external_dependency_handoff_ready ? "yes" : "no"}
            </span>
            <span>Posture {externalDependencySummary?.handoff_posture || "unknown"}</span>
            <span>
              Blockers {externalDependencySummary?.external_dependency_blocker_count || 0} · groups{" "}
              {externalDependencySummary?.dependency_group_count || 0}
            </span>
            <span>
              Clearance {externalDependencySummary?.clearance_ready_step_count || 0}/
              {externalDependencySummary?.clearance_step_count || 0} · current{" "}
              {externalDependencySummary?.clearance_current_step_id || externalClearanceSequence?.current_step_id || "none"}
            </span>
          </div>
          <div className="handoffBoundary">
            <span>
              Next dependency item{" "}
              {externalDependencyHandoff?.next_dependency_item_id || externalNextDependencyItem?.id || "none"}
            </span>
            <span>
              P0a credentials missing {externalDependencySummary?.p0a_required_secret_missing_count || 0} · real batch{" "}
              {externalDependencySummary?.p0a_real_batch_phase_next_phase || "none"} · planned{" "}
              {externalDependencySummary?.p0a_real_batch_total_planned_runs || 0}
            </span>
            <span>
              P0b required inputs missing {externalDependencySummary?.p0b_google_required_input_missing_count || 0} · Google phase{" "}
              {externalDependencySummary?.p0b_google_phase_next_phase || "none"} · full spike{" "}
              {externalDependencySummary?.p0b_google_full_spike_planned_runs || 0}
            </span>
            <span>
              Manual rows {externalDependencySummary?.p0b_google_manual_backfill_record_count || 0}/
              {externalDependencySummary?.p0b_google_manual_backfill_expected_record_count || 0}
            </span>
            <span>Hard gate: scripts/verify_au_external_dependency_handoff.py --require-ready</span>
            <span>Next clearance command {externalClearanceSequence?.next_command || "none"}</span>
          </div>
          <div className="clearanceDryRun">
            <div className="launchRemediationHeader">
              <strong>Clearance dry-run</strong>
              <span>
                {externalDependencyClearance?.clearance_execution_version ||
                  "au_external_dependency_clearance_execution_v1"} · hash{" "}
                {shortHash(externalDependencyClearance?.clearance_execution_hash)}
              </span>
            </div>
            <div className="launchEvidenceGrid">
              <span>Mode {externalDependencyClearance?.mode || "dry_run"}</span>
              <span>Status {externalDependencyClearance?.status || "unknown"}</span>
              <span>Ready to execute {externalDependencyClearance?.ready_to_execute ? "yes" : "no"}</span>
              <span>
                Handoff ready {externalDependencyClearance?.external_dependency_handoff_ready ? "yes" : "no"}
              </span>
              <span>
                Current step {externalDependencyClearance?.current_step_id || externalClearanceSequence?.current_step_id || "none"}
              </span>
              <span>Would execute {externalDependencyClearance?.would_execute_step_count || 0}</span>
            </div>
            <div className="handoffBoundary">
              <span>Dry-run does not execute provider, DB, Google, manual, or customer handoff commands.</span>
              <span>
                Next command {externalDependencyClearance?.next_command || externalClearanceSequence?.next_command || "none"}
              </span>
              <span>
                Steps {externalDependencyClearance?.recorded_step_count || 0}/
                {externalDependencyClearance?.planned_step_count || 0} · blocked{" "}
                {externalDependencyClearance?.blocked_step_count || 0}
              </span>
              <span>
                Request context {externalDependencyCurrentRequest?.request_artifact_id || "none"} ·{" "}
                {shortHash(externalDependencyCurrentRequest?.artifact_hash)}
              </span>
              <span>Request build {externalDependencyCurrentRequest?.build_command || "none"}</span>
              <span>Request verifier {externalDependencyCurrentRequest?.verify_command || "none"}</span>
              <span>Request strict gate {externalDependencyCurrentRequest?.strict_gate_command || "none"}</span>
              <span>Request endpoint {externalDependencyCurrentRequest?.runtime_endpoint || "none"}</span>
              <span>
                Recommended sequence {externalDependencyClearance?.current_recommended_sequence_count || 0} steps
              </span>
              <span>
                Hard gate: scripts/verify_au_external_dependency_clearance.py --require-handoff-ready
              </span>
              <span>Would-execute step {externalDependencyWouldExecuteStep?.id || "none"}</span>
            </div>
            {externalDependencyCurrentSequence.length ? (
              <ul className="plainList compactList">
                {externalDependencyCurrentSequence.slice(0, 6).map((command) => (
                  <li key={command}>{command}</li>
                ))}
              </ul>
            ) : null}
            <div className="clearanceStepGrid">
              {topExternalDependencyClearanceSteps.map((step) => (
                <div className="clearanceStep" key={step.id}>
                  <strong>
                    {step.index || 0}. {step.title || step.id}
                  </strong>
                  <span>
                    {step.would_execute ? "would execute" : step.ready ? "ready" : step.status || "blocked"}
                  </span>
                  <small>{step.linked_request_context?.request_artifact_id || "no request context"}</small>
                  <small>{(step.blocked_by || []).slice(0, 2).join(" · ") || "gate clear"}</small>
                </div>
              ))}
            </div>
            <code>{paths.externalDependencyClearance}</code>
          </div>
          <div className="clearanceStepGrid">
            {topExternalClearanceSteps.map((step) => (
              <div className="clearanceStep" key={step.id}>
                <strong>
                  {step.order || 0}. {step.title || step.id}
                </strong>
                <span>
                  {step.can_start ? "can start" : step.ready ? "ready" : step.status || "blocked"}
                </span>
                <small>{(step.blocked_by || []).slice(0, 2).join(" · ") || "gate clear"}</small>
              </div>
            ))}
          </div>
          <div className="dependencyGroupGrid">
            {topExternalDependencyGroups.map((group) => (
              <div className="dependencyGroup" key={group.id}>
                <strong>{group.title || group.id}</strong>
                <span>
                  {group.stage || "stage"} · {group.ready ? "ready" : group.status || "blocked"}
                </span>
                <small>
                  {group.dependency_class || "dependency"} · missing{" "}
                  {group.missing_required_count ?? group.missing_reason_count ?? group.blocked_phase_count ?? 0}
                </small>
                <small>Next {group.next_command || "none"}</small>
                <small>{group.commands?.length || 0} commands</small>
                <small>
                  Blocked {(group.blocking_reasons || group.missing_required || group.missing_reasons || [])
                    .slice(0, 3)
                    .join(" · ") || "gate clear"}
                </small>
              </div>
            ))}
          </div>
          <code>{paths.externalDependencyHandoff}</code>
        </div>
        <code>{paths.launchStatus}</code>
      </section>

      <section className="metrics" aria-label="runtime metrics">
        <Metric label="Projects" value={data.projects.total_count} />
        <Metric label="Prompts" value={data.prompts.total_count} />
        <Metric label="Evidence runs" value={data.evidence.total_count} />
        <Metric label="Question coverage" value={pct(questionCoverageRate)} />
        <Metric label="Final score" value={num(latestScore?.snapshot.final_score)} />
        <Metric label="Source gaps" value={latestGraph?.source_gaps.length || 0} />
        <Metric label="Open actions" value={latestAction?.action_recommendations.length || 0} />
        <Metric label="Content drafts" value={latestContent?.content_drafts.length || 0} />
        <Metric label="Human reviews" value={data.humanReviews.total_count} />
        <Metric label="Audit events" value={totalAuditEvents} />
        <Metric label="Trace links" value={traceability?.evidence_links.length || 0} />
      </section>

      <section className="dashboard">
        <Panel title="Project Bootstrap" subtitle={latestProject?.project.name || "No runtime project"}>
          <div className="stack">
            {latestProject ? (
              <>
                <dl className="facts">
                  <Fact label="Tenant" value={latestProject.tenant.name} />
                  <Fact label="Project ID" value={shortId(latestProject.project.id)} />
                  <Fact label="Market" value={latestProject.project.market_code} />
                  <Fact label="Industry" value={latestProject.project.industry_code} />
                  <Fact label="Brand" value={latestProject.brand?.canonical_name || latestProject.project.target_brand} />
                  <Fact label="Category" value={latestProject.project.category} />
                  <Fact label="Prompts" value={latestProject.prompt_count} />
                  <Fact label="Competitors" value={latestProject.competitors.length} />
                </dl>
                <ul className="plainList">
                  {latestProject.competitors.slice(0, 4).map((competitor) => (
                    <li key={competitor.canonical_name}>
                      <strong>{competitor.status || "competitor"}</strong>
                      <span>{competitor.canonical_name}</span>
                      <small>{competitor.official_domains?.[0] || "domain pending"}</small>
                    </li>
                  ))}
                </ul>
                <small className="auditLine">
                  {latestProject.audit_events[0]?.event_type || "no bootstrap audit"} ·{" "}
                  {latestProject.audit_events[0]?.method_version || "no method version"}
                </small>
                <form action={updateRuntimeProject} className="projectUpdateForm">
                  <div className="formHeader">
                    <h3>Project Metadata</h3>
                    <small>PATCH /v1/projects/runtime · project_updated</small>
                  </div>
                  <input type="hidden" name="project_id" value={latestProject.project.id} />
                  <label>
                    <span>Project</span>
                    <input name="name" defaultValue={latestProject.project.name} />
                  </label>
                  <label>
                    <span>Brand</span>
                    <input name="target_brand" defaultValue={latestProject.project.target_brand} />
                  </label>
                  <label>
                    <span>Category</span>
                    <input name="category" defaultValue={latestProject.project.category} />
                  </label>
                  <label>
                    <span>Status</span>
                    <select name="status" defaultValue={latestProject.project.status}>
                      <option value="configured">configured</option>
                      <option value="active">active</option>
                      <option value="paused">paused</option>
                    </select>
                  </label>
                  <label className="wideField">
                    <span>Reason</span>
                    <input name="reason" defaultValue="Update runtime project metadata" />
                  </label>
                  <input type="hidden" name="updated_by" value="runtime-console" />
                  <button className="actionButton" type="submit">
                    Save project
                  </button>
                </form>
                <div className="projectLifecycleActions">
                  <div className="formHeader">
                    <h3>Project Actions</h3>
                    <small>
                      POST /v1/projects/runtime/action · project_archived · project_restored · evidence preserved
                    </small>
                  </div>
                  <form action={actionRuntimeProject} className="inlineForm">
                    <input type="hidden" name="project_id" value={latestProject.project.id} />
                    <input
                      type="hidden"
                      name="action"
                      value={latestProject.project.status === "archived" ? "restore" : "archive"}
                    />
                    <input type="hidden" name="updated_by" value="runtime-console" />
                    <input
                      type="hidden"
                      name="reason"
                      value={
                        latestProject.project.status === "archived"
                          ? "Restore runtime project from archive"
                          : "Archive runtime project and preserve evidence history"
                      }
                    />
                    <button className="textButton" type="submit">
                      {latestProject.project.status === "archived" ? "Restore project" : "Archive project"}
                    </button>
                  </form>
                </div>
                <div className="projectLifecycleHistory">
                  <div className="formHeader">
                    <h3>Project Lifecycle</h3>
                    <small>
                      GET /v1/projects/runtime/lifecycle-events · project_bootstrap_created · project_updated ·
                      project_archived · project_restored
                    </small>
                  </div>
                  <div className="downloadRow">
                    <a href={projectLifecycleExportUrl}>Download lifecycle CSV</a>
                  </div>
                  <Fact label="Lifecycle export" value={paths.projectLifecycleExport} />
                  {data.projectLifecycleEvents.records.length ? (
                    <ul className="plainList">
                      {data.projectLifecycleEvents.records.slice(0, 6).map((record) => (
                        <li key={record.lifecycle_event.id || `${record.lifecycle_event.event_type}-${record.lifecycle_event.created_at}`}>
                          <strong>{record.lifecycle_event.event_type || "project_lifecycle_event"}</strong>
                          <span>{record.lifecycle_event.reason || record.lifecycle_event.method_version || "no reason"}</span>
                          <small>
                            {record.lifecycle_event.actor_id || "system"} ·{" "}
                            {record.lifecycle_event.status_before || "none"} →{" "}
                            {record.lifecycle_event.status_after || "none"} ·{" "}
                            {record.lifecycle_event.method_version || "no method"}
                          </small>
                          <small>
                            {record.lifecycle_event.created_at || "no timestamp"} · hash{" "}
                            {record.lifecycle_event.after_hash || record.audit_events[0]?.after_hash || "no hash"}
                          </small>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <small>No project lifecycle events found.</small>
                  )}
                </div>
                <div className="projectLifecycleHistory projectAuditTrail">
                  <div className="formHeader">
                    <h3>Project Audit Trail</h3>
                    <small>GET /v1/audit-events/runtime · append-only AuditEvent query</small>
                  </div>
                  <div className="downloadRow">
                    <a href={auditEventsExportUrl}>Download audit CSV</a>
                  </div>
                  <Fact label="Audit query" value={paths.auditEvents} />
                  <Fact label="Audit export" value={paths.auditEventsExport} />
                  {data.auditEvents.records.length ? (
                    <ul className="plainList">
                      {data.auditEvents.records.slice(0, 6).map((record) => (
                        <li key={record.audit_event.id || `${record.audit_event.event_type}-${record.audit_event.created_at}`}>
                          <strong>{record.audit_event.event_type || "audit_event"}</strong>
                          <span>{record.audit_event.reason || record.audit_event.method_version || "no reason"}</span>
                          <small>
                            {record.audit_event.actor_id || "system"} · {record.audit_event.target_type || "target"} ·{" "}
                            {record.audit_event.method_version || "no method"}
                          </small>
                          <small>
                            {record.audit_event.created_at || "no timestamp"} · hash{" "}
                            {record.audit_event.after_hash || record.audit_event.before_hash || "no hash"}
                          </small>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <small>No project audit events found.</small>
                  )}
                </div>
                <div className="projectMembers">
                  <div className="formHeader">
                    <h3>Project Members</h3>
                    <small>
                      {data.projectMembers.total_count} members · project_members gate · project_member_saved ·
                      project_member_deleted · {data.projectMemberInvitations.total_count} pending invites
                    </small>
                  </div>
                  {data.projectMembers.records.length ? (
                    <ul className="plainList">
                      {data.projectMembers.records.slice(0, 6).map((record) => (
                        <li key={record.member.id}>
                          <strong>{record.member.role}</strong>
                          <span>{record.member.user_id}</span>
                          <small>
                            {record.audit_events[0]?.event_type || "bootstrap member"} ·{" "}
                            {record.audit_events[0]?.actor_id || "system"} ·{" "}
                            {record.audit_events[0]?.after_hash || "no hash"}
                          </small>
                          <form action={deleteRuntimeProjectMember} className="projectMemberDeleteForm">
                            <input type="hidden" name="project_id" value={latestProject.project.id} />
                            <input type="hidden" name="user_id" value={record.member.user_id} />
                            <input type="hidden" name="deleted_by" value="runtime-console" />
                            <input type="hidden" name="reason" value="Remove runtime project collaborator" />
                            <button className="textButton" type="submit">
                              Remove
                            </button>
                          </form>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <small>No runtime project members found.</small>
                  )}
                  <form action={saveRuntimeProjectMember} className="projectMemberForm">
                    <input type="hidden" name="project_id" value={latestProject.project.id} />
                    <label>
                      <span>User ID</span>
                      <input name="user_id" defaultValue="analyst@example.com" />
                    </label>
                    <label>
                      <span>Role</span>
                      <select name="role" defaultValue="analyst">
                        <option value="owner">owner</option>
                        <option value="admin">admin</option>
                        <option value="analyst">analyst</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </label>
                    <label className="wideField">
                      <span>Reason</span>
                      <input name="reason" defaultValue="Add runtime project collaborator" />
                    </label>
                    <input type="hidden" name="updated_by" value="runtime-console" />
                    <button className="actionButton" type="submit">
                      Save member
                    </button>
                  </form>
                  <div className="formHeader">
                    <h3>Member Invitations</h3>
                    <small>
                      project_member_invitation_created · project_member_invitation_revoked ·
                      project_member_invitation_email_sent · project_member_invitation_accepted ·
                      project_member_invitation_expired · hashed token
                    </small>
                  </div>
                  {data.projectMemberInvitations.records.length ? (
                    <ul className="plainList">
                      {data.projectMemberInvitations.records.slice(0, 6).map((record) => (
                        <li key={record.invitation.id}>
                          <strong>{record.invitation.role}</strong>
                          <span>{record.invitation.email}</span>
                          <small>
                            {record.invitation.status} · {record.audit_events[0]?.event_type || "no audit"} ·{" "}
                            {record.invitation.invited_by || record.audit_events[0]?.actor_id || "runtime-console"}
                          </small>
                          <small>
                            hash {record.invitation.invite_token_hash?.slice(0, 16) || "pending"} · expires{" "}
                            {record.invitation.expires_at || "not set"}
                          </small>
                          {record.invitation.invite_token ? (
                            <>
                              <small>one-time token {record.invitation.invite_token}</small>
                              <form action={emailRuntimeProjectMemberInvitation} className="inlineForm">
                                <input type="hidden" name="project_id" value={latestProject.project.id} />
                                <input type="hidden" name="invitation_id" value={record.invitation.id} />
                                <input type="hidden" name="invite_token" value={record.invitation.invite_token} />
                                <input
                                  type="hidden"
                                  name="accept_base_url"
                                  value={`${process.env.NEXT_PUBLIC_APP_BASE_URL || "http://localhost:3000"}/invite/accept`}
                                />
                                <input type="hidden" name="sent_by" value="runtime-console" />
                                <input type="hidden" name="smtp_env_prefix" value="GENO_NOTIFICATION_SMTP" />
                                <input type="hidden" name="subject" value="GENO project invitation" />
                                <input
                                  type="hidden"
                                  name="message"
                                  value="You have been invited to join a GENO runtime project."
                                />
                                <input
                                  type="hidden"
                                  name="reason"
                                  value="Email runtime project invitation with one-time token"
                                />
                                <button className="textButton" type="submit">
                                  Email invite
                                </button>
                              </form>
                              <form action={acceptRuntimeProjectMemberInvitation} className="inlineForm">
                                <input type="hidden" name="invitation_id" value={record.invitation.id} />
                                <input type="hidden" name="invite_token" value={record.invitation.invite_token} />
                                <input
                                  type="hidden"
                                  name="accepted_by"
                                  value={record.invitation.email || "runtime-invitee"}
                                />
                                <input
                                  type="hidden"
                                  name="reason"
                                  value="Accept runtime project invitation from one-time token"
                                />
                                <button className="textButton" type="submit">
                                  Accept invite
                                </button>
                              </form>
                            </>
                          ) : null}
                          {record.invitation.status === "pending" ? (
                            <div className="inlineActions">
                              <form action={actionRuntimeProjectMemberInvitation}>
                                <input type="hidden" name="project_id" value={latestProject.project.id} />
                                <input type="hidden" name="invitation_id" value={record.invitation.id} />
                                <input type="hidden" name="action" value="revoke" />
                                <input type="hidden" name="updated_by" value="runtime-console" />
                                <input
                                  type="hidden"
                                  name="reason"
                                  value="Revoke pending runtime project invitation"
                                />
                                <button className="textButton" type="submit">
                                  Revoke invite
                                </button>
                              </form>
                              <form action={actionRuntimeProjectMemberInvitation}>
                                <input type="hidden" name="project_id" value={latestProject.project.id} />
                                <input type="hidden" name="invitation_id" value={record.invitation.id} />
                                <input type="hidden" name="action" value="expire" />
                                <input type="hidden" name="updated_by" value="runtime-console" />
                                <input
                                  type="hidden"
                                  name="reason"
                                  value="Expire pending runtime project invitation"
                                />
                                <button className="textButton" type="submit">
                                  Expire invite
                                </button>
                              </form>
                            </div>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <small>No pending member invitations found.</small>
                  )}
                  <form action={createRuntimeProjectMemberInvitation} className="projectMemberForm">
                    <input type="hidden" name="project_id" value={latestProject.project.id} />
                    <label>
                      <span>Email</span>
                      <input name="email" type="email" defaultValue="viewer@example.com" />
                    </label>
                    <label>
                      <span>Role</span>
                      <select name="role" defaultValue="viewer">
                        <option value="owner">owner</option>
                        <option value="admin">admin</option>
                        <option value="analyst">analyst</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </label>
                    <label>
                      <span>Expires At</span>
                      <input name="expires_at" type="datetime-local" />
                    </label>
                    <label>
                      <span>Invite Note</span>
                      <input name="invite_note" defaultValue="Design partner runtime access" />
                    </label>
                    <label className="wideField">
                      <span>Reason</span>
                      <input name="reason" defaultValue="Invite runtime project collaborator" />
                    </label>
                    <input type="hidden" name="invited_by" value="runtime-console" />
                    <button className="actionButton" type="submit">
                      Create invite
                    </button>
                  </form>
                </div>
                <form action={confirmEntityAlias} className="entityAliasForm">
                  <div className="formHeader">
                    <h3>Entity Alias</h3>
                    <small>
                      {data.entityAliases.total_count} confirmed · {data.entityAliasCandidates.total_count} candidates
                    </small>
                  </div>
                  <label className="wideField">
                    <span>Entity</span>
                    <select name="entity_ref" defaultValue={entityAliasOptions[0]?.ref || ""}>
                      {entityAliasOptions.map((option) => (
                        <option key={option.ref} value={option.ref}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Alias type</span>
                    <select name="alias_type" defaultValue="alias">
                      <option value="alias">alias</option>
                      <option value="domain">domain</option>
                      <option value="product">product</option>
                      <option value="parent_company">parent_company</option>
                    </select>
                  </label>
                  <label>
                    <span>Confidence</span>
                    <input name="confidence" type="number" min="0" max="1" step="0.01" defaultValue="1" />
                  </label>
                  <label className="wideField">
                    <span>Alias</span>
                    <input name="alias" defaultValue={defaultEntityAlias} />
                  </label>
                  <label className="wideField">
                    <span>Notes</span>
                    <input name="notes" defaultValue="Runtime entity alias confirmation for parser disambiguation" />
                  </label>
                  <input type="hidden" name="confirmed_by" value="runtime-console" />
                  <button className="actionButton" type="submit" disabled={!entityAliasOptions.length}>
                    Confirm alias
                  </button>
                </form>
                {visibleAliasCandidates.length ? (
                  <div className="aliasBatchQueue">
                    <div className="formHeader">
                      <h3>Bulk Alias Review Queue</h3>
                      <small>
                        {visibleAliasCandidates.length} visible candidates · entity_alias_confirm_batch_v1 ·
                        entity_alias_candidate_review_batch_v1
                      </small>
                    </div>
                    <p>
                      Confirm writes one entity_alias_confirmed audit event per alias and returns entity_alias_batch_confirmed.
                      Batch review writes entity_alias_candidate_review_recorded per candidate and returns
                      entity_alias_candidate_batch_reviewed.
                    </p>
                    <form action={confirmEntityAliasBatch} className="aliasBatchActions">
                      {visibleAliasCandidates.map((record) => (
                        <input
                          key={`batch-${record.candidate.id}`}
                          type="hidden"
                          name="candidate"
                          value={JSON.stringify({
                            entity_id: record.candidate.entity_id,
                            entity_kind: record.candidate.entity_kind,
                            alias: record.candidate.alias,
                            alias_type: record.candidate.alias_type,
                            confidence: record.candidate.confidence || 0.7,
                            notes: `Batch confirm generated alias candidate from ${record.candidate.source}${
                              record.candidate.evidence_count ? ` with ${record.candidate.evidence_count} evidence rows` : ""
                            }`
                          })}
                        />
                      ))}
                      <input type="hidden" name="confirmed_by" value="runtime-console" />
                      <input
                        type="hidden"
                        name="notes"
                        value="Batch entity alias confirmation for parser disambiguation review queue"
                      />
                      <button className="actionButton" type="submit">
                        Confirm visible candidates
                      </button>
                    </form>
                    <form action={reviewEntityAliasCandidatesBatch} className="aliasBatchActions">
                      {visibleAliasCandidates.map((record) => (
                        <input
                          key={`batch-review-${record.candidate.id}`}
                          type="hidden"
                          name="candidate_review"
                          value={JSON.stringify({
                            project_id: record.entity.project_id,
                            candidate_id: record.candidate.id,
                            entity_id: record.candidate.entity_id,
                            entity_kind: record.candidate.entity_kind,
                            alias: record.candidate.alias,
                            alias_type: record.candidate.alias_type,
                            source: record.candidate.source,
                            confidence: record.candidate.confidence || 0.7,
                            evidence_answer_run_ids: record.candidate.evidence_answer_run_ids || [],
                            evidence_urls: record.candidate.evidence_urls || []
                          })}
                        />
                      ))}
                      <input type="hidden" name="decision" value="needs_review" />
                      <input type="hidden" name="reviewed_by" value="runtime-console" />
                      <input
                        type="hidden"
                        name="notes"
                        value="Batch mark generated alias candidates as needs review"
                      />
                      <button className="actionButton" type="submit">
                        Mark visible needs review
                      </button>
                    </form>
                    <form action={reviewEntityAliasCandidatesBatch} className="aliasBatchActions">
                      {visibleAliasCandidates.map((record) => (
                        <input
                          key={`batch-reject-${record.candidate.id}`}
                          type="hidden"
                          name="candidate_review"
                          value={JSON.stringify({
                            project_id: record.entity.project_id,
                            candidate_id: record.candidate.id,
                            entity_id: record.candidate.entity_id,
                            entity_kind: record.candidate.entity_kind,
                            alias: record.candidate.alias,
                            alias_type: record.candidate.alias_type,
                            source: record.candidate.source,
                            confidence: record.candidate.confidence || 0.7,
                            evidence_answer_run_ids: record.candidate.evidence_answer_run_ids || [],
                            evidence_urls: record.candidate.evidence_urls || []
                          })}
                        />
                      ))}
                      <input type="hidden" name="decision" value="rejected" />
                      <input type="hidden" name="reviewed_by" value="runtime-console" />
                      <input
                        type="hidden"
                        name="notes"
                        value="Batch reject generated alias candidates from the visible review queue"
                      />
                      <button className="actionButton" type="submit">
                        Reject visible candidates
                      </button>
                    </form>
                  </div>
                ) : null}
                {visibleAliasCandidates.length ? (
                  <ul className="plainList">
                    {visibleAliasCandidates.map((record) => (
                      <li key={record.candidate.id}>
                        <strong>
                          Candidate · {record.candidate.alias_type} · {record.entity.entity_kind}
                        </strong>
                        <span>{record.candidate.alias}</span>
                        <small>
                          {record.entity.canonical_name} · {record.candidate.source} · confidence{" "}
                          {num(record.candidate.confidence)}
                          {record.candidate.evidence_count ? ` · evidence rows ${record.candidate.evidence_count}` : ""}
                          {record.candidate.evidence_answer_run_ids?.[0]
                            ? ` · answer run ${record.candidate.evidence_answer_run_ids[0]}`
                            : ""}
                          {record.candidate.latest_review?.decision
                            ? ` · review ${record.candidate.latest_review.decision}`
                            : ""}
                        </small>
                        <form action={confirmEntityAlias} className="inlineAliasForm">
                          <input
                            type="hidden"
                            name="entity_ref"
                            value={`${record.candidate.entity_kind}:${record.candidate.entity_id}`}
                          />
                          <input type="hidden" name="alias" value={record.candidate.alias} />
                          <input type="hidden" name="alias_type" value={record.candidate.alias_type} />
                          <input type="hidden" name="confidence" value={String(record.candidate.confidence || 0.7)} />
                          <input type="hidden" name="confirmed_by" value="runtime-console" />
                          <input
                            type="hidden"
                            name="notes"
                            value={`Confirm generated alias candidate from ${record.candidate.source}${
                              record.candidate.evidence_count ? ` with ${record.candidate.evidence_count} evidence rows` : ""
                            }`}
                          />
                          <button className="actionButton compactAction" type="submit">
                            Confirm candidate
                          </button>
                        </form>
                        {["needs_review", "rejected"].map((decision) => (
                          <form action={reviewEntityAliasCandidate} className="inlineAliasForm" key={decision}>
                            <input type="hidden" name="project_id" value={record.entity.project_id} />
                            <input type="hidden" name="candidate_id" value={record.candidate.id} />
                            <input type="hidden" name="entity_id" value={record.candidate.entity_id} />
                            <input type="hidden" name="entity_kind" value={record.candidate.entity_kind} />
                            <input type="hidden" name="alias" value={record.candidate.alias} />
                            <input type="hidden" name="alias_type" value={record.candidate.alias_type} />
                            <input type="hidden" name="source" value={record.candidate.source} />
                            <input type="hidden" name="confidence" value={String(record.candidate.confidence || 0.7)} />
                            <input
                              type="hidden"
                              name="evidence_answer_run_ids"
                              value={(record.candidate.evidence_answer_run_ids || []).join(",")}
                            />
                            <input
                              type="hidden"
                              name="evidence_urls"
                              value={(record.candidate.evidence_urls || []).join("\n")}
                            />
                            <input type="hidden" name="decision" value={decision} />
                            <input type="hidden" name="reviewed_by" value="runtime-console" />
                            <input
                              type="hidden"
                              name="reason"
                              value={`Alias candidate ${decision} from Runtime Console`}
                            />
                            <input
                              type="hidden"
                              name="notes"
                              value={`Record ${decision} decision for generated alias candidate ${record.candidate.alias}`}
                            />
                            <button className="actionButton compactAction" type="submit">
                              {decision === "rejected" ? "Reject candidate" : "Needs review"}
                            </button>
                          </form>
                        ))}
                      </li>
	                    ))}
	                  </ul>
	                ) : null}
	                <div className="aliasBatchQueue">
	                  <div className="formHeader">
	                    <h3>Alias Reviewer Workbench</h3>
	                    <small>
	                      reviewer {data.entityAliasAssignmentWorkbench.reviewer_id || "all"} ·{" "}
	                      {data.entityAliasAssignmentWorkbench.total_count} active reviews ·{" "}
	                      {paths.entityAliasAssignmentWorkbench}
	                    </small>
	                  </div>
	                  <div className="facts aliasAssignmentStats" aria-label="Alias Reviewer Workbench Stats">
	                    <div>
	                      <span>Active</span>
	                      <strong>{data.entityAliasAssignmentWorkbench.active_count}</strong>
	                    </div>
	                    <div>
	                      <span>Overdue</span>
	                      <strong>{data.entityAliasAssignmentWorkbench.overdue_count}</strong>
	                    </div>
	                    <div>
	                      <span>Due soon</span>
	                      <strong>{data.entityAliasAssignmentWorkbench.due_soon_count}</strong>
	                    </div>
	                    <div>
	                      <span>Escalated</span>
	                      <strong>{data.entityAliasAssignmentWorkbench.escalated_count}</strong>
	                    </div>
	                    <div>
	                      <span>Blocked</span>
	                      <strong>{data.entityAliasAssignmentWorkbench.blocked_count}</strong>
	                    </div>
	                  </div>
	                  <small>
	                    workbench: {data.entityAliasAssignmentWorkbench.method_version} · status_counts{" "}
	                    {JSON.stringify(data.entityAliasAssignmentWorkbench.status_counts)} · priority_counts{" "}
	                    {JSON.stringify(data.entityAliasAssignmentWorkbench.priority_counts)}
	                    {data.entityAliasAssignmentWorkbench.next_due_at
	                      ? ` · next due ${dateText(data.entityAliasAssignmentWorkbench.next_due_at)}`
	                      : " · no next due"}{" "}
		                    · audit entity_alias_candidate_review_recorded /
		                    entity_alias_candidate_assignment_actioned /
		                    entity_alias_candidate_assignment_batch_actioned /
		                    entity_alias_candidate_assignment_reassigned
		                  </small>
		                  {data.entityAliasAssignmentWorkbench.records.length ? (
		                    <div className="inlineActions">
		                      {["claim", "release"].map((action) => (
		                        <form
		                          action={actionEntityAliasCandidateAssignmentsBatch}
		                          className="inlineAliasForm"
		                          key={`batch-${action}`}
		                        >
		                          <input type="hidden" name="project_id" value={selectedProjectId || ""} />
		                          <input type="hidden" name="action" value={action} />
		                          <input type="hidden" name="updated_by" value="runtime-console" />
		                          <input type="hidden" name="continue_on_error" value="true" />
		                          <input
		                            type="hidden"
		                            name="note"
		                            value={`Batch ${action} visible alias reviewer workbench records from Runtime Console`}
		                          />
		                          {data.entityAliasAssignmentWorkbench.records.map((record) => (
		                            <input
		                              key={`${action}-${record.review.candidate_id}`}
		                              type="hidden"
		                              name="candidate_id"
		                              value={record.review.candidate_id}
		                            />
		                          ))}
		                          <button className="actionButton compactAction" type="submit" disabled={!selectedProjectId}>
		                            {action === "claim" ? "Claim workbench records" : "Release workbench records"}
		                          </button>
		                          <small>{endpoints.entityAliasAssignmentBatchAction}</small>
		                        </form>
		                      ))}
		                    </div>
		                  ) : null}
		                  {data.entityAliasAssignmentWorkbench.records.length ? (
		                    <ul className="plainList compactList">
	                      {data.entityAliasAssignmentWorkbench.records.slice(0, 4).map((record) => (
	                        <li key={`workbench-${record.review.id}`}>
	                          <strong>
	                            {record.review.alias} · {record.review.assignment_status || "unassigned"} ·{" "}
	                            {record.review.priority || "normal"}
	                          </strong>
	                          <span>{record.review.assigned_to || "unassigned"}</span>
	                          <small>
	                            candidate {record.review.candidate_id} · due{" "}
	                            {record.review.due_at ? dateText(record.review.due_at) : "not set"} · audit{" "}
	                            {record.audit_events[0]?.event_type || "none"}
	                          </small>
	                        </li>
	                      ))}
	                    </ul>
	                  ) : (
	                    <small>No active reviewer workbench records found for runtime-console.</small>
	                  )}
	                </div>
	                <div className="aliasBatchQueue">
	                  <div className="formHeader">
	                    <h3>Alias Reviewer Workload</h3>
	                    <small>
	                      {data.entityAliasAssignmentWorkload.total_active_count} active reviews ·{" "}
	                      {data.entityAliasAssignmentWorkload.reviewer_count} reviewers ·{" "}
	                      {paths.entityAliasAssignmentWorkload}
	                    </small>
	                  </div>
	                  <div className="facts aliasAssignmentStats" aria-label="Alias Reviewer Workload Stats">
	                    <div>
	                      <span>Unassigned</span>
	                      <strong>{data.entityAliasAssignmentWorkload.unassigned_count}</strong>
	                    </div>
	                    <div>
	                      <span>Overdue</span>
	                      <strong>{data.entityAliasAssignmentWorkload.overdue_count}</strong>
	                    </div>
	                    <div>
	                      <span>Due soon</span>
	                      <strong>{data.entityAliasAssignmentWorkload.due_soon_count}</strong>
	                    </div>
	                    <div>
	                      <span>Escalated</span>
	                      <strong>{data.entityAliasAssignmentWorkload.escalated_count}</strong>
	                    </div>
	                    <div>
	                      <span>Blocked</span>
	                      <strong>{data.entityAliasAssignmentWorkload.blocked_count}</strong>
	                    </div>
	                  </div>
	                  <small>
	                    workload: {data.entityAliasAssignmentWorkload.method_version} · active statuses{" "}
	                    {data.entityAliasAssignmentWorkload.active_statuses.join(", ")} · reviewer_loads sorted by
	                    unassigned, escalated, overdue, urgent, active count
	                  </small>
	                  {data.entityAliasAssignmentWorkload.reviewer_loads.length ? (
	                    <ul className="plainList compactList">
	                      {data.entityAliasAssignmentWorkload.reviewer_loads.slice(0, 5).map((load) => (
	                        <li key={`workload-${load.reviewer_id}`}>
	                          <strong>
	                            {load.reviewer_id} · {load.active_count} active · {load.urgent_count} urgent
	                          </strong>
	                          <span>
	                            overdue {load.overdue_count} · due soon {load.due_soon_count} · escalated{" "}
	                            {load.escalated_count} · blocked {load.blocked_count}
	                          </span>
	                          <small>
	                            next due {load.next_due_at ? dateText(load.next_due_at) : "not set"} · status_counts{" "}
	                            {JSON.stringify(load.status_counts)} · priority_counts{" "}
	                            {JSON.stringify(load.priority_counts)}
	                          </small>
	                        </li>
	                      ))}
	                    </ul>
	                  ) : (
	                    <small>No active reviewer workload records found.</small>
	                  )}
	                </div>
	                <div className="aliasBatchQueue">
	                  <div className="formHeader">
	                    <h3>Alias Assignment Dispatch Plan</h3>
	                    <small>
	                      {data.entityAliasAssignmentDispatchPlan.planned_assignment_count} planned ·{" "}
	                      {data.entityAliasAssignmentDispatchPlan.skipped_count} skipped ·{" "}
	                      {paths.entityAliasAssignmentDispatchPlan}
	                    </small>
	                  </div>
	                  <div className="facts aliasAssignmentStats" aria-label="Alias Assignment Dispatch Plan Stats">
	                    <div>
	                      <span>Candidates</span>
	                      <strong>{data.entityAliasAssignmentDispatchPlan.candidate_count}</strong>
	                    </div>
	                    <div>
	                      <span>Planned</span>
	                      <strong>{data.entityAliasAssignmentDispatchPlan.planned_assignment_count}</strong>
	                    </div>
	                    <div>
	                      <span>Skipped</span>
	                      <strong>{data.entityAliasAssignmentDispatchPlan.skipped_count}</strong>
	                    </div>
	                    <div>
	                      <span>Reviewers</span>
	                      <strong>{data.entityAliasAssignmentDispatchPlan.reviewer_ids.length}</strong>
	                    </div>
	                    <div>
	                      <span>Capacity</span>
	                      <strong>{data.entityAliasAssignmentDispatchPlan.max_per_reviewer}</strong>
	                    </div>
	                  </div>
	                  <small>
	                    dispatch plan: {data.entityAliasAssignmentDispatchPlan.method_version} · dry_run{" "}
	                    {data.entityAliasAssignmentDispatchPlan.dry_run ? "yes" : "no"} · strategy{" "}
	                    {data.entityAliasAssignmentDispatchPlan.strategy} · include{" "}
	                    {data.entityAliasAssignmentDispatchPlan.include_statuses.join(", ")} · apply{" "}
	                    {paths.entityAliasAssignmentDispatchApply} · audit
	                    entity_alias_assignment_dispatch_plan_applied /
	                    entity_alias_candidate_assignment_dispatch_applied
	                  </small>
	                  <form action={applyEntityAliasAssignmentDispatchPlan} className="inlineForm">
	                    <input type="hidden" name="project_id" value={selectedProjectId || ""} />
	                    <input
	                      type="hidden"
	                      name="include_statuses"
	                      value={data.entityAliasAssignmentDispatchPlan.include_statuses.join(",")}
	                    />
	                    <input
	                      type="hidden"
	                      name="reviewer_ids"
	                      value={data.entityAliasAssignmentDispatchPlan.reviewer_ids.join(",")}
	                    />
	                    <input
	                      type="hidden"
	                      name="max_per_reviewer"
	                      value={String(data.entityAliasAssignmentDispatchPlan.max_per_reviewer)}
	                    />
	                    <input type="hidden" name="limit" value="20" />
	                    <input type="hidden" name="applied_by" value="runtime-console" />
	                    <input type="hidden" name="assignment_status" value="assigned" />
	                    <input
	                      type="hidden"
	                      name="assignment_note"
	                      value="Apply Runtime Console alias assignment dispatch plan"
	                    />
	                    <input
	                      type="hidden"
	                      name="reason"
	                      value="Explicit Runtime Console apply for alias assignment dispatch plan"
	                    />
	                    <input type="hidden" name="continue_on_error" value="true" />
	                    <button
	                      type="submit"
	                      disabled={!selectedProjectId || data.entityAliasAssignmentDispatchPlan.planned_assignment_count < 1}
	                    >
	                      Apply dispatch plan
	                    </button>
	                    <small>{endpoints.entityAliasAssignmentDispatchApply}</small>
	                  </form>
	                  {data.entityAliasAssignmentDispatchPlan.reviewer_loads.length ? (
	                    <ul className="plainList compactList">
	                      {data.entityAliasAssignmentDispatchPlan.reviewer_loads.slice(0, 4).map((load) => (
	                        <li key={`dispatch-load-${load.reviewer_id}`}>
	                          <strong>
	                            {load.reviewer_id} · planned {load.planned_assignment_count}
	                          </strong>
	                          <span>
	                            current {load.current_active_count} · after plan {load.planned_active_count} · remaining{" "}
	                            {load.capacity_remaining}
	                          </span>
	                          <small>{load.over_capacity ? "over capacity before dispatch" : "within capacity"}</small>
	                        </li>
	                      ))}
	                    </ul>
	                  ) : null}
	                  {data.entityAliasAssignmentDispatchPlan.proposed_assignments.length ? (
	                    <ul className="plainList compactList">
	                      {data.entityAliasAssignmentDispatchPlan.proposed_assignments.slice(0, 5).map((item) => (
	                        <li key={`dispatch-${item.candidate_id}-${item.order}`}>
	                          <strong>
	                            {item.alias || item.candidate_id}{" "}
	                            {"->"} {item.recommended_assigned_to}
	                          </strong>
	                          <span>
	                            {item.current_assignment_status || "unknown"} · {item.priority || "normal"} ·{" "}
	                            {item.due_at ? dateText(item.due_at) : "no due date"}
	                          </span>
	                          <small>{item.reason}</small>
	                        </li>
	                      ))}
	                    </ul>
	                  ) : (
	                    <small>No dispatch assignments planned.</small>
	                  )}
	                </div>
	                {visibleAliasAssignmentQueue.length ? (
	                  <div className="aliasBatchQueue">
                    <div className="formHeader">
                      <h3>Alias Candidate Assignment Queue</h3>
                      <small>
                        {data.entityAliasAssignmentQueue.total_count} assigned reviews · assigned_to /
                        assignment_status / priority / due_before filters · {paths.entityAliasAssignmentQueue}
                      </small>
                    </div>
                    <div className="facts aliasAssignmentStats" aria-label="Alias Assignment Queue Stats">
                      <div>
                        <span>Total</span>
                        <strong>{data.entityAliasAssignmentStats.total_count}</strong>
                      </div>
                      <div>
                        <span>Active</span>
                        <strong>{data.entityAliasAssignmentStats.active_count}</strong>
                      </div>
                      <div>
                        <span>Overdue</span>
                        <strong>{data.entityAliasAssignmentStats.overdue_count}</strong>
                      </div>
                      <div>
                        <span>Due soon</span>
                        <strong>{data.entityAliasAssignmentStats.due_soon_count}</strong>
                      </div>
                      <div>
                        <span>Unassigned</span>
                        <strong>{data.entityAliasAssignmentStats.unassigned_count}</strong>
                      </div>
                    </div>
                    <small>
                      stats: {paths.entityAliasAssignmentStats} ·{" "}
                      {data.entityAliasAssignmentStats.method_version} · status_counts{" "}
                      {JSON.stringify(data.entityAliasAssignmentStats.status_counts)} · priority_counts{" "}
                      {JSON.stringify(data.entityAliasAssignmentStats.priority_counts)}
                      {` · active statuses ${data.entityAliasAssignmentStats.active_statuses.join(", ")}`}
                      {data.entityAliasAssignmentStats.next_due_at
                        ? ` · next due ${dateText(data.entityAliasAssignmentStats.next_due_at)}`
                        : " · no next due"}{" "}
                      · actions: {paths.entityAliasAssignmentAction} · audit entity_alias_candidate_assignment_actioned /
                      entity_alias_candidate_assignment_escalated / entity_alias_candidate_assignment_reassigned
                    </small>
                    <form action={enqueueEntityAliasAssignmentNotifications} className="inlineAliasForm">
                      <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                      <input type="hidden" name="created_by" value="runtime-console" />
                      <input
                        type="hidden"
                        name="reason"
                        value="Queue overdue entity alias assignment notifications from console"
                      />
                      <button
                        className="actionButton compactAction"
                        type="submit"
                        disabled={!selectedProjectId || data.entityAliasAssignmentStats.overdue_count < 1}
                      >
                        Queue overdue assignment notifications
                      </button>
                      <small>{paths.entityAliasAssignmentNotifications}</small>
                    </form>
                    <form action={escalateEntityAliasAssignmentReviews} className="inlineAliasForm">
                      <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                      <input type="hidden" name="escalated_by" value="runtime-console" />
                      <input
                        type="hidden"
                        name="reason"
                        value="Escalate overdue entity alias assignment reviews from console"
                      />
                      <button
                        className="actionButton compactAction"
                        type="submit"
                        disabled={!selectedProjectId || data.entityAliasAssignmentStats.overdue_count < 1}
                      >
                        Escalate overdue assignments
                      </button>
                      <small>{paths.entityAliasAssignmentEscalations}</small>
                    </form>
                    <form action={reassignEntityAliasAssignmentReviews} className="inlineAliasForm">
                      <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                      <input type="hidden" name="reassigned_by" value="runtime-console" />
                      <input type="hidden" name="from_assignment_status" value="escalated" />
                      <input type="hidden" name="assignment_status" value="assigned" />
                      <input type="hidden" name="priority" value="high" />
                      <input type="hidden" name="limit" value="50" />
                      <input
                        type="hidden"
                        name="assignment_note"
                        value="Reassign escalated alias reviews from Runtime Console"
                      />
                      <input
                        type="hidden"
                        name="reason"
                        value="Bulk reassign escalated entity alias assignment reviews from console"
                      />
                      <input
                        aria-label="Reassign alias reviews to"
                        name="assigned_to"
                        placeholder="reviewer@example.com"
                      />
                      <button
                        className="actionButton compactAction"
                        type="submit"
                        disabled={!selectedProjectId || !data.entityAliasAssignmentStats.status_counts.escalated}
                      >
                        Reassign escalated reviews
                      </button>
                      <small>{paths.entityAliasAssignmentReassignments}</small>
                    </form>
                    <ul className="plainList">
                      {visibleAliasAssignmentQueue.map((record) => {
                        const review = record.review;
                        return (
                          <li key={`assignment-${review.id}`}>
                            <strong>
                              {review.assignment_status || "assigned"} · {review.priority || "normal"} ·{" "}
                              {review.assigned_to || "unassigned"}
                            </strong>
                            <span>{review.alias}</span>
                            <small>
                              {review.entity_kind} · {review.decision} · candidate {shortId(review.candidate_id)}
                              {review.due_at ? ` · due ${dateText(review.due_at)}` : " · no due date"} ·{" "}
                              {record.audit_events[0]?.event_type || "no assignment audit"}
                            </small>
                            <form action={actionEntityAliasCandidateAssignment} className="inlineAliasForm">
                              <input type="hidden" name="project_id" value={review.project_id} />
                              <input type="hidden" name="candidate_id" value={review.candidate_id} />
                              <input type="hidden" name="action" value="claim" />
                              <input type="hidden" name="updated_by" value="runtime-console" />
                              <input
                                type="hidden"
                                name="note"
                                value={`Claim ${review.alias} alias candidate review from Runtime Console`}
                              />
                              <button className="actionButton compactAction" type="submit">
                                Claim review
                              </button>
                            </form>
                            <form action={actionEntityAliasCandidateAssignment} className="inlineAliasForm">
                              <input type="hidden" name="project_id" value={review.project_id} />
                              <input type="hidden" name="candidate_id" value={review.candidate_id} />
                              <input type="hidden" name="action" value="release" />
                              <input type="hidden" name="updated_by" value="runtime-console" />
                              <input
                                type="hidden"
                                name="note"
                                value={`Release ${review.alias} alias candidate review from Runtime Console`}
                              />
                              <button className="actionButton compactAction" type="submit" disabled={!review.assigned_to}>
                                Release review
                              </button>
                            </form>
                            {["in_progress", "blocked", "completed"].map((status) => (
                              <form action={assignEntityAliasCandidateReview} className="inlineAliasForm" key={status}>
                                <input type="hidden" name="project_id" value={review.project_id} />
                                <input type="hidden" name="candidate_id" value={review.candidate_id} />
                                <input
                                  type="hidden"
                                  name="assigned_to"
                                  value={review.assigned_to || "runtime-console"}
                                />
                                <input type="hidden" name="assigned_by" value="runtime-console" />
                                <input type="hidden" name="assignment_status" value={status} />
                                <input type="hidden" name="priority" value={review.priority || "normal"} />
                                <input type="hidden" name="due_at" value={review.due_at || ""} />
                                <input
                                  type="hidden"
                                  name="assignment_note"
                                  value={`Mark ${review.alias} assignment ${status}`}
                                />
                                <input
                                  type="hidden"
                                  name="reason"
                                  value={`Alias candidate assignment status changed to ${status} from Runtime Console`}
                                />
                                <button className="actionButton compactAction" type="submit">
                                  {status === "in_progress" ? "Start review" : status === "blocked" ? "Block review" : "Complete review"}
                                </button>
                              </form>
                            ))}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ) : null}
                {visibleAliasCandidateReviews.length ? (
                  <div className="aliasBatchQueue">
                    <div className="formHeader">
                      <h3>Alias Candidate Review History</h3>
                      <small>
                        {data.entityAliasCandidateReviews.total_count} stored reviews ·{" "}
                        /v1/entity-aliases/runtime/candidates/reviews
                      </small>
                    </div>
                    <ul className="plainList">
                      {visibleAliasCandidateReviews.map((record) => {
                        const review = record.review;
                        return (
                          <li key={review.id}>
                            <strong>
                              {review.decision} · {review.alias_type} · {review.entity_kind}
                            </strong>
                            <span>{review.alias}</span>
                            <small>
                              {review.source || "manual"} · candidate {shortId(review.candidate_id)} ·{" "}
                              {dateText(review.updated_at || review.created_at)} ·{" "}
                              {record.audit_events[0]?.event_type || "no review audit"}
                              {review.assigned_to
                                ? ` · assigned ${review.assigned_to} / ${review.assignment_status || "assigned"} / ${
                                    review.priority || "normal"
                                  }`
                                : " · unassigned"}
                              {review.due_at ? ` · due ${dateText(review.due_at)}` : ""}
                            </small>
                            <form action={assignEntityAliasCandidateReview} className="inlineAliasForm">
                              <input type="hidden" name="project_id" value={review.project_id} />
                              <input type="hidden" name="candidate_id" value={review.candidate_id} />
                              <input type="hidden" name="assigned_by" value="runtime-console" />
                              <input type="hidden" name="assignment_status" value="assigned" />
                              <input
                                type="hidden"
                                name="reason"
                                value="Assign alias candidate review from Runtime Console history"
                              />
                              <label>
                                <span>Assignee</span>
                                <input name="assigned_to" defaultValue={review.assigned_to || "runtime-console"} />
                              </label>
                              <label>
                                <span>Priority</span>
                                <select name="priority" defaultValue={review.priority || "normal"}>
                                  <option value="low">low</option>
                                  <option value="normal">normal</option>
                                  <option value="high">high</option>
                                  <option value="urgent">urgent</option>
                                </select>
                              </label>
                              <label>
                                <span>Due</span>
                                <input name="due_at" type="datetime-local" />
                              </label>
                              <input
                                type="hidden"
                                name="assignment_note"
                                value={`Assign ${review.alias} alias candidate review`}
                              />
                              <button className="actionButton compactAction" type="submit">
                                Assign review
                              </button>
                            </form>
                            {review.decision === "rejected" ? (
                              <form action={reviewEntityAliasCandidate} className="inlineAliasForm">
                                <input type="hidden" name="project_id" value={review.project_id} />
                                <input type="hidden" name="candidate_id" value={review.candidate_id} />
                                <input type="hidden" name="entity_id" value={review.entity_id} />
                                <input type="hidden" name="entity_kind" value={review.entity_kind} />
                                <input type="hidden" name="alias" value={review.alias} />
                                <input type="hidden" name="alias_type" value={review.alias_type} />
                                <input type="hidden" name="source" value={review.source || ""} />
                                <input type="hidden" name="confidence" value={String(review.confidence ?? 0.7)} />
                                <input
                                  type="hidden"
                                  name="evidence_answer_run_ids"
                                  value={(review.evidence_answer_run_ids || []).join(",")}
                                />
                                <input
                                  type="hidden"
                                  name="evidence_urls"
                                  value={(review.evidence_urls || []).join("\n")}
                                />
                                <input type="hidden" name="decision" value="needs_review" />
                                <input type="hidden" name="reviewed_by" value="runtime-console" />
                                <input
                                  type="hidden"
                                  name="reason"
                                  value="Restore rejected alias candidate from review history"
                                />
                                <input
                                  type="hidden"
                                  name="notes"
                                  value={`Restore ${review.alias} to needs_review from alias candidate review history`}
                                />
                                <button className="actionButton compactAction" type="submit">
                                  Restore to needs review
                                </button>
                              </form>
                            ) : null}
                            {review.decision !== "approved" ? (
                              <form action={reviewEntityAliasCandidate} className="inlineAliasForm">
                                <input type="hidden" name="project_id" value={review.project_id} />
                                <input type="hidden" name="candidate_id" value={review.candidate_id} />
                                <input type="hidden" name="entity_id" value={review.entity_id} />
                                <input type="hidden" name="entity_kind" value={review.entity_kind} />
                                <input type="hidden" name="alias" value={review.alias} />
                                <input type="hidden" name="alias_type" value={review.alias_type} />
                                <input type="hidden" name="source" value={review.source || ""} />
                                <input type="hidden" name="confidence" value={String(review.confidence ?? 0.7)} />
                                <input
                                  type="hidden"
                                  name="evidence_answer_run_ids"
                                  value={(review.evidence_answer_run_ids || []).join(",")}
                                />
                                <input
                                  type="hidden"
                                  name="evidence_urls"
                                  value={(review.evidence_urls || []).join("\n")}
                                />
                                <input type="hidden" name="decision" value="approved" />
                                <input type="hidden" name="reviewed_by" value="runtime-console" />
                                <input
                                  type="hidden"
                                  name="reason"
                                  value="Approve alias candidate from review history"
                                />
                                <input
                                  type="hidden"
                                  name="notes"
                                  value={`Mark ${review.alias} approved from alias candidate review history`}
                                />
                                <button className="actionButton compactAction" type="submit">
                                  Mark approved
                                </button>
                              </form>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ) : null}
                {data.entityAliases.records.length ? (
                  <ul className="plainList">
                    {data.entityAliases.records.slice(0, 4).map((record) => (
                      <li key={record.entity_alias.id}>
                        <strong>
                          {record.entity_alias.alias_type} · {record.entity.entity_kind}
                        </strong>
                        <span>{record.entity_alias.alias}</span>
                        <small>
                          {record.entity.canonical_name} ·{" "}
                          {record.audit_events[0]?.event_type || "no alias audit"} ·{" "}
                          {record.audit_events[0]?.after_hash || "no hash"}
                        </small>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : (
              <EmptyState />
            )}
            <form action={createAuRuntimeProject} className="projectCreateForm">
              <div className="formHeader">
                <h3>Client Project</h3>
                <small>AU / DTC ecommerce / 100 prompts</small>
              </div>
              <label>
                <span>Tenant</span>
                <input name="tenant_name" defaultValue="Design Partner AU" />
              </label>
              <label>
                <span>Project</span>
                <input name="project_name" defaultValue="AU DTC Evidence Pilot" />
              </label>
              <label>
                <span>Brand</span>
                <input name="target_brand" defaultValue="ExampleBrand" />
              </label>
              <label>
                <span>Category</span>
                <input name="category" defaultValue="DTC ecommerce products" />
              </label>
              <label className="wideField">
                <span>Brand domains</span>
                <input name="brand_official_domains" defaultValue="examplebrand.example" />
              </label>
              <label className="wideField">
                <span>Product lines</span>
                <input name="brand_product_lines" defaultValue="Flagship product, Premium bundle" />
              </label>
              <label className="wideField">
                <span>Competitors</span>
                <textarea
                  name="competitors"
                  defaultValue={"Emma Sleep\nSleeping Duck\nEcosa\nIKEA Australia"}
                  rows={4}
                />
              </label>
              <input type="hidden" name="owner_user_id" value="runtime-console" />
              <button className="actionButton" type="submit">
                Create client project
              </button>
            </form>
            <form action={saveProjectBrandKit} className="brandKitForm">
              <div className="formHeader">
                <h3>Brand Kit</h3>
                <small>
                  {projectBrandKit
                    ? `${projectBrandKit.updated_by} · ${brandKitAudit?.event_type || "saved"}`
                    : "project-level white-label defaults"}
                </small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <label>
                <span>Client name</span>
                <input
                  name="client_name"
                  defaultValue={
                    projectBrandKit?.client_name ||
                    latestProject?.brand?.canonical_name ||
                    latestProject?.project.target_brand ||
                    "ExampleBrand AU"
                  }
                />
              </label>
              <label>
                <span>Prepared by</span>
                <input name="prepared_by" defaultValue={projectBrandKit?.prepared_by || "GENO SaaS AU"} />
              </label>
              <label className="wideField">
                <span>Logo URL</span>
                <input name="logo_url" defaultValue={whiteLabelLogoUrl} />
              </label>
              <label className="themeColorField">
                <span>Primary color</span>
                <input name="primary_color" type="color" defaultValue={whiteLabelPrimaryColor} />
              </label>
              <label className="themeColorField">
                <span>Secondary color</span>
                <input name="secondary_color" type="color" defaultValue={whiteLabelSecondaryColor} />
              </label>
              <label className="wideField">
                <span>Footer text</span>
                <textarea
                  name="footer_text"
                  defaultValue={whiteLabelFooterText}
                  rows={2}
                />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                Save brand kit
              </button>
            </form>
            <section className="themeEditorPreview" aria-label="advanced white-label theme editor">
              <div className="formHeader">
                <h3>Theme Editor</h3>
                <small>
                  {brandKitAudit?.method_version || "project_brand_kit_v1"} ·{" "}
                  {brandKitAudit?.after_hash ? `hash ${clipText(brandKitAudit.after_hash, 18)}` : "not saved"}
                </small>
              </div>
              <div className="themePreviewCard">
                <div className="themePreviewHeader" style={{ backgroundColor: whiteLabelPrimaryColor }}>
                  <span className="themeLogoMark" style={{ borderColor: whiteLabelSecondaryColor }}>
                    {whiteLabelClientName.slice(0, 2).toUpperCase()}
                  </span>
                  <div>
                    <strong>{whiteLabelClientName}</strong>
                    <span>{whiteLabelPreparedBy}</span>
                  </div>
                </div>
                <div className="themePreviewBody">
                  <h3>AU GEO Visibility Report</h3>
                  <p>{filterLabel} · {evidenceSort}</p>
                  <div className="themeMetricStrip">
                    <span style={{ borderColor: whiteLabelPrimaryColor }}>
                      Score {num(latestScore?.snapshot.final_score)}
                    </span>
                    <span style={{ borderColor: whiteLabelSecondaryColor }}>
                      Evidence {latestReport?.answer_runs.length || data.evidence.total_count}
                    </span>
                  </div>
                  <small>{whiteLabelFooterText}</small>
                </div>
              </div>
              <dl className="facts themePreviewFacts">
                <Fact label="Primary color" value={whiteLabelPrimaryColor} />
                <Fact label="Secondary color" value={whiteLabelSecondaryColor} />
                <Fact label="Logo source" value={whiteLabelLogoUrl} />
                <Fact
                  label="White-label path"
                  value={reportWhiteLabelPdfUrl?.replace(displayUrl, "") || "No white-label artifact"}
                />
                <Fact label="Template payload" value="client_name/prepared_by/logo_url/primary_color/secondary_color/footer_text" />
                <Fact label="Audit event" value={brandKitAudit?.event_type || "project_brand_kit_saved pending"} />
              </dl>
            </section>
            <form action={uploadProjectBrandLogo} className="brandKitForm">
              <div className="formHeader">
                <h3>Logo Upload</h3>
                <small>{projectBrandKit?.logo_url || "archive to object storage"}</small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <input type="hidden" name="uploaded_by" value="runtime-console" />
              <label className="wideField">
                <span>Logo file</span>
                <input name="brand_logo" type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,image/gif" />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                Upload logo
              </button>
              <p className="formHint">
                {data.brandKit?.audit_events[0]?.event_type === "project_brand_logo_uploaded"
                  ? `Last upload · ${data.brandKit.audit_events[0]?.method_version || "project_brand_logo_upload_v1"}`
                  : "Uploaded logo URI becomes the Brand Kit default for white-label PDF artifacts."}
              </p>
            </form>
            <section className="brandAssetLibrary" aria-label="white-label brand asset versions">
              <div className="formHeader">
                <h3>Brand Assets</h3>
                <small>{data.brandAssets.total_count} versions · {paths.brandAssets}</small>
              </div>
              {data.brandAssets.records.length ? (
                <ul className="plainList">
                  {data.brandAssets.records.map((asset) => (
                    <li key={asset.version_id}>
                      <strong>
                        {asset.is_active ? "Active logo" : "Logo version"} · {asset.source_filename || shortId(asset.version_id)}
                      </strong>
                      <span>{asset.asset_url}</span>
                      <small>
                        {asset.source_content_type || "content type pending"} · {shortId(asset.content_hash || asset.version_id)} ·{" "}
                        {asset.audit_event?.event_type || "project_brand_logo_uploaded"}
                      </small>
                      <form action={activateProjectBrandAssetVersion} className="assetActivateForm">
                        <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                        <input type="hidden" name="asset_url" value={asset.asset_url} />
                        <input type="hidden" name="activated_by" value="runtime-console" />
                        <input type="hidden" name="reason" value="Activate brand logo asset version" />
                        <button className="textButton" type="submit" disabled={!selectedProjectId || asset.is_active}>
                          Activate
                        </button>
                      </form>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState />
              )}
            </section>
            <form action={saveProjectBrandAsset} className="brandAssetForm">
              <div className="formHeader">
                <h3>Asset Register</h3>
                <small>project_brand_asset_library_v1 · {paths.brandAssetLibrary}</small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <input type="hidden" name="uploaded_by" value="runtime-console" />
              <label>
                <span>Asset type</span>
                <select name="asset_type" defaultValue="image">
                  <option value="image">image</option>
                  <option value="logo">logo</option>
                  <option value="pdf">pdf</option>
                  <option value="document">document</option>
                  <option value="template">template</option>
                </select>
              </label>
              <label>
                <span>Category</span>
                <input name="category" defaultValue="brand_creative" />
              </label>
              <label className="wideField">
                <span>Asset URL</span>
                <input name="asset_url" defaultValue={projectBrandKit?.logo_url || ""} />
              </label>
              <label className="wideField">
                <span>Preview URL</span>
                <input name="preview_url" placeholder="https://cdn.example.com/client/asset-preview.png" />
              </label>
              <label>
                <span>Filename</span>
                <input name="source_filename" defaultValue="client-asset" />
              </label>
              <label>
                <span>Content type</span>
                <input name="source_content_type" defaultValue="image/png" />
              </label>
              <label>
                <span>Content hash</span>
                <input name="content_hash" placeholder="sha256 or object hash" />
              </label>
              <label>
                <span>Storage version</span>
                <input name="storage_version" placeholder="etag/version/content hash" />
              </label>
              <label>
                <span>Status</span>
                <select name="status" defaultValue="active">
                  <option value="active">active</option>
                  <option value="draft">draft</option>
                  <option value="archived">archived</option>
                </select>
              </label>
              <label className="wideField">
                <span>Reason</span>
                <input name="reason" defaultValue="Register project brand asset for white-label delivery" />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                Register asset
              </button>
            </form>
            <section className="brandAssetLibrary" aria-label="project brand asset library">
              <div className="formHeader">
                <h3>Asset Library</h3>
                <small>
                  {data.brandAssetLibrary.total_count} assets · table project_brand_assets ·
                  project_brand_asset_scan_recorded
                </small>
              </div>
              {data.brandAssetLibrary.records.length ? (
                <ul className="plainList">
                  {data.brandAssetLibrary.records.map((record) => {
                    const assetAudit = record.audit_events[0];
                    return (
                      <li key={record.asset.id}>
                        <strong>
                          {record.asset.asset_type} · {record.asset.category} · {record.asset.status} · scan{" "}
                          {record.asset.scan_status || "pending"}
                        </strong>
                        <span>{record.asset.asset_url}</span>
                        {record.asset.preview_url ? (
                          <a className="inlineLink" href={record.asset.preview_url} target="_blank" rel="noreferrer">
                            Preview asset
                          </a>
                        ) : null}
                        <small>
                          {record.asset.source_filename || "filename pending"} ·{" "}
                          {record.asset.source_content_type || "content type pending"} ·{" "}
                          {shortId(record.asset.content_hash || record.asset.storage_version || record.asset.id)}
                        </small>
                        <small>
                          {assetAudit?.event_type || "project_brand_asset_registered pending"} ·{" "}
                          {assetAudit?.method_version || "project_brand_asset_library_v1"} ·{" "}
                          {dateText(record.asset.updated_at)}
                        </small>
                        <small>
                          {record.asset.scan_method_version || "manual_asset_scan_v1"} ·{" "}
                          {dateText(record.asset.scan_checked_at || undefined)}
                        </small>
                        <form action={updateProjectBrandAssetScanStatus} className="assetActivateForm">
                          <input type="hidden" name="asset_id" value={record.asset.id} />
                          <input type="hidden" name="scanned_by" value="runtime-console" />
                          <input type="hidden" name="scan_method_version" value="manual_asset_scan_v1" />
                          <input
                            type="hidden"
                            name="reason"
                            value="Record manual project brand asset scan gate status"
                          />
                          <select name="scan_status" defaultValue={record.asset.scan_status || "pending"}>
                            <option value="pending">pending</option>
                            <option value="passed">passed</option>
                            <option value="failed">failed</option>
                            <option value="skipped">skipped</option>
                          </select>
                          <input
                            name="scan_notes"
                            placeholder={record.asset.scan_notes || "scan notes"}
                            defaultValue={record.asset.scan_notes || ""}
                          />
                          <button className="textButton" type="submit" disabled={!selectedProjectId}>
                            Update scan
                          </button>
                        </form>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState />
              )}
            </section>
            <form action={saveScoreWeightConfig} className="brandKitForm">
              <div className="formHeader">
                <h3>Score Weights</h3>
                <small>
                  {scoreWeightConfig?.updated_by || "system-default"} · {scoreWeightAuditEvent} ·{" "}
                  {selectedFormulaVersion} · total {num(scoreWeightTotal)}
                </small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <label className="wideField">
                <span>Formula version</span>
                <select name="formula_version" defaultValue={selectedFormulaVersion}>
                  {scoreFormulaOptions.map((formula) => (
                    <option key={formula.formula_version} value={formula.formula_version}>
                      {formula.formula_version} · {formula.status}
                    </option>
                  ))}
                </select>
              </label>
              <dl className="facts contributionFacts">
                <Fact label="Formula catalog" value={paths.scoreFormulas} />
                <Fact label="Selected formula" value={selectedFormula.formula_version} />
                <Fact label="Snapshot formula" value={latestScore?.snapshot.formula_version || "no snapshot"} />
                <Fact label="Formula status" value={selectedFormula.status} />
                <Fact label="Supersedes" value={selectedFormula.supersedes || "none"} />
                <Fact label="Formula note" value={selectedFormula.description} />
              </dl>
              {scoreComponentNames.map((component) => (
                <label key={component}>
                  <span>{component}</span>
                  <input
                    name={component}
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    defaultValue={String(configuredScoreWeights[component] ?? defaultScoreWeights[component])}
                  />
                </label>
              ))}
              <label className="wideField">
                <span>Notes</span>
                <textarea
                  name="notes"
                  defaultValue={scoreWeightConfig?.notes || "Project-level scoring weight review"}
                  rows={2}
                />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                Save score weights
              </button>
            </form>
          </div>
        </Panel>

        <Panel title="Prompt Pack" subtitle={latestPrompt?.prompt_version || "No runtime prompts"}>
          {data.prompts.records.length ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Total prompts" value={data.prompts.total_count} />
                <Fact label="Loaded" value={data.prompts.records.length} />
                <Fact label="Intent types" value={promptIntentCount} />
                <Fact label="Cities" value={promptCityCount} />
                <Fact label="Brand" value={latestPrompt?.target_brand || "unknown"} />
                <Fact label="Language" value={latestPrompt?.language || "unknown"} />
              </dl>
              <ul className="plainList promptList">
                {data.prompts.records.slice(0, 5).map((prompt) => (
                  <li key={prompt.id}>
                    <strong>
                      {prompt.priority} · {prompt.intent_type} · {prompt.city}
                    </strong>
                    <span>{prompt.text}</span>
                    <small>
                      weight {num(prompt.intent_weight)} · {prompt.status} · {prompt.competitors.length} competitors
                    </small>
                  </li>
                ))}
              </ul>
              <form action={importRuntimePromptsCsv} className="promptImportForm">
                <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                <div className="formHeader">
                  <h3>Prompt CSV Import</h3>
                  <small>text,intent_type,city,priority,intent_weight</small>
                </div>
                <label className="wideField">
                  <span>CSV rows</span>
                  <textarea
                    name="csv_content"
                    defaultValue={
                      "text,intent_type,city,priority,intent_weight\n" +
                      `"Is ${latestProject?.project.target_brand || "ExampleBrand"} visible in Sydney AI recommendations?",brand_awareness,Sydney,1,0.9\n` +
                      `"Best ${latestProject?.project.category || "DTC ecommerce products"} for Melbourne shoppers",category_recommendation,Melbourne,2,1.0`
                    }
                    rows={5}
                  />
                </label>
                <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                  Import prompts
                </button>
              </form>
              <form action={importRuntimePromptsFile} className="promptImportForm">
                <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                <div className="formHeader">
                  <h3>Prompt File Import</h3>
                  <small>.csv or .xlsx · first worksheet</small>
                </div>
                <label>
                  <span>Prompt file</span>
                  <input
                    name="prompt_file"
                    type="file"
                    accept=".csv,.txt,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  />
                </label>
                <button className="actionButton" type="submit" disabled={!selectedProjectId}>
                  Import file
                </button>
              </form>
              <div className="detailBlock">
                <div className="sectionHeader">
                  <h3>Prompt Import History</h3>
                  <small>Import query {paths.promptImports}</small>
                </div>
                {data.promptImports.records.length ? (
                  <ul className="plainList">
                    {data.promptImports.records.map((record) => {
                      const item = record.prompt_import;
                      const audit = record.audit_events[0];
                      return (
                        <li key={item.id || `${item.source_format}-${item.created_at}`}>
                          <strong>
                            {item.source_format || "csv"} · {item.prompt_count || 0} prompts ·{" "}
                            {dateText(item.created_at || undefined)}
                          </strong>
                          <span>
                            {item.source_filename || "inline CSV"} · {item.source_content_type || "no content type"}
                          </span>
                          <small>
                            {audit?.event_type || "runtime_prompts_imported"} ·{" "}
                            {audit?.method_version || item.method_version || "no method version"} · hash{" "}
                            {clipText(item.csv_sha256 || item.after_hash || audit?.after_hash || "no hash", 16)}
                          </small>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="mutedText">No prompt imports recorded for this project.</p>
                )}
              </div>
              <form action={submitManualBackfill} className="manualBackfillForm">
                <input type="hidden" name="prompt_question_id" value={latestPrompt?.id || ""} />
                <div className="formHeader">
                  <h3>Manual Backfill</h3>
                  <small>{latestPrompt ? shortId(latestPrompt.id) : "no prompt"}</small>
                </div>
                <label>
                  <span>Platform</span>
                  <select name="platform" defaultValue="google">
                    <option value="google">google</option>
                    <option value="perplexity">perplexity</option>
                    <option value="chatgpt">chatgpt</option>
                    <option value="gemini">gemini</option>
                    <option value="bing_copilot">bing_copilot</option>
                    <option value="claude">claude</option>
                    <option value="youtube">youtube</option>
                    <option value="reddit">reddit</option>
                    <option value="productreview">productreview</option>
                  </select>
                </label>
                <label>
                  <span>Surface</span>
                  <select name="surface" defaultValue="google_ai_mode">
                    <option value="google_ai_mode">google_ai_mode</option>
                    <option value="google_aio">google_aio</option>
                    <option value="sonar">sonar</option>
                    <option value="chatgpt_search">chatgpt_search</option>
                    <option value="gemini_search">gemini_search</option>
                    <option value="copilot_search">copilot_search</option>
                    <option value="claude_search">claude_search</option>
                    <option value="youtube_search">youtube_search</option>
                    <option value="reddit_search">reddit_search</option>
                    <option value="productreview_reviews">productreview_reviews</option>
                  </select>
                </label>
                <label className="wideField">
                  <span>Answer text</span>
                  <textarea
                    name="answer_text"
                    defaultValue={`Manual backfill answer for: ${latestPrompt?.text || "selected prompt"}`}
                    rows={4}
                  />
                </label>
                <label className="wideField">
                  <span>Citation URLs</span>
                  <textarea
                    name="citation_urls"
                    defaultValue={"https://examplebrand.example/au/manual-backfill\nhttps://reviews.example/manual-backfill"}
                    rows={2}
                  />
                </label>
                <label>
                  <span>Screenshot URL</span>
                  <input name="screenshot_url" defaultValue="s3://manual-backfill/examplebrand-google-ai-mode.png" />
                </label>
                <label>
                  <span>HTML URL</span>
                  <input name="html_snapshot_url" defaultValue="s3://manual-backfill/examplebrand-google-ai-mode.html" />
                </label>
                <label className="wideField">
                  <span>Notes</span>
                  <input name="notes" defaultValue="Manual Google AI Mode backfill for auditable spike coverage" />
                </label>
                <input type="hidden" name="submitted_by" value="runtime-console" />
                <button className="actionButton" type="submit" disabled={!latestPrompt}>
                  Save backfill
                </button>
              </form>
              <form action={importManualBackfillCsv} className="manualBackfillForm">
                <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                <input type="hidden" name="submitted_by" value="runtime-console" />
                <div className="formHeader">
                  <h3>Manual Backfill CSV</h3>
                  <small>manual_backfill_csv_import_v1</small>
                </div>
                <label className="wideField">
                  <span>CSV rows</span>
                  <textarea
                    name="csv_content"
                    defaultValue={
                      "prompt_question_id,platform,surface,answer_text,citation_urls,screenshot_url,html_snapshot_url,sample_index,sample_size,device,notes\n" +
                      `${latestPrompt?.id || "prompt-question-id"},google,google_ai_mode,"Manual AI Mode sample 1 for ${
                        latestPrompt?.text || "selected prompt"
                      }","https://examplebrand.example/au/manual|https://reviews.example/manual",s3://manual-backfill/google-ai-mode-1.png,s3://manual-backfill/google-ai-mode-1.html,1,2,desktop,"Batch manual backfill for Google spike"\n` +
                      `${latestPrompt?.id || "prompt-question-id"},google,google_ai_mode,"Manual AI Mode sample 2 for ${
                        latestPrompt?.text || "selected prompt"
                      }","https://examplebrand.example/au/manual-2",s3://manual-backfill/google-ai-mode-2.png,s3://manual-backfill/google-ai-mode-2.html,2,2,desktop,"Batch manual backfill for Google spike"`
                    }
                    rows={6}
                  />
                </label>
                <label>
                  <span>Max rows</span>
                  <input name="max_rows" defaultValue="120" />
                </label>
                <label>
                  <span>Import note</span>
                  <input name="notes" defaultValue="Batch manual backfill import for auditable Google spike coverage" />
                </label>
                <button className="actionButton" type="submit" disabled={!selectedProjectId || !latestPrompt}>
                  Import backfill CSV
                </button>
              </form>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Question Detail"
          subtitle={`${coveredQuestionCount}/${questionDetailRows.length} covered · evidence window ${data.questionEvidence.records.length}/${data.questionEvidence.total_count}`}
          wide
        >
          {questionDetailRows.length ? (
            <div className="questionDetail">
              <dl className="facts questionSummaryFacts">
                <Fact label="Coverage" value={pct(questionCoverageRate)} />
                <Fact label="Covered" value={coveredQuestionCount} />
                <Fact label="Open gaps" value={questionGapRows.length} />
                <Fact label="Evidence window" value={`${data.questionEvidence.records.length}/${data.questionEvidence.total_count}`} />
                <Fact label="Question evidence query" value={paths.questionEvidence} />
                <Fact label="Status mix" value={formatCounts(questionStatusCounts)} />
              </dl>
              <div className="questionTable" role="table" aria-label="question detail coverage matrix">
                <div className="questionTableHeader" role="row">
                  <span>Question</span>
                  <span>Coverage</span>
                  <span>Runs</span>
                  <span>Platforms</span>
                  <span>Evidence</span>
                  <span>Latest</span>
                </div>
                {questionDetailRows.map((row) => (
                  <details className="questionRow" key={row.prompt.id} open={row.status !== "covered"}>
                    <summary>
                      <span>
                        <strong>{row.prompt.priority}</strong>
                        {row.prompt.intent_type} · {row.prompt.city}
                      </span>
                      <span className={`coverageBadge coverage-${row.status}`}>{row.gapLabel}</span>
                      <span>
                        {row.runCount} runs · {row.answerCount} answers
                      </span>
                      <span>{row.platforms.length ? row.platforms.join(", ") : "none"}</span>
                      <span>
                        {row.citationCount} citations · {row.assetCount} assets
                      </span>
                      <span>{dateText(row.latestRun?.answer_run.collected_at)}</span>
                    </summary>
                    <div className="questionRowBody">
                      <p className="prompt">{row.prompt.text}</p>
                      <dl className="facts questionFacts">
                        <Fact label="Prompt ID" value={shortId(row.prompt.id)} />
                        <Fact label="Language" value={row.prompt.language} />
                        <Fact label="Target brand" value={row.prompt.target_brand} />
                        <Fact label="Competitors" value={row.prompt.competitors.length} />
                        <Fact label="Trigger rate" value={pct(row.runCount ? row.triggeredCount / row.runCount : 0)} />
                        <Fact label="Answer rate" value={pct(row.runCount ? row.answerCount / row.runCount : 0)} />
                        <Fact label="Missing platforms" value={row.missingPlatforms.length ? row.missingPlatforms.join(", ") : "none"} />
                        <Fact label="Cities observed" value={row.cities.length ? row.cities.join(", ") : "none"} />
                        <Fact label="Access methods" value={row.accessMethods.length ? row.accessMethods.join(", ") : "none"} />
                        <Fact label="Surface mix" value={formatCounts(row.surfaceCounts)} />
                        <Fact label="Run status mix" value={formatCounts(row.statusCounts)} />
                        <Fact label="Cost" value={num(row.totalCost)} />
                        <Fact label="Avg duration" value={`${row.averageDurationMs} ms`} />
                        <Fact label="Audit events" value={row.auditCount} />
                      </dl>
                      {row.evidenceRuns.length ? (
                        <ul className="plainList questionEvidenceList">
                          {row.evidenceRuns.slice(0, 4).map((run) => (
                            <li key={run.answer_run.id}>
                              <strong>
                                {run.answer_run.platform} · {run.answer_run.surface} · {shortId(run.answer_run.id)}
                              </strong>
                              <span>
                                {run.answer_run.status} · triggered {boolText(run.answer_run.surface_triggered)} · answer{" "}
                                {boolText(run.answer_run.answer_present)}
                              </span>
                              <small>
                                {run.citations.length} citations · {run.evidence_assets.length} assets · raw hash{" "}
                                {clipText(run.raw_answer?.raw_payload_hash, 18)}
                              </small>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mutedText">No evidence runs in the current question evidence window.</p>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Latest Evidence" subtitle={latestEvidence?.answer_run.platform || "No runtime evidence"}>
          {latestEvidence ? (
            <div className="stack">
              <p className="prompt">{latestEvidence.answer_run.prompt_text}</p>
              <dl className="facts">
                <Fact label="Surface" value={latestEvidence.answer_run.surface} />
                <Fact label="City" value={latestEvidence.answer_run.city} />
                <Fact label="Intent" value={latestEvidence.answer_run.prompt_intent_type || "unknown"} />
                <Fact label="Citations" value={latestEvidence.citations.length} />
                <Fact label="Assets" value={latestEvidence.evidence_assets.length} />
              </dl>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Human Review Trail"
          subtitle={`${data.humanReviewQueue.total_count} queue items · ${data.humanReviews.total_count} review records`}
          wide
        >
          <div className="humanReviewGrid">
            <form action={submitHumanReview} className="humanReviewForm">
              <div className="formHeader">
                <h3>Record Review</h3>
                <small>{reviewTarget ? `${reviewTarget.targetType} · ${shortId(reviewTarget.targetId)}` : "No target"}</small>
              </div>
              <input type="hidden" name="project_id" value={selectedProjectId || ""} />
              <input type="hidden" name="target_label" value={reviewTarget?.label || ""} />
              <label>
                <span>Target type</span>
                <select name="target_type" defaultValue={reviewTarget?.targetType || "project"}>
                  <option value="visibility_score_snapshot">visibility_score_snapshot</option>
                  <option value="content_draft">content_draft</option>
                  <option value="answer_analysis">answer_analysis</option>
                  <option value="answer_run">answer_run</option>
                  <option value="score_weight_config">score_weight_config</option>
                  <option value="project">project</option>
                </select>
              </label>
              <label>
                <span>Target ID</span>
                <input name="target_id" defaultValue={reviewTarget?.targetId || selectedProjectId || ""} />
              </label>
              <label>
                <span>Status</span>
                <select name="review_status" defaultValue="approved">
                  <option value="approved">approved</option>
                  <option value="needs_changes">needs_changes</option>
                  <option value="rejected">rejected</option>
                  <option value="acknowledged">acknowledged</option>
                </select>
              </label>
              <label>
                <span>Reviewer</span>
                <input name="reviewer_id" defaultValue="runtime-console" />
              </label>
              <label className="wideField">
                <span>Decision</span>
                <input name="decision" defaultValue="approved_for_report" />
              </label>
              <label className="wideField">
                <span>Notes</span>
                <textarea
                  name="notes"
                  defaultValue={`Reviewed ${reviewTarget?.label || "runtime object"} against evidence and traceability bundle`}
                  rows={3}
                />
              </label>
              <button className="actionButton" type="submit" disabled={!selectedProjectId || !reviewTarget}>
                Record review
              </button>
            </form>
            <div className="humanReviewList">
              <h3>Review Queue</h3>
              {data.humanReviewQueue.records.length ? (
                <ul className="plainList">
                  {data.humanReviewQueue.records.map((item) => (
                    <li key={`${item.target_type}:${item.target_id}`}>
                      <strong>
                        {item.queue_status} · {item.target_type}
                      </strong>
                      <span>{item.title}</span>
                      <small>
                        priority {item.priority} · {item.reason} · {dateText(item.created_at || undefined)}
                      </small>
                      <small>
                        {item.latest_review?.decision || "no decision"} · {shortId(item.target_id)}
                      </small>
                    </li>
                  ))}
                </ul>
              ) : (
                <small>No human review queue items.</small>
              )}
              <h3>Recent Reviews</h3>
              {data.humanReviews.records.length ? (
                <ul className="plainList">
                  {data.humanReviews.records.map((item) => (
                    <li key={item.human_review.id}>
                      <strong>
                        {item.human_review.review_status} · {item.human_review.target_type}
                      </strong>
                      <span>
                        {item.human_review.decision} · {shortId(item.human_review.target_id)}
                      </span>
                      <small>
                        {item.human_review.reviewer_id} · {dateText(item.human_review.created_at)} ·{" "}
                        {item.audit_events[0]?.event_type || "no review audit"} ·{" "}
                        {item.audit_events[0]?.after_hash || "no hash"}
                      </small>
                    </li>
                  ))}
                </ul>
              ) : (
                <small>No human review records yet.</small>
              )}
              <dl className="facts">
                <Fact label="Review query" value={paths.humanReviews} />
                <Fact label="Queue query" value={paths.humanReviewQueue} />
                <Fact label="Method" value="human_review_v1" />
                <Fact label="Audit event" value="human_review_recorded" />
                <Fact label="Draft projection" value="content_draft_review_status_updated" />
              </dl>
            </div>
          </div>
        </Panel>

        <Panel title="Collection Run Quality" subtitle={latestCollectionRun?.collection_run.run_type || "No collection run"}>
          {latestCollectionRun ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Planned" value={latestCollectionRun.collection_run.planned_runs || 0} />
                <Fact label="Attempted" value={latestCollectionRun.collection_run.attempted_runs || 0} />
                <Fact label="Success" value={latestCollectionRun.collection_run.success_count || 0} />
                <Fact label="Failure" value={latestCollectionRun.collection_run.failure_count || 0} />
                <Fact label="Success rate" value={pct(latestCollectionRun.collection_run.success_rate)} />
                <Fact label="Trigger rate" value={pct(latestCollectionRun.collection_run.trigger_rate)} />
                <Fact label="Answer rate" value={pct(latestCollectionRun.collection_run.answer_present_rate)} />
                <Fact label="Total cost" value={num(latestCollectionRun.collection_run.total_cost)} />
                <Fact label="Avg cost/run" value={num(latestCollectionRun.collection_run.average_cost_per_run)} />
                <Fact label="Avg duration" value={`${latestCollectionRun.collection_run.average_duration_ms || 0} ms`} />
                <Fact label="Mode" value={latestCollectionRun.collection_run.mode || "unknown"} />
                <Fact
                  label="Platforms"
                  value={formatCounts(latestCollectionRun.collection_run.platform_distribution || {})}
                />
                <Fact
                  label="Access"
                  value={formatCounts(latestCollectionRun.collection_run.access_method_distribution || {})}
                />
                <Fact label="Audit" value={latestCollectionRun.audit_events.length} />
              </dl>
              <small className="auditLine">
                Collection run {shortId(latestCollectionRun.collection_run.id)} ·{" "}
                {dateText(latestCollectionRun.collection_run.started_at)} to{" "}
                {dateText(latestCollectionRun.collection_run.completed_at)} · total duration{" "}
                {latestCollectionRun.collection_run.total_duration_ms || 0} ms · failures{" "}
                {formatCounts(latestCollectionRun.collection_run.failure_summary || {})}
              </small>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Score Explanation" subtitle={latestScore?.snapshot.formula_version || "No score"}>
          {latestScore ? (
            <div className="stack">
              <div className="scoreRow">
                <strong>{num(latestScore.snapshot.final_score)}</strong>
                <span>Trigger {pct(latestScore.snapshot.trigger_rate)}</span>
                <span>Mention {pct(latestScore.snapshot.mention_rate)}</span>
                <span>Recommend {pct(latestScore.snapshot.recommendation_rate)}</span>
              </div>
              <ul className="compactList">
                {latestScore.contributions.slice(0, 4).map((item) => (
                  <li key={item.component_name}>
                    <span>{item.component_name}</span>
                    <strong>{num(item.weighted_contribution)}</strong>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Citation Graph" subtitle={`${latestGraph?.nodes.length || 0} nodes`}>
          {latestGraph ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Competitors" value={latestGraph.competitor_benchmarks.length} />
                <Fact label="Gaps" value={latestGraph.source_gaps.length} />
              </dl>
              <ul className="plainList">
                {latestGraph.source_gaps.slice(0, 3).map((gap) => (
                  <li key={`${gap.source_type}-${gap.gap_type}`}>
                    <strong>{gap.source_type}</strong>
                    <span>{gap.recommendation}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Report Snapshot" subtitle={latestReport?.report_export.report_version || "No report"}>
          {latestReport ? (
            <div className="stack" id={anchorId("report-export", latestReport.report_export.id)}>
              <dl className="facts">
                <Fact label="Sample size" value={latestReport.report_export.sample_size} />
                <Fact label="Evidence links" value={latestReport.answer_runs.length} />
                <Fact label="Formula" value={latestReport.report_export.scoring_formula_version || "unknown"} />
                <Fact label="Frozen MD URL" value={latestReport.report_export.markdown_url || "pending object store"} />
                <Fact label="Frozen PDF URL" value={latestReport.report_export.pdf_url || "pending object store"} />
                <Fact label="Frozen CSV URL" value={latestReport.report_export.csv_url || "pending object store"} />
              </dl>
              <div className="downloadRow">
                {reportMarkdownUrl ? <a href={reportMarkdownUrl}>Download Markdown</a> : null}
                {reportCsvUrl ? <a href={reportCsvUrl}>Download CSV</a> : null}
                {reportPdfUrl ? <a href={reportPdfUrl}>Download PDF</a> : null}
                {reportWhiteLabelPdfUrl ? <a href={reportWhiteLabelPdfUrl}>White-label PDF</a> : null}
                {reportSignedPdfUrl ? <a href={reportSignedPdfUrl}>Signed PDF URL</a> : null}
                {reportSignedWhiteLabelPdfUrl ? <a href={reportSignedWhiteLabelPdfUrl}>Signed white-label URL</a> : null}
              </div>
              <div className="traceLinkRow" aria-label="report trace links">
                <NodeLink label="Trace bundle" kind="traceability-map" value="runtime" />
                <NodeLink label="Score package" kind="score-snapshot" value={latestScore?.snapshot.id || "latest"} />
                {latestReport.answer_runs[0] ? (
                  <NodeLink label="First evidence" kind="answer-run" value={latestReport.answer_runs[0].id} />
                ) : null}
                {latestReportGraph?.nodes[0] ? (
                  <NodeLink label="First source" kind="source-node" value={latestReportGraph.nodes[0].node.id} />
                ) : null}
              </div>
              <dl className="facts">
                <Fact label="Artifact filters" value={reportCsvUrl?.replace(displayUrl, "") || "No report artifact"} />
                <Fact
                  label="White-label template"
                  value={reportWhiteLabelPdfUrl?.replace(displayUrl, "") || "No white-label artifact"}
                />
                <Fact
                  label="Signed artifact URL"
                  value={reportSignedPdfUrl?.replace(displayUrl, "") || "No signed artifact URL"}
                />
              </dl>
              <form action={enqueueRuntimeReportExportJob} className="reportExportJobForm">
                <input type="hidden" name="project_id" value={selectedProjectId || ""} />
                <input type="hidden" name="report_export_id" value={latestReport.report_export.id} />
                <input type="hidden" name="platform" value={filters.platform || ""} />
                <input type="hidden" name="city" value={filters.city || ""} />
                <input type="hidden" name="intent_type" value={filters.intent_type || ""} />
                <input type="hidden" name="sort" value={evidenceSort} />
                <input type="hidden" name="requested_by" value="runtime-console" />
                <input type="hidden" name="reason" value="Queue filtered report artifact export" />
                <label>
                  <span>Artifact</span>
                  <select name="artifact_type" defaultValue="pdf">
                    <option value="pdf">PDF</option>
                    <option value="csv">CSV</option>
                    <option value="markdown">Markdown</option>
                  </select>
                </label>
                <label>
                  <span>Template</span>
                  <select name="template" defaultValue="standard">
                    <option value="standard">Standard</option>
                    <option value="white_label">White label</option>
                  </select>
                </label>
                <button className="actionButton compactAction" type="submit" disabled={!selectedProjectId}>
                  Queue export
                </button>
              </form>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Report History" subtitle={`${data.reports.total_count} stored exports`} wide>
          {data.reports.records.length ? (
            <div className="reportHistory">
              {data.reports.records.map((report) => {
                const artifactBase = `${displayUrl}/v1/reports/runtime/${report.report_export.id}/artifact`;
                const markdownUrl = reportArtifactPath(artifactBase, "markdown", reportArtifactFilters);
                const csvUrl = reportArtifactPath(artifactBase, "csv", reportArtifactFilters);
                const pdfUrl = reportArtifactPath(artifactBase, "pdf", reportArtifactFilters);
                const whiteLabelPdfUrl = reportArtifactPath(artifactBase, "pdf", reportArtifactFilters, {
                  template: "white_label",
                  client_name: whiteLabelClientName,
                  prepared_by: whiteLabelPreparedBy
                });
                const signedPdfUrl = reportArtifactSignedUrlPath(artifactBase, "pdf", reportArtifactFilters);
                const signedWhiteLabelPdfUrl = reportArtifactSignedUrlPath(artifactBase, "pdf", reportArtifactFilters, {
                  template: "white_label",
                  client_name: whiteLabelClientName,
                  prepared_by: whiteLabelPreparedBy
                });
                const scoreSnapshot = report.score_snapshots[0];
                const managementEvent = report.audit_events.find(
                  (event) => event.event_type === "report_export_management_recorded",
                );
                return (
                  <article className="reportHistoryItem" key={report.report_export.id}>
                    <header>
                      <div>
                        <h3>{report.report_export.report_version}</h3>
                        <span>{dateText(report.report_export.exported_at)}</span>
                      </div>
                      <strong>{report.report_export.report_type || "report"}</strong>
                    </header>
                    <dl className="facts contributionFacts">
                      <Fact label="Report ID" value={shortId(report.report_export.id)} />
                      <Fact label="Market" value={report.report_export.market_code || "unknown"} />
                      <Fact label="Sample size" value={report.report_export.sample_size} />
                      <Fact label="Evidence links" value={report.answer_runs.length} />
                      <Fact label="Score snapshots" value={report.score_snapshots.length} />
                      <Fact label="Audit events" value={report.audit_events.length} />
                      <Fact label="Final score" value={num(scoreSnapshot?.final_score)} />
                      <Fact label="Method hash" value={shortId(report.report_export.methodology_hash)} />
                    </dl>
                    <div className="downloadRow reportHistoryDownloads">
                      {markdownUrl ? <a href={markdownUrl}>Markdown</a> : null}
                      {csvUrl ? <a href={csvUrl}>CSV</a> : null}
                      {pdfUrl ? <a href={pdfUrl}>PDF</a> : null}
                      {whiteLabelPdfUrl ? <a href={whiteLabelPdfUrl}>White-label PDF</a> : null}
                      {signedPdfUrl ? <a href={signedPdfUrl}>Signed PDF URL</a> : null}
                      {signedWhiteLabelPdfUrl ? <a href={signedWhiteLabelPdfUrl}>Signed white-label URL</a> : null}
                    </div>
                    <form action={recordRuntimeReportManagementEvent} className="reportManagementForm">
                      <input type="hidden" name="report_export_id" value={report.report_export.id} />
                      <input type="hidden" name="updated_by" value="runtime-console" />
                      <label>
                        <span>Status</span>
                        <select name="status" defaultValue="internal_review">
                          <option value="internal_review">Internal review</option>
                          <option value="client_ready">Client ready</option>
                          <option value="archived">Archived</option>
                        </select>
                      </label>
                      <label>
                        <span>Note</span>
                        <input name="note" defaultValue="Report history management update" />
                      </label>
                      <button className="actionButton compactAction" type="submit">
                        Record status
                      </button>
                    </form>
                    <ul className="plainList">
                      <li>
                        <strong>{managementEvent?.event_type || "management status pending"}</strong>
                        <span>{managementEvent?.reason || "No report management event recorded"}</span>
                        <small>{managementEvent?.actor_id || "runtime-console"} · {managementEvent?.method_version || "report_export_management_v1"}</small>
                      </li>
                      <li>
                        <strong>Frozen artifact URLs</strong>
                        <span>{report.report_export.markdown_url || "markdown pending"}</span>
                        <small>
                          {report.report_export.pdf_url || "pdf pending"} · {report.report_export.csv_url || "csv pending"}
                        </small>
                      </li>
                      <li>
                        <strong>Artifact filter path</strong>
                        <span>{csvUrl?.replace(displayUrl, "") || "No artifact API path"}</span>
                        <small>
                          {filters.platform || "all platforms"} · {filters.city || "all cities"} ·{" "}
                          {filters.intent_type || "all intents"} · {evidenceSort}
                        </small>
                      </li>
                      <li>
                        <strong>White-label template</strong>
                        <span>{whiteLabelPdfUrl?.replace(displayUrl, "") || "No white-label artifact path"}</span>
                        <small>{whiteLabelClientName} · {whiteLabelPreparedBy} · template white_label</small>
                      </li>
                      <li>
                        <strong>Signed artifact URL</strong>
                        <span>{signedPdfUrl?.replace(displayUrl, "") || "No signed artifact URL"}</span>
                        <small>HMAC signed URL endpoint · configurable TTL</small>
                      </li>
                      <li>
                        <strong>{report.audit_events[0]?.event_type || "no report audit"}</strong>
                        <span>{report.audit_events[0]?.target_type || "report_export"}</span>
                        <small>{report.audit_events[0]?.method_version || "no method version"}</small>
                      </li>
                    </ul>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Report Export Queue" subtitle={`${data.reportJobStats.total_count} tracked jobs`} wide>
          <div className="metricGrid queueStatsGrid">
            <Metric label="Queued" value={String(data.reportJobStats.status_counts.queued || 0)} />
            <Metric label="Running" value={String(data.reportJobStats.status_counts.running || 0)} />
            <Metric label="Retryable" value={String(data.reportJobStats.retryable_count)} />
            <Metric label="Expired leases" value={String(data.reportJobStats.expired_running_count)} />
            <Metric label="Dead letter" value={String(data.reportJobStats.status_counts.dead_letter || 0)} />
            <Metric label="Oldest queued" value={dateText(data.reportJobStats.oldest_queued_at || undefined)} />
          </div>
          <dl className="facts contributionFacts">
            <Fact label="Report Jobs API" value={paths.reportJobs} />
            <Fact label="Report Jobs CSV" value={paths.reportJobsExport} />
            <Fact label="Queue Stats API" value={paths.reportJobStats} />
          </dl>
          <div className="downloadRow">
            <a href={paths.reportJobsExport}>Download report jobs CSV</a>
          </div>
          {data.reportJobs.records.length ? (
            <div className="reportHistory">
              {data.reportJobs.records.map((jobRecord) => {
                const job = jobRecord.report_export_job;
                const latestAudit = jobRecord.audit_events[0];
                return (
                  <article className="reportHistoryItem" key={job.id}>
                    <header>
                      <div>
                        <h3>{job.artifact_type.toUpperCase()} · {job.template}</h3>
                        <span>{dateText(job.requested_at)}</span>
                      </div>
                      <strong>{job.status}</strong>
                    </header>
                    <dl className="facts contributionFacts">
                      <Fact label="Job ID" value={shortId(job.id)} />
                      <Fact label="Report ID" value={shortId(job.report_export_id || undefined)} />
                      <Fact label="Sort" value={job.sort} />
                      <Fact label="Attempts" value={`${job.attempt_count || 0} / ${job.max_attempts || 3}`} />
                      <Fact label="Next attempt" value={dateText(job.next_attempt_at || undefined)} />
                      <Fact label="Lease expires" value={dateText(job.lease_expires_at || undefined)} />
                      <Fact label="Requested by" value={job.requested_by} />
                      <Fact label="Updated by" value={job.updated_by} />
                      <Fact label="Completed" value={dateText(job.completed_at || undefined)} />
                    </dl>
                    <form action={updateRuntimeReportExportJobStatus} className="reportManagementForm">
                      <input type="hidden" name="job_id" value={job.id} />
                      <input type="hidden" name="updated_by" value="runtime-console" />
                      <label>
                        <span>Status</span>
                        <select name="status" defaultValue={job.status === "queued" ? "cancelled" : job.status}>
                          <option value="queued">Queued</option>
                          <option value="running">Running</option>
                          <option value="succeeded">Succeeded</option>
                          <option value="failed">Failed</option>
                          <option value="dead_letter">Dead letter</option>
                          <option value="cancelled">Cancelled</option>
                        </select>
                      </label>
                      <label>
                        <span>Artifact URL</span>
                        <input name="artifact_url" defaultValue={job.artifact_url || ""} />
                      </label>
                      <label>
                        <span>Reason</span>
                        <input name="reason" defaultValue="Update queued report export job" />
                      </label>
                      <button className="actionButton compactAction" type="submit">
                        Update job
                      </button>
                    </form>
                    <ul className="plainList">
                      <li>
                        <strong>{latestAudit?.event_type || "report_export_job_queued"}</strong>
                        <span>{latestAudit?.reason || job.error_message || "No queue status note"}</span>
                        <small>
                          {latestAudit?.actor_id || job.updated_by} ·{" "}
                          {latestAudit?.method_version || "runtime_report_export_job_v1"} · report_export_job_status_updated
                        </small>
                      </li>
                      <li>
                        <strong>Queued filters</strong>
                        <span>{JSON.stringify(job.filters || {})}</span>
                        <small>{paths.reportJobs} · {paths.reportJobStats}</small>
                      </li>
                      <li>
                        <strong>Artifact output</strong>
                        <span>{job.artifact_url || "artifact pending"}</span>
                        <small>{job.started_at ? `started ${dateText(job.started_at)}` : "not started"}</small>
                      </li>
                    </ul>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Runtime Notifications"
          subtitle={`${data.notifications.unread_count} unread notifications · ${data.notificationDeliveries.total_count} deliveries · ${data.notificationEmailSuppressions.total_count} project suppressions`}
          wide
        >
          <form action={saveRuntimeNotificationSubscription} className="reportManagementForm">
            <input type="hidden" name="project_id" value={selectedProjectId || ""} />
            <input type="hidden" name="updated_by" value="runtime-console" />
            <input
              type="hidden"
              name="reason"
              value="Save runtime notification subscription from console"
            />
            <label>
              <span>Channel</span>
              <select name="channel" defaultValue="webhook">
                <option value="webhook">webhook</option>
                <option value="slack">slack</option>
                <option value="email">email</option>
              </select>
            </label>
            <label>
              <span>Endpoint URL</span>
              <input name="endpoint_url" placeholder="https://hooks.example.com/geno-runtime, Slack Incoming Webhook URL, or mailto:ops@example.com" />
            </label>
            <label>
              <span>Event types</span>
              <input name="event_types" defaultValue="report_export_job,runtime_alert,entity_alias_assignment_overdue" />
            </label>
            <label>
              <span>Signing env (webhook)</span>
              <input name="signing_secret_env" placeholder="GENO_NOTIFICATION_WEBHOOK_SIGNING_SECRET" />
            </label>
            <label>
              <span>Signing key id</span>
              <input name="signing_secret_key_id" placeholder="v2" />
            </label>
            <label>
              <span>Previous signing env</span>
              <input name="previous_signing_secret_env" placeholder="GENO_NOTIFICATION_WEBHOOK_SIGNING_SECRET_PREVIOUS" />
            </label>
            <label>
              <span>Previous key id</span>
              <input name="previous_signing_secret_key_id" placeholder="v1" />
            </label>
            <label>
              <span>Slack channel</span>
              <input name="slack_channel" placeholder="#geno-alerts" />
            </label>
            <label>
              <span>Email reply-to</span>
              <input name="email_reply_to" placeholder="reports@example.com" />
            </label>
            <label>
              <span>Email unsubscribe URL</span>
              <input name="email_unsubscribe_url" placeholder="https://app.example.com/notifications/unsubscribe" />
            </label>
            <label>
              <span>Email unsubscribe mailto</span>
              <input name="email_unsubscribe_mailto" placeholder="mailto:unsubscribe@example.com" />
            </label>
            <label>
              <span>Email preferences URL</span>
              <input name="email_preferences_url" placeholder="https://app.example.com/notifications/preferences" />
            </label>
            <label>
              <span>Email suppressed recipients</span>
              <input name="email_suppressed_recipients" placeholder="muted@example.com, paused@example.com" />
            </label>
            <label>
              <span>Severity</span>
              <select name="severity_threshold" defaultValue="info">
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="critical">critical</option>
              </select>
            </label>
            <label>
              <span>Status</span>
              <select name="status" defaultValue="active">
                <option value="active">active</option>
                <option value="paused">paused</option>
                <option value="disabled">disabled</option>
              </select>
            </label>
            <button className="actionButton compactAction" type="submit" disabled={!selectedProjectId}>
              Save subscription
            </button>
          </form>
          <dl className="facts contributionFacts">
            <Fact label="Subscriptions" value={data.notificationSubscriptions.total_count} />
            <Fact label="Deliveries" value={data.notificationDeliveries.total_count} />
            <Fact label="Email feedback" value={data.notificationEmailFeedback.total_count} />
            <Fact label="Project suppressions" value={data.notificationEmailSuppressions.total_count} />
            <Fact label="Notification CSV" value={paths.notificationsExport} />
            <Fact label="Subscription API" value={paths.notificationSubscriptions} />
            <Fact label="Subscription CSV" value={paths.notificationSubscriptionsExport} />
            <Fact label="Delivery API" value={paths.notificationDeliveries} />
            <Fact label="Delivery CSV" value={paths.notificationDeliveriesExport} />
            <Fact label="Feedback API" value={paths.notificationEmailFeedback} />
            <Fact label="Suppression API" value={paths.notificationEmailSuppressions} />
            <Fact label="Suppression CSV" value={paths.notificationEmailSuppressionsExport} />
            <Fact label="Feedback webhook" value={paths.notificationEmailFeedbackWebhook} />
            <Fact label="Preference status API" value={paths.notificationEmailPreferenceStatus} />
            <Fact label="Resubscribe API" value={paths.notificationEmailPreferenceResubscribe} />
            <Fact label="Unsubscribe API" value={paths.notificationEmailPreferenceUnsubscribe} />
          </dl>
          <div className="downloadRow">
            <a href={paths.notificationsExport}>Download notification CSV</a>
            <a href={paths.notificationSubscriptionsExport}>Download subscription CSV</a>
            <a href={paths.notificationDeliveriesExport}>Download delivery CSV</a>
            <a href={paths.notificationEmailSuppressionsExport}>Download suppression CSV</a>
          </div>
          <form action={saveRuntimeNotificationEmailSuppression} className="reportManagementForm">
            <input type="hidden" name="project_id" value={selectedProjectId || ""} />
            <input type="hidden" name="updated_by" value="runtime-console" />
            <input
              type="hidden"
              name="reason"
              value="Save project email suppression from runtime console"
            />
            <label>
              <span>Project recipient hash</span>
              <input name="recipient_hash" placeholder="sha256 recipient hash" />
            </label>
            <label>
              <span>Suppression status</span>
              <select name="status" defaultValue="active">
                <option value="active">active</option>
                <option value="inactive">inactive</option>
              </select>
            </label>
            <label>
              <span>Suppression source</span>
              <select name="source" defaultValue="manual">
                <option value="manual">manual</option>
                <option value="feedback">feedback</option>
                <option value="preference">preference</option>
                <option value="provider">provider</option>
              </select>
            </label>
            <label>
              <span>Source ref</span>
              <input name="source_ref" placeholder="feedback id, ticket id, provider event hash" />
            </label>
            <label>
              <span>Suppression note</span>
              <input name="note" placeholder="project-level bounce or complaint review" />
            </label>
            <button className="actionButton compactAction" type="submit" disabled={!selectedProjectId}>
              Save project suppression
            </button>
          </form>
          {data.notificationEmailSuppressions.records.length ? (
            <ul className="plainList">
              {data.notificationEmailSuppressions.records.map((record) => (
                <li key={record.suppression.id}>
                  <strong>
                    Project email suppression · {record.suppression.status} · {record.suppression.source}
                  </strong>
                  <span>
                    recipient hash {shortId(record.suppression.recipient_hash)} · source{" "}
                    {record.suppression.source_ref || "manual"}
                  </span>
                  <small>
                    {record.audit_events[0]?.event_type || "runtime_notification_email_suppression_saved pending"} ·{" "}
                    {record.audit_events[0]?.method_version || "runtime_notification_email_suppression_v1"} ·{" "}
                    {dateText(record.suppression.updated_at)}
                  </small>
                </li>
              ))}
            </ul>
          ) : null}
          {data.notificationSubscriptions.records.length ? (
            <ul className="plainList">
              {data.notificationSubscriptions.records.map((record) => (
                <li key={record.subscription.id}>
                  <strong>
                    {record.subscription.channel} · {record.subscription.status} ·{" "}
                    {record.subscription.severity_threshold}
                  </strong>
                  <span>{record.subscription.endpoint_url}</span>
                  <small>
                    {record.subscription.event_types.join(", ")} ·{" "}
                    {typeof record.subscription.metadata?.signing_secret_env === "string"
                      ? `signed by ${record.subscription.metadata.signing_secret_env}${
                          typeof record.subscription.metadata?.signing_secret_key_id === "string"
                            ? ` (${record.subscription.metadata.signing_secret_key_id})`
                            : ""
                        } · `
                      : ""}
                    {record.audit_events[0]?.event_type || "runtime_notification_subscription_saved pending"} ·{" "}
                    {dateText(record.subscription.updated_at)}
                  </small>
                </li>
              ))}
            </ul>
          ) : null}
          {data.notifications.records.length ? (
            <div className="alertGrid">
              {data.notifications.records.map((record) => {
                const notification = record.notification;
                const audit = record.audit_events[0];
                return (
                  <article className={`alertCard ${notification.severity}`} key={notification.id}>
                    <header>
                      <div>
                        <h3>{notification.title}</h3>
                        <span>{notification.notification_type} · {notification.status}</span>
                      </div>
                      <strong>{notification.severity}</strong>
                    </header>
                    <p>{notification.message}</p>
                    <dl className="facts contributionFacts">
                      <Fact label="Target" value={`${notification.target_type} · ${shortId(notification.target_id)}`} />
                      <Fact label="Recipient" value={notification.recipient_role} />
                      <Fact label="Created by" value={notification.created_by} />
                      <Fact label="Created at" value={dateText(notification.created_at)} />
                      <Fact label="Read at" value={dateText(notification.read_at || undefined)} />
                      <Fact label="Audit" value={audit?.event_type || "runtime_notification_created pending"} />
                    </dl>
                    <form action={updateRuntimeNotificationStatus} className="reportManagementForm">
                      <input type="hidden" name="notification_id" value={notification.id} />
                      <input type="hidden" name="updated_by" value="runtime-console" />
                      <input type="hidden" name="reason" value="Mark runtime notification read from console" />
                      <input type="hidden" name="status" value={notification.status === "read" ? "unread" : "read"} />
                      <button className="actionButton compactAction" type="submit">
                        {notification.status === "read" ? "Mark unread" : "Mark read"}
                      </button>
                    </form>
                    <small>{paths.notifications} · {audit?.method_version || "runtime_notification_v1"}</small>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState />
          )}
          {data.notificationDeliveries.records.length ? (
            <ul className="plainList">
              {data.notificationDeliveries.records.map((record) => (
                <li key={record.delivery.id}>
                  <strong>
                    Delivery · {record.delivery.status} · attempt {record.delivery.attempt_count}/
                    {record.delivery.max_attempts}
                  </strong>
                  <span>{record.delivery.endpoint_url}</span>
                  <small>
                    HTTP {record.delivery.response_status ?? "pending"} ·{" "}
                    {record.delivery.error_message || record.delivery.response_body_hash || "response pending"} ·{" "}
                    {record.audit_events[0]?.event_type || "runtime_notification_delivery_status_updated pending"}
                  </small>
                  {record.delivery.channel === "email" ? (
                    <form action={recordRuntimeNotificationEmailFeedback} className="reportManagementForm">
                      <input type="hidden" name="delivery_id" value={record.delivery.id} />
                      <input type="hidden" name="recorded_by" value="runtime-console" />
                      <input
                        type="hidden"
                        name="reason"
                        value="Record runtime notification email feedback from console"
                      />
                      <label>
                        <span>Email feedback</span>
                        <select name="feedback_type" defaultValue="bounce">
                          <option value="bounce">bounce</option>
                          <option value="complaint">complaint</option>
                          <option value="unsubscribe">unsubscribe</option>
                          <option value="suppressed">suppressed</option>
                        </select>
                      </label>
                      <label>
                        <span>Recipient</span>
                        <input name="recipient" placeholder="recipient@example.com" />
                      </label>
                      <label>
                        <span>Recipient hash</span>
                        <input name="recipient_hash" placeholder="sha256 recipient hash" />
                      </label>
                      <label>
                        <span>Provider</span>
                        <input name="provider" placeholder="smtp, ses, sendgrid" />
                      </label>
                      <label>
                        <span>Provider event id</span>
                        <input name="provider_event_id" placeholder="feedback event id" />
                      </label>
                      <label>
                        <span>Provider event hash</span>
                        <input name="provider_event_id_hash" placeholder="sha256 provider event id hash" />
                      </label>
                      <label>
                        <span>Note</span>
                        <input name="note" placeholder="manual bounce review" />
                      </label>
                      <button className="actionButton compactAction" type="submit">
                        Record feedback
                      </button>
                      <small>
                        /v1/runtime-notification-deliveries/{record.delivery.id}/email-feedback ·{" "}
                        runtime_notification_email_feedback_recorded
                      </small>
                    </form>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {data.notificationEmailFeedback.records.length ? (
            <ul className="plainList">
              {data.notificationEmailFeedback.records.map((record) => (
                <li key={record.feedback_event.id}>
                  <strong>
                    Email feedback · {record.feedback_event.feedback_type} ·{" "}
                    {record.feedback_event.provider || "provider unknown"}
                  </strong>
                  <span>
                    Delivery {shortId(record.feedback_event.delivery_id)} ·{" "}
                    {record.notification?.title || "notification context pending"}
                  </span>
                  <small>
                    recipient hash {shortId(record.feedback_event.recipient_hash || undefined)} · provider event{" "}
                    {shortId(record.feedback_event.provider_event_id_hash || undefined)} ·{" "}
                    {record.audit_events[0]?.event_type || "runtime_notification_email_feedback_recorded pending"} ·{" "}
                    {dateText(record.feedback_event.occurred_at || record.feedback_event.created_at)}
                  </small>
                  {record.feedback_event.recipient_hash ? (
                    <div className="inlineStatusForm">
                      <form action={applyRuntimeNotificationEmailFeedbackSuppression} className="inlineStatusForm">
                        <input type="hidden" name="feedback_event_id" value={record.feedback_event.id} />
                        <input type="hidden" name="updated_by" value="runtime-console" />
                        <input
                          type="hidden"
                          name="reason"
                          value={`apply ${record.feedback_event.feedback_type} feedback suppression`}
                        />
                        <button className="actionButton compactAction" type="submit">
                          Apply suppression
                        </button>
                        <small>
                          /v1/runtime-notification-email-feedback-events/{record.feedback_event.id}/suppress-recipient ·{" "}
                          runtime_notification_email_feedback_suppression_applied
                        </small>
                      </form>
                      <form action={applyRuntimeNotificationEmailFeedbackProjectSuppression} className="inlineStatusForm">
                        <input type="hidden" name="feedback_event_id" value={record.feedback_event.id} />
                        <input type="hidden" name="updated_by" value="runtime-console" />
                        <input
                          type="hidden"
                          name="reason"
                          value={`apply ${record.feedback_event.feedback_type} feedback project suppression`}
                        />
                        <button className="actionButton compactAction" type="submit">
                          Apply project suppression
                        </button>
                        <small>
                          /v1/runtime-notification-email-feedback-events/{record.feedback_event.id}/project-suppression ·{" "}
                          runtime_notification_email_feedback_project_suppression_applied
                        </small>
                      </form>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>

        <Panel
          title="Report Method & Evidence Appendix"
          subtitle={latestReport?.report_export.methodology_hash || "No frozen methodology"}
          wide
        >
          {latestReport ? (
            <div className="reportDetail">
              <section className="reportSection reportMethod">
                <h3>Frozen Methodology</h3>
                <dl className="facts">
                  <Fact label="Report type" value={latestReport.report_export.report_type || "unknown"} />
                  <Fact label="Market" value={latestReport.report_export.market_code || "unknown"} />
                  <Fact label="Prompt version" value={latestReport.report_export.prompt_version || "unknown"} />
                  <Fact label="Formula version" value={latestReport.report_export.scoring_formula_version || "unknown"} />
                  <Fact label="Window start" value={dateText(latestReport.report_export.window_start)} />
                  <Fact label="Window end" value={dateText(latestReport.report_export.window_end)} />
                  <Fact label="Platforms" value={reportPlatforms} />
                  <Fact label="Access methods" value={reportAccessMethods} />
                  <Fact label="Cities" value={reportCities} />
                  <Fact label="Method hash" value={latestReport.report_export.methodology_hash || "unknown"} />
                </dl>
              </section>

              <section className="reportSection">
                <h3>Method Disclosure</h3>
                <dl className="facts">
                  <Fact label="Google coverage" value={reportGoogleCoverage} />
                  <Fact label="Google gate" value={reportGoogleGateStatus} />
                  <Fact label="Limited coverage" value={reportLimitedCoverage ? "yes" : "no"} />
                  <Fact label="API/browser fidelity" value={reportFidelityStatus} />
                  <Fact label="Trigger denominator" value={reportTriggerDenominator} />
                  <Fact label="Mention denominator" value={reportMentionDenominator} />
                  <Fact label="Recommendation denominator" value={reportRecommendationDenominator} />
                  <Fact label="Attempted records" value={reportEvidenceAttemptedRecords} />
                  <Fact label="Surface-triggered records" value={reportEvidenceTriggeredRecords} />
                  <Fact label="Evidence trigger rate" value={pct(reportEvidenceTriggerRate)} />
                  <Fact label="Official API rows" value={reportOfficialApiCount} />
                  <Fact label="Browser rows" value={reportBrowserCount} />
                  <Fact label="Comparable pairs" value={reportComparablePairs} />
                  <Fact label="Mismatch count" value={reportFidelityMismatchCount} />
                  <Fact label="Difference rate" value={reportDifferenceRate} />
                  <Fact label="Fidelity trend" value={fidelityTrend?.trend_direction || "no_data"} />
                  <Fact label="Trend samples" value={fidelityTrendSampleText} />
                  <Fact label="Trend average" value={optionalPct(fidelityTrend?.average_difference_rate)} />
                  <Fact label="Trend max" value={optionalPct(fidelityTrend?.max_difference_rate)} />
                  <Fact label="Trend window" value={fidelityTrendWindow} />
                  <Fact label="Fidelity audit" value={reportFidelityAudit} />
                  <Fact label="Fidelity query" value={paths.fidelityChecks} />
                  <Fact label="Trend query" value={paths.fidelityTrend} />
                  <Fact label="Payload hash" value={shortId(runtimeFidelity?.payload_hash)} />
                  <Fact label="Access distribution" value={formatCounts(reportFrozenAccessMethodCounts)} />
                  <Fact label="Platform distribution" value={formatCounts(reportFrozenPlatformCounts)} />
                  <Fact label="Screenshot records" value={reportScreenshotCount} />
                  <Fact label="HTML records" value={reportHtmlSnapshotCount} />
                </dl>
                <small className="auditLine">
                  Google remains outside the main scoring denominator until a stored Google AIO / AI Mode spike gate passes.
                  API-vs-browser fidelity is frozen as a runtime check and audited with api_browser_fidelity_checked.
                </small>
              </section>

              <section className="reportSection">
                <h3>Score Snapshot</h3>
                <dl className="facts">
                  <Fact label="Final score" value={num(latestReportScore?.final_score)} />
                  <Fact label="Trigger rate" value={pct(latestReportScore?.trigger_rate)} />
                  <Fact label="Mention rate" value={pct(latestReportScore?.mention_rate)} />
                  <Fact label="Recommendation" value={pct(latestReportScore?.recommendation_rate)} />
                  <Fact label="Dispersion" value={num(latestReportScore?.dispersion)} />
                  <Fact label="Snapshot formula" value={latestReportScore?.formula_version || "unknown"} />
                </dl>
                <h3>Platform Weights</h3>
                <ul className="plainList">
                  {Object.entries(reportPlatformWeights).map(([platform, weight]) => (
                    <li key={platform}>
                      <strong>{platform}</strong>
                      <span>{num(weight)}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="reportSection">
                <h3>Evidence Appendix</h3>
                <ul className="plainList">
                  {latestReport.answer_runs.slice(0, 8).map((run) => (
                    <li key={run.id}>
                      <strong>
                        {run.platform || "platform"} / {run.surface || "surface"} / {run.city || "city"}
                      </strong>
                      <span>{run.prompt_text || run.id}</span>
                      <small>
                        intent {run.prompt_intent_type || "unknown"} · access {run.access_method || "unknown"} · sample{" "}
                        {run.sample_index || 0}/{run.sample_size || 0} · answer {boolText(run.answer_present)} ·
                        surface {boolText(run.surface_triggered)} · run {shortId(run.id)}
                      </small>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="reportSection">
                <h3>Citation & Audit Summary</h3>
                <dl className="facts">
                  <Fact label="Graph nodes" value={latestReportGraph?.nodes.length || 0} />
                  <Fact label="Graph links" value={latestReportGraph?.evidence_links.length || 0} />
                  <Fact label="Source gaps" value={latestReportGraph?.source_gaps.length || 0} />
                  <Fact label="Benchmarks" value={latestReportGraph?.competitor_benchmarks.length || 0} />
                  <Fact label="Audit events" value={latestReport.audit_events.length} />
                </dl>
                <ul className="plainList">
                  {latestReport.audit_events.slice(0, 5).map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type || "audit_event"}</strong>
                      <span>{event.target_type || "target"} · {event.method_version || "no method version"}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Action & Retest" subtitle={latestAction?.retest_comparisons[0]?.trend || "No action plan"}>
          {latestAction ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Retest days" value={latestAction.retest_schedule.offsets_days.join("/")} />
                <Fact label="Score delta" value={num(latestAction.retest_comparisons[0]?.score_delta)} />
                <Fact label="Open actions" value={latestAction.action_recommendations.length} />
                <Fact label="Evidence runs" value={latestAction.answer_runs.length} />
              </dl>
              <ul className="plainList">
                {latestAction.action_recommendations.slice(0, 3).map((action) => (
                  <li key={action.title}>
                    <strong>{action.priority}</strong>
                    <span>{action.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Runtime Alerts"
          subtitle={`${data.alerts.total_count} active evidence-derived alerts`}
          wide
        >
          <form action={enqueueRuntimeAlertNotifications} className="reportManagementForm">
            <input type="hidden" name="project_id" value={selectedProjectId || ""} />
            <input type="hidden" name="created_by" value="runtime-console" />
            <input type="hidden" name="reason" value="Queue runtime alert notifications from console" />
            <label>
              <span>Alert type</span>
              <input name="alert_type" placeholder="All alert types" />
            </label>
            <label>
              <span>Severity</span>
              <select name="severity" defaultValue="">
                <option value="">all</option>
                <option value="critical">critical</option>
                <option value="high">high</option>
                <option value="medium">medium</option>
              </select>
            </label>
            <label className="checkboxLabel">
              <input type="checkbox" name="include_resolved" />
              <span>Include resolved or snoozed</span>
            </label>
            <button className="actionButton compactAction" type="submit" disabled={!selectedProjectId}>
              Queue alert notifications
            </button>
          </form>
          {data.alerts.records.length ? (
            <div className="alertGrid">
              {data.alerts.records.map((item) => (
                <article className={`alertItem ${alertTone(item.alert.severity)}`} key={item.alert.id}>
                  <header>
                    <h3>{item.alert.title}</h3>
                    <span>{item.alert.severity}</span>
                  </header>
                  <p>{item.alert.summary || "No alert summary"}</p>
                  <dl className="facts contributionFacts">
                    <Fact label="Type" value={item.alert.alert_type} />
                    <Fact label="Metric" value={item.alert.metric_name || "unknown"} />
                    <Fact label="Value" value={num(item.alert.metric_value)} />
                    <Fact label="Threshold" value={num(item.alert.threshold)} />
                    <Fact label="Source" value={item.alert.source || "derived"} />
                    <Fact label="Rule" value={item.alert.rule_version || "runtime_alerts_v1"} />
                  </dl>
                  <div className="traceLinkRow">
                    {item.evidence_refs.slice(0, 4).map((ref, index) => (
                      <NodeLink
                        key={`${item.alert.id}-${ref.target_type}-${ref.target_id}-${index}`}
                        label={ref.target_type || "Evidence"}
                        kind={ref.target_type || "evidence"}
                        value={ref.target_id || item.alert.source_id}
                      />
                    ))}
                  </div>
                  {item.related_actions.length ? (
                    <ul className="plainList compactList">
                      {item.related_actions.slice(0, 2).map((action) => (
                        <li key={action.id || action.title}>
                          <strong>{action.title || "Related action"}</strong>
                          <span>
                            {action.priority || "priority"} · {action.status || "status"} ·{" "}
                            {action.source_gap_type || "no source gap"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {item.management_events.length ? (
                    <ul className="plainList compactList">
                      {item.management_events.slice(0, 2).map((event) => (
                        <li key={event.id || `${item.alert.id}-${event.created_at}`}>
                          <strong>{event.status || "alert event"}</strong>
                          <span>
                            {event.updated_by || "runtime-console"} · {dateText(event.created_at)}
                            {event.note ? ` · ${event.note}` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <form action={recordRuntimeAlertEvent} className="inlineForm">
                    <input type="hidden" name="project_id" value={item.alert.project_id} />
                    <input type="hidden" name="alert_id" value={item.alert.id} />
                    <input type="hidden" name="alert_type" value={item.alert.alert_type} />
                    <input type="hidden" name="source" value={item.alert.source || "runtime_alert"} />
                    <input type="hidden" name="source_id" value={item.alert.source_id || item.alert.id} />
                    <input type="hidden" name="severity" value={item.alert.severity} />
                    <select name="status" defaultValue="acknowledged">
                      <option value="acknowledged">Acknowledge</option>
                      <option value="resolved">Resolve</option>
                      <option value="snoozed">Snooze</option>
                      <option value="reopened">Reopen</option>
                      <option value="escalated">Escalate</option>
                    </select>
                    <input name="updated_by" defaultValue="runtime-console" />
                    <input name="note" placeholder="Note" />
                    <button type="submit">Record alert event</button>
                  </form>
                  <small>
                    {item.audit_events[0]?.event_type || "derived alert"} ·{" "}
                    {item.audit_events[0]?.method_version || "runtime_alerts_v1"} ·{" "}
                    {shortId(item.alert.source_id)}
                  </small>
                </article>
              ))}
              <dl className="facts">
                <Fact label="Alert query" value={paths.alerts} />
                <Fact label="Alert notification API" value={paths.alertNotifications} />
                <Fact label="Method" value="runtime_alerts_v1" />
                <Fact label="Evidence refs" value="score/source_gap/benchmark/action" />
              </dl>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Action Plan & Retest Detail"
          subtitle={latestAction?.retest_schedule.prompt_version || "No retest schedule"}
          wide
        >
          {latestAction ? (
            <div className="actionDetail">
              <section className="actionSection actionSchedule">
                <h3>Retest Schedule</h3>
                <dl className="facts">
                  <Fact label="Schedule ID" value={shortId(latestAction.retest_schedule.id)} />
                  <Fact label="Prompt version" value={latestAction.retest_schedule.prompt_version} />
                  <Fact label="Sample size" value={latestAction.retest_schedule.sample_size || 0} />
                  <Fact label="Offsets" value={latestAction.retest_schedule.offsets_days.join("/")} />
                  <Fact label="Answer runs" value={latestAction.retest_schedule.answer_run_ids?.length || 0} />
                  <Fact label="Created" value={dateText(latestAction.retest_schedule.created_at)} />
                </dl>
                <ul className="plainList">
                  {(latestAction.retest_schedule.scheduled_dates || []).map((date, index) => (
                    <li key={`${date}-${index}`}>
                      <strong>T+{latestAction.retest_schedule.offsets_days[index] ?? index}</strong>
                      <span>{dateText(date)}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="actionSection">
                <h3>Action Recommendations</h3>
                <div className="actionCards">
                  {latestAction.action_recommendations.map((action) => (
                    <article
                      className="actionCard"
                      id={
                        traceability?.traceability_bundle.action_recommendation_ids.includes(action.id || "")
                          ? undefined
                          : anchorId("action", action.id || action.title)
                      }
                      key={action.id || action.title}
                    >
                      <header>
                        <h3>{action.title}</h3>
                        <span>{action.priority}</span>
                      </header>
                      <p>{action.description || "No description"}</p>
                      <dl className="facts contributionFacts">
                        <Fact label="Status" value={action.status} />
                        <Fact label="Owner" value={action.owner_id || "unassigned"} />
                        <Fact label="Source gap" value={action.source_gap_type || "none"} />
                        <Fact label="Source types" value={(action.related_source_types || []).join(", ") || "none"} />
                        <Fact label="Evidence runs" value={action.evidence_answer_run_ids?.length || 0} />
                        <Fact label="Next check" value={dateText(action.next_check_date)} />
                      </dl>
                    </article>
                  ))}
                </div>
              </section>

              <section className="actionSection">
                <h3>Retest Comparison</h3>
                <dl className="facts">
                  <Fact label="Trend" value={latestRetestComparison?.trend || "unknown"} />
                  <Fact label="Baseline score" value={num(latestRetestComparison?.baseline_score)} />
                  <Fact label="Retest score" value={num(latestRetestComparison?.retest_score)} />
                  <Fact label="Score delta" value={num(latestRetestComparison?.score_delta)} />
                  <Fact label="Baseline runs" value={latestRetestComparison?.baseline_answer_run_ids?.length || 0} />
                  <Fact label="Retest runs" value={latestRetestComparison?.retest_answer_run_ids?.length || 0} />
                  <Fact label="Compared at" value={dateText(latestRetestComparison?.created_at)} />
                </dl>
              </section>

              <section className="actionSection retestSchedulerPlan">
                <h3>AU Retest Scheduler Plan</h3>
                <dl className="facts contributionFacts">
                  <Fact label="Plan status" value={retestSchedulerPlan?.status || "unknown"} />
                  <Fact label="Ready" value={boolText(retestSchedulerPlan?.retest_scheduler_plan_ready)} />
                  <Fact label="Plan hash" value={shortHash(retestSchedulerPlan?.retest_scheduler_plan_hash)} />
                  <Fact label="Execution status" value={retestExecutionStatus?.status || "unknown"} />
                  <Fact label="Execution ready" value={boolText(retestExecutionStatus?.retest_execution_ready)} />
                  <Fact label="Comparison allowed" value={boolText(retestExecutionStatus?.comparison_allowed)} />
                  <Fact
                    label="Scheduler"
                    value={retestSchedulerPlan?.scheduler_policy.scheduler_status || "planned_not_temporalized"}
                  />
                  <Fact label="Prompt version" value={retestSchedulerScope?.prompt_version || "unknown"} />
                  <Fact label="Prompt count" value={retestSchedulerScope?.prompt_count || 0} />
                  <Fact label="Sample size" value={retestSchedulerScope?.sample_size || 0} />
                  <Fact label="Offsets" value={retestSchedulerScope?.offsets_days.join("/") || "0/7/14/30"} />
                  <Fact label="Runs/window" value={retestSchedulerScope?.planned_runs_per_window || 0} />
                  <Fact label="Total planned" value={retestSchedulerScope?.total_planned_runs || 0} />
                  <Fact label="Ready windows" value={`${retestExecutionSummary?.ready_window_count || 0}/${retestExecutionSummary?.window_count || 0}`} />
                  <Fact label="Missing artifacts" value={retestExecutionSummary?.missing_artifact_count || 0} />
                  <Fact label="Next execution" value={retestExecutionStatus?.next_action || "unknown"} />
                  <Fact label="Status hash" value={shortHash(retestExecutionStatus?.retest_execution_status_hash)} />
                  <Fact label="API" value={paths.retestSchedulerPlan} />
                  <Fact label="Execution API" value={paths.retestExecutionStatus} />
                </dl>
                {retestSchedulerTimeline.length ? (
                  <div className="retestTimeline">
                    {retestSchedulerTimeline.map((window) => (
                      <article className="retestWindow" key={window.id}>
                        <header>
                          <h4>{window.label}</h4>
                          <span>T+{window.offset_day}</span>
                        </header>
                        <dl className="facts contributionFacts">
                          <Fact label="Runs" value={window.planned_runs} />
                          <Fact label="Outputs" value={window.evidence_outputs?.length || 0} />
                        </dl>
                        <code>{window.commands?.[0]?.shell_command || "collection command pending"}</code>
                      </article>
                    ))}
                  </div>
                ) : (
                  <EmptyState />
                )}
                {retestExecutionWindows.length ? (
                  <div className="retestExecutionGrid">
                    {retestExecutionWindows.map((window) => (
                      <article className="retestExecutionWindow" key={window.id}>
                        <header>
                          <h4>{window.label}</h4>
                          <span>{window.window_ready ? "ready" : "blocked"}</span>
                        </header>
                        <dl className="facts contributionFacts">
                          <Fact label="Offset" value={`T+${window.offset_day}`} />
                          <Fact label="Runs" value={window.planned_runs} />
                          <Fact label="Missing" value={window.missing_artifact_count} />
                          <Fact label="Payload" value={`${window.payload?.status || "unknown"} / exists ${boolText(window.payload?.exists)}`} />
                          <Fact label="Manifest" value={`${window.manifest?.status || "unknown"} / exists ${boolText(window.manifest?.exists)}`} />
                          <Fact label="Payload hash" value={boolText(window.payload?.hash_valid)} />
                          <Fact label="Manifest hash" value={boolText(window.manifest?.hash_valid)} />
                        </dl>
                        <code>{window.blocking_reasons?.slice(0, 4).join("\n") || "window evidence ready"}</code>
                      </article>
                    ))}
                  </div>
                ) : null}
                <ul className="plainList compactList">
                  {(retestSchedulerPlan?.scheduler_policy.immutability_requirements || []).map((item) => (
                    <li key={item}>
                      <strong>Invariant</strong>
                      <span>{item}</span>
                    </li>
                  ))}
                  <li>
                    <strong>Boundary</strong>
                    <span>
                      plan real runs {boolText(retestSchedulerPlan?.current_boundary.real_external_runs_completed)} ·
                      execution real runs {boolText(retestExecutionStatus?.current_boundary.real_external_runs_completed)} ·
                      Temporal {boolText(retestSchedulerPlan?.current_boundary.temporal_scheduler_implemented)}
                    </span>
                  </li>
                </ul>
              </section>

              <section className="actionSection">
                <h3>Evidence Runs & Audit</h3>
                <ul className="plainList">
                  {latestAction.answer_runs.slice(0, 6).map((run) => (
                    <li key={run.id}>
                      <strong>
                        {run.platform || "platform"} / {run.surface || "surface"} / {run.city || "city"}
                      </strong>
                      <span>{run.prompt_text || run.id}</span>
                      <small>
                        intent {run.prompt_intent_type || "unknown"} · access {run.access_method || "unknown"} · sample{" "}
                        {run.sample_index || 0}/{run.sample_size || 0} · answer {boolText(run.answer_present)} ·
                        surface {boolText(run.surface_triggered)} · run {shortId(run.id)}
                      </small>
                    </li>
                  ))}
                </ul>
                <h3>Audit Trail</h3>
                <ul className="plainList">
                  {latestAction.audit_events.map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type || "audit_event"}</strong>
                      <span>{event.target_type || "target"} · {event.method_version || "no method version"}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Content Engine" subtitle={`${latestContent?.integration_connectors.length || 0} connectors`}>
          {latestContent ? (
            <div className="stack">
              <dl className="facts">
                <Fact label="Facts" value={latestContent.knowledge_facts.length} />
                  <Fact label="Drafts" value={latestContent.content_drafts.length} />
                  <Fact label="Manual records" value={latestContent.manual_distribution_records.length} />
                </dl>
                <ul className="plainList">
                  {latestContent.content_drafts.slice(0, 3).map((item) => (
                  <li key={item.draft.title}>
                    <strong>{item.draft.review_status}</strong>
                    <span>{item.draft.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Content Engine Detail"
          subtitle={`${latestContent?.content_drafts.length || 0} evidence-backed drafts`}
          wide
        >
          {latestContent ? (
            <div className="contentDetail">
              <section className="contentSection">
                <h3>Localized Knowledge Facts</h3>
                <ul className="plainList">
                  {latestContent.knowledge_facts.slice(0, 8).map((fact) => (
                    <li key={fact.id} id={anchorId("knowledge-fact", fact.id)}>
                      <strong>
                        {fact.market_code || "market"} · {fact.fact_type || "fact"}
                      </strong>
                      <span>
                        {fact.subject || "subject"} {fact.predicate || "predicate"} {fact.object_value || "value"}
                      </span>
                      <small>
                        city {fact.city || "global"} · confidence {num(fact.confidence)} · status {fact.status || "unknown"} ·
                        evidence {shortId(fact.evidence_source_id || undefined)}
                      </small>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="contentSection">
                <h3>pgvector Knowledge Search</h3>
                {data.knowledgeSearch ? (
                  <div className="knowledgeSearch">
                    <dl className="facts contributionFacts">
                      <Fact label="Query" value={data.knowledgeSearch.query} />
                      <Fact label="Model" value={data.knowledgeSearch.embedding_model} />
                      <Fact label="Market" value={data.knowledgeSearch.market_code} />
                      <Fact label="City" value={data.knowledgeSearch.city || "global"} />
                      <Fact label="Matches" value={data.knowledgeSearch.total_count} />
                      <Fact label="Search API" value={paths.knowledgeSearch} />
                      <Fact
                        label="Index audit"
                        value={data.knowledgeSearch.audit_events[0]?.event_type || "no index audit"}
                      />
                    </dl>
                    <ul className="plainList">
                      {data.knowledgeSearch.records.map((item) => (
                        <li key={item.fact.id}>
                          <strong>
                            {item.fact.market_code || "market"} · {item.fact.fact_type || "fact"} · score{" "}
                            {num(item.score)}
                          </strong>
                          <span>
                            {item.fact.subject || "subject"} {item.fact.predicate || "predicate"}{" "}
                            {item.fact.object_value || "value"}
                          </span>
                          <small>
                            fallback {item.fallback_used ? "yes" : "no"} · confidence {num(item.fact.confidence)} ·
                            model {item.embedding_model}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <small>
                    No pgvector knowledge search results yet. Expected audit: knowledge_fact_embeddings_indexed · model
                    fixture-knowledge-embedding-v1.
                  </small>
                )}
              </section>

              <section className="contentSection">
                <h3>Integration Connectors</h3>
                <div className="connectorGrid">
                  {latestContent.integration_connectors.map((connector) => (
                    <article className="connectorItem" key={connector.provider}>
                      <header>
                        <h3>{connector.provider}</h3>
                        <span>{connector.connection_status}</span>
                      </header>
                      <dl className="facts contributionFacts">
                        <Fact label="Auth" value={connector.auth_mode || "unknown"} />
                        <Fact label="Capabilities" value={(connector.capabilities || []).join(", ") || "none"} />
                      </dl>
                    </article>
                  ))}
                </div>
              </section>

              <section className="contentSection contentDrafts">
                <h3>Content Drafts</h3>
                <div className="contentDraftGrid">
                  {latestContent.content_drafts.map((item) => (
                    <article
                      className="contentDraftCard"
                      id={
                        traceability?.traceability_bundle.content_draft_ids.includes(item.draft.id || "")
                          ? undefined
                          : anchorId("content-draft", item.draft.id || item.draft.title)
                      }
                      key={item.draft.id || item.draft.title}
                    >
                      <header>
                        <h3>{item.draft.title}</h3>
                        <span>{item.draft.review_status}</span>
                      </header>
                      <dl className="facts contributionFacts">
                        <Fact label="Template" value={item.draft.content_template_id || "unknown"} />
                        <Fact label="Type" value={item.draft.content_type || "unknown"} />
                        <Fact label="City" value={item.draft.target_city || "unknown"} />
                        <Fact label="Platform" value={item.draft.target_platform || "unknown"} />
                        <Fact label="Source type" value={item.draft.target_source_type || "unknown"} />
                        <Fact label="Source gaps" value={(item.draft.source_gap_types || []).join(", ") || "none"} />
                        <Fact label="Facts used" value={item.knowledge_facts.length} />
                        <Fact label="Evidence runs" value={item.answer_runs.length} />
                        <Fact label="Manual records" value={item.manual_distribution_records.length} />
                      </dl>
                      <div className="contentBinding">
                        <h3>Target Questions</h3>
                        <ul className="plainList">
                          {item.target_questions.slice(0, 3).map((question, index) => (
                            <li key={`${item.draft.id}-question-${index}`}>
                              <strong>{question.intent_type || "intent"}</strong>
                              <span>{question.text}</span>
                              <small>{question.city || "unknown city"}</small>
                            </li>
                          ))}
                        </ul>
                        <h3>Evidence Runs</h3>
                        <ul className="plainList">
                          {item.answer_runs.slice(0, 3).map((run) => (
                            <li key={run.id}>
                              <strong>
                                <a href={anchorHref("answer-run", run.id)}>
                                  {run.platform || "platform"} · {run.city || "city"}
                                </a>
                              </strong>
                              <span>{run.prompt_text || run.id}</span>
                              <small>
                                intent {run.prompt_intent_type || "unknown"} · run {shortId(run.id)}
                              </small>
                            </li>
                          ))}
                        </ul>
                      </div>
                      {item.action_recommendation ? (
                        <small className="auditLine">
                          Source action: {item.action_recommendation.priority || "priority"} ·{" "}
                          {item.action_recommendation.status || "status"} ·{" "}
                          {item.action_recommendation.source_gap_type || "no source gap"} ·{" "}
                          {item.action_recommendation.title || "untitled"}
                        </small>
                      ) : null}
                      {item.audit_events.length ? (
                        <small className="auditLine">
                          Draft audit: {item.audit_events[0].event_type || "audit_event"} ·{" "}
                          {item.audit_events[0].method_version || "no method version"} ·{" "}
                          {dateText(item.audit_events[0].created_at || undefined)}
                        </small>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>

              <section className="contentSection">
                <h3>Manual Distribution & Audit</h3>
                <ul className="plainList">
                  {latestContent.manual_distribution_records.map((record, index) => (
                    <li key={`${record.platform}-${index}`}>
                      <strong>
                        {record.platform || "manual"} · {record.status || "unknown"}
                      </strong>
                      <span>{record.target_url || "URL pending human review"}</span>
                      <small>{record.notes || "No notes"}</small>
                    </li>
                  ))}
                </ul>
                <h3>Audit Trail</h3>
                <ul className="plainList">
                  {latestContent.audit_events.map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type || "audit_event"}</strong>
                      <span>{event.target_type || "target"} · {event.method_version || "no method version"}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel title="Evidence Runs" subtitle={`${data.evidence.total_count} stored runs · ${evidenceSort}`} wide>
          {data.evidence.records.length ? (
            <div className="evidenceGrid">
              {data.evidence.records.map((run) => (
                <details
                  className="evidenceItem"
                  id={
                    traceability?.traceability_bundle.answer_run_ids.includes(run.answer_run.id)
                      ? undefined
                      : anchorId("answer-run", run.answer_run.id)
                  }
                  key={run.answer_run.id}
                  open
                >
                  <summary>
                    {run.answer_run.platform} · {run.answer_run.city} · {shortId(run.answer_run.id)}
                  </summary>
                  <div className="evidenceBody">
                    <p className="prompt">{run.answer_run.prompt_text || "No prompt text"}</p>
                    <dl className="facts evidenceFacts">
                      <Fact label="Intent" value={run.answer_run.prompt_intent_type || "unknown"} />
                      <Fact label="Priority" value={run.answer_run.prompt_priority || "unknown"} />
                      <Fact label="Surface" value={run.answer_run.surface} />
                      <Fact label="Access" value={run.answer_run.access_method || "unknown"} />
                      <Fact label="Device" value={run.answer_run.device || "unknown"} />
                      <Fact label="Language" value={run.answer_run.language || "unknown"} />
                      <Fact label="Answer" value={boolText(run.answer_run.answer_present)} />
                      <Fact label="Triggered" value={boolText(run.answer_run.surface_triggered)} />
                      <Fact
                        label="Sample"
                        value={`${run.answer_run.sample_index || "?"}/${run.answer_run.sample_size || "?"}`}
                      />
                      <Fact label="Collector" value={run.answer_run.collector_backend_id || "unknown"} />
                      <Fact label="Version" value={run.answer_run.collector_version || "unknown"} />
                      <Fact label="Cost" value={num(run.collection_cost?.total_cost)} />
                      <Fact label="Duration" value={`${run.collection_cost?.duration_ms || 0} ms`} />
                      <Fact label="Citations" value={run.citations.length} />
                      <Fact label="Assets" value={run.evidence_assets.length} />
                      <Fact label="Raw hash" value={run.raw_answer?.raw_payload_hash || "missing"} />
                      <Fact label="Audit" value={run.audit_events.length} />
                    </dl>
                    <div className="evidenceColumns">
                      <div>
                        <h3>Citations</h3>
                        <ul className="plainList">
                          {run.citations.slice(0, 3).map((citation, index) => (
                            <li key={`${run.answer_run.id}-citation-${index}`}>
                              <strong>{citation.domain || citation.source_type || "citation"}</strong>
                              <span>{citation.url || "No URL"}</span>
                              <small>position {citation.position || index + 1}</small>
                            </li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <h3>Assets & Audit</h3>
                        <ul className="plainList">
                          {run.evidence_assets.slice(0, 2).map((asset, index) => (
                            <li key={`${run.answer_run.id}-asset-${index}`}>
                              <strong>{asset.asset_type || "asset"}</strong>
                              <span>{asset.url || "No URL"}</span>
                              <small>{asset.content_hash || "No content hash"}</small>
                            </li>
                          ))}
                          {run.collector_logs.slice(0, 1).map((log, index) => (
                            <li key={`${run.answer_run.id}-log-${index}`}>
                              <strong>{log.event_type || "collector_log"}</strong>
                              <span>{log.collector_backend_id || run.answer_run.collector_backend_id || "unknown"}</span>
                              <small>{JSON.stringify(log.payload || {})}</small>
                            </li>
                          ))}
                          {run.audit_events.slice(0, 1).map((event, index) => (
                            <li key={`${run.answer_run.id}-audit-${index}`}>
                              <strong>{event.event_type || "audit_event"}</strong>
                              <span>{event.target_type || "answer_run"}</span>
                              <small>{event.method_version || "no method version"}</small>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                </details>
              ))}
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Score Contributions"
          subtitle={latestScore?.snapshot.formula_version || "No score contribution package"}
          wide
        >
          {latestScore ? (
            <div className="scoreDetail" id={anchorId("score-snapshot", latestScore.snapshot.id || "latest")}>
              <div className="scoreSummary">
                <div className="scoreTotal">
                  <span>Final score</span>
                  <strong>{num(latestScore.snapshot.final_score)}</strong>
                </div>
                <dl className="facts">
                  <Fact label="Scope" value={latestScore.snapshot.scope_value || latestScore.snapshot.scope_type || "unknown"} />
                  <Fact label="Formula" value={latestScore.snapshot.formula_version} />
                  <Fact label="Trigger" value={pct(latestScore.snapshot.trigger_rate)} />
                  <Fact label="Mention" value={pct(latestScore.snapshot.mention_rate)} />
                  <Fact label="Recommend" value={pct(latestScore.snapshot.recommendation_rate)} />
                  <Fact label="Dispersion" value={num(latestScore.snapshot.dispersion)} />
                  <Fact label="Weight snapshot" value={latestScore.snapshot.component_weights_snapshot ? num(latestScoreWeightTotal) : "legacy"} />
                  <Fact label="Answer runs" value={latestScore.answer_runs.length} />
                  <Fact label="Parser agreement" value={parserAgreement(latestScore.answer_runs[0])} />
                  <Fact label="Audit events" value={latestScore.audit_events.length} />
                </dl>
              </div>
              <div className="contributionGrid">
                {latestScore.contributions.map((item) => (
                  <article
                    className="contributionItem"
                    id={anchorId("score-contribution", item.id || item.component_name)}
                    key={item.id || item.component_name}
                  >
                    <header>
                      <h3>{item.component_name}</h3>
                      <strong>{num(item.weighted_contribution)}</strong>
                    </header>
                    <dl className="facts contributionFacts">
                      <Fact label="Raw score" value={num(item.component_score)} />
                      <Fact label="Weight" value={num(item.weight)} />
                      <Fact label="Denominator" value={item.denominator || "unknown"} />
                      <Fact label="Evidence runs" value={item.evidence_answer_run_ids?.length || 0} />
                    </dl>
                    <div className="evidenceNote positiveNote">
                      <strong>Positive evidence</strong>
                      <span>{item.positive_evidence_summary || "No positive evidence summary"}</span>
                    </div>
                    <div className="evidenceNote">
                      <strong>Negative evidence</strong>
                      <span>{item.negative_evidence_summary || "No negative evidence summary"}</span>
                    </div>
                    {(item.evidence_answer_run_ids || []).length ? (
                      <div className="traceLinkRow">
                        {(item.evidence_answer_run_ids || []).slice(0, 3).map((runId) => (
                          <NodeLink key={runId} label="Evidence" kind="answer-run" value={runId} />
                        ))}
                      </div>
                    ) : null}
                    <small>{item.confidence_note || "No confidence note"}</small>
                  </article>
                ))}
              </div>
              <div className="scoreRuns">
                <h3>Linked Answer Runs</h3>
                <ul className="plainList">
                  {latestScore.answer_runs.slice(0, 6).map((run) => (
                    <li key={run.answer_run.id}>
                      <strong>
                        <a href={anchorHref("answer-run", run.answer_run.id)}>
                          {run.answer_run.platform || "platform"} · {run.answer_run.city || "city"} ·{" "}
                          {shortId(run.answer_run.id)}
                        </a>
                      </strong>
                      <span>{run.answer_run.prompt_text || "No prompt text"}</span>
                      <small>
                        {run.answer_run.prompt_intent_type || "unknown intent"} · parser{" "}
                        {run.analysis?.analysis_version || "unknown"} · confidence {num(run.analysis?.confidence)}
                        {" · "}
                        {parserComparisonText(run)}
                      </small>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Citation Graph & Competitors"
          subtitle={`${latestGraph?.nodes.length || 0} sources · ${latestGraph?.competitor_benchmarks.length || 0} competitors`}
          wide
        >
          {latestGraph ? (
            <div className="graphDetail">
              <CitationGraphMap graph={latestGraph} />
              <div className="graphColumns">
                <section className="graphSection">
                  <h3>Source Nodes</h3>
                  <ul className="plainList">
                    {latestGraph.nodes.slice(0, 8).map((item) => (
                      <li id={anchorId("source-node", item.node.id)} key={item.node.id}>
                        <strong>
                          {item.node.source_domain || "source"} · {item.node.source_type || "unknown"}
                        </strong>
                        <span>{item.node.source_url || "No source URL"}</span>
                        <small>
                          topic {item.node.topic || "unknown"} · citations {item.node.citation_count || 0} · runs{" "}
                          {item.answer_runs.length}
                        </small>
                        {item.answer_runs.length ? (
                          <div className="traceLinkRow">
                            {item.answer_runs.slice(0, 3).map((run) => (
                              <NodeLink key={run.id} label="Run" kind="answer-run" value={run.id} />
                            ))}
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </section>
                <section className="graphSection">
                  <h3>Source Gaps</h3>
                  <ul className="plainList">
                    {latestGraph.source_gaps.map((gap) => (
                      <li key={`${gap.source_type}-${gap.gap_type}`}>
                        <strong>
                          {gap.source_type} · {gap.gap_type}
                        </strong>
                        <span>{gap.recommendation}</span>
                        <small>
                          observed {gap.observed_count || 0} · expected weight {num(gap.expected_weight)}
                        </small>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
              <div className="graphColumns">
                <section className="graphSection">
                  <h3>Competitor Benchmarks</h3>
                  <div className="benchmarkGrid">
                    {latestGraph.competitor_benchmarks.map((benchmark) => (
                      <article className="benchmarkItem" key={benchmark.competitor_name}>
                        <header>
                          <h3>{benchmark.competitor_name}</h3>
                          <span>{benchmark.metric_scope || "project"}</span>
                        </header>
                        <dl className="facts contributionFacts">
                          <Fact label="Mentions" value={benchmark.payload?.mention_count || 0} />
                          <Fact label="Mention rate" value={pct(benchmark.payload?.mention_rate)} />
                          <Fact label="Recs" value={benchmark.payload?.recommendation_count || 0} />
                          <Fact label="Overlap" value={benchmark.payload?.citation_overlap_count || 0} />
                          <Fact label="Local avg" value={num(benchmark.payload?.local_relevance_average)} />
                          <Fact label="Runs" value={benchmark.answer_run_ids?.length || 0} />
                        </dl>
                      </article>
                    ))}
                  </div>
                </section>
                <section className="graphSection">
                  <h3>Graph Evidence Links</h3>
                  <ul className="plainList">
                    {latestGraph.evidence_links.slice(0, 8).map((link, index) => (
                      <li key={`${link.source_graph_id}-${link.answer_run_id}-${index}`}>
                        <strong>{link.relation_type || "graph_evidence"}</strong>
                        <span className="inlineLinks">
                          <NodeLink label="Source" kind="source-node" value={link.source_graph_id} />
                          <NodeLink label="Run" kind="answer-run" value={link.answer_run_id} />
                        </span>
                        <small>citation {shortId(link.answer_citation_id || undefined)}</small>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>

        <Panel
          title="Traceability Detail"
          subtitle={traceability?.report_exports[0]?.report_version || "No traceability bundle"}
          wide
        >
          {traceability ? (
            <div className="traceGrid">
              <div className="traceSummary">
                <p className="prompt">{traceability.traceability_bundle.explanation_summary}</p>
                <div className="downloadRow">
                  <a href={`/traceability${selectedProjectId ? `?project_id=${encodeURIComponent(selectedProjectId)}` : ""}`}>
                    Open traceability detail
                  </a>
                </div>
                <dl className="facts">
                  <Fact label="Reports" value={traceability.traceability_bundle.report_export_ids.length} />
                  <Fact label="Score snapshots" value={traceability.traceability_bundle.score_snapshot_ids.length} />
                  <Fact label="Score parts" value={traceability.traceability_bundle.score_contribution_ids.length} />
                  <Fact label="Answer runs" value={traceability.traceability_bundle.answer_run_ids.length} />
                  <Fact label="Raw answers" value={traceability.traceability_bundle.raw_answer_ids.length} />
                  <Fact label="Citations" value={traceability.traceability_bundle.answer_citation_ids.length} />
                  <Fact label="Assets" value={traceability.traceability_bundle.evidence_asset_ids.length} />
                  <Fact label="Graph nodes" value={traceability.traceability_bundle.source_graph_ids.length} />
                  <Fact label="Actions" value={traceability.traceability_bundle.action_recommendation_ids.length} />
                  <Fact label="Drafts" value={traceability.traceability_bundle.content_draft_ids.length} />
                </dl>
              </div>
              <TraceabilityMap
                graph={latestGraph}
                report={latestReport}
                score={latestScore}
                traceability={traceability}
              />
              <div className="traceColumn">
                <h3>Evidence Links</h3>
                <ul className="plainList">
                  {traceability.evidence_links.slice(0, 5).map((link, index) => (
                    <li key={`${link.relation_type}-${index}`}>
                      <strong>{link.relation_type}</strong>
                      <span>
                        {link.source_type} to {link.target_type} · {link.answer_run_ids.length} answer runs
                      </span>
                      <div className="traceLinkRow">
                        {link.answer_run_ids.slice(0, 3).map((runId) => (
                          <NodeLink key={runId} label="Run" kind="answer-run" value={runId} />
                        ))}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="traceColumn">
                <h3>Audit Trail</h3>
                <ul className="plainList">
                  {traceability.audit_events.slice(0, 5).map((event, index) => (
                    <li key={`${event.event_type}-${index}`}>
                      <strong>{event.event_type}</strong>
                      <span>
                        {event.target_type} · {event.method_version || "no method version"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="traceDrilldown">
                <h3>Node Drilldown</h3>
                <div className="detailGrid">
                  <details open>
                    <summary>Score Components</summary>
                    <ul className="nodeList">
                      {traceability.score_snapshots[0]?.contributions.map((item) => (
                        <li key={item.component_name}>
                          <strong>{item.component_name}</strong>
                          <span>
                            {num(item.weighted_contribution)} weighted · denominator {item.denominator || "unknown"}
                          </span>
                          <small>{item.positive_evidence_summary || "No positive evidence summary"}</small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  <details open>
                    <summary>Answer Evidence</summary>
                    <ul className="nodeList">
                      {traceability.evidence_runs.slice(0, 4).map((run) => (
                        <li id={anchorId("answer-run", run.answer_run.id)} key={run.answer_run.id}>
                          <strong>
                            {run.answer_run.platform} · {run.answer_run.city} · {shortId(run.answer_run.id)}
                          </strong>
                          <span>{run.answer_run.prompt_text || "No prompt text"}</span>
                          <small>
                            {run.citations.length} citations · {run.evidence_assets.length} assets · raw_payload_hash{" "}
                            {run.raw_answer?.raw_payload_hash || "missing"}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  <details>
                    <summary>Citation & Asset Nodes</summary>
                    <ul className="nodeList">
                      {traceability.evidence_runs.slice(0, 3).flatMap((run) =>
                        [
                          ...run.citations.slice(0, 2).map((citation, index) => ({
                            key: `${run.answer_run.id}-citation-${index}`,
                            title: citation.domain || citation.url || "citation",
                            body: citation.url || "No URL",
                            meta: `${citation.source_type || "unknown source"} · position ${citation.position || index + 1}`
                          })),
                          ...run.evidence_assets.slice(0, 1).map((asset, index) => ({
                            key: `${run.answer_run.id}-asset-${index}`,
                            title: asset.asset_type || "asset",
                            body: asset.url || "No asset URL",
                            meta: asset.content_hash || "No content hash"
                          }))
                        ].map((item) => (
                          <li key={item.key}>
                            <strong>{item.title}</strong>
                            <span>{item.body}</span>
                            <small>{item.meta}</small>
                          </li>
                        ))
                      )}
                    </ul>
                  </details>
                  <details>
                    <summary>Actions & Content Drafts</summary>
                    <ul className="nodeList">
                      {traceability.action_recommendations.slice(0, 4).map((action) => (
                        <li id={anchorId("action", action.id || action.title)} key={action.id || action.title}>
                          <strong>{action.priority}</strong>
                          <span>{action.title}</span>
                          <small>
                            {action.status} · {action.source_gap_type || "no source gap"}
                          </small>
                        </li>
                      ))}
                      {traceability.content_drafts.slice(0, 4).map((item) => (
                        <li id={anchorId("content-draft", item.draft.id || item.draft.title)} key={item.draft.id || item.draft.title}>
                          <strong>{item.draft.review_status}</strong>
                          <span>{item.draft.title}</span>
                          <small>
                            {item.draft.target_city || "no city"} · {item.draft.target_platform || "no platform"}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </details>
                  <details>
                    <summary>Audit Event Nodes</summary>
                    <ul className="nodeList">
                      {traceability.audit_events.map((event, index) => (
                        <li key={`${event.event_type}-${index}`}>
                          <strong>{event.event_type}</strong>
                          <span>{event.target_type}</span>
                          <small>{event.method_version || "no method version"}</small>
                        </li>
                      ))}
                    </ul>
                  </details>
                </div>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </Panel>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function Panel({
  title,
  subtitle,
  children,
  wide = false
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <article className={wide ? "panel panelWide" : "panel"}>
      <header className="panelHeader">
        <h2>{title}</h2>
        <span>{subtitle}</span>
      </header>
      {children}
    </article>
  );
}

function NodeLink({ label, kind, value }: { label: string; kind: string; value: string | undefined }) {
  return (
    <a className="nodeLink" href={anchorHref(kind, value)} title={`${label}: ${value || "unknown"}`}>
      {label} {shortId(value)}
    </a>
  );
}

function CitationGraphMap({ graph }: { graph: CitationGraph }) {
  const nodes = graph.nodes.slice(0, 5);
  const runIds = Array.from(
    new Set(
      nodes
        .flatMap((item) => item.answer_runs.map((run) => run.id))
        .concat(graph.evidence_links.map((link) => link.answer_run_id || ""))
        .filter(Boolean)
    )
  ).slice(0, 5);
  const nodePositions = nodes.map((item, index) => ({
    item,
    x: 140 + index * 150,
    y: index % 2 === 0 ? 88 : 158
  }));
  const runPositions = runIds.map((runId, index) => ({
    runId,
    x: 120 + index * 150,
    y: 280
  }));
  return (
    <section className="graphSection graphMapPanel" aria-label="citation graph map">
      <div className="sectionHeader">
        <h3>Citation Graph Map</h3>
        <span>
          {nodes.length} sources · {runIds.length} runs · {graph.evidence_links.length} links
        </span>
      </div>
      <div className="graphCanvas">
        <svg viewBox="0 0 820 360" role="img" aria-label="Source nodes linked to answer runs">
          <line x1="50" y1="34" x2="770" y2="34" className="graphRail" />
          <text x="50" y="22" className="graphLabel">
            Source nodes
          </text>
          <text x="50" y="340" className="graphLabel">
            Answer runs
          </text>
          {graph.evidence_links.slice(0, 12).map((link, index) => {
            const sourceIndex = nodePositions.findIndex((node) => node.item.node.id === link.source_graph_id);
            const runIndex = runPositions.findIndex((run) => run.runId === link.answer_run_id);
            if (sourceIndex < 0 || runIndex < 0) return null;
            const source = nodePositions[sourceIndex];
            const run = runPositions[runIndex];
            return (
              <line
                className="graphEdge"
                key={`${link.source_graph_id}-${link.answer_run_id}-${index}`}
                x1={source.x}
                y1={source.y + 24}
                x2={run.x}
                y2={run.y - 24}
              />
            );
          })}
          {nodePositions.map(({ item, x, y }) => (
            <a href={anchorHref("source-node", item.node.id)} key={item.node.id}>
              <circle className="graphSourceNode" cx={x} cy={y} r="24" />
              <text className="graphNodeText" x={x} y={y - 34} textAnchor="middle">
                {clipText(item.node.source_domain || item.node.source_type || "source", 18)}
              </text>
              <text className="graphNodeMeta" x={x} y={y + 5} textAnchor="middle">
                {item.node.citation_count || 0}
              </text>
            </a>
          ))}
          {runPositions.map(({ runId, x, y }) => (
            <a href={anchorHref("answer-run", runId)} key={runId}>
              <rect className="graphRunNode" height="42" rx="6" width="104" x={x - 52} y={y - 21} />
              <text className="graphRunText" x={x} y={y + 4} textAnchor="middle">
                {shortId(runId)}
              </text>
            </a>
          ))}
        </svg>
      </div>
    </section>
  );
}

function TraceabilityMap({
  graph,
  report,
  score,
  traceability
}: {
  graph: CitationGraph | undefined;
  report: ReportExport | undefined;
  score: ScoreSnapshot | undefined;
  traceability: TraceabilityDetail;
}) {
  const firstRunId = traceability.traceability_bundle.answer_run_ids[0] || report?.answer_runs[0]?.id;
  const firstSourceId = graph?.nodes[0]?.node.id || traceability.traceability_bundle.source_graph_ids[0];
  const firstActionId =
    traceability.traceability_bundle.action_recommendation_ids[0] || traceability.action_recommendations[0]?.id;
  const firstDraftId = traceability.traceability_bundle.content_draft_ids[0] || traceability.content_drafts[0]?.draft.id;
  const nodes = [
    {
      label: "Report",
      kind: "report-export",
      value: report?.report_export.id || traceability.traceability_bundle.report_export_ids[0],
      x: 80,
      y: 58
    },
    {
      label: "Score",
      kind: "score-snapshot",
      value: score?.snapshot.id || traceability.traceability_bundle.score_snapshot_ids[0] || "latest",
      x: 250,
      y: 58
    },
    { label: "Evidence", kind: "answer-run", value: firstRunId, x: 420, y: 58 },
    { label: "Source", kind: "source-node", value: firstSourceId, x: 590, y: 58 },
    { label: "Action", kind: "action", value: firstActionId, x: 250, y: 166 },
    { label: "Draft", kind: "content-draft", value: firstDraftId, x: 420, y: 166 }
  ];
  return (
    <section className="traceMap" id={anchorId("traceability-map", "runtime")}>
      <div className="sectionHeader">
        <h3>Traceability Map</h3>
        <span>report to score to evidence to source</span>
      </div>
      <div className="traceMapCanvas">
        <svg viewBox="0 0 700 230" role="img" aria-label="Runtime traceability map">
          <path className="traceEdge" d="M128 58 H202" />
          <path className="traceEdge" d="M298 58 H372" />
          <path className="traceEdge" d="M468 58 H542" />
          <path className="traceEdge" d="M420 90 C420 128 330 128 250 142" />
          <path className="traceEdge" d="M420 90 V136" />
          {nodes.map((node) => (
            <a href={anchorHref(node.kind, node.value)} key={`${node.kind}-${node.value}`}>
              <rect className="traceNode" height="52" rx="7" width="96" x={node.x - 48} y={node.y - 26} />
              <text className="traceNodeLabel" x={node.x} y={node.y - 4} textAnchor="middle">
                {node.label}
              </text>
              <text className="traceNodeMeta" x={node.x} y={node.y + 15} textAnchor="middle">
                {shortId(node.value)}
              </text>
            </a>
          ))}
        </svg>
      </div>
      <div className="traceLinkRow">
        <NodeLink label="Report" kind="report-export" value={report?.report_export.id} />
        <NodeLink label="Score" kind="score-snapshot" value={score?.snapshot.id || "latest"} />
        <NodeLink label="Evidence" kind="answer-run" value={firstRunId} />
        <NodeLink label="Source" kind="source-node" value={firstSourceId} />
      </div>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function EmptyState() {
  return <p className="empty">Run the collector worker to populate runtime data.</p>;
}
