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
        "证据准备",
        "冻结本次生成输入",
        "生成任务事件",
        "事实与表述",
        "人工修改并创建新版本",
        "创建不可变导出",
        "标记为待发布",
        "保存公开 URL",
        "请求验证",
        "记录一次测量",
    ):
        assert control in placement


def test_admin_geo_redesign_preserves_every_existing_command() -> None:
    surfaces = read_tree(".tsx")
    commands = {
        "approveReport", "approveSuggestion", "changeProtocol", "computeMetrics",
        "createCampaign", "createDestination", "createMonitoringQuery", "createProtocol",
        "createReport", "createSuggestion", "importObservation", "importOfficialReport",
        "reviewDestination", "transitionOpportunity", "bindOpportunityPromptRelease",
        "transitionPromptRelease", "blockSubmission", "buildEvidence",
        "cancelMeasurementCollectionTask", "completeMeasurementCollectionTask", "controlJob",
        "createBrief", "createExport", "createGenerationJob", "createMeasurement",
        "createPromptBundle", "createPromptRelease", "createPromptSimulation",
        "createPromptSkill", "createPublication", "createSubmission", "editPackage",
        "installDefaultPromptCatalog", "reviewPackage", "setSubmissionUrl",
        "submitPackageReview", "transitionPublication", "verifySubmission",
    }
    missing = sorted(command for command in commands if f"action={{{command}}}" not in surfaces)
    assert not missing, f"redesign removed GEO commands: {missing}"


def test_admin_geo_mutations_use_server_identity_and_idempotency_guards() -> None:
    actions = "\n".join(
        path.read_text(encoding="utf-8") for path in FEATURE_ROOT.glob("*-actions.ts")
    )
    client_factory = (GEO_ROOT / "client.ts").read_text(encoding="utf-8")
    assert "actorHeaders()" in client_factory
    assert "guards(form)" in actions
    for forbidden_identity_field in ("actor_id:", "reviewer_id:", "created_by:", "submitted_by:"):
        assert forbidden_identity_field not in actions
    assert "idempotencyKey" in (FEATURE_ROOT / "action-utils.ts").read_text(encoding="utf-8")


def test_admin_geo_client_forms_work_on_lan_http_origins() -> None:
    action_form = (FEATURE_ROOT / "ActionForm.tsx").read_text(encoding="utf-8")
    placement = (FEATURE_ROOT / "PlacementWorkspace.tsx").read_text(encoding="utf-8")
    assert "crypto.randomUUID" not in action_form
    assert "crypto.getRandomValues" in action_form
    assert "disabled={disabled || pending || !idempotencyKey}" in action_form
    assert '<a key={stage.id}' in placement


def test_admin_geo_normal_workflows_do_not_require_internal_ids_or_json() -> None:
    normal_surfaces = "\n".join(
        (FEATURE_ROOT / name).read_text(encoding="utf-8")
        for name in (
            "CampaignWorkspace.tsx", "ObservationWorkspace.tsx", "DestinationWorkspace.tsx",
            "PlacementWorkspace.tsx", "GenerationPackagePanel.tsx", "PublicationPanel.tsx",
        )
    )
    for leaked_control in (
        "Market Profile ID", "主商品实体 ID", "Job ID", "目标 JSON", "约束 JSON",
        "变量 JSON", "附加指标 JSON", "结构化内容 JSON", "完整 Claim 清单 JSON",
    ):
        assert leaked_control not in normal_surfaces


def test_admin_geo_export_and_publication_are_separate_explicit_actions() -> None:
    actions = (FEATURE_ROOT / "placement-actions.ts").read_text(encoding="utf-8")
    package_panel = (FEATURE_ROOT / "GenerationPackagePanel.tsx").read_text(encoding="utf-8")
    publication_panel = (FEATURE_ROOT / "PublicationPanel.tsx").read_text(encoding="utf-8")
    export_route = (
        GEO_ROOT.parent / "export-download/[version_id]/[export_id]/route.ts"
    ).read_text(encoding="utf-8")
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


