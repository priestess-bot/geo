from __future__ import annotations

from math import sqrt
from typing import Any


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Vector dimensions must match")
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return round(sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm), 8)


class InMemoryPgVectorStore:
    """VectorStore-compatible projection that mirrors pgvector cosine search semantics."""

    store_id = "vector_store.pgvector.memory"

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, list[float]]] = {}

    def upsert(self, *, collection: str, ids: list[str], vectors: list[list[float]]) -> None:
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors must have the same length")
        collection_vectors = self.collections.setdefault(collection, {})
        for item_id, vector in zip(ids, vectors, strict=True):
            collection_vectors[item_id] = [float(value) for value in vector]

    def search(self, *, collection: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
        scored = [
            {
                "id": item_id,
                "score": _cosine_similarity([float(value) for value in vector], stored_vector),
                "distance": round(1 - _cosine_similarity([float(value) for value in vector], stored_vector), 8),
            }
            for item_id, stored_vector in self.collections.get(collection, {}).items()
        ]
        return sorted(scored, key=lambda item: (-float(item["score"]), str(item["id"])))[:limit]


class InMemoryQdrantVectorStore:
    """VectorStore-compatible projection that mirrors Qdrant collection point search."""

    store_id = "vector_store.qdrant.memory"

    def __init__(self) -> None:
        self.points: dict[str, dict[str, dict[str, Any]]] = {}

    def upsert(self, *, collection: str, ids: list[str], vectors: list[list[float]]) -> None:
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors must have the same length")
        collection_points = self.points.setdefault(collection, {})
        for item_id, vector in zip(ids, vectors, strict=True):
            collection_points[item_id] = {
                "id": item_id,
                "vector": [float(value) for value in vector],
                "payload": {"source_id": item_id},
            }

    def search(self, *, collection: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
        query_vector = [float(value) for value in vector]
        scored = [
            {
                "id": str(point["id"]),
                "score": _cosine_similarity(query_vector, point["vector"]),
                "payload": dict(point["payload"]),
            }
            for point in self.points.get(collection, {}).values()
        ]
        return sorted(scored, key=lambda item: (-float(item["score"]), str(item["id"])))[:limit]


def summarize_vector_search(
    store: Any,
    *,
    collection: str,
    vector: list[float],
    limit: int,
) -> tuple[tuple[str, float], ...]:
    return tuple(
        (str(item["id"]), round(float(item["score"]), 6))
        for item in store.search(collection=collection, vector=vector, limit=limit)
    )
