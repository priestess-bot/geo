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
    assert "createExport" in actions
    assert "createPublication" in actions
    assert "未产生发布任务" in actions
    assert "Export is not publication" in package_panel
    assert "标记为待发布" in publication_panel


def test_admin_geo_files_stay_below_refactor_size_limits() -> None:
    page = (GEO_ROOT / "page.tsx").read_text(encoding="utf-8")
    assert len(page.splitlines()) < 300
    for path in [*FEATURE_ROOT.glob("*.ts"), *FEATURE_ROOT.glob("*.tsx")]:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 600, path
    source = read_tree(".ts", ".tsx")
    assert "Record<string, unknown>" not in source
