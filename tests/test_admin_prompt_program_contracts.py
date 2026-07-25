from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "apps/admin-web/app/projects/[project_id]"
PROMPT = PROJECT / "features/prompt-programs"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_prompt_program_tab_loads_only_its_minimal_workspace_projection() -> None:
    page = source(PROJECT / "page.tsx")
    shell = source(PROJECT / "features/project-workbench/WorkbenchShell.tsx")
    tabs = source(PROJECT / "features/project-workbench/tabs.ts")
    data = source(PROMPT / "promptProgramData.ts")

    assert 'activeTab === "prompts" ? loadPromptWorkspace(projectId, query)' in page
    assert "await Promise.all([" in page
    assert "PromptProgramWorkspace" in shell
    assert 'id: "prompts", label: "Prompt 程序"' in tabs
    assert "limit: PROGRAM_PAGE_SIZE, offset" in data
    assert "const [programResponse, response] = await Promise.all([" in data
    assert "programsProblem" in data and "releasesProblem" in data
    assert (
        "let [programsResponse, bootstrapResponse, runtimesResponse, bindingsResponse] = await Promise.all"
        in data
    )
    assert "/prompt-program-test-options`" in data
    assert "/prompt-bootstrap`" in data
    assert "isPromptBootstrapCatalog" in data


def test_prompt_bootstrap_catalog_is_strict_draft_only_and_idempotently_retryable() -> None:
    types = source(PROMPT / "promptBootstrapTypes.ts")
    actions = source(PROMPT / "promptBootstrapActions.ts")
    panel = source(PROMPT / "PromptBootstrapCatalog.tsx")
    controls = source(PROMPT / "PromptBootstrapActions.tsx")

    assert "items.length !== promptProgramKinds.length" in types
    assert "value.fixtures.length === 5" in types
    assert 'value.release.state.status === "draft"' in types
    assert 'action_boundary === "draft_only_no_approval_freeze_binding"' in types
    assert actions.count("await verifyPromptActor(projectId, MANAGERS)") == 2
    assert '`${bootstrapBase(projectId)}/evaluate`' in actions
    assert '`${bootstrapBase(projectId)}/drafts`' in actions
    assert "idempotencyKey" in actions
    assert "revalidatePath" not in actions
    assert "目录不是批准结果" in panel
    assert "只创建 v1 草稿" in panel
    assert "使用同一键重试失败项" in controls
    assert "发布版本状态：草稿 · 未批准" in controls
    assert "approvePrompt" not in controls + actions
    assert "freezePrompt" not in controls + actions
    assert "bindPrompt" not in controls + actions


def test_prompt_bootstrap_browser_covers_partial_failure_long_error_empty_and_mobile() -> None:
    browser = source(ROOT / "tests/browser/admin-prompt-bootstrap.spec.ts")
    fixture = source(ROOT / "tests/browser/fixtures/prompt-bootstrap-fixture.mjs")

    assert "尚无本次创建结果" in browser
    assert "partial_failure" in browser
    assert "Fixture persistence was interrupted" in browser
    assert 'width: 390' in browser
    assert "document.documentElement.scrollWidth" in browser
    assert "lastIdempotencyKey" in fixture
    assert 'status: "draft"' in fixture
    assert "LONG_FAILURE" in fixture


def test_every_prompt_server_action_reauthorizes_project_actor_and_uses_guards() -> None:
    actions = source(PROMPT / "promptProgramActions.ts")
    support = source(PROMPT / "promptProgramActionSupport.ts")

    exported_actions = [
        "createPromptProgramAction",
        "createPromptReleaseAction",
        "enqueuePromptTestAction",
        "approvePromptReleaseAction",
        "freezePromptReleaseAction",
        "retirePromptReleaseAction",
        "bindPromptReleaseAction",
        "diffPromptReleaseAction",
    ]
    for action in exported_actions:
        assert f"export async function {action}" in actions
    assert actions.count("await verifyPromptActor(projectId") == len(exported_actions)
    assert 'runtimeRequest<AuthIdentity>("/v1/auth/me")' in support
    assert "isProjectMemberListResponse" in support
    assert "item.status === \"active\"" in support
    assert "identity.data.project_ids.includes(projectId)" in support
    assert "idempotencyKey" in actions
    assert 'field(formData, "actor_id")' not in actions


