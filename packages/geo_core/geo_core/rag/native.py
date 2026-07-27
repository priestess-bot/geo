"""Project-native structured extraction behind the stable RAG adapter boundary."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Mapping, Sequence

from geo_core.rag.contracts import (
    CandidateEntity,
    CandidateFact,
    CandidateGraph,
    CandidateQuestion,
    CandidateRelation,
    CandidateValidationFinding,
    JsonModelInvoker,
    QuestionPlan,
    RagAdapterError,
    RagSourceDocument,
)


ADAPTER_RELEASE = "project-native-rag-v1"
ENTITY_TYPES = frozenset(
    {
        "Brand",
        "Product",
        "Competitor",
        "Feature",
        "Specification",
        "UseCase",
        "Persona",
        "PainPoint",
        "Market",
        "Channel",
    }
)
RELATION_TYPES = frozenset(
    {
        "belongs_to",
        "has_feature",
        "has_specification",
        "competes_with",
        "belongs_to_market",
        "uses_channel",
        "compatible_with",
        "has_pain_point",
        "supports_use_case",
    }
)

_SYSTEM_PROMPT = """You are an enterprise knowledge extraction engine.
Extract only facts, entities, and relations explicitly stated in the supplied source. Every
candidate field must be traceable to an exact substring of that source. For fact text, return the
smallest complete proposition and exclude preceding field labels, bullets, headings, or metadata;
the proposition itself must remain an exact source substring. Do not infer, paraphrase, translate,
add common knowledge, or treat navigation, marketing noise, warnings about excluded material, or
unverified claims as facts.

Return one JSON object with exactly these arrays:
{"facts":[{"text":"complete source sentence","source_quote":"exact source substring"}],
 "entities":[{"entity_type":"allowed type","name":"exact source name",
              "source_quote":"exact source substring"}],
 "relations":[{"subject":"exact entity name","predicate":"allowed relation key",
               "object":"exact entity name","source_quote":"exact source substring"}]}

Allowed entity types: Brand, Product, Competitor, Feature, Specification, UseCase, Persona,
PainPoint, Market, Channel.
Allowed relation keys: belongs_to, has_feature, has_specification, competes_with,
belongs_to_market, uses_channel, compatible_with, has_pain_point, supports_use_case.
Preserve source spelling and punctuation. Return JSON only."""

_QUESTION_GROUNDING_PROMPT = """You ground governed user-question plans in verified facts.
For every supplied dimension_key, select one or more fact_texts that directly answer its intent in
the stated scenario. Intent-specific evidence is more important than incidental words from the
subject or scenario. Select only exact strings from fact_candidates. Do not infer, paraphrase, or
use outside knowledge. Return every dimension_key exactly once with at least one supporting fact.

