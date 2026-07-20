"""Optional LlamaIndex Property Graph adapter behind project-owned contracts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Sequence

from pydantic import PrivateAttr

from geo_core.rag.contracts import (
    CandidateEntity,
    CandidateGraph,
    CandidateRelation,
    CandidateValidationFinding,
    JsonModelInvoker,
    QuestionPlan,
    RagAdapterError,
    RagSourceDocument,
)
from geo_core.rag.native import ProjectNativeRagAdapterV1

try:
    from llama_index.core import Document
    from llama_index.core.graph_stores.types import EntityNode
    from llama_index.core.indices.property_graph import PropertyGraphIndex
    from llama_index.core.indices.property_graph.transformations import SchemaLLMPathExtractor
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.llms import (
        CompletionResponse,
        CompletionResponseGen,
        CustomLLM,
        LLMMetadata,
    )
    from llama_index.core.llms.callbacks import llm_completion_callback
    from llama_index.core.node_parser import SentenceSplitter
except ImportError as exc:  # pragma: no cover - exercised by the isolated dependency probe.
    raise ImportError(
        "LlamaIndex adapter requires the pinned f019-rag optional dependency"
    ) from exc


ADAPTER_RELEASE = "llamaindex-property-graph-v1"
FRAMEWORK_VERSION = "llama-index-core-0.14.23"

class EntitySchema(StrEnum):
    BRAND = "BRAND"
    PRODUCT = "PRODUCT"
    COMPETITOR = "COMPETITOR"
    FEATURE = "FEATURE"
    SPECIFICATION = "SPECIFICATION"
    USE_CASE = "USE_CASE"
    PERSONA = "PERSONA"
    PAIN_POINT = "PAIN_POINT"
    MARKET = "MARKET"
    CHANNEL = "CHANNEL"


class RelationSchema(StrEnum):
    BELONGS_TO = "BELONGS_TO"
    HAS_FEATURE = "HAS_FEATURE"
    HAS_SPECIFICATION = "HAS_SPECIFICATION"
    COMPETES_WITH = "COMPETES_WITH"
    BELONGS_TO_MARKET = "BELONGS_TO_MARKET"
    USES_CHANNEL = "USES_CHANNEL"
    COMPATIBLE_WITH = "COMPATIBLE_WITH"
    HAS_PAIN_POINT = "HAS_PAIN_POINT"
    SUPPORTS_USE_CASE = "SUPPORTS_USE_CASE"

_VALID_RELATIONSHIPS = [
    ("PRODUCT", "BELONGS_TO", "BRAND"),
    ("PRODUCT", "HAS_FEATURE", "FEATURE"),
    ("PRODUCT", "HAS_SPECIFICATION", "SPECIFICATION"),
    ("PRODUCT", "COMPETES_WITH", "COMPETITOR"),
    ("PERSONA", "BELONGS_TO_MARKET", "MARKET"),
    ("PERSONA", "USES_CHANNEL", "CHANNEL"),
    ("PRODUCT", "USES_CHANNEL", "CHANNEL"),
    ("PRODUCT", "COMPATIBLE_WITH", "PRODUCT"),
    ("PERSONA", "HAS_PAIN_POINT", "PAIN_POINT"),
    ("PRODUCT", "SUPPORTS_USE_CASE", "USE_CASE"),
]
_RELATION_NAMES = frozenset(
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

_GRAPH_PROMPT = """Extract the explicit knowledge-graph paths in the text below.
Use only names and relationships that occur in the source. Preserve exact spelling. Do not infer
relationships, add common knowledge, translate names, or treat excluded/noisy material as facts.
Return no path unless both endpoint names and the relationship are explicitly supported.

