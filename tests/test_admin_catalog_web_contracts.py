from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "apps/admin-web/app/projects"
DETAIL = ADMIN / "[project_id]"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_project_list_and_create_use_only_stable_project_contract() -> None:
    listing = source(ADMIN / "page.tsx")
    create = source(ADMIN / "new/actions.ts")

    assert 'runtimeRequest<ProjectListResponse>("/v1/projects"' in listing
    assert 'runtimeRequest<CatalogProject>("/v1/projects"' in create
    assert 'method: "POST"' in create
    assert "/v1/projects/runtime" not in listing + create
    assert "invitation" not in create.lower()
    assert "fixture" not in listing.lower() + create.lower()
    assert create.startswith('"use server";')


def test_detail_loads_and_mutates_only_stable_catalog_resources() -> None:
    page = source(DETAIL / "page.tsx")
<<<<<<< HEAD
    shell = source(DETAIL / "features/project-workbench/WorkbenchShell.tsx")
    tabs = source(DETAIL / "features/project-workbench/tabs.ts")
    data = source(DETAIL / "catalogData.ts")
    actions = source(DETAIL / "catalogActions.ts")
    combined = page + shell + tabs + data + actions
=======
    data = source(DETAIL / "catalogData.ts")
    actions = source(DETAIL / "catalogActions.ts")
    combined = page + data + actions
>>>>>>> codex/remediation-access

    assert "Promise.all" in page
    assert "loadCatalog" in page
    assert "loadProjectInvitations" in page
    assert "loadProjectMembers" in page
<<<<<<< HEAD
    assert "loadGeoWorkspace" in page
    for label in ("基础配置", "用户入口", "Prompt", "知识库", "运营工作台", "GEO 投放", "项目状态", "全流程测试"):
        assert label in tabs + shell
=======
>>>>>>> codex/remediation-access
    assert "`/v1/projects/${encodeURIComponent(projectId)}`" in data
    for suffix in ("/entities", "/market-profiles", "/evidence-items"):
        assert suffix in data
        assert suffix in actions
    assert 'method: "PATCH"' in actions
    assert 'method: "POST"' in actions
    assert "/v1/projects/runtime" not in combined
    assert "/v1/knowledge/" not in combined
    assert "fixture" not in combined.lower()
    assert "connector" not in combined.lower()
    assert "manual-distribution" not in combined.lower()
    assert actions.startswith('"use server";')
    assert "adminActorId" not in actions
    assert "NEXT_PUBLIC" not in actions


def test_catalog_ui_covers_governance_and_error_states() -> None:
    actions = source(DETAIL / "catalogActions.ts")
    feedback = source(DETAIL / "CatalogActionFeedback.tsx")
    evidence = source(DETAIL / "EvidenceCreateForm.tsx")
    invitation_actions = source(DETAIL / "invitationActions.ts")
    invitation_forms = source(DETAIL / "InvitationForms.tsx")

    for status in ("401", "403", "409", "422"):
        assert status in actions
        assert status in feedback
    assert "createHash" in actions
    assert 'kind: "text"' in actions
    assert "真实消费者使用描述" in evidence
    assert invitation_actions.startswith('"use server";')
    assert "idempotencyKey" in invitation_actions
    assert 'name="idempotency_key"' in invitation_forms
    assert "rawInviteToken" in invitation_forms
    assert "localStorage" not in invitation_forms
    assert "sessionStorage" not in invitation_forms


<<<<<<< HEAD
def test_project_workbench_is_restored_without_legacy_giant_files() -> None:
    assert not (DETAIL / "ProjectActions.tsx").exists()
    assert not (DETAIL / "actions.ts").exists()
    assert not (ADMIN / "status.ts").exists()
    assert not (DETAIL / "geo/page.tsx").exists()
    assert not (DETAIL / "geo/loading.tsx").exists()
    assert not (DETAIL / "geo/error.tsx").exists()
=======
def test_legacy_admin_project_workbench_is_removed_and_files_are_bounded() -> None:
    assert not (DETAIL / "ProjectActions.tsx").exists()
    assert not (DETAIL / "actions.ts").exists()
    assert not (ADMIN / "status.ts").exists()
>>>>>>> codex/remediation-access
    assert 'aria-busy="true"' in source(ADMIN / "loading.tsx")
    assert 'aria-busy="true"' in source(ADMIN / "new/loading.tsx")
    assert 'aria-busy="true"' in source(DETAIL / "loading.tsx")
    assert len(source(DETAIL / "page.tsx").splitlines()) < 300
    for path in ADMIN.rglob("*.ts*"):
        if "/geo/" in path.as_posix():
            continue
        assert len(source(path).splitlines()) < 600, path
