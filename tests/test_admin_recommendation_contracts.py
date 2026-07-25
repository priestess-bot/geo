from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEATURE = (
    ROOT
    / "apps/admin-web/app/projects/[project_id]/features/recommendations"
)


def source(name: str) -> str:
    return (FEATURE / name).read_text(encoding="utf-8")


def test_recommendation_loader_uses_bounded_project_scoped_projection() -> None:
    page = (FEATURE.parent.parent / "page.tsx").read_text(encoding="utf-8")
    shell = (FEATURE.parent / "project-workbench/WorkbenchShell.tsx").read_text(encoding="utf-8")
    tabs = (FEATURE.parent / "project-workbench/tabs.ts").read_text(encoding="utf-8")
    data = source("recommendationData.ts")

    assert 'activeTab === "recommendations" ? loadRecommendationWorkspace(projectId, query)' in page
    assert "RecommendationWorkspace" in shell
    assert "recommendationRuntimeUnavailable ? null : members.currentRole" in shell
    assert 'id: "recommendations", label: "建议"' in tabs
    assert "const LIST_LIMIT = 200" in data
    assert "query: { limit: LIST_LIMIT, offset: 0 }" in data
    assert "`/v1/projects/${encodeURIComponent(projectId)}/recommendations`" in data
    assert "recommendation_status" in data
    assert "recommendation_type" in data
    assert "loadSelected(base, requestedId)" in data
    assert "selectedProblem" in data
    assert 'tab: "recommendations"' in data


def test_every_recommendation_action_reauthorizes_and_freezes_command_identity() -> None:
    actions = source("recommendationActions.ts")
    support = source("recommendationActionSupport.ts")
    exported_actions = [
        "submitRecommendationAction",
        "reviewRecommendationAction",
        "approveRecommendationAction",
        "rejectRecommendationAction",
        "expireRecommendationAction",
        "reconcileRecommendationStaleAction",
        "prepareRecommendationDraftAction",
    ]

    for action in exported_actions:
        assert f"export async function {action}" in actions
    assert actions.count("await verifyRecommendationActor(") == len(exported_actions)
    assert 'runtimeRequest<AuthIdentity>("/v1/auth/me")' in support
    assert "isProjectMemberListResponse" in support
    assert 'item.status === "active"' in support
    assert "identity.data.project_ids.includes(projectId)" in support
    assert 'integerField(formData, "expected_version")' in support
    assert 'field(formData, "idempotency_key")' in support
    assert "idempotencyKey:" in actions
    assert 'field(formData, "actor_id")' not in actions
    assert "actor_id:" not in actions


def test_recommendation_commands_cover_human_lifecycle_and_source_invalidation() -> None:
    commands = source("RecommendationCommands.tsx")
    actions = source("recommendationActions.ts")

    assert "useActionState" in commands
    assert "useEffect" not in commands
    for label in [
        "提交审核",
        "记录当前证据审核",
        "批准并创建草稿",
        "拒绝建议",
        "过期并阻断未启动草稿",
        "核对并同步失效状态",
        "执行前复核来源",
    ]:
        assert label in commands
    for status in ["draft", "in_review", "approved"]:
        assert status in commands
    assert '"stale",' in source("recommendationTypes.ts")
    assert '"expired"' in source("recommendationTypes.ts")
    assert "current_inputs" not in commands
    assert "current_inputs" not in actions
    assert "由服务端" in commands
    assert "change_reason" in commands
    assert "cancelled_outbox_ids" in actions
    assert "reconcile-stale" in actions
    assert "prepare-action" in actions


def test_recommendation_generation_uses_selectors_and_governed_job_api_only() -> None:
    workspace = source("RecommendationWorkspace.tsx")
    panel = source("RecommendationGenerationPanel.tsx")
    action = source("recommendationGenerationAction.ts")
    data = source("recommendationData.ts")

    assert "RecommendationGenerationPanel" in workspace
    assert "evidence_selectors" in panel
    assert "prompt_binding_id" in action
    assert "runtime_selection_id" in action
    assert "adapter_release_id" not in action
    assert "model_release_id" not in action
    assert "/recommendations/generation-jobs" in action
    assert "/prompt-program-bindings" in data
    assert "/model-gateway/options" in data
    assert "无已批准运行时" in panel
    assert "Prompt Binding ID" not in panel
    assert 'label="Provider"' not in panel
    assert "approved" not in action
    assert "current_inputs" not in action
    for forbidden in ["/claim", "/lease", "/heartbeat", "/execute"]:
        assert forbidden not in action


