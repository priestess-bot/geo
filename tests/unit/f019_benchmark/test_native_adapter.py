from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from geo_core.rag import ProjectNativeRagAdapterV1, QuestionPlan, RagAdapterError
from geo_core.rag.contracts import RagSourceDocument


class FakeInvoker:
    def __init__(self, output: Mapping[str, object]) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    def complete_json(
        self,
        *,
        project_id: str,
        purpose: str,
        messages: Sequence[Mapping[str, str]],
        request_hash: str,
        max_output_tokens: int,
    ) -> Mapping[str, object]:
        self.calls.append(
            {
                "project_id": project_id,
                "purpose": purpose,
                "messages": messages,
                "request_hash": request_hash,
                "max_output_tokens": max_output_tokens,
            }
        )
        if purpose == "geo-rag-question-grounding":
            return {
                "supports": [
                    {
                        "dimension_key": "installation-space",
                        "fact_texts": ["A1 支持免改柜安装。"],
                    }
                ]
            }
        return self.output


CONTENT = """A1 的流量为每分钟 2 升。
A1 支持免改柜安装。
Brand: 星澜
Product: A1
Feature: 免改柜安装
A1 belongs_to 星澜
A1 has_feature 免改柜安装"""


def _document() -> RagSourceDocument:
    return RagSourceDocument("doc-1", "project-1", "A1 产品资料", CONTENT, "source://doc-1")


def _output() -> dict[str, object]:
    return {
        "facts": [
            {"text": "A1 的流量为每分钟 2 升。", "source_quote": "A1 的流量为每分钟 2 升。"},
            {"text": "A1 支持免改柜安装。", "source_quote": "A1 支持免改柜安装。"},
        ],
        "entities": [
            {"entity_type": "Brand", "name": "星澜", "source_quote": "星澜"},
            {"entity_type": "Product", "name": "A1", "source_quote": "A1"},
            {"entity_type": "Feature", "name": "免改柜安装", "source_quote": "免改柜安装"},
        ],
        "relations": [
            {
                "subject": "A1",
                "predicate": "belongs_to",
                "object": "星澜",
                "source_quote": "A1 belongs_to 星澜",
            },
            {
                "subject": "A1",
                "predicate": "has_feature",
                "object": "免改柜安装",
                "source_quote": "A1 has_feature 免改柜安装",
            },
        ],
    }


def test_native_adapter_is_model_backed_traceable_and_content_cached() -> None:
    invoker = FakeInvoker(_output())
    adapter = ProjectNativeRagAdapterV1(invoker)
    plan = QuestionPlan(
        dimension_key="installation-space",
        source_document_id="doc-1",
        persona="小户型业主",
        scenario="比较安装方案",
        intent="安装空间",
        funnel="comparison",
        region="全国",
        language="zh-CN",
        brand_scope="non_branded",
        platform="搜索助手",
        subject="A1",
    )

    first = adapter.extract((_document(),), (plan,))
    second = adapter.extract((_document(),), (plan,))

    assert first == second
    assert len(invoker.calls) == 2
    assert invoker.calls[0]["purpose"] == "geo-rag-graph-extraction"
    assert invoker.calls[1]["purpose"] == "geo-rag-question-grounding"
    assert len(first.facts) == 2
    assert len(first.entities) == 3
    assert len(first.relations) == 2
    assert len(first.questions) == 1
    assert first.questions[0].dimension_key == plan.dimension_key
    assert first.questions[0].source_fact_ids


def test_native_adapter_rejects_untraceable_model_content() -> None:
    output = _output()
    output["facts"] = [{"text": "A1 获得不存在的认证。", "source_quote": "A1 获得不存在的认证。"}]

    with pytest.raises(RagAdapterError, match="no traceable fact"):
        ProjectNativeRagAdapterV1(FakeInvoker(output)).extract((_document(),))


def test_native_adapter_drops_and_hashes_one_invalid_candidate() -> None:
    output = _output()
    output["facts"] = [
        output["facts"][0],
        {"text": "A1 获得不存在的认证。", "source_quote": "A1 获得不存在的认证。"},
    ]

    graph = ProjectNativeRagAdapterV1(FakeInvoker(output)).extract((_document(),))

    assert [item.text for item in graph.facts] == ["A1 的流量为每分钟 2 升。"]
    assert len(graph.validation_findings) == 1
    finding = graph.validation_findings[0]
    assert finding.candidate_kind == "fact"
    assert finding.reason_code == "fact_untraceable"
    assert len(finding.candidate_hash) == 64


