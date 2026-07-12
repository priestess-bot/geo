from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

from geno_core.durable_jobs import (
    KNOWLEDGE_JOB_TABLES,
    ClaimMode,
    ClaimOutcome,
    LeaseFencedConnection,
    LeaseClaim,
    LeaseGuard,
    acknowledge_durable_cancel,
    begin_durable_finalizing,
    claim_durable_job,
    complete_durable_job,
    durable_job_spec,
    fail_durable_job,
    next_fair_table_order,
    record_recovery_pass,
    request_durable_cancel,
)
from geno_core.object_store import S3CompatibleObjectStore, StoredObject

PIPELINE_STAGE_KEYS = (
    "source_precheck",
    "asset_ingestion",
    "crawl",
    "parse",
    "ocr",
    "table_extract",
    "chunk",
    "quality_summary",
    "embedding",
    "fact_extract",
    "fact_review",
    "prompt_generate",
    "prompt_review",
    "content_generate",
    "content_review",
    "trace_verify",
    "publish_or_export",
)

JOB_TABLES = KNOWLEDGE_JOB_TABLES

KNOWLEDGE_TABLE_FILTERS: dict[str, dict[str, str]] = {
    "knowledge_import_jobs": {
        "pipeline_run_id": "pipeline_run_id",
        "status": "status",
        "source_mode": "source_mode",
        "created_by": "created_by",
    },
    "knowledge_source_assets": {
        "pipeline_run_id": "pipeline_run_id",
        "import_job_id": "import_job_id",
        "asset_type": "asset_type",
        "status": "status",
    },
    "knowledge_parser_runs": {
        "pipeline_run_id": "pipeline_run_id",
        "import_job_id": "import_job_id",
        "source_asset_id": "source_asset_id",
        "status": "status",
        "adapter_engine": "adapter_engine",
    },
    "knowledge_blocks": {"pipeline_run_id": "pipeline_run_id", "source_asset_id": "source_asset_id", "parser_run_id": "parser_run_id"},
    "knowledge_tables": {"pipeline_run_id": "pipeline_run_id", "source_asset_id": "source_asset_id", "parser_run_id": "parser_run_id"},
    "knowledge_ocr_spans": {"pipeline_run_id": "pipeline_run_id", "source_asset_id": "source_asset_id", "parser_run_id": "parser_run_id"},
    "knowledge_page_snapshots": {"pipeline_run_id": "pipeline_run_id", "source_asset_id": "source_asset_id", "parser_run_id": "parser_run_id"},
    "knowledge_quality_findings": {
        "pipeline_run_id": "pipeline_run_id",
        "target_type": "target_type",
        "severity": "severity",
        "status": "status",
    },
    "knowledge_quality_gate_runs": {
        "pipeline_run_id": "pipeline_run_id",
        "stage_id": "pipeline_stage_id",
        "gate_key": "gate_key",
        "status": "status",
    },
    "knowledge_trace_refs": {
        "pipeline_run_id": "pipeline_run_id",
        "source_type": "source_type",
        "source_id": "source_id",
        "target_type": "target_type",
        "target_id": "target_id",
    },
    "knowledge_chunks": {
        "pipeline_run_id": "pipeline_run_id",
        "import_job_id": "import_job_id",
        "source_asset_id": "source_asset_id",
        "chunk_type": "chunk_type",
        "status": "status",
        "embedding_status": "embedding_status",
        "market_code": "market_code",
        "city": "city",
    },
    "knowledge_fact_candidates": {
        "pipeline_run_id": "pipeline_run_id",
        "fact_kind": "fact_kind",
        "status": "status",
        "market_code": "market_code",
        "city": "city",
    },
    "localized_knowledge_facts": {"status": "status", "fact_kind": "fact_kind", "market_code": "market_code", "city": "city"},
    "fact_extraction_jobs": {"pipeline_run_id": "pipeline_run_id", "import_job_id": "import_job_id", "status": "status"},
    "prompt_generation_jobs": {"pipeline_run_id": "pipeline_run_id", "target_platform": "target_platform", "intent_type": "intent_type", "status": "status"},
    "content_generation_jobs": {"pipeline_run_id": "pipeline_run_id", "content_type": "content_type", "target_city": "target_city", "status": "status"},
    "prompt_candidates": {
        "pipeline_run_id": "pipeline_run_id",
        "target_platform": "target_platform",
        "intent_type": "intent_type",
        "status": "review_status",
    },
    "content_drafts": {
        "pipeline_run_id": "pipeline_run_id",
        "content_type": "content_type",
        "target_city": "target_city",
        "status": "status",
    },
}

KNOWLEDGE_TABLE_QUERY_COLUMNS: dict[str, tuple[str, ...]] = {
    "knowledge_import_jobs": ("created_by",),
    "knowledge_source_assets": ("title", "filename", "source_uri"),
    "knowledge_blocks": ("text",),
    "knowledge_tables": ("caption", "markdown"),
    "knowledge_ocr_spans": ("text",),
    "knowledge_chunks": ("text",),
    "knowledge_fact_candidates": ("subject", "predicate", "object_value"),
    "localized_knowledge_facts": ("subject", "predicate", "object_value"),
    "prompt_candidates": ("text", "rationale"),
    "content_drafts": ("title", "summary", "draft_markdown"),
}


def source_config_text(source_config: dict[str, Any]) -> str:
    """Return text payloads accepted by the public import contract."""
    for key in ("text", "pasted_text", "raw_text", "csv_content"):
        value = source_config.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""

KNOWLEDGE_UUID_FILTER_KEYS = {
    "pipeline_run_id",
    "import_job_id",
    "source_asset_id",
    "parser_run_id",
    "stage_id",
}


def _public_job_record(record: dict[str, Any]) -> dict[str, Any]:
    public = dict(record)
    public.pop("lease_token", None)
    public.pop("finalize_descriptor", None)
    return public

DEFAULT_QDRANT_COLLECTION = "geo_knowledge_chunks_bge_m3_v1"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_EMBEDDING_MODEL_VERSION = "bge-m3-local-v1"
DEFAULT_EMBEDDING_DIMENSION = 1024
MAX_KNOWLEDGE_FILE_BYTES = 50 * 1024 * 1024
SUPPORTED_KNOWLEDGE_SUFFIXES = {
    "pdf", "docx", "pptx", "xlsx", "csv", "txt", "md", "markdown", "html", "htm",
    "png", "jpg", "jpeg", "webp", "tif", "tiff",
}

COMPONENT_PYTHON_ENV = {
    "docling": "GEO_DOCLING_PYTHON",
    "mineru": "GEO_MINERU_PYTHON",
    "unstructured": "GEO_UNSTRUCTURED_PYTHON",
    "markitdown": "GEO_MARKITDOWN_PYTHON",
    "tika": "GEO_TIKA_PYTHON",
    "crawl4ai": "GEO_CRAWL4AI_PYTHON",
    "bge": "GEO_BGE_M3_PYTHON",
}


@dataclass(frozen=True)
class KnowledgePipelineCreateInput:
    project_id: str
    run_type: str = "full_ingestion"
    entry_source: str = "mixed"
    market_code: str = "GLOBAL"
    locale: str = "en"
    city: str | None = None
    created_by: str = "runtime-console"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeImportCreateInput:
    project_id: str
    pipeline_run_id: str
    source_mode: str
    requested_by: str = "runtime-console"
    source_config: dict[str, Any] = field(default_factory=dict)
    priority: int = 0


def stable_pipeline_id(kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, "geo:knowledge:" + ":".join(str(part) for part in parts)))


def payload_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def content_hash(content: str | bytes) -> str:
    value = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(value).hexdigest()


def precheck_knowledge_source(*, filename: str, content: bytes, content_type: str) -> dict[str, Any]:
    normalized_name = Path(filename.strip() or "knowledge-source").name
    suffix = normalized_name.rsplit(".", 1)[-1].lower() if "." in normalized_name else ""
    findings: list[dict[str, str]] = []
    if not content:
        findings.append({"code": "empty_file", "severity": "blocked", "message": "The file is empty."})
    if len(content) > MAX_KNOWLEDGE_FILE_BYTES:
        findings.append({"code": "file_too_large", "severity": "blocked", "message": "The file exceeds 50 MB."})
    if suffix not in SUPPORTED_KNOWLEDGE_SUFFIXES:
        findings.append(
            {"code": "unsupported_file_type", "severity": "blocked", "message": f"Unsupported file type: {suffix or 'none'}."}
        )
    if suffix == "pdf" and b"/Encrypt" in content[-256_000:]:
        findings.append({"code": "encrypted_file", "severity": "blocked", "message": "Encrypted PDFs require manual handling."})

    decoded = content[:2_000_000].decode("utf-8", errors="ignore")
    secret_patterns = (
        r"\bsk-[A-Za-z0-9_-]{16,}\b",
        r"(?i)\b(?:api[_ -]?key|secret[_ -]?key|access[_ -]?token)\s*[:=]\s*[^\s,;]{8,}",
    )
    if any(re.search(pattern, decoded) for pattern in secret_patterns):
        findings.append(
            {"code": "possible_secret", "severity": "blocked", "message": "The file appears to contain a secret or API key."}
        )
    pii_detected = bool(
        re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", decoded, flags=re.IGNORECASE)
        or re.search(r"(?<!\d)(?:\+?\d[\d ()-]{8,}\d)(?!\d)", decoded)
    )
    if pii_detected:
        findings.append(
            {"code": "possible_pii", "severity": "warning", "message": "The file may contain email addresses or phone numbers."}
        )

    image_only_pdf = suffix == "pdf" and b"/Subtype /Image" in content and b" BT" not in content and b"BT\n" not in content
    image_input = suffix in {"png", "jpg", "jpeg", "webp", "tif", "tiff"}
    requires_ocr = image_input or image_only_pdf
    table_dense = suffix in {"csv", "xlsx"} or decoded.count("|") >= 8 or decoded.count(",") >= 20
    if requires_ocr:
        recommendation = "mineru"
    elif suffix in {"pdf", "docx", "pptx", "xlsx", "html", "htm"}:
        recommendation = "docling"
    elif suffix in {"md", "markdown", "txt", "csv"} or content_type.startswith("text/"):
        recommendation = "markitdown"
    else:
        recommendation = "mineru"
    blocked = any(finding["severity"] == "blocked" for finding in findings)
    return {
        "accepted": not blocked,
        "filename": normalized_name,
        "suffix": suffix,
        "content_type": content_type or "application/octet-stream",
        "byte_size": len(content),
        "content_hash": content_hash(content),
        "requires_ocr": requires_ocr,
        "table_dense": table_dense,
        "recommended_adapter": recommendation,
        "findings": findings,
    }


def _now() -> datetime:
    return datetime.now(UTC)


