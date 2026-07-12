from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from geno_core.knowledge_pipeline import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_MODEL_VERSION,
    LocalBgeM3Embedder,
)
from geno_core.runtime import validate_runtime_schema_compatibility


app = FastAPI(title="GEO Knowledge Embedding API", version="1.0.0")
_embedder: LocalBgeM3Embedder | None = None


@app.on_event("startup")
def validate_schema_compatibility_on_startup() -> None:
    validate_runtime_schema_compatibility()


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=32)


def _model() -> LocalBgeM3Embedder:
    global _embedder
    if _embedder is None:
        _embedder = LocalBgeM3Embedder(
            os.getenv("GEO_BGE_M3_MODEL") or DEFAULT_EMBEDDING_MODEL,
            allow_deterministic_fallback=False,
        )
    return _embedder


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": os.getenv("GEO_BGE_M3_MODEL") or DEFAULT_EMBEDDING_MODEL,
        "model_version": DEFAULT_EMBEDDING_MODEL_VERSION,
        "dimensions": DEFAULT_EMBEDDING_DIMENSION,
    }


@app.post("/v1/embeddings")
def embeddings(payload: EmbeddingRequest) -> dict[str, Any]:
    texts = [text.strip() for text in payload.texts]
    if any(not text for text in texts):
        raise HTTPException(status_code=400, detail="embedding texts must not be empty")
    try:
        embedder = _model()
        vectors = embedder.embed(texts)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if any(len(vector) != DEFAULT_EMBEDDING_DIMENSION for vector in vectors):
        raise HTTPException(status_code=500, detail="BGE-M3 returned an unexpected vector dimension")
    if "deterministic" in embedder.last_backend:
        raise HTTPException(status_code=500, detail="deterministic embedding fallback is forbidden")
    return {
        "model": DEFAULT_EMBEDDING_MODEL,
        "model_version": DEFAULT_EMBEDDING_MODEL_VERSION,
        "dimensions": DEFAULT_EMBEDDING_DIMENSION,
        "backend": embedder.last_backend,
        "vectors": vectors,
    }
