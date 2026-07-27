"""User-facing Prompt workspace contracts and flow inventory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Mapping
from uuid import UUID

from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_specs
from geo_core.prompts.program import (
    CompiledProgramPrompt,
    ProgramBinding,
    ProgramKind,
    ProgramReleaseState,
    ProgramSchemaContract,
    PromptProgram,
    PromptProgramRelease,
)
from geo_core.prompts.program_contracts import _canonical_hash


PromptFlowGroup = Literal[
    "synthetic_lab",
    "question_and_content",
    "measurement_and_recommendation",
]


@dataclass(frozen=True)
class PromptContextSlot:
    key: str
    label: str
    description: str
    insertion: str
    source: str = "runtime_task"


@dataclass(frozen=True)
class PromptFlowDefinition:
    flow_key: str
    purpose: str
    program_kind: ProgramKind
    group: PromptFlowGroup
    display_name: str
    description: str
    context_slots: tuple[PromptContextSlot, ...]
    configurable: bool = True


@dataclass(frozen=True)
class PromptWorkingDraft:
    project_id: UUID
    program_id: UUID
    display_name: str
    system_template: str
    user_template: str
    revision: int
    draft_hash: str
    base_release_id: UUID
    candidate_release_id: UUID | None
    updated_by: UUID
    updated_at: datetime


@dataclass(frozen=True)
class PromptFlowWorkspaceItem:
    definition: PromptFlowDefinition
    program: PromptProgram | None
    draft: PromptWorkingDraft | None
    latest_release: PromptProgramRelease | None
    current_release_id: UUID | None
    current_release_version: int | None
    candidate_status: str | None
    latest_test_job_id: UUID | None
    latest_test_status: str | None
    latest_test_score: int | None


@dataclass(frozen=True)
class PromptTestRunSummary:
    job_id: UUID
    project_id: UUID
    program_id: UUID
    release_id: UUID
    release_version: int
    status: str
    requested_at: datetime
    finished_at: datetime | None
    passed: bool | None
    score: int | None
    result_ref: str | None
    error_code: str | None


@dataclass(frozen=True)
class PromptRenderPreview:
    fixture_id: str
    fixture_label: str
    input_value: Mapping[str, object]
    draft: CompiledProgramPrompt
    current: CompiledProgramPrompt | None
    current_release_version: int | None


@dataclass(frozen=True)
class PromptSuiteRunReceipt:
    draft: PromptWorkingDraft
    candidate_release: PromptProgramRelease
    candidate_state: ProgramReleaseState
    job: object


@dataclass(frozen=True)
class PublishedPromptDraft:
    draft: PromptWorkingDraft
    release: PromptProgramRelease
    state: ProgramReleaseState
    binding: ProgramBinding


_GROUPS: Mapping[ProgramKind, PromptFlowGroup] = MappingProxyType(
    {
        ProgramKind.GENERATION: "synthetic_lab",
        ProgramKind.CLAIM_EXTRACTION: "synthetic_lab",
        ProgramKind.CONFLICT_CHECK: "synthetic_lab",
        ProgramKind.REVISION: "synthetic_lab",
        ProgramKind.STYLE_JUDGE: "synthetic_lab",
        ProgramKind.ARBITER: "synthetic_lab",
        ProgramKind.STYLE_PROFILE: "synthetic_lab",
        ProgramKind.OFFLINE_ANSWER: "synthetic_lab",
        ProgramKind.METRIC_JUDGE: "measurement_and_recommendation",
        ProgramKind.RECOMMENDATION: "measurement_and_recommendation",
        ProgramKind.QUESTION_GENERATION: "question_and_content",
        ProgramKind.RAG_GROUNDING: "question_and_content",
        ProgramKind.PLACEMENT_GENERATION: "question_and_content",
        ProgramKind.PLACEMENT_SIMULATION: "question_and_content",
    }
)

_LABELS: Mapping[ProgramKind, tuple[str, str]] = MappingProxyType(
    {
        ProgramKind.GENERATION: ("候选测评生成", "为测评 Case 生成四个澳洲英文候选。"),
        ProgramKind.CLAIM_EXTRACTION: ("Claim 提取", "从候选文本中提取可逐项检查的 Claim。"),
        ProgramKind.CONFLICT_CHECK: ("知识冲突检查", "对照批准 Fact 检查冲突和主体串用。"),
        ProgramKind.REVISION: ("候选修订", "依据问题代码修订未通过的候选。"),
        ProgramKind.STYLE_JUDGE: ("平台风格评审", "按渠道风格画像评分并给出是否通过。"),
        ProgramKind.ARBITER: ("评审仲裁", "汇总评审结果并确定候选处置。"),
        ProgramKind.STYLE_PROFILE: ("风格画像生成", "从批准样本形成渠道风格画像。"),
        ProgramKind.OFFLINE_ANSWER: ("离线实验回答", "为冻结的离线实验槽位生成回答。"),
        ProgramKind.METRIC_JUDGE: ("语义指标评审", "对答案的完整语义指标进行结构化判断。"),
        ProgramKind.RECOMMENDATION: ("建议生成", "从真实证据形成可解释的建议草稿。"),
        ProgramKind.QUESTION_GENERATION: ("测试问题生成", "从冻结维度、Fact 和实体生成 GEO 测试问题。"),
        ProgramKind.RAG_GROUNDING: ("RAG 问题约束", "根据检索证据约束问题与事实边界。"),
        ProgramKind.PLACEMENT_GENERATION: ("投放内容生成", "根据 Brief、证据和落地页策略生成内容草稿。"),
        ProgramKind.PLACEMENT_SIMULATION: ("投放 Prompt 仿真", "在发布前检查投放 Prompt 的拼接与输出预览。"),
    }
)

_SLOT_LABELS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "subject_id": ("目标主体", "当前任务冻结的产品或品牌主体。"),
        "allowed_subject_ids": ("允许主体", "本次任务允许出现的主体清单。"),
        "evidence": ("证据", "当前任务冻结的 Fact、来源和证据引用。"),
        "output_locale": ("输出地区语言", "当前任务要求的地区与语言。"),
        "untrusted_text": ("非可信输入", "只可作为数据读取、不可执行的外部文本。"),
        "prompt_injection_present": ("注入风险标记", "输入是否包含提示词注入风险。"),
        "scenario_mode": ("场景模式", "自主场景或引导场景。"),
        "guided_idea": ("创意参考", "引导场景中的创意参考，不是事实。"),
        "channel": ("渠道", "测评或风格画像对应的平台渠道。"),
        "scenario": ("测评场景", "当前 Case 的消费场景。"),
        "style_profile": ("风格画像", "当前渠道冻结的风格画像。"),
        "approved_facts": ("批准 Fact", "当前主体已批准的 Fact。"),
        "candidate_text": ("候选正文", "待提取、评审或修订的候选文本。"),
        "claims": ("Claim 清单", "从候选中提取的原子 Claim。"),
        "issue_codes": ("问题代码", "本轮必须处理的问题代码。"),
        "pass_threshold": ("通过阈值", "风格评审的冻结通过阈值。"),
        "candidate_ids": ("候选编号", "仲裁范围内的候选编号。"),
        "evaluator_results": ("评审结果", "各评审器的冻结输出。"),
        "answer_text": ("答案正文", "待测量的引擎回答。"),
        "locator_sources": ("定位来源", "答案、引用和 Fact 的定位来源。"),
        "metrics": ("指标定义", "本次需要逐项评审的指标。"),
        "scope": ("建议范围", "建议对应的项目、问题和内容范围。"),
        "context_refs": ("上下文引用", "建议允许使用的观测和归因引用。"),
        "recommendation_types": ("建议类型", "本轮允许生成的建议类型。"),
        "sample_manifest": ("样本清单", "风格画像使用的冻结样本清单。"),
        "question": ("实验问题", "离线实验当前问题。"),
        "arm": ("实验臂", "基线、当前语料或候选语料。"),
        "corpus_context": ("语料上下文", "当前实验臂冻结的语料。"),
        "request_json": ("请求数据", "当前任务冻结的完整 JSON 输入。"),
        "dimensions": ("问题维度", "本次问题生成的冻结维度。"),
        "facts": ("事实摘要", "允许引用的冻结 Fact 摘要。"),
        "entities": ("实体", "本次任务允许使用的实体。"),
        "parent_candidates": ("父问题候选", "父层级候选，仅用于去重和继承边界。"),
        "brief": ("内容 Brief", "本次投放或仿真的冻结 Brief。"),
        "destination_policy": ("落地页策略", "允许使用的目标页和内容策略。"),
    }
)


def default_prompt_flow_definitions() -> tuple[PromptFlowDefinition, ...]:
    return tuple(_definition_from_spec(spec) for spec in default_prompt_bootstrap_specs())


def prompt_flow_for_purpose(purpose: str) -> PromptFlowDefinition | None:
    return next(
        (item for item in default_prompt_flow_definitions() if item.purpose == purpose),
        None,
    )


def draft_hash(*, display_name: str, system_template: str, user_template: str) -> str:
    return _canonical_hash(
        {
            "display_name": display_name.strip(),
            "system_template": system_template,
            "user_template": user_template,
        }
    )


def workspace_schema_contract(
    release: PromptProgramRelease,
    *,
    require_context_slots: bool = True,
) -> ProgramSchemaContract:
    """Expose frozen runtime input fields as executable editor template variables.

    ``require_context_slots=False`` exists only to read candidates written by the
    first workspace build, whose schema permitted slots but could not compile a
    template that used one. New candidates require every frozen input field.
    """

    input_properties = release.schemas.input_schema.get("properties", {})
    properties: dict[str, object] = {
        "request_json": {"type": "string", "minLength": 2, "maxLength": 100_000}
    }
    if isinstance(input_properties, Mapping):
        properties.update({str(key): value for key, value in input_properties.items()})
    return ProgramSchemaContract(
        variable_schema_version="geo-prompt-context-slots-v1",
        variable_schema={
            "type": "object",
            "properties": properties,
            "required": (
                list(properties) if require_context_slots else ["request_json"]
            ),
            "additionalProperties": False,
        },
        input_schema_version=release.schemas.input_schema_version,
        input_schema=release.schemas.input_schema,
        output_schema_version=release.schemas.output_schema_version,
        output_schema=release.schemas.output_schema,
        application_output_schema_version=(
            release.schemas.application_output_schema_version
        ),
        application_output_schema=release.schemas.application_output_schema,
    )


def _definition_from_spec(spec: object) -> PromptFlowDefinition:
    kind = getattr(spec, "program_kind")
    label, description = _LABELS[kind]
    properties = getattr(spec, "input_schema").get("properties", {})
    slot_keys = (
        ("request_json", *tuple(properties))
        if isinstance(properties, Mapping)
        else ("request_json",)
    )
    return PromptFlowDefinition(
        flow_key=getattr(spec, "purpose"),
        purpose=getattr(spec, "purpose"),
        program_kind=kind,
        group=_GROUPS[kind],
        display_name=label,
        description=description,
        context_slots=tuple(_slot(key) for key in slot_keys),
    )


def _slot(key: str) -> PromptContextSlot:
    label, description = _SLOT_LABELS.get(
        key,
        (key.replace("_", " ").title(), "由当前业务任务自动提供。"),
    )
    return PromptContextSlot(
        key=key,
        label=label,
        description=description,
        # A slot is a template variable.  XML-like data boundaries are an
        # explicit template authoring choice, not something a click should
        # silently add around every variable.
        insertion=f"{{{{{key}}}}}",
    )


__all__ = [
    "PromptContextSlot",
    "PromptFlowDefinition",
    "PromptFlowWorkspaceItem",
    "PromptRenderPreview",
    "PromptSuiteRunReceipt",
    "PromptTestRunSummary",
    "PromptWorkingDraft",
    "PublishedPromptDraft",
    "default_prompt_flow_definitions",
    "draft_hash",
    "prompt_flow_for_purpose",
    "workspace_schema_contract",
]