def test_monitoring_statistics_ui_uses_frozen_protocol_denominators_and_full_v2_evidence() -> None:
    workspace = (FEATURE_ROOT / "CampaignWorkspace.tsx").read_text(encoding="utf-8")
    actions = (FEATURE_ROOT / "campaign-actions.ts").read_text(encoding="utf-8")
    sampling = (FEATURE_ROOT / "ProtocolSamplingFields.tsx").read_text(encoding="utf-8")
    metric = (FEATURE_ROOT / "MonitoringMetricSnapshot.tsx").read_text(encoding="utf-8")
    hashing = (FEATURE_ROOT / "monitoring-statistics.ts").read_text(encoding="utf-8")
    web_types = (ROOT / "packages/web/types/src/geo.ts").read_text(encoding="utf-8")
    client = (ROOT / "packages/web/api-client/src/geo.ts").read_text(encoding="utf-8")

    assert "selectedProtocol?.source_strata" in workspace
    assert "data.observations.data.flatMap" not in workspace
    assert "sourceStratumHash(stratum)" in workspace
    assert 'name="query_cluster_key"' in workspace
    assert "data.protocolQueries.data" in workspace
    assert "minimum_valid_repeats" in actions
    assert "query_cluster_key: value" in actions
    assert 'min="3"' in sampling
    assert "Math.ceil(sampleSize * 0.8)" in sampling
    assert "source_stratum_hash: string; query_cluster_key: string" in web_types
    assert '"complete" | "confounded" | "insufficient_evidence"' in web_types
    assert "MetricCompute" in client
    assert 'createHash("sha256")' in hashing
    for evidence_field in (
        "sampled_sample_count", "eligible_sample_count", "invalid_sample_count",
        "missing_sample_count", "sampling_completion_ratio", "valid_completion_ratio",
        "invalid_reason_counts", "declared_confounding_factors", "recommendation_ci_low",
        "recommendation_query_min", "worst_query_id", "query_results", "result_hash",
        "observation_membership_version", "observation_membership_hash",
        "observation_membership_count",
    ):
        assert evidence_field in web_types
    for visible_evidence in (
        "已采样", "有效", "无效", "缺失", "采样完成度", "有效完成度",
        "Wilson 95% CI", "问题区间", "无效原因", "混杂因素", "最弱问题",
        "逐问题分母与区间", "指标审计信息",
    ):
        assert visible_evidence in metric
    assert "不作趋势判断" in metric
    assert all(word not in metric.casefold() for word in ("improved", "declined", "stable"))


def test_legacy_query_suggestions_without_clusters_are_visible_but_not_approvable() -> None:
    workspace = (FEATURE_ROOT / "CampaignWorkspace.tsx").read_text(encoding="utf-8")
    web_types = (ROOT / "packages/web/types/src/geo.ts").read_text(encoding="utf-8")

    assert "query_cluster_key: string | null" in web_types
    assert 'name="query_cluster_key" required' in workspace
    assert 'item.status === "suggested" && item.query_cluster_key' in workspace
    assert 'data-testid={item.query_cluster_key ? undefined : "legacy-query-suggestion"}' in workspace
    assert "迁移历史 · 缺少问题簇 · 只读" in workspace
    assert "请在上方提交包含问题簇的新建议" in workspace


def test_legacy_prompt_bundles_are_visible_but_not_executable() -> None:
    generation = (FEATURE_ROOT / "GenerationPackagePanel.tsx").read_text(encoding="utf-8")

    assert 'data-testid="legacy-prompt-bundle"' in generation
    assert "迁移历史生成输入只读，不能启动新版生成任务" in generation
    assert "返回准备证据并重建" in generation
    assert "isLegacyBundle ? <Empty>" in generation


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
    assert "bindOpportunityPromptRelease" in prompt_panel
    assert 'name="expected_binding_version"' in prompt_panel
    assert 'name="confirmed_release_hash"' in prompt_panel
    assert "transitionPromptRelease" in prompt_panel
    assert "bindPromptTask" not in prompt_panel
    assert "PROMPT_TASK_KEYS" not in prompt_panel
    assert "internal_evidence_refs" in defaults
    assert "public_citation_refs" in defaults
    assert "DEFAULT_SYSTEM_PROMPT" not in defaults
    assert "DEFAULT_USER_PROMPT" not in defaults
    assert (ROOT / "prompt/catalog.json").is_file()
    assert (ROOT / "prompt/channels/productreview.md").is_file()
    assert (ROOT / "prompt/runtime/simulation-system.md").is_file()
    assert 'defaultValue="deepseek-v4-flash"' in generation
    assert 'max="5" defaultValue="2"' in generation


