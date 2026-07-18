from pathlib import Path
import re

from geo_api.app_factory import create_api_app


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "apps/admin-web/app/projects/[project_id]"


def test_knowledge_api_is_project_scoped_and_internal_only() -> None:
    internal = create_api_app(surface="internal").openapi()["paths"]
    customer = create_api_app(surface="customer").openapi()["paths"]
    expected = {
        "/v1/projects/{project_id}/knowledge/sources",
        "/v1/projects/{project_id}/knowledge/sources/{source_id}/reprocess",
        "/v1/projects/{project_id}/knowledge/pipeline-runs",
        "/v1/projects/{project_id}/knowledge/pipeline-runs/{run_id}/stages",
        "/v1/projects/{project_id}/knowledge/chunks",
        "/v1/projects/{project_id}/knowledge/fact-candidates/{fact_id}",
        "/v1/projects/{project_id}/knowledge/quality-findings/{finding_id}",
        "/v1/projects/{project_id}/knowledge/dashboard",
    }
    assert expected <= set(internal)
    assert expected.isdisjoint(customer)


def test_knowledge_workspace_keeps_all_enterprise_preprocessing_views() -> None:
    source = (WORKSPACE / "KnowledgeWorkspace.tsx").read_text(encoding="utf-8")
    for label in (
        "导入企业知识",
        "处理任务",
        "Chunk 可视化",
        "知识检索",
        "知识库看板",
        "质检发现",
        "事实候选与证据追踪",
    ):
        assert label in source
    assert ".pdf,.docx" in source
    assert "reviewKnowledgeFinding" in source
    assert "EvidencePanel" not in source


def test_knowledge_slice_is_modular_and_does_not_reintroduce_legacy_names() -> None:
    paths = [
        *Path("packages/geo_core/geo_core/knowledge").glob("*.py"),
        *Path("apps/api/geo_api").glob("knowledge_*.py"),
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 600, path
        assert re.search(r"\bgeno(?:_|\b)", source, re.IGNORECASE) is None, path
