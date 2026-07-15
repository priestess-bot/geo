from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEMBER_ROOT = ROOT / "apps/admin-web/app/projects/[project_id]"


def source(name: str) -> str:
    return (MEMBER_ROOT / name).read_text(encoding="utf-8")


def test_admin_member_ui_uses_only_stable_internal_contracts() -> None:
    page = source("page.tsx")
    data = source("memberData.ts")
    actions = source("memberActions.ts")

    assert "MemberGovernancePanel" in page
    assert "loadProjectMembers" in page
    assert 'activeTab === "entry"' in page
    assert "/v1/project-members/runtime" not in page
    assert "/v1/project-members/runtime" not in actions
    assert "/v1/projects/${encodeURIComponent(projectId)}/members" in data
    assert "/v1/projects/${encodeURIComponent(projectId)}/members" in actions
    assert 'runtimeRequest<AuthIdentity>("/v1/auth/me")' in data


def test_member_mutations_are_server_only_typed_and_idempotent() -> None:
    actions = source("memberActions.ts")
    types = source("memberTypes.ts")

    assert actions.startswith('"use server";')
    assert "function idempotencyKey(formData: FormData)" in actions
    assert "idempotencyKey" in actions
    assert "AddProjectMemberRequest" in actions
    assert "ChangeProjectMemberRoleRequest" in actions
    assert "ProjectMemberMutationResponse" in actions
    assert "isProjectMemberMutationResponse" in actions
    assert "actor" not in actions.lower()
    assert "NEXT_PUBLIC" not in actions
    assert "export type ProjectMemberSummary" in types
    assert "export type ProjectMemberListResponse" in types
    assert "items: ProjectMemberSummary[]" in types
    assert "isProjectMemberListResponse" in types
    assert 'kind: "idle" | "success" | "error"' in types


def test_member_ui_covers_permissions_and_operational_states() -> None:
    panel = source("MemberGovernancePanel.tsx")
    row = source("MemberRow.tsx")
    add = source("AddMemberForm.tsx")
    feedback = source("MemberActionFeedback.tsx")
    loading = source("loading.tsx")

    assert "data.currentRole === \"owner\" || data.currentRole === \"admin\"" in panel
    assert "problemTitle" in panel
    assert "暂无成员记录" in panel
    assert "isLastOwner" in row
    assert "isLastSelfManager" in row
    assert "canTargetRole" in row
    assert "disabled={!canRevoke || commandPending}" in row
    assert 'role === "owner" && actorRole !== "owner"' in add
    assert 'state.kind === "error" ? "alert" : "status"' in feedback
    assert 'aria-busy="true"' in loading


def test_new_member_files_stay_within_module_size_limit() -> None:
    names = (
        "AddMemberForm.tsx",
        "MemberActionFeedback.tsx",
        "MemberGovernancePanel.tsx",
        "MemberRow.tsx",
        "memberActions.ts",
        "memberData.ts",
        "memberTypes.ts",
    )
    for name in names:
        assert len(source(name).splitlines()) < 600, name
