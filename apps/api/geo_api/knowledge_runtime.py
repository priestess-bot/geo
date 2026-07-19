"""Composition root for the enterprise knowledge application."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy
from geo_core.rag import load_rag_selection


def build_knowledge_application() -> KnowledgeApplication | None:
    database_url = _secret("GEO_DATABASE_URL")
    if not database_url:
        return None
    default = Path(__file__).resolve().parents[3] / "benchmarks/f019/selection.json"
    selection_path = Path(os.getenv("GEO_RAG_SELECTION_FILE", str(default)).strip())
    try:
        selection_content = selection_path.read_bytes()
    except OSError as exc:
        raise RuntimeError("GEO_RAG_SELECTION_FILE cannot be read") from exc
    selection = load_rag_selection(selection_path)
    return KnowledgeApplication(
        database_url,
        question_policy=KnowledgeRagEnqueuePolicy(
            adapter_release=selection.adapter_release,
            selection_manifest_hash=hashlib.sha256(selection_content).hexdigest(),
            configured_model=os.getenv("GEO_RAG_MODEL", "deepseek-v4-flash").strip(),
        ),
    )


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ValueError(f"{name} and {name}_FILE cannot both be configured")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return direct
