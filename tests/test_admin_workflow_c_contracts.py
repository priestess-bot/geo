from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "apps/admin-web/app/projects/[project_id]"
FEATURE = PROJECT / "features/workflow-c"
ROUTE = PROJECT / "workflow-c"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def feature_source() -> str:
    return "\n".join(
        source(path)
        for path in [*FEATURE.glob("*.ts"), *FEATURE.glob("*.tsx")]
    )


def test_workflow_c_uses_an_independent_internal_admin_route() -> None:
    project_page = source(PROJECT / "page.tsx")
    project_shell = source(PROJECT / "features/project-workbench/WorkbenchShell.tsx")
    project_tabs = source(PROJECT / "features/project-workbench/tabs.ts")
    page = source(ROUTE / "page.tsx")
    data = source(FEATURE / "workflowCData.ts")
    workspace = source(FEATURE / "WorkflowCWorkspace.tsx")

    assert "loadWorkflowCWorkspace(projectId, query)" in page
    assert 'redirect("/login")' in page
    assert "WorkflowCWorkspace" in page
    assert 'activeTab === "measurement" ? loadWorkflowCWorkspace(projectId, query)' in project_page
    assert 'workflowCData?.alerts.problem?.status === 401' in project_page
    assert "WorkflowCPanel" in project_shell
    assert 'id: "measurement", label: "Measurement & Alerts"' in project_tabs
    assert "export function WorkflowCPanel" in workspace
    assert "export type WorkflowCPanelProps" in workspace
    assert '<main className={styles.shell}>' in workspace
    assert "!data.alerts.problem" in workspace
    assert 'label="Workflow C control plane"' in workspace
    assert "Promise.all" in data
    for projection in [
        "/sampling/runs/",
        "/analysis/semantic-metrics/",
        "/analysis/comparisons/",
        "/analysis/drift/",
        "/alerts",
    ]:
        assert projection in data
    assert "/connectors" not in data
    assert "/attribution" not in data


def test_sampling_keeps_a_fixed_denominator_and_supported_capture_methods() -> None:
    panel = source(FEATURE / "SamplingPanel.tsx")
    types = source(FEATURE / "workflowCTypes.ts")
    guards = source(FEATURE / "workflowCTypeGuards.ts")

    for label in ["Planned", "Valid", "Invalid", "Missing", "Valid completion"]:
        assert f'label="{label}"' in panel
    assert "denominator_hash" in panel
    assert '"provider_api" | "proxy_grounded_api" | "manual_ui"' in types
    assert 'new Set(["provider_api", "proxy_grounded_api", "manual_ui"])' in guards
    assert "automated_ui" not in feature_source()
    assert '"lease_token", "lease_owner", "lease_expires_at", "fencing_generation"' in guards
    assert "lease_token" not in panel
    assert "lease_owner" not in panel
    assert "fencing_generation" not in panel
    assert "answer_text" not in panel
    assert "derived_summary" in panel


def test_manual_consumer_surface_parsers_stay_non_live_and_text_free() -> None:
    commands = source(FEATURE / "ManualEvidenceCommands.tsx")
    actions = source(FEATURE / "samplingActions.ts")
    data = source(FEATURE / "workflowCData.ts")
    guards = source(FEATURE / "workflowCTypeGuards.ts")

    assert "/sampling/surface-parser-releases" in data
    assert 'name="surface_parser_release_id"' in commands
    assert "releaseMatchesSource" in commands
    assert "Non-live evidence · no Australian egress proof" in commands
    assert "answer_character_count" in commands
    assert "citation_count" in commands
    assert "summary_hash" in commands
    assert "surface_parser_release_id: surfaceParserReleaseId || null" in actions
    assert 'evidenceKind !== "transcript_export"' in actions
    assert 'contentType !== "application/json"' in actions
    assert "item.automated_capture_eligible === false" in guards
    assert "value.live_capture_eligible === false" in guards
    for forbidden in ["answer_text", "citations", "citation_urls", "raw_artifact_uri"]:
        assert f'"{forbidden}"' in guards


