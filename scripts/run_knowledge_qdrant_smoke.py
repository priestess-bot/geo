from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from geo_core.knowledge_pipeline import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_QDRANT_COLLECTION,
    QdrantKnowledgeStore,
    deterministic_embedding,
    stable_pipeline_id,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify real Qdrant payload filtering for GEO knowledge chunks.")
    parser.add_argument("--project-id", default="00000000-0000-0000-0000-000000000001")
    parser.add_argument("--other-project-id", default="00000000-0000-0000-0000-000000000002")
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION))
    parser.add_argument("--artifact", default="/tmp/geo-knowledge-qdrant-smoke.json")
    args = parser.parse_args(argv)
    run_id = f"knowledge-qdrant-{uuid4().hex}"
    started_at = datetime.now(UTC)
    store = QdrantKnowledgeStore(collection=args.collection)
    if not store.enabled():
        raise SystemExit("QDRANT_URL is required for knowledge-qdrant-smoke")
    texts = ["KoalaHome offers fast delivery in Sydney.", "BrightNest has showroom pickup.", "Other tenant private chunk."]
    vectors = [deterministic_embedding(text) for text in texts]
    points = []
    for index, (text, vector) in enumerate(zip(texts, vectors, strict=True), start=1):
        project_id = args.project_id if index < 3 else args.other_project_id
        point_id = stable_pipeline_id("qdrant-smoke", project_id, index, text)
        points.append(
            {
                "id": point_id,
                "vector": vector,
                "payload": {
                    "project_id": project_id,
                    "chunk_id": point_id,
                    "pipeline_run_id": run_id,
                    "import_job_id": "smoke",
                    "chunk_job_id": "smoke",
                    "parser_run_id": "smoke",
                    "source_asset_id": "smoke",
                    "market_code": "GLOBAL",
                    "locale": "en",
                    "city": "Test City" if index == 1 else "",
                    "chunk_type": "text",
                    "status": "active" if index != 2 else "disabled",
                    "embedding_status": "embedded",
                    "content_hash": point_id,
                    "chunk_version": 1,
                    "embedding_model": "BAAI/bge-m3",
                    "embedding_model_version": "bge-m3-local-v1",
                    "created_at": started_at.isoformat(),
                },
            }
        )
    store.upsert(points=points, vector_size=len(vectors[0]))
    results = store.search(vector=vectors[0], project_id=args.project_id, limit=10, filters={"city": "Test City"})
    if not results:
        raise SystemExit("Qdrant smoke failed: no results returned")
    payloads = [item.get("payload") or {} for item in results]
    if any(payload.get("project_id") != args.project_id for payload in payloads):
        raise SystemExit("Qdrant smoke failed: cross-project payload leaked")
    if any(payload.get("status") != "active" for payload in payloads):
        raise SystemExit("Qdrant smoke failed: disabled/stale payload returned")
    artifact = {
        "status": "pass",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "result_count": len(results),
        "collection": args.collection,
        "vector_dimension": DEFAULT_EMBEDDING_DIMENSION,
        "project_filter_verified": True,
        "disabled_filter_verified": True,
    }
    Path(args.artifact).write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    store.delete_points(point_ids=[str(point["id"]) for point in points])
    print(json.dumps(artifact, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
