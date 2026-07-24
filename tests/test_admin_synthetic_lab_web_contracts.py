from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEATURE = (
    ROOT
    / "apps/admin-web/app/projects/[project_id]/features/synthetic-lab"
)


def source(name: str) -> str:
    return (FEATURE / name).read_text(encoding="utf-8")


def feature_source(*suffixes: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in FEATURE.iterdir()
        if path.suffix in suffixes
    )


def test_synthetic_loader_is_bounded_project_scoped_and_fail_closed() -> None:
    page = (FEATURE.parent.parent / "page.tsx").read_text(encoding="utf-8")
    shell = (FEATURE.parent / "project-workbench/WorkbenchShell.tsx").read_text(encoding="utf-8")
    tabs = (FEATURE.parent / "project-workbench/tabs.ts").read_text(encoding="utf-8")
    data = source("syntheticLabData.ts")
    types = source("syntheticLabTypes.ts")

    assert 'activeTab === "synthetic-lab" ? loadSyntheticLabWorkspace(projectId, query)' in page
    assert "SyntheticLabWorkspace" in shell
    assert "syntheticRuntimeUnavailable ? null : members.currentRole" in shell
    assert 'id: "synthetic-lab", label: "Synthetic Lab"' in tabs
    assert "const PAGE_SIZE = 100" in data
    assert "await Promise.all([" in data
    for path in (
        "/authorizations",
        "/style-sources",
        "/sample-import-previews",
        "/resource-inventory",
        "/style-profiles",
        "/review-suites",
        "/jobs/",
    ):
        assert path in data
    assert "synthetic_suite_id" in data
    assert "synthetic_job_id" in data
    assert "publication_eligible: false" in data
    assert "isSyntheticJob" in data
    for forbidden in (
        '"secret_value"',
        '"raw_text"',
        '"cookie"',
        '"storage_state"',
        '"model_response"',
        '"debug_trace"',
    ):
        assert forbidden in types


def test_every_synthetic_server_action_reauthorizes_membership_and_role() -> None:
    action_files = [
        "syntheticLabGovernanceActions.ts",
        "syntheticLabResourceActions.ts",
        "syntheticLabJobActions.ts",
    ]
    actions = "\n".join(source(name) for name in action_files)
    support = source("syntheticLabActionSupport.ts")
    exported_actions = [
        "createAuthorizationAction",
        "decideAuthorizationAction",
        "revokeAuthorizationAction",
        "reassessAuthorizationAction",
        "submitStyleProfileAction",
        "decideStyleProfileAction",
        "freezeStyleProfileAction",
        "freezeReviewSuiteAction",
        "createStyleSourceAction",
        "createManualImportPreviewAction",
        "approveManualImportPreviewAction",
        "createStyleProfileAction",
        "createReviewSuiteAction",
        "createReviewCaseAction",
        "admitStyleCollectionAction",
        "cancelSyntheticJobAction",
    ]

    for action in exported_actions:
        assert f"export async function {action}" in actions
    assert actions.count("await verifySyntheticActor(projectId") == len(exported_actions)
    assert 'runtimeRequest<AuthIdentity>("/v1/auth/me")' in support
    assert "isProjectMemberListResponse" in support
    assert 'item.status === "active"' in support
    assert "identity.data.project_ids.includes(projectId)" in support
    assert "allowedRoles.includes(membership.role)" in support
    assert 'field(formData, "actor_id")' not in actions
    assert "actor_id:" not in actions
    governance_forms = source("SyntheticLabGovernanceForms.tsx")
    assert 'name="allowed_purposes" type="checkbox" value="style_collection"' in governance_forms
    assert 'name="allowed_purposes" />' not in governance_forms