def test_prompt_controls_cover_release_lifecycle_and_do_not_derive_state_in_effects() -> None:
    editor = source(PROMPT / "PromptReleaseEditorForm.tsx")
    commands = source(PROMPT / "PromptReleaseCommands.tsx")
    feedback = source(PROMPT / "PromptActionFeedback.tsx")
    actions = source(PROMPT / "promptProgramActions.ts")

    assert "useActionState" in editor and "useActionState" in commands
    assert "useEffect" not in editor and "useEffect" not in commands
    assert '<option disabled value="reference_translation">' in editor
    assert '<optgroup label="主类型（业务）">' in editor
    assert '<optgroup label="内部辅助（系统工作流）">' in editor
    assert "用途（由 Prompt 程序类型固定）" in editor
    assert "固定测试集（目录）" in editor
    assert 'name="purpose" type="hidden"' in editor
    assert 'name="test_set_id" type="hidden"' in editor
    assert 'name="test_set_hash" type="hidden"' in editor
    assert "pattern={" not in editor
    assert "verifyBootstrapSelection" in actions
    assert "verifyBindingSelection" in actions
    assert 'programResponse.data.program_kind !== kind' in actions
    assert 'inventory.test_set_hash !== release.test_set_hash' in actions
    assert 'name="purpose" type="hidden" value={release.purpose}' in commands
    assert "用途（由冻结发布版本固定）" in commands
    assert 'defaultValue={release.purpose} name="purpose"' not in commands
    assert "authoritativeVersion !== expectedVersion" in actions
    for label in [
        "运行固定测试集",
        "批准",
        "冻结",
        "退役发布版本",
        "绑定冻结发布版本",
        "比较版本",
    ]:
        assert label in commands
    assert "pending" in editor and "disabled={formDisabled}" in editor
    assert "409" in source(PROMPT / "promptProgramActionSupport.ts")
    assert "422" in source(PROMPT / "promptProgramActionSupport.ts")
    assert "fixed_input_hash" in feedback
    assert "fixed_variables" not in feedback
    assert "diffColumns" in feedback
    assert "Output Artifact reference" not in commands
    assert "output_artifact_ref" not in actions
    assert "output_hash" not in actions
    assert 'name="runtime_selection_id"' in commands
    assert "runtime_selection_id: runtimeSelectionId" in actions
    assert "无已批准运行时" in commands
    assert "当前项目没有支持 Prompt 固定测试的已批准运行时" in commands
    for legacy in (
        'name="runtime_manifest_id"',
        'name="provider"',
        'name="adapter_release_id"',
        'name="model_release_id"',
    ):
        assert legacy not in commands


def test_prompt_read_models_and_lists_never_include_raw_templates_or_fixed_input() -> None:
    types = source(PROMPT / "promptProgramTypes.ts")
    workspace = source(PROMPT / "PromptProgramWorkspace.tsx")
    release_contract = types.split("export type PromptProgramRelease", 1)[1].split(">;", 1)[0]

    assert "system_template:" not in release_contract
    assert "user_template:" not in release_contract
    assert "system_template_hash:" in release_contract
    assert "user_template_hash:" in release_contract
    assert "fixed_variables" not in workspace
    assert "release.release_hash" in workspace
    assert "release.state.evidence_ref" in workspace


def test_prompt_layout_contains_explicit_overflow_and_mobile_guards() -> None:
    styles = source(PROMPT / "PromptPrograms.module.css")

    assert "overflow-x: auto" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "word-break: break-word" in styles
    assert "table-layout: fixed" in styles
    assert "@media (max-width: 680px)" in styles
