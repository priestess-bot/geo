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


def test_workflow_c_modules_stay_within_size_budget() -> None:
    for path in [
        *FEATURE.glob("*.ts"),
        *FEATURE.glob("*.tsx"),
        *FEATURE.glob("*.css"),
        *ROUTE.glob("*.tsx"),
    ]:
        assert len(source(path).splitlines()) < 600, path
