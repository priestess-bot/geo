from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.sax.saxutils import escape

import httpx

from geno_core.knowledge_pipeline import DEFAULT_EMBEDDING_DIMENSION, DEFAULT_QDRANT_COLLECTION


ACTOR_ID = "runtime-console"


def _request(method: str, url: str, *, headers: dict[str, str], expected: set[int] | None = None, **kwargs: Any) -> dict[str, Any]:
    response = httpx.request(method, url, headers=headers, timeout=90, **kwargs)
    try:
        payload = response.json()
    except Exception:
        payload = {"text": response.text}
    accepted = expected or {200}
    if response.status_code not in accepted:
        raise RuntimeError(f"{method} {url} failed: {response.status_code} {payload}")
    return dict(payload)


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records")
    return [dict(record) for record in records] if isinstance(records, list) else []


def _trace_reaches_source_asset(trace_refs: list[dict[str, Any]], *, target_type: str, target_id: str) -> bool:
    reverse: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for ref in trace_refs:
        target = (str(ref.get("target_type") or ""), str(ref.get("target_id") or ""))
        source = (str(ref.get("source_type") or ""), str(ref.get("source_id") or ""))
        reverse.setdefault(target, []).append(source)
    queue = [(target_type, target_id)]
    seen: set[tuple[str, str]] = set()
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        if current[0] == "source_asset":
            return True
        queue.extend(reverse.get(current, []))
    return False


def _wait_api(base_url: str, *, headers: dict[str, str]) -> None:
    deadline = time.time() + 90
    last_error = ""
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", headers=headers, timeout=5)
            if response.status_code == 200:
                return
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"API did not become ready: {last_error}")


def _compose_command(root: Path, args: argparse.Namespace) -> list[str]:
    command = ["docker", "compose", "-p", args.compose_project]
    env_file = root / args.compose_env_file
    if env_file.exists():
        command.extend(["--env-file", str(env_file)])
    command.extend(["-f", str(root / "infra/docker-compose.yml"), "--profile", "knowledge"])
    return command


