from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from geo_core.models import RuntimeReportExportJobStatusInput
from geo_core.object_store import S3CompatibleObjectStore, StoredObject, archive_runtime_report_artifact
from geo_core.repository import PostgresEvidenceRepository
from geo_core.runtime import (
    build_object_store_from_env,
    build_repository_from_env,
    close_repository_connection,
    validate_runtime_schema_compatibility,
)


WORKER_ID = "runtime-worker"


class ReportExportJobRepository(Protocol):
    def claim_next_runtime_report_export_job(
        self,
        *,
        updated_by: str = WORKER_ID,
        lease_seconds: int = 900,
    ) -> object | None:
        ...

    def list_runtime_report_exports(
        self,
        *,
        project_id: str | None = None,
        report_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> object:
        ...

    def get_runtime_report_artifact(
        self,
        *,
        report_export_id: str,
        artifact_type: str,
        platform: str | None = None,
        city: str | None = None,
        intent_type: str | None = None,
        status: str | None = None,
        sort: str | None = None,
        template: str | None = None,
        client_name: str | None = None,
        prepared_by: str | None = None,
    ) -> object | None:
        ...

    def update_runtime_report_export_job_status(self, update: RuntimeReportExportJobStatusInput) -> object:
        ...


def _clean_filter_value(filters: dict[str, Any], key: str) -> str | None:
    value = filters.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _latest_report_export_id(repository: ReportExportJobRepository, *, project_id: str) -> str | None:
    page = repository.list_runtime_report_exports(project_id=project_id, limit=1, offset=0)
    records = tuple(getattr(page, "records", ()))
    if not records:
        return None
    report_export = getattr(records[0], "report_export", {})
    report_export_id = str(report_export.get("id") or "").strip()
    return report_export_id or None


def process_next_report_export_job(
    *,
    repository: ReportExportJobRepository,
    object_store: S3CompatibleObjectStore | None,
    updated_by: str = WORKER_ID,
    require_object_store: bool = False,
    max_attempts: int = 3,
    retry_backoff_seconds: int = 300,
    lease_seconds: int = 900,
) -> dict[str, Any]:
    max_attempts = max(1, int(max_attempts))
    retry_backoff_seconds = max(0, int(retry_backoff_seconds))
    lease_seconds = max(1, int(lease_seconds))
    job_record = repository.claim_next_runtime_report_export_job(updated_by=updated_by, lease_seconds=lease_seconds)
    if job_record is None:
        return {
            "processed": False,
            "status": "idle",
            "reason": "no queued report export jobs",
        }

    job = dict(getattr(job_record, "report_export_job"))
    job_id = str(job["id"])
    project_id = str(job["project_id"])
    attempt_count = int(job.get("attempt_count") or 0)
    job_max_attempts = max(max_attempts, int(job.get("max_attempts") or max_attempts))
    report_export_id = str(job["report_export_id"] or "").strip()
    if not report_export_id:
        report_export_id = _latest_report_export_id(repository, project_id=project_id) or ""
    if not report_export_id:
        repository.update_runtime_report_export_job_status(
            RuntimeReportExportJobStatusInput(
                job_id=job_id,
                status=_failed_status(attempt_count=attempt_count, max_attempts=job_max_attempts),
                updated_by=updated_by,
                error_message="No report_export_id supplied and no report_exports exist for project",
                next_attempt_at=_next_attempt_at(
                    attempt_count=attempt_count,
                    max_attempts=job_max_attempts,
                    retry_backoff_seconds=retry_backoff_seconds,
                ),
                reason="report export job has no renderable report",
            )
        )
        return {
            "processed": True,
            "status": _failed_status(attempt_count=attempt_count, max_attempts=job_max_attempts),
            "job_id": job_id,
            "project_id": project_id,
            "attempt_count": attempt_count,
            "max_attempts": job_max_attempts,
            "error_message": "No report_export_id supplied and no report_exports exist for project",
        }

    filters = job.get("filters") if isinstance(job.get("filters"), dict) else {}
    try:
        artifact = repository.get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type=str(job["artifact_type"]),
            platform=_clean_filter_value(filters, "platform"),
            city=_clean_filter_value(filters, "city"),
            intent_type=_clean_filter_value(filters, "intent_type"),
            status=_clean_filter_value(filters, "status"),
            sort=str(job.get("sort") or "collected_at_desc"),
            template=str(job.get("template") or "standard"),
            client_name=_clean_filter_value(filters, "client_name"),
            prepared_by=_clean_filter_value(filters, "prepared_by"),
        )
        if artifact is None:
            raise ValueError(f"report_export not found: {report_export_id}")
        stored_object: StoredObject | None = None
        if object_store is not None:
            stored_object = archive_runtime_report_artifact(
                project_id=project_id,
                artifact=artifact,
                store=object_store,
            )
            artifact_url = stored_object.uri
        elif require_object_store:
            raise ValueError("OBJECT_STORE_ENDPOINT is required when --require-object-store is set")
        else:
            artifact_url = f"runtime-report-artifact://{report_export_id}/{artifact.filename}?hash={artifact.content_hash}"
        repository.update_runtime_report_export_job_status(
            RuntimeReportExportJobStatusInput(
                job_id=job_id,
                status="succeeded",
                updated_by=updated_by,
                report_export_id=report_export_id,
                artifact_url=artifact_url,
                reason="report export artifact rendered and archived",
            )
        )
        return {
            "processed": True,
            "status": "succeeded",
            "job_id": job_id,
            "project_id": project_id,
            "report_export_id": report_export_id,
            "attempt_count": attempt_count,
            "max_attempts": job_max_attempts,
            "artifact_type": artifact.artifact_type,
            "template": artifact.template,
            "artifact_url": artifact_url,
            "content_hash": artifact.content_hash,
            "stored_object": asdict(stored_object) if stored_object else None,
        }
    except Exception as exc:
        failed_status = _failed_status(attempt_count=attempt_count, max_attempts=job_max_attempts)
        next_attempt_at = _next_attempt_at(
            attempt_count=attempt_count,
            max_attempts=job_max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        repository.update_runtime_report_export_job_status(
            RuntimeReportExportJobStatusInput(
                job_id=job_id,
                status=failed_status,
                updated_by=updated_by,
                report_export_id=report_export_id or None,
                error_message=str(exc),
                next_attempt_at=next_attempt_at,
                reason="report export artifact rendering failed",
            )
        )
        return {
            "processed": True,
            "status": failed_status,
            "job_id": job_id,
            "project_id": project_id,
            "report_export_id": report_export_id or None,
            "attempt_count": attempt_count,
            "max_attempts": job_max_attempts,
            "next_attempt_at": next_attempt_at.isoformat() if next_attempt_at else None,
            "error_message": str(exc),
        }


def _failed_status(*, attempt_count: int, max_attempts: int) -> str:
    return "dead_letter" if attempt_count >= max_attempts else "queued"


def _next_attempt_at(*, attempt_count: int, max_attempts: int, retry_backoff_seconds: int) -> datetime | None:
    if attempt_count >= max_attempts:
        return None
    delay = retry_backoff_seconds * max(1, attempt_count)
    return datetime.now(UTC) + timedelta(seconds=delay)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process queued GEO runtime report export jobs")
    parser.add_argument("--max-jobs", type=int, default=1, help="Maximum queued jobs to process before exiting.")
    parser.add_argument("--worker-id", default=WORKER_ID, help="Actor id used in report export job audit events.")
    parser.add_argument("--max-attempts", type=int, default=3, help="Dead-letter a job after this many claimed attempts.")
    parser.add_argument("--retry-backoff-seconds", type=int, default=300, help="Base delay before retrying failed jobs.")
    parser.add_argument("--lease-seconds", type=int, default=900, help="Running job lease duration before it can be reclaimed.")
    parser.add_argument(
        "--require-object-store",
        action="store_true",
        help="Fail jobs if OBJECT_STORE_* is not configured instead of using runtime-report-artifact:// fallback URLs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_runtime_schema_compatibility()
    max_jobs = max(1, args.max_jobs)
    repository: PostgresEvidenceRepository | None = None
    results: list[dict[str, Any]] = []
    try:
        repository = build_repository_from_env()
        object_store = build_object_store_from_env() if os.environ.get("OBJECT_STORE_ENDPOINT", "").strip() else None
        for _ in range(max_jobs):
            result = process_next_report_export_job(
                repository=repository,
                object_store=object_store,
                updated_by=args.worker_id,
                require_object_store=args.require_object_store,
                max_attempts=args.max_attempts,
                retry_backoff_seconds=args.retry_backoff_seconds,
                lease_seconds=args.lease_seconds,
            )
            results.append(result)
            if result["status"] == "idle":
                break
    finally:
        if repository is not None:
            close_repository_connection(repository)
    print(json.dumps({"worker": args.worker_id, "results": results}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
