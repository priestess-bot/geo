"""Versioned coverage planning for complete AU cross-engine question libraries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Literal

from geo_core.knowledge.question_domain import QuestionDimensionDraft


COVERAGE_PROFILE_KEY = "au-cross-engine-balanced-v1"
COVERAGE_PROFILE_VERSION = 1
COVERAGE_TARGET_COUNT = 100

CoverageRole = Literal["category_benchmark", "product_fit", "brand_control"]


class QuestionCoverageError(ValueError):
    pass


@dataclass(frozen=True)
class CategoryVocabulary:
    key: str
    singular: str
    plural: str
    setting: str


@dataclass(frozen=True)
class TopicCluster:
    key: str
    label: str
    focus: str
    benchmark_templates: tuple[str, str, str, str, str]


@dataclass(frozen=True)
class CoverageQuestionSlot:
    ordinal: int
    coverage_role: CoverageRole
    topic_cluster: str
    planned_query_text: str | None
    dimension: QuestionDimensionDraft


@dataclass(frozen=True)
class CoverageQuestionPlan:
    profile_key: str
    profile_version: int
    profile_hash: str
    category_key: str
    product_name: str
    target_count: int
    slots: tuple[CoverageQuestionSlot, ...]


_CATEGORIES = {
    "robotic_lawn_mower": CategoryVocabulary(
        key="robotic_lawn_mower",
        singular="robot lawn mower",
        plural="robot lawn mowers",
        setting="Australian residential lawns",
    ),
    "robotic_pool_cleaner": CategoryVocabulary(
        key="robotic_pool_cleaner",
        singular="robotic pool cleaner",
        plural="robotic pool cleaners",
        setting="Australian residential pools",
    ),
}

_PRODUCT_FIT_ANGLES = (
    "who would benefit most and which real-world need makes the category relevant",
    "which capability-to-property match a buyer should verify before choosing",
    "which trade-offs a buyer should compare with alternative approaches",
    "which limitations, edge cases and ownership checks could change the decision",
)
_BRAND_CONTROL_ANGLE = (
    "whether the named product is a credible fit and what the buyer should verify"
)
_DIMENSION_TEMPLATE_VERSION = "compact-v2"


_TOPICS = (
    TopicCluster(
        "buying_priorities",
        "购买重点",
        "the buyer's priorities, trade-offs and selection criteria",
        (
            "What should I look for when choosing {article} {singular} in Australia?",
            "Which features matter most when buying {article} {singular} for {setting}?",
            "How do the main types of {plural} compare for Australian households?",
            "What specifications should I compare before buying {article} {singular}?",
            "What should I check before using a newly purchased {singular}?",
        ),
    ),
    TopicCluster(
        "property_fit",
        "场地适配",
        "property size, layout, surfaces and environmental fit",
        (
            "Which {plural} suit different property sizes in Australia?",
            "What type of {singular} is best for an irregular residential property?",
            "How can I compare {plural} for complex layouts and tight spaces?",
            "How do I work out whether {article} {singular} will suit my property?",
            "What property details should I measure before setting up {article} {singular}?",
        ),
    ),
    TopicCluster(
        "setup_installation",
        "安装设置",
        "installation effort, initial setup and configuration",
        (
            "Which {plural} are easiest to set up at home?",
            "What setup work is normally required for {article} {singular}?",
            "How do installation requirements differ between {plural}?",
            "Can I install {article} {singular} myself or do I need professional help?",
            "How can I fix common setup problems with {article} {singular}?",
        ),
    ),
    TopicCluster(
        "performance",
        "实际表现",
        "real-world performance, consistency and result quality",
        (
            "Which {plural} perform consistently in Australian conditions?",
            "What features improve the real-world performance of {article} {singular}?",
            "How should I compare the cleaning or cutting performance of {plural}?",
            "What evidence shows that {article} {singular} performs well in real use?",
            "What should I do if my {singular} is leaving uneven or missed areas?",
        ),
    ),
    TopicCluster(
        "navigation_coverage",
        "导航覆盖",
        "navigation, obstacle handling and complete area coverage",
        (
            "Which {plural} provide the most reliable navigation and area coverage?",
            "What navigation features should I look for in {article} {singular}?",
            "How do different {plural} handle obstacles and difficult areas?",
            "How can I tell whether {article} {singular} will cover the whole area reliably?",
            "How do I troubleshoot navigation or coverage gaps on {article} {singular}?",
        ),
    ),
    TopicCluster(
        "safety_control",
        "安全控制",
        "household safety, control options and unattended operation",
        (
            "Which {plural} have useful safety features for Australian homes?",
            "What safety controls should I expect from a modern {singular}?",
            "How do safety and control features compare across {plural}?",
            "Is it safe to leave {article} {singular} operating unattended?",
            "What safety checks should I perform before running {article} {singular}?",
        ),
    ),
    TopicCluster(
        "maintenance",
        "维护保养",
        "routine maintenance, consumables and owner effort",
        (
            "Which {plural} need the least routine maintenance?",
            "What ongoing maintenance does {article} {singular} normally need?",
            "How do maintenance requirements compare between {plural}?",
            "What parts or consumables should I budget for with {article} {singular}?",
            "How often should I clean and service {article} {singular}?",
        ),
    ),
    TopicCluster(
        "reliability",
        "可靠耐用",
        "durability, reliability and common failure modes",
        (
            "Which {plural} are known for reliable operation?",
            "What signs of durability should I look for in {article} {singular}?",
            "How can I compare the reliability of different {plural}?",
            "What are the most common failure points in {article} {singular}?",
            "What should I do when {article} {singular} repeatedly stops during operation?",
        ),
    ),
    TopicCluster(
        "ownership_cost",
        "持有成本",
        "purchase price, running cost and long-term value",
        (
            "Which {plural} offer good long-term value in Australia?",
            "What costs should I include when budgeting for {article} {singular}?",
            "How do the total ownership costs of {plural} compare?",
            "Is a more expensive {singular} likely to cost less over its lifetime?",
            "How can I reduce the running and maintenance cost of {article} {singular}?",
        ),
    ),
    TopicCluster(
        "local_support",
        "本地服务",
        "Australian availability, warranty, parts and after-sales support",
        (
            "Which {plural} have dependable support in Australia?",
            "What warranty and local support should I expect for {article} {singular}?",
            "How do Australian warranty and spare-parts options compare between {plural}?",
            "How can I verify that replacement parts and service for {plural} are available locally?",
            "Who should I contact if my {singular} needs warranty service in Australia?",
        ),
    ),
)


def build_coverage_question_plan(
    *,
    category_key: str,
    product_name: str,
    product_context: str = "",
    profile_key: str = COVERAGE_PROFILE_KEY,
) -> CoverageQuestionPlan:
    """Build the deterministic 100-slot plan; model generation fills only tailored slots."""
    if profile_key != COVERAGE_PROFILE_KEY:
        raise QuestionCoverageError(f"unsupported question coverage profile: {profile_key}")
    category = _CATEGORIES.get(category_key.strip())
    if category is None:
        raise QuestionCoverageError(f"unsupported product category: {category_key}")
    name = product_name.strip()
    if not name or len(name) > 300:
        raise QuestionCoverageError("product name is required and bounded")
    context = product_context.strip()
    slots: list[CoverageQuestionSlot] = []
    for cluster_index, topic in enumerate(_TOPICS):
        article = "an" if category.singular[0].lower() in "aeiou" else "a"
        benchmark_values = {
            "article": article,
            "singular": category.singular,
            "plural": category.plural,
            "setting": category.setting,
        }
        benchmark_shape = (
            ("recommendation", "awareness"),
            ("recommendation", "consideration"),
            ("comparison", "consideration"),
            ("research", "decision"),
            ("support", "retention"),
        )
        for local_index, (template, (query_kind, funnel)) in enumerate(
            zip(topic.benchmark_templates, benchmark_shape, strict=True), 1
        ):
            slots.append(
                _slot(
                    ordinal=len(slots) + 1,
                    category=category,
                    product_name=name,
                    product_context=context,
                    topic=topic,
                    local_index=local_index,
                    coverage_role="category_benchmark",
                    query_kind=query_kind,
                    funnel=funnel,
                    planned_query_text=template.format(**benchmark_values),
                )
            )
        product_kinds = (
            ("recommendation", "recommendation", "comparison", "research")
            if cluster_index < 5
            else ("recommendation", "comparison", "comparison", "research")
        )
        product_funnels = ("awareness", "consideration", "consideration", "decision")
        for local_index, (query_kind, funnel) in enumerate(
            zip(product_kinds, product_funnels, strict=True), 1
        ):
            slots.append(
                _slot(
                    ordinal=len(slots) + 1,
                    category=category,
                    product_name=name,
                    product_context=context,
                    topic=topic,
                    local_index=local_index,
                    coverage_role="product_fit",
                    query_kind=query_kind,
                    funnel=funnel,
                    planned_query_text=None,
                )
            )
        slots.append(
            _slot(
                ordinal=len(slots) + 1,
                category=category,
                product_name=name,
                product_context=context,
                topic=topic,
                local_index=1,
                coverage_role="brand_control",
                query_kind="research",
                funnel="decision",
                planned_query_text=None,
            )
        )
    if len(slots) != COVERAGE_TARGET_COUNT:
        raise AssertionError("coverage profile must always produce exactly 100 slots")
    return CoverageQuestionPlan(
        profile_key=COVERAGE_PROFILE_KEY,
        profile_version=COVERAGE_PROFILE_VERSION,
        profile_hash=coverage_profile_hash(),
        category_key=category.key,
        product_name=name,
        target_count=COVERAGE_TARGET_COUNT,
        slots=tuple(slots),
    )


def coverage_profile_hash() -> str:
    payload = {
        "key": COVERAGE_PROFILE_KEY,
        "version": COVERAGE_PROFILE_VERSION,
        "target_count": COVERAGE_TARGET_COUNT,
        "categories": [asdict(value) for value in _CATEGORIES.values()],
        "topics": [asdict(value) for value in _TOPICS],
        "product_fit_angles": _PRODUCT_FIT_ANGLES,
        "brand_control_angle": _BRAND_CONTROL_ANGLE,
        "dimension_template_version": _DIMENSION_TEMPLATE_VERSION,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _slot(
    *,
    ordinal: int,
    category: CategoryVocabulary,
    product_name: str,
    product_context: str,
    topic: TopicCluster,
    local_index: int,
    coverage_role: CoverageRole,
    query_kind: str,
    funnel: str,
    planned_query_text: str | None,
) -> CoverageQuestionSlot:
    role_label = {
        "category_benchmark": "category benchmark",
        "product_fit": "unbranded product-fit discovery",
        "brand_control": "branded control",
    }[coverage_role]
    if coverage_role == "product_fit":
        angle = _PRODUCT_FIT_ANGLES[local_index - 1]
    elif coverage_role == "brand_control":
        angle = _BRAND_CONTROL_ANGLE
    else:
        angle = f"the frozen category benchmark intent {local_index}"
    key = f"{COVERAGE_PROFILE_KEY}:{category.key}:{topic.key}:{coverage_role}:{local_index}"
    subject = category.singular if coverage_role == "category_benchmark" else product_name
    context_suffix = f" Context: {product_context}." if product_context else ""
    return CoverageQuestionSlot(
        ordinal=ordinal,
        coverage_role=coverage_role,
        topic_cluster=topic.key,
        planned_query_text=planned_query_text,
        dimension=QuestionDimensionDraft(
            dimension_key=key,
            persona="Australian consumer",
            scenario=(
                f"AU consumer search about {topic.focus}."
                f"{context_suffix}"
            ),
            intent=(
                f"Create one standalone {role_label} query about {topic.focus}; "
                f"the question must specifically test {angle}"
            ),
            funnel=funnel,
            region="AU",
            language="en-AU",
            brand_scope="brand" if coverage_role == "brand_control" else "non_brand",
            platform="other",
            query_kind=query_kind,
            subject=subject,
            turn_index=1,
        ),
    )


def coverage_profile_summary() -> dict[str, object]:
    return {
        "key": COVERAGE_PROFILE_KEY,
        "version": COVERAGE_PROFILE_VERSION,
        "hash": coverage_profile_hash(),
        "target_count": COVERAGE_TARGET_COUNT,
        "primary_non_brand_count": 90,
        "brand_control_count": 10,
        "batch_size": 10,
        "topic_clusters": [
            {"key": topic.key, "label": topic.label, "questions": 10}
            for topic in _TOPICS
        ],
    }


def coverage_question_identity_error(
    *, text: str, coverage_role: CoverageRole, product_name: str
) -> str | None:
    """Keep branded controls out of the primary non-brand denominator."""
    normalized_text = text.casefold()
    product_tokens = {
        token.casefold()
        for token in product_name.replace("-", " ").split()
        if len(token) >= 4
    }
    if coverage_role != "brand_control" and any(
        token in normalized_text for token in product_tokens
    ):
        return "non-brand coverage question exposed product identity"
    model_tokens = product_name.split()
    model_token = model_tokens[-1].casefold() if model_tokens else ""
    if coverage_role == "brand_control" and (
        not model_token or model_token not in normalized_text
    ):
        return "brand-control question omitted the product model"
    return None