def test_native_adapter_drops_relation_whose_endpoint_is_not_an_entity() -> None:
    output = _output()
    output["relations"] = [
        *output["relations"],
        {
            "subject": "A1",
            "predicate": "uses_channel",
            "object": "每分钟 2 升",
            "source_quote": "A1 的流量为每分钟 2 升。",
        },
    ]

    graph = ProjectNativeRagAdapterV1(FakeInvoker(output)).extract((_document(),))

    assert len(graph.relations) == 2
    assert any(
        item.candidate_kind == "relation"
        and item.reason_code == "relation_endpoint_not_an_entity"
        for item in graph.validation_findings
    )


def test_native_adapter_keeps_one_type_for_an_ambiguous_entity_name() -> None:
    output = _output()
    output["entities"] = [
        *output["entities"],
        {"entity_type": "Feature", "name": "A1", "source_quote": "A1"},
    ]

    graph = ProjectNativeRagAdapterV1(FakeInvoker(output)).extract((_document(),))

    assert [(item.entity_type, item.name) for item in graph.entities].count(
        ("Product", "A1")
    ) == 1
    assert not any(item.entity_type == "Feature" and item.name == "A1" for item in graph.entities)
    assert any(
        item.candidate_kind == "entity" and item.reason_code == "ambiguous_entity_name"
        for item in graph.validation_findings
    )


def test_native_adapter_resolves_entity_type_ambiguity_across_documents() -> None:
    class CrossDocumentInvoker(FakeInvoker):
        def complete_json(self, **kwargs) -> Mapping[str, object]:
            messages = kwargs["messages"]
            if "A1 is presented as a feature." in messages[1]["content"]:
                return {
                    "facts": [
                        {
                            "text": "A1 is presented as a feature.",
                            "source_quote": "A1 is presented as a feature.",
                        }
                    ],
                    "entities": [
                        {"entity_type": "Feature", "name": "A1", "source_quote": "A1"}
                    ],
                    "relations": [],
                }
            return super().complete_json(**kwargs)

    second = RagSourceDocument(
        "doc-2",
        "project-1",
        "A1 feature fragment",
        "A1 is presented as a feature.",
        "source://doc-2",
    )

    graph = ProjectNativeRagAdapterV1(CrossDocumentInvoker(_output())).extract(
        (_document(), second)
    )

    assert [(item.entity_type, item.name) for item in graph.entities].count(
        ("Product", "A1")
    ) == 1
    assert not any(item.entity_type == "Feature" and item.name == "A1" for item in graph.entities)
    assert not any(item.subject == "A1" or item.object == "A1" for item in graph.relations)
    assert {
        "ambiguous_entity_name_across_documents",
        "ambiguous_relation_endpoint_across_documents",
    } <= {item.reason_code for item in graph.validation_findings}


def test_native_adapter_rejects_question_plan_outside_batch() -> None:
    plan = QuestionPlan(
        "missing",
        "other-doc",
        "persona",
        "scenario",
        "intent",
        "discovery",
        "region",
        "zh-CN",
        "branded",
        "platform",
        "subject",
    )
    with pytest.raises(RagAdapterError, match="outside the batch"):
        ProjectNativeRagAdapterV1(FakeInvoker(_output())).extract((_document(),), (plan,))


def test_native_adapter_rejects_question_support_outside_verified_facts() -> None:
    class InvalidSupportInvoker(FakeInvoker):
        def complete_json(self, **kwargs) -> Mapping[str, object]:
            output = super().complete_json(**kwargs)
            if kwargs["purpose"] == "geo-rag-question-grounding":
                return {
                    "supports": [
                        {
                            "dimension_key": "installation-space",
                            "fact_texts": ["A1 获得不存在的认证。"],
                        }
                    ]
                }
            return output

    plan = QuestionPlan(
        "installation-space",
        "doc-1",
        "persona",
        "scenario",
        "intent",
        "comparison",
        "region",
        "zh-CN",
        "branded",
        "platform",
        "A1",
    )

    with pytest.raises(RagAdapterError, match="outside verified facts"):
        ProjectNativeRagAdapterV1(InvalidSupportInvoker(_output())).extract((_document(),), (plan,))


def test_native_adapter_allows_empty_fragment_when_document_group_has_facts() -> None:
    class GroupInvoker(FakeInvoker):
        def complete_json(self, **kwargs) -> Mapping[str, object]:
            messages = kwargs["messages"]
            if "页脚" in messages[1]["content"]:
                return {"facts": [], "entities": [], "relations": []}
            return super().complete_json(**kwargs)

    first = _document()
    first = RagSourceDocument(
        first.document_id,
        first.project_id,
        first.title,
        first.content,
        first.source_locator,
        "document-group-1",
    )
    footer = RagSourceDocument(
        "doc-1-footer",
        "project-1",
        "页脚",
        "页脚和导航内容。",
        "source://doc-1-footer",
        "document-group-1",
    )

    graph = ProjectNativeRagAdapterV1(GroupInvoker(_output())).extract((first, footer))

    assert len(graph.facts) == 2