def test_sampling_run_purpose_is_resolved_from_the_governed_inventory() -> None:
    commands = source(FEATURE / "SamplingCommands.tsx")
    actions = source(FEATURE / "samplingActions.ts")

    assert 'name="purpose"' not in commands
    assert "由 Suite 的已批准 Admission Policy 冻结" in commands
    assert "isSamplingSuitePage" in actions
    assert "isAdmissionPolicyPage" in actions
    assert 'item.status === "approved"' in actions
    assert 'item.effective_authorization_state === "approved"' in actions
    assert "purposes.length !== 1" in actions


def test_analysis_preserves_all_five_conclusions_and_explainable_evidence() -> None:
    panels = source(FEATURE / "AnalysisPanels.tsx")
    types = source(FEATURE / "workflowCTypes.ts")

    for conclusion in [
        "win",
        "equivalent",
        "loss",
        "inconclusive",
        "insufficient_evidence",
    ]:
        assert f'"{conclusion}"' in types
        assert f'"{conclusion}"' in panels
    assert 'if (value === "equivalent") return "达到等效门槛"' in source(
        FEATURE / "WorkflowCWorkspace.tsx"
    )
    assert 'if (value === "inconclusive") return "不确定"' in source(
        FEATURE / "WorkflowCWorkspace.tsx"
    )
    for field in [
        "negative_gain",
        "worst_question_id",
        "evidence_locators",
        "model_drift",
        "source_drift",
        "effect_drift",
    ]:
        assert field in panels


def test_report_diversity_metrics_require_integer_counts_across_admin_boundaries() -> None:
    actions = source(FEATURE / "workflowCReportActions.ts")
    guards = source(FEATURE / "workflowCControlTypeGuards.ts")
    commands = source(FEATURE / "WorkflowCReportCommands.tsx")

    assert "isWorkflowCReportMetricValue(key, value)" in actions
    assert 'value.length > 64 || !DECIMAL_PATTERN.test(value)' in guards
    assert "fractionalPartIsZero" in guards
    assert "const nonNegative = !negative || decimalIsZero" in guards
    assert "magnitudeAtMostOne" in guards
    assert 'step: "1", label: "Nonnegative integer count"' in commands


def test_alert_actions_reauthorize_membership_and_cover_lifecycle() -> None:
    actions = source(FEATURE / "workflowCActions.ts")
    support = source(FEATURE / "workflowCActionSupport.ts")
    commands = source(FEATURE / "AlertCommands.tsx")

    for action in [
        "acknowledgeWorkflowCAlertAction",
        "suppressWorkflowCAlertAction",
        "unsuppressWorkflowCAlertAction",
        "resolveWorkflowCAlertAction",
    ]:
        assert f"export async function {action}" in actions
    assert 'runtimeRequest<AuthIdentity>("/v1/auth/me")' in support
    assert "/members`" in support
    assert "identity.data.project_ids.includes(projectId)" in support
    assert 'item.status === "active"' in support
    assert "offset < firstMembers.data.total" in support
    assert "await verifyWorkflowCActor" in actions
    assert "idempotencyKey:" in actions
    for label in ["确认", "抑制", "解除抑制", "解决"]:
        assert label in commands


def test_alert_inbox_exposes_evidence_dispositions_and_safe_notifications() -> None:
    inbox = source(FEATURE / "AlertInbox.tsx")
    guards = source(FEATURE / "workflowCTypeGuards.ts")

    for label in [
        "Immutable lineage",
        "处置历史",
        "Outbox projection",
        "Admin inbox",
        "Local SMTP",
        "Internal Webhook",
    ]:
        assert label in inbox
    assert "payload_hash" in inbox
    assert "command_hash" in inbox
    assert "Safe summary" in inbox
    assert "admin_inbox" in guards
    assert "local_smtp" in guards
    assert "internal_webhook" in guards