def test_evidence_workspace_exposes_graph_hashes_input_versions_and_all_ref_groups() -> None:
    evidence = source("EvidenceGraphPanel.tsx")
    workspace = source("RecommendationWorkspace.tsx")
    types = source("recommendationTypes.ts")
    guards = source("recommendationTypeGuards.ts")

    for field in [
        "evidence_graph_hash",
        "input_fingerprint",
        "input_versions",
        "applicable_version",
        "impact_chain",
        "counterevidence",
        "validation_plan",
        "stale_conditions",
    ]:
        assert field in evidence
    for group in [
        "observations",
        "metric_comparisons",
        "facts",
        "rules",
        "prompt_releases",
        "model_calls",
        "contents",
        "questions",
        "surfaces",
    ]:
        assert group in evidence
    assert "frozen_input_fingerprint" in workspace
    assert "frozen_evidence_graph_hash" in workspace
    assert "isObservationRef" in guards
    assert "isMetricComparisonRef" in guards
    assert "isModelCallRef" in guards
    assert "booleanFields" in guards
    assert 'DraftStatus = "draft" | "started" | "blocked_source_stale" | "blocked_source_expired"' in types


def test_approved_recommendations_remain_draft_only_and_never_offer_execution() -> None:
    actions = source("recommendationActions.ts")
    commands = source("RecommendationCommands.tsx")
    workspace = source("RecommendationWorkspace.tsx")
    all_ui = f"{actions}\n{commands}\n{workspace}"

    assert "draft_only_unstarted" in source("recommendationTypes.ts")
    assert "source_checked_draft_only" in source("recommendationTypes.ts")
    assert "批准只创建未启动草稿" in commands
    assert "不会自动排队、执行或发布" in commands
    assert "draft.enqueued" in workspace
    assert "draft.executed" in workspace
    assert "draft.published" in workspace
    assert '"/execute"' not in all_ui
    assert '"/publish"' not in all_ui
    assert "executeRecommendationAction" not in all_ui
    assert "publishRecommendationAction" not in all_ui


def test_recommendation_layout_handles_empty_errors_long_lineage_and_mobile() -> None:
    workspace = source("RecommendationWorkspace.tsx")
    feedback = source("RecommendationActionFeedback.tsx")
    styles = source("Recommendations.module.css")

    assert "当前筛选没有结果" in workspace
    assert "暂无建议" in workspace
    assert "problem.detail" in workspace
    assert "problem.correlationId" in workspace
    assert "state.correlationId" in feedback
    assert "overflow-x: auto" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "word-break: break-word" in styles
    assert "table-layout: fixed" in styles
    assert "@media (max-width: 760px)" in styles


def test_recommendation_browser_fixture_preserves_draft_only_and_fail_closed_contracts() -> None:
    fixture = (
        ROOT / "tests/browser/fixtures/recommendation-fixture.mjs"
    ).read_text(encoding="utf-8")
    browser = (
        ROOT / "tests/browser/admin-recommendations.spec.ts"
    ).read_text(encoding="utf-8")

    assert 'action_boundary: "draft_only_unstarted"' in fixture
    assert 'action_boundary: "source_checked_draft_only"' in fixture
    assert 'enqueued: false' in fixture
    assert 'executed: false' in fixture
    assert 'published: false' in fixture
    assert 'mode === "partial-unavailable"' in fixture
    assert 'width: 390' in browser
    assert "toBeDisabled()" in browser
    assert "/(execute|publish)$" in browser


def test_recommendation_typescript_modules_stay_within_size_budget() -> None:
    for path in [*FEATURE.glob("*.ts"), *FEATURE.glob("*.tsx")]:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 600, path