def _run_worker_once(root: Path, args: argparse.Namespace, *, max_jobs: int = 50) -> dict[str, Any]:
    command = [
        *_compose_command(root, args),
        "run",
        "--rm",
        "--no-deps",
        "knowledge-worker",
        "python",
        "workers/knowledge_worker/run_knowledge_pipeline.py",
        "--max-jobs",
        str(max_jobs),
        "--loop-once",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
        timeout=args.worker_timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"knowledge worker failed:\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    for line in reversed(completed.stdout.splitlines()):
        try:
            payload = json.loads(line.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("worker"):
            return payload
    raise RuntimeError(f"knowledge worker returned no JSON result: {completed.stdout[-2000:]}")


def _worker_model_statuses(worker_runs: list[dict[str, Any]]) -> list[str]:
    statuses: list[str] = []
    for worker_run in worker_runs:
        for record in worker_run.get("processed") or []:
            if isinstance(record, dict):
                result = record.get("result") if isinstance(record.get("result"), dict) else {}
                status = str(result.get("model_status") or "")
                if status:
                    statuses.append(status)
    return statuses


def _qdrant_project_points(qdrant_url: str, collection: str, project_id: str) -> tuple[int, list[dict[str, Any]]]:
    collection_response = httpx.get(f"{qdrant_url}/collections/{collection}", timeout=20)
    collection_response.raise_for_status()
    result = collection_response.json().get("result") or {}
    vectors = ((result.get("config") or {}).get("params") or {}).get("vectors") or {}
    dimension = int(vectors.get("size") or 0)
    scroll_response = httpx.post(
        f"{qdrant_url}/collections/{collection}/points/scroll",
        json={
            "limit": 100,
            "with_payload": True,
            "with_vector": False,
            "filter": {"must": [{"key": "project_id", "match": {"value": project_id}}]},
        },
        timeout=30,
    )
    scroll_response.raise_for_status()
    points = list((scroll_response.json().get("result") or {}).get("points") or [])
    return dimension, points


def _create_project(api_base: str, headers: dict[str, str], unique: str) -> tuple[str, dict[str, Any]]:
    brand = f"KnowledgeFlow{unique}"
    payload = {
        "tenant_name": f"Knowledge E2E Tenant {unique}",
        "project_name": f"{brand} GEO Production",
        "target_brand": brand,
        "category": "Home wellness products",
        "market_code": "AU",
        "market_name": "Australia",
        "locale": "en-AU",
        "timezone": "Australia/Sydney",
        "currency": "AUD",
        "primary_language": "English",
        "cities": ["Sydney"],
        "industry_code": "dtc_ecommerce",
        "industry_name": "DTC / e-commerce",
        "prompt_version": "knowledge_e2e_v1",
        "score_formula_version": "visibility_v1.0",
        "competitors": ["BrightNest"],
        "brand_official_domains": [f"{brand.lower()}.example.com"],
        "brand_product_lines": ["Modular sofa"],
        "owner_user_id": ACTOR_ID,
        "customer_email": f"knowledge-{unique}@example.com",
        "competitor_domains": ["brightnest.example.com"],
        "collection_mode": "manual",
        "schedule": {"frequency": "manual", "timezone": "Australia/Sydney"},
        "external_connectors": {"deepseek": {"enabled": True, "model": "deepseek-v4-flash"}},
        "create_customer_invitation": False,
    }
    response = _request("POST", f"{api_base}/v1/projects/runtime", headers=headers, json=payload)
    project_id = str(response.get("project_id") or "")
    if not project_id:
        raise RuntimeError(f"project create response missing id: {response}")
    return project_id, payload


def _create_pipeline(
    api_base: str,
    headers: dict[str, str],
    *,
    project_id: str,
    entry_source: str,
    run_id: str,
) -> str:
    response = _request(
        "POST",
        f"{api_base}/v1/knowledge/pipeline-runs/runtime",
        headers=headers,
        json={
            "project_id": project_id,
            "run_type": "full_ingestion",
            "entry_source": entry_source,
            "market_code": "AU",
            "locale": "en-AU",
            "city": "Sydney",
            "created_by": ACTOR_ID,
            "metadata": {"created_from": "knowledge_live_e2e", "run_id": run_id},
        },
    )
    pipeline_run_id = str((response.get("knowledge_pipeline_run") or {}).get("id") or "")
    if not pipeline_run_id:
        raise RuntimeError("knowledge pipeline create response missing id")
    return pipeline_run_id


def _create_import_job(
    api_base: str,
    headers: dict[str, str],
    *,
    project_id: str,
    pipeline_run_id: str,
    source_mode: str,
    source_config: dict[str, Any],
) -> str:
    response = _request(
        "POST",
        f"{api_base}/v1/knowledge/import-jobs/runtime",
        headers=headers,
        json={
            "project_id": project_id,
            "pipeline_run_id": pipeline_run_id,
            "source_mode": source_mode,
            "requested_by": ACTOR_ID,
            "source_config": source_config,
            "priority": 100,
        },
    )
    import_job_id = str((response.get("knowledge_import_job") or {}).get("id") or "")
    if not import_job_id:
        raise RuntimeError("knowledge import job create response missing id")
    return import_job_id


def _minimal_pdf(text: str) -> bytes:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    operators = ["BT", "/F1 11 Tf", "72 760 Td", "14 TL"]
    for index, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if index:
            operators.append("T*")
        operators.append(f"({escaped}) Tj")
    operators.append("ET")
    stream = "\n".join(operators).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _minimal_docx(paragraphs: list[str]) -> bytes:
    document_xml = "".join(f"<w:p><w:r><w:t>{escape(value)}</w:t></w:r></w:p>" for value in paragraphs)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{document_xml}<w:sectPr/></w:body></w:document>",
        )
    return stream.getvalue()


def _review_facts(
    api_base: str,
    headers: dict[str, str],
    project_id: str,
    candidates: list[dict[str, Any]],
    *,
    preferred_subject: str,
) -> str:
    if not candidates:
        raise RuntimeError("no fact candidates available for review")
    approved_index = next(
        (
            index
            for index, candidate in enumerate(candidates)
            if str(candidate.get("fact_kind") or "") == "brand"
            and str(candidate.get("subject") or "").casefold() == preferred_subject.casefold()
        ),
        0,
    )
    approved_id = str(candidates[approved_index]["id"])
    for index, candidate in enumerate(candidates):
        _request(
            "PATCH",
            f"{api_base}/v1/knowledge/fact-candidates/runtime/{candidate['id']}/review",
            headers=headers,
            json={
                "project_id": project_id,
                "review_status": "approved" if index == approved_index else "rejected",
                "reviewed_by": ACTOR_ID,
                "decision": "knowledge live E2E review",
                "notes": "Approve one source-backed fact and resolve the remaining review queue.",
            },
        )
    return approved_id


def _review_and_import_prompts(
    api_base: str,
    headers: dict[str, str],
    project_id: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        raise RuntimeError("no Prompt candidates available for review")
    approved_id = str(candidates[0]["id"])
    for index, candidate in enumerate(candidates):
        _request(
            "PATCH",
            f"{api_base}/v1/knowledge/prompt-candidates/runtime/{candidate['id']}/review",
            headers=headers,
            json={
                "project_id": project_id,
                "review_status": "approved" if index == 0 else "rejected",
                "reviewed_by": ACTOR_ID,
                "decision": "knowledge live E2E Prompt review",
            },
        )
    return _request(
        "POST",
        f"{api_base}/v1/knowledge/prompt-candidates/runtime/import-approved",
        headers=headers,
        json={
            "project_id": project_id,
            "imported_by": ACTOR_ID,
            "prompt_candidate_ids": [approved_id],
            "prompt_version": "knowledge_live_e2e_v1",
        },
    )


def _review_content(
    api_base: str,
    headers: dict[str, str],
    project_id: str,
    drafts: list[dict[str, Any]],
    *,
    review_status: str = "approved",
) -> None:
    if not drafts:
        raise RuntimeError("no content drafts available for review")
    for draft in drafts:
        _request(
            "PATCH",
            f"{api_base}/v1/knowledge/content-drafts/runtime/{draft['id']}/review",
            headers=headers,
            json={
                "project_id": project_id,
                "review_status": review_status,
                "reviewer_id": ACTOR_ID,
                "decision": f"knowledge live E2E content review: {review_status}",
            },
        )


def _start_rerun(
    api_base: str,
    headers: dict[str, str],
    *,
    project_id: str,
    run_type: str,
    source_pipeline_run_id: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    response = _request(
        "POST",
        f"{api_base}/v1/knowledge/pipeline-runs/runtime",
        headers=headers,
        json={
            "project_id": project_id,
            "run_type": run_type,
            "entry_source": "mixed",
            "market_code": "AU",
            "locale": "en-AU",
            "city": "Sydney",
            "created_by": ACTOR_ID,
            "metadata": {"source_pipeline_run_id": source_pipeline_run_id, **(metadata or {})},
        },
    )
    pipeline_run_id = str((response.get("knowledge_pipeline_run") or {}).get("id") or "")
    _request(
        "POST",
        f"{api_base}/v1/knowledge/pipeline-runs/runtime/{pipeline_run_id}/start",
        headers=headers,
        params={"project_id": project_id},
    )
    return pipeline_run_id


def _pipeline_detail(api_base: str, headers: dict[str, str], project_id: str, pipeline_run_id: str) -> dict[str, Any]:
    return dict(
        _request(
            "GET",
            f"{api_base}/v1/knowledge/pipeline-runs/runtime/{pipeline_run_id}",
            headers=headers,
            params={"project_id": project_id},
        ).get("knowledge_pipeline_run")
        or {}
    )


def _pipeline_jobs(api_base: str, headers: dict[str, str], project_id: str, pipeline_run_id: str) -> dict[str, Any]:
    return _request(
        "GET",
        f"{api_base}/v1/knowledge/pipeline-runs/runtime/{pipeline_run_id}/jobs",
        headers=headers,
        params={"project_id": project_id, "limit": 100},
    )


def _run_worker_until_pipeline_ready(
    root: Path,
    args: argparse.Namespace,
    *,
    headers: dict[str, str],
    project_id: str,
    pipeline_run_id: str,
    accepted_statuses: set[str],
    max_jobs: int,
    max_passes: int = 30,
) -> list[dict[str, Any]]:
    worker_runs: list[dict[str, Any]] = []
    pending_statuses = {"draft", "ready", "queued", "running", "retrying"}
    for _ in range(max_passes):
        worker_runs.append(_run_worker_once(root, args, max_jobs=max_jobs))
        detail = _pipeline_detail(args.api_base, headers, project_id, pipeline_run_id)
        status = str(detail.get("status") or "")
        if status in {"failed", "cancelled"}:
            raise RuntimeError(f"pipeline {pipeline_run_id} entered terminal status {status}")
        jobs = _pipeline_jobs(args.api_base, headers, project_id, pipeline_run_id)
        pending_count = sum(
            1
            for page in (jobs.get("job_groups") or {}).values()
            for record in _records(dict(page or {}))
            if str(record.get("status") or "") in pending_statuses
        )
        if status in accepted_statuses and pending_count == 0:
            return worker_runs
        time.sleep(5)
    detail = _pipeline_detail(args.api_base, headers, project_id, pipeline_run_id)
    jobs = _pipeline_jobs(args.api_base, headers, project_id, pipeline_run_id)
    job_statuses = {
        table: {
            str(status): sum(
                1 for record in _records(dict(page or {})) if str(record.get("status") or "") == str(status)
            )
            for status in sorted({str(record.get("status") or "") for record in _records(dict(page or {}))})
        }
        for table, page in (jobs.get("job_groups") or {}).items()
        if _records(dict(page or {}))
    }
    raise RuntimeError(
        f"pipeline {pipeline_run_id} did not settle after {max_passes} worker passes: "
        f"run_type={detail.get('run_type')} status={detail.get('status')} "
        f"failed_step={detail.get('failed_step')} job_statuses={job_statuses}"
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    headers = {"X-GENO-Actor-Id": ACTOR_ID}
    _wait_api(args.api_base, headers=headers)
    run_id = f"knowledge-live-{uuid4().hex}"
    started_at = datetime.now(UTC)
    unique = uuid4().hex[:10]
    project_id, project_payload = _create_project(args.api_base, headers, unique)

    pipeline_run_id = _create_pipeline(
        args.api_base,
        headers,
        project_id=project_id,
        entry_source="file",
        run_id=run_id,
    )
    import_job_id = _create_import_job(
        args.api_base,
        headers,
        project_id=project_id,
        pipeline_run_id=pipeline_run_id,
        source_mode="file",
        source_config={"adapter_engine": "auto", "title": "Knowledge live E2E multi-format batch"},
    )
    markdown_content = (
        f"# {project_payload['target_brand']} product policy\n\n"
        f"{project_payload['target_brand']} offers modular sofas with free Sydney metro delivery over AUD 99.\n\n"
        "Customers may return unused products within 30 days under the published returns policy.\n\n"
        "| Policy | Value |\n| --- | --- |\n| Delivery | Free over AUD 99 |\n| Returns | 30 days |\n"
    ).encode("utf-8")
    fixtures = [
        (f"knowledge-{unique}.md", markdown_content, "text/markdown", "markitdown"),
        (
            f"brand-policy-{unique}.pdf",
            _minimal_pdf(
                f"{project_payload['target_brand']} official brand guide\n"
                "Sydney delivery is free over AUD 99\nReturns are accepted within 30 days"
            ),
            "application/pdf",
            "docling",
        ),
        (
            f"scanned-market-{unique}.pdf",
            _minimal_pdf(
                f"{project_payload['target_brand']} market evidence\n"
                "Australian customers compare delivery, returns, warranty and service evidence"
            ),
            "application/pdf",
            "mineru",
        ),
        (
            f"competitor-notes-{unique}.docx",
            _minimal_docx(
                [
                    f"{project_payload['target_brand']} and BrightNest are compared for modular sofa delivery.",
                    "BrightNest charges delivery in selected Sydney suburbs.",
                ]
            ),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "mineru",
        ),
        (
            f"market-facts-{unique}.csv",
            (
                "fact_type,subject,predicate,object_value,market_code\n"
                f"policy,{project_payload['target_brand']},delivery,Free over AUD 99,AU\n"
                f"policy,{project_payload['target_brand']},returns,30 days,AU\n"
            ).encode("utf-8"),
            "text/csv",
            "markitdown",
        ),
    ]
    upload_responses: list[dict[str, Any]] = []
    for filename, content, content_type, adapter_engine in fixtures:
        upload_responses.append(
            _request(
                "POST",
                f"{args.api_base}/v1/knowledge/import-jobs/runtime/{import_job_id}/files",
                headers=headers,
                files={"file": (filename, content, content_type)},
                data={
                    "project_id": project_id,
                    "pipeline_run_id": pipeline_run_id,
                    "market_code": project_payload["market_code"],
                    "locale": project_payload["locale"],
                    "city": "Sydney",
                    "adapter_engine": adapter_engine,
                    "defer_start": "1",
                },
            )
        )
    duplicate_filename, duplicate_content, duplicate_content_type, duplicate_adapter = fixtures[0]
    duplicate_upload_response = _request(
        "POST",
        f"{args.api_base}/v1/knowledge/import-jobs/runtime/{import_job_id}/files",
        headers=headers,
        files={"file": (duplicate_filename, duplicate_content, duplicate_content_type)},
        data={
            "project_id": project_id,
            "pipeline_run_id": pipeline_run_id,
            "market_code": project_payload["market_code"],
            "locale": project_payload["locale"],
            "city": "Sydney",
            "adapter_engine": duplicate_adapter,
            "defer_start": "1",
        },
    )

    source_contract_details: dict[str, dict[str, Any]] = {}
    for source_mode, entry_source, source_config in (
        (
            "pasted_text",
            "text",
            {
                "pasted_text": f"{project_payload['target_brand']} provides source-backed support in Sydney.",
                "market_code": "AU",
                "locale": "en-AU",
            },
        ),
        (
            "csv",
            "csv",
            {
                "csv_content": "subject,predicate,object_value\nKnowledgeFlow,warranty,5 years\n",
                "market_code": "AU",
                "locale": "en-AU",
            },
        ),
    ):
        source_pipeline_run_id = _create_pipeline(
            args.api_base,
            headers,
            project_id=project_id,
            entry_source=entry_source,
            run_id=f"{run_id}-{source_mode}-contract",
        )
        source_import_job_id = _create_import_job(
            args.api_base,
            headers,
            project_id=project_id,
            pipeline_run_id=source_pipeline_run_id,
            source_mode=source_mode,
            source_config=source_config,
        )
        source_contract_details[source_mode] = _request(
            "GET",
            f"{args.api_base}/v1/knowledge/import-jobs/runtime/{source_import_job_id}",
            headers=headers,
            params={"project_id": project_id},
        )
    _request(
        "POST",
        f"{args.api_base}/v1/knowledge/pipeline-runs/runtime/{pipeline_run_id}/start",
        headers=headers,
        params={"project_id": project_id},
    )

    worker_runs = _run_worker_until_pipeline_ready(
        root,
        args,
        headers=headers,
        project_id=project_id,
        pipeline_run_id=pipeline_run_id,
        accepted_statuses={"waiting_human_review", "succeeded", "partial_succeeded"},
        max_jobs=100,
    )
    fact_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/fact-candidates/runtime",
        headers=headers,
        params={"project_id": project_id, "limit": 100},
    )
    fact_candidates = _records(fact_page)
    first_fact = fact_candidates[0] if fact_candidates else {}
    filtered_fact_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/fact-candidates/runtime",
        headers=headers,
        params={
            "project_id": project_id,
            "pipeline_run_id": pipeline_run_id,
            "fact_kind": first_fact.get("fact_kind") or "brand",
            "status": "pending_review",
            "limit": 100,
        },
    )
    approved_fact_candidate_id = _review_facts(
        args.api_base,
        headers,
        project_id,
        fact_candidates,
        preferred_subject=project_payload["target_brand"],
    )

    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=pipeline_run_id,
            accepted_statuses={"waiting_human_review", "succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    prompt_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/prompt-candidates/runtime",
        headers=headers,
        params={"project_id": project_id, "limit": 100},
    )
    content_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/content-drafts/runtime",
        headers=headers,
        params={"project_id": project_id, "limit": 100},
    )
    prompt_candidates = _records(prompt_page)
    content_drafts = _records(content_page)
    first_prompt_candidate = prompt_candidates[0] if prompt_candidates else {}
    filtered_prompt_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/prompt-candidates/runtime",
        headers=headers,
        params={
            "project_id": project_id,
            "pipeline_run_id": first_prompt_candidate.get("pipeline_run_id") or pipeline_run_id,
            "target_platform": first_prompt_candidate.get("target_platform") or "chatgpt",
            "status": "pending_review",
            "limit": 100,
        },
    )
    first_content_draft = content_drafts[0] if content_drafts else {}
    filtered_content_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/content-drafts/runtime",
        headers=headers,
        params={
            "project_id": project_id,
            "pipeline_run_id": first_content_draft.get("pipeline_run_id") or pipeline_run_id,
            "content_type": first_content_draft.get("content_type") or "faq",
            "status": "pending_human_review",
            "limit": 100,
        },
    )
    if prompt_candidates:
        pending_prompt_import = httpx.post(
            f"{args.api_base}/v1/knowledge/prompt-candidates/runtime/import-approved",
            headers=headers,
            json={
                "project_id": project_id,
                "imported_by": ACTOR_ID,
                "prompt_candidate_ids": [str(prompt_candidates[0]["id"])],
                "prompt_version": "knowledge_pending_negative_v1",
            },
            timeout=30,
        )
        if pending_prompt_import.status_code not in {400, 409, 422}:
            raise RuntimeError(
                f"pending Prompt candidate import was not blocked: HTTP {pending_prompt_import.status_code}"
            )
    if content_drafts:
        pending_export = httpx.post(
            f"{args.api_base}/v1/knowledge/content-drafts/runtime/{content_drafts[0]['id']}/export.md",
            headers=headers,
            params={"project_id": project_id},
            timeout=30,
        )
        if pending_export.status_code not in {400, 409, 422}:
            raise RuntimeError(f"pending content export was not blocked: HTTP {pending_export.status_code}")
    prompt_import = _review_and_import_prompts(args.api_base, headers, project_id, prompt_candidates)
    _review_content(args.api_base, headers, project_id, content_drafts)
    reviewed_prompt_candidates = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/prompt-candidates/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 100},
        )
    )
    exported_content = None
    if content_drafts:
        exported_content = _request(
            "POST",
            f"{args.api_base}/v1/knowledge/content-drafts/runtime/{content_drafts[0]['id']}/export.md",
            headers=headers,
            params={"project_id": project_id},
        )

    pipeline_detail_payload = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/pipeline-runs/runtime/{pipeline_run_id}",
        headers=headers,
        params={"project_id": project_id},
    )
    pipeline_detail = pipeline_detail_payload.get("knowledge_pipeline_run") or {}
    import_detail_payload = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/import-jobs/runtime/{import_job_id}",
        headers=headers,
        params={"project_id": project_id},
    )
    stages = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/pipeline-runs/runtime/{pipeline_run_id}/stages",
            headers=headers,
            params={"project_id": project_id},
        )
    )
    jobs_payload = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/pipeline-runs/runtime/{pipeline_run_id}/jobs",
        headers=headers,
        params={"project_id": project_id, "limit": 100},
    )
    chunks = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/chunks/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 100},
        )
    )
    source_assets = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/source-assets/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    parser_runs = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/parser-runs/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 100},
        )
    )
    parser_blocks = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/blocks/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    parser_tables = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/tables/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 100},
        )
    )
    page_snapshots = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/page-snapshots/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 100},
        )
    )
    quality_gates = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/quality-gate-runs/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 100},
        )
    )
    trace_refs = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/trace-refs/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    audit_page = _request(
        "GET",
        f"{args.api_base}/v1/audit-events/runtime",
        headers=headers,
        params={"project_id": project_id, "limit": 200},
    )
    prompts = _request(
        "GET",
        f"{args.api_base}/v1/prompts/runtime",
        headers=headers,
        params={"project_id": project_id, "limit": 100, "offset": 0},
    )
    dimension, qdrant_points = _qdrant_project_points(args.qdrant_url, args.qdrant_collection, project_id)

    filtered_pipeline_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/pipeline-runs/runtime",
        headers=headers,
        params={
            "project_id": project_id,
            "run_type": pipeline_detail.get("run_type") or "full_ingestion",
            "status": pipeline_detail.get("status") or "succeeded",
            "entry_source": pipeline_detail.get("entry_source") or "file",
            "limit": 100,
        },
    )
    import_record = import_detail_payload.get("knowledge_import_job") or {}
    filtered_import_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/import-jobs/runtime",
        headers=headers,
        params={
            "project_id": project_id,
            "status": import_record.get("status") or "succeeded",
            "source_mode": import_record.get("source_mode") or "file",
            "limit": 100,
        },
    )
    filter_chunk = next((chunk for chunk in chunks if "delivery" in str(chunk.get("text") or "").lower()), chunks[0] if chunks else {})
    filtered_chunk_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/chunks/runtime",
        headers=headers,
        params={
            "project_id": project_id,
            "source_asset_id": filter_chunk.get("source_asset_id"),
            "status": filter_chunk.get("status") or "active",
            "embedding_status": filter_chunk.get("embedding_status") or "embedded",
            "chunk_type": filter_chunk.get("chunk_type") or "text",
            "query": "delivery",
            "limit": 100,
        },
    )
    first_gate = quality_gates[0] if quality_gates else {}
    filtered_gate_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/quality-gate-runs/runtime",
        headers=headers,
        params={
            "project_id": project_id,
            "pipeline_run_id": pipeline_run_id,
            "gate_key": first_gate.get("gate_key"),
            "status": first_gate.get("status"),
            "limit": 100,
        },
    )
    first_trace = trace_refs[0] if trace_refs else {}
    filtered_trace_page = _request(
        "GET",
        f"{args.api_base}/v1/knowledge/trace-refs/runtime",
        headers=headers,
        params={
            "project_id": project_id,
            "pipeline_run_id": pipeline_run_id,
            "target_type": first_trace.get("target_type"),
            "target_id": first_trace.get("target_id"),
            "limit": 100,
        },
    )

    job_groups = jobs_payload.get("job_groups") if isinstance(jobs_payload.get("job_groups"), dict) else {}
    all_jobs = [record for group in job_groups.values() if isinstance(group, dict) for record in _records(group)]
    model_statuses = _worker_model_statuses(worker_runs)
    failures: list[str] = []
    duplicate_asset = duplicate_upload_response.get("knowledge_source_asset") or {}
    original_asset = (upload_responses[0].get("knowledge_source_asset") or {}) if upload_responses else {}

    def page_has_id(page: dict[str, Any], record_id: object) -> bool:
        expected_id = str(record_id or "")
        return bool(expected_id) and any(str(record.get("id") or "") == expected_id for record in _records(page))

    source_prechecks_passed = all(
        bool(
            (((detail.get("knowledge_import_job") or {}).get("result_summary") or {}).get("precheck") or {}).get(
                "accepted"
            )
        )
        for detail in source_contract_details.values()
    )
    operational_checks = [
        {
            "name": "duplicate file reuses stored object with a versioned asset",
            "passed": bool(
                duplicate_asset.get("id")
                and duplicate_asset.get("id") != original_asset.get("id")
                and str(duplicate_asset.get("duplicate_of_asset_id") or "") == str(original_asset.get("id") or "")
                and duplicate_asset.get("object_uri") == original_asset.get("object_uri")
            ),
        },
        {"name": "pasted_text and csv_content direct API prechecks pass", "passed": source_prechecks_passed},
        {
            "name": "pipeline detail aggregates stages jobs assets chunks gates candidates summaries and audit",
            "passed": {
                "stages", "jobs", "source_assets", "parser_runs", "chunks", "quality_gate_runs",
                "fact_candidates", "prompt_candidates", "content_drafts", "summaries", "audit_events",
            }.issubset(pipeline_detail_payload),
        },
        {
            "name": "import detail aggregates assets parsers chunks findings facts summaries and audit",
            "passed": {
                "source_assets", "parser_runs", "chunks", "quality_findings", "fact_candidates",
                "summaries", "audit_events",
            }.issubset(import_detail_payload),
        },
        {"name": "pipeline list filters return the requested run", "passed": page_has_id(filtered_pipeline_page, pipeline_run_id)},
        {"name": "import list filters return the requested job", "passed": page_has_id(filtered_import_page, import_job_id)},
        {"name": "chunk source/status/type/text filters return the requested chunk", "passed": page_has_id(filtered_chunk_page, filter_chunk.get("id"))},
        {"name": "fact candidate filters return the requested candidate", "passed": page_has_id(filtered_fact_page, first_fact.get("id"))},
        {"name": "Prompt candidate filters return the requested candidate", "passed": page_has_id(filtered_prompt_page, first_prompt_candidate.get("id"))},
        {"name": "content draft filters return the requested draft", "passed": page_has_id(filtered_content_page, first_content_draft.get("id"))},
        {"name": "quality gate filters return the requested gate", "passed": page_has_id(filtered_gate_page, first_gate.get("id"))},
        {"name": "trace filters return the requested trace", "passed": page_has_id(filtered_trace_page, first_trace.get("id"))},
    ]
    failures.extend(
        f"operational contract failed: {check['name']}"
        for check in operational_checks
        if not check["passed"]
    )
    if str(pipeline_detail.get("status")) != "succeeded":
        failures.append(f"pipeline status is {pipeline_detail.get('status')}, expected succeeded")
    if not chunks or any(str(chunk.get("embedding_status")) != "embedded" for chunk in chunks):
        failures.append("active chunks were not fully embedded")
    if dimension != DEFAULT_EMBEDDING_DIMENSION:
        failures.append(f"Qdrant dimension is {dimension}, expected {DEFAULT_EMBEDDING_DIMENSION}")
    if not qdrant_points:
        failures.append("Qdrant has no project-scoped points")
    if any((point.get("payload") or {}).get("embedding_backend") == "deterministic-test-fallback" for point in qdrant_points):
        failures.append("production knowledge flow used deterministic embedding fallback")
    if not model_statuses or any(status != "deepseek_succeeded" for status in model_statuses):
        failures.append(f"knowledge model execution was not fully real DeepSeek: {model_statuses}")
    if len(quality_gates) < 7 or any(str(gate.get("status")) in {"blocked", "failed"} for gate in quality_gates):
        failures.append("knowledge quality gates are incomplete or blocked")
    if not any(str(ref.get("target_type")) == "prompt_candidate" for ref in trace_refs):
        failures.append("Prompt candidate trace is missing")
    if not any(str(ref.get("target_type")) == "content_draft" for ref in trace_refs):
        failures.append("content draft trace is missing")
    for candidate in prompt_candidates[:5]:
        if not _trace_reaches_source_asset(
            trace_refs,
            target_type="prompt_candidate",
            target_id=str(candidate.get("id") or ""),
        ):
            failures.append(f"Prompt candidate {candidate.get('id')} does not trace to a source asset")
    for draft in content_drafts[:5]:
        if not _trace_reaches_source_asset(
            trace_refs,
            target_type="content_draft",
            target_id=str(draft.get("id") or ""),
        ):
            failures.append(f"content draft {draft.get('id')} does not trace to a source asset")
    if int(audit_page.get("total_count") or 0) < 10:
        failures.append("knowledge pipeline audit trail is incomplete")
    expected_job_groups = {
        "knowledge_import_jobs",
        "knowledge_parser_runs",
        "chunk_jobs",
        "embedding_jobs",
        "fact_extraction_jobs",
        "prompt_generation_jobs",
        "content_generation_jobs",
    }
    if not expected_job_groups.issubset(set(job_groups)):
        failures.append("pipeline jobs endpoint did not return every job group")
    if any(
        str(job.get("status")) not in {"succeeded", "partial_succeeded", "fallback_succeeded"}
        for job in all_jobs
    ):
        failures.append("one or more pipeline jobs are not terminal-success")
    if int(prompts.get("total_count") or 0) < 1:
        failures.append("approved Prompt candidate was not imported as an official Prompt")
    if not exported_content or project_payload["target_brand"] not in str(exported_content.get("text") or ""):
        failures.append("approved GEO content draft did not export as source-backed Markdown")
    rejected_prompt_ids = {
        str(candidate.get("id"))
        for candidate in prompt_candidates
        if str(candidate.get("id")) != str(prompt_candidates[0].get("id") if prompt_candidates else "")
    }
    if any(candidate.get("imported_prompt_id") for candidate in reviewed_prompt_candidates if str(candidate.get("id")) in rejected_prompt_ids):
        failures.append("rejected Prompt candidate was imported")
    if not any(str(stage.get("stage_key")) == "trace_verify" and str(stage.get("status")) == "succeeded" for stage in stages):
        failures.append("trace_verify stage did not succeed")
    uploaded_assets = [asset for asset in source_assets if str(asset.get("asset_type")) == "uploaded_file"]
    if len(uploaded_assets) < len(fixtures):
        failures.append(f"multi-format upload persisted {len(uploaded_assets)} assets, expected at least {len(fixtures)}")
    if len(parser_runs) < len(fixtures) or not parser_blocks or not page_snapshots:
        failures.append("multi-format parser output is incomplete")
    if not parser_tables or not any(table.get("csv_asset_id") or table.get("html_asset_id") for table in parser_tables):
        failures.append("table extraction did not persist downloadable CSV/HTML artifacts")
    required_payload_fields = {
        "pipeline_run_id", "chunk_job_id", "parser_run_id", "embedding_model",
        "embedding_model_version", "locale", "content_hash", "chunk_version",
    }
    if any(not required_payload_fields.issubset(set((point.get("payload") or {}).keys())) for point in qdrant_points):
        failures.append("Qdrant payload is missing production version/trace fields")

    approved_facts = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/approved-facts/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 100},
        )
    )
    evidence_chunk_ids = {
        str(chunk_id)
        for fact in approved_facts
        for chunk_id in (fact.get("source_chunk_ids") or [])
    }
    disable_candidate = next(
        (chunk for chunk in chunks if str(chunk.get("id")) not in evidence_chunk_ids),
        None,
    )
    disabled_chunk_id = ""
    search_page: dict[str, Any] = {}
    disabled_search_excluded = False
    if disable_candidate:
        disabled_chunk_id = str(disable_candidate["id"])
        _request(
            "POST",
            f"{args.api_base}/v1/knowledge/chunks/runtime/{disabled_chunk_id}/disable",
            headers=headers,
            json={"project_id": project_id, "reason": "full pipeline disabled-chunk retrieval test"},
        )
        search_page = _request(
            "GET",
            f"{args.api_base}/v1/knowledge/chunks/runtime/search",
            headers=headers,
            params={"project_id": project_id, "query": "delivery returns", "market_code": "AU", "limit": 50},
        )
        search_chunk_ids = {str((record.get("chunk") or {}).get("id")) for record in _records(search_page)}
        disabled_search_excluded = disabled_chunk_id not in search_chunk_ids
        if disabled_chunk_id in search_chunk_ids:
            failures.append("disabled chunk remained visible in production vector search")
    else:
        failures.append("no non-evidence chunk was available for the disabled-chunk search test")

    unauthorized = httpx.get(
        f"{args.api_base}/v1/knowledge/source-assets/runtime",
        headers={"X-GENO-Actor-Id": f"unauthorized-{unique}"},
        params={"project_id": project_id, "limit": 1},
        timeout=30,
    )
    if unauthorized.status_code not in {401, 403, 404}:
        failures.append(f"cross-project actor was not denied: HTTP {unauthorized.status_code}")

    private_pipeline_run_id = _create_pipeline(
        args.api_base,
        headers,
        project_id=project_id,
        entry_source="url",
        run_id=f"{run_id}-private-url-negative",
    )
    private_import_job_id = _create_import_job(
        args.api_base,
        headers,
        project_id=project_id,
        pipeline_run_id=private_pipeline_run_id,
        source_mode="url",
        source_config={"market_code": "AU", "locale": "en-AU"},
    )
    private_url_response = httpx.post(
        f"{args.api_base}/v1/knowledge/import-jobs/runtime/{private_import_job_id}/urls",
        headers=headers,
        json={
            "project_id": project_id,
            "urls": ["http://127.0.0.1:8000/private"],
            "crawl_mode": "single_url",
            "max_pages": 1,
        },
        timeout=30,
    )
    if private_url_response.status_code not in {400, 422}:
        failures.append(f"private URL crawl was not blocked: HTTP {private_url_response.status_code}")

    crawl_pipeline_run_id = _create_pipeline(
        args.api_base,
        headers,
        project_id=project_id,
        entry_source="site",
        run_id=f"{run_id}-crawl",
    )
    crawl_job_ids: list[str] = []
    for source_mode, crawl_mode in (("url", "single_url"), ("site_crawl", "site_depth")):
        crawl_import_job_id = _create_import_job(
            args.api_base,
            headers,
            project_id=project_id,
            pipeline_run_id=crawl_pipeline_run_id,
            source_mode=source_mode,
            source_config={"market_code": "AU", "locale": "en-AU", "city": "Sydney"},
        )
        crawl_job_ids.append(crawl_import_job_id)
        _request(
            "POST",
            f"{args.api_base}/v1/knowledge/import-jobs/runtime/{crawl_import_job_id}/urls",
            headers=headers,
            json={
                "project_id": project_id,
                "urls": ["https://example.com/"],
                "crawl_mode": crawl_mode,
                "crawl_depth": 1 if crawl_mode == "site_depth" else 0,
                "max_pages": 1,
                "include_patterns": [],
                "exclude_patterns": [],
                "respect_robots": True,
            },
        )
    _request(
        "POST",
        f"{args.api_base}/v1/knowledge/pipeline-runs/runtime/{crawl_pipeline_run_id}/start",
        headers=headers,
        params={"project_id": project_id},
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=crawl_pipeline_run_id,
            accepted_statuses={"waiting_human_review", "succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    crawl_assets = [
        asset
        for asset in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/source-assets/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
        if str(asset.get("pipeline_run_id")) == crawl_pipeline_run_id
    ]
    crawl_asset_types = {str(asset.get("asset_type")) for asset in crawl_assets}
    required_crawl_assets = {"crawled_html", "crawled_markdown", "screenshot", "crawl_link_graph"}
    if not required_crawl_assets.issubset(crawl_asset_types):
        failures.append(f"Crawl4AI archive is incomplete: {sorted(crawl_asset_types)}")

    reruns: dict[str, dict[str, Any]] = {}
    primary_parser_ids = {
        str(record.get("id"))
        for record in _records(dict(job_groups.get("knowledge_parser_runs") or {}))
    }
    primary_chunk_ids = {str(chunk.get("id")) for chunk in chunks if str(chunk.get("pipeline_run_id")) == pipeline_run_id}

    reparse_run_id = _start_rerun(
        args.api_base,
        headers,
        project_id=project_id,
        run_type="reparse",
        source_pipeline_run_id=pipeline_run_id,
        metadata={"adapter_engine": "markitdown"},
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=reparse_run_id,
            accepted_statuses={"succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    reparse_jobs = _pipeline_jobs(args.api_base, headers, project_id, reparse_run_id)
    reparse_parser_ids = {
        str(record.get("id"))
        for record in _records(dict((reparse_jobs.get("job_groups") or {}).get("knowledge_parser_runs") or {}))
    }
    reparse_status = str(_pipeline_detail(args.api_base, headers, project_id, reparse_run_id).get("status"))
    reruns["reparse"] = {
        "pipeline_run_id": reparse_run_id,
        "status": reparse_status,
        "parser_run_count": len(reparse_parser_ids),
        "old_parser_runs_preserved": bool(primary_parser_ids and primary_parser_ids.isdisjoint(reparse_parser_ids)),
    }
    if reparse_status != "succeeded" or not reruns["reparse"]["old_parser_runs_preserved"]:
        failures.append("reparse did not preserve old parser runs and finish successfully")

    rechunk_run_id = _start_rerun(
        args.api_base,
        headers,
        project_id=project_id,
        run_type="rechunk",
        source_pipeline_run_id=pipeline_run_id,
        metadata={"chunk_profile_version": "geo_chunk_profile_e2e_v2"},
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=rechunk_run_id,
            accepted_statuses={"succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    chunks_after_rechunk = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/chunks/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    rechunk_chunks = [chunk for chunk in chunks_after_rechunk if str(chunk.get("pipeline_run_id")) == rechunk_run_id]
    old_chunks = [chunk for chunk in chunks_after_rechunk if str(chunk.get("id")) in primary_chunk_ids]
    facts_after_rechunk = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/fact-candidates/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    prompts_after_rechunk = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/prompt-candidates/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    content_after_rechunk = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/content-drafts/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    active_facts_after_rechunk = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/approved-facts/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    previous_fact_ids = {str(candidate.get("id")) for candidate in fact_candidates}
    previous_prompt_ids = {str(candidate.get("id")) for candidate in prompt_candidates}
    previous_content_ids = {str(draft.get("id")) for draft in content_drafts}
    previous_approved_fact_ids = {str(fact.get("id")) for fact in approved_facts}
    invalidated_fact_candidates = [
        candidate
        for candidate in facts_after_rechunk
        if str(candidate.get("id")) in previous_fact_ids and str(candidate.get("status")) == "needs_reextract"
    ]
    invalidated_prompt_candidates = [
        candidate
        for candidate in prompts_after_rechunk
        if str(candidate.get("id")) in previous_prompt_ids and str(candidate.get("review_status")) == "superseded"
    ]
    invalidated_content_drafts = [
        draft
        for draft in content_after_rechunk
        if str(draft.get("id")) in previous_content_ids and str(draft.get("status")) == "needs_revision"
    ]
    current_active_fact_ids = {str(fact.get("id")) for fact in active_facts_after_rechunk}
    version_invalidation_observed = all(
        (
            bool(old_chunks)
            and all(
                str(chunk.get("embedding_status")) == "stale"
                or (str(chunk.get("status")) == "disabled" and str(chunk.get("embedding_status")) == "disabled")
                for chunk in old_chunks
            ),
            bool(invalidated_fact_candidates),
            bool(invalidated_prompt_candidates),
            bool(invalidated_content_drafts),
            bool(previous_approved_fact_ids) and previous_approved_fact_ids.isdisjoint(current_active_fact_ids),
        )
    )
    rechunk_status = str(_pipeline_detail(args.api_base, headers, project_id, rechunk_run_id).get("status"))
    reruns["rechunk"] = {
        "pipeline_run_id": rechunk_run_id,
        "status": rechunk_status,
        "new_chunk_count": len(rechunk_chunks),
        "old_chunks_superseded": bool(
            old_chunks
            and all(
                str(chunk.get("status")) == "superseded"
                or (str(chunk.get("id")) == disabled_chunk_id and str(chunk.get("status")) == "disabled")
                for chunk in old_chunks
            )
        ),
        "new_chunks_embedded": bool(rechunk_chunks and all(str(chunk.get("embedding_status")) == "embedded" for chunk in rechunk_chunks)),
        "old_embeddings_stale": bool(old_chunks)
        and all(
            str(chunk.get("embedding_status")) == "stale"
            or (str(chunk.get("status")) == "disabled" and str(chunk.get("embedding_status")) == "disabled")
            for chunk in old_chunks
        ),
        "fact_candidates_needing_reextract": len(invalidated_fact_candidates),
        "prompt_candidates_superseded": len(invalidated_prompt_candidates),
        "content_drafts_needing_revision": len(invalidated_content_drafts),
        "approved_facts_superseded": previous_approved_fact_ids.isdisjoint(current_active_fact_ids),
        "version_invalidation_observed": version_invalidation_observed,
    }
    if rechunk_status != "succeeded" or not all(
        [
            reruns["rechunk"]["old_chunks_superseded"],
            reruns["rechunk"]["new_chunks_embedded"],
            reruns["rechunk"]["version_invalidation_observed"],
        ]
    ):
        failures.append("rechunk did not supersede/stale dependent outputs and embed the new version")

    text_before_reindex = {str(chunk.get("id")): str(chunk.get("text")) for chunk in rechunk_chunks}
    reindex_run_id = _start_rerun(
        args.api_base,
        headers,
        project_id=project_id,
        run_type="reindex",
        source_pipeline_run_id=rechunk_run_id,
        metadata={"embedding_model_version": "bge-m3-local-v1"},
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=reindex_run_id,
            accepted_statuses={"succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    chunks_after_reindex = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/chunks/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    text_after_reindex = {
        str(chunk.get("id")): str(chunk.get("text"))
        for chunk in chunks_after_reindex
        if str(chunk.get("id")) in text_before_reindex
    }
    reindex_status = str(_pipeline_detail(args.api_base, headers, project_id, reindex_run_id).get("status"))
    reruns["reindex"] = {
        "pipeline_run_id": reindex_run_id,
        "status": reindex_status,
        "chunk_text_unchanged": text_before_reindex == text_after_reindex,
    }
    if reindex_status != "succeeded" or not reruns["reindex"]["chunk_text_unchanged"]:
        failures.append("reindex changed chunk text or did not finish")

    fact_refresh_run_id = _start_rerun(
        args.api_base,
        headers,
        project_id=project_id,
        run_type="fact_refresh",
        source_pipeline_run_id=rechunk_run_id,
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=fact_refresh_run_id,
            accepted_statuses={"waiting_human_review", "succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    refreshed_fact_candidates = [
        candidate
        for candidate in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/fact-candidates/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
        if str(candidate.get("pipeline_run_id")) == fact_refresh_run_id
    ]
    _review_facts(
        args.api_base,
        headers,
        project_id,
        refreshed_fact_candidates,
        preferred_subject=project_payload["target_brand"],
    )
    fact_refresh_status = str(_pipeline_detail(args.api_base, headers, project_id, fact_refresh_run_id).get("status"))
    current_fact_candidate_ids = {
        str(candidate.get("id"))
        for candidate in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/fact-candidates/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
    }
    previous_fact_candidate_ids = {str(candidate.get("id")) for candidate in fact_candidates}
    reruns["fact_refresh"] = {
        "pipeline_run_id": fact_refresh_run_id,
        "status": fact_refresh_status,
        "new_candidate_count": len(refreshed_fact_candidates),
        "old_candidates_preserved": previous_fact_candidate_ids.issubset(current_fact_candidate_ids),
    }
    if fact_refresh_status != "succeeded" or not reruns["fact_refresh"]["old_candidates_preserved"]:
        failures.append("fact_refresh did not retain prior candidates or finish")

    previous_prompt_candidate_ids = {str(candidate.get("id")) for candidate in prompt_candidates}
    prompt_generation_run_id = _start_rerun(
        args.api_base,
        headers,
        project_id=project_id,
        run_type="prompt_generation",
        source_pipeline_run_id=fact_refresh_run_id,
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=prompt_generation_run_id,
            accepted_statuses={"waiting_human_review", "succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    regenerated_prompts = [
        candidate
        for candidate in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/prompt-candidates/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
        if str(candidate.get("pipeline_run_id")) == prompt_generation_run_id
    ]
    _review_and_import_prompts(args.api_base, headers, project_id, regenerated_prompts)
    prompt_generation_status = str(_pipeline_detail(args.api_base, headers, project_id, prompt_generation_run_id).get("status"))
    current_prompt_candidate_ids = {
        str(candidate.get("id"))
        for candidate in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/prompt-candidates/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
    }
    reruns["prompt_generation"] = {
        "pipeline_run_id": prompt_generation_run_id,
        "status": prompt_generation_status,
        "new_candidate_count": len(regenerated_prompts),
        "old_candidates_preserved": previous_prompt_candidate_ids.issubset(current_prompt_candidate_ids),
    }
    if prompt_generation_status != "succeeded" or not reruns["prompt_generation"]["old_candidates_preserved"]:
        failures.append("Prompt regeneration overwrote old candidates or did not finish")

    previous_content_ids = {str(draft.get("id")) for draft in content_drafts}
    content_generation_run_id = _start_rerun(
        args.api_base,
        headers,
        project_id=project_id,
        run_type="content_generation",
        source_pipeline_run_id=fact_refresh_run_id,
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=content_generation_run_id,
            accepted_statuses={"waiting_human_review", "succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    regenerated_content = [
        draft
        for draft in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/content-drafts/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
        if str(draft.get("pipeline_run_id")) == content_generation_run_id
    ]
    _review_content(args.api_base, headers, project_id, regenerated_content, review_status="rejected")
    rejected_content_export_blocked = True
    for draft in regenerated_content:
        response = httpx.post(
            f"{args.api_base}/v1/knowledge/content-drafts/runtime/{draft['id']}/export.md",
            headers=headers,
            params={"project_id": project_id},
            timeout=30,
        )
        if response.status_code not in {400, 409, 422}:
            rejected_content_export_blocked = False
    content_generation_status = str(_pipeline_detail(args.api_base, headers, project_id, content_generation_run_id).get("status"))
    current_content_ids = {
        str(draft.get("id"))
        for draft in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/content-drafts/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
    }
    reruns["content_generation"] = {
        "pipeline_run_id": content_generation_run_id,
        "status": content_generation_status,
        "new_draft_count": len(regenerated_content),
        "old_drafts_preserved": previous_content_ids.issubset(current_content_ids),
    }
    if content_generation_status != "succeeded" or not reruns["content_generation"]["old_drafts_preserved"]:
        failures.append("content regeneration overwrote old drafts or did not finish")
    if not rejected_content_export_blocked:
        failures.append("rejected content draft remained exportable")

    source_assets_before_rebuild = {
        str(asset.get("id"))
        for asset in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/source-assets/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
    }
    full_rebuild_run_id = _start_rerun(
        args.api_base,
        headers,
        project_id=project_id,
        run_type="full_rebuild",
        source_pipeline_run_id=pipeline_run_id,
        metadata={"adapter_engine": "markitdown", "chunk_profile_version": "geo_chunk_profile_e2e_rebuild_v1"},
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=full_rebuild_run_id,
            accepted_statuses={"waiting_human_review", "succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    rebuild_fact_candidates = [
        candidate
        for candidate in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/fact-candidates/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
        if str(candidate.get("pipeline_run_id")) == full_rebuild_run_id
    ]
    _review_facts(
        args.api_base,
        headers,
        project_id,
        rebuild_fact_candidates,
        preferred_subject=project_payload["target_brand"],
    )
    worker_runs.extend(
        _run_worker_until_pipeline_ready(
            root,
            args,
            headers=headers,
            project_id=project_id,
            pipeline_run_id=full_rebuild_run_id,
            accepted_statuses={"waiting_human_review", "succeeded", "partial_succeeded"},
            max_jobs=100,
        )
    )
    rebuild_prompts = [
        candidate
        for candidate in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/prompt-candidates/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
        if str(candidate.get("pipeline_run_id")) == full_rebuild_run_id
    ]
    rebuild_content = [
        draft
        for draft in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/content-drafts/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
        if str(draft.get("pipeline_run_id")) == full_rebuild_run_id
    ]
    _review_and_import_prompts(args.api_base, headers, project_id, rebuild_prompts)
    _review_content(args.api_base, headers, project_id, rebuild_content)
    rebuild_jobs = _pipeline_jobs(args.api_base, headers, project_id, full_rebuild_run_id)
    rebuild_parser_runs = _records(dict((rebuild_jobs.get("job_groups") or {}).get("knowledge_parser_runs") or {}))
    rebuild_chunks = [
        chunk
        for chunk in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/chunks/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
        if str(chunk.get("pipeline_run_id")) == full_rebuild_run_id
    ]
    source_assets_after_rebuild = {
        str(asset.get("id"))
        for asset in _records(
            _request(
                "GET",
                f"{args.api_base}/v1/knowledge/source-assets/runtime",
                headers=headers,
                params={"project_id": project_id, "limit": 200},
            )
        )
    }
    full_rebuild_status = str(
        _pipeline_detail(args.api_base, headers, project_id, full_rebuild_run_id).get("status")
    )
    reruns["full_rebuild"] = {
        "pipeline_run_id": full_rebuild_run_id,
        "status": full_rebuild_status,
        "parser_run_count": len(rebuild_parser_runs),
        "chunk_count": len(rebuild_chunks),
        "fact_candidate_count": len(rebuild_fact_candidates),
        "prompt_candidate_count": len(rebuild_prompts),
        "content_draft_count": len(rebuild_content),
        "source_assets_preserved": source_assets_before_rebuild.issubset(source_assets_after_rebuild),
    }
    if full_rebuild_status != "succeeded" or not all(
        (
            rebuild_parser_runs,
            rebuild_chunks,
            rebuild_fact_candidates,
            rebuild_prompts,
            rebuild_content,
            reruns["full_rebuild"]["source_assets_preserved"],
        )
    ):
        failures.append("full_rebuild did not preserve source assets or produce a complete versioned output chain")

    model_statuses = _worker_model_statuses(worker_runs)
    if any(status != "deepseek_succeeded" for status in model_statuses):
        failures.append(f"rerun knowledge model execution was not fully real DeepSeek: {model_statuses}")

    asset_names = {str(asset.get("filename") or asset.get("title") or "").lower() for asset in source_assets}
    parser_engines = {str(run.get("adapter_engine") or "") for run in parser_runs}
    final_fact_candidates = _records(
        _request(
            "GET",
            f"{args.api_base}/v1/knowledge/fact-candidates/runtime",
            headers=headers,
            params={"project_id": project_id, "limit": 200},
        )
    )
    fact_kinds = {str(candidate.get("fact_kind") or "") for candidate in final_fact_candidates}
    approved_fact_ids = {str(fact.get("id")) for fact in approved_facts}
    prompt_inputs_are_approved = bool(prompt_candidates) and all(
        set(str(value) for value in candidate.get("source_knowledge_fact_ids") or []).issubset(approved_fact_ids)
        for candidate in prompt_candidates
    )
    imported_prompt_ids = [
        str(candidate.get("imported_prompt_id"))
        for candidate in reviewed_prompt_candidates
        if candidate.get("imported_prompt_id")
    ]
    official_prompt_traceable = bool(imported_prompt_ids) and all(
        _trace_reaches_source_asset(trace_refs, target_type="official_prompt", target_id=prompt_id)
        for prompt_id in imported_prompt_ids
    )
    acceptance_checks = [
        {"id": 1, "name": "新建真实项目", "passed": bool(project_id)},
        {"id": 2, "name": "上传并解析 PDF", "passed": any(name.endswith(".pdf") for name in asset_names)},
        {"id": 3, "name": "上传并解析 DOCX", "passed": any(name.endswith(".docx") for name in asset_names)},
        {"id": 4, "name": "上传并解析 CSV", "passed": any(name.endswith(".csv") for name in asset_names)},
        {"id": 5, "name": "单 URL 抓取", "passed": len(crawl_job_ids) >= 1 and "crawled_markdown" in crawl_asset_types},
        {"id": 6, "name": "站点深度抓取", "passed": len(crawl_job_ids) >= 2 and "crawl_link_graph" in crawl_asset_types},
        {"id": 7, "name": "归档 HTML/Markdown/截图", "passed": required_crawl_assets.issubset(crawl_asset_types)},
        {"id": 8, "name": "Docling 解析", "passed": "docling" in parser_engines},
        {"id": 9, "name": "MinerU 解析", "passed": "mineru" in parser_engines},
        {"id": 10, "name": "解析器降级生效", "passed": any(str(run.get("status")) == "fallback_succeeded" for run in parser_runs)},
        {"id": 11, "name": "表格 CSV/HTML 产物", "passed": bool(parser_tables) and any(table.get("csv_asset_id") or table.get("html_asset_id") for table in parser_tables)},
        {"id": 12, "name": "Chunk 生成", "passed": bool(chunks)},
        {"id": 13, "name": "Chunk/解析质量问题可记录", "passed": bool(quality_gates)},
        {"id": 14, "name": "BGE-M3 写入 Qdrant", "passed": bool(qdrant_points) and dimension == DEFAULT_EMBEDDING_DIMENSION},
        {"id": 15, "name": "检索只返回 active chunk", "passed": bool(_records(search_page)) and all(str((record.get("chunk") or {}).get("status")) == "active" for record in _records(search_page))},
        {"id": 16, "name": "disabled chunk 不返回", "passed": disabled_search_excluded},
        {"id": 17, "name": "抽取品牌/竞品/市场/信源事实", "passed": {"brand", "competitor", "market", "source"}.issubset(fact_kinds)},
        {"id": 18, "name": "人工审核事实", "passed": bool(approved_facts)},
        {"id": 19, "name": "生成仅使用 active facts", "passed": prompt_inputs_are_approved},
        {"id": 20, "name": "approved facts 进入 Prompt 生成", "passed": bool(prompt_candidates)},
        {"id": 21, "name": "Prompt candidates 生成", "passed": bool(prompt_candidates)},
        {"id": 22, "name": "Prompt 审核并导入正式 Prompt", "passed": bool(imported_prompt_ids)},
        {"id": 23, "name": "GEO content draft 生成", "passed": bool(content_drafts)},
        {"id": 24, "name": "内容草稿带 citation refs", "passed": bool(content_drafts) and all(draft.get("citation_refs") for draft in content_drafts)},
        {"id": 25, "name": "rejected draft 不可导出", "passed": rejected_content_export_blocked},
        {"id": 26, "name": "approved draft 可导出", "passed": bool(exported_content)},
        {"id": 27, "name": "Prompt/Content 追溯到 Source Asset", "passed": official_prompt_traceable and all(_trace_reaches_source_asset(trace_refs, target_type="content_draft", target_id=str(draft.get("id"))) for draft in content_drafts)},
        {"id": 28, "name": "跨项目/未授权访问阻断", "passed": unauthorized.status_code in {401, 403, 404}},
        {"id": 29, "name": "私有 URL 抓取阻断", "passed": private_url_response.status_code in {400, 422}},
        {"id": 30, "name": "审计事件完整", "passed": int(audit_page.get("total_count") or 0) >= 10},
        {"id": 31, "name": "reparse 保留旧 Parser Run", "passed": bool(reruns.get("reparse", {}).get("old_parser_runs_preserved"))},
        {"id": 32, "name": "rechunk 旧 Chunk superseded", "passed": bool(reruns.get("rechunk", {}).get("old_chunks_superseded"))},
        {"id": 33, "name": "reindex 不改变 Chunk 文本", "passed": bool(reruns.get("reindex", {}).get("chunk_text_unchanged"))},
        {"id": 34, "name": "fact_refresh 保留旧候选", "passed": bool(reruns.get("fact_refresh", {}).get("old_candidates_preserved"))},
        {"id": 35, "name": "Prompt/Content 重生成保留旧产物", "passed": bool(reruns.get("prompt_generation", {}).get("old_candidates_preserved")) and bool(reruns.get("content_generation", {}).get("old_drafts_preserved"))},
        {
            "id": 36,
            "name": "版本变化标记 stale/needs_reextract 并可 full_rebuild",
            "passed": bool(reruns.get("rechunk", {}).get("version_invalidation_observed"))
            and bool(reruns.get("full_rebuild", {}).get("source_assets_preserved")),
        },
    ]
    failed_acceptance = [check for check in acceptance_checks if not check["passed"]]
    if failed_acceptance:
        failures.append(
            "full pipeline acceptance failed: "
            + ", ".join(f"{check['id']}:{check['name']}" for check in failed_acceptance)
        )

    return {
        "status": "fail" if failures else "pass",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "project_id": project_id,
        "pipeline_run_id": pipeline_run_id,
        "import_job_id": import_job_id,
        "source_asset_ids": [
            str((response.get("knowledge_source_asset") or {}).get("id") or "")
            for response in upload_responses
        ],
        "duplicate_source_asset_id": str(duplicate_asset.get("id") or ""),
        "source_contract_prechecks": {
            source_mode: ((detail.get("knowledge_import_job") or {}).get("result_summary") or {}).get("precheck")
            for source_mode, detail in source_contract_details.items()
        },
        "approved_fact_candidate_id": approved_fact_candidate_id,
        "pipeline_status": pipeline_detail.get("status"),
        "stage_statuses": {str(stage.get("stage_key")): str(stage.get("status")) for stage in stages},
        "job_group_counts": {name: int(group.get("total_count") or 0) for name, group in job_groups.items() if isinstance(group, dict)},
        "chunk_count": len(chunks),
        "fact_candidate_count": len(fact_candidates),
        "prompt_candidate_count": len(prompt_candidates),
        "content_draft_count": len(content_drafts),
        "official_prompt_count": int(prompts.get("total_count") or 0),
        "quality_gate_count": len(quality_gates),
        "trace_ref_count": len(trace_refs),
        "qdrant_point_count": len(qdrant_points),
        "qdrant_collection": args.qdrant_collection,
        "qdrant_dimension": dimension,
        "model_statuses": model_statuses,
        "prompt_import_count": (prompt_import.get("prompt_import") or {}).get("prompt_count"),
        "worker_runs": worker_runs,
        "reruns": reruns,
        "crawl_pipeline_run_id": crawl_pipeline_run_id,
        "crawl_asset_types": sorted(crawl_asset_types),
        "acceptance_checks": acceptance_checks,
        "operational_checks": operational_checks,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real GEO knowledge production pipeline E2E.")
    parser.add_argument("--api-base", default=os.getenv("GENO_LIVE_API_BASE", "http://localhost:18003"))
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:18006"))
    parser.add_argument("--qdrant-collection", default=os.getenv("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION))
    parser.add_argument("--compose-project", default=os.getenv("GENO_COMPOSE_PROJECT", "geno-auto"))
    parser.add_argument("--compose-env-file", default="tmp/docker-compose.auto-ports.env")
    parser.add_argument("--worker-timeout", type=int, default=1800)
    parser.add_argument("--artifact", default="/tmp/geo-knowledge-live-e2e.json")
    args = parser.parse_args(argv)
    try:
        artifact = run(args)
    except Exception as exc:  # noqa: BLE001
        artifact = {
            "status": "fail",
            "run_id": f"knowledge-live-{uuid4().hex}",
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "failures": [f"{type(exc).__name__}: {exc}"],
        }
    Path(args.artifact).write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False))
    return 0 if artifact["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
