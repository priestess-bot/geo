from __future__ import annotations

import unittest
from datetime import UTC, datetime

from geno_core.models import (
    RuntimeReportArtifact,
    RuntimeReportExport,
    RuntimeReportExportJob,
    RuntimeReportExportJobStatusInput,
    RuntimeReportExportPage,
)
from geno_core.object_store import S3CompatibleObjectStore
from workers.report_export_worker.run_report_export_jobs import process_next_report_export_job


class FakeReportExportJobRepository:
    def __init__(
        self,
        *,
        job: RuntimeReportExportJob | None,
        latest_report_id: str | None,
        artifact: RuntimeReportArtifact | None,
    ) -> None:
        self.job = job
        self.latest_report_id = latest_report_id
        self.artifact = artifact
        self.claimed_by: str | None = None
        self.artifact_kwargs: dict[str, object] | None = None
        self.status_updates: list[RuntimeReportExportJobStatusInput] = []

    def claim_next_runtime_report_export_job(self, *, updated_by: str = "runtime-worker") -> RuntimeReportExportJob | None:
        self.claimed_by = updated_by
        return self.job

    def list_runtime_report_exports(
        self,
        *,
        project_id: str | None = None,
        report_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RuntimeReportExportPage:
        if not self.latest_report_id:
            return RuntimeReportExportPage(total_count=0, limit=limit, offset=offset, records=())
        return RuntimeReportExportPage(
            total_count=1,
            limit=limit,
            offset=offset,
            records=(
                RuntimeReportExport(
                    report_export={"id": self.latest_report_id, "project_id": project_id, "report_version": "latest"},
                    score_snapshots=(),
                    answer_runs=(),
                    citation_graph=None,
                    audit_events=(),
                ),
            ),
        )

    def get_runtime_report_artifact(self, **kwargs: object) -> RuntimeReportArtifact | None:
        self.artifact_kwargs = dict(kwargs)
        return self.artifact

    def update_runtime_report_export_job_status(self, update: RuntimeReportExportJobStatusInput) -> RuntimeReportExportJob:
        self.status_updates.append(update)
        assert self.job is not None
        return self.job


class ReportExportWorkerContractsTest(unittest.TestCase):
    def test_process_next_report_export_job_archives_artifact_and_marks_succeeded(self) -> None:
        now = datetime(2026, 6, 11, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        job_id = "8f4f2a24-d6cf-5050-96a4-942d2c337fd0"
        job = RuntimeReportExportJob(
            report_export_job={
                "id": job_id,
                "project_id": project_id,
                "report_export_id": None,
                "status": "running",
                "artifact_type": "pdf",
                "template": "white_label",
                "filters": {"platform": "perplexity", "city": "Sydney", "client_name": "Client AU"},
                "sort": "cost_desc",
                "requested_by": "runtime-console",
                "requested_at": now,
                "started_at": now,
                "completed_at": None,
                "artifact_url": None,
                "error_message": None,
                "updated_by": "runtime-worker",
                "updated_at": now,
            },
            audit_events=(),
        )
        artifact = RuntimeReportArtifact(
            report_export={"id": report_export_id, "project_id": project_id, "report_version": "worker-runtime-v1"},
            artifact_type="pdf",
            template="white_label",
            template_payload={"template": "white_label", "client_name": "Client AU"},
            template_hash="template-hash",
            filename="worker-runtime-v1-white-label.pdf",
            media_type="application/pdf",
            content=b"%PDF-1.4 worker artifact\n%%EOF",
            content_hash="artifact-content-hash",
            filters={"platform": "perplexity", "city": "Sydney"},
            filter_hash="filter-hash",
            sort="cost_desc",
            total_count=10,
            row_count=3,
        )
        repository = FakeReportExportJobRepository(job=job, latest_report_id=report_export_id, artifact=artifact)
        requests: list[tuple[str, str, dict[str, str], bytes]] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append((method, url, dict(headers), body))
            return 200, {"ETag": '"worker-etag"'}, b""

        store = S3CompatibleObjectStore(
            endpoint="http://minio:9000",
            bucket="geno-reports",
            access_key="minio",
            secret_key="minio123",
            requester=requester,
        )

        result = process_next_report_export_job(repository=repository, object_store=store)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["report_export_id"], report_export_id)
        self.assertTrue(str(result["artifact_url"]).startswith("s3://geno-reports/report-artifacts/"))
        self.assertEqual(repository.claimed_by, "runtime-worker")
        self.assertEqual(repository.artifact_kwargs["platform"], "perplexity")
        self.assertEqual(repository.artifact_kwargs["city"], "Sydney")
        self.assertEqual(repository.artifact_kwargs["client_name"], "Client AU")
        self.assertEqual(repository.status_updates[-1].status, "succeeded")
        self.assertEqual(repository.status_updates[-1].artifact_url, result["artifact_url"])
        self.assertEqual(repository.status_updates[-1].reason, "report export artifact rendered and archived")
        object_puts = [item for item in requests if item[0] == "PUT" and "report-artifacts" in item[1]]
        self.assertEqual(len(object_puts), 1)

    def test_process_next_report_export_job_marks_failed_when_no_report_exists(self) -> None:
        now = datetime(2026, 6, 11, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        job_id = "8f4f2a24-d6cf-5050-96a4-942d2c337fd0"
        job = RuntimeReportExportJob(
            report_export_job={
                "id": job_id,
                "project_id": project_id,
                "report_export_id": None,
                "status": "running",
                "artifact_type": "csv",
                "template": "standard",
                "filters": {},
                "sort": "collected_at_desc",
                "requested_by": "runtime-console",
                "requested_at": now,
                "started_at": now,
                "completed_at": None,
                "artifact_url": None,
                "error_message": None,
                "updated_by": "runtime-worker",
                "updated_at": now,
            },
            audit_events=(),
        )
        repository = FakeReportExportJobRepository(job=job, latest_report_id=None, artifact=None)

        result = process_next_report_export_job(repository=repository, object_store=None)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(repository.status_updates[-1].status, "failed")
        self.assertIn("No report_export_id supplied", repository.status_updates[-1].error_message or "")
        self.assertIsNone(repository.artifact_kwargs)


if __name__ == "__main__":
    unittest.main()