Return one JSON object only:
{"supports":[{"dimension_key":"exact supplied key","fact_texts":["exact candidate text"]}]}"""

RAG_EXTRACTION_OUTPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts", "entities", "relations"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "source_quote"],
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "source_quote": {"type": "string", "minLength": 1},
                },
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["entity_type", "name", "source_quote"],
                "properties": {
                    "entity_type": {"type": "string", "minLength": 1},
                    "name": {"type": "string", "minLength": 1},
                    "source_quote": {"type": "string", "minLength": 1},
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["subject", "predicate", "object", "source_quote"],
                "properties": {
                    "subject": {"type": "string", "minLength": 1},
                    "predicate": {"type": "string", "minLength": 1},
                    "object": {"type": "string", "minLength": 1},
                    "source_quote": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}


class ProjectNativeRagAdapterV1:
    """LLM-backed extraction plus governed plan-to-question generation.

    The adapter consumes only production contracts. It has no access to benchmark gold data,
    benchmark document classes, or fixture-specific parsing rules.
    """

    adapter_release = ADAPTER_RELEASE

    def __init__(self, model: JsonModelInvoker) -> None:
        self._model = model
        self._cache: dict[str, CandidateGraph] = {}
        self._question_cache: dict[str, tuple[CandidateQuestion, ...]] = {}
        self._last_validation_findings: tuple[CandidateValidationFinding, ...] = ()

    @property
    def last_validation_findings(self) -> tuple[CandidateValidationFinding, ...]:
        return self._last_validation_findings

    def extract(
        self,
        documents: Sequence[RagSourceDocument],
        question_plans: Sequence[QuestionPlan] = (),
    ) -> CandidateGraph:
        document_by_id = _documents_by_id(documents)
        plans_by_document: dict[str, list[QuestionPlan]] = defaultdict(list)
        for plan in question_plans:
            document = document_by_id.get(plan.source_document_id)
            if document is None:
                raise RagAdapterError(
                    "question plan references a source document outside the batch"
                )
            plans_by_document[plan.source_document_id].append(plan)

        facts: list[CandidateFact] = []
        relations: list[CandidateRelation] = []
        entity_sources: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        questions: list[CandidateQuestion] = []
        findings: list[CandidateValidationFinding] = []
        groups_with_facts: set[str] = set()
        self._last_validation_findings = ()
        for document in sorted(documents, key=lambda item: (item.project_id, item.document_id)):
            graph = self._extract_document(document)
            findings.extend(graph.validation_findings)
            self._last_validation_findings = tuple(findings)
            if graph.facts:
                groups_with_facts.add(document.group_id)
            facts.extend(graph.facts)
            relations.extend(graph.relations)
            for entity in graph.entities:
                entity_sources[(entity.project_id, entity.entity_type, entity.name)].update(
                    entity.source_document_ids
                )
            questions.extend(
                self._questions_for_plans(
                    document,
                    graph.facts,
                    plans_by_document[document.document_id],
                )
            )

        missing_groups = {document.group_id for document in documents} - groups_with_facts
        if missing_groups:
            raise RagAdapterError("document produced no traceable fact candidate")

        entities = tuple(
            CandidateEntity(
                candidate_id=_candidate_id("entity", *key),
                project_id=key[0],
                entity_type=key[1],
                name=key[2],
                source_document_ids=tuple(sorted(source_ids)),
            )
            for key, source_ids in sorted(entity_sources.items())
        )
        return CandidateGraph(
            tuple(facts),
            entities,
            tuple(relations),
            tuple(questions),
            tuple(findings),
        )

    def _extract_document(self, document: RagSourceDocument) -> CandidateGraph:
        cache_key = _sha(
            json.dumps(
                {
                    "adapter_release": self.adapter_release,
                    "project_id": document.project_id,
                    "document_id": document.document_id,
                    "content": document.content,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        messages = (
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "title": document.title,
                        "source_locator": document.source_locator,
                        "content": document.content,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        )
        request_hash = _sha(
            json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        output = self._model.complete_json(
            project_id=document.project_id,
            purpose="geo-rag-graph-extraction",
            messages=messages,
            request_hash=request_hash,
            max_output_tokens=3000,
        )
        graph = _validate_model_output(document, output)
        self._cache[cache_key] = graph
        return graph

    def _questions_for_plans(
        self,
        document: RagSourceDocument,
        facts: Sequence[CandidateFact],
        plans: Sequence[QuestionPlan],
    ) -> tuple[CandidateQuestion, ...]:
        if not plans:
            return ()
        if not facts:
            raise RagAdapterError("a governed question plan has no traceable fact candidate")
        ordered_plans = tuple(sorted(plans, key=lambda item: item.dimension_key))
        cache_key = _sha(
            json.dumps(
                {
                    "adapter_release": self.adapter_release,
                    "document_id": document.document_id,
                    "facts": [(item.candidate_id, item.text) for item in facts],
                    "plans": [
                        {
                            "dimension_key": item.dimension_key,
                            "persona": item.persona,
                            "scenario": item.scenario,
                            "intent": item.intent,
                            "funnel": item.funnel,
                            "region": item.region,
                            "language": item.language,
                            "brand_scope": item.brand_scope,
                            "platform": item.platform,
                            "subject": item.subject,
                        }
                        for item in ordered_plans
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        cached = self._question_cache.get(cache_key)
        if cached is not None:
            return cached
        messages = (
            {"role": "system", "content": _QUESTION_GROUNDING_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "fact_candidates": [item.text for item in facts],
                        "question_plans": [
                            {
                                "dimension_key": item.dimension_key,
                                "persona": item.persona,
                                "scenario": item.scenario,
                                "intent": item.intent,
                                "funnel": item.funnel,
                                "region": item.region,
                                "language": item.language,
                                "brand_scope": item.brand_scope,
                                "platform": item.platform,
                                "subject": item.subject,
                            }
                            for item in ordered_plans
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        )
        output = self._model.complete_json(
            project_id=document.project_id,
            purpose="geo-rag-question-grounding",
            messages=messages,
            request_hash=_sha(
                json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            ),
            max_output_tokens=2000,
        )
        questions = _validated_questions(document, facts, ordered_plans, output)
        self._question_cache[cache_key] = questions
        return questions


def _documents_by_id(documents: Sequence[RagSourceDocument]) -> dict[str, RagSourceDocument]:
    result: dict[str, RagSourceDocument] = {}
    for document in documents:
        previous = result.get(document.document_id)
        if previous is not None:
            raise RagAdapterError("RAG document IDs must be unique within one extraction batch")
        result[document.document_id] = document
    return result


def _validate_model_output(
    document: RagSourceDocument, output: Mapping[str, object]
) -> CandidateGraph:
    if set(output) != {"facts", "entities", "relations"}:
        raise RagAdapterError("model output must contain only facts, entities, and relations")
    fact_rows = _rows(output["facts"], "facts")
    entity_rows = _rows(output["entities"], "entities")
    relation_rows = _rows(output["relations"], "relations")

    facts: list[CandidateFact] = []
    findings: list[CandidateValidationFinding] = []
    seen_facts: set[str] = set()
    for row in fact_rows:
        try:
            _exact_keys(row, {"text", "source_quote"}, "fact")
            text = _source_text(row, "text", document, "fact")
            quote = _source_text(row, "source_quote", document, "fact source quote")
        except _CandidateValidationError as exc:
            findings.append(_finding(document, "fact", exc.reason_code, row))
            continue
        if text in seen_facts:
            continue
        seen_facts.add(text)
        facts.append(
            CandidateFact(
                _candidate_id("fact", document.project_id, document.document_id, text),
                document.project_id,
                text,
                document.document_id,
                _line_locator(document.content, quote),
            )
        )

    entity_values: list[tuple[str, str]] = []
    seen_entities: set[tuple[str, str]] = set()
    for row in entity_rows:
        try:
            _exact_keys(row, {"entity_type", "name", "source_quote"}, "entity")
            entity_type = _text(row, "entity_type", "entity")
            if entity_type not in ENTITY_TYPES:
                raise _CandidateValidationError("unsupported_entity_type")
            name = _source_text(row, "name", document, "entity name")
            _source_text(row, "source_quote", document, "entity source quote")
        except _CandidateValidationError as exc:
            findings.append(_finding(document, "entity", exc.reason_code, row))
            continue
        entity_key = (entity_type, name)
        if entity_key not in seen_entities:
            entity_values.append(entity_key)
            seen_entities.add(entity_key)

    relations: list[CandidateRelation] = []
    seen_relations: set[tuple[str, str, str]] = set()
    for row in relation_rows:
        try:
            _exact_keys(row, {"subject", "predicate", "object", "source_quote"}, "relation")
            subject = _source_text(row, "subject", document, "relation subject")
            predicate = _text(row, "predicate", "relation")
            if predicate not in RELATION_TYPES:
                raise _CandidateValidationError("unsupported_relation_type")
            obj = _source_text(row, "object", document, "relation object")
            quote = _source_text(row, "source_quote", document, "relation source quote")
            if subject not in quote or obj not in quote:
                raise _CandidateValidationError("relation_quote_missing_endpoint")
        except _CandidateValidationError as exc:
            findings.append(_finding(document, "relation", exc.reason_code, row))
            continue
        relation_key = (subject, predicate, obj)
        if subject == obj or relation_key in seen_relations:
            continue
        seen_relations.add(relation_key)
        relations.append(
            CandidateRelation(
                _candidate_id("relation", document.project_id, document.document_id, *relation_key),
                document.project_id,
                subject,
                predicate,
                obj,
                document.document_id,
                _line_locator(document.content, quote),
            )
        )

    entities = tuple(
        CandidateEntity(
            _candidate_id("entity", document.project_id, entity_type, name),
            document.project_id,
            entity_type,
            name,
            (document.document_id,),
        )
        for entity_type, name in entity_values
    )
    return CandidateGraph(tuple(facts), entities, tuple(relations), (), tuple(findings))


def _validated_questions(
    document: RagSourceDocument,
    facts: Sequence[CandidateFact],
    plans: Sequence[QuestionPlan],
    output: Mapping[str, object],
) -> tuple[CandidateQuestion, ...]:
    if set(output) != {"supports"}:
        raise RagAdapterError("question grounding output must contain only supports")
    rows = _rows(output["supports"], "question supports")
    plans_by_key = {item.dimension_key: item for item in plans}
    facts_by_text = {item.text: item for item in facts}
    support_by_key: dict[str, tuple[CandidateFact, ...]] = {}
    for row in rows:
        if set(row) != {"dimension_key", "fact_texts"}:
            raise RagAdapterError("question support output has unexpected fields")
        dimension_key = row.get("dimension_key")
        fact_texts = row.get("fact_texts")
        if not isinstance(dimension_key, str) or dimension_key not in plans_by_key:
            raise RagAdapterError("question support references an unknown dimension")
        if dimension_key in support_by_key:
            raise RagAdapterError("question support repeats a governed dimension")
        if (
            not isinstance(fact_texts, list)
            or not fact_texts
            or len(fact_texts) > len(facts)
            or not all(isinstance(value, str) for value in fact_texts)
        ):
            raise RagAdapterError("question support requires a bounded list of facts")
        selected: list[CandidateFact] = []
        for fact_text in fact_texts:
            fact = facts_by_text.get(fact_text)
            if fact is None:
                raise RagAdapterError("question support references text outside verified facts")
            if fact not in selected:
                selected.append(fact)
        support_by_key[dimension_key] = tuple(selected)
    if set(support_by_key) != set(plans_by_key):
        raise RagAdapterError("question grounding did not cover every governed dimension")

    result: list[CandidateQuestion] = []
    for plan in plans:
        support = support_by_key[plan.dimension_key]
        text = (
            f"{plan.persona}在{plan.scenario}时，应依据哪些可核验事实评估"
            f"{plan.subject}的{plan.intent}？"
        )
        result.append(
            CandidateQuestion(
                _candidate_id("question", document.project_id, plan.dimension_key, text),
                document.project_id,
                text,
                plan.dimension_key,
                tuple(item.candidate_id for item in support),
                (document.document_id,),
            )
        )
    return tuple(result)


def _rows(value: object, label: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or len(value) > 200:
        raise RagAdapterError(f"model {label} must be a bounded JSON array")
    if not all(isinstance(item, Mapping) for item in value):
        raise RagAdapterError(f"model {label} entries must be JSON objects")
    return list(value)


class _CandidateValidationError(RagAdapterError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _exact_keys(row: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(row) != expected:
        raise _CandidateValidationError(f"{label}_unexpected_fields")


def _text(row: Mapping[str, object], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise _CandidateValidationError(f"{label}_{key}_invalid")
    return value.strip()


def _source_text(
    row: Mapping[str, object], key: str, document: RagSourceDocument, label: str
) -> str:
    value = _text(row, key, label)
    if value not in document.content:
        raise _CandidateValidationError(f"{label.replace(' ', '_')}_untraceable")
    return value


def _finding(
    document: RagSourceDocument,
    candidate_kind: str,
    reason_code: str,
    row: Mapping[str, object],
) -> CandidateValidationFinding:
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return CandidateValidationFinding(
        project_id=document.project_id,
        source_document_id=document.document_id,
        candidate_kind=candidate_kind,
        reason_code=reason_code,
        candidate_hash=_sha(canonical),
    )


def _line_locator(content: str, quote: str) -> str:
    offset = content.find(quote)
    return f"line:{content.count(chr(10), 0, offset) + 1}"


def _candidate_id(kind: str, *values: str) -> str:
    return f"{kind}-{hashlib.sha256('|'.join(values).encode()).hexdigest()[:24]}"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