def test_workflow_c_has_loading_error_empty_long_text_and_mobile_guards() -> None:
    main_styles = source(FEATURE / "WorkflowC.module.css")
    alert_styles = source(FEATURE / "WorkflowCAlerts.module.css")
    route_states = source(ROUTE / "loading.tsx") + source(ROUTE / "error.tsx")

    assert 'aria-busy="true"' in route_states
    assert "reset" in route_states
    assert "暂无可展示记录" in source(FEATURE / "WorkflowCWorkspace.tsx")
    assert "overflow-x: auto" in main_styles
    assert "overflow-wrap: anywhere" in main_styles
    assert "word-break: break-word" in main_styles
    assert "table-layout: fixed" in main_styles
    assert "@media (max-width: 620px)" in main_styles
    assert "@media (max-width: 620px)" in alert_styles


def test_protocol_job_and_report_controls_use_internal_guarded_contracts() -> None:
    data = source(FEATURE / "workflowCData.ts")
    workspace = source(FEATURE / "WorkflowCWorkspace.tsx")
    protocol_actions = source(FEATURE / "workflowCProtocolActions.ts")
    job_actions = source(FEATURE / "workflowCAnalysisJobActions.ts")
    report_actions = source(FEATURE / "workflowCReportActions.ts")
    report_commands = source(FEATURE / "WorkflowCReportCommands.tsx")
    guards = source(FEATURE / "workflowCControlTypeGuards.ts")

    for endpoint in [
        "/analysis/metric-protocols",
        "/analysis/statistical-protocols",
        "/analysis/reports",
    ]:
        assert endpoint in data
    assert 'protocols: "协议与任务"' in workspace
    assert 'reports: "报告"' in workspace
    assert "await verifyWorkflowCActor" in protocol_actions
    assert "expected_aggregate_version" in protocol_actions
    for path in ["semantic-metrics/jobs", '"comparisons"', '"drift"', "${path}/jobs"]:
        assert path in job_actions
    assert "isSemanticMetricsJobReceipt" in job_actions
    assert "isStatisticalAnalysisJobReceipt" in job_actions
    assert "approved_safe_payload: payload.value" in report_actions
    assert 'name="approved_safe_payload"' not in report_commands
    assert 'name="definition"' not in source(FEATURE / "WorkflowCProtocolCommands.tsx")
    assert "workflowCReportMetricKeys.map" in report_commands
    assert "onlyKeys(value, safePayloadKeys)" in guards
    assert "reportMetricKeys.has(key)" in guards
    for forbidden in ["access_token", "raw_text", "system_prompt"]:
        assert forbidden not in report_commands
    assert "headline.length > 200" in report_actions
    assert 'maxLength={200}' in report_commands
    assert "isWorkflowCReportMetricValue(key, value)" in report_actions
    assert "countMetricKeys.has(key)" in guards
    assert "signedMetricKeys.has(key)" in guards
    assert "magnitudeAtMostOne" in guards
    assert "Nonnegative integer count" in report_commands
    assert "Signed score · -1 to 1" in report_commands
    assert "Rate / score · 0 to 1" in report_commands


def test_protocol_and_report_maker_checker_buttons_are_identity_aware() -> None:
    protocols = source(FEATURE / "WorkflowCProtocolCommands.tsx")
    reports = source(FEATURE / "WorkflowCReportCommands.tsx")
    data = source(FEATURE / "workflowCData.ts")

    assert 'protocol.created_by === actorId' in protocols
    assert 'currentIdentityId === report.actor_id' in reports
    assert "currentIdentityId: membership?.identity_id || null" in data
    assert "需其他审批人" in protocols
    assert "需其他审批人" in reports


def test_workflow_c_modules_stay_within_size_budget() -> None:
    for path in [
        *FEATURE.glob("*.ts"),
        *FEATURE.glob("*.tsx"),
        *FEATURE.glob("*.css"),
        *ROUTE.glob("*.tsx"),
    ]:
        assert len(source(path).splitlines()) < 600, path
