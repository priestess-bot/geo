from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "apps/admin-web/app/projects/[project_id]"
SECRET = PROJECT / "features/secret-store"
FIXTURE = ROOT / "tests/browser/fixtures/admin-geo-api.mjs"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_secret_store_tab_loads_reference_and_audit_metadata_in_parallel() -> None:
    page = source(PROJECT / "page.tsx")
    shell = source(PROJECT / "features/project-workbench/WorkbenchShell.tsx")
    tabs = source(PROJECT / "features/project-workbench/tabs.ts")
    data = source(SECRET / "secretStoreData.ts")

    assert 'activeTab === "secrets" ? loadSecretWorkspace(projectId, query)' in page
    assert "SecretStoreWorkspace" in shell
    assert 'id: "secrets", label: "密钥库"' in tabs
    assert "let [referencesResponse, auditsResponse, selectedResponse] = await Promise.all" in data
    assert "SecretReferencePage" in data and "SecretAuditPage" in data
    assert "lastPageOffset" in data


def test_every_secret_action_reauthorizes_and_never_forwards_upstream_error_detail() -> None:
    actions = source(SECRET / "secretStoreActions.ts")
    support = source(SECRET / "secretStoreActionSupport.ts")
    names = [
        "createSecretReferenceAction",
        "stageSecretRotationAction",
        "verifySecretVersionAction",
        "activateSecretVersionAction",
        "revokeSecretVersionAction",
    ]

    for name in names:
        assert f"export async function {name}" in actions
    assert actions.count("await verifySecretActor(projectId)") == len(names)
    assert 'runtimeRequest<AuthIdentity>("/v1/auth/me")' in support
    assert "isProjectMemberListResponse" in support
    assert 'membership.role !== "owner" && membership.role !== "admin"' in support
    assert "response.error" not in support
    assert "Secret Store unavailable" in support
    assert "status === 409" in support and "status === 422" in support


def test_secret_value_is_write_only_bounded_and_cleared_without_client_state() -> None:
    forms = source(SECRET / "SecretStoreForms.tsx")
    support = source(SECRET / "secretStoreActionSupport.ts")
    types = source(SECRET / "secretStoreTypes.ts")

    assert 'type="password"' in forms
    assert 'autoComplete="new-password"' in forms
    assert "maxLength={SECRET_MAX_BYTES}" in forms
    assert 'key={inputKey}' in forms
    assert "useState" not in forms and "useEffect" not in forms
    assert 'formData.get("secret_value")' in support
    assert 'Buffer.byteLength(value, "utf8")' in support
    assert "SECRET_MAX_BYTES" in support
    action_state = types.split("export type SecretActionState", 1)[1].split(">;", 1)[0]
    assert "secret_value" not in action_state
    assert "plaintext" not in action_state
    assert "ciphertext" not in action_state


def test_create_uses_server_generated_reference_and_governed_purpose_options() -> None:
    forms = source(SECRET / "SecretStoreForms.tsx")
    actions = source(SECRET / "secretStoreActions.ts")
    types = source(SECRET / "secretStoreTypes.ts")

    assert 'name="reference_id"' not in forms.split(
        "export function SecretLifecycleForms", 1
    )[0]
    assert 'name="purpose"' in forms and "<select" in forms
    assert "SECRET_PURPOSE_GROUPS" in forms
    assert "model_provider.openai" in types
    assert "egress.proxy.australia" in types
    create_action = actions.split("export async function stageSecretRotationAction", 1)[0]
    assert 'field(formData, "reference_id")' not in create_action
    assert "reference_id:" not in create_action
    assert "response.data.reference_id" in create_action


def test_secret_workspace_covers_two_person_lifecycle_and_fail_closed_states() -> None:
    forms = source(SECRET / "SecretStoreForms.tsx")
    workspace = source(SECRET / "SecretStoreWorkspace.tsx")

    for label in [
        "验证 Canary",
        "第二人激活",
        "暂存新版本",
        "撤销版本",
    ]:
        assert label in forms
    assert "version_verified" in forms
    assert "version_activated" in forms
    assert "aggregate_version" in forms
    assert "密钥库暂不可用" in workspace
    assert "current_version" in workspace
    assert "master_key_version" in workspace
    assert "fingerprint" in workspace


def test_browser_fixture_redacts_secret_before_request_logging() -> None:
    fixture = source(FIXTURE)

    assert "body: loggedRequestBody(path, payload)" in fixture
    assert 'key === "secret_value" ? "[REDACTED]"' in fixture
    assert "Secret creator cannot activate the same version" in fixture
    assert "secretUnavailable" in fixture


def test_secret_files_stay_bounded_and_layout_guards_long_metadata() -> None:
    styles = source(SECRET / "SecretStore.module.css")

    for path in SECRET.iterdir():
        if path.suffix in {".ts", ".tsx", ".css"}:
            assert len(source(path).splitlines()) < 600, path
    assert "overflow-x: auto" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "word-break: break-word" in styles
    assert "@media (max-width: 680px)" in styles