def test_manual_sample_intake_uses_governed_file_preview_and_independent_approval() -> None:
    forms = source("SyntheticLabResourceForms.tsx")
    actions = source("syntheticLabResourceActions.ts")

    for forbidden_input in (
        'name="raw_text"',
        'name="body"',
        'name="password"',
        'name="cookie"',
        'name="authorization"',
        'name="storage_state"',
    ):
        assert forbidden_input not in forms
    assert 'type="file"' in forms
    assert 'accept=".txt,.text,.csv,.jsonl,.ndjson' in forms
    assert "createManualImportPreviewAction" in actions
    assert "approveManualImportPreviewAction" in actions
    assert "await upload.arrayBuffer()" in actions
    assert "sample-import-previews" in actions
    assert 'selected_row_numbers' in forms
    assert 'au_english_verified' in forms
    assert 'anonymization_verified' in forms
    for forbidden_legacy in (
        "submitted_field_names",
        "normalized_text_hash",
        "source_artifact_hash",
        "language_reviewer_id",
        "language_reviewed_at",
        "import_request_id",
        "manifest_id",
        "collection_run_id",
    ):
        assert forbidden_legacy not in forms
        assert forbidden_legacy not in actions


def test_ui_covers_governance_review_generation_and_warning_contracts() -> None:
    workspace = source("SyntheticLabWorkspace.tsx")
    resources = source("SyntheticLabResourceForms.tsx")
    jobs = source("SyntheticLabJobForms.tsx")
    warnings = source("SyntheticLabWarnings.tsx")

    for marker in (
        "synthetic = true",
        "test_only = true",
        "publication_eligible = false",
        "Customer Portal 不读取、不展示且不可发布这些结果",
    ):
        assert marker in workspace
    for control in (
        "采集 Authorization",
        "Style Source 与人工样本",
        "Style Profile",
        "Review Suite / Case",
        "生成、修订、Corpus 与三臂实验",
    ):
        assert control in workspace
    assert "取消任务" in jobs
    assert "EnqueueSyntheticJobForm" not in jobs
    assert "enqueueSyntheticJobAction" not in jobs
    for forbidden_expert_input in (
        "Resource UUID",
        "Fact snapshot UUID",
        "Prompt Release UUID",
        "SHA-256",
    ):
        assert forbidden_expert_input not in resources
        assert forbidden_expert_input not in jobs
    assert "autonomous_scenario" in resources
    assert "guided_scenario" in resources
    for stratum in (
        "by_code",
        "by_channel",
        "by_scenario_mode",
        "by_competitor",
        "by_model",
        "by_question_cluster",
    ):
        assert stratum in warnings
    assert "不会将缺失证据记为 0" in warnings
    assert "<SyntheticLabWarnings />" in workspace


def test_ui_has_empty_loading_error_conflict_long_value_and_mobile_guards() -> None:
    workspace = source("SyntheticLabWorkspace.tsx")
    support = source("syntheticLabActionSupport.ts")
    styles = source("SyntheticLab.module.css")
    fixture = (
        ROOT / "tests/browser/fixtures/synthetic-lab-fixture.mjs"
    ).read_text(encoding="utf-8")

    assert "SyntheticLabLoading" in workspace
    assert "Synthetic Lab unavailable" in workspace
    assert "LoadProblem" in workspace
    assert "暂无 Style Source" in workspace
    assert "409" in support and "状态冲突" in support
    assert "extraordinarily-long-release-identity" in fixture
    assert "overflow-x: auto" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "word-break: break-word" in styles
    assert "table-layout: fixed" in styles
    assert "@media (max-width: 680px)" in styles


def test_synthetic_lab_remains_admin_only_and_has_no_browser_capture_command() -> None:
    all_feature = feature_source(".ts", ".tsx")
    customer = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "apps/customer-web").rglob("*")
        if path.suffix in {".ts", ".tsx"}
    )

    assert "playwright" not in all_feature.casefold()
    assert "browser-capture" not in all_feature
    assert "automatic_capture" not in all_feature
    assert "/synthetic-lab" not in customer
    assert "SyntheticLabWorkspace" not in customer


def test_synthetic_feature_modules_stay_within_size_budget() -> None:
    for path in [*FEATURE.glob("*.ts"), *FEATURE.glob("*.tsx")]:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 600, path