def test_prompt_simulation_is_an_internal_test_only_surface() -> None:
    panel = (FEATURE_ROOT / "PromptSimulationPanel.tsx").read_text(encoding="utf-8")
    actions = (FEATURE_ROOT / "placement-actions.ts").read_text(encoding="utf-8")
    client = (ROOT / "packages/web/api-client/src/geo.ts").read_text(encoding="utf-8")
    customer_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "apps/customer-web").rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx"}
    )
    download = (GEO_ROOT.parent / "simulation-download/[simulation_id]/route.ts").read_text(
        encoding="utf-8"
    )

    assert "仅限测试" in panel
    assert "publication_eligible=false" in panel
    assert 'name="authenticity_mode"' in panel
    assert 'value="synthetic_testimonial"' in panel
    assert 'value="fake_persona"' in panel
    assert "eligible_for_generation" in panel
    assert "createPromptSimulation" in actions
    assert "createExport" not in panel
    assert "createPublication" not in panel
    assert "submitPackageReview" not in panel
    assert "/geo/prompt-simulations" in client
    assert "/geo/prompt-simulations" in download
    assert "x-geo-test-only" in download
    assert "prompt-simulations" not in customer_source


def test_admin_preserves_migrated_prompt_simulation_read_and_download_paths() -> None:
    data = (FEATURE_ROOT / "data.ts").read_text(encoding="utf-8")
    panel = (FEATURE_ROOT / "PromptSimulationPanel.tsx").read_text(encoding="utf-8")
    shell = (FEATURE_ROOT / "GeoShell.tsx").read_text(encoding="utf-8")
    placement = (FEATURE_ROOT / "PlacementWorkspace.tsx").read_text(encoding="utf-8")
    client = (ROOT / "packages/web/api-client/src/geo.ts").read_text(encoding="utf-8")
    download = (GEO_ROOT.parent / "simulation-download/[simulation_id]/route.ts").read_text(
        encoding="utf-8"
    )

    assert "listPromptSimulations(projectId: string, campaignId?: string)" in client
    assert "getPromptSimulation(projectId: string, simulationId: string)" in client
    assert "legacySimulationsPromise = client.listPromptSimulations(projectId)" in data
    assert "Promise.all([\n    campaignResourcesPromise,\n    legacySimulationsPromise" in data
    assert "mergeSimulationResources(currentSimulations, legacySimulations)" in data
    assert "if (!byId.has(item.id))" in data
    assert "selectedSimulation?.campaign_id" in data
    assert "client.getPromptSimulation(projectId, id)" in data
    assert "迁移历史（只读）" in panel
    assert 'data-testid="legacy-simulation-readonly"' in panel
    assert "不能作为新建、审核、导出或发布输入" in panel
    assert "item.campaign_id ? item.generation_job_id : undefined" in panel
    assert "simulationDownloadHref(projectId, simulation)" in panel
    assert "hasLegacySimulations" in shell
    assert "hasLegacySimulations" in placement
    assert 'searchParams.get("campaign_id")' in download
    assert 'url.searchParams.set("campaign_id", campaignId)' in download
    assert "url.search =" not in download
    assert "for (const [key" not in download


def test_project_page_loads_geo_workspace_without_serial_catalog_waterfall() -> None:
    page = (GEO_ROOT.parent / "page.tsx").read_text(encoding="utf-8")
    start = page.index(
        "const [catalog, invitations, members, geoData, knowledgeData, promptData, secretData, syntheticData, recommendationData, workflowCData, externalOperationsData] = await Promise.all"
    )
    end = page.index(");", start)
    parallel_block = page[start:end]
    assert "loadCatalog(projectId)" in parallel_block
    assert "loadGeoWorkspace(projectId, query)" in parallel_block
    assert "loadKnowledgeWorkspace(projectId, query)" in parallel_block
    assert "loadPromptWorkspace(projectId, query)" in parallel_block
    assert "loadSecretWorkspace(projectId, query)" in parallel_block
    assert "loadSyntheticLabWorkspace(projectId, query)" in parallel_block
    assert "loadRecommendationWorkspace(projectId, query)" in parallel_block
    assert "loadWorkflowCWorkspace(projectId, query)" in parallel_block
    assert "loadExternalOperations(projectId)" in parallel_block


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
