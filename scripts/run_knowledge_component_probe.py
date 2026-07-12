from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from geno_core.knowledge_application import load_deepseek_api_key
from geno_core.knowledge_pipeline import QdrantKnowledgeStore, deterministic_embedding


COMPONENT_MODULES = {
    "docling": "docling.document_converter",
    "mineru": "magic_pdf.pipe.UNIPipe",
    "unstructured": "unstructured.partition.auto",
    "markitdown": "markitdown",
    "tika": "tika",
    "crawl4ai": "crawl4ai",
    "sentence_transformers_bge_m3": "sentence_transformers",
    "playwright": "playwright.sync_api",
}


def _module_probe(module_name: str) -> dict[str, Any]:
    try:
        available = importlib.util.find_spec(module_name) is not None
        return {"status": "pass" if available else "fail", "module": module_name, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "module": module_name, "error": f"{type(exc).__name__}: {exc}"}


def _worker_probe(root: Path, *, compose_project: str, env_file: Path) -> dict[str, Any]:
    script = (
        "import importlib.util,json;"
        f"mods={json.dumps(COMPONENT_MODULES)};"
        "out={};"
        "\nfor k,m in mods.items():\n"
        "    try:\n"
        "        ok=importlib.util.find_spec(m) is not None\n"
        "        out[k]={'status':'pass' if ok else 'fail','module':m,'error':None}\n"
        "    except Exception as exc:\n"
        "        out[k]={'status':'fail','module':m,'error':type(exc).__name__+': '+str(exc)}\n"
        "print(json.dumps(out, ensure_ascii=False))"
    )
    command = [
        "docker",
        "compose",
        "-p",
        compose_project,
        "--env-file",
        str(env_file),
        "-f",
        str(root / "infra/docker-compose.yml"),
        "--profile",
        "knowledge",
        "exec",
        "-T",
        "knowledge-worker",
        "python",
        "-c",
        script,
    ]
    completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        return {
            "status": "fail",
            "error": completed.stderr.strip() or completed.stdout.strip() or f"docker compose returned {completed.returncode}",
        }
    try:
        return {"status": "pass", "components": json.loads(completed.stdout)}
    except json.JSONDecodeError as exc:
        return {"status": "fail", "error": f"invalid worker probe json: {exc}", "stdout": completed.stdout}


def _qdrant_probe(url: str, project_id: str | None) -> dict[str, Any]:
    try:
        health = httpx.get(f"{url.rstrip('/')}/collections", timeout=10)
        health.raise_for_status()
        payload: dict[str, Any] = {"status": "pass", "url": url, "collections_status": health.status_code}
        if project_id:
            results = QdrantKnowledgeStore(url=url).search(
                vector=deterministic_embedding("KoalaHome delivery returns"),
                project_id=project_id,
                limit=3,
            )
            payload["project_scoped_result_count"] = len(results)
            if len(results) < 1:
                payload["status"] = "fail"
                payload["error"] = "no project-scoped Qdrant result"
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "url": url, "error": f"{type(exc).__name__}: {exc}"}


def _deepseek_probe() -> dict[str, Any]:
    key = load_deepseek_api_key()
    return {
        "status": "pass" if key else "fail",
        "key_present": bool(key),
        "model": "deepseek-v4-flash",
        "note": "This probe only verifies configured key presence; live E2E verifies extraction success.",
    }


def build_probe(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    host_components = {name: _module_probe(module) for name, module in COMPONENT_MODULES.items()}
    worker = _worker_probe(root, compose_project=args.compose_project, env_file=Path(args.env_file))
    qdrant = _qdrant_probe(args.qdrant_url, args.project_id)
    deepseek = _deepseek_probe()
    required_runtime = {
        "business_pipeline": "verified_by_run_knowledge_pipeline_live_e2e",
        "qdrant": qdrant["status"],
        "deepseek_key": deepseek["status"],
    }
    heavy_components = {
        name: (worker.get("components") or {}).get(name, host_components[name])
        for name in (
            "docling",
            "mineru",
            "unstructured",
            "markitdown",
            "tika",
            "crawl4ai",
            "sentence_transformers_bge_m3",
        )
    }
    status = "pass"
    blockers = []
    if qdrant["status"] != "pass":
        status = "fail"
        blockers.append("qdrant")
    if deepseek["status"] != "pass":
        status = "fail"
        blockers.append("deepseek_key")
    unavailable_heavy = [name for name, result in heavy_components.items() if result.get("status") != "pass"]
    return {
        "status": status,
        "blockers": blockers,
        "runtime_components": required_runtime,
        "heavy_component_status": "pass" if not unavailable_heavy else "incomplete",
        "unavailable_heavy_components": unavailable_heavy,
        "host_components": host_components,
        "worker_probe": worker,
        "qdrant": qdrant,
        "deepseek": deepseek,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe GEO knowledge pipeline component availability.")
    parser.add_argument("--artifact", default="/tmp/geo-knowledge-component-probe.json")
    parser.add_argument("--compose-project", default=os.getenv("GENO_COMPOSE_PROJECT", "geno-auto"))
    parser.add_argument("--env-file", default=os.getenv("GENO_COMPOSE_ENV_FILE", "tmp/docker-compose.auto-ports.env"))
    parser.add_argument("--qdrant-url", default=os.getenv("GENO_QDRANT_PROBE_URL", "http://localhost:18006"))
    parser.add_argument("--project-id", default=os.getenv("GENO_KNOWLEDGE_PROBE_PROJECT_ID", ""))
    args = parser.parse_args(argv)
    probe = build_probe(args)
    Path(args.artifact).write_text(json.dumps(probe, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(probe, ensure_ascii=False))
    return 0 if probe["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