def _compact_text(value: str, *, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def deterministic_embedding(text: str, *, dimensions: int = DEFAULT_EMBEDDING_DIMENSION) -> list[float]:
    """Deterministic vector for isolated tests; production workers must not use it."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    while len(values) < dimensions:
        for byte in digest:
            values.append(round((byte / 127.5) - 1.0, 6))
            if len(values) >= dimensions:
                break
        digest = hashlib.sha256(digest).digest()
    return values


def _component_python(component: str) -> Path:
    configured = os.getenv(COMPONENT_PYTHON_ENV[component], "").strip()
    return Path(configured or f"/opt/venvs/{component}/bin/python")


def _component_runner_path() -> Path:
    configured = os.getenv("GEO_KNOWLEDGE_COMPONENT_RUNNER", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "scripts" / "run_knowledge_component.py"


def _run_component(command: list[str], *, timeout: int) -> dict[str, Any]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout)
    output_path = Path(command[command.index("--output") + 1])
    payload: dict[str, Any] = {}
    if output_path.exists():
        value = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            payload = value
    if completed.returncode != 0 or payload.get("status") != "pass":
        error = str(payload.get("error") or completed.stderr[-2000:] or "component execution failed")
        raise RuntimeError(error)
    payload.pop("status", None)
    return payload


def crawl_with_crawl4ai(
    source_url: str,
    *,
    max_pages: int = 1,
    depth_limit: int = 0,
    crawl_mode: str = "single_url",
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    respect_robots: bool = True,
) -> dict[str, Any]:
    python_exe = _component_python("crawl4ai")
    runner = _component_runner_path()
    if not python_exe.exists() or not runner.exists():
        raise RuntimeError(f"Crawl4AI runtime is missing: python={python_exe} runner={runner}")
    with tempfile.TemporaryDirectory(prefix="geo-crawl4ai-") as tmp:
        output_path = Path(tmp) / "crawl.json"
        command = [
                str(python_exe),
                str(runner),
                "crawl",
                "--url",
                source_url,
                "--output",
                str(output_path),
                "--max-pages",
                str(max(1, min(500, max_pages))),
                "--depth-limit",
                str(max(0, min(5, depth_limit))),
                "--crawl-mode",
                crawl_mode,
                "--respect-robots" if respect_robots else "--no-respect-robots",
            ]
        for pattern in include_patterns or []:
            command.extend(["--include-pattern", pattern])
        for pattern in exclude_patterns or []:
            command.extend(["--exclude-pattern", pattern])
        return _run_component(command, timeout=int(os.getenv("GEO_CRAWL4AI_TIMEOUT_SECONDS", "900")))


class LocalBgeM3Embedder:
    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        *,
        allow_deterministic_fallback: bool = False,
    ) -> None:
        self.model_name = os.getenv("GEO_BGE_M3_MODEL", "").strip() or model_name
        self.allow_deterministic_fallback = allow_deterministic_fallback
        self._model: Any | None = None
        self.last_backend = "not_run"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        errors: list[str] = []
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            if self._model is None:
                self._model = SentenceTransformer(self.model_name, device="cpu")
            vectors = self._model.encode(texts, normalize_embeddings=True)
            self.last_backend = "sentence-transformers:in-process"
            return [[float(value) for value in vector] for vector in vectors]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"in-process: {exc}")
        python_exe = _component_python("bge")
        runner = _component_runner_path()
        if python_exe.exists() and runner.exists():
            try:
                with tempfile.TemporaryDirectory(prefix="geo-bge-") as tmp:
                    input_path = Path(tmp) / "texts.json"
                    output_path = Path(tmp) / "vectors.json"
                    input_path.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
                    payload = _run_component(
                        [
                            str(python_exe),
                            str(runner),
                            "embed",
                            "--input",
                            str(input_path),
                            "--output",
                            str(output_path),
                            "--model",
                            self.model_name,
                            "--device",
                            "cpu",
                        ],
                        timeout=int(os.getenv("GEO_BGE_M3_TIMEOUT_SECONDS", "900")),
                    )
                vectors = payload.get("vectors")
                if not isinstance(vectors, list) or len(vectors) != len(texts):
                    raise RuntimeError("BGE-M3 returned an invalid vector batch")
                self.last_backend = "sentence-transformers:isolated"
                return [[float(value) for value in vector] for vector in vectors]
            except Exception as exc:  # noqa: BLE001
                errors.append(f"isolated: {exc}")
        else:
            errors.append(f"isolated runtime missing: python={python_exe} runner={runner}")
        if self.allow_deterministic_fallback:
            self.last_backend = "deterministic-test-fallback"
            return [deterministic_embedding(text) for text in texts]
        raise RuntimeError("BGE-M3 embedding failed; " + "; ".join(errors))


class QdrantKnowledgeStore:
    def __init__(self, *, url: str | None = None, collection: str = DEFAULT_QDRANT_COLLECTION) -> None:
        self.url = (url or os.getenv("QDRANT_URL") or "").rstrip("/")
        self.collection = collection or os.getenv("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION)

    def enabled(self) -> bool:
        return bool(self.url)

    def ensure_collection(self, *, vector_size: int) -> None:
        if not self.enabled():
            return
        try:
            response = httpx.get(f"{self.url}/collections/{self.collection}", timeout=10)
            if response.status_code == 200:
                result = response.json().get("result") or {}
                vectors = ((result.get("config") or {}).get("params") or {}).get("vectors") or {}
                existing_size = vectors.get("size") if isinstance(vectors, dict) else None
                if existing_size is not None and int(existing_size) != vector_size:
                    raise RuntimeError(
                        f"qdrant collection {self.collection} uses {existing_size} dimensions; expected {vector_size}"
                    )
                return
            response = httpx.put(
                f"{self.url}/collections/{self.collection}",
                json={"vectors": {"size": vector_size, "distance": "Cosine"}},
                timeout=20,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"qdrant collection setup failed: {exc}") from exc

    def upsert(self, *, points: list[dict[str, Any]], vector_size: int) -> None:
        if not self.enabled() or not points:
            return
        self.ensure_collection(vector_size=vector_size)
        response = httpx.put(
            f"{self.url}/collections/{self.collection}/points?wait=true",
            json={"points": points},
            timeout=30,
        )
        response.raise_for_status()

    def search(self, *, vector: list[float], project_id: str, limit: int = 10, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self.enabled():
            return []
        must = [
            {"key": "project_id", "match": {"value": project_id}},
            {"key": "status", "match": {"value": "active"}},
            {"key": "embedding_status", "match": {"value": "embedded"}},
        ]
        for key, value in (filters or {}).items():
            if value not in (None, ""):
                must.append({"key": key, "match": {"value": value}})
        response = httpx.post(
            f"{self.url}/collections/{self.collection}/points/search",
            json={"vector": vector, "limit": limit, "with_payload": True, "filter": {"must": must}},
            timeout=20,
        )
        response.raise_for_status()
        return list(response.json().get("result") or [])

    def update_payload(self, *, point_ids: list[str], payload: dict[str, Any]) -> None:
        if not self.enabled() or not point_ids:
            return
        response = httpx.post(
            f"{self.url}/collections/{self.collection}/points/payload?wait=true",
            json={"payload": payload, "points": point_ids},
            timeout=20,
        )
        response.raise_for_status()

    def delete_points(self, *, point_ids: list[str]) -> None:
        if not self.enabled() or not point_ids:
            return
        response = httpx.post(
            f"{self.url}/collections/{self.collection}/points/delete?wait=true",
            json={"points": point_ids},
            timeout=20,
        )
        response.raise_for_status()


class SimpleHtmlToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in {"p", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
        self.parts.append(data)

    def text(self) -> str:
        return _compact_text("\n".join(self.parts), limit=200_000)


class GeoParserAdapter:
    adapter_version = "geo-parser-adapter-v1"

    def parse(self, *, text: str, source_asset_id: str, engine: str = "docling") -> dict[str, Any]:
        raw_text = str(text or "").replace("\r\n", "\n").strip()[:200_000]
        clean = _compact_text(raw_text, limit=200_000)
        blocks = []
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", raw_text) if part.strip()]
        if len(paragraphs) <= 1:
            paragraphs = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", clean) if part.strip()]
        for index, paragraph in enumerate(paragraphs[:500]):
            blocks.append(
                {
                    "id": stable_pipeline_id("block", source_asset_id, index, paragraph[:80]),
                    "page_number": 1,
                    "block_index": index,
                    "block_type": "paragraph",
                    "text": paragraph,
                    "bbox": None,
                    "section_path": [],
                    "html": None,
                    "markdown": paragraph,
                    "reading_order": index,
                    "confidence": 1.0,
                    "content_hash": content_hash(paragraph),
                    "metadata": {},
                }
            )
        return self._normalize_output({
            "adapter": {"engine": engine, "engine_version": "runtime-adapter", "adapter_version": self.adapter_version},
            "source_asset_id": source_asset_id,
            "pages": [{"page_number": 1, "text_preview": clean[:500]}],
            "blocks": blocks,
            "tables": [],
            "images": [],
            "ocr_spans": [],
            "metadata": {},
            "quality_signals": [] if blocks else [{"code": "parser_empty_text", "severity": "blocked"}],
            "artifacts": [],
        }, source_asset_id=source_asset_id)

    def parse_bytes(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        source_asset_id: str,
        requested_engine: str = "auto",
    ) -> dict[str, Any]:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix == "csv" or content_type.split(";", 1)[0].strip().lower() == "text/csv":
            return self._parse_csv(content=content, source_asset_id=source_asset_id, requested_engine=requested_engine)
        engine_order = self._engine_order(filename=filename, content_type=content_type, requested_engine=requested_engine)
        errors: list[dict[str, str]] = []
        for engine in engine_order:
            try:
                parsed: dict[str, Any] | None = None
                if engine == "markitdown":
                    parsed = self._parse_with_markitdown(content=content, filename=filename, source_asset_id=source_asset_id)
                elif engine == "tika":
                    parsed = self._parse_with_tika(content=content, filename=filename, source_asset_id=source_asset_id)
                elif engine == "unstructured":
                    parsed = self._parse_with_unstructured(content=content, filename=filename, source_asset_id=source_asset_id)
                elif engine == "docling":
                    parsed = self._parse_with_docling(content=content, filename=filename, source_asset_id=source_asset_id)
                elif engine == "mineru":
                    parsed = self._parse_with_mineru(content=content, filename=filename, source_asset_id=source_asset_id)
                if parsed is not None:
                    parsed = self._normalize_output(parsed, source_asset_id=source_asset_id)
                    if not parsed["blocks"] and not parsed["tables"] and not parsed["ocr_spans"]:
                        raise RuntimeError(f"{engine} produced no usable parser output")
                    parsed.setdefault("adapter", {})["requested_engine"] = requested_engine
                    if errors:
                        parsed["adapter"]["fallback_from_engines"] = [error["engine"] for error in errors]
                        parsed["adapter"]["fallback_reason"] = "; ".join(
                            f"{error['engine']}: {error['error']}" for error in errors
                        )[:2000]
                        parsed.setdefault("quality_signals", []).append(
                            {"code": "adapter_fallback_used", "severity": "warning", "errors": errors}
                        )
                    return parsed
            except Exception as exc:  # noqa: BLE001
                errors.append({"engine": engine, "error": str(exc)[:500]})
        text_fallback_allowed = suffix in {"txt", "md", "markdown", "csv", "html", "htm", "json"} or content_type.startswith("text/")
        if not text_fallback_allowed:
            raise RuntimeError(f"all production parser adapters failed for {filename}: {errors}")
        text = self._decode_text(content)
        parsed = self.parse(text=text, source_asset_id=source_asset_id, engine="text_fallback")
        parsed["adapter"]["fallback_from_engine"] = requested_engine
        parsed["adapter"]["fallback_reason"] = "; ".join(
            f"{error['engine']}: {error['error']}" for error in errors
        )[:2000]
        parsed["quality_signals"].append({"code": "adapter_fallback_used", "severity": "warning", "errors": errors})
        return parsed

    def _parse_csv(self, *, content: bytes, source_asset_id: str, requested_engine: str) -> dict[str, Any]:
        text = self._decode_text(content)
        rows = [[str(value) for value in row] for row in csv.reader(io.StringIO(text))]
        rows = [row for row in rows if any(value.strip() for value in row)]
        if not rows:
            raise RuntimeError("CSV source produced no rows")
        width = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (width - len(row)) for row in rows]
        markdown_lines = [
            "| " + " | ".join(normalized_rows[0]) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
            *("| " + " | ".join(row) + " |" for row in normalized_rows[1:]),
        ]
        markdown = "\n".join(markdown_lines)
        parsed = self.parse(text=markdown, source_asset_id=source_asset_id, engine="python_csv")
        parsed["adapter"].update({"requested_engine": requested_engine, "engine_version": "stdlib"})
        parsed["tables"] = [
            {
                "id": stable_pipeline_id("table", source_asset_id, 0),
                "page_number": 1,
                "table_index": 0,
                "caption": None,
                "table_json": {"rows": normalized_rows},
                "markdown": markdown,
                "row_count": len(normalized_rows),
                "column_count": width,
                "confidence": 1.0,
                "quality_flags": [],
                "metadata": {"delimiter": ",", "header_present": True},
            }
        ]
        parsed["artifacts"].append({"artifact_type": "parser_markdown", "content": markdown})
        return self._normalize_output(parsed, source_asset_id=source_asset_id)

    def _engine_order(self, *, filename: str, content_type: str, requested_engine: str) -> list[str]:
        requested = requested_engine.strip().lower()
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if requested and requested != "auto":
            automatic = self._engine_order(filename=filename, content_type=content_type, requested_engine="auto")
            return list(dict.fromkeys([requested, *automatic]))
        if suffix in {"md", "markdown", "txt", "csv"} or content_type.startswith("text/"):
            return ["markitdown", "unstructured", "tika"]
        if suffix in {"png", "jpg", "jpeg", "webp", "tif", "tiff"}:
            return ["mineru", "docling", "tika"]
        if suffix == "pdf":
            return ["docling", "mineru", "tika", "markitdown"]
        if suffix in {"docx", "pptx", "xlsx", "html", "htm"}:
            return ["docling", "markitdown", "unstructured", "tika"]
        return ["docling", "unstructured", "tika", "markitdown"]

    def _normalize_output(self, payload: dict[str, Any], *, source_asset_id: str) -> dict[str, Any]:
        normalized = dict(payload or {})
        adapter = dict(normalized.get("adapter") or {})
        adapter.setdefault("engine", "unknown")
        adapter.setdefault("engine_version", "unknown")
        adapter["adapter_version"] = self.adapter_version
        normalized["adapter"] = adapter
        normalized["source_asset_id"] = source_asset_id
        normalized["metadata"] = dict(normalized.get("metadata") or {})
        normalized["quality_signals"] = list(normalized.get("quality_signals") or [])
        normalized["artifacts"] = list(normalized.get("artifacts") or [])
        normalized["images"] = list(normalized.get("images") or [])

        blocks: list[dict[str, Any]] = []
        for index, raw in enumerate(normalized.get("blocks") or []):
            block = dict(raw or {})
            text = str(block.get("text") or "").strip()
            block.update(
                {
                    "id": str(block.get("id") or stable_pipeline_id("block", source_asset_id, index, text[:80])),
                    "page_number": int(block.get("page_number") or 1),
                    "block_index": int(block.get("block_index") if block.get("block_index") is not None else index),
                    "block_type": str(block.get("block_type") or "paragraph"),
                    "text": text,
                    "bbox": block.get("bbox"),
                    "section_path": list(block.get("section_path") or []),
                    "html": block.get("html"),
                    "markdown": block.get("markdown") or text,
                    "reading_order": int(block.get("reading_order") if block.get("reading_order") is not None else index),
                    "confidence": float(block.get("confidence") or 1.0),
                    "content_hash": str(block.get("content_hash") or content_hash(text)),
                    "metadata": dict(block.get("metadata") or {}),
                }
            )
            if text:
                blocks.append(block)
        normalized["blocks"] = blocks

        tables: list[dict[str, Any]] = []
        for index, raw in enumerate(normalized.get("tables") or []):
            table = dict(raw or {})
            table_json = dict(table.get("table_json") or {})
            rows = table_json.get("rows") if isinstance(table_json.get("rows"), list) else []
            column_count = max((len(row) for row in rows if isinstance(row, list)), default=0)
            table.update(
                {
                    "id": str(table.get("id") or stable_pipeline_id("table", source_asset_id, index)),
                    "page_number": int(table.get("page_number") or 1),
                    "table_index": int(table.get("table_index") if table.get("table_index") is not None else index),
                    "caption": table.get("caption"),
                    "table_json": table_json,
                    "markdown": str(table.get("markdown") or ""),
                    "row_count": int(table.get("row_count") or len(rows)),
                    "column_count": int(table.get("column_count") or column_count),
                    "confidence": float(table.get("confidence") or 0.0),
                    "quality_flags": list(table.get("quality_flags") or []),
                    "metadata": dict(table.get("metadata") or {}),
                }
            )
            tables.append(table)
        normalized["tables"] = tables

        ocr_spans: list[dict[str, Any]] = []
        for index, raw in enumerate(normalized.get("ocr_spans") or []):
            span = dict(raw or {})
            text = str(span.get("text") or "").strip()
            flags = list(span.get("quality_flags") or [])
            if span.get("bbox") is None and "ocr_missing_location" not in flags:
                flags.append("ocr_missing_location")
            span.update(
                {
                    "id": str(span.get("id") or stable_pipeline_id("ocr-span", source_asset_id, index, text[:80])),
                    "page_number": int(span.get("page_number") or 1),
                    "text": text,
                    "bbox": span.get("bbox"),
                    "confidence": float(span.get("confidence") or 0.0),
                    "language": span.get("language"),
                    "source_image_ref": span.get("source_image_ref"),
                    "content_hash": str(span.get("content_hash") or content_hash(text)),
                    "quality_flags": flags,
                    "metadata": dict(span.get("metadata") or {}),
                }
            )
            if text:
                ocr_spans.append(span)
        normalized["ocr_spans"] = ocr_spans

        pages: list[dict[str, Any]] = []
        for index, raw in enumerate(normalized.get("pages") or []):
            page = dict(raw or {})
            page.setdefault("page_number", index + 1)
            page.setdefault("text_preview", "")
            page.setdefault("metadata", {})
            pages.append(page)
        if not pages and (blocks or tables or ocr_spans):
            pages = [{"page_number": 1, "text_preview": "", "metadata": {}}]
        normalized["pages"] = pages
        return normalized

    def _parse_isolated(
        self,
        *,
        engine: str,
        content: bytes,
        filename: str,
        source_asset_id: str,
    ) -> dict[str, Any] | None:
        python_exe = _component_python(engine)
        runner = _component_runner_path()
        if not python_exe.exists() or not runner.exists():
            return None
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        with tempfile.TemporaryDirectory(prefix=f"geo-{engine}-") as tmp:
            input_path = Path(tmp) / f"source{suffix}"
            output_path = Path(tmp) / "result.json"
            input_path.write_bytes(content)
            payload = _run_component(
                [
                    str(python_exe),
                    str(runner),
                    "parse",
                    "--engine",
                    engine,
                    "--input",
                    str(input_path),
                    "--source-asset-id",
                    source_asset_id,
                    "--output",
                    str(output_path),
                ],
                timeout=int(os.getenv("GEO_PARSER_TIMEOUT_SECONDS", "600")),
            )
        for index, block in enumerate(payload.get("blocks") or []):
            block["id"] = stable_pipeline_id("block", source_asset_id, index, str(block.get("text") or "")[:80])
        payload["source_asset_id"] = source_asset_id
        return payload

    def _parse_with_docling(self, *, content: bytes, filename: str, source_asset_id: str) -> dict[str, Any]:
        isolated = self._parse_isolated(
            engine="docling", content=content, filename=filename, source_asset_id=source_asset_id
        )
        if isolated is not None:
            return isolated
        from tempfile import NamedTemporaryFile

        from docling.document_converter import DocumentConverter  # type: ignore

        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        with NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(content)
            tmp.flush()
            result = DocumentConverter().convert(tmp.name)
            markdown = result.document.export_to_markdown()
        parsed = self.parse(text=markdown, source_asset_id=source_asset_id, engine="docling")
        parsed["artifacts"].append({"artifact_type": "parser_markdown", "content": markdown})
        return parsed

    def _parse_with_unstructured(self, *, content: bytes, filename: str, source_asset_id: str) -> dict[str, Any]:
        isolated = self._parse_isolated(
            engine="unstructured", content=content, filename=filename, source_asset_id=source_asset_id
        )
        if isolated is not None:
            return isolated
        from tempfile import NamedTemporaryFile

        from unstructured.partition.auto import partition  # type: ignore

        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        with NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(content)
            tmp.flush()
            elements = partition(filename=tmp.name)
        text = "\n\n".join(str(element) for element in elements if str(element).strip())
        parsed = self.parse(text=text, source_asset_id=source_asset_id, engine="unstructured")
        parsed["metadata"]["element_count"] = len(elements)
        return parsed

    def _parse_with_tika(self, *, content: bytes, filename: str, source_asset_id: str) -> dict[str, Any]:
        isolated = self._parse_isolated(engine="tika", content=content, filename=filename, source_asset_id=source_asset_id)
        if isolated is not None:
            return isolated
        from tempfile import NamedTemporaryFile

        from tika import parser as tika_parser  # type: ignore

        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        with NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(content)
            tmp.flush()
            parsed_payload = tika_parser.from_file(tmp.name)
        text = str(parsed_payload.get("content") or "")
        parsed = self.parse(text=text, source_asset_id=source_asset_id, engine="tika")
        parsed["metadata"]["tika_metadata"] = parsed_payload.get("metadata") or {}
        return parsed

    def _parse_with_markitdown(self, *, content: bytes, filename: str, source_asset_id: str) -> dict[str, Any]:
        isolated = self._parse_isolated(
            engine="markitdown", content=content, filename=filename, source_asset_id=source_asset_id
        )
        if isolated is not None:
            return isolated
        from tempfile import NamedTemporaryFile

        from markitdown import MarkItDown  # type: ignore

        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        with NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(content)
            tmp.flush()
            result = MarkItDown().convert(tmp.name)
        markdown = str(getattr(result, "text_content", "") or "")
        parsed = self.parse(text=markdown, source_asset_id=source_asset_id, engine="markitdown")
        parsed["artifacts"].append({"artifact_type": "parser_markdown", "content": markdown})
        return parsed

    def _parse_with_mineru(self, *, content: bytes, filename: str, source_asset_id: str) -> dict[str, Any]:
        isolated = self._parse_isolated(engine="mineru", content=content, filename=filename, source_asset_id=source_asset_id)
        if isolated is None:
            raise RuntimeError("MinerU isolated runtime is not available")
        return isolated

    def _decode_text(self, content: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore")


def archive_knowledge_source_asset(
    *,
    project_id: str,
    pipeline_run_id: str | None,
    import_job_id: str | None,
    filename: str,
    content: bytes,
    content_type: str,
    store: S3CompatibleObjectStore,
) -> StoredObject:
    if not project_id.strip():
        raise ValueError("project_id is required")
    if not content:
        raise ValueError("knowledge source file is empty")
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.strip() or "knowledge-source").strip("-") or "knowledge-source"
    digest = hashlib.sha256(content).hexdigest()
    key = "/".join(
        [
            "knowledge-source-assets",
            project_id.strip(),
            pipeline_run_id or "manual",
            import_job_id or "unbound",
            f"{digest[:12]}-{safe_filename}",
        ]
    )
    return store.put_object(key=key, content=content, content_type=content_type, expected_hash=digest)


class KnowledgePipelineRepository:
    def __init__(self, connection: Any, *, database_url: str | None = None) -> None:
        self.connection = connection
        self.database_url = database_url

    def _record_audit(
        self,
        *,
        cursor: Any,
        event_type: str,
        project_id: str,
        actor_id: str,
        target_type: str,
        target_id: str,
        before: object,
        after: object,
        reason: str,
        method_version: str,
    ) -> None:
        before_hash = payload_hash(before)
        after_hash = payload_hash(after)
        audit_id = stable_pipeline_id(
            "audit",
            event_type,
            project_id,
            target_id,
            actor_id,
            before_hash,
            after_hash,
        )
        cursor.execute(
            """
            INSERT INTO audit_events (
              id, event_type, project_id, actor_type, actor_id, target_type, target_id,
              before_hash, after_hash, input_refs, output_refs, method_version, reason
            ) VALUES (%s::uuid, %s, %s::uuid, 'user', %s, %s, %s,
                      %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                audit_id,
                event_type,
                project_id,
                actor_id,
                target_type,
                target_id,
                before_hash,
                after_hash,
                json.dumps({"target_ids": [target_id]}, ensure_ascii=False),
                json.dumps({"status": (after or {}).get("status") if isinstance(after, dict) else None}, ensure_ascii=False),
                method_version,
                reason,
            ),
        )

    def create_pipeline_run(self, payload: KnowledgePipelineCreateInput) -> dict[str, Any]:
        from psycopg.rows import dict_row

        self.set_runtime_scope(actor_id=payload.created_by, project_id=payload.project_id)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_pipeline_runs (
                  project_id, run_type, status, entry_source, market_code, locale, city, created_by, metadata
                ) VALUES (%s::uuid, %s, 'ready', %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING *
                """,
                (
                    payload.project_id,
                    payload.run_type,
                    payload.entry_source,
                    payload.market_code,
                    payload.locale,
                    payload.city,
                    payload.created_by,
                    json.dumps(payload.metadata, ensure_ascii=False),
                ),
            )
            run = dict(cursor.fetchone() or {})
            for stage_key in PIPELINE_STAGE_KEYS:
                cursor.execute(
                    """
                    INSERT INTO knowledge_pipeline_stages (pipeline_run_id, project_id, stage_key, status, required, blocking)
                    VALUES (%s::uuid, %s::uuid, %s, 'not_started', true, true)
                    ON CONFLICT (pipeline_run_id, stage_key) DO NOTHING
                    """,
                    (run["id"], payload.project_id, stage_key),
                )
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.pipeline_run_created",
                project_id=payload.project_id,
                actor_id=payload.created_by,
                target_type="knowledge_pipeline_run",
                target_id=str(run["id"]),
                before={},
                after=run,
                reason="create knowledge pipeline run",
                method_version="knowledge_pipeline_orchestration_v1",
            )
            self.connection.commit()
            return run

    def start_pipeline_run(self, pipeline_run_id: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_pipeline_runs
                WHERE id = %s::uuid
                FOR UPDATE
                """,
                (pipeline_run_id,),
            )
            current = dict(cursor.fetchone() or {})
            if not current:
                raise ValueError("knowledge pipeline run not found")
            current_status = str(current.get("status") or "")
            if current_status in {"queued", "running"}:
                return current
            if current_status not in {"draft", "ready"}:
                raise ValueError(
                    f"knowledge pipeline run in status {current_status} cannot be started; create a versioned rerun"
                )
            if str(current.get("run_type") or "") == "full_ingestion":
                cursor.execute(
                    """
                    SELECT import_job.*,
                           (SELECT count(*) FROM knowledge_source_assets asset
                            WHERE asset.import_job_id = import_job.id
                              AND asset.status NOT IN ('rejected', 'failed', 'archived')) AS source_asset_count
                    FROM knowledge_import_jobs import_job
                    WHERE import_job.pipeline_run_id = %s::uuid
                    ORDER BY import_job.created_at ASC
                    """,
                    (pipeline_run_id,),
                )
                import_jobs = [dict(row) for row in cursor.fetchall()]
                if not import_jobs:
                    raise ValueError("full ingestion pipeline requires at least one import job")
                for import_job in import_jobs:
                    source_mode = str(import_job.get("source_mode") or "")
                    source_config = dict(import_job.get("source_config") or {})
                    source_asset_count = int(import_job.get("source_asset_count") or 0)
                    has_text = bool(source_config_text(source_config))
                    has_urls = bool(source_config.get("urls") or source_config.get("url") or source_config.get("source_url"))
                    if source_mode == "file" and source_asset_count <= 0:
                        raise ValueError("full ingestion file source has no accepted asset")
                    if source_mode in {"pasted_text", "csv"} and not (has_text or source_asset_count > 0):
                        raise ValueError(f"full ingestion {source_mode} source has no text payload")
                    if source_mode in {"url", "url_batch", "site_crawl"} and not has_urls:
                        raise ValueError("full ingestion URL source has no validated URL")
                cursor.execute(
                    """
                    SELECT count(*) AS blocked_count
                    FROM knowledge_quality_gate_runs
                    WHERE pipeline_run_id = %s::uuid AND gate_key = 'pre_import_gate'
                      AND status IN ('blocked', 'failed')
                    """,
                    (pipeline_run_id,),
                )
                if int((cursor.fetchone() or {}).get("blocked_count") or 0) > 0:
                    raise ValueError("full ingestion pipeline is blocked by source precheck")
            cursor.execute(
                """
                UPDATE knowledge_pipeline_runs
                SET status = 'queued', started_at = COALESCE(started_at, now()), updated_at = now()
                WHERE id = %s::uuid AND status IN ('draft', 'ready')
                RETURNING *
                """,
                (pipeline_run_id,),
            )
            run = dict(cursor.fetchone() or {})
            if not run:
                raise ValueError("knowledge pipeline run changed while it was being started")
            metadata = dict(run.get("metadata") or {})
            source_pipeline_run_id = str(metadata.get("source_pipeline_run_id") or "").strip() or None
            if run["run_type"] != "full_ingestion" and source_pipeline_run_id is None:
                cursor.execute(
                    """
                    SELECT id
                    FROM knowledge_pipeline_runs
                    WHERE project_id = %s::uuid AND id <> %s::uuid
                      AND status IN ('succeeded', 'waiting_human_review', 'running')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (run["project_id"], pipeline_run_id),
                )
                source_row = cursor.fetchone()
                source_pipeline_run_id = str(source_row["id"]) if source_row else None
            if run["run_type"] in {"reparse", "full_rebuild"}:
                if source_pipeline_run_id is None:
                    raise ValueError("reparse requires source_pipeline_run_id or a prior knowledge pipeline")
                cursor.execute(
                    """
                    INSERT INTO knowledge_parser_runs (
                      project_id, pipeline_run_id, import_job_id, source_asset_id,
                      adapter_engine, adapter_version, metadata
                    )
                    SELECT project_id, %s::uuid, import_job_id, id,
                           %s, 'geo-parser-adapter-v1', %s::jsonb
                    FROM knowledge_source_assets
                    WHERE project_id = %s::uuid AND pipeline_run_id = %s::uuid
                      AND asset_type IN ('uploaded_file', 'pasted_text', 'uploaded_csv', 'normalized_csv', 'crawled_html', 'crawled_markdown')
                      AND status NOT IN ('disabled', 'archived', 'rejected', 'failed')
                    """,
                    (
                        pipeline_run_id,
                        str(metadata.get("adapter_engine") or "auto"),
                        json.dumps({"rerun_type": run["run_type"], "source_pipeline_run_id": source_pipeline_run_id}),
                        run["project_id"],
                        source_pipeline_run_id,
                    ),
                )
                if cursor.rowcount <= 0:
                    raise ValueError("reparse source pipeline has no reusable source assets")
            elif run["run_type"] == "rechunk":
                if source_pipeline_run_id is None:
                    raise ValueError("rechunk requires source_pipeline_run_id or a prior knowledge pipeline")
                cursor.execute(
                    """
                    INSERT INTO chunk_jobs (
                      project_id, pipeline_run_id, import_job_id, parser_run_id,
                      chunk_profile_version, cleaner_profile_version, result_summary
                    )
                    SELECT project_id, %s::uuid, import_job_id, id, %s, %s, %s::jsonb
                    FROM knowledge_parser_runs
                    WHERE project_id = %s::uuid AND pipeline_run_id = %s::uuid
                      AND status IN ('succeeded', 'fallback_succeeded', 'partial_succeeded')
                    """,
                    (
                        pipeline_run_id,
                        str(metadata.get("chunk_profile_version") or "geo_chunk_profile_v1"),
                        str(metadata.get("cleaner_profile_version") or "geo_cleaner_v1"),
                        json.dumps({"rerun_type": "rechunk", "source_pipeline_run_id": source_pipeline_run_id}),
                        run["project_id"],
                        source_pipeline_run_id,
                    ),
                )
                if cursor.rowcount <= 0:
                    raise ValueError("rechunk source pipeline has no reusable parser runs")
            elif run["run_type"] == "reindex":
                if source_pipeline_run_id is None:
                    raise ValueError("reindex requires source_pipeline_run_id or a prior knowledge pipeline")
                cursor.execute(
                    """
                    UPDATE knowledge_chunks
                    SET embedding_status = 'stale', updated_at = now()
                    WHERE project_id = %s::uuid AND pipeline_run_id = %s::uuid AND status = 'active'
                    """,
                    (run["project_id"], source_pipeline_run_id),
                )
                cursor.execute(
                    """
                    INSERT INTO embedding_jobs (
                      project_id, pipeline_run_id, chunk_job_id, embedding_model,
                      embedding_model_version, qdrant_collection, result_summary
                    )
                    SELECT DISTINCT project_id, %s::uuid, chunk_job_id, %s, %s, %s, %s::jsonb
                    FROM knowledge_chunks
                    WHERE project_id = %s::uuid AND pipeline_run_id = %s::uuid
                      AND status = 'active' AND chunk_job_id IS NOT NULL
                    """,
                    (
                        pipeline_run_id,
                        str(metadata.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
                        str(metadata.get("embedding_model_version") or DEFAULT_EMBEDDING_MODEL_VERSION),
                        str(metadata.get("qdrant_collection") or DEFAULT_QDRANT_COLLECTION),
                        json.dumps({"rerun_type": "reindex", "source_pipeline_run_id": source_pipeline_run_id}),
                        run["project_id"],
                        source_pipeline_run_id,
                    ),
                )
                if cursor.rowcount <= 0:
                    raise ValueError("reindex source pipeline has no reusable chunks")
            elif run["run_type"] == "fact_refresh":
                if source_pipeline_run_id is None:
                    raise ValueError("fact_refresh requires source_pipeline_run_id or a prior knowledge pipeline")
                cursor.execute(
                    """
                    INSERT INTO fact_extraction_jobs (
                      project_id, pipeline_run_id, import_job_id, fact_kinds, chunk_filter, model,
                      prompt_version, max_facts, metadata
                    ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::text[], %s::jsonb, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        run["project_id"],
                        pipeline_run_id,
                        metadata.get("import_job_id"),
                        list(metadata.get("fact_kinds") or ["brand", "competitor", "market", "source"]),
                        json.dumps(
                            {
                                "source_pipeline_run_id": source_pipeline_run_id,
                                **dict(metadata.get("chunk_filter") or {}),
                            },
                            ensure_ascii=False,
                        ),
                        str(metadata.get("model") or "deepseek-v4-flash"),
                        str(metadata.get("prompt_version") or "knowledge_fact_extraction_v1"),
                        int(metadata.get("max_facts") or 20),
                        json.dumps({"rerun_type": "fact_refresh", "source_pipeline_run_id": source_pipeline_run_id}),
                    ),
                )
            elif run["run_type"] == "prompt_generation":
                self.enqueue_generation_for_approved_facts(
                    cursor=cursor,
                    project_id=str(run["project_id"]),
                    pipeline_run_id=pipeline_run_id,
                )
                cursor.execute("DELETE FROM content_generation_jobs WHERE pipeline_run_id = %s::uuid", (pipeline_run_id,))
            elif run["run_type"] == "content_generation":
                self.enqueue_generation_for_approved_facts(
                    cursor=cursor,
                    project_id=str(run["project_id"]),
                    pipeline_run_id=pipeline_run_id,
                )
                cursor.execute("DELETE FROM prompt_generation_jobs WHERE pipeline_run_id = %s::uuid", (pipeline_run_id,))
            cursor.execute(
                """
                UPDATE knowledge_pipeline_stages
                SET status = CASE WHEN stage_key = 'source_precheck' THEN 'queued' ELSE status END,
                    updated_at = now()
                WHERE pipeline_run_id = %s::uuid
                """,
                (pipeline_run_id,),
            )
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.pipeline_run_queued",
                project_id=str(run["project_id"]),
                actor_id=str(run.get("created_by") or "runtime-console"),
                target_type="knowledge_pipeline_run",
                target_id=pipeline_run_id,
                before={"status": "ready"},
                after={"status": "queued", "run_type": run["run_type"]},
                reason="start knowledge pipeline run",
                method_version="knowledge_pipeline_orchestration_v1",
            )
            self.connection.commit()
            return run

    def set_runtime_scope(self, *, actor_id: str, project_id: str | None = None, roles: str = "owner,admin,analyst") -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.rls_enabled', 'true', false)")
            cursor.execute("SELECT set_config('geno.runtime_project_access_control', 'true', false)")
            cursor.execute("SELECT set_config('app.actor_id', %s, false)", (actor_id,))
            cursor.execute("SELECT set_config('geno.runtime_actor_id', %s, false)", (actor_id,))
            cursor.execute("SELECT set_config('app.roles', %s, false)", (roles,))
            if project_id:
                cursor.execute("SELECT set_config('app.project_id', %s, false)", (project_id,))
                cursor.execute("SELECT set_config('geno.runtime_project_id', %s, false)", (project_id,))
            else:
                cursor.execute("SELECT set_config('app.project_id', '', false)")
                cursor.execute("SELECT set_config('geno.runtime_project_id', '', false)")
            self.connection.commit()

    def set_maintenance_scope(self, *, worker_id: str) -> None:
        """Run worker-owned orchestration with project checks disabled for this DB session."""
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.rls_enabled', 'false', false)")
            cursor.execute("SELECT set_config('geno.runtime_project_access_control', 'false', false)")
            cursor.execute("SELECT set_config('app.actor_id', %s, false)", (worker_id,))
            cursor.execute("SELECT set_config('geno.runtime_actor_id', %s, false)", (worker_id,))
            cursor.execute("SELECT set_config('app.project_id', '', false)")
            cursor.execute("SELECT set_config('geno.runtime_project_id', '', false)")
            cursor.execute("SELECT set_config('app.project_ids', '', false)")
            cursor.execute("SELECT set_config('app.roles', 'system,worker', false)")
            self.connection.commit()

    def list_pipeline_runs(
        self,
        *,
        project_id: str,
        limit: int,
        offset: int,
        filters: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        allowed_filters = {"run_type", "status", "entry_source"}
        clauses = ["project_id = %s::uuid"]
        params: list[Any] = [project_id]
        for key, value in (filters or {}).items():
            if value is None or not str(value).strip():
                continue
            if key not in allowed_filters:
                raise ValueError(f"unsupported knowledge pipeline filter: {key}")
            clauses.append(f"{key} = %s")
            params.append(str(value).strip())
        where_sql = " AND ".join(clauses)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT count(*) AS total_count FROM knowledge_pipeline_runs WHERE {where_sql}",
                tuple(params),
            )
            total = int((cursor.fetchone() or {}).get("total_count") or 0)
            cursor.execute(
                f"""
                SELECT * FROM knowledge_pipeline_runs
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            return {"total_count": total, "limit": limit, "offset": offset, "records": tuple(dict(row) for row in cursor.fetchall())}

    def get_pipeline_run(self, pipeline_run_id: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM knowledge_pipeline_runs WHERE id = %s::uuid", (pipeline_run_id,))
            run = dict(cursor.fetchone() or {})
            if not run:
                raise ValueError("knowledge pipeline run not found")
            return run

    def get_pipeline_run_detail(self, *, project_id: str, pipeline_run_id: str) -> dict[str, Any]:
        run = self.get_pipeline_run(pipeline_run_id)
        if str(run.get("project_id")) != project_id:
            raise ValueError("knowledge pipeline run not found")
        stages = self.list_pipeline_stages(pipeline_run_id)
        jobs = self.list_pipeline_jobs(
            pipeline_run_id=pipeline_run_id,
            project_id=project_id,
            limit=200,
            offset=0,
        )
        pipeline_filter = {"pipeline_run_id": pipeline_run_id}
        assets = self._list_table(
            "knowledge_source_assets", project_id=project_id, limit=200, offset=0, filters=pipeline_filter
        )
        parser_runs = self._list_table(
            "knowledge_parser_runs", project_id=project_id, limit=200, offset=0, filters=pipeline_filter
        )
        chunks = self.list_chunks(project_id=project_id, limit=100, offset=0, filters=pipeline_filter)
        gates = self.list_quality_gate_runs(
            project_id=project_id, limit=200, offset=0, filters=pipeline_filter
        )
        fact_candidates = self.list_fact_candidates(
            project_id=project_id, limit=100, offset=0, filters=pipeline_filter
        )
        prompt_candidates = self.list_prompt_candidates(
            project_id=project_id, limit=100, offset=0, filters=pipeline_filter
        )
        content_drafts = self.list_content_drafts(
            project_id=project_id, limit=100, offset=0, filters=pipeline_filter
        )
        target_ids = {pipeline_run_id}
        for page in (assets, parser_runs, chunks, gates, fact_candidates, prompt_candidates, content_drafts):
            target_ids.update(str(record.get("id")) for record in page["records"] if record.get("id"))
        for group in (jobs.get("job_groups") or {}).values():
            target_ids.update(str(record.get("id")) for record in group.get("records") or () if record.get("id"))
        return {
            "knowledge_pipeline_run": run,
            "stages": stages,
            "jobs": jobs,
            "source_assets": assets,
            "parser_runs": parser_runs,
            "chunks": chunks,
            "quality_gate_runs": gates,
            "fact_candidates": fact_candidates,
            "prompt_candidates": prompt_candidates,
            "content_drafts": content_drafts,
            "summaries": {
                "chunks": self._status_summary("knowledge_chunks", project_id=project_id, filters=pipeline_filter, status_column="status"),
                "facts": self._status_summary("knowledge_fact_candidates", project_id=project_id, filters=pipeline_filter, status_column="status"),
                "prompts": self._status_summary("prompt_candidates", project_id=project_id, filters=pipeline_filter, status_column="review_status"),
                "content": self._status_summary("content_drafts", project_id=project_id, filters=pipeline_filter, status_column="status"),
            },
            "audit_events": self._list_audit_events(project_id=project_id, target_ids=target_ids),
        }

    def list_pipeline_stages(self, pipeline_run_id: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT stage.*,
                       COALESCE((
                         SELECT jsonb_agg(
                           jsonb_build_object(
                             'id', gate_run.id,
                             'gate_key', gate_run.gate_key,
                             'status', gate_run.status,
                             'blocking', gate_run.blocking,
                             'finding_count', cardinality(gate_run.finding_ids),
                             'summary', gate_run.summary
                           ) ORDER BY gate_run.created_at ASC
                         )
                         FROM knowledge_quality_gate_runs gate_run
                         LEFT JOIN knowledge_quality_gates gate ON gate.id = gate_run.gate_id
                         WHERE gate_run.pipeline_run_id = stage.pipeline_run_id
                           AND (gate_run.pipeline_stage_id = stage.id OR gate.target_stage_key = stage.stage_key)
                       ), '[]'::jsonb) AS quality_gate_runs
                FROM knowledge_pipeline_stages stage
                WHERE stage.pipeline_run_id = %s::uuid
                ORDER BY stage.created_at ASC
                """,
                (pipeline_run_id,),
            )
            records = tuple(dict(row) for row in cursor.fetchall())
            return {"total_count": len(records), "records": records}

    def list_pipeline_jobs(
        self,
        *,
        pipeline_run_id: str,
        project_id: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        groups: dict[str, dict[str, Any]] = {}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            for table in JOB_TABLES:
                cursor.execute(
                    f"SELECT count(*) AS total_count FROM {table} "
                    "WHERE project_id = %s::uuid AND pipeline_run_id = %s::uuid",
                    (project_id, pipeline_run_id),
                )
                total_count = int((cursor.fetchone() or {}).get("total_count") or 0)
                cursor.execute(
                    f"SELECT * FROM {table} "
                    "WHERE project_id = %s::uuid AND pipeline_run_id = %s::uuid "
                    "ORDER BY created_at ASC LIMIT %s OFFSET %s",
                    (project_id, pipeline_run_id, limit, offset),
                )
                groups[table] = {
                    "total_count": total_count,
                    "limit": limit,
                    "offset": offset,
                    "records": tuple(_public_job_record(dict(row)) for row in cursor.fetchall()),
                }
        return {"pipeline_run_id": pipeline_run_id, "job_groups": groups}

    def create_import_job(self, payload: KnowledgeImportCreateInput) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_import_jobs (
                  project_id, pipeline_run_id, source_mode, status, requested_by, source_config, priority,
                  parser_strategy, crawler_strategy, market_code, locale, city, created_by
                ) VALUES (%s::uuid, %s::uuid, %s, 'ready', %s, %s::jsonb, %s,
                          %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    payload.project_id,
                    payload.pipeline_run_id,
                    payload.source_mode,
                    payload.requested_by,
                    json.dumps(payload.source_config, ensure_ascii=False),
                    payload.priority,
                    str(payload.source_config.get("adapter_engine") or "auto"),
                    "crawl4ai" if payload.source_mode in {"url", "url_batch", "site_crawl"} else "none",
                    str(payload.source_config.get("market_code") or "GLOBAL"),
                    str(payload.source_config.get("locale") or "en"),
                    str(payload.source_config.get("city") or "") or None,
                    payload.requested_by,
                ),
            )
            job = dict(cursor.fetchone() or {})
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.import_job_created",
                project_id=payload.project_id,
                actor_id=payload.requested_by,
                target_type="knowledge_import_job",
                target_id=str(job["id"]),
                before={},
                after=job,
                reason="create knowledge import job",
                method_version="knowledge_import_job_v1",
            )
            self.connection.commit()
            return job

    def enqueue_import_job(self, import_job_id: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_import_jobs
                WHERE id = %s::uuid
                FOR UPDATE
                """,
                (import_job_id,),
            )
            current = dict(cursor.fetchone() or {})
            if not current:
                raise ValueError("knowledge import job not found")
            current_status = str(current.get("status") or "")
            if current_status in {"queued", "running"}:
                return current
            if current_status not in {"draft", "ready"}:
                raise ValueError(
                    f"knowledge import job in status {current_status} cannot be enqueued; retry its failed stage instead"
                )
            source_mode = str(current.get("source_mode") or "")
            source_config = dict(current.get("source_config") or {})
            cursor.execute(
                "SELECT count(*) AS source_count FROM knowledge_source_assets WHERE import_job_id = %s::uuid AND status NOT IN ('rejected', 'failed', 'archived')",
                (import_job_id,),
            )
            asset_count = int((cursor.fetchone() or {}).get("source_count") or 0)
            has_url_source = bool(source_config.get("urls"))
            has_text_source = bool(source_config_text(source_config))
            if source_mode == "file" and asset_count <= 0:
                raise ValueError("knowledge import job requires at least one accepted source asset")
            if source_mode == "csv" and not (has_text_source or asset_count > 0):
                raise ValueError("knowledge import job requires CSV text or a source asset")
            if source_mode in {"url", "url_batch", "site_crawl"} and not has_url_source:
                raise ValueError("knowledge import job requires at least one validated URL source")
            if source_mode == "pasted_text" and not (has_text_source or asset_count > 0):
                raise ValueError("knowledge import job requires pasted text or a source asset")
            cursor.execute(
                """
                UPDATE knowledge_import_jobs
                SET status = 'queued', next_run_at = now(), updated_at = now()
                WHERE id = %s::uuid AND status IN ('draft', 'ready')
                RETURNING *
                """,
                (import_job_id,),
            )
            job = dict(cursor.fetchone() or {})
            if not job:
                raise ValueError("knowledge import job changed while it was being enqueued")
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.import_job_queued",
                project_id=str(job["project_id"]),
                actor_id=str(job.get("requested_by") or "runtime-console"),
                target_type="knowledge_import_job",
                target_id=import_job_id,
                before={"status": "ready"},
                after=job,
                reason="enqueue knowledge import job",
                method_version="knowledge_import_job_v1",
            )
            stage_key = "crawl" if source_mode in {"url", "url_batch", "site_crawl"} else "asset_ingestion"
            cursor.execute(
                """
                UPDATE knowledge_pipeline_stages
                SET status = 'queued', updated_at = now()
                WHERE pipeline_run_id = %s::uuid AND project_id = %s::uuid
                  AND stage_key = %s AND status IN ('not_started', 'failed', 'blocked', 'retrying')
                """,
                (job.get("pipeline_run_id"), job["project_id"], stage_key),
            )
            self.connection.commit()
            return job

    def record_import_precheck(
        self,
        *,
        project_id: str,
        pipeline_run_id: str,
        import_job_id: str,
        checked_by: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        findings = [dict(item) for item in result.get("findings") or [] if isinstance(item, dict)]
        source_rejected = not bool(result.get("accepted"))
        blocked = source_rejected and not bool(result.get("allow_partial"))
        gate_status = "blocked" if blocked else ("warning" if findings else "passed")
        finding_ids: list[str] = []
        with self.connection.cursor() as cursor:
            for finding in findings:
                finding_id = stable_pipeline_id(
                    "quality-finding",
                    pipeline_run_id,
                    import_job_id,
                    finding.get("code"),
                    result.get("content_hash"),
                )
                cursor.execute(
                    """
                    INSERT INTO knowledge_quality_findings (
                      id, project_id, pipeline_run_id, target_type, target_id, finding_type,
                      severity, status, message, evidence_refs, metadata
                    ) VALUES (%s::uuid, %s::uuid, %s::uuid, 'import_job', %s, %s,
                              %s, 'open', %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                      severity = EXCLUDED.severity, message = EXCLUDED.message,
                      metadata = EXCLUDED.metadata, updated_at = now()
                    """,
                    (
                        finding_id,
                        project_id,
                        pipeline_run_id,
                        import_job_id,
                        str(finding.get("code") or "precheck_finding"),
                        "high" if finding.get("severity") == "blocked" else str(finding.get("severity") or "warning"),
                        str(finding.get("message") or finding.get("code") or "Knowledge source precheck finding"),
                        json.dumps({"content_hash": result.get("content_hash"), "filename": result.get("filename")}),
                        json.dumps(finding, ensure_ascii=False),
                    ),
                )
                finding_ids.append(finding_id)
            cursor.execute("SELECT id FROM knowledge_quality_gates WHERE gate_key = 'pre_import_gate' AND status = 'active'")
            gate_row = cursor.fetchone()
            gate_id = gate_row[0] if gate_row else None
            gate_run_id = stable_pipeline_id("quality-gate-run", pipeline_run_id, "pre_import_gate", import_job_id)
            cursor.execute(
                """
                INSERT INTO knowledge_quality_gate_runs (
                  id, project_id, pipeline_run_id, gate_id, gate_key, status, blocking,
                  summary, finding_ids, metadata, started_at, completed_at
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'pre_import_gate', %s, true,
                          %s::jsonb, %s::uuid[], %s::jsonb, now(), now())
                ON CONFLICT (id) DO UPDATE SET
                  status = CASE
                    WHEN knowledge_quality_gate_runs.status IN ('blocked', 'failed') THEN knowledge_quality_gate_runs.status
                    WHEN EXCLUDED.status IN ('blocked', 'failed') THEN EXCLUDED.status
                    WHEN knowledge_quality_gate_runs.status = 'warning' OR EXCLUDED.status = 'warning' THEN 'warning'
                    ELSE 'passed'
                  END,
                  summary = knowledge_quality_gate_runs.summary || EXCLUDED.summary,
                  finding_ids = ARRAY(
                    SELECT DISTINCT finding_id
                    FROM unnest(knowledge_quality_gate_runs.finding_ids || EXCLUDED.finding_ids) finding_id
                  ),
                  metadata = knowledge_quality_gate_runs.metadata || EXCLUDED.metadata,
                  completed_at = now(), updated_at = now()
                """,
                (
                    gate_run_id,
                    project_id,
                    pipeline_run_id,
                    gate_id,
                    gate_status,
                    json.dumps(result, ensure_ascii=False),
                    finding_ids,
                    json.dumps({"checked_by": checked_by}, ensure_ascii=False),
                ),
            )
            cursor.execute(
                """
                UPDATE knowledge_import_jobs
                SET status = CASE WHEN %s THEN 'failed' ELSE status END,
                    result_summary = result_summary || %s::jsonb,
                    last_error_code = CASE WHEN %s THEN 'pre_import_gate_blocked' ELSE null END,
                    last_error_message = CASE WHEN %s THEN 'Knowledge source precheck blocked the import' ELSE null END,
                    updated_at = now()
                WHERE id = %s::uuid AND project_id = %s::uuid
                """,
                (blocked, json.dumps({"precheck": result}, ensure_ascii=False), blocked, blocked, import_job_id, project_id),
            )
            cursor.execute(
                """
                UPDATE knowledge_pipeline_stages
                SET status = %s, started_at = COALESCE(started_at, now()), completed_at = now(),
                    summary = summary || %s::jsonb, updated_at = now()
                WHERE pipeline_run_id = %s::uuid AND stage_key = 'source_precheck'
                """,
                ("blocked" if blocked else "succeeded", json.dumps(result, ensure_ascii=False), pipeline_run_id),
            )
            if blocked:
                cursor.execute(
                    """
                    UPDATE knowledge_pipeline_runs
                    SET status = 'failed', failed_step = 'source_precheck',
                        blocking_quality_gate = 'pre_import_gate', completed_at = now(), updated_at = now()
                    WHERE id = %s::uuid
                    """,
                    (pipeline_run_id,),
                )
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.source_prechecked",
                project_id=project_id,
                actor_id=checked_by,
                target_type="knowledge_import_job",
                target_id=import_job_id,
                before={},
                after={"status": gate_status, "precheck": result},
                reason="precheck knowledge source before object storage upload",
                method_version="knowledge_source_precheck_v1",
            )
            self.connection.commit()
        return {"gate_status": gate_status, "gate_run_id": gate_run_id, "finding_ids": finding_ids}

    def configure_import_urls(
        self,
        *,
        project_id: str,
        import_job_id: str,
        actor_id: str,
        source_mode: str,
        source_config: dict[str, Any],
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_import_jobs
                WHERE id = %s::uuid AND project_id = %s::uuid
                FOR UPDATE
                """,
                (import_job_id, project_id),
            )
            before = dict(cursor.fetchone() or {})
            if not before:
                raise ValueError("knowledge import job not found")
            if str(before.get("status") or "") not in {"draft", "ready"}:
                raise ValueError("knowledge import URLs can only be changed before the job is queued")
            cursor.execute(
                """
                UPDATE knowledge_import_jobs
                SET source_mode = %s,
                    source_config = source_config || %s::jsonb,
                    crawler_strategy = 'crawl4ai',
                    market_code = %s,
                    locale = %s,
                    city = %s,
                    status = 'ready', updated_at = now()
                WHERE id = %s::uuid AND project_id = %s::uuid
                RETURNING *
                """,
                (
                    source_mode,
                    json.dumps(source_config, ensure_ascii=False),
                    str(source_config.get("market_code") or before.get("market_code") or "GLOBAL"),
                    str(source_config.get("locale") or before.get("locale") or "en"),
                    str(source_config.get("city") or before.get("city") or "") or None,
                    import_job_id,
                    project_id,
                ),
            )
            job = dict(cursor.fetchone() or {})
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.import_urls_configured",
                project_id=project_id,
                actor_id=actor_id,
                target_type="knowledge_import_job",
                target_id=import_job_id,
                before={"source_mode": before.get("source_mode"), "source_config": before.get("source_config")},
                after={"source_mode": source_mode, "source_config": source_config},
                reason="configure normalized knowledge URL seeds",
                method_version="knowledge_import_urls_v1",
            )
            self.connection.commit()
            return job

    def list_import_jobs(self, *, project_id: str, limit: int, offset: int, filters: dict[str, str | None] | None = None) -> dict[str, Any]:
        return self._list_table("knowledge_import_jobs", project_id=project_id, limit=limit, offset=offset, filters=filters)

    def get_import_job(self, *, project_id: str, import_job_id: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_import_jobs
                WHERE id = %s::uuid AND project_id = %s::uuid
                LIMIT 1
                """,
                (import_job_id, project_id),
            )
            job = dict(cursor.fetchone() or {})
        if not job:
            raise ValueError("knowledge import job not found")
        return _public_job_record(job)

    def get_import_job_detail(self, *, project_id: str, import_job_id: str) -> dict[str, Any]:
        job = self.get_import_job(project_id=project_id, import_job_id=import_job_id)
        import_filter = {"import_job_id": import_job_id}
        assets = self._list_table(
            "knowledge_source_assets", project_id=project_id, limit=200, offset=0, filters=import_filter
        )
        parser_runs = self._list_table(
            "knowledge_parser_runs", project_id=project_id, limit=200, offset=0, filters=import_filter
        )
        chunks = self.list_chunks(project_id=project_id, limit=100, offset=0, filters=import_filter)
        fact_candidates = self.list_fact_candidates(
            project_id=project_id,
            limit=100,
            offset=0,
            filters={"pipeline_run_id": str(job.get("pipeline_run_id") or "")},
        )
        target_ids = {import_job_id}
        for page in (assets, parser_runs, chunks, fact_candidates):
            target_ids.update(str(record.get("id")) for record in page["records"] if record.get("id"))
        findings = self._list_findings_for_targets(
            project_id=project_id,
            pipeline_run_id=str(job.get("pipeline_run_id") or "") or None,
            target_ids=target_ids,
            limit=200,
        )
        return {
            "knowledge_import_job": job,
            "source_assets": assets,
            "parser_runs": parser_runs,
            "chunks": chunks,
            "quality_findings": findings,
            "fact_candidates": fact_candidates,
            "summaries": {
                "chunks": self._status_summary("knowledge_chunks", project_id=project_id, filters=import_filter, status_column="status"),
                "facts": self._status_summary(
                    "knowledge_fact_candidates",
                    project_id=project_id,
                    filters={"pipeline_run_id": str(job.get("pipeline_run_id") or "")},
                    status_column="status",
                ),
            },
            "audit_events": self._list_audit_events(project_id=project_id, target_ids=target_ids),
        }

    def list_source_assets(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("knowledge_source_assets", project_id=project_id, limit=limit, offset=offset)

    def list_approved_facts(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT count(*) AS total_count FROM localized_knowledge_facts WHERE project_id = %s::uuid AND status = 'active'",
                (project_id,),
            )
            total = int((cursor.fetchone() or {}).get("total_count") or 0)
            cursor.execute(
                """
                SELECT * FROM localized_knowledge_facts
                WHERE project_id = %s::uuid AND status = 'active'
                ORDER BY valid_from DESC, id ASC
                LIMIT %s OFFSET %s
                """,
                (project_id, limit, offset),
            )
            return {
                "total_count": total,
                "limit": limit,
                "offset": offset,
                "records": tuple(dict(row) for row in cursor.fetchall()),
            }

    def list_fact_extraction_jobs(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("fact_extraction_jobs", project_id=project_id, limit=limit, offset=offset)

    def list_prompt_generation_jobs(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("prompt_generation_jobs", project_id=project_id, limit=limit, offset=offset)

    def list_content_generation_jobs(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("content_generation_jobs", project_id=project_id, limit=limit, offset=offset)

    def list_prompt_generation_templates(self, *, limit: int, offset: int) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT count(*) AS total_count FROM prompt_generation_templates")
            total = int((cursor.fetchone() or {}).get("total_count") or 0)
            cursor.execute(
                """
                SELECT * FROM prompt_generation_templates
                ORDER BY status ASC, template_key ASC, template_version DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return {
                "total_count": total,
                "limit": limit,
                "offset": offset,
                "records": tuple(dict(row) for row in cursor.fetchall()),
            }

    def get_published_prompt_generation_template(self, *, template_key: str, template_version: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM prompt_generation_templates
                WHERE template_key = %s AND template_version = %s AND status = 'published'
                LIMIT 1
                """,
                (template_key.strip(), template_version.strip()),
            )
            template = dict(cursor.fetchone() or {})
        if not template:
            raise ValueError("published Prompt generation template version not found")
        return template

    def create_prompt_generation_template(
        self,
        *,
        project_id: str,
        template_key: str,
        template_version: str,
        name: str,
        template_body: str,
        status: str,
        description: str,
        system_prompt: str | None,
        user_prompt_template: str | None,
        input_variables: list[str],
        output_schema: dict[str, Any],
        model_config: dict[str, Any],
        evaluation_set: list[dict[str, Any]],
        created_by: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        normalized_key = template_key.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,159}", normalized_key):
            raise ValueError("template_key must use lowercase letters, digits, and underscores")
        if not template_version.strip() or not name.strip() or not template_body.strip():
            raise ValueError("template_version, name, and template_body are required")
        normalized_status = status.strip().lower()
        if normalized_status not in {"draft", "published", "archived"}:
            raise ValueError("template status must be draft, published, or archived")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM prompt_generation_templates
                WHERE template_key = %s AND template_version = %s
                FOR UPDATE
                """,
                (normalized_key, template_version.strip()),
            )
            before = dict(cursor.fetchone() or {})
            if before and str(before.get("status")) == "published":
                requested_contract = {
                    "name": name.strip(),
                    "template_body": template_body.strip(),
                    "description": description.strip(),
                    "system_prompt": (system_prompt or template_body).strip(),
                    "user_prompt_template": (user_prompt_template or template_body).strip(),
                    "input_variables": [value.strip() for value in input_variables if value.strip()],
                    "output_schema": output_schema or {"prompt_candidates": [{"text": "string"}]},
                    "model_config": model_config or {"model": "deepseek-v4-flash"},
                    "evaluation_set": evaluation_set,
                }
                existing_contract = {key: before.get(key) for key in requested_contract}
                if payload_hash(existing_contract) != payload_hash(requested_contract):
                    raise ValueError("published Prompt template versions are immutable; create a new template version")
            cursor.execute(
                """
                INSERT INTO prompt_generation_templates (
                  template_key, template_version, name, template_body, status, description,
                  system_prompt, user_prompt_template, input_variables, output_schema,
                  model_config, evaluation_set, metadata, created_by, approved_by, published_at
                ) VALUES (%s, %s, %s, %s, %s, %s,
                          %s, %s, %s::jsonb, %s::jsonb,
                          %s::jsonb, %s::jsonb, %s::jsonb, %s,
                          CASE WHEN %s = 'published' THEN %s ELSE null END,
                          CASE WHEN %s = 'published' THEN now() ELSE null END)
                ON CONFLICT (template_key, template_version) DO UPDATE SET
                  name = EXCLUDED.name,
                  template_body = EXCLUDED.template_body,
                  status = EXCLUDED.status,
                  description = EXCLUDED.description,
                  system_prompt = EXCLUDED.system_prompt,
                  user_prompt_template = EXCLUDED.user_prompt_template,
                  input_variables = EXCLUDED.input_variables,
                  output_schema = EXCLUDED.output_schema,
                  model_config = EXCLUDED.model_config,
                  evaluation_set = EXCLUDED.evaluation_set,
                  approved_by = CASE WHEN EXCLUDED.status = 'published' THEN EXCLUDED.created_by ELSE null END,
                  published_at = CASE WHEN EXCLUDED.status = 'published' THEN COALESCE(prompt_generation_templates.published_at, now()) ELSE null END,
                  metadata = prompt_generation_templates.metadata || EXCLUDED.metadata,
                  updated_at = now()
                RETURNING *
                """,
                (
                    normalized_key,
                    template_version.strip(),
                    name.strip(),
                    template_body.strip(),
                    normalized_status,
                    description.strip(),
                    (system_prompt or template_body).strip(),
                    (user_prompt_template or template_body).strip(),
                    json.dumps([value.strip() for value in input_variables if value.strip()], ensure_ascii=False),
                    json.dumps(output_schema or {"prompt_candidates": [{"text": "string"}]}, ensure_ascii=False),
                    json.dumps(model_config or {"model": "deepseek-v4-flash"}, ensure_ascii=False),
                    json.dumps(evaluation_set, ensure_ascii=False),
                    json.dumps({"scope": "global", "source_project_id": project_id, **(metadata or {})}, ensure_ascii=False),
                    created_by,
                    normalized_status,
                    created_by,
                    normalized_status,
                ),
            )
            template = dict(cursor.fetchone() or {})
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.prompt_template_saved",
                project_id=project_id,
                actor_id=created_by,
                target_type="prompt_generation_template",
                target_id=str(template["id"]),
                before=before,
                after=template,
                reason="save global Prompt generation template version",
                method_version="knowledge_prompt_template_v1",
            )
            self.connection.commit()
        return template

    def list_quality_findings(self, *, project_id: str, limit: int, offset: int, filters: dict[str, str | None] | None = None) -> dict[str, Any]:
        return self._list_table("knowledge_quality_findings", project_id=project_id, limit=limit, offset=offset, filters=filters)

    def list_quality_gate_runs(self, *, project_id: str, limit: int, offset: int, filters: dict[str, str | None] | None = None) -> dict[str, Any]:
        return self._list_table("knowledge_quality_gate_runs", project_id=project_id, limit=limit, offset=offset, filters=filters)

    def list_trace_refs(self, *, project_id: str, limit: int, offset: int, filters: dict[str, str | None] | None = None) -> dict[str, Any]:
        return self._list_table("knowledge_trace_refs", project_id=project_id, limit=limit, offset=offset, filters=filters)

    def list_chunks(self, *, project_id: str, limit: int, offset: int, filters: dict[str, str | None] | None = None, quality_flag: str | None = None, query: str | None = None) -> dict[str, Any]:
        return self._list_table(
            "knowledge_chunks", project_id=project_id, limit=limit, offset=offset,
            filters=filters, quality_flag=quality_flag, query=query, enrich_chunks=True,
        )

    def list_parser_runs(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("knowledge_parser_runs", project_id=project_id, limit=limit, offset=offset)

    def list_blocks(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("knowledge_blocks", project_id=project_id, limit=limit, offset=offset)

    def list_tables(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("knowledge_tables", project_id=project_id, limit=limit, offset=offset)

    def list_ocr_spans(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("knowledge_ocr_spans", project_id=project_id, limit=limit, offset=offset)

    def list_page_snapshots(self, *, project_id: str, limit: int, offset: int) -> dict[str, Any]:
        return self._list_table("knowledge_page_snapshots", project_id=project_id, limit=limit, offset=offset)

    def get_source_asset(self, *, project_id: str, source_asset_id: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM knowledge_source_assets
                WHERE id = %s::uuid AND project_id = %s::uuid
                LIMIT 1
                """,
                (source_asset_id, project_id),
            )
            asset = dict(cursor.fetchone() or {})
        if not asset:
            raise ValueError("knowledge source asset not found")
        return asset

    def get_chunks_by_ids(self, *, project_id: str, chunk_ids: list[str]) -> list[dict[str, Any]]:
        from psycopg.rows import dict_row

        normalized_ids = list(dict.fromkeys(value.strip() for value in chunk_ids if value.strip()))
        if not normalized_ids:
            return []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_chunks
                WHERE project_id = %s::uuid
                  AND id = ANY(%s::uuid[])
                  AND status = 'active'
                  AND embedding_status = 'embedded'
                """,
                (project_id, normalized_ids),
            )
            rows = {str(row["id"]): dict(row) for row in cursor.fetchall()}
        return [rows[chunk_id] for chunk_id in normalized_ids if chunk_id in rows]

    def list_fact_candidates(self, *, project_id: str, limit: int, offset: int, filters: dict[str, str | None] | None = None) -> dict[str, Any]:
        return self._list_table("knowledge_fact_candidates", project_id=project_id, limit=limit, offset=offset, filters=filters)

    def list_prompt_candidates(self, *, project_id: str, limit: int, offset: int, filters: dict[str, str | None] | None = None) -> dict[str, Any]:
        return self._list_table("prompt_candidates", project_id=project_id, limit=limit, offset=offset, filters=filters)

    def list_content_drafts(self, *, project_id: str, limit: int, offset: int, filters: dict[str, str | None] | None = None) -> dict[str, Any]:
        return self._list_table("content_drafts", project_id=project_id, limit=limit, offset=offset, filters=filters)

    def accept_quality_gate_risk(
        self,
        *,
        project_id: str,
        gate_run_id: str,
        accepted_by: str,
        reason: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("accepted risk reason is required")
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("accepted risk expiry must include a timezone")
        if expires_at <= _now():
            raise ValueError("accepted risk expiry must be in the future")
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_quality_gate_runs
                WHERE id = %s::uuid AND project_id = %s::uuid
                FOR UPDATE
                """,
                (gate_run_id, project_id),
            )
            before = dict(cursor.fetchone() or {})
            if not before:
                raise ValueError("knowledge quality gate run not found")
            if str(before.get("gate_key")) in {"traceability_gate", "security_gate"}:
                raise ValueError("traceability and security gate risks cannot be accepted")
            if str(before.get("status")) not in {"warning", "blocked"}:
                raise ValueError("only warning or blocked quality gate risks can be accepted")
            finding_ids = [str(value) for value in (before.get("finding_ids") or [])]
            cursor.execute(
                """
                UPDATE knowledge_quality_gate_runs
                SET status = 'accepted_risk', accepted_by = %s, accepted_at = now(),
                    accepted_reason = %s, accepted_expires_at = %s,
                    affected_gate_run_ids = ARRAY[%s::uuid],
                    affected_finding_ids = %s::uuid[],
                    metadata = metadata || %s::jsonb,
                    updated_at = now()
                WHERE id = %s::uuid
                RETURNING *
                """,
                (
                    accepted_by,
                    reason.strip(),
                    expires_at,
                    gate_run_id,
                    finding_ids,
                    json.dumps({"accepted_from_status": before.get("status")}, ensure_ascii=False),
                    gate_run_id,
                ),
            )
            accepted = dict(cursor.fetchone() or {})
            if finding_ids:
                cursor.execute(
                    """
                    UPDATE knowledge_quality_findings
                    SET status = 'accepted_risk',
                        metadata = metadata || %s::jsonb,
                        updated_at = now()
                    WHERE id = ANY(%s::uuid[])
                    """,
                    (
                        json.dumps(
                            {"accepted_by": accepted_by, "accepted_reason": reason.strip(), "accepted_expires_at": expires_at.isoformat()},
                            ensure_ascii=False,
                        ),
                        finding_ids,
                    ),
                )
            before_hash = payload_hash(before)
            after_hash = payload_hash(accepted)
            audit_id = stable_pipeline_id("quality-risk-accepted", gate_run_id, accepted_by, expires_at.isoformat())
            cursor.execute(
                """
                INSERT INTO audit_events (
                  id, event_type, project_id, actor_type, actor_id, target_type, target_id,
                  before_hash, after_hash, input_refs, output_refs, method_version, reason
                ) VALUES (%s::uuid, 'knowledge.quality_risk_accepted', %s::uuid, 'user', %s,
                          'knowledge_quality_gate_run', %s, %s, %s, %s::jsonb, %s::jsonb,
                          'knowledge_quality_risk_acceptance_v1', %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    audit_id,
                    project_id,
                    accepted_by,
                    gate_run_id,
                    before_hash,
                    after_hash,
                    json.dumps({"gate_run_ids": [gate_run_id], "finding_ids": finding_ids}),
                    json.dumps({"status": "accepted_risk", "expires_at": expires_at.isoformat()}),
                    reason.strip(),
                ),
            )
            self.connection.commit()
        pipeline_states = self.refresh_project_pipeline_states(project_id=project_id)
        return {"quality_gate_run": accepted, "pipeline_states": pipeline_states}

    def _list_table(
        self,
        table: str,
        *,
        project_id: str,
        limit: int,
        offset: int,
        filters: dict[str, str | None] | None = None,
        quality_flag: str | None = None,
        query: str | None = None,
        enrich_chunks: bool = False,
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        if table not in {
            "knowledge_import_jobs",
            "knowledge_source_assets",
            "knowledge_parser_runs",
            "knowledge_blocks",
            "knowledge_tables",
            "knowledge_ocr_spans",
            "knowledge_page_snapshots",
            "knowledge_quality_findings",
            "knowledge_quality_gate_runs",
            "knowledge_trace_refs",
            "knowledge_chunks",
            "knowledge_fact_candidates",
            "localized_knowledge_facts",
            "fact_extraction_jobs",
            "prompt_generation_jobs",
            "content_generation_jobs",
            "prompt_candidates",
            "content_drafts",
        }:
            raise ValueError("unsupported knowledge table")
        allowed_filters = KNOWLEDGE_TABLE_FILTERS.get(table, {})
        clauses = ["t.project_id = %s::uuid"]
        params: list[Any] = [project_id]
        for key, value in (filters or {}).items():
            if value is None or not str(value).strip():
                continue
            column = allowed_filters.get(key)
            if column is None:
                raise ValueError(f"unsupported {table} filter: {key}")
            placeholder = "%s::uuid" if key in KNOWLEDGE_UUID_FILTER_KEYS else "%s"
            clauses.append(f"t.{column} = {placeholder}")
            params.append(str(value).strip())
        if quality_flag:
            if table != "knowledge_chunks":
                raise ValueError("quality_flag is only supported for knowledge chunks")
            clauses.append("%s = ANY(t.quality_flags)")
            params.append(quality_flag.strip())
        if query and query.strip():
            query_columns = KNOWLEDGE_TABLE_QUERY_COLUMNS.get(table, ())
            if not query_columns:
                raise ValueError(f"query is not supported for {table}")
            clauses.append("(" + " OR ".join(f"t.{column} ILIKE %s" for column in query_columns) + ")")
            params.extend([f"%{query.strip()}%"] * len(query_columns))
        where_sql = " AND ".join(clauses)
        select_sql = "t.*"
        if table == "knowledge_chunks" and enrich_chunks:
            select_sql += ", a.title AS source_asset_title, a.filename AS source_asset_filename, p.adapter_engine AS parser_engine"
        join_sql = ""
        if table == "knowledge_chunks" and enrich_chunks:
            join_sql = (
                " LEFT JOIN knowledge_source_assets a ON a.id = t.source_asset_id AND a.project_id = t.project_id"
                " LEFT JOIN knowledge_parser_runs p ON p.id = t.parser_run_id AND p.project_id = t.project_id"
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(f"SELECT count(*) AS total_count FROM {table} t WHERE {where_sql}", tuple(params))
            total = int((cursor.fetchone() or {}).get("total_count") or 0)
            cursor.execute(
                f"SELECT {select_sql} FROM {table} t{join_sql} WHERE {where_sql} ORDER BY t.created_at DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            records = tuple(dict(row) for row in cursor.fetchall())
            if table in JOB_TABLES:
                records = tuple(_public_job_record(record) for record in records)
            return {"total_count": total, "limit": limit, "offset": offset, "records": records}

    def _status_summary(
        self,
        table: str,
        *,
        project_id: str,
        filters: dict[str, str | None],
        status_column: str,
    ) -> dict[str, int]:
        from psycopg.rows import dict_row

        allowed_filters = KNOWLEDGE_TABLE_FILTERS.get(table, {})
        if status_column not in {"status", "review_status", "embedding_status"}:
            raise ValueError("unsupported knowledge summary status column")
        clauses = ["project_id = %s::uuid"]
        params: list[Any] = [project_id]
        for key, value in filters.items():
            if not value:
                continue
            column = allowed_filters.get(key)
            if column is None:
                raise ValueError(f"unsupported {table} summary filter: {key}")
            placeholder = "%s::uuid" if key in KNOWLEDGE_UUID_FILTER_KEYS else "%s"
            clauses.append(f"{column} = {placeholder}")
            params.append(value)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT {status_column} AS status_key, count(*) AS record_count FROM {table} "
                f"WHERE {' AND '.join(clauses)} GROUP BY {status_column}",
                tuple(params),
            )
            return {str(row["status_key"]): int(row["record_count"]) for row in cursor.fetchall()}

    def _list_audit_events(self, *, project_id: str, target_ids: set[str], limit: int = 200) -> tuple[dict[str, Any], ...]:
        from psycopg.rows import dict_row

        normalized_ids = sorted(value for value in target_ids if value)
        if not normalized_ids:
            return ()
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM audit_events
                WHERE project_id = %s::uuid AND target_id = ANY(%s::text[])
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, normalized_ids, limit),
            )
            return tuple(dict(row) for row in cursor.fetchall())

    def _list_findings_for_targets(
        self,
        *,
        project_id: str,
        pipeline_run_id: str | None,
        target_ids: set[str],
        limit: int,
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        normalized_ids = sorted(value for value in target_ids if value)
        if not normalized_ids:
            return {"total_count": 0, "limit": limit, "offset": 0, "records": ()}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT count(*) AS total_count
                FROM knowledge_quality_findings
                WHERE project_id = %s::uuid
                  AND (%s::uuid IS NULL OR pipeline_run_id = %s::uuid)
                  AND (target_id = ANY(%s::text[]) OR metadata->>'source_asset_id' = ANY(%s::text[]))
                """,
                (project_id, pipeline_run_id, pipeline_run_id, normalized_ids, normalized_ids),
            )
            total = int((cursor.fetchone() or {}).get("total_count") or 0)
            cursor.execute(
                """
                SELECT * FROM knowledge_quality_findings
                WHERE project_id = %s::uuid
                  AND (%s::uuid IS NULL OR pipeline_run_id = %s::uuid)
                  AND (target_id = ANY(%s::text[]) OR metadata->>'source_asset_id' = ANY(%s::text[]))
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, pipeline_run_id, pipeline_run_id, normalized_ids, normalized_ids, limit),
            )
            return {
                "total_count": total,
                "limit": limit,
                "offset": 0,
                "records": tuple(dict(row) for row in cursor.fetchall()),
            }

    def retry_pipeline_stage(self, *, project_id: str, stage_id: str, retried_by: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        retry_tables = {
            "asset_ingestion": ("knowledge_import_jobs",),
            "crawl": ("crawl_jobs",),
            "parse": ("knowledge_parser_runs",),
            "ocr": ("knowledge_parser_runs",),
            "table_extract": ("knowledge_parser_runs",),
            "chunk": ("chunk_jobs",),
            "embedding": ("embedding_jobs",),
            "fact_extract": ("fact_extraction_jobs",),
            "prompt_generate": ("prompt_generation_jobs",),
            "content_generate": ("content_generation_jobs",),
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_pipeline_stages
                WHERE id = %s::uuid AND project_id = %s::uuid
                FOR UPDATE
                """,
                (stage_id, project_id),
            )
            stage = dict(cursor.fetchone() or {})
            if not stage:
                raise ValueError("knowledge pipeline stage not found")
            stage_key = str(stage["stage_key"])
            tables = retry_tables.get(stage_key)
            if not tables:
                raise ValueError("this knowledge pipeline stage cannot be retried automatically")
            requeued = 0
            for table in tables:
                cursor.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'queued', next_run_at = now(),
                        locked_by = null, locked_at = null, lease_expires_at = null,
                        heartbeat_at = null, lease_token = null,
                        last_error_code = null, last_error_message = null,
                        completed_at = null, updated_at = now()
                    WHERE pipeline_run_id = %s::uuid
                      AND status = 'retry_wait'
                    """,
                    (stage["pipeline_run_id"],),
                )
                requeued += max(0, cursor.rowcount)
            if requeued <= 0:
                raise ValueError("knowledge pipeline stage has no retry_wait jobs")
            cursor.execute(
                """
                UPDATE knowledge_pipeline_stages
                SET status = 'queued', retry_count = retry_count + 1,
                    started_at = null, completed_at = null,
                    error_code = null, error_message = null, updated_at = now()
                WHERE id = %s::uuid
                RETURNING *
                """,
                (stage_id,),
            )
            retried_stage = dict(cursor.fetchone() or {})
            cursor.execute(
                """
                UPDATE knowledge_pipeline_runs
                SET status = 'queued', failed_step = null, completed_at = null, updated_at = now()
                WHERE id = %s::uuid
                RETURNING *
                """,
                (stage["pipeline_run_id"],),
            )
            run = dict(cursor.fetchone() or {})
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.pipeline_stage_retried",
                project_id=project_id,
                actor_id=retried_by,
                target_type="knowledge_pipeline_stage",
                target_id=stage_id,
                before=stage,
                after=retried_stage,
                reason=f"retry stage and requeue {requeued} failed jobs",
                method_version="knowledge_pipeline_stage_retry_v1",
            )
            self.connection.commit()
        return {"knowledge_pipeline_stage": retried_stage, "knowledge_pipeline_run": run, "requeued_job_count": requeued}

    def disable_chunk(self, *, project_id: str, chunk_id: str, disabled_by: str, reason: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_chunks
                WHERE id = %s::uuid AND project_id = %s::uuid
                FOR UPDATE
                """,
                (chunk_id, project_id),
            )
            before = dict(cursor.fetchone() or {})
            if not before:
                raise ValueError("knowledge chunk not found")
            if before.get("status") == "disabled":
                return {"knowledge_chunk": before, "already_disabled": True}
            cursor.execute(
                """
                UPDATE knowledge_chunks
                SET status = 'disabled', embedding_status = 'disabled', updated_at = now()
                WHERE id = %s::uuid
                RETURNING *
                """,
                (chunk_id,),
            )
            chunk = dict(cursor.fetchone() or {})
            cursor.execute(
                """
                UPDATE knowledge_fact_candidates
                SET status = 'needs_reextract', review_notes = %s,
                    metadata = metadata || %s::jsonb, updated_at = now()
                WHERE project_id = %s::uuid AND %s::uuid = ANY(source_chunk_ids)
                  AND status IN ('pending_review', 'approved')
                """,
                (
                    reason,
                    json.dumps({"reason": "source_chunk_disabled", "disabled_chunk_id": chunk_id}),
                    project_id,
                    chunk_id,
                ),
            )
            cursor.execute(
                """
                UPDATE localized_knowledge_facts
                SET status = 'superseded',
                    metadata = metadata || %s::jsonb
                WHERE project_id = %s::uuid AND %s::uuid = ANY(source_chunk_ids)
                  AND status = 'active'
                """,
                (json.dumps({"reason": "source_chunk_disabled", "disabled_chunk_id": chunk_id}), project_id, chunk_id),
            )
            cursor.execute(
                """
                UPDATE prompt_candidates
                SET review_status = 'superseded', updated_at = now()
                WHERE project_id = %s::uuid AND %s::uuid = ANY(source_chunk_ids)
                  AND review_status IN ('pending_review', 'approved', 'edited_approved')
                """,
                (project_id, chunk_id),
            )
            cursor.execute(
                """
                UPDATE content_drafts
                SET status = 'needs_revision', review_status = 'needs_revision'
                WHERE project_id = %s::uuid AND %s::uuid = ANY(source_chunk_ids)
                  AND status IN ('pending_human_review', 'approved')
                """,
                (project_id, chunk_id),
            )
            audit_id = stable_pipeline_id("chunk-disabled", project_id, chunk_id, content_hash(reason))
            cursor.execute(
                """
                INSERT INTO audit_events (
                  id, event_type, project_id, actor_type, actor_id, target_type, target_id,
                  before_hash, after_hash, input_refs, output_refs, method_version, reason
                ) VALUES (%s::uuid, 'knowledge.chunk_disabled', %s::uuid, 'user', %s,
                          'knowledge_chunk', %s, %s, %s, %s::jsonb, %s::jsonb,
                          'knowledge_chunk_disable_v1', %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    audit_id,
                    project_id,
                    disabled_by,
                    chunk_id,
                    payload_hash(before),
                    payload_hash(chunk),
                    json.dumps({"knowledge_chunk_ids": [chunk_id]}),
                    json.dumps({"status": "disabled"}),
                    reason,
                ),
            )
            self.connection.commit()
        qdrant_point_id = str(chunk.get("qdrant_point_id") or "")
        if qdrant_point_id:
            QdrantKnowledgeStore(
                collection=os.getenv("QDRANT_COLLECTION") or DEFAULT_QDRANT_COLLECTION
            ).update_payload(
                point_ids=[qdrant_point_id],
                payload={"status": "disabled", "embedding_status": "disabled"},
            )
        return {"knowledge_chunk": chunk, "already_disabled": False}

    def get_chunk_trace(self, *, project_id: str, chunk_id: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM knowledge_chunks WHERE id = %s::uuid AND project_id = %s::uuid",
                (chunk_id, project_id),
            )
            chunk = dict(cursor.fetchone() or {})
            if not chunk:
                raise ValueError("knowledge chunk not found")
            cursor.execute(
                "SELECT * FROM knowledge_blocks WHERE id = ANY(%s::uuid[]) ORDER BY block_index ASC",
                (list(chunk.get("source_block_ids") or []),),
            )
            blocks = tuple(dict(row) for row in cursor.fetchall())
            cursor.execute("SELECT * FROM knowledge_parser_runs WHERE id = %s::uuid", (chunk.get("parser_run_id"),))
            parser_run = dict(cursor.fetchone() or {})
            cursor.execute("SELECT * FROM knowledge_source_assets WHERE id = %s::uuid", (chunk.get("source_asset_id"),))
            source_asset = dict(cursor.fetchone() or {})
            cursor.execute("SELECT * FROM knowledge_import_jobs WHERE id = %s::uuid", (chunk.get("import_job_id"),))
            import_job = dict(cursor.fetchone() or {})
            cursor.execute(
                """
                SELECT * FROM knowledge_tables
                WHERE parser_run_id = %s::uuid
                ORDER BY table_index ASC
                """,
                (chunk.get("parser_run_id"),),
            )
            tables = tuple(dict(row) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT * FROM knowledge_quality_findings
                WHERE project_id = %s::uuid
                  AND ((target_type = 'chunk' AND target_id = %s)
                    OR (target_type = 'parser_run' AND target_id = %s)
                    OR (target_type = 'asset' AND target_id = %s))
                ORDER BY created_at DESC
                """,
                (project_id, chunk_id, str(chunk.get("parser_run_id") or ""), str(chunk.get("source_asset_id") or "")),
            )
            findings = tuple(dict(row) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT * FROM knowledge_fact_candidates
                WHERE project_id = %s::uuid AND %s::uuid = ANY(source_chunk_ids)
                ORDER BY created_at DESC
                """,
                (project_id, chunk_id),
            )
            fact_candidates = tuple(dict(row) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT * FROM localized_knowledge_facts
                WHERE project_id = %s::uuid AND %s::uuid = ANY(source_chunk_ids)
                ORDER BY valid_from DESC
                """,
                (project_id, chunk_id),
            )
            approved_facts = tuple(dict(row) for row in cursor.fetchall())
            approved_fact_ids = [str(fact["id"]) for fact in approved_facts]
            cursor.execute(
                """
                SELECT * FROM knowledge_trace_refs
                WHERE project_id = %s::uuid
                  AND ((source_type = 'chunk' AND source_id = %s)
                    OR (target_type = 'chunk' AND target_id = %s)
                    OR (source_type = 'approved_fact' AND source_id = ANY(%s::text[])))
                ORDER BY created_at ASC
                """,
                (project_id, chunk_id, chunk_id, approved_fact_ids),
            )
            trace_refs = tuple(dict(row) for row in cursor.fetchall())
            prompt_candidate_ids = [
                str(ref["target_id"])
                for ref in trace_refs
                if ref.get("target_type") == "prompt_candidate"
            ]
            content_draft_ids = [
                str(ref["target_id"])
                for ref in trace_refs
                if ref.get("target_type") == "content_draft"
            ]
            cursor.execute(
                """
                SELECT * FROM prompt_candidates
                WHERE project_id = %s::uuid AND id = ANY(%s::uuid[])
                ORDER BY created_at DESC
                """,
                (project_id, prompt_candidate_ids),
            )
            prompt_candidates = tuple(dict(row) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT * FROM content_drafts
                WHERE project_id = %s::uuid AND id = ANY(%s::uuid[])
                ORDER BY created_at DESC
                """,
                (project_id, content_draft_ids),
            )
            content_drafts = tuple(dict(row) for row in cursor.fetchall())
        return {
            "knowledge_chunk": chunk,
            "blocks": blocks,
            "tables": tables,
            "parser_run": parser_run,
            "source_asset": source_asset,
            "import_job": import_job,
            "quality_findings": findings,
            "fact_candidates": fact_candidates,
            "approved_facts": approved_facts,
            "prompt_candidates": prompt_candidates,
            "content_drafts": content_drafts,
            "trace_refs": trace_refs,
        }

    def export_content_draft(self, *, project_id: str, content_draft_id: str, exported_by: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM content_drafts
                WHERE id = %s::uuid AND project_id = %s::uuid
                FOR UPDATE
                """,
                (content_draft_id, project_id),
            )
            before = dict(cursor.fetchone() or {})
            if not before:
                raise ValueError("content draft not found")
            if str(before.get("status") or "") not in {"approved", "exported", "published"}:
                raise ValueError("only an approved content draft can be exported")
            cursor.execute(
                """
                UPDATE content_drafts
                SET status = 'exported', updated_at = now()
                WHERE id = %s::uuid
                RETURNING *
                """,
                (content_draft_id,),
            )
            draft = dict(cursor.fetchone() or {})
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.content_draft_exported",
                project_id=project_id,
                actor_id=exported_by,
                target_type="content_draft",
                target_id=content_draft_id,
                before=before,
                after=draft,
                reason="export approved GEO content draft",
                method_version="knowledge_content_export_v1",
            )
            self.connection.commit()
        return draft

    def review_fact_candidate(
        self,
        *,
        project_id: str,
        fact_candidate_id: str,
        review_status: str,
        reviewed_by: str,
        notes: str | None = None,
        merged_into_fact_id: str | None = None,
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        normalized_status = review_status.strip().lower()
        if normalized_status not in {
            "approved", "rejected", "archived", "forbidden", "needs_reextract",
            "pending_review", "superseded", "merged",
        }:
            raise ValueError("fact candidate review_status is not supported")
        if normalized_status == "merged" and not merged_into_fact_id:
            raise ValueError("merged_into_fact_id is required when merging a fact candidate")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_fact_candidates
                WHERE id = %s::uuid AND project_id = %s::uuid
                FOR UPDATE
                """,
                (fact_candidate_id, project_id),
            )
            candidate = dict(cursor.fetchone() or {})
            if not candidate:
                raise ValueError("knowledge fact candidate not found")
            if normalized_status == "approved":
                source_chunk_ids = list(candidate.get("source_chunk_ids") or [])
                source_asset_ids = list(candidate.get("source_asset_ids") or [])
                quality_flags = list(dict(candidate.get("metadata") or {}).get("quality_flags") or [])
                if not source_chunk_ids or not source_asset_ids:
                    raise ValueError("knowledge fact candidate cannot be approved without source evidence")
                if "fact_forbidden_claim" in quality_flags:
                    raise ValueError("knowledge fact candidate contains a forbidden claim and cannot be approved")
                cursor.execute(
                    """
                    SELECT count(*) AS source_count
                    FROM knowledge_chunks
                    WHERE project_id = %s::uuid AND id = ANY(%s::uuid[])
                      AND status = 'active' AND embedding_status = 'embedded'
                    """,
                    (project_id, source_chunk_ids),
                )
                if int((cursor.fetchone() or {}).get("source_count") or 0) != len(source_chunk_ids):
                    raise ValueError("knowledge fact candidate references disabled or stale chunks")
            if merged_into_fact_id:
                cursor.execute(
                    """
                    SELECT id FROM localized_knowledge_facts
                    WHERE id = %s::uuid AND project_id = %s::uuid AND status = 'active'
                    """,
                    (merged_into_fact_id, project_id),
                )
                if not cursor.fetchone():
                    raise ValueError("merge target active knowledge fact not found")
            cursor.execute(
                """
                UPDATE knowledge_fact_candidates
                SET status = %s, reviewed_by = %s, reviewed_at = now(),
                    review_notes = %s,
                    merged_into_fact_id = %s::uuid,
                    metadata = metadata || %s::jsonb,
                    updated_at = now()
                WHERE id = %s::uuid
                RETURNING *
                """,
                (
                    normalized_status,
                    reviewed_by,
                    notes or "",
                    merged_into_fact_id,
                    json.dumps({"review_notes": notes or ""}, ensure_ascii=False),
                    fact_candidate_id,
                ),
            )
            reviewed_candidate = dict(cursor.fetchone() or {})
            cursor.execute(
                """
                UPDATE knowledge_quality_findings
                SET status = 'resolved',
                    metadata = metadata || %s::jsonb,
                    updated_at = now()
                WHERE project_id = %s::uuid
                  AND pipeline_run_id = %s::uuid
                  AND metadata->>'fact_candidate_id' = %s
                  AND status = 'open'
                """,
                (
                    json.dumps({"resolved_by": reviewed_by, "review_status": normalized_status}, ensure_ascii=False),
                    project_id,
                    candidate.get("pipeline_run_id"),
                    fact_candidate_id,
                ),
            )
            cursor.execute(
                """
                UPDATE knowledge_quality_gate_runs gate_run
                SET status = CASE
                      WHEN EXISTS (
                        SELECT 1 FROM knowledge_quality_findings finding
                        WHERE finding.id = ANY(gate_run.finding_ids)
                          AND finding.status = 'open' AND finding.severity IN ('high', 'critical')
                      ) THEN 'blocked'
                      WHEN EXISTS (
                        SELECT 1 FROM knowledge_quality_findings finding
                        WHERE finding.id = ANY(gate_run.finding_ids) AND finding.status = 'open'
                      ) THEN 'warning'
                      ELSE 'passed'
                    END,
                    updated_at = now()
                WHERE gate_run.project_id = %s::uuid
                  AND gate_run.pipeline_run_id = %s::uuid
                  AND gate_run.gate_key IN ('fact_quality_gate', 'security_gate')
                """,
                (project_id, candidate.get("pipeline_run_id")),
            )
            approved_fact: dict[str, Any] | None = None
            if normalized_status == "approved":
                fact_id = stable_pipeline_id("approved-fact", fact_candidate_id)
                cursor.execute(
                    """
                    INSERT INTO localized_knowledge_facts (
                      id, project_id, market_code, fact_type, subject, predicate, object_value,
                      city, evidence_source_id, confidence, status, valid_from, valid_until,
                      source_candidate_id, fact_kind, locale, source_chunk_ids, source_block_ids,
                      source_asset_ids, approved_by, approved_at, created_from_pipeline_run_id,
                      created_from_job_id, metadata
                    ) VALUES (
                      %s::uuid, %s::uuid, %s, %s, %s, %s, %s,
                      %s, null, %s, 'active', now(), null,
                      %s::uuid, %s, %s, %s::uuid[], %s::uuid[],
                      %s::uuid[], %s, now(), %s::uuid,
                      %s::uuid, %s::jsonb
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      status = 'active',
                      confidence = EXCLUDED.confidence,
                      source_chunk_ids = EXCLUDED.source_chunk_ids,
                      source_block_ids = EXCLUDED.source_block_ids,
                      source_asset_ids = EXCLUDED.source_asset_ids,
                      approved_by = EXCLUDED.approved_by,
                      approved_at = EXCLUDED.approved_at,
                      metadata = localized_knowledge_facts.metadata || EXCLUDED.metadata
                    RETURNING *
                    """,
                    (
                        fact_id,
                        project_id,
                        candidate["market_code"],
                        candidate["fact_type"],
                        candidate["subject"],
                        candidate["predicate"],
                        candidate["object_value"],
                        candidate.get("city"),
                        candidate["confidence"],
                        fact_candidate_id,
                        candidate["fact_kind"],
                        candidate["locale"],
                        list(candidate.get("source_chunk_ids") or []),
                        list(candidate.get("source_block_ids") or []),
                        list(candidate.get("source_asset_ids") or []),
                        reviewed_by,
                        candidate.get("pipeline_run_id"),
                        candidate.get("fact_extraction_job_id"),
                        json.dumps({"review_source": "knowledge_fact_candidate", "review_notes": notes or ""}, ensure_ascii=False),
                    ),
                )
                approved_fact = dict(cursor.fetchone() or {})
                cursor.execute(
                    """
                    UPDATE knowledge_fact_candidates
                    SET approved_fact_id = %s::uuid, updated_at = now()
                    WHERE id = %s::uuid
                    """,
                    (fact_id, fact_candidate_id),
                )
                cursor.execute(
                    """
                    INSERT INTO knowledge_trace_refs (
                      project_id, pipeline_run_id, source_type, source_id, target_type, target_id,
                      trace_role, confidence, created_by_job_type, created_by_job_id, metadata
                    ) VALUES (%s::uuid, %s::uuid, 'fact_candidate', %s, 'approved_fact', %s,
                              'derived_from', %s, 'human_review', null, %s::jsonb)
                    """,
                    (
                        project_id,
                        candidate.get("pipeline_run_id"),
                        fact_candidate_id,
                        fact_id,
                        candidate.get("confidence"),
                        json.dumps({"reviewed_by": reviewed_by}, ensure_ascii=False),
                    ),
                )
            candidate_pipeline_run_id = str(candidate.get("pipeline_run_id") or "") or None
            if candidate_pipeline_run_id:
                cursor.execute(
                    """
                    SELECT run_type,
                           (SELECT count(*) FROM knowledge_fact_candidates
                            WHERE pipeline_run_id = knowledge_pipeline_runs.id
                              AND status = 'pending_review') AS pending_fact_count
                    FROM knowledge_pipeline_runs
                    WHERE id = %s::uuid
                    """,
                    (candidate_pipeline_run_id,),
                )
                run_type_row = cursor.fetchone() or {}
                if (
                    str(run_type_row.get("run_type") or "") in {"full_ingestion", "full_rebuild"}
                    and int(run_type_row.get("pending_fact_count") or 0) == 0
                ):
                    self.enqueue_generation_for_approved_facts(
                        cursor=cursor,
                        project_id=project_id,
                        pipeline_run_id=candidate_pipeline_run_id,
                    )
            self._record_audit(
                cursor=cursor,
                event_type=f"knowledge.fact_candidate_{normalized_status}",
                project_id=project_id,
                actor_id=reviewed_by,
                target_type="knowledge_fact_candidate",
                target_id=fact_candidate_id,
                before=candidate,
                after=reviewed_candidate,
                reason=notes or f"fact candidate {normalized_status}",
                method_version="knowledge_fact_candidate_review_v1",
            )
            self.connection.commit()
            pipeline_states = self.refresh_project_pipeline_states(project_id=project_id)
            return {
                "fact_candidate": reviewed_candidate,
                "approved_fact": approved_fact,
                "pipeline_states": pipeline_states,
            }

    def enqueue_generation_for_approved_facts(self, *, cursor: Any, project_id: str, pipeline_run_id: str | None) -> None:
        if not pipeline_run_id:
            return
        cursor.execute(
            "SELECT run_type, metadata FROM knowledge_pipeline_runs WHERE id = %s::uuid AND project_id = %s::uuid",
            (pipeline_run_id, project_id),
        )
        run_row = cursor.fetchone() or {}
        if not run_row:
            return
        run_type = str(run_row.get("run_type") or "full_ingestion")
        metadata = dict(run_row.get("metadata") or {})
        cursor.execute(
            """
            SELECT count(*) AS approved_count
            FROM localized_knowledge_facts
            WHERE project_id = %s::uuid AND status = 'active'
            """,
            (project_id,),
        )
        row = cursor.fetchone()
        approved_count = int(row["approved_count"] if isinstance(row, dict) else row[0])
        if approved_count <= 0:
            return
        if run_type in {"full_ingestion", "full_rebuild", "prompt_generation"}:
            template_key = str(metadata.get("template_key") or "brand_visibility_prompt_v1")
            template_version = str(metadata.get("template_version") or "v1")
            cursor.execute(
                """
                SELECT id
                FROM prompt_generation_templates
                WHERE template_key = %s AND template_version = %s AND status = 'published'
                LIMIT 1
                """,
                (template_key, template_version),
            )
            template_row = cursor.fetchone()
            template_id = (template_row or {}).get("id") if isinstance(template_row, dict) else (template_row[0] if template_row else None)
            if template_id is None:
                raise ValueError(
                    f"published Prompt generation template {template_key}:{template_version} not found"
                )
            cursor.execute(
                """
                INSERT INTO prompt_generation_jobs (
                  id, project_id, pipeline_run_id, template_id, template_version, target_platform,
                  intent_type, city, source_fact_filter, source_chunk_filter,
                  requested_count, model, metadata
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s,
                          %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    stable_pipeline_id("prompt-generation-job", project_id, pipeline_run_id),
                    project_id,
                    pipeline_run_id,
                    template_id,
                    template_version,
                    str(metadata.get("target_platform") or "chatgpt"),
                    str(metadata.get("intent_type") or "brand_visibility"),
                    str(metadata.get("city") or "") or None,
                    json.dumps(metadata.get("source_fact_filter") or {}, ensure_ascii=False),
                    json.dumps(metadata.get("source_chunk_filter") or {}, ensure_ascii=False),
                    max(1, min(50, int(metadata.get("requested_count") or 10))),
                    str(metadata.get("model") or "deepseek-v4-flash"),
                    json.dumps(
                        {
                            "trigger": "approved_fact_available",
                            "template_key": template_key,
                            "approved_fact_count": approved_count,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        if run_type in {"full_ingestion", "full_rebuild", "content_generation"}:
            cursor.execute(
                """
                INSERT INTO content_generation_jobs (
                  id, project_id, pipeline_run_id, content_type, target_platform,
                  target_city, tone, required_citations, forbidden_claims,
                  model, template_version, target_audience, target_action, metadata
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s,
                          %s, %s, %s, %s::text[], %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    stable_pipeline_id("content-generation-job", project_id, pipeline_run_id),
                    project_id,
                    pipeline_run_id,
                    str(metadata.get("content_type") or "faq"),
                    str(metadata.get("target_platform") or "chatgpt"),
                    str(metadata.get("target_city") or metadata.get("city") or "") or None,
                    str(metadata.get("tone") or "clear"),
                    max(1, min(20, int(metadata.get("required_citations") or 1))),
                    [str(value) for value in (metadata.get("forbidden_claims") or []) if str(value).strip()],
                    str(metadata.get("model") or "deepseek-v4-flash"),
                    str(metadata.get("template_version") or "geo_content_draft_v1"),
                    str(metadata.get("target_audience") or "general customer"),
                    json.dumps(
                        {
                            key: metadata.get(key)
                            for key in ("source_action_id", "source_report_id", "source_retest_id", "source_gap_type")
                            if metadata.get(key)
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {"trigger": "approved_fact_available", "approved_fact_count": approved_count},
                        ensure_ascii=False,
                    ),
                ),
            )

    def refresh_project_pipeline_states(self, *, project_id: str) -> tuple[dict[str, Any], ...]:
        from psycopg.rows import dict_row

        refreshed: list[dict[str, Any]] = []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, pipeline_run_id, finding_ids,
                       COALESCE(metadata->>'accepted_from_status', 'blocked') AS restore_status
                FROM knowledge_quality_gate_runs
                WHERE project_id = %s::uuid AND status = 'accepted_risk'
                  AND accepted_expires_at IS NOT NULL AND accepted_expires_at <= now()
                FOR UPDATE
                """,
                (project_id,),
            )
            expired_risks = [dict(row) for row in cursor.fetchall()]
            for expired in expired_risks:
                restore_status = str(expired.get("restore_status") or "blocked")
                if restore_status not in {"warning", "blocked"}:
                    restore_status = "blocked"
                cursor.execute(
                    """
                    UPDATE knowledge_quality_gate_runs
                    SET status = %s,
                        metadata = metadata || '{"accepted_risk_expired":true}'::jsonb,
                        updated_at = now()
                    WHERE id = %s::uuid
                    """,
                    (restore_status, expired["id"]),
                )
                finding_ids = list(expired.get("finding_ids") or [])
                if finding_ids:
                    cursor.execute(
                        """
                        UPDATE knowledge_quality_findings
                        SET status = 'open',
                            metadata = metadata || '{"accepted_risk_expired":true}'::jsonb,
                            updated_at = now()
                        WHERE id = ANY(%s::uuid[])
                        """,
                        (finding_ids,),
                    )
                if expired.get("pipeline_run_id"):
                    cursor.execute(
                        """
                        UPDATE knowledge_pipeline_runs
                        SET status = 'running', completed_at = null, updated_at = now()
                        WHERE id = %s::uuid AND status NOT IN ('cancelled')
                        """,
                        (expired["pipeline_run_id"],),
                    )
            cursor.execute(
                """
                SELECT id, run_type
                FROM knowledge_pipeline_runs
                WHERE project_id = %s::uuid
                  AND status IN ('queued', 'running', 'waiting_human_review')
                ORDER BY created_at ASC
                FOR UPDATE
                """,
                (project_id,),
            )
            runs = [(str(row["id"]), str(row["run_type"])) for row in cursor.fetchall()]
            for pipeline_run_id, run_type in runs:
                cursor.execute(
                    """
                    SELECT
                      (SELECT count(*) FROM knowledge_fact_candidates WHERE pipeline_run_id = %s::uuid) AS fact_total,
                      (SELECT count(*) FROM knowledge_fact_candidates WHERE pipeline_run_id = %s::uuid AND status = 'pending_review') AS fact_pending,
                      (SELECT count(*) FROM prompt_candidates WHERE pipeline_run_id = %s::uuid) AS prompt_total,
                      (SELECT count(*) FROM prompt_candidates WHERE pipeline_run_id = %s::uuid AND review_status = 'pending_review') AS prompt_pending,
                      (SELECT count(*) FROM content_drafts WHERE pipeline_run_id = %s::uuid) AS content_total,
                      (SELECT count(*) FROM content_drafts WHERE pipeline_run_id = %s::uuid AND status = 'pending_human_review') AS content_pending,
                      (SELECT count(*) FROM knowledge_quality_gate_runs WHERE pipeline_run_id = %s::uuid AND status IN ('blocked', 'failed')) AS blocked_gates,
                      (SELECT count(*) FROM prompt_candidates pc WHERE pc.pipeline_run_id = %s::uuid AND NOT EXISTS (
                         SELECT 1 FROM knowledge_trace_refs tr
                         WHERE tr.project_id = pc.project_id AND tr.target_type = 'prompt_candidate' AND tr.target_id = pc.id::text
                       )) AS untraced_prompts,
                      (SELECT count(*) FROM content_drafts cd WHERE cd.pipeline_run_id = %s::uuid AND NOT EXISTS (
                         SELECT 1 FROM knowledge_trace_refs tr
                         WHERE tr.project_id = cd.project_id AND tr.target_type = 'content_draft' AND tr.target_id = cd.id::text
                       )) AS untraced_content
                    """,
                    (pipeline_run_id,) * 9,
                )
                counts = dict(cursor.fetchone() or {})
                pending_jobs = 0
                failed_jobs = 0
                partial_jobs = 0
                job_totals: dict[str, int] = {}
                for table in JOB_TABLES:
                    cursor.execute(
                        f"SELECT count(*) AS total, "
                        f"count(*) FILTER (WHERE status IN ('queued', 'retry_wait', 'running', 'finalizing', 'ready', 'draft')) AS pending, "
                        f"count(*) FILTER (WHERE status IN ('failed', 'dead_letter')) AS failed, "
                        f"count(*) FILTER (WHERE status = 'partial_succeeded') AS partial "
                        f"FROM {table} WHERE pipeline_run_id = %s::uuid",
                        (pipeline_run_id,),
                    )
                    job_counts = cursor.fetchone() or {}
                    job_totals[table] = int(job_counts.get("total") or 0)
                    pending_jobs += int(job_counts.get("pending") or 0)
                    failed_jobs += int(job_counts.get("failed") or 0)
                    partial_jobs += int(job_counts.get("partial") or 0)

                fact_total = int(counts.get("fact_total") or 0)
                fact_pending = int(counts.get("fact_pending") or 0)
                prompt_total = int(counts.get("prompt_total") or 0)
                prompt_pending = int(counts.get("prompt_pending") or 0)
                content_total = int(counts.get("content_total") or 0)
                content_pending = int(counts.get("content_pending") or 0)
                blocked_gates = int(counts.get("blocked_gates") or 0)
                untraced = int(counts.get("untraced_prompts") or 0) + int(counts.get("untraced_content") or 0)

                for stage_key, total, pending in (
                    ("fact_review", fact_total, fact_pending),
                    ("prompt_review", prompt_total, prompt_pending),
                    ("content_review", content_total, content_pending),
                ):
                    if total:
                        cursor.execute(
                            """
                            UPDATE knowledge_pipeline_stages
                            SET status = %s,
                                completed_at = CASE WHEN %s = 0 THEN now() ELSE null END,
                                summary = summary || %s::jsonb,
                                updated_at = now()
                            WHERE pipeline_run_id = %s::uuid AND stage_key = %s
                            """,
                            (
                                "succeeded" if pending == 0 else "waiting_review",
                                pending,
                                json.dumps({"total_count": total, "waiting_review_count": pending}),
                                pipeline_run_id,
                                stage_key,
                            ),
                        )

                waiting_stage = None
                waiting_count = 0
                if fact_pending:
                    waiting_stage, waiting_count = "fact_review", fact_pending
                elif prompt_pending:
                    waiting_stage, waiting_count = "prompt_review", prompt_pending
                elif content_pending:
                    waiting_stage, waiting_count = "content_review", content_pending

                complete_outputs = fact_total > 0 and prompt_total > 0 and content_total > 0
                maintenance_complete = False
                if run_type == "reparse":
                    maintenance_complete = job_totals.get("knowledge_parser_runs", 0) > 0 and pending_jobs == 0
                elif run_type == "rechunk":
                    maintenance_complete = (
                        job_totals.get("chunk_jobs", 0) > 0
                        and job_totals.get("embedding_jobs", 0) > 0
                        and pending_jobs == 0
                    )
                elif run_type == "reindex":
                    maintenance_complete = job_totals.get("embedding_jobs", 0) > 0 and pending_jobs == 0
                elif run_type == "fact_refresh":
                    maintenance_complete = fact_total > 0 and fact_pending == 0 and pending_jobs == 0
                elif run_type == "prompt_generation":
                    maintenance_complete = prompt_total > 0 and prompt_pending == 0 and pending_jobs == 0
                elif run_type == "content_generation":
                    maintenance_complete = content_total > 0 and content_pending == 0 and pending_jobs == 0
                if waiting_stage:
                    status = "waiting_human_review"
                elif blocked_gates or failed_jobs or untraced:
                    status = "failed"
                elif pending_jobs:
                    status = "running"
                elif partial_jobs and (complete_outputs or maintenance_complete):
                    status = "partial_succeeded"
                elif complete_outputs or maintenance_complete:
                    status = "succeeded"
                else:
                    status = "running"

                if complete_outputs and untraced == 0:
                    cursor.execute(
                        """
                        UPDATE knowledge_pipeline_stages
                        SET status = 'succeeded', completed_at = now(),
                            summary = summary || %s::jsonb, updated_at = now()
                        WHERE pipeline_run_id = %s::uuid AND stage_key = 'trace_verify'
                        """,
                        (json.dumps({"untraced_output_count": 0}), pipeline_run_id),
                    )
                if status in {"succeeded", "partial_succeeded"}:
                    cursor.execute(
                        """
                        UPDATE knowledge_pipeline_stages
                        SET status = 'skipped', completed_at = now(),
                            summary = summary || '{"reason":"ingestion pipeline does not auto-publish"}'::jsonb,
                            updated_at = now()
                        WHERE pipeline_run_id = %s::uuid AND stage_key = 'publish_or_export'
                        """,
                        (pipeline_run_id,),
                    )
                    cursor.execute(
                        """
                        UPDATE knowledge_pipeline_stages
                        SET status = 'skipped', completed_at = now(),
                            summary = summary || %s::jsonb, updated_at = now()
                        WHERE pipeline_run_id = %s::uuid AND status = 'not_started'
                        """,
                        (json.dumps({"reason": f"not required for {run_type}"}), pipeline_run_id),
                    )
                summary = {
                    "fact_total": fact_total,
                    "prompt_total": prompt_total,
                    "content_total": content_total,
                    "pending_job_count": pending_jobs,
                    "failed_job_count": failed_jobs,
                    "partial_job_count": partial_jobs,
                    "blocked_gate_count": blocked_gates,
                    "untraced_output_count": untraced,
                    "run_type": run_type,
                    "job_totals": job_totals,
                }
                cursor.execute(
                    """
                    UPDATE knowledge_pipeline_runs
                    SET status = %s,
                        waiting_review_stage_key = %s,
                        waiting_review_count = %s,
                        completed_at = CASE WHEN %s IN ('succeeded', 'partial_succeeded', 'failed') THEN now() ELSE null END,
                        failed_step = CASE WHEN %s = 'failed' THEN COALESCE(failed_step, 'quality_or_job') ELSE null END,
                        summary = summary || %s::jsonb,
                        updated_at = now()
                    WHERE id = %s::uuid
                    RETURNING *
                    """,
                    (
                        status,
                        waiting_stage,
                        waiting_count,
                        status,
                        status,
                        json.dumps(summary, ensure_ascii=False),
                        pipeline_run_id,
                    ),
                )
                refreshed.append(dict(cursor.fetchone() or {}))
            self.connection.commit()
        return tuple(refreshed)

    def claim_job_outcome(
        self,
        table: str,
        *,
        worker_id: str,
        lease_seconds: int,
        mode: ClaimMode = "any",
    ) -> ClaimOutcome:
        return claim_durable_job(
            self.connection,
            durable_job_spec(table),
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            mode=mode,
        )

    def claim_job(
        self,
        table: str,
        *,
        worker_id: str,
        lease_seconds: int,
        mode: ClaimMode = "any",
    ) -> LeaseClaim | None:
        return self.claim_job_outcome(
            table, worker_id=worker_id, lease_seconds=lease_seconds, mode=mode
        ).claim

    def complete_job(
        self,
        claim: LeaseClaim,
        *,
        status: str,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return complete_durable_job(self.connection, claim, status=status, result=summary)

    def fail_job(
        self,
        claim: LeaseClaim,
        *,
        error_code: str,
        error_message: str,
        retry_seconds: int = 120,
        retryable: bool = True,
    ) -> dict[str, Any]:
        self.connection.rollback()
        return fail_durable_job(
            self.connection,
            claim,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            retry_seconds=retry_seconds,
        )

    def begin_job_finalizing(
        self, claim: LeaseClaim, *, descriptor: dict[str, Any]
    ) -> dict[str, Any]:
        return begin_durable_finalizing(self.connection, claim, descriptor=descriptor)

    def acknowledge_job_cancel(self, claim: LeaseClaim) -> dict[str, Any]:
        self.connection.rollback()
        return acknowledge_durable_cancel(self.connection, claim)

    def cancel_job(self, table: str, *, project_id: str, job_id: str) -> dict[str, Any]:
        from uuid import UUID

        cancelled = request_durable_cancel(
            self.connection,
            durable_job_spec(table),
            project_id=UUID(project_id),
            job_id=UUID(job_id),
        )
        return _public_job_record(cancelled)

    def next_job_table_order(self, *, queue_name: str, worker_id: str) -> tuple[str, ...]:
        if queue_name not in {"knowledge_fresh", "knowledge_recovery"}:
            raise ValueError("unsupported Knowledge fair queue")
        return next_fair_table_order(
            self.connection,
            queue_name=queue_name,
            tables=JOB_TABLES,
            worker_id=worker_id,
        )

    def record_recovery_pass(self, *, worker_id: str, slots_used: int) -> None:
        record_recovery_pass(
            self.connection,
            queue_name="knowledge_recovery",
            worker_id=worker_id,
            slots_used=slots_used,
        )

    def lease_guard(self, claim: LeaseClaim, *, lease_seconds: int) -> LeaseGuard:
        import psycopg

        database_url = self.database_url or os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for the independent LeaseGuard connection")

        def initialize_scope(connection: Any, worker_id: str) -> None:
            KnowledgePipelineRepository(connection).set_maintenance_scope(worker_id=worker_id)

        return LeaseGuard(
            claim,
            lease_seconds=lease_seconds,
            connection_factory=lambda: psycopg.connect(database_url),
            scope_initializer=initialize_scope,
        )

    @contextmanager
    def fence_job_commits(self, claim: LeaseClaim, *, lease_seconds: int):
        raw_connection = self.connection
        if isinstance(raw_connection, LeaseFencedConnection):
            raise RuntimeError("nested durable handler commit fence is not supported")
        fenced = LeaseFencedConnection(raw_connection, claim, lease_seconds=lease_seconds)
        self.connection = fenced
        try:
            yield fenced
        except BaseException:
            fenced.rollback()
            raise
        else:
            if (
                fenced.commits_deferred
                and not fenced.terminal_completed
                and not fenced.finalizing_committed
            ):
                fenced.rollback()
                raise RuntimeError("durable handler exited without atomic terminal completion")
            if not fenced.commits_deferred:
                fenced.commit()
        finally:
            self.connection = raw_connection

    def run_ready_pipeline_once(self, *, worker_id: str) -> dict[str, Any] | None:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_pipeline_runs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
            run = dict(cursor.fetchone() or {})
            if not run:
                return None
            cursor.execute(
                """
                UPDATE knowledge_pipeline_runs
                SET status = 'running', started_at = COALESCE(started_at, now()), updated_at = now()
                WHERE id = %s::uuid
                """,
                (run["id"],),
            )
            cursor.execute(
                """
                UPDATE knowledge_import_jobs
                SET status = 'queued', next_run_at = now(), updated_at = now()
                WHERE pipeline_run_id = %s::uuid AND status IN ('ready', 'draft')
                """,
                (run["id"],),
            )
            cursor.execute(
                """
                UPDATE knowledge_pipeline_stages
                SET status = CASE WHEN stage_key IN ('source_precheck', 'asset_ingestion') THEN 'succeeded' ELSE status END,
                    completed_at = CASE WHEN stage_key IN ('source_precheck', 'asset_ingestion') THEN now() ELSE completed_at END,
                    updated_at = now()
                WHERE pipeline_run_id = %s::uuid
                """,
                (run["id"],),
            )
            self.connection.commit()
            return run

    def create_asset_from_text(
        self,
        *,
        project_id: str,
        pipeline_run_id: str | None,
        import_job_id: str | None,
        crawl_job_id: str | None = None,
        asset_type: str,
        text: str,
        title: str,
        source_uri: str | None,
        created_by: str,
        market_code: str = "GLOBAL",
        locale: str = "en",
        city: str | None = None,
        asset_id: str | None = None,
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_source_assets (
                  id, project_id, pipeline_run_id, import_job_id, crawl_job_id, asset_type, status, source_uri, title,
                  content_type, content_hash, byte_size, market_code, locale, city, metadata, created_by
                ) VALUES (COALESCE(%s::uuid, uuid_generate_v4()), %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, 'accepted', %s, %s, 'text/plain',
                          %s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (id) DO UPDATE SET updated_at = knowledge_source_assets.updated_at
                RETURNING *
                """,
                (
                    asset_id,
                    project_id,
                    pipeline_run_id,
                    import_job_id,
                    crawl_job_id,
                    asset_type,
                    source_uri,
                    title,
                    content_hash(text),
                    len(text.encode("utf-8")),
                    market_code,
                    locale,
                    city,
                    json.dumps({"text_preview": text[:1000], "text_body": text}, ensure_ascii=False),
                    created_by,
                ),
            )
            asset = dict(cursor.fetchone() or {})
            self.connection.commit()
            return asset

    def create_asset_from_stored_object(
        self,
        *,
        project_id: str,
        pipeline_run_id: str | None,
        import_job_id: str | None,
        crawl_job_id: str | None = None,
        asset_type: str,
        stored: StoredObject,
        title: str,
        source_uri: str | None,
        created_by: str,
        market_code: str = "GLOBAL",
        locale: str = "en",
        city: str | None = None,
        metadata: dict[str, Any] | None = None,
        filename: str | None = None,
        parser_engine: str | None = None,
        parser_version: str | None = None,
        precheck_result: dict[str, Any] | None = None,
        duplicate_of_asset_id: str | None = None,
        asset_id: str | None = None,
    ) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_source_assets (
                  id, project_id, pipeline_run_id, import_job_id, crawl_job_id, asset_type, status, source_uri,
                  object_uri, title, content_type, content_hash, byte_size, market_code,
                  locale, city, metadata, created_by, filename, parser_engine, parser_version,
                  precheck_result, duplicate_of_asset_id
                ) VALUES (COALESCE(%s::uuid, uuid_generate_v4()), %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, 'uploaded', %s,
                          %s, %s, %s, %s, %s, %s,
                          %s, %s, %s::jsonb, %s, %s, %s, %s,
                          %s::jsonb, %s::uuid)
                ON CONFLICT (id) DO UPDATE SET updated_at = knowledge_source_assets.updated_at
                RETURNING *
                """,
                (
                    asset_id,
                    project_id,
                    pipeline_run_id,
                    import_job_id,
                    crawl_job_id,
                    asset_type,
                    source_uri,
                    stored.uri,
                    title,
                    stored.content_type,
                    stored.content_hash,
                    int((metadata or {}).get("byte_size") or 0),
                    market_code,
                    locale,
                    city,
                    json.dumps({"object_store_key": stored.key, "etag": stored.etag, **dict(metadata or {})}, ensure_ascii=False),
                    created_by,
                    filename or title,
                    parser_engine,
                    parser_version,
                    json.dumps(precheck_result or {}, ensure_ascii=False),
                    duplicate_of_asset_id,
                ),
            )
            asset = dict(cursor.fetchone() or {})
            self.connection.commit()
            return asset

    def find_source_asset_by_hash(self, *, project_id: str, digest: str) -> dict[str, Any] | None:
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM knowledge_source_assets
                WHERE project_id = %s::uuid AND content_hash = %s
                  AND status NOT IN ('archived', 'rejected', 'failed')
                  AND asset_type IN ('uploaded_file', 'uploaded_csv', 'pasted_text')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (project_id, digest),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def reuse_source_asset(
        self,
        *,
        existing_asset_id: str,
        project_id: str,
        pipeline_run_id: str,
        import_job_id: str,
        title: str,
        created_by: str,
        market_code: str,
        locale: str,
        city: str | None,
        parser_engine: str,
        precheck_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a versioned asset reference without uploading duplicate object bytes."""
        from psycopg.rows import dict_row

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_source_assets (
                  project_id, pipeline_run_id, import_job_id, asset_type, status, source_uri,
                  object_uri, title, content_type, content_hash, byte_size, market_code, locale,
                  city, metadata, created_by, filename, parser_engine, parser_version,
                  precheck_result, duplicate_of_asset_id
                )
                SELECT %s::uuid, %s::uuid, %s::uuid, asset_type, 'uploaded', source_uri,
                       object_uri, %s, content_type, content_hash, byte_size, %s, %s,
                       %s, metadata || %s::jsonb, %s, %s, %s,
                       'geo-parser-adapter-v1', %s::jsonb, id
                FROM knowledge_source_assets
                WHERE id = %s::uuid AND project_id = %s::uuid
                  AND status NOT IN ('archived', 'rejected', 'failed')
                RETURNING *
                """,
                (
                    project_id,
                    pipeline_run_id,
                    import_job_id,
                    title,
                    market_code,
                    locale,
                    city,
                    json.dumps({"reused_object": True, "duplicate_of_asset_id": existing_asset_id}, ensure_ascii=False),
                    created_by,
                    title,
                    parser_engine,
                    json.dumps(precheck_result, ensure_ascii=False),
                    existing_asset_id,
                    project_id,
                ),
            )
            asset = dict(cursor.fetchone() or {})
            if not asset:
                raise ValueError("duplicate knowledge source asset is unavailable for reuse")
            self._record_audit(
                cursor=cursor,
                event_type="knowledge.source_asset_reused",
                project_id=project_id,
                actor_id=created_by,
                target_type="knowledge_source_asset",
                target_id=str(asset["id"]),
                before={"source_asset_id": existing_asset_id},
                after=asset,
                reason="reuse identical source object in a versioned pipeline run",
                method_version="knowledge_source_asset_reuse_v1",
            )
            self.connection.commit()
            return asset

    def create_parser_artifact_asset(
        self,
        *,
        project_id: str,
        pipeline_run_id: str | None,
        import_job_id: str | None,
        source_asset_id: str,
        parser_run_id: str,
        asset_type: str,
        title: str,
        content: str | bytes,
        content_type: str,
        store: S3CompatibleObjectStore | None,
    ) -> dict[str, Any] | None:
        payload = content.encode("utf-8") if isinstance(content, str) else content
        if not payload:
            return None
        from psycopg.rows import dict_row

        object_uri = None
        storage_metadata: dict[str, Any] = {"source_asset_id": source_asset_id, "parser_run_id": parser_run_id}
        if store is not None:
            digest = hashlib.sha256(payload).hexdigest()
            key = "/".join(
                [
                    "knowledge-parser-artifacts",
                    project_id,
                    pipeline_run_id or "manual",
                    parser_run_id,
                    f"{asset_type}-{digest[:12]}",
                ]
            )
            stored = store.put_object(key=key, content=payload, content_type=content_type, expected_hash=digest)
            object_uri = stored.uri
            storage_metadata.update({"object_store_key": stored.key, "etag": stored.etag})
        with self.connection.cursor(row_factory=dict_row) as cursor:
            artifact_id = stable_pipeline_id(
                "parser-artifact", parser_run_id, asset_type, title, hashlib.sha256(payload).hexdigest()
            )
            cursor.execute(
                """
                INSERT INTO knowledge_source_assets (
                  id, project_id, pipeline_run_id, import_job_id, asset_type, status, source_uri,
                  object_uri, title, content_type, content_hash, byte_size, metadata, created_by
                ) VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, 'processed', null,
                          %s, %s, %s, %s, %s, %s::jsonb, 'knowledge-parser-worker')
                ON CONFLICT (id) DO UPDATE SET updated_at = knowledge_source_assets.updated_at
                RETURNING *
                """,
                (
                    artifact_id,
                    project_id,
                    pipeline_run_id,
                    import_job_id,
                    asset_type,
                    object_uri,
                    title,
                    content_type,
                    hashlib.sha256(payload).hexdigest(),
                    len(payload),
                    json.dumps(storage_metadata, ensure_ascii=False),
                ),
            )
            asset = dict(cursor.fetchone() or {})
            self.connection.commit()
            return asset


def connect_knowledge_pipeline_repository(database_url: str | None = None) -> KnowledgePipelineRepository:
    import psycopg

    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    connection = psycopg.connect(url)
    return KnowledgePipelineRepository(connection, database_url=url)


def close_knowledge_repository(repository: KnowledgePipelineRepository) -> None:
    repository.connection.close()
