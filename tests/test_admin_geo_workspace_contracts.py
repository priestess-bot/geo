from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GEO_ROOT = ROOT / "apps/admin-web/app/projects/[project_id]/geo"
FEATURE_ROOT = GEO_ROOT / "features/geo"


def read_tree(*suffixes: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in GEO_ROOT.rglob("*")
        if path.is_file() and path.suffix in suffixes
    )


def test_admin_geo_workspace_uses_only_stable_project_scoped_routes() -> None:
    source = read_tree(".ts", ".tsx")
    client = (ROOT / "packages/web/api-client/src/geo.ts").read_text(encoding="utf-8")
    assert '"/v1/geo/' not in source
    assert "`/v1/geo/" not in client
    assert "/v1/projects/${projectId}/geo/" in client
    assert "/v1/projects/${projectId}/monitoring-protocols" in client
    assert "/v1/projects/${projectId}/monitoring-reports" in client
    assert not (GEO_ROOT / "page.tsx").exists()
    assert not (GEO_ROOT / "loading.tsx").exists()
    assert not (GEO_ROOT / "error.tsx").exists()
    assert 'tab: "geo"' in source
    assert "geo_section" in source
    assert "`/projects/${projectId}/geo" not in source


def test_admin_geo_workspace_is_split_into_complete_operator_surfaces() -> None:
    shell = (FEATURE_ROOT / "GeoShell.tsx").read_text(encoding="utf-8")
    for component in (
        "CampaignWorkspace",
        "ObservationWorkspace",
        "DestinationWorkspace",
        "PlacementWorkspace",
    ):
        assert component in shell
        assert (FEATURE_ROOT / f"{component}.tsx").exists()
    placement = read_tree(".tsx")
    for control in (
        "Evidence Pack",
        "Prompt Bundle",
        "Job Events",
        "Claim inventory",
        "人工编辑",
        "不可变导出",
        "标记为待发布",
        "回填 URL",
        "请求验证",
        "记录投放测量",
    ):
        assert control in placement


def test_admin_geo_mutations_use_server_identity_and_idempotency_guards() -> None:
    actions = "\n".join(
        path.read_text(encoding="utf-8")
        for path in FEATURE_ROOT.glob("*-actions.ts")
    )
    client_factory = (GEO_ROOT / "client.ts").read_text(encoding="utf-8")
    assert "actorHeaders()" in client_factory
    assert "guards(form)" in actions
    for forbidden_identity_field in ("actor_id:", "reviewer_id:", "created_by:", "submitted_by:"):
        assert forbidden_identity_field not in actions
    assert "idempotencyKey" in (FEATURE_ROOT / "action-utils.ts").read_text(encoding="utf-8")


def test_admin_geo_export_and_publication_are_separate_explicit_actions() -> None:
    actions = (FEATURE_ROOT / "placement-actions.ts").read_text(encoding="utf-8")
    package_panel = (FEATURE_ROOT / "GenerationPackagePanel.tsx").read_text(encoding="utf-8")
    publication_panel = (FEATURE_ROOT / "PublicationPanel.tsx").read_text(encoding="utf-8")
    export_route = (GEO_ROOT.parent / "export-download/[version_id]/[export_id]/route.ts").read_text(encoding="utf-8")
    assert "createExport" in actions
    assert "createPublication" in actions
    assert "未产生发布任务" in actions
    assert "Export is not publication" in package_panel
    assert "/export-download/" in package_panel
    assert "/geo/export-download/" not in package_panel
    assert "/geo/package-versions/" in export_route
    assert "标记为待发布" in publication_panel


def test_observation_workspace_uses_protocol_queries_and_verified_submission_targets() -> None:
    data = (FEATURE_ROOT / "data.ts").read_text(encoding="utf-8")
    actions = (FEATURE_ROOT / "campaign-actions.ts").read_text(encoding="utf-8")
    workspace = (FEATURE_ROOT / "ObservationWorkspace.tsx").read_text(encoding="utf-8")
    client = (ROOT / "packages/web/api-client/src/geo.ts").read_text(encoding="utf-8")

    assert "listProtocolQueries" in data
    assert "listCitationTargets" in data
    assert "/monitoring-protocols/${protocolId}/queries" in client
    assert "/monitoring-protocols/${protocolId}/citation-targets" in client
    assert "data.protocolQueries.data" in workspace
    assert "query.monitoring_query_id" in workspace
    assert 'name="verified_citation_targets"' in workspace
    assert 'verification_status: "unknown"' not in actions


def test_admin_prompt_catalog_edits_the_actual_executable_release() -> None:
    prompt_panel = (FEATURE_ROOT / "BriefPromptPanel.tsx").read_text(encoding="utf-8")
    actions = (FEATURE_ROOT / "placement-actions.ts").read_text(encoding="utf-8")
    generation = (FEATURE_ROOT / "GenerationPackagePanel.tsx").read_text(encoding="utf-8")
    client = (ROOT / "packages/web/api-client/src/geo.ts").read_text(encoding="utf-8")
    defaults = (FEATURE_ROOT / "prompt-defaults.ts").read_text(encoding="utf-8")

    assert "installDefaultPromptCatalog" in prompt_panel
    assert "installDefaultPromptCatalog" in client
    assert 'name="system_template"' in prompt_panel
    assert 'name="user_template"' in prompt_panel
    assert "system_template: value" in actions
    assert "user_template: value" in actions
    assert "PROMPT_TASK_KEYS" in prompt_panel
    assert "internal_evidence_refs" in defaults
    assert "public_citation_refs" in defaults
    assert 'defaultValue="deepseek-v4-flash"' in generation
    assert 'max="5" defaultValue="2"' in generation


def test_admin_geo_files_stay_below_refactor_size_limits() -> None:
    page = (GEO_ROOT.parent / "page.tsx").read_text(encoding="utf-8")
    workbench_files = list((GEO_ROOT.parent / "features/project-workbench").glob("*.ts*"))
    assert len(page.splitlines()) < 300
    for path in workbench_files:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 600, path
    for path in [*FEATURE_ROOT.glob("*.ts"), *FEATURE_ROOT.glob("*.tsx")]:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 600, path
    source = read_tree(".ts", ".tsx")
    assert "Record<string, unknown>" not in source
