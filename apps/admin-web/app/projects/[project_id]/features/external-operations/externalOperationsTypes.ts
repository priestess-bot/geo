export type LoadProblem = Readonly<{ status?: number; detail: string; correlationId?: string }>;

export type ConnectorDefinition = Readonly<{
  id: string; kind: string; adapter_release: string; runtime_release: string; status: string;
}>;
export type ConnectorConnection = Readonly<{
  id: string; definition_id: string; name: string; secret_reference_id: string;
  secret_purpose: string; secret_version: number; status: string; version: number;
}>;
export type ConnectorScope = Readonly<{
  id: string; connection_id: string; source_locator: string; streams: string[];
  locale: string; status: string; version: number;
}>;
export type ConnectorRun = Readonly<{
  id: string; scope_id: string; mode: string; status: string; version: number;
  durable_job_id?: string;
  requested_at: string; started_at?: string; finished_at?: string; error_class?: string;
  projection_batch_id?: string; checkpoint_id?: string; freshness_status?: string;
  freshness_reason?: string; projected_row_count?: number;
  cancel_requested_at?: string;
}>;
export type ConnectorInventory = Readonly<{
  definitions: ConnectorDefinition[]; connections: ConnectorConnection[];
  scopes: ConnectorScope[]; runs: ConnectorRun[];
  connection_tests: Array<Readonly<{
    id: string; connection_id: string; durable_job_id: string; adapter_release: string;
    secret_version: number; status: string; requested_at: string; finished_at?: string;
    error_class?: string;
  }>>;
}>;

export type SurfaceRelease = Readonly<{
  id: string; platform: string; surface: string; release_version: string; status: string;
  authorization_status: string; authorization_valid_until?: string; release_hash: string;
  suspended_at?: string; suspension_reason?: string;
}>;
export type EgressEndpoint = Readonly<{
  id: string; name: string; endpoint_host: string; endpoint_port: number; network_type: string;
  sticky_mode: string; expected_country: string; status: string;
  provider: string; pool_product: string; session_ttl_seconds: number;
  max_concurrency: number; health_status: string; consecutive_failures: number;
  last_checked_at?: string; cooldown_until?: string; last_error_class?: string;
}>;
export type BrowserProfile = Readonly<{
  id: string; version: string; browser_release: string; device_class: string; locale: string;
  timezone: string; account_cohort: string; status: string;
}>;
export type BrowserCaptureTask = Readonly<{
  id: string; run_id: string; question_id: string; repetition: number;
  status: string; version: number; run_status: string;
  surface_release_id: string; egress_endpoint_id: string; profile_version_id: string;
  attempt_id?: string; attempt_status?: string; durable_job_id?: string;
}>;
export type BrowserInventory = Readonly<{
  surface_releases: SurfaceRelease[]; egress_endpoints: EgressEndpoint[];
  profiles: BrowserProfile[]; tasks: BrowserCaptureTask[];
  egress_tests: Array<Readonly<{
    id: string; endpoint_id: string; durable_job_id: string; status: string;
    requested_at: string; finished_at?: string; outcome?: string; eligible?: boolean;
    verification_hash?: string; error_class?: string;
  }>>;
  drift_events: Array<Readonly<{
    id: string; surface_release_id: string; drift_kind: string;
    expected_value: string; observed_value: string; evidence_hash: string;
    detected_at: string; release_suspended: boolean;
  }>>;
  sessions: Array<Record<string, unknown>>;
}>;
export type BrowserAdmissionPolicy = Readonly<{
  id: string; platform: string; capture_method: string; adapter_release: string;
  valid_until: string; status: string; effective_authorization_state: string;
}>;

export type ExternalReport = Readonly<{
  id: string; campaign_id: string; snapshot_hash: string; title: string; source_kind?: string;
  status: string; version: number; freshness_status?: string; row_count?: number; created_at: string;
}>;
export type ExternalOperationalAlertInput = Readonly<{
  id: string; source_kind: string; source_id: string; source_version: number;
  signal_kind: string; severity: "info" | "warning" | "critical";
  reason_code: string; action_path: string; payload: Record<string, unknown>;
  input_hash: string; observed_at: string; created_at: string;
}>;
export type AttributionInventory = Readonly<{
  policies: Array<Readonly<{ id: string; version: number; last_click_days: number;
    assisted_days: number; status: string }>>;
  collectors: Array<Readonly<{ id: string; name: string; allowed_origins: string[];
    sdk_release: string; status: string }>>;
  counts: Record<string, number>;
  snapshots: Array<Readonly<{ id: string; cutoff_at: string; result_hash: string;
    created_at: string }>>;
}>;

export type ExternalOperationsData = Readonly<{
  connectors: ConnectorInventory;
  browser: BrowserInventory;
  browserAdmissionPolicies: BrowserAdmissionPolicy[];
  reports: ExternalReport[];
  operationalAlertInputs: ExternalOperationalAlertInput[];
  attribution: AttributionInventory;
  problems: Readonly<Record<string, LoadProblem | undefined>>;
}>;