Source text:
{text}
"""

_TYPE_NAMES = {
    "BRAND": "Brand",
    "PRODUCT": "Product",
    "COMPETITOR": "Competitor",
    "FEATURE": "Feature",
    "SPECIFICATION": "Specification",
    "USE_CASE": "UseCase",
    "PERSONA": "Persona",
    "PAIN_POINT": "PainPoint",
    "MARKET": "Market",
    "CHANNEL": "Channel",
}


class _GatewayLlamaLLM(CustomLLM):
    """Route every LlamaIndex call through the project model invocation port."""

    _invoker: JsonModelInvoker = PrivateAttr()
    _project_id: str = PrivateAttr()

    def __init__(self, invoker: JsonModelInvoker, project_id: str) -> None:
        super().__init__()
        self._invoker = invoker
        self._project_id = project_id

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=65536,
            num_output=4096,
            is_chat_model=False,
            is_function_calling_model=False,
            model_name="geo-audited-json-gateway",
        )

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        del formatted, kwargs
        messages = (
            {
                "role": "system",
                "content": (
                    "Follow the supplied extraction schema exactly and return one valid JSON "
                    "object. Do not include markdown or explanatory text."
                ),
            },
            {"role": "user", "content": prompt},
        )
        request_hash = hashlib.sha256(
            json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        output = self._invoker.complete_json(
            project_id=self._project_id,
            purpose="geo-rag-llamaindex-property-graph",
            messages=messages,
            request_hash=request_hash,
            max_output_tokens=4096,
        )
        return CompletionResponse(
            text=json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )

    @llm_completion_callback()
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        result = self.complete(prompt, formatted=formatted, **kwargs)

        def generate() -> CompletionResponseGen:
            yield CompletionResponse(text=result.text, delta=result.text)

        return generate()


class LlamaIndexPropertyGraphAdapterV1:
    """LlamaIndex ingestion and strict Property Graph extraction.

    Facts and governed question plans use the same project-native extraction boundary. Entity and
    relation candidates come from LlamaIndex's SchemaLLMPathExtractor and in-memory Property Graph;
    no framework object is returned or persisted as business data.
    """

    adapter_release = ADAPTER_RELEASE
    framework_version = FRAMEWORK_VERSION

    def __init__(self, model: JsonModelInvoker) -> None:
        self._model = model
        self._native = ProjectNativeRagAdapterV1(model)
        self._graph_cache: dict[
            str,
            tuple[
                tuple[CandidateEntity, ...],
                tuple[CandidateRelation, ...],
                tuple[CandidateValidationFinding, ...],
            ],
        ] = {}
        self._last_validation_findings: tuple[CandidateValidationFinding, ...] = ()

    @property
    def last_validation_findings(self) -> tuple[CandidateValidationFinding, ...]:
        return self._last_validation_findings

    def extract(
        self,
        documents: Sequence[RagSourceDocument],
        question_plans: Sequence[QuestionPlan] = (),
    ) -> CandidateGraph:
        self._last_validation_findings = ()
        try:
            native = self._native.extract(documents, question_plans)
        except Exception:
            self._last_validation_findings = self._native.last_validation_findings
            raise
        entity_sources: dict[tuple[str, str, str], set[str]] = {}
        relations: list[CandidateRelation] = []
        findings = list(native.validation_findings)
        self._last_validation_findings = tuple(findings)
        for document in sorted(documents, key=lambda item: (item.project_id, item.document_id)):
            entities, document_relations, document_findings = self._extract_document_graph(document)
            relations.extend(document_relations)
            findings.extend(document_findings)
            self._last_validation_findings = tuple(findings)
            for entity in entities:
                key = (entity.project_id, entity.entity_type, entity.name)
                entity_sources.setdefault(key, set()).update(entity.source_document_ids)
        entities = tuple(
            CandidateEntity(
                _candidate_id("entity", *key),
                key[0],
                key[1],
                key[2],
                tuple(sorted(source_ids)),
            )
            for key, source_ids in sorted(entity_sources.items())
        )
        return CandidateGraph(
            native.facts,
            entities,
            tuple(relations),
            native.questions,
            tuple(findings),
        )

    def _extract_document_graph(
        self, document: RagSourceDocument
    ) -> tuple[
        tuple[CandidateEntity, ...],
        tuple[CandidateRelation, ...],
        tuple[CandidateValidationFinding, ...],
    ]:
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "adapter_release": self.adapter_release,
                    "project_id": document.project_id,
                    "document_id": document.document_id,
                    "content": document.content,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cached = self._graph_cache.get(cache_key)
        if cached is not None:
            return cached

        llama_document = Document(
            text=document.content,
            id_=document.document_id,
            metadata={
                "project_id": document.project_id,
                "source_document_id": document.document_id,
                "source_locator": document.source_locator,
            },
            excluded_llm_metadata_keys=["project_id", "source_document_id", "source_locator"],
            excluded_embed_metadata_keys=["project_id", "source_document_id", "source_locator"],
        )
        nodes = IngestionPipeline(
            transformations=[
                SentenceSplitter(
                    chunk_size=2048,
                    chunk_overlap=0,
                    include_metadata=False,
                    include_prev_next_rel=False,
                )
            ]
        ).run(documents=[llama_document], show_progress=False)
        llm = _GatewayLlamaLLM(self._model, document.project_id)
        extractor = SchemaLLMPathExtractor(
            llm=llm,
            extract_prompt=_GRAPH_PROMPT,
            possible_entities=EntitySchema,
            possible_relations=RelationSchema,
            kg_validation_schema=_VALID_RELATIONSHIPS,
            strict=True,
            max_triplets_per_chunk=20,
            num_workers=1,
            allow_additional_properties=False,
        )
        index = PropertyGraphIndex(
            nodes=nodes,
            llm=llm,
            kg_extractors=[extractor],
            embed_kg_nodes=False,
            use_async=False,
            show_progress=False,
        )
        entity_values: set[tuple[str, str]] = set()
        relation_values: dict[tuple[str, str, str], str] = {}
        findings: list[CandidateValidationFinding] = []
        for subject_node, relation_node, object_node in index.property_graph_store.get_triplets(
            relation_names=sorted(name.upper() for name in _RELATION_NAMES)
        ):
            if not isinstance(subject_node, EntityNode) or not isinstance(
                object_node, EntityNode
            ):
                findings.append(
                    CandidateValidationFinding(
                        project_id=document.project_id,
                        source_document_id=document.document_id,
                        candidate_kind="llamaindex_triplet",
                        reason_code="unsupported_graph_endpoint",
                        candidate_hash=_triplet_hash(
                            subject_node.label,
                            subject_node.id,
                            str(relation_node.label),
                            object_node.label,
                            object_node.id,
                        ),
                    )
                )
                continue
            subject = str(subject_node.name).strip()
            obj = str(object_node.name).strip()
            predicate = str(relation_node.label).strip().lower()
            candidate_hash = _triplet_hash(
                str(subject_node.label), subject, predicate, str(object_node.label), obj
            )
            try:
                subject_type = _entity_type(str(subject_node.label))
                object_type = _entity_type(str(object_node.label))
                if (
                    not subject
                    or not obj
                    or subject not in document.content
                    or obj not in document.content
                ):
                    raise _LlamaCandidateValidationError("untraceable_graph_endpoint")
                if predicate not in _RELATION_NAMES:
                    raise _LlamaCandidateValidationError("unsupported_graph_relation")
                locator = _relation_locator(document.content, subject, obj)
                if locator is None:
                    raise _LlamaCandidateValidationError("untraceable_graph_relation")
            except _LlamaCandidateValidationError as exc:
                findings.append(
                    CandidateValidationFinding(
                        project_id=document.project_id,
                        source_document_id=document.document_id,
                        candidate_kind="llamaindex_triplet",
                        reason_code=exc.reason_code,
                        candidate_hash=candidate_hash,
                    )
                )
                continue
            entity_values.add((subject_type, subject))
            entity_values.add((object_type, obj))
            relation_values[(subject, predicate, obj)] = locator

        entities = tuple(
            CandidateEntity(
                _candidate_id("entity", document.project_id, entity_type, name),
                document.project_id,
                entity_type,
                name,
                (document.document_id,),
            )
            for entity_type, name in sorted(entity_values)
        )
        relations = tuple(
            CandidateRelation(
                _candidate_id(
                    "relation", document.project_id, document.document_id, subject, predicate, obj
                ),
                document.project_id,
                subject,
                predicate,
                obj,
                document.document_id,
                locator,
            )
            for (subject, predicate, obj), locator in sorted(relation_values.items())
        )
        result = (entities, relations, tuple(findings))
        self._graph_cache[cache_key] = result
        return result


class _LlamaCandidateValidationError(RagAdapterError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _entity_type(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "_")
    try:
        return _TYPE_NAMES[normalized]
    except KeyError as exc:
        raise _LlamaCandidateValidationError("unsupported_graph_entity_type") from exc


def _relation_locator(content: str, subject: str, obj: str) -> str | None:
    for line_number, line in enumerate(content.splitlines(), 1):
        if subject in line and obj in line:
            return f"line:{line_number}"
    return None


def _triplet_hash(
    subject_type: str,
    subject: str,
    predicate: str,
    object_type: str,
    obj: str,
) -> str:
    canonical = json.dumps(
        {
            "subject_type": subject_type,
            "subject": subject,
            "predicate": predicate,
            "object_type": object_type,
            "object": obj,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _candidate_id(kind: str, *values: str) -> str:
    return f"{kind}-{hashlib.sha256('|'.join(values).encode()).hexdigest()[:24]}"
