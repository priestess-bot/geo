from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import inspect
from io import BytesIO
import json
import os
from pathlib import Path
import time
import unittest
from datetime import UTC, datetime
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

import fastapi.dependencies.utils
import fastapi.routing
import httpx
import starlette.concurrency
import starlette.routing
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes

from geno_api.main import app, close_runtime_resources, reset_runtime_auth_caches, reset_runtime_metrics
from geno_core.runtime import RuntimeComponentDiagnostic, RuntimeDiagnostics
from geno_core.email_preferences import sign_runtime_notification_email_preference_token
from geno_core.webhook_signing import (
    RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER,
    RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER,
    RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER,
    runtime_notification_webhook_payload_hash,
    sign_runtime_notification_webhook,
)
from scripts.build_au_p0a_env_report import compute_env_report_hash
from scripts.build_au_launch_status import compute_launch_status_hash
from scripts.build_au_external_dependency_handoff import compute_external_dependency_handoff_hash
from scripts.build_au_p0b_google_environment_request_packet import (
    compute_p0b_google_environment_request_packet_hash,
)
from scripts.build_au_p0b_google_environment_clearance import compute_p0b_google_environment_clearance_hash
from scripts.build_au_p0b_google_manual_backfill_request_packet import (
    compute_p0b_google_manual_backfill_request_packet_hash,
)
from scripts.build_au_p0b_google_manual_backfill_fulfillment import (
    compute_p0b_google_manual_backfill_fulfillment_hash,
)
from scripts.build_au_p0b_google_manual_backfill_clearance import (
    compute_p0b_google_manual_backfill_clearance_hash,
)
from scripts.build_au_p0b_google_phase_execution_request_packet import (
    compute_p0b_google_phase_execution_request_packet_hash,
)
from scripts.build_au_p0b_google_phase_execution_fulfillment import (
    compute_p0b_google_phase_execution_fulfillment_hash,
)
from scripts.build_au_p0b_google_phase_execution_clearance import (
    compute_p0b_google_phase_execution_clearance_hash,
)
from scripts.build_au_customer_handoff_clearance import compute_customer_handoff_clearance_hash
from scripts.run_au_external_dependency_clearance import run_au_external_dependency_clearance
from scripts.build_au_p0a_real_batch_request_packet import compute_p0a_real_batch_request_packet_hash
from scripts.build_au_p0a_real_batch_fulfillment import compute_p0a_real_batch_fulfillment_hash
from scripts.build_au_p0a_credential_clearance import compute_p0a_credential_clearance_hash
from scripts.build_au_p0a_credential_update_receipt import compute_p0a_credential_update_receipt_hash
from scripts.build_au_p0a_real_batch_clearance import compute_p0a_real_batch_clearance_hash
from tests.test_au_handoff_dossier import AuHandoffDossierTest
from tests.test_au_external_dependency_clearance import AuExternalDependencyClearanceTest
from tests.test_au_p0a_environment_checklist import AuP0aEnvironmentChecklistTest
from tests.test_au_p0a_execution_checklist import AuP0aExecutionChecklistTest
from tests.test_au_p0b_google_execution_checklist import AuP0bGoogleExecutionChecklistTest
from geno_core.models import (
    RuntimeEntityAlias,
    RuntimeEntityAliasAssignmentEscalationResult,
    RuntimeEntityAliasAssignmentNotificationResult,
    RuntimeEntityAliasAssignmentReassignmentResult,
    RuntimeEntityAliasAssignmentWorkbench,
    RuntimeEntityAliasAssignmentWorkloadSummary,
    RuntimeEntityAliasAssignmentDispatchApplyResult,
    RuntimeEntityAliasAssignmentDispatchPlan,
    RuntimeEntityAliasAssignmentBatchActionResult,
    RuntimeEntityAliasCandidateAssignmentQueueStats,
    RuntimeEntityAliasCandidate,
    RuntimeEntityAliasCandidateBatchReviewResult,
    RuntimeEntityAliasCandidatePage,
    RuntimeEntityAliasCandidateReview,
    RuntimeEntityAliasCandidateReviewPage,
    RuntimeCollectionRunPage,
    RuntimeAlertEvent,
    RuntimeAlertItem,
    RuntimeAlertNotificationResult,
    RuntimeAlertPage,
    RuntimeAuditEventExport,
    RuntimeAuditEventPage,
    RuntimeEvidenceExport,
    RuntimeFidelityCheck,
    RuntimeFidelityCheckPage,
    RuntimeFidelityTrend,
    RuntimeFidelityTrendPoint,
    RuntimeHumanReviewPage,
    RuntimeHumanReviewQueueItem,
    RuntimeHumanReviewQueuePage,
    RuntimeHumanReviewRecord,
    RuntimeKnowledgeSearchPage,
    RuntimeKnowledgeSearchResult,
    RuntimeNotificationDelivery,
    RuntimeNotificationDeliveryPage,
    RuntimeNotificationEmailFeedback,
    RuntimeNotificationEmailFeedbackPage,
    RuntimeNotificationEmailSuppression,
    RuntimeNotificationEmailSuppressionPage,
    RuntimeNotificationEmailPreferenceStatus,
    RuntimeNotification,
    RuntimeNotificationPage,
    RuntimeNotificationSubscription,
    RuntimeNotificationSubscriptionPage,
    RuntimeProjectBrandAsset,
    RuntimeProjectBrandAssetInput,
    RuntimeProjectBrandAssetPage,
    RuntimeProjectBrandAssetScanInput,
    RuntimeProjectBrandKit,
    RuntimeProjectBrandAssetVersion,
    RuntimeProjectBrandAssetVersionPage,
    RuntimeProjectBrandLogoUpload,
    RuntimeProject,
    RuntimeProjectLifecycleEventExport,
    RuntimeProjectLifecycleEvent,
    RuntimeProjectLifecycleEventPage,
    RuntimeProjectMember,
    RuntimeProjectMemberInvitation,
    RuntimeProjectMemberInvitationPage,
    RuntimeProjectMemberPage,
    RuntimeProjectActionInput,
    RuntimeProjectUpdateInput,
    RuntimePromptImportHistoryItem,
    RuntimePromptImportHistoryPage,
    RuntimePromptImportResult,
    RuntimeProjectPage,
    RuntimeReportArtifact,
    RuntimeReportExport,
    RuntimeReportExportJob,
    RuntimeReportExportJobPage,
    RuntimeReportExportJobQueueStats,
    RuntimeScoreWeightConfig,
)


# API contract tests drive ASGI directly because Starlette TestClient's portal
# can hang in this Python/anyio stack even for a minimal synchronous endpoint.
async def _run_inline_in_test_threadpool(func: object, *args: object, **kwargs: object) -> object:
    result = func(*args, **kwargs)  # type: ignore[misc]
    if inspect.isawaitable(result):
        return await result
    return result


fastapi.dependencies.utils.run_in_threadpool = _run_inline_in_test_threadpool
fastapi.routing.run_in_threadpool = _run_inline_in_test_threadpool
starlette.concurrency.run_in_threadpool = _run_inline_in_test_threadpool
starlette.routing.run_in_threadpool = _run_inline_in_test_threadpool


def _find_forbidden_exact_fields(value: object, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"value", "raw_value", "database_url"}:
                findings.append(child_path)
            findings.extend(_find_forbidden_exact_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden_exact_fields(child, path=f"{path}[{index}]"))
    return findings


def _write_p0a_env_report_with_database(temp_dir: str) -> Path:
    report: dict[str, object] = {
        "environment_report_version": "au_p0a_environment_report_v1",
        "generated_at": "2026-06-12T00:00:00Z",
        "status": "fail",
        "ready_for_real_batch": False,
        "next_action": "populate_required_environment",
        "runbook_path": "runbook.json",
        "runbook": {"status": "pass", "hash_valid": True},
        "env_file": {
            "exists": True,
            "loaded": True,
            "entry_count": 3,
            "errors": [],
            "hygiene": {
                "exists": True,
                "hygiene_ready": True,
                "hygiene_required": True,
                "errors": [],
                "warnings": [],
                "secret_redacted": True,
            },
        },
        "required": [
            {
                "name": "PERPLEXITY_API_KEY",
                "present": False,
                "source": "missing",
                "value_length": 0,
                "sha256_prefix": "",
                "secret_redacted": True,
            },
            {
                "name": "OPENAI_API_KEY",
                "present": False,
                "source": "missing",
                "value_length": 0,
                "sha256_prefix": "",
                "secret_redacted": True,
            },
            {
                "name": "DATABASE_URL",
                "present": True,
                "source": "env_file",
                "value_length": 66,
                "sha256_prefix": "237b9d13d4e5",
                "secret_redacted": True,
            },
        ],
        "recommended": [],
        "missing_required": ["OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
        "missing_recommended": [],
        "summary": {
            "required_count": 3,
            "present_required_count": 1,
            "missing_required_count": 2,
            "missing_required": ["OPENAI_API_KEY", "PERPLEXITY_API_KEY"],
            "recommended_count": 0,
            "present_recommended_count": 0,
            "missing_recommended_count": 0,
            "missing_recommended": [],
            "runbook_status": "pass",
            "runbook_hash_valid": True,
            "env_file_exists": True,
            "env_file_loaded": True,
            "env_file_entry_count": 3,
            "env_file_hygiene_ready": True,
            "env_file_hygiene_error_count": 0,
            "env_file_hygiene_warning_count": 0,
            "ready_for_real_batch": False,
            "next_action": "populate_required_environment",
            "raw_secret_values_allowed": False,
        },
        "warnings": [],
        "errors": [
            "required_env_missing:PERPLEXITY_API_KEY",
            "required_env_missing:OPENAI_API_KEY",
        ],
        "secrets_redacted": True,
    }
    report["environment_report_hash"] = compute_env_report_hash(report)
    path = Path(temp_dir) / "p0a-env.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


class RuntimeApiTestClient:
    def __init__(self, app: object) -> None:
        self._app = app

    def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app, raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.request(method, url, **kwargs)
                await response.aread()
                return response

        return asyncio.run(_request())

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)


class ApiContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_metrics()
        reset_runtime_auth_caches()
        self.client = RuntimeApiTestClient(app)

    def _runtime_jwt(self, *, secret: str = "test-runtime-secret", payload: dict[str, object] | None = None) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        claims = {"sub": "agency-owner", "exp": int(time.time()) + 300}
        if payload:
            claims.update(payload)
        encoded_header = base64.urlsafe_b64encode(
            json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        encoded_payload = base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        signature = hmac.new(
            secret.encode("utf-8"),
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return f"{encoded_header}.{encoded_payload}.{encoded_signature}"

    def _runtime_jwks_rs256_token(
        self,
        *,
        payload: dict[str, object] | None = None,
        key_id: str = "runtime-key-1",
    ) -> tuple[str, str]:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_numbers = private_key.public_key().public_numbers()

        def base64url_int(value: int) -> str:
            raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

        jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": key_id,
                    "use": "sig",
                    "alg": "RS256",
                    "n": base64url_int(public_numbers.n),
                    "e": base64url_int(public_numbers.e),
                }
            ]
        }
        header = {"alg": "RS256", "kid": key_id, "typ": "JWT"}
        claims = {"sub": "jwks-owner", "exp": int(time.time()) + 300}
        if payload:
            claims.update(payload)
        encoded_header = base64.urlsafe_b64encode(
            json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        encoded_payload = base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        signature = private_key.sign(
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return f"{encoded_header}.{encoded_payload}.{encoded_signature}", json.dumps(jwks)

    def _xlsx_prompt_import_bytes(self) -> bytes:
        buffer = BytesIO()
        with ZipFile(buffer, "w") as workbook:
            workbook.writestr(
                "xl/workbook.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Prompts" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
            )
            workbook.writestr(
                "xl/_rels/workbook.xml.rels",
                """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
            )
            workbook.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>text</t></is></c><c r="B1" t="inlineStr"><is><t>intent_type</t></is></c><c r="C1" t="inlineStr"><is><t>city</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>Is ExampleBrand visible in AI answers?</t></is></c><c r="B2" t="inlineStr"><is><t>brand_awareness</t></is></c><c r="C2" t="inlineStr"><is><t>Sydney</t></is></c></row>
  </sheetData>
</worksheet>""",
            )
        return buffer.getvalue()

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_readiness_returns_503_when_database_check_fails(self) -> None:
        with patch(
            "geno_api.main.runtime_database_diagnostic",
            return_value=RuntimeComponentDiagnostic(
                name="database",
                status="fail",
                detail="DATABASE_URL is not configured",
                metadata={"database_url": "missing"},
            ),
        ):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["checks"][0]["name"], "database")

    def test_readiness_returns_200_when_database_check_passes(self) -> None:
        with patch(
            "geno_api.main.runtime_database_diagnostic",
            return_value=RuntimeComponentDiagnostic(
                name="database",
                status="pass",
                detail="PostgreSQL connection check succeeded",
                metadata={"database_url": "configured"},
            ),
        ):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pass")

    def test_runtime_diagnostics_endpoint_returns_component_checks(self) -> None:
        diagnostics = RuntimeDiagnostics(
            status="warn",
            checks=(
                RuntimeComponentDiagnostic(
                    name="database",
                    status="pass",
                    detail="PostgreSQL connection check succeeded",
                    metadata={"database_url": "configured"},
                ),
                RuntimeComponentDiagnostic(
                    name="object_store",
                    status="warn",
                    detail="OBJECT_STORE_ENDPOINT is not configured",
                    metadata={"endpoint": "missing"},
                ),
            ),
        )
        with patch("geno_api.main.build_runtime_diagnostics", return_value=diagnostics):
            response = self.client.get("/v1/runtime-diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "warn")
        self.assertEqual([check["name"] for check in payload["checks"]], ["database", "object_store"])

    def test_au_launch_status_endpoint_returns_auditable_gate(self) -> None:
        status_payload = {
            "launch_status_version": "au_launch_status_v1",
            "generated_at": "2026-06-12T00:00:00Z",
            "status": "blocked",
            "ready_for_customer_report_handoff": False,
            "next_action": "configure_required_environment",
            "remaining_blockers": ["missing_real_p0a_credentials"],
            "launch_status_hash": "abc123",
            "p0a_design_partner": {
                "status": "blocked",
                "ready_for_design_partner": False,
                "completion": {
                    "completion_percent": 50.0,
                    "design_ready_artifact_percent": 40.0,
                },
                "remaining_blockers": ["missing_real_p0a_credentials"],
            },
            "p0b_google": {
                "status": "blocked",
                "google_main_scoring_allowed": False,
                "limited_coverage": True,
                "package_summary": {
                    "artifact_count": 5,
                    "failed_artifacts": ["real_google_serp_health"],
                },
                "remaining_blockers": ["missing_google_serp_health"],
            },
            "p0c_customer_report": {
                "status": "blocked",
                "p0c_report_contract_ready": False,
                "report_contract_version": "customer_report_handoff_v1",
                "google_coverage": "limited_coverage_appendix_only",
                "audit_event_count": 12,
                "artifact_count": 8,
                "remaining_blockers": ["missing_signed_report_url"],
            },
        }
        with patch("geno_api.main.build_au_launch_status", return_value=status_payload) as build_status:
            response = self.client.get("/v1/launch-status/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["launch_status_version"], "au_launch_status_v1")
        self.assertFalse(payload["ready_for_customer_report_handoff"])
        self.assertEqual(payload["next_action"], "configure_required_environment")
        self.assertIn("missing_real_p0a_credentials", payload["remaining_blockers"])
        self.assertEqual(payload["p0a_design_partner"]["completion"]["completion_percent"], 50.0)
        self.assertTrue(payload["p0b_google"]["limited_coverage"])
        self.assertEqual(payload["p0c_customer_report"]["report_contract_version"], "customer_report_handoff_v1")
        build_status.assert_called_once()

    def test_au_launch_remediation_plan_endpoint_returns_auditable_work_items(self) -> None:
        status_payload = {
            "launch_status_version": "au_launch_status_v1",
            "generated_at": "2026-06-12T00:00:00Z",
            "status": "fail",
            "ready_for_customer_report_handoff": False,
            "next_action": "configure_required_environment",
            "remaining_blockers": ["p0a:preflight:required_env_missing:OPENAI_API_KEY"],
        }
        status_payload["launch_status_hash"] = compute_launch_status_hash(status_payload)
        plan_payload = {
            "remediation_plan_version": "au_launch_remediation_plan_v1",
            "generated_at": "2026-06-12T00:00:00Z",
            "status": "pass",
            "remediation_plan_ready": True,
            "next_work_item_id": "p0a_environment",
            "summary": {
                "blocker_count": 1,
                "covered_blocker_count": 1,
                "unmapped_blocker_count": 0,
                "work_item_count": 1,
            },
            "work_items": [
                {
                    "id": "p0a_environment",
                    "stage": "P0a",
                    "title": "Configure AU P0a provider keys and runtime database",
                    "commands": [{"shell": "make au-p0a-env"}],
                    "verification_commands": [{"shell": "make verify-au-p0a-env"}],
                    "evidence_outputs": ["docs/runtime_preflight/au-p0a-env-latest.json"],
                    "clears_blockers": ["p0a:preflight:required_env_missing:OPENAI_API_KEY"],
                    "blocker_count": 1,
                    "external_dependency": True,
                    "dependency_class": "provider_keys_and_database",
                }
            ],
            "blocker_remediations": [
                {
                    "blocker": "p0a:preflight:required_env_missing:OPENAI_API_KEY",
                    "work_item_id": "p0a_environment",
                    "mapped": True,
                    "next_command": "make au-p0a-env",
                }
            ],
            "remediation_plan_hash": "plan123",
        }
        with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload) as build_status, patch(
            "geno_api.main.build_au_launch_remediation_plan",
            return_value=plan_payload,
        ) as build_plan:
            response = self.client.get("/v1/launch-remediation-plan/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["remediation_plan_version"], "au_launch_remediation_plan_v1")
        self.assertTrue(payload["remediation_plan_ready"])
        self.assertEqual(payload["next_work_item_id"], "p0a_environment")
        self.assertEqual(payload["summary"]["covered_blocker_count"], 1)
        self.assertEqual(payload["work_items"][0]["verification_commands"][0]["shell"], "make verify-au-p0a-env")
        self.assertEqual(payload["blocker_remediations"][0]["work_item_id"], "p0a_environment")
        build_status.assert_called_once()
        build_plan.assert_called_once()

    def test_au_p0a_environment_checklist_endpoint_returns_redacted_readiness(self) -> None:
        helper = AuP0aEnvironmentChecklistTest()
        with TemporaryDirectory() as temp_dir:
            runbook_path = helper._write_runbook(temp_dir)
            env_path = helper._write_env_report(temp_dir, runbook_path, ready=False)
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0A_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0A_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0A_STATUS_OUTPUT_PATH": str(Path(temp_dir) / "missing-status.json"),
                    "GENO_AU_P0A_ENV_FILE": str(Path(temp_dir) / "missing.env"),
                    "GENO_AU_P0A_ENVIRONMENT_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0a-environment-checklist/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["environment_checklist_version"], "au_p0a_environment_checklist_v1")
        self.assertFalse(payload["environment_checklist_ready"])
        self.assertEqual(payload["next_action"], "populate_required_environment")
        self.assertEqual(payload["summary"]["missing_required_count"], 3)
        self.assertTrue(payload["summary"]["env_file_hygiene_ready"])
        self.assertEqual(payload["summary"]["env_file_hygiene_error_count"], 0)
        self.assertIn("env_file_hygiene", payload)
        self.assertIn("OPENAI_API_KEY", payload["summary"]["missing_required"])
        self.assertIn("hard_env_gate", [command["id"] for command in payload["verification_commands"]])
        self.assertNotIn("raw_value", json.dumps(payload))
        self.assertNotIn("perplexity-key", json.dumps(payload))

    def test_au_p0a_execution_checklist_endpoint_returns_redacted_readiness(self) -> None:
        helper = AuP0aExecutionChecklistTest()
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = helper._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            helper._write_env_report(environment_path, runbook_path, ready=False)
            helper._write_runbook_execution(execution_path, runbook_path, ready=False)
            helper._write_readiness(readiness_path, ready=False)
            helper._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=False,
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0A_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0A_ENV_OUTPUT_PATH": str(environment_path),
                    "GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0A_READINESS_OUTPUT_PATH": str(readiness_path),
                    "GENO_AU_P0A_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0A_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0A_ENV_FILE": str(Path(temp_dir) / "missing.env"),
                    "GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "execution-checklist.json"),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0a-execution-checklist/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_checklist_version"], "au_p0a_execution_checklist_v1")
        self.assertFalse(payload["p0a_execution_checklist_ready"])
        self.assertFalse(payload["ready_for_design_partner"])
        self.assertEqual(payload["next_action"], "configure_required_environment")
        self.assertIn("preflight_json", payload["summary"]["missing_artifacts"])
        self.assertIn("real_batch_phase_handoff", payload)
        self.assertFalse(payload["real_batch_phase_handoff"]["ready"])
        self.assertEqual(payload["real_batch_phase_handoff"]["next_phase"], "preflight")
        self.assertEqual(payload["summary"]["real_batch_phase_handoff_next_phase"], "preflight")
        self.assertIn("hard_status_gate", [command["id"] for command in payload["verification_commands"]])
        self.assertNotIn("raw_value", json.dumps(payload))
        self.assertNotIn("perplexity-key", json.dumps(payload))

    def test_au_p0b_google_execution_checklist_endpoint_returns_redacted_readiness(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0b-google-execution-checklist/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["execution_checklist_version"], "au_p0b_google_execution_checklist_v1")
        self.assertFalse(payload["google_execution_checklist_ready"])
        self.assertFalse(payload["google_main_scoring_allowed"])
        self.assertEqual(payload["next_action"], "populate_google_playwright_smoke_environment")
        self.assertEqual(payload["summary"]["remaining_blocker_count"], 7)
        self.assertTrue(payload["summary"]["env_file_hygiene_ready"])
        self.assertEqual(payload["summary"]["env_file_hygiene_error_count"], 0)
        self.assertFalse(payload["summary"]["environment_handoff_ready"])
        self.assertEqual(payload["summary"]["environment_handoff_missing_required_count"], 5)
        self.assertTrue(payload["summary"]["environment_handoff_secret_redacted"])
        self.assertIn("environment_handoff", payload)
        self.assertIn(
            "smoke_env:GOOGLE_PLAYWRIGHT_ENABLED",
            payload["environment_handoff"]["missing_required"],
        )
        self.assertIn("manual_backfill_handoff", payload)
        self.assertFalse(payload["manual_backfill_handoff"]["ready"])
        self.assertEqual(payload["manual_backfill_handoff"]["expected_record_count"], 120)
        self.assertEqual(payload["manual_backfill_handoff"]["record_count"], 0)
        self.assertIn("manual_backfill:file_missing", payload["manual_backfill_handoff"]["missing_reasons"])
        self.assertFalse(payload["manual_backfill_handoff"]["redaction_policy"]["raw_answer_values_allowed"])
        self.assertTrue(payload["summary"]["manual_backfill_handoff_content_redacted"])
        self.assertIn("google_spike_phase_handoff", payload)
        self.assertFalse(payload["google_spike_phase_handoff"]["ready"])
        self.assertEqual(payload["google_spike_phase_handoff"]["next_phase"], "environment")
        self.assertEqual(payload["google_spike_phase_handoff"]["blocked_phase_count"], 6)
        self.assertEqual(payload["google_spike_phase_handoff"]["full_spike_planned_runs"], 240)
        self.assertIn("env_file_hygiene", payload)
        self.assertIn("google_aio_prompt_selector", payload["summary"]["missing_selector_groups"])
        self.assertIn("hard_package_gate", [command["id"] for command in payload["verification_commands"]])
        self.assertNotIn("raw_value", json.dumps(payload))

    def test_au_p0b_google_environment_request_endpoint_returns_current_handoff_packet(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            p0a_env_path = _write_p0a_env_report_with_database(temp_dir)
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0A_ENV_OUTPUT_PATH": str(p0a_env_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "environment-request.json"
                    ),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0b-google-environment-request/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_environment_request_packet_version"],
            "au_p0b_google_environment_request_packet_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["google_environment_request_packet_ready"])
        self.assertFalse(payload["environment_handoff_ready"])
        self.assertFalse(payload["google_main_scoring_allowed"])
        self.assertEqual(payload["summary"]["target_env_file"], str(Path(temp_dir) / "missing-google.env"))
        self.assertEqual(payload["summary"]["missing_required_count"], len(payload["summary"]["missing_required"]))
        self.assertIn("smoke_env:GOOGLE_PLAYWRIGHT_ENABLED", payload["summary"]["missing_required"])
        self.assertIn("full_run_env:DATABASE_URL", payload["summary"]["missing_required"])
        self.assertIn("selector_group:google_aio_prompt_selector", payload["summary"]["missing_required"])
        self.assertEqual(payload["summary"]["next_command"], "make verify-au-p0b-google-env-template")
        self.assertEqual(payload["summary"]["post_update_verification_command"], "make au-p0b-google-playwright-env")
        self.assertEqual(payload["summary"]["cross_stage_reuse_hint_count"], 1)
        self.assertTrue(payload["summary"]["database_url_reuse_available"])
        self.assertEqual(payload["cross_stage_reuse_hints"][0]["id"], "reuse_p0a_database_url_for_p0b_google")
        self.assertEqual(payload["cross_stage_reuse_hints"][0]["target_missing_id"], "full_run_env:DATABASE_URL")
        self.assertFalse(payload["cross_stage_reuse_hints"][0]["copy_raw_value_required"])
        self.assertTrue(payload["cross_stage_reuse_hints"][0]["secret_redacted"])
        self.assertEqual(payload["source_p0a_env_report"]["path"], str(p0a_env_path))
        self.assertTrue(payload["source_p0a_env_report"]["environment_report_hash"])
        self.assertEqual(payload["p0a_env_report_verifier"]["status"], "pass")
        self.assertTrue(payload["p0a_env_report_verifier"]["hash_valid"])
        self.assertFalse(payload["summary"]["raw_secret_values_allowed"])
        self.assertTrue(payload["summary"]["forbidden_exact_secret_fields_redacted"])
        self.assertIn("make au-p0b-google-env-bootstrap", payload["setup_commands"])
        self.assertIn("make verify-au-p0b-google-playwright-env", payload["verification_commands"])
        self.assertIn("docs/runtime_preflight/au-p0b-google-playwright-env-latest.json", payload["evidence_outputs"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_environment_request"],
            "GET /v1/p0b-google-environment-request/au",
        )
        self.assertIn("make verify-au-p0b-google-environment-request", payload["hard_gate_commands"])
        self.assertTrue(payload["source_p0b_google_execution_checklist"]["google_execution_checklist_hash"])
        self.assertEqual(
            payload["p0b_google_environment_request_packet_hash"],
            compute_p0b_google_environment_request_packet_hash(payload),
        )
        self.assertNotIn("postgres://", json.dumps(payload))
        self.assertEqual(_find_forbidden_exact_fields(payload), [])

    def test_au_p0b_google_environment_fulfillment_endpoint_returns_current_status(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            p0a_env_path = _write_p0a_env_report_with_database(temp_dir)
            fulfillment_path = Path(temp_dir) / "environment-fulfillment.json"
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0A_ENV_OUTPUT_PATH": str(p0a_env_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "environment-request.json"
                    ),
                    "GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH": str(fulfillment_path),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0b-google-environment-fulfillment/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_environment_fulfillment_version"],
            "au_p0b_google_environment_fulfillment_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["environment_fulfillment_ready"])
        self.assertFalse(payload["environment_fulfilled"])
        self.assertFalse(payload["ready_for_playwright_smoke"])
        self.assertEqual(payload["summary"]["missing_required_count"], 6)
        self.assertIn("environment:DATABASE_URL", payload["summary"]["missing_required"])
        self.assertIn("selector:google_aio_prompt_selector", payload["summary"]["missing_required"])
        self.assertTrue(payload["summary"]["database_url_reuse_available"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_environment_fulfillment"],
            "GET /v1/p0b-google-environment-fulfillment/au",
        )
        self.assertIn("make verify-au-p0b-google-environment-fulfillment", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in payload["hard_gate_commands"]))
        self.assertNotIn("postgres://", json.dumps(payload))
        self.assertEqual(_find_forbidden_exact_fields(payload), [])

    def test_au_p0b_google_environment_clearance_endpoint_returns_current_clearance_packet(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            p0a_env_path = _write_p0a_env_report_with_database(temp_dir)
            clearance_helper = AuExternalDependencyClearanceTest()
            clearance_helper.setUp()
            handoff_path = clearance_helper._write_handoff(temp_dir)
            external_clearance_path = Path(temp_dir) / "external-clearance.json"
            external_clearance = run_au_external_dependency_clearance(
                handoff_path=handoff_path,
                output_path=external_clearance_path,
                generated_at="2026-06-14T00:00:00Z",
            )
            clearance_path = Path(temp_dir) / "environment-clearance.json"
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0A_ENV_OUTPUT_PATH": str(p0a_env_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_ENVIRONMENT_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "environment-request.json"
                    ),
                    "GENO_AU_P0B_GOOGLE_ENVIRONMENT_FULFILLMENT_OUTPUT_PATH": str(
                        Path(temp_dir) / "environment-fulfillment.json"
                    ),
                    "GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH": str(handoff_path),
                    "GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH": str(external_clearance_path),
                    "GENO_AU_P0B_GOOGLE_ENVIRONMENT_CLEARANCE_OUTPUT_PATH": str(clearance_path),
                },
                clear=False,
            ), patch("geno_api.main.au_external_dependency_clearance", return_value=external_clearance):
                response = self.client.get("/v1/p0b-google-environment-clearance/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_environment_clearance_version"],
            "au_p0b_google_environment_clearance_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["environment_clearance_packet_ready"])
        self.assertFalse(payload["environment_fulfilled"])
        self.assertFalse(payload["environment_clearance_ready"])
        self.assertFalse(payload["ready_for_next_clearance_step"])
        self.assertTrue(payload["blocked_by_prerequisite_step"])
        self.assertEqual(payload["summary"]["target_clearance_step_id"], "p0b_google_environment")
        self.assertEqual(payload["summary"]["prerequisite_step_id"], "p0a_real_batches")
        self.assertEqual(payload["summary"]["missing_required_count"], 6)
        self.assertIn("environment:DATABASE_URL", payload["summary"]["missing_required"])
        self.assertIn("selector:google_aio_prompt_selector", payload["summary"]["missing_required"])
        self.assertTrue(payload["summary"]["database_url_reuse_available"])
        self.assertEqual(payload["summary"]["next_action"], "clear_p0a_real_batches_first")
        self.assertEqual(payload["summary"]["next_command"], "make au-p0a-real-batch-clearance")
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_environment_clearance"],
            "GET /v1/p0b-google-environment-clearance/au",
        )
        self.assertIn("make verify-au-p0b-google-environment-clearance", payload["hard_gate_commands"])
        self.assertTrue(any("--require-cleared" in command for command in payload["hard_gate_commands"]))
        self.assertTrue(any("--require-fulfilled" in command for command in payload["hard_gate_commands"]))
        self.assertTrue(any("--require-ready-smoke" in command for command in payload["hard_gate_commands"]))
        self.assertEqual(payload["source_artifacts"]["environment_request"]["hash_field"], "p0b_google_environment_request_packet_hash")
        self.assertEqual(payload["source_artifacts"]["playwright_env_report"]["hash_field"], "environment_report_hash")
        self.assertEqual(payload["source_artifacts"]["environment_fulfillment"]["hash_field"], "p0b_google_environment_fulfillment_hash")
        self.assertTrue(payload["source_artifacts"]["environment_request"]["hash_valid"])
        self.assertTrue(payload["source_artifacts"]["playwright_env_report"]["hash_valid"])
        self.assertTrue(payload["source_artifacts"]["environment_fulfillment"]["hash_valid"])
        self.assertIn("clear_p0a_real_batches", {step["id"] for step in payload["operator_steps"]})
        self.assertIn("make au-p0b-google-environment-fulfillment", payload["post_update_validation_sequence"])
        self.assertEqual(
            payload["p0b_google_environment_clearance_hash"],
            compute_p0b_google_environment_clearance_hash(payload),
        )
        self.assertNotIn("postgres://", json.dumps(payload))
        self.assertEqual(_find_forbidden_exact_fields(payload), [])

    def test_au_p0b_google_manual_backfill_request_endpoint_returns_current_handoff_packet(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "manual-backfill-request.json"
                    ),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0b-google-manual-backfill-request/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_manual_backfill_request_packet_version"],
            "au_p0b_google_manual_backfill_request_packet_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["manual_backfill_request_packet_ready"])
        self.assertFalse(payload["manual_backfill_handoff_ready"])
        self.assertFalse(payload["google_main_scoring_allowed"])
        self.assertEqual(payload["summary"]["expected_record_count"], 120)
        self.assertEqual(payload["summary"]["record_count"], 0)
        self.assertEqual(payload["summary"]["expected_prompt_city_count"], 60)
        self.assertEqual(payload["summary"]["covered_prompt_city_count"], 0)
        self.assertIn("manual_backfill:file_missing", payload["summary"]["missing_reasons"])
        self.assertEqual(payload["summary"]["next_command"], "make au-p0b-google-manual-template")
        self.assertEqual(
            payload["summary"]["post_update_verification_command"],
            "make verify-au-p0b-google-manual-backfill",
        )
        self.assertTrue(payload["summary"]["content_redacted"])
        self.assertFalse(payload["summary"]["raw_answer_values_allowed"])
        self.assertFalse(payload["summary"]["raw_citation_values_allowed"])
        self.assertFalse(payload["summary"]["raw_asset_urls_allowed"])
        self.assertIn("answer_text", payload["required_fields"])
        self.assertIn("citation_urls", payload["required_fields"])
        self.assertIn("fill_answer_text_for_each_record", payload["operator_requirements"])
        self.assertIn("make au-p0b-google-manual-template", payload["setup_commands"])
        self.assertIn("make verify-au-p0b-google-manual-backfill", payload["verification_commands"])
        self.assertIn(payload["summary"]["verification_path"], payload["evidence_outputs"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_manual_backfill_request"],
            "GET /v1/p0b-google-manual-backfill-request/au",
        )
        self.assertIn("make verify-au-p0b-google-manual-backfill-request", payload["hard_gate_commands"])
        self.assertTrue(payload["source_p0b_google_execution_checklist"]["google_execution_checklist_hash"])
        self.assertEqual(
            payload["p0b_google_manual_backfill_request_packet_hash"],
            compute_p0b_google_manual_backfill_request_packet_hash(payload),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn("s3://manual-backfill", serialized)

    def test_au_p0b_google_manual_backfill_fulfillment_endpoint_returns_current_status(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "manual-backfill-request.json"
                    ),
                    "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH": str(
                        Path(temp_dir) / "missing-manual-verification.json"
                    ),
                    "MANUAL_BACKFILL_PATH": str(Path(temp_dir) / "missing-manual.jsonl"),
                    "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH": str(
                        Path(temp_dir) / "manual-backfill-fulfillment.json"
                    ),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0b-google-manual-backfill-fulfillment/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_manual_backfill_fulfillment_version"],
            "au_p0b_google_manual_backfill_fulfillment_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["manual_backfill_fulfillment_ready"])
        self.assertFalse(payload["manual_backfill_fulfilled"])
        self.assertFalse(payload["google_main_scoring_allowed"])
        self.assertEqual(payload["summary"]["expected_record_count"], 120)
        self.assertEqual(payload["summary"]["record_count"], 0)
        self.assertEqual(payload["summary"]["covered_prompt_city_count"], 0)
        self.assertIn("verification:status", payload["summary"]["missing_required"])
        self.assertIn("count:record_count", payload["summary"]["missing_required"])
        self.assertIn("manual_backfill_file_missing", payload["summary"]["verification_errors"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_manual_backfill_fulfillment"],
            "GET /v1/p0b-google-manual-backfill-fulfillment/au",
        )
        self.assertIn("make verify-au-p0b-google-manual-backfill-fulfillment", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in payload["hard_gate_commands"]))
        self.assertEqual(
            payload["p0b_google_manual_backfill_fulfillment_hash"],
            compute_p0b_google_manual_backfill_fulfillment_hash(payload),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn("s3://manual-backfill", serialized)

    def test_au_p0b_google_manual_backfill_clearance_endpoint_returns_current_clearance_packet(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            clearance_helper = AuExternalDependencyClearanceTest()
            clearance_helper.setUp()
            handoff_path = clearance_helper._write_handoff(temp_dir)
            external_clearance_path = Path(temp_dir) / "external-clearance.json"
            external_clearance = run_au_external_dependency_clearance(
                handoff_path=handoff_path,
                output_path=external_clearance_path,
                generated_at="2026-06-14T00:00:00Z",
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "manual-backfill-request.json"
                    ),
                    "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_VERIFICATION_PATH": str(
                        Path(temp_dir) / "missing-manual-verification.json"
                    ),
                    "MANUAL_BACKFILL_PATH": str(Path(temp_dir) / "missing-manual.jsonl"),
                    "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_FULFILLMENT_OUTPUT_PATH": str(
                        Path(temp_dir) / "manual-backfill-fulfillment.json"
                    ),
                    "GENO_AU_EXTERNAL_DEPENDENCY_HANDOFF_OUTPUT_PATH": str(handoff_path),
                    "GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH": str(external_clearance_path),
                    "GENO_AU_P0B_GOOGLE_MANUAL_BACKFILL_CLEARANCE_OUTPUT_PATH": str(
                        Path(temp_dir) / "manual-backfill-clearance.json"
                    ),
                },
                clear=False,
            ), patch("geno_api.main.au_external_dependency_clearance", return_value=external_clearance):
                response = self.client.get("/v1/p0b-google-manual-backfill-clearance/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_manual_backfill_clearance_version"],
            "au_p0b_google_manual_backfill_clearance_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["manual_backfill_clearance_packet_ready"])
        self.assertFalse(payload["manual_backfill_fulfilled"])
        self.assertFalse(payload["manual_backfill_clearance_ready"])
        self.assertFalse(payload["ready_for_next_clearance_step"])
        self.assertTrue(payload["blocked_by_prerequisite_step"])
        self.assertEqual(payload["summary"]["target_clearance_step_id"], "p0b_google_manual_backfill")
        self.assertEqual(payload["summary"]["prerequisite_step_id"], "p0b_google_environment")
        self.assertEqual(payload["summary"]["expected_record_count"], 120)
        self.assertEqual(payload["summary"]["record_count"], 0)
        self.assertEqual(payload["summary"]["covered_prompt_city_count"], 0)
        self.assertIn("verification:status", payload["summary"]["missing_required"])
        self.assertIn("count:record_count", payload["summary"]["missing_required"])
        self.assertIn("manual_backfill_file_missing", payload["summary"]["verification_errors"])
        self.assertEqual(payload["summary"]["next_action"], "clear_p0b_google_environment_first")
        self.assertEqual(payload["summary"]["next_command"], "make au-p0b-google-environment-clearance")
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_manual_backfill_clearance"],
            "GET /v1/p0b-google-manual-backfill-clearance/au",
        )
        self.assertIn("make verify-au-p0b-google-manual-backfill-clearance", payload["hard_gate_commands"])
        self.assertTrue(any("--require-cleared" in command for command in payload["hard_gate_commands"]))
        self.assertTrue(any("--require-manual-backfill-ready" in command for command in payload["hard_gate_commands"]))
        self.assertTrue(any("--require-fulfilled" in command for command in payload["hard_gate_commands"]))
        self.assertEqual(
            payload["source_artifacts"]["manual_backfill_request"]["hash_field"],
            "p0b_google_manual_backfill_request_packet_hash",
        )
        self.assertEqual(payload["source_artifacts"]["manual_backfill_verification"]["hash_field"], "verification_hash")
        self.assertEqual(
            payload["source_artifacts"]["manual_backfill_fulfillment"]["hash_field"],
            "p0b_google_manual_backfill_fulfillment_hash",
        )
        self.assertTrue(payload["source_artifacts"]["manual_backfill_request"]["hash_valid"])
        self.assertTrue(payload["source_artifacts"]["manual_backfill_verification"]["hash_valid"])
        self.assertTrue(payload["source_artifacts"]["manual_backfill_fulfillment"]["hash_valid"])
        self.assertIn("clear_p0b_google_environment", {step["id"] for step in payload["operator_steps"]})
        self.assertIn("make verify-au-p0b-google-manual-backfill", payload["post_update_validation_sequence"])
        self.assertEqual(
            payload["p0b_google_manual_backfill_clearance_hash"],
            compute_p0b_google_manual_backfill_clearance_hash(payload),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn("s3://manual-backfill", serialized)
        self.assertEqual(_find_forbidden_exact_fields(payload), [])

    def test_au_p0b_google_phase_execution_request_endpoint_returns_current_phase_handoff_packet(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "phase-execution-request.json"
                    ),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0b-google-phase-execution-request/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_phase_execution_request_packet_version"],
            "au_p0b_google_phase_execution_request_packet_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["phase_execution_request_packet_ready"])
        self.assertFalse(payload["google_spike_phase_handoff_ready"])
        self.assertFalse(payload["google_main_scoring_allowed"])
        self.assertEqual(
            payload["summary"]["phase_order"],
            ["environment", "browser_smoke", "manual_backfill", "health_check", "full_spike", "main_scoring"],
        )
        self.assertEqual(payload["summary"]["phase_count"], 6)
        self.assertEqual(payload["summary"]["next_phase"], "environment")
        self.assertEqual(payload["summary"]["full_spike_planned_runs"], 240)
        self.assertEqual(payload["summary"]["manual_expected_record_count"], 120)
        self.assertIn(
            "environment:environment_handoff:smoke_env:GOOGLE_PLAYWRIGHT_ENABLED",
            payload["summary"]["blocking_reasons"],
        )
        self.assertEqual([phase["id"] for phase in payload["phase_requests"]], payload["summary"]["phase_order"])
        self.assertTrue(payload["phase_requests"][0]["can_start"])
        self.assertEqual(payload["phase_requests"][4]["planned_runs"], 240)
        self.assertIn("make verify-au-p0b-google-playwright-env", payload["phase_commands"])
        self.assertIn("make verify-au-p0b-google-manual-backfill", payload["phase_commands"])
        self.assertIn("make au-p0b-google-package && make verify-au-p0b-google-package", payload["phase_commands"])
        self.assertIn("make au-p0b-google-environment-request", payload["setup_commands"])
        self.assertIn("make au-p0b-google-spike", payload["verification_commands"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_phase_execution_request"],
            "GET /v1/p0b-google-phase-execution-request/au",
        )
        self.assertIn("make verify-au-p0b-google-phase-execution-request", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-google-phases-ready") for command in payload["hard_gate_commands"]))
        self.assertTrue(
            any(command.endswith("--require-google-main-scoring-ready") for command in payload["hard_gate_commands"])
        )
        self.assertTrue(payload["source_p0b_google_execution_checklist"]["google_execution_checklist_hash"])
        self.assertEqual(
            payload["p0b_google_phase_execution_request_packet_hash"],
            compute_p0b_google_phase_execution_request_packet_hash(payload),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)

    def test_au_p0b_google_phase_execution_fulfillment_endpoint_returns_current_status(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "phase-execution-request.json"
                    ),
                    "GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH": str(
                        Path(temp_dir) / "phase-execution-fulfillment.json"
                    ),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0b-google-phase-execution-fulfillment/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_phase_execution_fulfillment_version"],
            "au_p0b_google_phase_execution_fulfillment_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["phase_execution_fulfillment_ready"])
        self.assertFalse(payload["phase_execution_fulfilled"])
        self.assertFalse(payload["google_spike_phase_handoff_ready"])
        self.assertFalse(payload["google_main_scoring_allowed"])
        self.assertEqual(payload["summary"]["phase_count"], 6)
        self.assertEqual(payload["summary"]["next_phase"], "environment")
        self.assertEqual(payload["summary"]["missing_required_count"], 6)
        self.assertTrue(payload["summary"]["source_checklist_hash_aligned"])
        self.assertIn("phase:environment", payload["summary"]["missing_required"])
        self.assertEqual([item["phase_id"] for item in payload["phase_fulfillment_items"]], payload["summary"]["phase_order"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_phase_execution_fulfillment"],
            "GET /v1/p0b-google-phase-execution-fulfillment/au",
        )
        self.assertIn("make verify-au-p0b-google-phase-execution-fulfillment", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in payload["hard_gate_commands"]))
        self.assertEqual(
            payload["p0b_google_phase_execution_fulfillment_hash"],
            compute_p0b_google_phase_execution_fulfillment_hash(payload),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)

    def test_au_p0b_google_phase_execution_clearance_endpoint_returns_current_clearance_packet(self) -> None:
        helper = AuP0bGoogleExecutionChecklistTest()
        helper.setUp()
        clearance_helper = AuExternalDependencyClearanceTest()
        clearance_helper.setUp()
        with TemporaryDirectory() as temp_dir:
            runbook_path, execution_path, env_path, status_path, package_path, _runbook = helper._write_status_and_package(
                temp_dir,
                google_ready=False,
            )
            handoff_path = clearance_helper._write_handoff(temp_dir)
            external_clearance_path = Path(temp_dir) / "external-clearance.json"
            run_au_external_dependency_clearance(
                handoff_path=handoff_path,
                output_path=external_clearance_path,
                generated_at="2026-06-14T00:00:00Z",
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0B_GOOGLE_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0B_GOOGLE_PLAYWRIGHT_ENV_OUTPUT_PATH": str(env_path),
                    "GENO_AU_P0B_GOOGLE_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0B_GOOGLE_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0B_GOOGLE_ENV_FILE": str(Path(temp_dir) / "missing-google.env"),
                    "GENO_AU_P0B_GOOGLE_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "checklist.json"),
                    "GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_REQUEST_OUTPUT_PATH": str(
                        Path(temp_dir) / "phase-execution-request.json"
                    ),
                    "GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_FULFILLMENT_OUTPUT_PATH": str(
                        Path(temp_dir) / "phase-execution-fulfillment.json"
                    ),
                    "GENO_AU_P0B_GOOGLE_PHASE_EXECUTION_CLEARANCE_OUTPUT_PATH": str(
                        Path(temp_dir) / "phase-execution-clearance.json"
                    ),
                    "GENO_AU_EXTERNAL_DEPENDENCY_CLEARANCE_OUTPUT_PATH": str(external_clearance_path),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0b-google-phase-execution-clearance/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0b_google_phase_execution_clearance_version"],
            "au_p0b_google_phase_execution_clearance_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["phase_execution_clearance_packet_ready"])
        self.assertFalse(payload["phase_execution_fulfilled"])
        self.assertFalse(payload["phase_execution_clearance_ready"])
        self.assertFalse(payload["ready_for_next_clearance_step"])
        self.assertTrue(payload["blocked_by_prerequisite_step"])
        self.assertEqual(payload["summary"]["phase_count"], 6)
        self.assertEqual(payload["summary"]["next_phase"], "environment")
        self.assertEqual(payload["summary"]["missing_required_count"], 6)
        self.assertEqual(payload["summary"]["next_action"], "clear_p0b_google_manual_backfill_first")
        self.assertEqual(payload["summary"]["next_command"], "make au-p0b-google-manual-backfill-clearance")
        self.assertIn("phase:environment", payload["summary"]["missing_required"])
        self.assertEqual([item["phase_id"] for item in payload["phase_execution_clearance_items"]], payload["summary"]["phase_order"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_phase_execution_clearance"],
            "GET /v1/p0b-google-phase-execution-clearance/au",
        )
        self.assertIn("make verify-au-p0b-google-phase-execution-clearance", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-cleared") for command in payload["hard_gate_commands"]))
        self.assertEqual(
            payload["p0b_google_phase_execution_clearance_hash"],
            compute_p0b_google_phase_execution_clearance_hash(payload),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("Manual Google AI Mode answer", serialized)
        self.assertNotIn("https://examplebrand.example", serialized)
        self.assertNotIn('"provider_response":', serialized)

    def test_au_p0a_real_batch_request_endpoint_returns_current_phase_handoff_packet(self) -> None:
        helper = AuP0aExecutionChecklistTest()
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = helper._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            helper._write_env_report(environment_path, runbook_path, ready=False)
            helper._write_runbook_execution(execution_path, runbook_path, ready=False)
            helper._write_readiness(readiness_path, ready=False)
            helper._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=False,
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0A_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0A_ENV_OUTPUT_PATH": str(environment_path),
                    "GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0A_READINESS_OUTPUT_PATH": str(readiness_path),
                    "GENO_AU_P0A_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0A_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0A_ENV_FILE": str(Path(temp_dir) / "missing.env"),
                    "GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "execution-checklist.json"),
                    "GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH": str(Path(temp_dir) / "real-batch-request.json"),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0a-real-batch-request/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["p0a_real_batch_request_packet_version"], "au_p0a_real_batch_request_packet_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["real_batch_request_packet_ready"])
        self.assertFalse(payload["real_batch_phase_handoff_ready"])
        self.assertFalse(payload["ready_for_design_partner"])
        self.assertEqual(payload["summary"]["phase_order"], ["preflight", "small_batch", "full_batch"])
        self.assertEqual(payload["summary"]["total_planned_runs"], 2436)
        self.assertEqual(payload["summary"]["next_phase"], "preflight")
        self.assertIn(
            "preflight:credential_handoff_missing_required:OPENAI_API_KEY",
            payload["summary"]["blocking_reasons"],
        )
        self.assertIn("make api-preflight", payload["phase_commands"])
        self.assertTrue(
            any("run_collection_slice.py --mode api --prompt-limit 5" in command for command in payload["phase_commands"])
        )
        self.assertTrue(
            any(
                "run_collection_slice.py --mode api --prompt-limit 100" in command
                for command in payload["phase_commands"]
            )
        )
        self.assertEqual(payload["runtime_endpoints"]["p0a_real_batch_request"], "GET /v1/p0a-real-batch-request/au")
        self.assertIn("make verify-au-p0a-real-batch-request", payload["hard_gate_commands"])
        self.assertTrue(payload["source_p0a_execution_checklist"]["p0a_execution_checklist_hash"])
        self.assertEqual(
            payload["p0a_real_batch_request_packet_hash"],
            compute_p0a_real_batch_request_packet_hash(payload),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("perplexity-key", serialized)

    def test_au_p0a_real_batch_fulfillment_endpoint_returns_current_status(self) -> None:
        helper = AuP0aExecutionChecklistTest()
        with TemporaryDirectory() as temp_dir:
            runbook_path, _runbook = helper._write_runbook(temp_dir)
            environment_path = Path(temp_dir) / "environment.json"
            execution_path = Path(temp_dir) / "execution.json"
            readiness_path = Path(temp_dir) / "readiness.json"
            package_path = Path(temp_dir) / "package.json"
            status_path = Path(temp_dir) / "status.json"
            helper._write_env_report(environment_path, runbook_path, ready=False)
            helper._write_runbook_execution(execution_path, runbook_path, ready=False)
            helper._write_readiness(readiness_path, ready=False)
            helper._write_package_and_status(
                runbook_path=runbook_path,
                environment_path=environment_path,
                execution_path=execution_path,
                readiness_path=readiness_path,
                package_path=package_path,
                status_path=status_path,
                ready=False,
            )
            with patch.dict(
                os.environ,
                {
                    "GENO_AU_P0A_RUNBOOK_OUTPUT_PATH": str(runbook_path),
                    "GENO_AU_P0A_ENV_OUTPUT_PATH": str(environment_path),
                    "GENO_AU_P0A_RUNBOOK_EXECUTION_OUTPUT_PATH": str(execution_path),
                    "GENO_AU_P0A_READINESS_OUTPUT_PATH": str(readiness_path),
                    "GENO_AU_P0A_PACKAGE_OUTPUT_PATH": str(package_path),
                    "GENO_AU_P0A_STATUS_OUTPUT_PATH": str(status_path),
                    "GENO_AU_P0A_ENV_FILE": str(Path(temp_dir) / "missing.env"),
                    "GENO_AU_P0A_EXECUTION_CHECKLIST_OUTPUT_PATH": str(Path(temp_dir) / "execution-checklist.json"),
                    "GENO_AU_P0A_REAL_BATCH_REQUEST_OUTPUT_PATH": str(Path(temp_dir) / "real-batch-request.json"),
                    "GENO_AU_P0A_REAL_BATCH_FULFILLMENT_OUTPUT_PATH": str(Path(temp_dir) / "real-batch-fulfillment.json"),
                },
                clear=False,
            ):
                response = self.client.get("/v1/p0a-real-batch-fulfillment/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["p0a_real_batch_fulfillment_version"], "au_p0a_real_batch_fulfillment_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["real_batch_fulfillment_ready"])
        self.assertFalse(payload["real_batches_fulfilled"])
        self.assertFalse(payload["ready_for_design_partner"])
        self.assertEqual(payload["summary"]["phase_order"], ["preflight", "small_batch", "full_batch"])
        self.assertEqual(payload["summary"]["total_planned_runs"], 2436)
        self.assertEqual(payload["summary"]["next_phase"], "preflight")
        self.assertEqual(payload["summary"]["missing_required_count"], 3)
        self.assertTrue(payload["summary"]["source_checklist_hash_aligned"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_real_batch_fulfillment"],
            "GET /v1/p0a-real-batch-fulfillment/au",
        )
        self.assertIn("make verify-au-p0a-real-batch-fulfillment", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in payload["hard_gate_commands"]))
        self.assertEqual(
            payload["p0a_real_batch_fulfillment_hash"],
            compute_p0a_real_batch_fulfillment_hash(payload),
        )
        serialized = json.dumps(payload)
        self.assertNotIn("raw_value", serialized)
        self.assertNotIn("perplexity-key", serialized)

    def test_au_p0a_real_batch_clearance_endpoint_returns_current_clearance_packet(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/p0a-real-batch-clearance/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["p0a_real_batch_clearance_version"], "au_p0a_real_batch_clearance_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["real_batch_clearance_packet_ready"])
        self.assertFalse(payload["real_batches_fulfilled"])
        self.assertFalse(payload["real_batch_clearance_ready"])
        self.assertFalse(payload["ready_for_next_clearance_step"])
        self.assertTrue(payload["blocked_by_prerequisite_step"])
        self.assertEqual(payload["summary"]["phase_order"], ["preflight", "small_batch", "full_batch"])
        self.assertEqual(payload["summary"]["total_planned_runs"], 2436)
        self.assertEqual(payload["summary"]["next_phase"], "preflight")
        self.assertEqual(payload["summary"]["next_action"], "clear_p0a_provider_credentials_first")
        self.assertEqual(payload["summary"]["next_command"], "make au-p0a-credential-clearance")
        self.assertEqual(payload["summary"]["target_clearance_step_id"], "p0a_real_batches")
        self.assertEqual(payload["summary"]["prerequisite_step_id"], "p0a_provider_credentials")
        self.assertEqual(payload["summary"]["missing_required_count"], 3)
        self.assertIn("phase:preflight", payload["summary"]["missing_required"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_real_batch_clearance"],
            "GET /v1/p0a-real-batch-clearance/au",
        )
        self.assertIn("make verify-au-p0a-real-batch-clearance", payload["hard_gate_commands"])
        self.assertTrue(any("--require-cleared" in command for command in payload["hard_gate_commands"]))
        self.assertTrue(any("--require-fulfilled" in command for command in payload["hard_gate_commands"]))
        self.assertTrue(any("--require-design-partner-ready" in command for command in payload["hard_gate_commands"]))
        self.assertEqual(payload["source_artifacts"]["real_batch_request"]["hash_field"], "p0a_real_batch_request_packet_hash")
        self.assertEqual(payload["source_artifacts"]["real_batch_fulfillment"]["hash_field"], "p0a_real_batch_fulfillment_hash")
        self.assertTrue(payload["source_artifacts"]["real_batch_request"]["hash_valid"])
        self.assertTrue(payload["source_artifacts"]["real_batch_fulfillment"]["hash_valid"])
        self.assertIn("clear_p0a_provider_credentials", {step["id"] for step in payload["operator_steps"]})
        self.assertIn("make au-p0a-real-batch-fulfillment", payload["post_update_validation_sequence"])
        self.assertEqual(payload["p0a_real_batch_clearance_hash"], compute_p0a_real_batch_clearance_hash(payload))

    def test_au_broader_platform_registry_endpoint_returns_disabled_candidates(self) -> None:
        response = self.client.get("/v1/au-broader-platform-registry")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["registry_version"], "au_broader_platform_registry_v1")
        self.assertTrue(payload["broader_platform_registry_ready"])
        self.assertEqual(payload["summary"]["candidate_count"], 6)
        self.assertEqual(payload["summary"]["enabled_candidate_count"], 0)
        self.assertEqual(set(payload["summary"]["p0a_enabled_platform_surfaces"]), {"chatgpt:chatgpt_search", "perplexity:sonar"})
        self.assertEqual(payload["candidate_platforms"][0]["id"], "gemini_ai_search")
        self.assertEqual(payload["candidate_platforms"][-1]["id"], "productreview_au_reviews")
        self.assertTrue(all(candidate["enabled"] is False for candidate in payload["candidate_platforms"]))
        self.assertTrue(payload["broader_platform_registry_hash"])

    def test_au_handoff_dossier_endpoint_returns_runtime_handoff_summary(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/handoff-dossier/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["handoff_dossier_version"], "au_handoff_dossier_v1")
        self.assertTrue(payload["handoff_dossier_ready"])
        self.assertFalse(payload["ready_for_customer_report_handoff"])
        self.assertEqual(payload["summary"]["handoff_posture"], "blocked_external_dependencies")
        self.assertEqual(payload["summary"]["next_work_item_id"], "p0a_environment")
        self.assertGreater(payload["summary"]["remaining_blocker_count"], 0)
        self.assertEqual(
            payload["summary"]["remaining_blocker_count"],
            payload["customer_handoff_readiness_audit"]["remaining_blocker_count"],
        )
        self.assertEqual(payload["summary"]["unmapped_blocker_count"], 0)
        self.assertEqual(
            payload["customer_handoff_readiness_audit"]["audit_version"],
            "au_customer_handoff_readiness_audit_v1",
        )
        self.assertFalse(payload["customer_handoff_readiness_audit"]["customer_report_handoff_ready"])
        self.assertEqual(payload["customer_handoff_readiness_audit"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(payload["customer_handoff_readiness_audit"]["customer_ready_gate_count"], 1)
        self.assertEqual(payload["customer_handoff_readiness_audit"]["customer_total_gate_count"], 10)
        self.assertEqual(payload["customer_handoff_readiness_audit"]["structural_auditability_percent"], 100.0)
        self.assertIn(
            "customer_report_handoff_gate",
            payload["customer_handoff_readiness_audit"]["blocked_customer_gate_ids"],
        )
        self.assertTrue(payload["summary"]["p0a_env_file_hygiene_ready"])
        self.assertEqual(payload["summary"]["p0a_env_file_hygiene_error_count"], 0)
        self.assertTrue(payload["summary"]["p0b_google_env_file_hygiene_ready"])
        self.assertEqual(payload["summary"]["p0b_google_env_file_hygiene_error_count"], 0)
        self.assertEqual(payload["runtime_endpoints"]["launch_status"], "GET /v1/launch-status/au")
        self.assertEqual(payload["runtime_endpoints"]["launch_remediation_plan"], "GET /v1/launch-remediation-plan/au")
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_environment_checklist"],
            "GET /v1/p0a-environment-checklist/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_execution_checklist"],
            "GET /v1/p0a-execution-checklist/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_execution_checklist"],
            "GET /v1/p0b-google-execution-checklist/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["project_lifecycle_events"],
            "GET /v1/projects/runtime/lifecycle-events?project_id={project_id}",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["project_lifecycle_events_export"],
            "GET /v1/projects/runtime/lifecycle-events/export.csv?project_id={project_id}",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["runtime_audit_events"],
            "GET /v1/audit-events/runtime?project_id={project_id}",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["runtime_audit_events_export"],
            "GET /v1/audit-events/runtime/export.csv?project_id={project_id}",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["external_dependency_handoff"],
            "GET /v1/external-dependency-handoff/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["external_dependency_clearance"],
            "GET /v1/external-dependency-clearance/au",
        )
        self.assertIn("p0a_environment_checklist", payload)
        self.assertGreater(payload["p0a_environment_checklist"]["missing_required_count"], 0)
        self.assertEqual(
            payload["summary"]["p0a_missing_required_environment_count"],
            payload["p0a_environment_checklist"]["missing_required_count"],
        )
        self.assertTrue(payload["p0a_environment_checklist"]["env_file_hygiene_ready"])
        self.assertEqual(payload["p0a_environment_checklist"]["env_file_hygiene_error_count"], 0)
        self.assertIn("p0a_execution_checklist", payload)
        self.assertGreater(payload["p0a_execution_checklist"]["remaining_blocker_count"], 0)
        self.assertEqual(
            payload["summary"]["p0a_execution_remaining_blocker_count"],
            payload["p0a_execution_checklist"]["remaining_blocker_count"],
        )
        self.assertFalse(payload["p0a_execution_checklist"]["credential_handoff_ready"])
        self.assertGreater(payload["p0a_execution_checklist"]["credential_handoff_missing_required_count"], 0)
        self.assertTrue(payload["p0a_execution_checklist"]["credential_handoff_secret_redacted"])
        self.assertFalse(payload["summary"]["p0a_credential_handoff_ready"])
        self.assertEqual(
            payload["summary"]["p0a_credential_handoff_missing_required_count"],
            payload["p0a_execution_checklist"]["credential_handoff_missing_required_count"],
        )
        self.assertTrue(payload["summary"]["p0a_credential_handoff_secret_redacted"])
        self.assertFalse(payload["p0a_execution_checklist"]["real_batch_phase_handoff_ready"])
        self.assertEqual(payload["p0a_execution_checklist"]["real_batch_phase_handoff_next_phase"], "preflight")
        self.assertFalse(payload["summary"]["p0a_real_batch_phase_handoff_ready"])
        self.assertEqual(payload["summary"]["p0a_real_batch_phase_handoff_next_phase"], "preflight")
        self.assertIn("p0b_google_execution_checklist", payload)
        self.assertEqual(payload["p0b_google_execution_checklist"]["remaining_blocker_count"], 7)
        self.assertTrue(payload["p0b_google_execution_checklist"]["env_file_hygiene_ready"])
        self.assertEqual(payload["p0b_google_execution_checklist"]["env_file_hygiene_error_count"], 0)
        self.assertFalse(payload["p0b_google_execution_checklist"]["environment_handoff_ready"])
        self.assertEqual(payload["p0b_google_execution_checklist"]["environment_handoff_missing_required_count"], 5)
        self.assertTrue(payload["p0b_google_execution_checklist"]["environment_handoff_secret_redacted"])
        self.assertFalse(payload["summary"]["p0b_google_environment_handoff_ready"])
        self.assertEqual(payload["summary"]["p0b_google_environment_handoff_missing_required_count"], 5)
        self.assertTrue(payload["summary"]["p0b_google_environment_handoff_secret_redacted"])
        self.assertFalse(payload["p0b_google_execution_checklist"]["manual_backfill_handoff_ready"])
        self.assertEqual(payload["p0b_google_execution_checklist"]["manual_backfill_handoff_expected_record_count"], 120)
        self.assertEqual(payload["p0b_google_execution_checklist"]["manual_backfill_handoff_record_count"], 0)
        self.assertEqual(payload["p0b_google_execution_checklist"]["manual_backfill_handoff_missing_reason_count"], 1)
        self.assertFalse(payload["summary"]["p0b_google_manual_backfill_handoff_ready"])
        self.assertEqual(payload["summary"]["p0b_google_manual_backfill_handoff_expected_record_count"], 120)
        self.assertEqual(payload["summary"]["p0b_google_manual_backfill_handoff_record_count"], 0)
        self.assertEqual(payload["summary"]["p0b_google_manual_backfill_handoff_missing_reason_count"], 1)
        self.assertTrue(payload["summary"]["p0b_google_manual_backfill_handoff_content_redacted"])
        self.assertFalse(payload["p0b_google_execution_checklist"]["google_spike_phase_handoff_ready"])
        self.assertEqual(payload["p0b_google_execution_checklist"]["google_spike_phase_handoff_next_phase"], "environment")
        self.assertEqual(payload["p0b_google_execution_checklist"]["google_spike_phase_handoff_blocked_phase_count"], 6)
        self.assertFalse(payload["summary"]["p0b_google_spike_phase_handoff_ready"])
        self.assertEqual(payload["summary"]["p0b_google_spike_phase_handoff_next_phase"], "environment")
        self.assertEqual(payload["summary"]["p0b_google_spike_phase_handoff_blocked_phase_count"], 6)
        self.assertEqual(payload["next_work_item"]["id"], "p0a_environment")
        self.assertEqual(payload["markdown_report"]["media_type"], "text/markdown; charset=utf-8")
        self.assertTrue(payload["handoff_dossier_hash"])

    def test_au_customer_handoff_readiness_endpoint_returns_standalone_readiness_summary(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/customer-handoff-readiness/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["customer_handoff_readiness_version"], "au_customer_handoff_readiness_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["readiness_audit_ready"])
        self.assertFalse(payload["ready_for_customer_report_handoff"])
        self.assertEqual(payload["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(payload["summary"]["structural_auditability_percent"], 100.0)
        self.assertEqual(payload["summary"]["blocked_customer_gate_count"], 9)
        self.assertEqual(payload["summary"]["next_work_item_id"], "p0a_environment")
        self.assertGreater(payload["summary"]["remaining_blocker_count"], 0)
        self.assertEqual(
            payload["summary"]["remaining_blocker_count"],
            payload["handoff_dossier_verifier"]["remaining_blocker_count"],
        )
        self.assertEqual(
            payload["runtime_endpoints"]["customer_handoff_readiness"],
            "GET /v1/customer-handoff-readiness/au",
        )
        self.assertEqual(payload["runtime_endpoints"]["handoff_dossier"], "GET /v1/handoff-dossier/au")
        self.assertIn("make verify-au-customer-handoff-readiness", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-customer-ready") for command in payload["hard_gate_commands"]))
        self.assertTrue(payload["source_handoff_dossier"]["handoff_dossier_hash"])
        self.assertTrue(payload["customer_handoff_readiness_hash"])

    def test_au_next_work_item_endpoint_returns_current_execution_packet(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/next-work-item/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["next_work_item_packet_version"], "au_next_work_item_packet_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["next_work_item_packet_ready"])
        self.assertFalse(payload["ready_for_customer_report_handoff"])
        self.assertEqual(payload["summary"]["next_work_item_id"], "p0a_environment")
        self.assertEqual(payload["summary"]["stage"], "P0a")
        self.assertEqual(payload["summary"]["dependency_class"], "provider_keys_and_database")
        self.assertGreater(payload["summary"]["remaining_blocker_count"], 0)
        self.assertEqual(
            payload["summary"]["remaining_blocker_count"],
            payload["handoff_dossier_verifier"]["remaining_blocker_count"],
        )
        self.assertEqual(payload["summary"]["command_count"], len(payload["commands"]))
        self.assertEqual(payload["summary"]["verification_command_count"], len(payload["verification_commands"]))
        self.assertEqual(payload["summary"]["evidence_output_count"], len(payload["evidence_outputs"]))
        self.assertEqual(payload["summary"]["group_command_count"], len(payload["execution_context"]["group_commands"]))
        self.assertEqual(
            payload["summary"]["group_verification_command_count"],
            len(payload["execution_context"]["group_verification_commands"]),
        )
        self.assertEqual(
            payload["summary"]["group_evidence_output_count"],
            len(payload["execution_context"]["group_evidence_outputs"]),
        )
        self.assertEqual(payload["summary"]["linked_dependency_group_id"], "p0a_provider_credentials")
        self.assertEqual(payload["summary"]["linked_dependency_group_status"], "requires_external_input")
        self.assertEqual(payload["summary"]["linked_dependency_group_next_command"], "make au-p0a-env")
        self.assertGreater(payload["summary"]["linked_dependency_group_blocking_reason_count"], 0)
        self.assertEqual(payload["summary"]["linked_request_packet_id"], "p0a_credential_request")
        self.assertEqual(payload["summary"]["linked_request_artifact_type"], "request_packet")
        self.assertEqual(payload["execution_context"]["execution_context_version"], "au_next_work_item_execution_context_v1")
        self.assertEqual(payload["execution_context"]["linked_dependency_group"]["id"], "p0a_provider_credentials")
        self.assertEqual(payload["execution_context"]["linked_dependency_group"]["source"], "external_dependency_handoff")
        self.assertEqual(payload["execution_context"]["linked_dependency_group"]["status"], "requires_external_input")
        self.assertEqual(
            payload["execution_context"]["linked_dependency_group"]["next_command"],
            "make au-p0a-env",
        )
        self.assertTrue(payload["execution_context"]["linked_dependency_group"]["env_file_hygiene_exists"])
        self.assertTrue(payload["execution_context"]["linked_dependency_group"]["env_file_hygiene_ready"])
        self.assertGreater(payload["execution_context"]["linked_dependency_group"]["blocking_reason_count"], 0)
        self.assertEqual(payload["execution_context"]["linked_request_packet"]["request_packet_id"], "p0a_credential_request")
        self.assertEqual(payload["execution_context"]["linked_request_packet"]["artifact_type"], "request_packet")
        self.assertEqual(
            payload["execution_context"]["linked_request_packet"]["runtime_endpoint"],
            "GET /v1/p0a-credential-request/au",
        )
        self.assertIn("make au-p0a-credential-request", payload["execution_context"]["recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-request", payload["execution_context"]["recommended_sequence"])
        self.assertIn("make au-p0a-credential-fulfillment", payload["execution_context"]["recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", payload["execution_context"]["recommended_sequence"])
        self.assertIn("make au-p0a-credential-clearance", payload["execution_context"]["recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-clearance", payload["execution_context"]["recommended_sequence"])
        self.assertIn("make au-p0a-credential-update-receipt", payload["execution_context"]["recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["execution_context"]["recommended_sequence"])
        self.assertTrue(
            any(command.endswith("--require-fulfilled") for command in payload["execution_context"]["recommended_sequence"])
        )
        self.assertTrue(
            any(command.endswith("--require-cleared") for command in payload["execution_context"]["recommended_sequence"])
        )
        self.assertTrue(
            any(command.endswith("--require-complete") for command in payload["execution_context"]["recommended_sequence"])
        )
        self.assertEqual(payload["summary"]["recommended_sequence_count"], 26)
        self.assertEqual(payload["commands"][0], "make au-p0a-env")
        self.assertIn("make au-p0a-env-bootstrap", payload["commands"])
        self.assertIn("make verify-au-p0a-status", payload["verification_commands"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", payload["verification_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", payload["verification_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["verification_commands"])
        self.assertIn("docs/runtime_preflight/au-p0a-env-bootstrap-latest.json", payload["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-env-latest.json", payload["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-credential-fulfillment-latest.json", payload["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-credential-clearance-latest.json", payload["evidence_outputs"])
        self.assertIn("docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json", payload["evidence_outputs"])
        self.assertEqual(payload["runtime_endpoints"]["next_work_item"], "GET /v1/next-work-item/au")
        self.assertEqual(payload["runtime_endpoints"]["handoff_dossier"], "GET /v1/handoff-dossier/au")
        self.assertIn("make verify-au-next-work-item", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-request", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-customer-ready") for command in payload["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-credentials-ready") for command in payload["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-fulfilled") for command in payload["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-cleared") for command in payload["hard_gate_commands"]))
        self.assertTrue(any(command.endswith("--require-complete") for command in payload["hard_gate_commands"]))
        self.assertTrue(payload["source_handoff_dossier"]["handoff_dossier_hash"])
        self.assertTrue(payload["next_work_item_packet_hash"])

    def test_au_delivery_progress_endpoint_returns_current_machine_readable_progress(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/delivery-progress/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["delivery_progress_version"], "au_delivery_progress_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["delivery_progress_ready"])
        self.assertFalse(payload["ready_for_customer_report_handoff"])
        self.assertEqual(payload["summary"]["engineering_progress_percent"], 46.2)
        self.assertEqual(payload["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(payload["summary"]["structural_auditability_percent"], 100.0)
        self.assertEqual(payload["summary"]["ready_progress_gate_count"], 6)
        self.assertEqual(payload["summary"]["total_progress_gate_count"], 13)
        self.assertEqual(payload["summary"]["blocked_progress_gate_count"], 7)
        self.assertIn("p0a_credentials_fulfilled", payload["summary"]["blocked_progress_gate_ids"])
        self.assertEqual(payload["summary"]["next_work_item_id"], "p0a_environment")
        self.assertEqual(payload["summary"]["current_clearance_step_id"], "p0a_provider_credentials")
        self.assertEqual(payload["summary"]["next_command"], "make au-p0a-env")
        self.assertFalse(payload["summary"]["p0a_credential_clearance_ready"])
        self.assertFalse(payload["summary"]["p0a_credentials_fulfilled"])
        self.assertTrue(payload["summary"]["p0a_credential_update_receipt_ready"])
        self.assertFalse(payload["summary"]["p0a_credential_update_receipt_complete"])
        self.assertEqual(
            payload["summary"]["p0a_credential_update_receipt_missing_required_count"],
            len(payload["summary"]["p0a_credential_update_receipt_missing_required"]),
        )
        self.assertEqual(
            payload["summary"]["p0a_credential_missing_required_count"],
            len(payload["summary"]["p0a_credential_missing_required"]),
        )
        self.assertIn("PERPLEXITY_API_KEY", payload["summary"]["p0a_credential_missing_required"])
        self.assertIn("OPENAI_API_KEY", payload["summary"]["p0a_credential_missing_required"])
        self.assertFalse(payload["summary"]["p0a_real_batch_clearance_ready"])
        self.assertFalse(payload["summary"]["p0a_real_batches_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0a_real_batch_missing_required_count"], 1)
        self.assertFalse(payload["summary"]["p0b_google_environment_clearance_ready"])
        self.assertFalse(payload["summary"]["p0b_google_environment_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0b_google_environment_missing_required_count"], 1)
        self.assertFalse(payload["summary"]["p0b_google_manual_backfill_clearance_ready"])
        self.assertFalse(payload["summary"]["p0b_google_manual_backfill_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0b_google_manual_backfill_missing_required_count"], 1)
        self.assertFalse(payload["summary"]["p0b_google_phase_execution_clearance_ready"])
        self.assertFalse(payload["summary"]["p0b_google_phase_execution_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0b_google_phase_execution_missing_required_count"], 1)
        self.assertEqual(payload["runtime_endpoints"]["delivery_progress"], "GET /v1/delivery-progress/au")
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_clearance"],
            "GET /v1/p0a-credential-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_real_batch_clearance"],
            "GET /v1/p0a-real-batch-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_environment_clearance"],
            "GET /v1/p0b-google-environment-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_manual_backfill_clearance"],
            "GET /v1/p0b-google-manual-backfill-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_phase_execution_clearance"],
            "GET /v1/p0b-google-phase-execution-clearance/au",
        )
        self.assertIn("make verify-au-delivery-progress", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", payload["hard_gate_commands"])
        self.assertIn("make au-p0a-credential-update-receipt", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["hard_gate_commands"])
        self.assertTrue(any("--require-complete" in command for command in payload["hard_gate_commands"]))
        self.assertIn("make verify-au-p0a-real-batch-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-environment-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-manual-backfill-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-phase-execution-clearance", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-customer-ready") for command in payload["hard_gate_commands"]))
        self.assertEqual(payload["source_artifacts"]["next_work_item"]["hash_field"], "next_work_item_packet_hash")
        self.assertEqual(payload["verifiers"]["next_work_item"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0a_credential_clearance"]["hash_field"],
            "p0a_credential_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0a_credential_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0a_credential_clearance"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0a_credential_update_receipt"]["hash_field"],
            "p0a_credential_update_receipt_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0a_credential_update_receipt"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0a_credential_update_receipt"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0a_real_batch_clearance"]["hash_field"],
            "p0a_real_batch_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0a_real_batch_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0a_real_batch_clearance"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0b_google_environment_clearance"]["hash_field"],
            "p0b_google_environment_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0b_google_environment_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0b_google_environment_clearance"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0b_google_manual_backfill_clearance"]["hash_field"],
            "p0b_google_manual_backfill_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0b_google_manual_backfill_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0b_google_manual_backfill_clearance"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0b_google_phase_execution_clearance"]["hash_field"],
            "p0b_google_phase_execution_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0b_google_phase_execution_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0b_google_phase_execution_clearance"]["status"], "pass")
        self.assertTrue(payload["delivery_progress_hash"])

    def test_au_customer_handoff_clearance_endpoint_returns_final_handoff_clearance_packet(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/customer-handoff-clearance/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["customer_handoff_clearance_version"], "au_customer_handoff_clearance_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["customer_handoff_clearance_packet_ready"])
        self.assertFalse(payload["customer_handoff_ready"])
        self.assertFalse(payload["customer_handoff_clearance_ready"])
        self.assertFalse(payload["ready_for_report_export_handoff"])
        self.assertTrue(payload["blocked_by_prerequisite_step"])
        self.assertEqual(payload["clearance_step"]["id"], "customer_report_handoff_gate")
        self.assertEqual(payload["summary"]["required_count"], 10)
        self.assertEqual(payload["summary"]["fulfilled_required_count"], 1)
        self.assertEqual(payload["summary"]["missing_required_count"], 9)
        self.assertEqual(payload["summary"]["engineering_progress_percent"], 46.2)
        self.assertEqual(payload["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertFalse(payload["summary"]["p0a_credential_clearance_ready"])
        self.assertFalse(payload["summary"]["p0a_credentials_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0a_credential_missing_required_count"], 2)
        self.assertTrue(payload["summary"]["p0a_credential_update_receipt_ready"])
        self.assertFalse(payload["summary"]["p0a_credential_update_receipt_complete"])
        self.assertGreaterEqual(payload["summary"]["p0a_credential_update_receipt_missing_required_count"], 2)
        self.assertFalse(payload["summary"]["p0a_real_batch_clearance_ready"])
        self.assertFalse(payload["summary"]["p0a_real_batches_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0a_real_batch_missing_required_count"], 1)
        self.assertFalse(payload["summary"]["p0b_google_environment_clearance_ready"])
        self.assertFalse(payload["summary"]["p0b_google_environment_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0b_google_environment_missing_required_count"], 1)
        self.assertFalse(payload["summary"]["p0b_google_manual_backfill_clearance_ready"])
        self.assertFalse(payload["summary"]["p0b_google_manual_backfill_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0b_google_manual_backfill_missing_required_count"], 1)
        self.assertFalse(payload["summary"]["p0b_google_phase_execution_clearance_ready"])
        self.assertFalse(payload["summary"]["p0b_google_phase_execution_fulfilled"])
        self.assertGreaterEqual(payload["summary"]["p0b_google_phase_execution_missing_required_count"], 1)
        self.assertEqual(payload["summary"]["next_action"], "clear_customer_handoff_prerequisites_first")
        self.assertEqual(payload["summary"]["next_command"], "make au-p0a-env")
        self.assertIn("customer_gate:customer_report_handoff_gate", payload["summary"]["missing_required"])
        self.assertEqual(
            payload["runtime_endpoints"]["customer_handoff_clearance"],
            "GET /v1/customer-handoff-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_clearance"],
            "GET /v1/p0a-credential-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_real_batch_clearance"],
            "GET /v1/p0a-real-batch-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_environment_clearance"],
            "GET /v1/p0b-google-environment-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_manual_backfill_clearance"],
            "GET /v1/p0b-google-manual-backfill-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0b_google_phase_execution_clearance"],
            "GET /v1/p0b-google-phase-execution-clearance/au",
        )
        self.assertIn("make verify-au-customer-handoff-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-clearance", payload["hard_gate_commands"])
        self.assertIn("make au-p0a-credential-update-receipt", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["hard_gate_commands"])
        self.assertTrue(any("--require-complete" in command for command in payload["hard_gate_commands"]))
        self.assertIn("make verify-au-p0a-real-batch-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-environment-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-manual-backfill-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0b-google-phase-execution-clearance", payload["hard_gate_commands"])
        self.assertTrue(any(command.endswith("--require-cleared") for command in payload["hard_gate_commands"]))
        self.assertEqual(payload["source_artifacts"]["delivery_progress"]["hash_field"], "delivery_progress_hash")
        self.assertTrue(payload["source_artifacts"]["delivery_progress"]["hash_valid"])
        self.assertEqual(
            payload["source_artifacts"]["p0a_credential_clearance"]["hash_field"],
            "p0a_credential_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0a_credential_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0a_credential_clearance"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0a_credential_update_receipt"]["hash_field"],
            "p0a_credential_update_receipt_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0a_credential_update_receipt"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0a_credential_update_receipt"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0a_real_batch_clearance"]["hash_field"],
            "p0a_real_batch_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0a_real_batch_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0a_real_batch_clearance"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0b_google_environment_clearance"]["hash_field"],
            "p0b_google_environment_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0b_google_environment_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0b_google_environment_clearance"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0b_google_manual_backfill_clearance"]["hash_field"],
            "p0b_google_manual_backfill_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0b_google_manual_backfill_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0b_google_manual_backfill_clearance"]["status"], "pass")
        self.assertEqual(
            payload["source_artifacts"]["p0b_google_phase_execution_clearance"]["hash_field"],
            "p0b_google_phase_execution_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0b_google_phase_execution_clearance"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0b_google_phase_execution_clearance"]["status"], "pass")
        self.assertEqual(payload["customer_handoff_clearance_hash"], compute_customer_handoff_clearance_hash(payload))

    def test_au_customer_handoff_package_endpoint_returns_delivery_index(self) -> None:
        response = self.client.get("/v1/customer-handoff-package/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["customer_handoff_package_version"], "au_customer_handoff_package_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["customer_handoff_package_manifest_ready"])
        self.assertFalse(payload["customer_handoff_package_ready"])
        self.assertFalse(payload["ready_for_report_export_handoff"])
        self.assertFalse(payload["ready_for_customer_delivery"])
        self.assertEqual(payload["summary"]["source_artifact_count"], 17)
        self.assertEqual(payload["summary"]["blocked_source_artifact_count"], 0)
        self.assertEqual(payload["summary"]["engineering_progress_percent"], 46.2)
        self.assertEqual(payload["summary"]["customer_report_handoff_readiness_percent"], 10.0)
        self.assertEqual(payload["summary"]["structural_auditability_percent"], 100.0)
        self.assertEqual(payload["summary"]["missing_required_count"], 9)
        self.assertEqual(payload["summary"]["next_command"], "make au-p0a-env")
        self.assertIn("customer_handoff_clearance", payload["source_artifacts"])
        self.assertIn("next_work_item", payload["source_artifacts"])
        self.assertIn("p0a_credential_update_receipt", payload["source_artifacts"])
        self.assertIn("p0c_report_package", payload["source_artifacts"])
        self.assertEqual(
            payload["source_artifacts"]["customer_handoff_clearance"]["hash_field"],
            "customer_handoff_clearance_hash",
        )
        self.assertTrue(payload["source_artifacts"]["customer_handoff_clearance"]["hash_valid"])
        self.assertEqual(payload["source_artifacts"]["next_work_item"]["hash_field"], "next_work_item_packet_hash")
        self.assertTrue(payload["source_artifacts"]["next_work_item"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["next_work_item"]["status"], "pass")
        self.assertEqual(
            payload["summary"]["next_work_item_packet_hash"],
            payload["source_artifacts"]["next_work_item"]["hash"],
        )
        self.assertEqual(
            payload["source_artifacts"]["p0a_credential_update_receipt"]["hash_field"],
            "p0a_credential_update_receipt_hash",
        )
        self.assertTrue(payload["source_artifacts"]["p0a_credential_update_receipt"]["hash_valid"])
        self.assertEqual(payload["verifiers"]["p0a_credential_update_receipt"]["status"], "pass")
        self.assertEqual(
            payload["summary"]["p0a_credential_update_receipt_hash"],
            payload["source_artifacts"]["p0a_credential_update_receipt"]["hash"],
        )
        self.assertEqual(payload["source_artifacts"]["p0c_report_package"]["hash_field"], "package_payload_hash")
        self.assertTrue(payload["source_artifacts"]["p0c_report_package"]["hash_valid"])
        self.assertEqual(
            payload["runtime_endpoints"]["customer_handoff_package"],
            "GET /v1/customer-handoff-package/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertEqual(payload["runtime_endpoints"]["next_work_item"], "GET /v1/next-work-item/au")
        self.assertIn("make au-next-work-item", payload["post_update_validation_sequence"])
        self.assertIn("make verify-au-next-work-item", payload["post_update_validation_sequence"])
        self.assertIn("make au-next-work-item", payload["hard_gate_commands"])
        self.assertIn("make verify-au-next-work-item", payload["hard_gate_commands"])
        self.assertIn("make au-p0a-credential-update-receipt", payload["post_update_validation_sequence"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["post_update_validation_sequence"])
        self.assertIn("make au-p0a-credential-update-receipt", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["hard_gate_commands"])
        self.assertTrue(any("--require-complete" in command for command in payload["hard_gate_commands"]))
        self.assertIn("make verify-au-customer-handoff-package", payload["hard_gate_commands"])
        self.assertEqual(payload["customer_handoff_package_markdown"]["artifact_type"], "markdown")
        self.assertEqual(
            payload["customer_handoff_package_markdown"]["path"],
            "docs/runtime_preflight/au-customer-handoff-package-latest.md",
        )
        self.assertTrue(payload["customer_handoff_package_markdown"]["file_sha256"])
        self.assertFalse(payload["redaction_policy"]["source_payloads_embedded"])
        self.assertTrue(payload["customer_handoff_package_hash"])

    def test_au_p0a_credential_request_endpoint_returns_current_handoff_packet(self) -> None:
        response = self.client.get("/v1/p0a-credential-request/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["p0a_credential_request_packet_version"], "au_p0a_credential_request_packet_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["credential_request_packet_ready"])
        self.assertFalse(payload["credential_handoff_ready"])
        self.assertFalse(payload["ready_for_design_partner"])
        self.assertEqual(payload["summary"]["target_env_file"], ".env.au-p0a")
        self.assertEqual(payload["summary"]["missing_required_count"], len(payload["summary"]["missing_required"]))
        self.assertIn("PERPLEXITY_API_KEY", payload["summary"]["missing_required"])
        self.assertIn("OPENAI_API_KEY", payload["summary"]["missing_required"])
        self.assertEqual(payload["summary"]["next_command"], "make verify-au-p0a-env-template")
        self.assertEqual(payload["summary"]["post_update_verification_command"], "make verify-au-p0a-env-bootstrap")
        self.assertFalse(payload["summary"]["raw_secret_values_allowed"])
        self.assertTrue(payload["summary"]["forbidden_exact_secret_fields_redacted"])
        self.assertIn("make au-p0a-env-bootstrap", payload["setup_commands"])
        self.assertIn("make au-p0a-env", payload["verification_commands"])
        self.assertIn("docs/runtime_preflight/au-p0a-env-latest.json", payload["evidence_outputs"])
        self.assertEqual(payload["runtime_endpoints"]["p0a_credential_request"], "GET /v1/p0a-credential-request/au")
        self.assertIn("make verify-au-p0a-credential-request", payload["hard_gate_commands"])
        self.assertTrue(payload["source_p0a_execution_checklist"]["p0a_execution_checklist_hash"])
        self.assertTrue(payload["p0a_credential_request_packet_hash"])

    def test_au_p0a_credential_fulfillment_endpoint_returns_current_status(self) -> None:
        response = self.client.get("/v1/p0a-credential-fulfillment/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["p0a_credential_fulfillment_version"], "au_p0a_credential_fulfillment_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["credential_fulfillment_ready"])
        self.assertFalse(payload["credentials_fulfilled"])
        self.assertFalse(payload["ready_for_design_partner"])
        self.assertEqual(payload["summary"]["missing_required_count"], len(payload["summary"]["missing_required"]))
        self.assertIn("PERPLEXITY_API_KEY", payload["summary"]["missing_required"])
        self.assertIn("OPENAI_API_KEY", payload["summary"]["missing_required"])
        self.assertEqual(payload["summary"]["next_action"], "populate_required_environment")
        self.assertIn("make verify-au-p0a-credential-fulfillment", payload["verification_commands"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", payload["hard_gate_commands"])
        self.assertTrue(any("--require-fulfilled" in command for command in payload["hard_gate_commands"]))
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_fulfillment"],
            "GET /v1/p0a-credential-fulfillment/au",
        )
        self.assertTrue(payload["source_p0a_credential_request"]["p0a_credential_request_packet_hash"])
        self.assertTrue(payload["source_p0a_env_report"]["environment_report_hash"])
        self.assertTrue(payload["p0a_credential_fulfillment_hash"])

    def test_au_p0a_credential_clearance_endpoint_returns_current_clearance_packet(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/p0a-credential-clearance/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["p0a_credential_clearance_version"], "au_p0a_credential_clearance_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["credential_clearance_packet_ready"])
        self.assertFalse(payload["credentials_fulfilled"])
        self.assertFalse(payload["credential_clearance_ready"])
        self.assertFalse(payload["ready_for_next_clearance_step"])
        self.assertEqual(payload["summary"]["current_clearance_step_id"], "p0a_provider_credentials")
        self.assertTrue(payload["summary"]["clearance_step_matches"])
        self.assertEqual(payload["summary"]["next_action"], "populate_required_p0a_credentials")
        self.assertEqual(payload["summary"]["missing_required_count"], len(payload["summary"]["missing_required"]))
        self.assertIn("PERPLEXITY_API_KEY", payload["summary"]["missing_required"])
        self.assertIn("OPENAI_API_KEY", payload["summary"]["missing_required"])
        self.assertFalse(payload["summary"]["raw_secret_values_allowed"])
        self.assertEqual(
            payload["summary"]["credential_update_contract_version"],
            "au_p0a_credential_update_contract_v1",
        )
        self.assertTrue(payload["summary"]["credential_update_contract_ready"])
        update_contract = payload["credential_update_contract"]
        self.assertEqual(update_contract["version"], "au_p0a_credential_update_contract_v1")
        self.assertTrue(update_contract["ready"])
        self.assertEqual(update_contract["target_env_file"], payload["summary"]["target_env_file"])
        self.assertEqual(
            sorted(update_contract["required_missing_keys"]),
            sorted(payload["summary"]["missing_required"]),
        )
        self.assertFalse(update_contract["raw_values_allowed_in_artifacts"])
        self.assertIn("raw_value", update_contract["forbidden_artifact_fields"])
        self.assertIn("sha256_prefix", update_contract["redacted_record_fields"])
        self.assertIn("make verify-au-p0a-env-template", update_contract["pre_update_commands"])
        self.assertEqual(update_contract["post_update_commands"], payload["post_update_validation_sequence"])
        self.assertTrue(any("--require-fulfilled" in command for command in update_contract["strict_gate_commands"]))
        self.assertTrue(any("--require-cleared" in command for command in update_contract["strict_gate_commands"]))
        self.assertTrue(update_contract["completion_requirements"]["credential_update_receipt_complete"])
        self.assertIn(
            "make verify-au-p0a-credential-update-receipt",
            update_contract["completion_requirements"]["required_verifiers"],
        )
        self.assertTrue(update_contract["current_state"]["ready_to_update"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_clearance"],
            "GET /v1/p0a-credential-clearance/au",
        )
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertIn("make verify-au-p0a-credential-clearance", payload["hard_gate_commands"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["hard_gate_commands"])
        self.assertTrue(any("--require-cleared" in command for command in payload["hard_gate_commands"]))
        self.assertTrue(any("--require-fulfilled" in command for command in payload["hard_gate_commands"]))
        self.assertEqual(payload["source_artifacts"]["credential_request"]["hash_field"], "p0a_credential_request_packet_hash")
        self.assertTrue(payload["source_artifacts"]["credential_request"]["hash_valid"])
        self.assertEqual(
            payload["source_artifacts"]["credential_fulfillment"]["hash_field"],
            "p0a_credential_fulfillment_hash",
        )
        self.assertTrue(payload["source_artifacts"]["credential_fulfillment"]["hash_valid"])
        self.assertEqual(payload["source_artifacts"]["external_dependency_clearance"]["hash_field"], "clearance_execution_hash")
        self.assertIn("populate_missing_credentials", {step["id"] for step in payload["operator_steps"]})
        self.assertIn("make au-p0a-env", payload["post_update_validation_sequence"])
        self.assertIn("make verify-au-p0a-credential-fulfillment", payload["post_update_validation_sequence"])
        self.assertIn("make au-p0a-credential-update-receipt", payload["post_update_validation_sequence"])
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["post_update_validation_sequence"])
        self.assertEqual(payload["p0a_credential_clearance_hash"], compute_p0a_credential_clearance_hash(payload))

    def test_au_p0a_credential_update_receipt_endpoint_returns_redacted_update_receipt(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/p0a-credential-update-receipt/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["p0a_credential_update_receipt_version"],
            "au_p0a_credential_update_receipt_v1",
        )
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["credential_update_receipt_ready"])
        self.assertFalse(payload["credential_update_receipt_complete"])
        self.assertFalse(payload["credentials_fulfilled"])
        self.assertFalse(payload["credential_clearance_ready"])
        self.assertTrue(payload["summary"]["credential_update_receipt_ready"])
        self.assertEqual(payload["summary"]["missing_required_count"], len(payload["summary"]["missing_required"]))
        self.assertIn("PERPLEXITY_API_KEY", payload["summary"]["missing_required"])
        self.assertIn("OPENAI_API_KEY", payload["summary"]["missing_required"])
        self.assertEqual(payload["summary"]["next_command"], "make au-p0a-env")
        self.assertFalse(payload["summary"]["raw_secret_values_allowed"])
        self.assertEqual(
            payload["credential_update_contract"]["version"],
            "au_p0a_credential_update_contract_v1",
        )
        self.assertFalse(payload["credential_update_contract"]["raw_values_allowed_in_artifacts"])
        self.assertIn("gitignored_env_file", payload["credential_update_contract"]["allowed_update_surface_ids"])
        self.assertIn("process_environment", payload["credential_update_contract"]["allowed_update_surface_ids"])
        self.assertEqual(
            payload["runtime_endpoints"]["p0a_credential_update_receipt"],
            "GET /v1/p0a-credential-update-receipt/au",
        )
        self.assertIn("make verify-au-p0a-credential-update-receipt", payload["strict_gate_commands"])
        self.assertTrue(any("--require-complete" in command for command in payload["strict_gate_commands"]))
        self.assertEqual(payload["source_artifacts"]["credential_request"]["hash_field"], "p0a_credential_request_packet_hash")
        self.assertEqual(payload["source_artifacts"]["env_report"]["hash_field"], "environment_report_hash")
        self.assertEqual(payload["source_artifacts"]["credential_fulfillment"]["hash_field"], "p0a_credential_fulfillment_hash")
        self.assertEqual(payload["source_artifacts"]["credential_clearance"]["hash_field"], "p0a_credential_clearance_hash")
        self.assertEqual(payload["verifiers"]["credential_request"]["status"], "pass")
        self.assertEqual(payload["verifiers"]["credential_fulfillment"]["status"], "pass")
        self.assertEqual(payload["verifiers"]["credential_clearance"]["status"], "pass")
        self.assertEqual(
            payload["p0a_credential_update_receipt_hash"],
            compute_p0a_credential_update_receipt_hash(payload),
        )
        self.assertTrue(payload["required_credential_records"])
        for record in payload["required_credential_records"]:
            self.assertTrue(record["secret_redacted"])
            self.assertFalse(record["raw_value_recorded"])
            self.assertNotIn("raw_value", record)
            if record["present"]:
                self.assertGreater(record["value_length"], 0)
                self.assertEqual(len(record["sha256_prefix"]), 12)

    def test_au_external_dependency_handoff_endpoint_returns_current_dependency_boundary(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/external-dependency-handoff/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["external_dependency_handoff_version"], "au_external_dependency_handoff_v1")
        self.assertEqual(payload["status"], "pass")
        self.assertFalse(payload["external_dependency_handoff_ready"])
        self.assertFalse(payload["ready_for_customer_report_handoff"])
        self.assertEqual(payload["summary"]["handoff_posture"], "blocked_external_dependencies")
        self.assertTrue(payload["summary"]["structural_ready"])
        self.assertGreater(payload["summary"]["external_dependency_blocker_count"], 0)
        self.assertEqual(
            payload["summary"]["external_dependency_blocker_count"],
            sum(1 for item in payload["blocker_remediations"] if item["external_dependency"]),
        )
        self.assertGreaterEqual(payload["summary"]["work_item_count"], 8)
        self.assertEqual(payload["summary"]["dependency_group_count"], 5)
        self.assertEqual(payload["summary"]["clearance_step_count"], 6)
        self.assertEqual(payload["summary"]["clearance_current_step_id"], "p0a_provider_credentials")
        self.assertEqual(payload["next_dependency_item_id"], "p0a_environment")
        self.assertEqual(
            payload["summary"]["p0a_required_secret_missing_count"],
            len(payload["summary"]["p0a_required_secret_missing"]),
        )
        self.assertEqual(payload["summary"]["p0a_real_batch_phase_next_phase"], "preflight")
        self.assertEqual(payload["summary"]["p0a_real_batch_total_planned_runs"], 2436)
        self.assertEqual(payload["summary"]["p0b_google_required_input_missing_count"], 6)
        self.assertEqual(payload["summary"]["p0b_google_manual_backfill_expected_record_count"], 120)
        self.assertEqual(payload["summary"]["p0b_google_phase_next_phase"], "environment")
        self.assertEqual(payload["summary"]["p0b_google_full_spike_planned_runs"], 240)
        self.assertEqual(
            [group["id"] for group in payload["dependency_groups"]],
            [
                "p0a_provider_credentials",
                "p0a_real_batches",
                "p0b_google_environment",
                "p0b_google_manual_backfill",
                "p0b_google_phase_execution",
            ],
        )
        dependency_groups_by_id = {group["id"]: group for group in payload["dependency_groups"]}
        self.assertEqual(
            dependency_groups_by_id["p0a_provider_credentials"]["next_command"],
            "make au-p0a-env",
        )
        self.assertTrue(dependency_groups_by_id["p0a_provider_credentials"]["env_file_hygiene_exists"])
        self.assertTrue(dependency_groups_by_id["p0a_provider_credentials"]["env_file_hygiene_ready"])
        self.assertIn(
            "missing_required:OPENAI_API_KEY",
            dependency_groups_by_id["p0a_provider_credentials"]["blocking_reasons"],
        )
        self.assertIn(
            "make api-preflight",
            dependency_groups_by_id["p0a_real_batches"]["commands"],
        )
        self.assertIn(
            "manual_backfill:file_missing",
            dependency_groups_by_id["p0b_google_manual_backfill"]["blocking_reasons"],
        )
        self.assertGreaterEqual(len(dependency_groups_by_id["p0b_google_phase_execution"]["commands"]), 1)
        self.assertIn(
            "make verify-au-p0b-google-phase-execution-fulfillment",
            dependency_groups_by_id["p0b_google_phase_execution"]["verification_commands"],
        )
        self.assertTrue(
            any(
                "--require-fulfilled" in command
                for command in dependency_groups_by_id["p0b_google_phase_execution"]["verification_commands"]
            )
        )
        self.assertIn(
            "docs/runtime_preflight/au-p0b-google-phase-execution-fulfillment-latest.json",
            dependency_groups_by_id["p0b_google_phase_execution"]["evidence_outputs"],
        )
        self.assertEqual(payload["clearance_sequence"]["version"], "au_external_dependency_clearance_sequence_v1")
        self.assertEqual(payload["clearance_sequence"]["current_step_id"], "p0a_provider_credentials")
        self.assertEqual(payload["clearance_sequence"]["next_command"], "make au-p0a-env")
        self.assertEqual(payload["clearance_sequence"]["steps"][-1]["id"], "customer_report_handoff_gate")
        self.assertFalse(payload["redaction_policy"]["raw_secret_values_allowed"])
        self.assertFalse(payload["redaction_policy"]["raw_database_url_allowed"])
        self.assertFalse(payload["redaction_policy"]["raw_selector_values_allowed"])
        self.assertFalse(payload["redaction_policy"]["raw_manual_answer_values_allowed"])
        self.assertEqual(payload["external_dependency_handoff_hash"], compute_external_dependency_handoff_hash(payload))

    def test_au_external_dependency_clearance_endpoint_returns_current_dry_run(self) -> None:
        helper = AuHandoffDossierTest()
        helper.setUp()
        with TemporaryDirectory() as temp_dir:
            launch_status_path, remediation_plan_path = helper._write_launch_status_and_plan(temp_dir, ready=False)
            status_payload = json.loads(launch_status_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(remediation_plan_path.read_text(encoding="utf-8"))
            with patch("geno_api.main._build_au_launch_status_from_env", return_value=status_payload), patch(
                "geno_api.main.build_au_launch_remediation_plan",
                return_value=plan_payload,
            ):
                response = self.client.get("/v1/external-dependency-clearance/au")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["clearance_execution_version"], "au_external_dependency_clearance_execution_v1")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["ready_to_execute"])
        self.assertFalse(payload["external_dependency_handoff_ready"])
        self.assertEqual(payload["clearance_sequence_version"], "au_external_dependency_clearance_sequence_v1")
        self.assertEqual(payload["planned_step_count"], 6)
        self.assertEqual(payload["recorded_step_count"], 6)
        self.assertEqual(payload["blocked_step_count"], 6)
        self.assertEqual(payload["would_execute_step_count"], 1)
        self.assertEqual(payload["current_step_id"], "p0a_provider_credentials")
        self.assertEqual(payload["next_command"], "make au-p0a-env")
        self.assertTrue(payload["clearance_execution_hash"])
        self.assertEqual(
            payload["current_step_request_context"]["request_artifact_id"],
            "p0a_credential_request",
        )
        self.assertEqual(
            payload["current_step_request_context"]["runtime_endpoint"],
            "GET /v1/p0a-credential-request/au",
        )
        self.assertIn("make au-p0a-credential-request", payload["current_recommended_sequence"])
        self.assertIn("make verify-au-p0a-credential-request", payload["current_recommended_sequence"])
        self.assertEqual(
            payload["current_recommended_sequence_count"],
            len(payload["current_recommended_sequence"]),
        )
        self.assertTrue(payload["current_strict_gate_command"].endswith("--require-credentials-ready"))
        self.assertEqual(payload["steps"][0]["status"], "dry_run_ready_to_start")
        self.assertTrue(payload["steps"][0]["would_execute"])
        self.assertEqual(payload["steps"][0]["linked_request_context"]["request_artifact_id"], "p0a_credential_request")
        self.assertIn("make verify-au-p0a-credential-request", payload["hard_gate_commands"])

    def test_metrics_endpoint_exports_request_and_pool_metrics(self) -> None:
        self.client.get("/health")
        with patch(
            "geno_api.main.runtime_postgres_pool_snapshot",
            return_value={
                "enabled": True,
                "max_size": 10,
                "timeout_seconds": 5.0,
                "created": 2,
                "available": 1,
            },
        ):
            response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        body = response.text
        self.assertIn("# TYPE geno_api_requests_total counter", body)
        self.assertIn('geno_api_requests_total{method="GET",path="/health",status="200"} 1', body)
        self.assertIn(
            'geno_api_request_duration_seconds_bucket{method="GET",path="/health",status="200",le="+Inf"} 1',
            body,
        )
        self.assertIn('geno_api_request_duration_seconds_count{method="GET",path="/health",status="200"} 1', body)
        self.assertIn("geno_runtime_postgres_pool_snapshot_ok 1", body)
        self.assertIn("geno_runtime_postgres_pool_enabled 1", body)
        self.assertIn("geno_runtime_postgres_pool_max_size 10", body)
        self.assertIn("geno_runtime_postgres_pool_connections_created 2", body)
        self.assertNotIn('path="/metrics"', body)

    def test_metrics_endpoint_uses_route_path_without_query_values(self) -> None:
        response = self.client.get("/v1/projects/runtime?market_code=AU&limit=5")
        self.assertEqual(response.status_code, 503)

        metrics = self.client.get("/metrics").text

        self.assertIn('geno_api_requests_total{method="GET",path="/v1/projects/runtime",status="503"} 1', metrics)
        self.assertNotIn("market_code", metrics)
        self.assertNotIn("limit=5", metrics)

    def test_runtime_access_log_emits_request_id_and_route_template(self) -> None:
        with self.assertLogs("geno_api.access", level="INFO") as captured:
            response = self.client.get(
                "/v1/projects/runtime?market_code=AU&limit=5",
                headers={"X-GENO-Request-Id": "req-runtime-001"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["X-GENO-Request-Id"], "req-runtime-001")
        payload = json.loads(captured.records[0].getMessage())
        self.assertEqual(payload["event_type"], "runtime_api_request")
        self.assertEqual(payload["log_version"], "runtime_access_log_v1")
        self.assertEqual(payload["request_id"], "req-runtime-001")
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["path"], "/v1/projects/runtime")
        self.assertEqual(payload["route"], "/v1/projects/runtime")
        self.assertEqual(payload["status_code"], 503)
        self.assertIsInstance(payload["duration_ms"], float)
        self.assertNotIn("market_code", captured.records[0].getMessage())

    def test_runtime_access_log_sanitizes_invalid_request_id(self) -> None:
        with self.assertLogs("geno_api.access", level="INFO") as captured:
            response = self.client.get("/health", headers={"X-GENO-Request-Id": "bad request id"})

        response_request_id = response.headers["X-GENO-Request-Id"]
        payload = json.loads(captured.records[0].getMessage())
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["request_id"], response_request_id)
        self.assertNotEqual(response_request_id, "bad request id")
        self.assertEqual(len(response_request_id), 32)
        int(response_request_id, 16)

    def test_shutdown_closes_runtime_postgres_pool(self) -> None:
        with patch("geno_api.main.close_runtime_postgres_pool") as close_pool:
            close_runtime_resources()
        close_pool.assert_called_once_with()

    def test_m1_project_bootstrap_endpoint(self) -> None:
        response = self.client.get("/v1/project-bootstraps/au/dtc-ecommerce")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["project"]["market_code"], "AU")
        self.assertEqual(payload["industry_profile"]["industry_code"], "dtc_ecommerce")
        self.assertEqual(len(payload["competitors"]), 4)
        self.assertEqual(len(payload["prompt_questions"]), 100)
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_bootstrap_created")

    def test_m1_prompt_pack_endpoint(self) -> None:
        response = self.client.get("/v1/prompt-packs/au/dtc-ecommerce")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 100)
        self.assertEqual(payload["market_code"], "AU")
        self.assertEqual(payload["prompt_version"], "au_dtc_ecommerce_v1")

    def test_m2a_collection_plan_endpoint(self) -> None:
        response = self.client.get("/v1/collection-plans/au/p0a")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["planned_runs"], 2400)
        self.assertEqual(payload["sample_size"], 3)
        self.assertEqual(set(payload["platform_surfaces"]), {"chatgpt:chatgpt_search", "perplexity:sonar"})

    def test_m2a_fixture_evidence_slice_endpoint(self) -> None:
        response = self.client.get("/v1/evidence-runs/au/p0a-fixture-slice")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["record_count"], 8)
        first = payload["records"][0]
        self.assertTrue(first["answer_run"]["answer_present"])
        self.assertTrue(first["answer_run"]["surface_triggered"])
        self.assertEqual(len(first["citations"]), 3)
        self.assertEqual(len(first["evidence_assets"]), 2)
        self.assertGreater(first["collection_cost"]["total_cost"], 0)
        self.assertEqual(first["audit_events"][0]["event_type"], "answer_run_collected")

    def test_runtime_project_create_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post("/v1/projects/runtime/au/dtc-ecommerce")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_create_endpoint_accepts_client_configuration(self) -> None:
        class FakeRepository:
            def save_project_bootstrap(self, bootstrap: object) -> None:
                self.bootstrap = bootstrap

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/projects/runtime/au/dtc-ecommerce",
                json={
                    "tenant_name": "Agency Client AU",
                    "project_name": "Koala Mattress GEO Pilot",
                    "target_brand": "Koala",
                    "category": "mattresses",
                    "competitors": ["Emma Sleep", "Sleeping Duck", "Ecosa"],
                    "brand_official_domains": ["koala.com"],
                    "brand_parent_company": "Koala",
                    "brand_product_lines": ["Mattress", "Sofa Bed"],
                    "owner_user_id": "agency-owner",
                },
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["market_code"], "AU")
        self.assertEqual(payload["prompt_count"], 100)
        self.assertEqual(payload["competitor_count"], 3)
        self.assertEqual(payload["bootstrap"]["tenant"]["name"], "Agency Client AU")
        self.assertEqual(payload["bootstrap"]["project"]["name"], "Koala Mattress GEO Pilot")
        self.assertEqual(payload["bootstrap"]["project"]["target_brand"], "Koala")
        self.assertEqual(payload["bootstrap"]["brand"]["official_domains"], ["koala.com"])
        self.assertEqual(payload["bootstrap"]["brand"]["product_lines"], ["Mattress", "Sofa Bed"])
        self.assertEqual(payload["bootstrap"]["members"][0]["user_id"], "agency-owner")

    def test_runtime_project_create_endpoint_uses_actor_as_owner_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def save_project_bootstrap(self, bootstrap: object) -> None:
                self.bootstrap = bootstrap

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/projects/runtime/au/dtc-ecommerce",
                json={
                    "target_brand": "Koala",
                    "category": "mattresses",
                    "competitors": ["Emma Sleep", "Sleeping Duck", "Ecosa"],
                    "owner_user_id": "payload-owner",
                },
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["bootstrap"]["members"][0]["user_id"], "agency-owner")

    def test_runtime_project_create_endpoint_rejects_invalid_competitor_count(self) -> None:
        response = self.client.post(
            "/v1/projects/runtime/au/dtc-ecommerce",
            json={
                "target_brand": "Koala",
                "category": "mattresses",
                "competitors": ["Only One"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("3-5 competitors", response.json()["detail"])

    def test_runtime_projects_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/projects/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_projects_endpoint_passes_project_id_filter(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/projects/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&market_code=AU&limit=2&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_count"], 0)
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["market_code"], "AU")
        self.assertIsNone(fake_repository.kwargs["status"])
        self.assertFalse(fake_repository.kwargs["include_archived"])
        self.assertEqual(fake_repository.kwargs["limit"], 2)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_projects_endpoint_passes_status_and_archive_filters(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/projects/runtime?market_code=AU&status=archived&include_archived=true&limit=2&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.kwargs["market_code"], "AU")
        self.assertEqual(fake_repository.kwargs["status"], "archived")
        self.assertTrue(fake_repository.kwargs["include_archived"])

    def test_runtime_project_update_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def update_runtime_project(self, project: RuntimeProjectUpdateInput) -> RuntimeProject:
                self.project = project
                return RuntimeProject(
                    project={
                        "id": project.project_id,
                        "name": project.name,
                        "market_code": "AU",
                        "industry_code": "dtc_ecommerce",
                        "target_brand": project.target_brand,
                        "category": project.category,
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "status": project.status,
                    },
                    tenant={"id": "tenant-1", "name": "Design Partner AU"},
                    brand=None,
                    competitors=(),
                    prompt_count=100,
                    audit_events=({"event_type": "project_updated", "method_version": "runtime_project_update_v1"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.patch(
                "/v1/projects/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "name": "Koala GEO Pilot",
                    "target_brand": "Koala",
                    "category": "mattresses",
                    "status": "active",
                    "updated_by": "agency-owner",
                    "reason": "refresh client metadata",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project"]["name"], "Koala GEO Pilot")
        self.assertIsInstance(fake_repository.project, RuntimeProjectUpdateInput)
        self.assertEqual(fake_repository.project.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.project.updated_by, "agency-owner")
        self.assertEqual(fake_repository.project.reason, "refresh client metadata")

    def test_runtime_project_update_endpoint_requires_admin_or_owner_role(self) -> None:
        class FakeRepository:
            def __init__(self, role: str) -> None:
                self.role = role
                self.contexts: list[tuple[str | None, str | None]] = []

            def get_project_member_role(self, *, project_id: str, actor_id: str) -> str | None:
                self.role_project_id = project_id
                self.role_actor_id = actor_id
                return self.role

            def set_runtime_project_access_context(self, *, actor_id: str, project_id: str | None = None) -> None:
                self.contexts.append((actor_id, project_id))

            def update_runtime_project(self, project: RuntimeProjectUpdateInput) -> RuntimeProject:
                self.project = project
                return RuntimeProject(
                    project={
                        "id": project.project_id,
                        "name": project.name,
                        "market_code": "AU",
                        "industry_code": "dtc_ecommerce",
                        "target_brand": project.target_brand,
                        "category": project.category,
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "status": project.status,
                    },
                    tenant={"id": "tenant-1", "name": "Design Partner AU"},
                    brand=None,
                    competitors=(),
                    prompt_count=100,
                    audit_events=({"event_type": "project_updated", "method_version": "runtime_project_update_v1"},),
                )

        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        denied_repository = FakeRepository(role="analyst")
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=denied_repository
        ), patch("geno_api.main.close_repository_connection"):
            denied = self.client.patch(
                "/v1/projects/runtime",
                json={"project_id": project_id, "name": "Koala GEO Pilot"},
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(denied.status_code, 403)
        self.assertIn("requires owner, admin", denied.json()["detail"])

        allowed_repository = FakeRepository(role="owner")
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=allowed_repository
        ), patch("geno_api.main.close_repository_connection"):
            allowed = self.client.patch(
                "/v1/projects/runtime",
                json={"project_id": project_id, "name": "Koala GEO Pilot", "updated_by": "payload-user"},
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed_repository.project.updated_by, "agency-owner")
        self.assertEqual(allowed_repository.contexts, [("agency-owner", project_id)])

    def test_runtime_project_action_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def apply_runtime_project_action(self, project_action: RuntimeProjectActionInput) -> RuntimeProject:
                self.project_action = project_action
                return RuntimeProject(
                    project={
                        "id": project_action.project_id,
                        "name": "Koala GEO Pilot",
                        "market_code": "AU",
                        "industry_code": "dtc_ecommerce",
                        "target_brand": "Koala",
                        "category": "mattresses",
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "status": "archived",
                    },
                    tenant={"id": "tenant-1", "name": "Design Partner AU"},
                    brand=None,
                    competitors=(),
                    prompt_count=100,
                    audit_events=({"event_type": "project_archived", "method_version": "runtime_project_archive_v1"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/projects/runtime/action",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "action": "archive",
                    "updated_by": "agency-owner",
                    "reason": "archive stale pilot",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["project"]["status"], "archived")
        self.assertIsInstance(fake_repository.project_action, RuntimeProjectActionInput)
        self.assertEqual(fake_repository.project_action.action, "archive")
        self.assertEqual(fake_repository.project_action.updated_by, "agency-owner")
        self.assertEqual(fake_repository.project_action.reason, "archive stale pilot")

    def test_runtime_project_action_endpoint_requires_admin_or_owner_role(self) -> None:
        class FakeRepository:
            def __init__(self, role: str) -> None:
                self.role = role
                self.contexts: list[tuple[str | None, str | None]] = []

            def get_project_member_role(self, *, project_id: str, actor_id: str) -> str | None:
                self.role_project_id = project_id
                self.role_actor_id = actor_id
                return self.role

            def set_runtime_project_access_context(self, *, actor_id: str, project_id: str | None = None) -> None:
                self.contexts.append((actor_id, project_id))

            def apply_runtime_project_action(self, project_action: RuntimeProjectActionInput) -> RuntimeProject:
                self.project_action = project_action
                return RuntimeProject(
                    project={
                        "id": project_action.project_id,
                        "name": "Koala GEO Pilot",
                        "market_code": "AU",
                        "industry_code": "dtc_ecommerce",
                        "target_brand": "Koala",
                        "category": "mattresses",
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "status": "active",
                    },
                    tenant={"id": "tenant-1", "name": "Design Partner AU"},
                    brand=None,
                    competitors=(),
                    prompt_count=100,
                    audit_events=({"event_type": "project_restored", "method_version": "runtime_project_restore_v1"},),
                )

        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        denied_repository = FakeRepository(role="analyst")
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=denied_repository
        ), patch("geno_api.main.close_repository_connection"):
            denied = self.client.post(
                "/v1/projects/runtime/action",
                json={"project_id": project_id, "action": "restore"},
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(denied.status_code, 403)
        self.assertIn("requires owner, admin", denied.json()["detail"])

        allowed_repository = FakeRepository(role="owner")
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=allowed_repository
        ), patch("geno_api.main.close_repository_connection"):
            allowed = self.client.post(
                "/v1/projects/runtime/action",
                json={"project_id": project_id, "action": "restore", "updated_by": "payload-user"},
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed_repository.project_action.updated_by, "agency-owner")
        self.assertEqual(allowed_repository.contexts, [("agency-owner", project_id)])

    def test_runtime_project_action_endpoint_returns_conflict_for_invalid_lifecycle_state(self) -> None:
        class FakeRepository:
            def apply_runtime_project_action(self, project_action: RuntimeProjectActionInput) -> object:
                raise ValueError("project already archived")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/projects/runtime/action",
                json={"project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c", "action": "archive"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("project already archived", response.json()["detail"])

    def test_runtime_project_lifecycle_events_endpoint_passes_project_filter(self) -> None:
        class FakeRepository:
            def list_runtime_project_lifecycle_events(self, **kwargs: object) -> RuntimeProjectLifecycleEventPage:
                self.kwargs = kwargs
                return RuntimeProjectLifecycleEventPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeProjectLifecycleEvent(
                            lifecycle_event={
                                "id": "event-1",
                                "project_id": kwargs["project_id"],
                                "event_type": "project_archived",
                                "actor_id": "agency-owner",
                                "status_before": "paused",
                                "status_after": "archived",
                            },
                            audit_events=({"event_type": "project_archived", "method_version": "runtime_project_archive_v1"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/projects/runtime/lifecycle-events"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["lifecycle_event"]["event_type"], "project_archived")
        self.assertEqual(payload["records"][0]["lifecycle_event"]["status_before"], "paused")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_project_lifecycle_events_endpoint_checks_access_control(self) -> None:
        class FakeRepository:
            def __init__(self, role: str | None) -> None:
                self.role = role
                self.contexts: list[tuple[str | None, str | None]] = []

            def get_project_member_role(self, *, project_id: str, actor_id: str) -> str | None:
                self.role_project_id = project_id
                self.role_actor_id = actor_id
                return self.role

            def set_runtime_project_access_context(self, *, actor_id: str, project_id: str | None = None) -> None:
                self.contexts.append((actor_id, project_id))

            def list_runtime_project_lifecycle_events(self, **kwargs: object) -> RuntimeProjectLifecycleEventPage:
                self.kwargs = kwargs
                return RuntimeProjectLifecycleEventPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        denied_repository = FakeRepository(role=None)
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=denied_repository
        ), patch("geno_api.main.close_repository_connection"):
            denied = self.client.get(
                f"/v1/projects/runtime/lifecycle-events?project_id={project_id}",
                headers={"X-GENO-Actor-Id": "outsider"},
            )
        self.assertEqual(denied.status_code, 403)

        allowed_repository = FakeRepository(role="viewer")
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=allowed_repository
        ), patch("geno_api.main.close_repository_connection"):
            allowed = self.client.get(
                f"/v1/projects/runtime/lifecycle-events?project_id={project_id}",
                headers={"X-GENO-Actor-Id": "viewer-user"},
            )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed_repository.contexts, [("viewer-user", project_id)])

    def test_runtime_project_lifecycle_events_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_project_lifecycle_events_csv(self, **kwargs: object) -> RuntimeProjectLifecycleEventExport:
                self.kwargs = kwargs
                return RuntimeProjectLifecycleEventExport(
                    export_type="runtime_project_lifecycle_events_csv",
                    filename="runtime-project-lifecycle-events.csv",
                    media_type="text/csv; charset=utf-8",
                    content="audit_event_id,event_type\n7f28023e-977f-4c14-9007-95e7e84db71a,project_archived\n",
                    content_hash="hash-lifecycle-csv",
                    project_id=str(kwargs["project_id"]),
                    method_version="runtime_project_lifecycle_export_v1",
                    total_count=3,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                f"/v1/projects/runtime/lifecycle-events/export.csv?project_id={project_id}&limit=10&offset=2"
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("project_archived", response.text)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-project-lifecycle-export-hash"], "hash-lifecycle-csv")
        self.assertEqual(response.headers["x-geno-project-lifecycle-project-id"], project_id)
        self.assertEqual(response.headers["x-geno-project-lifecycle-method-version"], "runtime_project_lifecycle_export_v1")
        self.assertEqual(response.headers["x-geno-project-lifecycle-row-count"], "1")
        self.assertEqual(response.headers["x-geno-project-lifecycle-total-count"], "3")
        self.assertIn("runtime-project-lifecycle-events.csv", response.headers["content-disposition"])
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["limit"], 10)
        self.assertEqual(fake_repository.kwargs["offset"], 2)

    def test_runtime_audit_events_endpoint_passes_filters_and_checks_access(self) -> None:
        class FakeRepository:
            def __init__(self) -> None:
                self.contexts: list[tuple[str | None, str | None]] = []

            def get_project_member_role(self, *, project_id: str, actor_id: str) -> str | None:
                self.role_project_id = project_id
                self.role_actor_id = actor_id
                return "viewer"

            def set_runtime_project_access_context(self, *, actor_id: str, project_id: str | None = None) -> None:
                self.contexts.append((actor_id, project_id))

            def list_runtime_audit_events(self, **kwargs: object) -> RuntimeAuditEventPage:
                self.kwargs = kwargs
                return RuntimeAuditEventPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    filters={
                        "project_id": str(kwargs["project_id"]),
                        "event_type": str(kwargs["event_type"]),
                        "target_type": str(kwargs["target_type"]),
                        "actor_id": str(kwargs["actor_id"]),
                    },
                    records=(
                        {
                            "audit_event": {
                                "id": "audit-1",
                                "event_type": "runtime_prompts_imported",
                                "target_type": "prompt_import",
                                "actor_id": "agency-owner",
                            }
                        },
                    ),
                )

        fake_repository = FakeRepository()
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get(
                f"/v1/audit-events/runtime?project_id={project_id}"
                "&event_type=runtime_prompts_imported&target_type=prompt_import&actor_id=agency-owner&limit=10&offset=2",
                headers={"X-GENO-Actor-Id": "viewer-user"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["records"][0]["audit_event"]["event_type"], "runtime_prompts_imported")
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["event_type"], "runtime_prompts_imported")
        self.assertEqual(fake_repository.kwargs["target_type"], "prompt_import")
        self.assertEqual(fake_repository.kwargs["actor_id"], "agency-owner")
        self.assertEqual(fake_repository.contexts, [("viewer-user", project_id)])

    def test_runtime_audit_events_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_audit_events_csv(self, **kwargs: object) -> RuntimeAuditEventExport:
                self.kwargs = kwargs
                return RuntimeAuditEventExport(
                    export_type="runtime_audit_events_csv",
                    filename="runtime-audit-events.csv",
                    media_type="text/csv; charset=utf-8",
                    content="audit_event_id,event_type\n7f28023e-977f-4c14-9007-95e7e84db71a,runtime_prompts_imported\n",
                    content_hash="hash-audit-csv",
                    filters={"project_id": str(kwargs["project_id"]), "event_type": str(kwargs["event_type"])},
                    total_count=5,
                    row_count=1,
                    method_version="runtime_audit_events_export_v1",
                )

        fake_repository = FakeRepository()
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                f"/v1/audit-events/runtime/export.csv?project_id={project_id}&event_type=runtime_prompts_imported&limit=10"
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("runtime_prompts_imported", response.text)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-audit-export-hash"], "hash-audit-csv")
        self.assertEqual(response.headers["x-geno-audit-method-version"], "runtime_audit_events_export_v1")
        self.assertEqual(response.headers["x-geno-audit-row-count"], "1")
        self.assertEqual(response.headers["x-geno-audit-total-count"], "5")
        self.assertEqual(response.headers["x-geno-audit-project-id"], project_id)
        self.assertIn("runtime-audit-events.csv", response.headers["content-disposition"])
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["event_type"], "runtime_prompts_imported")
        self.assertEqual(fake_repository.kwargs["limit"], 10)

    def test_runtime_projects_endpoint_requires_actor_when_access_control_enabled(self) -> None:
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}):
            response = self.client.get("/v1/projects/runtime")

        self.assertEqual(response.status_code, 401)
        self.assertIn("X-GENO-Actor-Id", response.json()["detail"])

    def test_runtime_projects_endpoint_requires_jwt_secret_when_jwt_auth_mode_enabled(self) -> None:
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1", "GENO_RUNTIME_AUTH_MODE": "jwt"}, clear=False):
            response = self.client.get("/v1/projects/runtime")

        self.assertEqual(response.status_code, 503)
        self.assertIn("GENO_RUNTIME_JWT_SECRET", response.json()["detail"])

    def test_runtime_projects_endpoint_requires_bearer_jwt_when_jwt_auth_mode_enabled(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ):
            response = self.client.get("/v1/projects/runtime")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Authorization Bearer JWT", response.json()["detail"])

    def test_runtime_projects_endpoint_rejects_invalid_jwt_signature(self) -> None:
        token = self._runtime_jwt(secret="wrong-secret")
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ):
            response = self.client.get("/v1/projects/runtime", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid runtime JWT signature", response.json()["detail"])

    def test_runtime_projects_endpoint_filters_by_actor_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get("/v1/projects/runtime?market_code=AU", headers={"X-GENO-Actor-Id": "agency-owner"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "agency-owner")

    def test_runtime_projects_endpoint_filters_by_jwt_actor_when_jwt_auth_mode_enabled(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        token = self._runtime_jwt(payload={"sub": "jwt-owner"})
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "jwt-owner")

    def test_runtime_projects_endpoint_filters_by_jwks_actor_when_jwks_auth_mode_enabled(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "jwks-owner"})
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": jwks_json,
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "jwks-owner")

    def test_runtime_projects_endpoint_fetches_and_caches_jwks_url(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJwksResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                return json.loads(jwks_json)

        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "remote-jwks-owner"})
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_get(url: str, **kwargs: object) -> FakeJwksResponse:
            calls.append((url, kwargs))
            return FakeJwksResponse()

        jwks_url = "https://idp.example.test/.well-known/jwks.json"
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": jwks_url,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "60",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "remote-jwks-owner")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], jwks_url)
        self.assertEqual(calls[0][1]["timeout"], 1.5)
        self.assertEqual(calls[0][1]["follow_redirects"], True)

    def test_runtime_projects_endpoint_rejects_expired_jwks_cache_without_stale_if_error(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJwksResponse:
            status_code = 200

            def __init__(self, payload: object | None) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                if self.payload is None:
                    raise ValueError("temporary upstream parse failure")
                return self.payload

        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "remote-jwks-owner"})
        jwks_payload = json.loads(jwks_json)
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeJwksResponse:
            calls.append(url)
            return FakeJwksResponse(jwks_payload if len(calls) == 1 else None)

        jwks_url = "https://idp.example.test/.well-known/jwks.json"
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": jwks_url,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "0",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 503)
        self.assertIn("runtime JWKS URL fetch failed", second.json()["detail"])
        self.assertEqual(calls, [jwks_url, jwks_url])

    def test_runtime_projects_endpoint_uses_stale_jwks_on_refresh_error_when_enabled(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJwksResponse:
            status_code = 200

            def __init__(self, payload: object | None) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                if self.payload is None:
                    raise ValueError("temporary upstream parse failure")
                return self.payload

        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "stale-jwks-owner"})
        jwks_payload = json.loads(jwks_json)
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeJwksResponse:
            calls.append(url)
            return FakeJwksResponse(jwks_payload if len(calls) == 1 else None)

        jwks_url = "https://idp.example.test/.well-known/jwks.json"
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": jwks_url,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "0",
                "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS": "60",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "stale-jwks-owner")
        self.assertEqual(calls, [jwks_url, jwks_url])

    def test_runtime_projects_endpoint_discovers_jwks_uri_from_oidc_issuer(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJsonResponse:
            status_code = 200

            def __init__(self, payload: object) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                return self.payload

        issuer = "https://idp.example.test/realms/geno"
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        jwks_url = "https://idp.example.test/realms/geno/protocol/openid-connect/certs"
        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "oidc-owner", "iss": issuer})
        jwks_payload = json.loads(jwks_json)
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_get(url: str, **kwargs: object) -> FakeJsonResponse:
            calls.append((url, kwargs))
            if url == discovery_url:
                return FakeJsonResponse({"issuer": issuer, "jwks_uri": jwks_url})
            if url == jwks_url:
                return FakeJsonResponse(jwks_payload)
            raise AssertionError(f"unexpected runtime auth fetch: {url}")

        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": "",
                "GENO_RUNTIME_JWT_ISSUER": issuer,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "60",
                "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS": "60",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.25",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "oidc-owner")
        self.assertEqual([call[0] for call in calls], [discovery_url, jwks_url])
        self.assertEqual(calls[0][1]["timeout"], 1.25)
        self.assertEqual(calls[1][1]["timeout"], 1.25)
        self.assertEqual(calls[0][1]["follow_redirects"], True)
        self.assertEqual(calls[1][1]["follow_redirects"], True)

    def test_runtime_projects_endpoint_uses_stale_oidc_discovery_and_jwks_on_refresh_error(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> RuntimeProjectPage:
                self.kwargs = kwargs
                return RuntimeProjectPage(total_count=0, limit=int(kwargs["limit"]), offset=int(kwargs["offset"]), records=())

        class FakeJsonResponse:
            status_code = 200

            def __init__(self, payload: object | None) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                if self.payload is None:
                    raise ValueError("temporary upstream parse failure")
                return self.payload

        issuer = "https://idp.example.test/realms/geno"
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        jwks_url = "https://idp.example.test/realms/geno/protocol/openid-connect/certs"
        fake_repository = FakeRepository()
        token, jwks_json = self._runtime_jwks_rs256_token(payload={"sub": "stale-oidc-owner", "iss": issuer})
        jwks_payload = json.loads(jwks_json)
        calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> FakeJsonResponse:
            calls.append(url)
            if len(calls) > 2:
                return FakeJsonResponse(None)
            if url == discovery_url:
                return FakeJsonResponse({"issuer": issuer, "jwks_uri": jwks_url})
            if url == jwks_url:
                return FakeJsonResponse(jwks_payload)
            raise AssertionError(f"unexpected runtime auth fetch: {url}")

        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "",
                "GENO_RUNTIME_JWKS_URL": "",
                "GENO_RUNTIME_JWT_ISSUER": issuer,
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "0",
                "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS": "60",
                "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS": "0",
                "GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS": "60",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.25",
            },
            clear=False,
        ), patch("geno_api.main.httpx.get", side_effect=fake_get), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            first = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})
            second = self.client.get("/v1/projects/runtime?market_code=AU", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(fake_repository.kwargs["actor_id"], "stale-oidc-owner")
        self.assertEqual(calls, [discovery_url, jwks_url, discovery_url, jwks_url])

    def test_runtime_projects_endpoint_rejects_jwks_token_signed_by_untrusted_key(self) -> None:
        token, _ = self._runtime_jwks_rs256_token(payload={"sub": "jwks-owner"}, key_id="runtime-key-1")
        _, trusted_jwks_json = self._runtime_jwks_rs256_token(key_id="runtime-key-1")
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": trusted_jwks_json,
            },
            clear=False,
        ):
            response = self.client.get("/v1/projects/runtime", headers={"Authorization": f"Bearer {token}"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid runtime JWT signature", response.json()["detail"])

    def test_runtime_project_member_save_endpoint_uses_jwt_actor_when_jwt_auth_mode_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "admin"

            def set_runtime_project_access_context(self, **kwargs: object) -> None:
                self.context_kwargs = kwargs

            def save_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(member={"id": "member-1", "project_id": member.project_id}, audit_events=())

        fake_repository = FakeRepository()
        token = self._runtime_jwt(payload={"sub": "jwt-admin"})
        with patch.dict(
            "os.environ",
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "role": "viewer",
                    "updated_by": "payload-user",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "jwt-admin")
        self.assertEqual(fake_repository.context_kwargs["actor_id"], "jwt-admin")
        self.assertEqual(fake_repository.member.updated_by, "jwt-admin")

    def test_runtime_project_members_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/project-members/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_members_endpoint_passes_project_filter(self) -> None:
        class FakeRepository:
            def list_runtime_project_members(self, **kwargs: object) -> RuntimeProjectMemberPage:
                self.kwargs = kwargs
                return RuntimeProjectMemberPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeProjectMember(
                            member={
                                "id": "member-1",
                                "project_id": kwargs["project_id"],
                                "user_id": "analyst@example.com",
                                "role": "analyst",
                            },
                            audit_events=(),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-members/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["records"][0]["member"]["user_id"], "analyst@example.com")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_project_members_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_project_members_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_project_members_csv",
                    filename="runtime-project-members.csv",
                    media_type="text/csv; charset=utf-8",
                    content="member_id,user_id_hash\nmember-1,hash-user\n",
                    content_hash="hash-project-members-csv",
                    filters={"project_id": kwargs["project_id"]},
                    total_count=2,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-members/runtime/export.csv?project_id=project-1&limit=5&offset=1",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-project-member-export-hash"], "hash-project-members-csv")
        self.assertEqual(response.headers["x-geno-project-member-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-project-member-row-count"], "1")
        self.assertEqual(response.headers["x-geno-project-member-total-count"], "2")
        self.assertIn("runtime-project-members.csv", response.headers["content-disposition"])
        self.assertIn("member-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_project_members_endpoint_checks_access_control_when_enabled(self) -> None:
        class FakeRepository:
            def user_can_access_project(self, **kwargs: object) -> bool:
                self.access_kwargs = kwargs
                return False

            def list_runtime_project_members(self, **kwargs: object) -> object:
                raise AssertionError("list_runtime_project_members should not be called when access is denied")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get(
                "/v1/project-members/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(fake_repository.access_kwargs["actor_id"], "agency-owner")

    def test_runtime_project_member_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(
                    member={
                        "id": "member-1",
                        "project_id": member.project_id,
                        "user_id": member.user_id,
                        "role": member.role,
                    },
                    audit_events=(
                        {
                            "event_type": "project_member_saved",
                            "target_type": "project_member",
                            "method_version": "project_member_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "analyst@example.com",
                    "role": "analyst",
                    "updated_by": "agency-owner",
                    "reason": "add analyst",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["member"]["role"], "analyst")
        self.assertEqual(response.json()["audit_events"][0]["event_type"], "project_member_saved")
        self.assertEqual(fake_repository.member.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.member.user_id, "analyst@example.com")
        self.assertEqual(fake_repository.member.role, "analyst")

    def test_runtime_project_member_save_endpoint_uses_actor_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "admin"

            def set_runtime_project_access_context(self, **kwargs: object) -> None:
                self.context_kwargs = kwargs

            def save_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(member={"id": "member-1", "project_id": member.project_id}, audit_events=())

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "role": "viewer",
                    "updated_by": "payload-user",
                },
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-owner")
        self.assertEqual(fake_repository.context_kwargs["actor_id"], "agency-owner")
        self.assertEqual(fake_repository.context_kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.member.updated_by, "agency-owner")

    def test_runtime_project_member_save_endpoint_requires_admin_or_owner_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "analyst"

            def save_runtime_project_member(self, member: object) -> object:
                raise AssertionError("save_runtime_project_member should not be called for analyst role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "role": "viewer",
                },
                headers={"X-GENO-Actor-Id": "agency-analyst"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-analyst")

    def test_runtime_project_member_delete_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def delete_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(
                    member={
                        "id": "member-1",
                        "project_id": member.project_id,
                        "user_id": member.user_id,
                        "role": "viewer",
                    },
                    audit_events=(
                        {
                            "event_type": "project_member_deleted",
                            "target_type": "project_member",
                            "method_version": "project_member_delete_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.request(
                "DELETE",
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "deleted_by": "agency-owner",
                    "reason": "remove viewer",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit_events"][0]["event_type"], "project_member_deleted")
        self.assertEqual(fake_repository.member.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.member.user_id, "viewer@example.com")
        self.assertEqual(fake_repository.member.deleted_by, "agency-owner")

    def test_runtime_project_member_delete_endpoint_uses_actor_and_requires_admin_or_owner_role(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "admin"

            def delete_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                self.member = member
                return RuntimeProjectMember(member={"id": "member-1", "user_id": member.user_id}, audit_events=())

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.request(
                "DELETE",
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                    "deleted_by": "payload-user",
                },
                headers={"X-GENO-Actor-Id": "agency-admin"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-admin")
        self.assertEqual(fake_repository.member.deleted_by, "agency-admin")

    def test_runtime_project_member_delete_endpoint_forbids_viewer_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "viewer"

            def delete_runtime_project_member(self, member: object) -> object:
                raise AssertionError("delete_runtime_project_member should not be called for viewer role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.request(
                "DELETE",
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "viewer@example.com",
                },
                headers={"X-GENO-Actor-Id": "agency-viewer"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-viewer")

    def test_runtime_project_member_delete_endpoint_maps_last_owner_guard_to_400(self) -> None:
        class FakeRepository:
            def delete_runtime_project_member(self, member: object) -> RuntimeProjectMember:
                raise ValueError("cannot remove or downgrade the last project owner")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.request(
                "DELETE",
                "/v1/project-members/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "user_id": "owner@example.com",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("last project owner", response.json()["detail"])

    def test_runtime_project_member_invitations_endpoint_passes_project_filter(self) -> None:
        class FakeRepository:
            def list_runtime_project_member_invitations(self, **kwargs: object) -> RuntimeProjectMemberInvitationPage:
                self.kwargs = kwargs
                return RuntimeProjectMemberInvitationPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeProjectMemberInvitation(
                            invitation={
                                "id": "invite-1",
                                "project_id": kwargs["project_id"],
                                "email": "viewer@example.com",
                                "role": "viewer",
                                "status": kwargs["status"],
                                "invite_token_hash": "hash",
                            },
                            audit_events=(),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-member-invitations/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&status=pending&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["records"][0]["invitation"]["email"], "viewer@example.com")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["status"], "pending")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_project_member_invitations_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_project_member_invitations_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_project_member_invitations_csv",
                    filename="runtime-project-member-invitations.csv",
                    media_type="text/csv; charset=utf-8",
                    content="invitation_id,email_hash\ninvite-1,hash-email\n",
                    content_hash="hash-project-member-invitations-csv",
                    filters={"project_id": kwargs["project_id"], "status": kwargs["status"]},
                    total_count=3,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-member-invitations/runtime/export.csv?project_id=project-1&status=pending&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(
            response.headers["x-geno-project-member-invitation-export-hash"],
            "hash-project-member-invitations-csv",
        )
        self.assertEqual(response.headers["x-geno-project-member-invitation-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-project-member-invitation-status"], "pending")
        self.assertEqual(response.headers["x-geno-project-member-invitation-row-count"], "1")
        self.assertEqual(response.headers["x-geno-project-member-invitation-total-count"], "3")
        self.assertIn("runtime-project-member-invitations.csv", response.headers["content-disposition"])
        self.assertIn("invite-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["status"], "pending")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_project_member_invitations_endpoint_requires_admin_or_owner_role(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "viewer"

            def list_runtime_project_member_invitations(self, **kwargs: object) -> object:
                raise AssertionError("list_runtime_project_member_invitations should not be called for viewer role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get(
                "/v1/project-member-invitations/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c",
                headers={"X-GENO-Actor-Id": "agency-viewer"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-viewer")

    def test_runtime_project_member_invitation_create_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def create_runtime_project_member_invitation(self, invitation: object) -> RuntimeProjectMemberInvitation:
                self.invitation = invitation
                return RuntimeProjectMemberInvitation(
                    invitation={
                        "id": "invite-1",
                        "project_id": invitation.project_id,
                        "email": invitation.email,
                        "role": invitation.role,
                        "status": "pending",
                        "invite_token": "geno-invite-token",
                        "invite_token_hash": "hash",
                    },
                    audit_events=(
                        {
                            "event_type": "project_member_invitation_created",
                            "target_type": "project_member_invitation",
                            "method_version": "project_member_invitation_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-member-invitations/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "email": "Viewer@Example.com",
                    "role": "viewer",
                    "invited_by": "agency-owner",
                    "expires_at": "2026-06-17T00:00:00+00:00",
                    "metadata": {"source": "runtime-console"},
                    "reason": "invite viewer",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["invitation"]["email"], "Viewer@Example.com")
        self.assertEqual(response.json()["audit_events"][0]["event_type"], "project_member_invitation_created")
        self.assertEqual(fake_repository.invitation.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.invitation.email, "Viewer@Example.com")
        self.assertEqual(fake_repository.invitation.role, "viewer")
        self.assertEqual(fake_repository.invitation.invited_by, "agency-owner")
        self.assertEqual(fake_repository.invitation.metadata["source"], "runtime-console")
        self.assertIsNotNone(fake_repository.invitation.expires_at)

    def test_runtime_project_member_invitation_create_endpoint_uses_actor_and_requires_admin_or_owner_role(
        self,
    ) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "admin"

            def set_runtime_project_access_context(self, **kwargs: object) -> None:
                self.context_kwargs = kwargs

            def create_runtime_project_member_invitation(self, invitation: object) -> RuntimeProjectMemberInvitation:
                self.invitation = invitation
                return RuntimeProjectMemberInvitation(
                    invitation={"id": "invite-1", "project_id": invitation.project_id},
                    audit_events=(),
                )

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-member-invitations/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "email": "viewer@example.com",
                    "role": "viewer",
                    "invited_by": "payload-user",
                },
                headers={"X-GENO-Actor-Id": "agency-admin"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-admin")
        self.assertEqual(fake_repository.context_kwargs["actor_id"], "agency-admin")
        self.assertEqual(fake_repository.invitation.invited_by, "agency-admin")

    def test_runtime_project_member_invitation_create_endpoint_rejects_bad_expiry(self) -> None:
        with patch("geno_api.main.build_repository_from_env", return_value=object()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-member-invitations/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "email": "viewer@example.com",
                    "expires_at": "not-a-date",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("expires_at must be ISO-8601 datetime", response.json()["detail"])

    def test_runtime_project_member_invitation_action_endpoint_revokes_invitation(self) -> None:
        class FakeRepository:
            def apply_runtime_project_member_invitation_action(self, action: object) -> RuntimeProjectMemberInvitation:
                self.action = action
                return RuntimeProjectMemberInvitation(
                    invitation={
                        "id": action.invitation_id,
                        "project_id": action.project_id,
                        "email": "viewer@example.com",
                        "role": "viewer",
                        "status": "revoked",
                    },
                    audit_events=(
                        {
                            "event_type": "project_member_invitation_revoked",
                            "target_type": "project_member_invitation",
                            "method_version": "project_member_invitation_action_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-member-invitations/runtime/action",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                    "action": "revoke",
                    "updated_by": "agency-admin",
                    "reason": "wrong email",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["invitation"]["status"], "revoked")
        self.assertEqual(response.json()["audit_events"][0]["event_type"], "project_member_invitation_revoked")
        self.assertEqual(fake_repository.action.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.action.invitation_id, "21a98a17-7930-5504-a6fa-cd08990fbf07")
        self.assertEqual(fake_repository.action.action, "revoke")
        self.assertEqual(fake_repository.action.updated_by, "agency-admin")

    def test_runtime_project_member_invitation_action_endpoint_returns_conflict_for_non_pending_status(self) -> None:
        class FakeRepository:
            def apply_runtime_project_member_invitation_action(self, action: object) -> object:
                raise ValueError("cannot revoke invitation with status revoked")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-member-invitations/runtime/action",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                    "action": "revoke",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("cannot revoke invitation", response.json()["detail"])

    def test_runtime_project_member_invitation_email_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def send_runtime_project_member_invitation_email(self, email_input: object) -> RuntimeProjectMemberInvitation:
                self.email_input = email_input
                return RuntimeProjectMemberInvitation(
                    invitation={
                        "id": email_input.invitation_id,
                        "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                        "email": "viewer@example.com",
                        "role": "viewer",
                        "status": "pending",
                    },
                    audit_events=(
                        {
                            "event_type": "project_member_invitation_email_sent",
                            "target_type": "project_member_invitation",
                            "method_version": "project_member_invitation_email_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-member-invitations/runtime/email",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                    "invite_token": "geno-invite-token",
                    "accept_base_url": "https://app.example.com/invite/accept",
                    "sent_by": "agency-admin",
                    "smtp_env_prefix": "GENO_TEST_SMTP",
                    "subject": "Join GENO",
                    "message": "Please join.",
                    "reason": "send invitation",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit_events"][0]["event_type"], "project_member_invitation_email_sent")
        self.assertEqual(fake_repository.email_input.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.email_input.invite_token, "geno-invite-token")
        self.assertEqual(fake_repository.email_input.accept_base_url, "https://app.example.com/invite/accept")
        self.assertEqual(fake_repository.email_input.smtp_env_prefix, "GENO_TEST_SMTP")
        self.assertEqual(fake_repository.email_input.subject, "Join GENO")
        self.assertEqual(fake_repository.email_input.message, "Please join.")

    def test_runtime_project_member_invitation_email_endpoint_uses_actor_and_requires_admin_or_owner_role(
        self,
    ) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "admin"

            def set_runtime_project_access_context(self, **kwargs: object) -> None:
                self.context_kwargs = kwargs

            def send_runtime_project_member_invitation_email(self, email_input: object) -> RuntimeProjectMemberInvitation:
                self.email_input = email_input
                return RuntimeProjectMemberInvitation(
                    invitation={"id": email_input.invitation_id, "status": "pending"},
                    audit_events=(),
                )

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-member-invitations/runtime/email",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                    "invite_token": "geno-invite-token",
                    "accept_base_url": "https://app.example.com/invite/accept",
                    "sent_by": "payload-user",
                },
                headers={"X-GENO-Actor-Id": "agency-admin"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-admin")
        self.assertEqual(fake_repository.context_kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.email_input.sent_by, "agency-admin")

    def test_runtime_project_member_invitation_email_endpoint_returns_unavailable_for_smtp_failure(self) -> None:
        class FakeRepository:
            def send_runtime_project_member_invitation_email(self, email_input: object) -> object:
                raise RuntimeError("GENO_NOTIFICATION_SMTP_HOST is not configured")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-member-invitations/runtime/email",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                    "invite_token": "geno-invite-token",
                    "accept_base_url": "https://app.example.com/invite/accept",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("SMTP_HOST", response.json()["detail"])

    def test_runtime_project_member_invitation_accept_endpoint_adds_member(self) -> None:
        class FakeRepository:
            def accept_runtime_project_member_invitation(self, invitation: object) -> RuntimeProjectMemberInvitation:
                self.invitation = invitation
                return RuntimeProjectMemberInvitation(
                    invitation={
                        "id": invitation.invitation_id,
                        "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                        "email": "viewer@example.com",
                        "role": "viewer",
                        "status": "accepted",
                        "member": {"user_id": "viewer@example.com", "role": "viewer"},
                    },
                    audit_events=(
                        {"event_type": "project_member_saved"},
                        {"event_type": "project_member_invitation_accepted"},
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-member-invitations/runtime/accept",
                json={
                    "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                    "invite_token": "geno-invite-token",
                    "accepted_by": "viewer@example.com",
                    "reason": "accept invite",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["invitation"]["status"], "accepted")
        self.assertEqual(response.json()["invitation"]["member"]["user_id"], "viewer@example.com")
        self.assertEqual(response.json()["audit_events"][1]["event_type"], "project_member_invitation_accepted")
        self.assertEqual(fake_repository.invitation.invite_token, "geno-invite-token")
        self.assertEqual(fake_repository.invitation.accepted_by, "viewer@example.com")

    def test_runtime_project_member_invitation_accept_endpoint_sets_token_context_when_access_control_enabled(
        self,
    ) -> None:
        class FakeRepository:
            def set_runtime_project_invitation_accept_context(self, **kwargs: object) -> None:
                self.context_kwargs = kwargs

            def accept_runtime_project_member_invitation(self, invitation: object) -> RuntimeProjectMemberInvitation:
                self.invitation = invitation
                return RuntimeProjectMemberInvitation(
                    invitation={"id": invitation.invitation_id, "status": "accepted"},
                    audit_events=(),
                )

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-member-invitations/runtime/accept",
                json={
                    "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                    "invite_token": "geno-invite-token",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            fake_repository.context_kwargs["invite_token_hash"],
            hashlib.sha256("geno-invite-token".encode("utf-8")).hexdigest(),
        )

    def test_runtime_project_member_invitation_accept_endpoint_returns_conflict_for_expired_invitation(self) -> None:
        class FakeRepository:
            def accept_runtime_project_member_invitation(self, invitation: object) -> object:
                raise ValueError("project member invitation expired")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-member-invitations/runtime/accept",
                json={
                    "invitation_id": "21a98a17-7930-5504-a6fa-cd08990fbf07",
                    "invite_token": "geno-invite-token",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("expired", response.json()["detail"])

    def test_runtime_prompts_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/prompts/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompts_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_prompts_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_prompts_csv",
                    filename="runtime-prompts.csv",
                    media_type="text/csv; charset=utf-8",
                    content="prompt_question_id,project_id\nprompt-1,project-1\n",
                    content_hash="hash-prompts-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "market_code": kwargs["market_code"],
                        "intent_type": kwargs["intent_type"],
                        "city": kwargs["city"],
                        "status": kwargs["status"],
                    },
                    total_count=2,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/prompts/runtime/export.csv"
                "?project_id=project-1&market_code=AU&intent_type=brand_awareness&city=Sydney&status=active&limit=5",
                headers={"X-GENO-Actor-Id": "analyst-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("prompt-1", response.text)
        self.assertEqual(response.headers["x-geno-prompt-export-hash"], "hash-prompts-csv")
        self.assertEqual(response.headers["x-geno-prompt-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-prompt-market-code"], "AU")
        self.assertEqual(response.headers["x-geno-prompt-intent-type"], "brand_awareness")
        self.assertEqual(response.headers["x-geno-prompt-city"], "Sydney")
        self.assertEqual(response.headers["x-geno-prompt-status"], "active")
        self.assertEqual(response.headers["x-geno-prompt-row-count"], "1")
        self.assertEqual(response.headers["x-geno-prompt-total-count"], "2")
        self.assertIn('filename="runtime-prompts.csv"', response.headers["content-disposition"])
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["market_code"], "AU")
        self.assertEqual(fake_repository.kwargs["intent_type"], "brand_awareness")
        self.assertEqual(fake_repository.kwargs["city"], "Sydney")
        self.assertEqual(fake_repository.kwargs["status"], "active")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 0)

    def test_runtime_prompts_endpoint_requires_project_id_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def user_can_access_project(self, **kwargs: object) -> bool:
                return True

        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=FakeRepository()
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get("/v1/prompts/runtime", headers={"X-GENO-Actor-Id": "agency-owner"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("project_id is required", response.json()["detail"])

    def test_runtime_prompts_endpoint_forbids_project_without_membership_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def user_can_access_project(self, **kwargs: object) -> bool:
                self.access_kwargs = kwargs
                return False

            def list_runtime_prompts(self, **kwargs: object) -> object:
                raise AssertionError("list_runtime_prompts should not be called when access is denied")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.get(
                "/v1/prompts/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(fake_repository.access_kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.access_kwargs["actor_id"], "agency-owner")

    def test_runtime_prompt_import_endpoint_requires_admin_or_owner_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "viewer"

            def import_runtime_prompts_csv(self, prompt_import: object) -> object:
                raise AssertionError("import_runtime_prompts_csv should not be called for viewer role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/prompts/runtime/import.csv",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "csv_content": "text,intent_type\nIs ExampleBrand visible?,brand_awareness\n",
                    "imported_by": "runtime-console",
                    "max_rows": 100,
                },
                headers={"X-GENO-Actor-Id": "agency-viewer"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-viewer")

    def test_runtime_human_review_save_endpoint_allows_analyst_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "analyst"

            def save_human_review(self, review: object) -> RuntimeHumanReviewRecord:
                self.review = review
                return RuntimeHumanReviewRecord(
                    human_review={
                        "id": "review-1",
                        "project_id": review.project_id,
                        "target_type": review.target_type,
                        "target_id": review.target_id,
                        "review_status": review.review_status,
                        "decision": review.decision,
                        "reviewer_id": review.reviewer_id,
                        "notes": review.notes,
                        "payload": review.payload,
                    },
                    audit_events=({"event_type": "human_review_recorded"},),
                )

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/human-reviews/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "target_type": "visibility_score_snapshot",
                    "target_id": "38f0251c-c380-4197-b6c9-3e630b127844",
                    "review_status": "approved",
                    "decision": "approved_for_report",
                    "reviewer_id": "agency-analyst",
                    "payload": {},
                },
                headers={"X-GENO-Actor-Id": "agency-analyst"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-analyst")
        self.assertEqual(fake_repository.review.decision, "approved_for_report")

    def test_runtime_human_review_save_endpoint_forbids_viewer_role_when_access_control_enabled(self) -> None:
        class FakeRepository:
            def get_project_member_role(self, **kwargs: object) -> str:
                self.role_kwargs = kwargs
                return "viewer"

            def save_human_review(self, review: object) -> object:
                raise AssertionError("save_human_review should not be called for viewer role")

        fake_repository = FakeRepository()
        with patch.dict("os.environ", {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}), patch(
            "geno_api.main.build_repository_from_env", return_value=fake_repository
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/human-reviews/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "target_type": "visibility_score_snapshot",
                    "target_id": "38f0251c-c380-4197-b6c9-3e630b127844",
                    "review_status": "approved",
                    "decision": "approved_for_report",
                    "reviewer_id": "agency-viewer",
                    "payload": {},
                },
                headers={"X-GENO-Actor-Id": "agency-viewer"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("requires owner, admin, analyst", response.json()["detail"])
        self.assertEqual(fake_repository.role_kwargs["actor_id"], "agency-viewer")

    def test_runtime_prompt_import_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/prompts/runtime/import.csv",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "csv_content": "text,intent_type\nIs ExampleBrand visible?,brand_awareness\n",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompt_file_import_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/prompts/runtime/import.file"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&filename=prompts.csv",
            content=b"text,intent_type\nIs ExampleBrand visible?,brand_awareness\n",
            headers={"content-type": "text/csv"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompt_import_history_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/prompts/runtime/imports?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&limit=5"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_prompt_import_history_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_prompt_imports(self, **kwargs: object) -> RuntimePromptImportHistoryPage:
                self.kwargs = kwargs
                return RuntimePromptImportHistoryPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimePromptImportHistoryItem(
                            prompt_import={
                                "id": "prompt-import-1",
                                "project_id": kwargs["project_id"],
                                "source_format": kwargs["source_format"],
                                "source_filename": "prompts.xlsx",
                                "prompt_count": 1,
                                "csv_sha256": "hash",
                            },
                            audit_events=(
                                {
                                    "event_type": "runtime_prompts_imported",
                                    "method_version": "runtime_prompt_import_xlsx_v1",
                                },
                            ),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/prompts/runtime/imports"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&source_format=xlsx&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["prompt_import"]["source_format"], "xlsx")
        self.assertEqual(payload["records"][0]["audit_events"][0]["method_version"], "runtime_prompt_import_xlsx_v1")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["source_format"], "xlsx")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_prompt_import_endpoint_passes_csv_payload(self) -> None:
        class FakeRepository:
            def import_runtime_prompts_csv(self, prompt_import: object) -> RuntimePromptImportResult:
                self.prompt_import = prompt_import
                return RuntimePromptImportResult(
                    prompt_import={
                        "project_id": prompt_import.project_id,
                        "prompt_count": 1,
                        "prompt_ids": ["prompt-1"],
                        "prompt_version": "au_dtc_ecommerce_v1_imported",
                    },
                    prompts=(
                        {
                            "id": "prompt-1",
                            "project_id": prompt_import.project_id,
                            "text": "Is ExampleBrand visible?",
                            "intent_type": "brand_awareness",
                        },
                    ),
                    audit_events=(
                        {
                            "event_type": "runtime_prompts_imported",
                            "target_type": "prompt_import",
                            "method_version": "runtime_prompt_import_csv_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/prompts/runtime/import.csv",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "csv_content": "text,intent_type\nIs ExampleBrand visible?,brand_awareness\n",
                    "imported_by": "runtime-console",
                    "max_rows": 100,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["prompt_import"]["prompt_count"], 1)
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_prompts_imported")
        self.assertEqual(fake_repository.prompt_import.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertIn("Is ExampleBrand visible?", fake_repository.prompt_import.csv_content)

    def test_runtime_prompt_file_import_endpoint_parses_xlsx_payload(self) -> None:
        class FakeRepository:
            def import_runtime_prompts_csv(self, prompt_import: object) -> RuntimePromptImportResult:
                self.prompt_import = prompt_import
                return RuntimePromptImportResult(
                    prompt_import={
                        "project_id": prompt_import.project_id,
                        "prompt_count": 1,
                        "prompt_ids": ["prompt-1"],
                        "prompt_version": "au_dtc_ecommerce_v1_imported",
                        "source_format": prompt_import.source_format,
                        "source_filename": prompt_import.source_filename,
                    },
                    prompts=(
                        {
                            "id": "prompt-1",
                            "project_id": prompt_import.project_id,
                            "text": "Is ExampleBrand visible in AI answers?",
                            "intent_type": "brand_awareness",
                        },
                    ),
                    audit_events=(
                        {
                            "event_type": "runtime_prompts_imported",
                            "target_type": "prompt_import",
                            "method_version": "runtime_prompt_import_xlsx_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/prompts/runtime/import.file"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&filename=prompts.xlsx&imported_by=runtime-console&max_rows=100",
                content=self._xlsx_prompt_import_bytes(),
                headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["prompt_import"]["source_format"], "xlsx")
        self.assertEqual(payload["audit_events"][0]["method_version"], "runtime_prompt_import_xlsx_v1")
        self.assertEqual(fake_repository.prompt_import.source_filename, "prompts.xlsx")
        self.assertEqual(fake_repository.prompt_import.source_format, "xlsx")
        self.assertIn("Is ExampleBrand visible in AI answers?", fake_repository.prompt_import.csv_content)

    def test_runtime_evidence_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/evidence-runs/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_evidence_filter_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_collection_runs_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/collection-runs/runtime?run_type=p0a_slice")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_collection_runs_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_collection_runs(self, **kwargs: object) -> RuntimeCollectionRunPage:
                self.kwargs = kwargs
                return RuntimeCollectionRunPage(
                    total_count=0,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/collection-runs/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&run_type=p0a_slice&limit=2&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_count"], 0)
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["run_type"], "p0a_slice")
        self.assertEqual(fake_repository.kwargs["limit"], 2)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_collection_runs_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_collection_runs_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_collection_runs_csv",
                    filename="runtime-collection-runs.csv",
                    media_type="text/csv; charset=utf-8",
                    content="collection_run_id,project_id\nrun-1,project-1\n",
                    content_hash="hash-collection-runs-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "run_type": kwargs["run_type"],
                    },
                    total_count=2,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/collection-runs/runtime/export.csv?project_id=project-1&run_type=p0a_slice&limit=5",
                headers={"X-GENO-Actor-Id": "analyst-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("run-1", response.text)
        self.assertEqual(response.headers["x-geno-collection-run-export-hash"], "hash-collection-runs-csv")
        self.assertEqual(response.headers["x-geno-collection-run-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-collection-run-type"], "p0a_slice")
        self.assertEqual(response.headers["x-geno-collection-run-row-count"], "1")
        self.assertEqual(response.headers["x-geno-collection-run-total-count"], "2")
        self.assertIn('filename="runtime-collection-runs.csv"', response.headers["content-disposition"])
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["run_type"], "p0a_slice")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 0)

    def test_runtime_fidelity_checks_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/fidelity-checks/runtime?status=not_run")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_fidelity_trend_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/fidelity-checks/runtime/trend?limit=10")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_fidelity_check_create_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/fidelity-checks/runtime",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "checked_by": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_fidelity_checks_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_fidelity_checks(self, **kwargs: object) -> RuntimeFidelityCheckPage:
                self.kwargs = kwargs
                return RuntimeFidelityCheckPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeFidelityCheck(
                            fidelity_check={
                                "id": "9128c59e-54ca-5ceb-9272-3efe226bd07b",
                                "project_id": kwargs["project_id"],
                                "report_export_id": kwargs["report_export_id"],
                                "status": kwargs["status"],
                                "official_api_records": 4,
                                "browser_records": 0,
                                "comparable_prompt_city_pairs": 0,
                                "mismatch_count": 0,
                                "difference_rate": None,
                                "payload_hash": "f" * 64,
                            },
                            audit_events=(
                                {
                                    "event_type": "api_browser_fidelity_checked",
                                    "target_type": "api_browser_fidelity_check",
                                    "method_version": "api_browser_fidelity_check_v1",
                                },
                            ),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/fidelity-checks/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&report_export_id=b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
                "&status=not_run&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "api_browser_fidelity_checked")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad")
        self.assertEqual(fake_repository.kwargs["status"], "not_run")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_fidelity_checks_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_fidelity_checks_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_fidelity_checks_csv",
                    filename="runtime-fidelity-checks.csv",
                    media_type="text/csv; charset=utf-8",
                    content="fidelity_check_id,project_id\ncheck-1,project-1\n",
                    content_hash="hash-fidelity-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "report_export_id": kwargs["report_export_id"],
                        "status": kwargs["status"],
                    },
                    total_count=2,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/fidelity-checks/runtime/export.csv"
                "?project_id=project-1&report_export_id=report-1&status=sampled&limit=5",
                headers={"X-GENO-Actor-Id": "analyst-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("check-1", response.text)
        self.assertEqual(response.headers["x-geno-fidelity-check-export-hash"], "hash-fidelity-csv")
        self.assertEqual(response.headers["x-geno-fidelity-check-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-fidelity-check-report-export-id"], "report-1")
        self.assertEqual(response.headers["x-geno-fidelity-check-status"], "sampled")
        self.assertEqual(response.headers["x-geno-fidelity-check-row-count"], "1")
        self.assertEqual(response.headers["x-geno-fidelity-check-total-count"], "2")
        self.assertIn('filename="runtime-fidelity-checks.csv"', response.headers["content-disposition"])
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "report-1")
        self.assertEqual(fake_repository.kwargs["status"], "sampled")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 0)

    def test_runtime_fidelity_trend_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def get_runtime_fidelity_trend(self, **kwargs: object) -> RuntimeFidelityTrend:
                self.kwargs = kwargs
                return RuntimeFidelityTrend(
                    project_id=kwargs["project_id"],
                    report_export_id=kwargs["report_export_id"],
                    total_count=2,
                    sampled_count=2,
                    limit=int(kwargs["limit"]),
                    latest_status="sampled",
                    latest_checked_at="2026-06-10T01:00:00+00:00",
                    earliest_checked_at="2026-06-10T00:00:00+00:00",
                    latest_difference_rate=0.5,
                    earliest_difference_rate=0.25,
                    average_difference_rate=0.375,
                    max_difference_rate=0.5,
                    trend_direction="worsening",
                    points=(
                        RuntimeFidelityTrendPoint(
                            id="9d0ccf2f-4058-5efd-a3d3-fef60a73191a",
                            project_id=str(kwargs["project_id"]),
                            report_export_id=str(kwargs["report_export_id"]),
                            status="sampled",
                            official_api_records=10,
                            browser_records=10,
                            comparable_prompt_city_pairs=4,
                            mismatch_count=1,
                            difference_rate=0.25,
                            payload_hash="b" * 64,
                            checked_at="2026-06-10T00:00:00+00:00",
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/fidelity-checks/runtime/trend"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&report_export_id=b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
                "&limit=10"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trend_direction"], "worsening")
        self.assertEqual(payload["average_difference_rate"], 0.375)
        self.assertEqual(payload["points"][0]["difference_rate"], 0.25)
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad")
        self.assertEqual(fake_repository.kwargs["limit"], 10)

    def test_runtime_fidelity_check_create_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def create_runtime_fidelity_check(self, **kwargs: object) -> RuntimeFidelityCheck:
                self.kwargs = kwargs
                return RuntimeFidelityCheck(
                    fidelity_check={
                        "id": "9128c59e-54ca-5ceb-9272-3efe226bd07b",
                        "project_id": kwargs["project_id"],
                        "report_export_id": kwargs["report_export_id"],
                        "status": "sampled",
                        "official_api_records": 1,
                        "browser_records": 1,
                        "comparable_prompt_city_pairs": 1,
                        "mismatch_count": 1,
                        "difference_rate": 1.0,
                        "payload_hash": "a" * 64,
                        "checked_by": kwargs["checked_by"],
                    },
                    audit_events=(
                        {
                            "event_type": "api_browser_fidelity_checked",
                            "target_type": "api_browser_fidelity_check",
                            "method_version": "api_browser_fidelity_check_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/fidelity-checks/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "report_export_id": "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad",
                    "checked_by": "runtime-console",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["fidelity_check"]["status"], "sampled")
        self.assertEqual(payload["audit_events"][0]["event_type"], "api_browser_fidelity_checked")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad")
        self.assertEqual(fake_repository.kwargs["checked_by"], "runtime-console")

    def test_runtime_evidence_export_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_manual_backfill_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/evidence-runs/runtime/manual-backfill",
            json={
                "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                "platform": "google",
                "surface": "google_ai_mode",
                "answer_text": "Manual answer",
                "citation_urls": ["https://examplebrand.example/au/manual"],
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_manual_backfill_csv_import_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/evidence-runs/runtime/manual-backfill/import.csv",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "csv_content": "prompt_question_id,answer_text\nf1f8ee6a-cd19-5afc-a053-b4d16a5e56c0,Manual answer",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_manual_backfill_csv_import_returns_batch_audit_summary(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        prompt_one = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        prompt_two = "d05d0df2-b067-5f65-a65b-2fb19054b248"

        class FakeRepository:
            def __init__(self) -> None:
                self.saved_records = ()
                self.prompts = {
                    prompt_one: {
                        "id": prompt_one,
                        "project_id": project_id,
                        "text": "Is ExampleBrand visible in Google AI Mode?",
                        "market_code": "AU",
                        "city": "Sydney",
                        "language": "en-AU",
                    },
                    prompt_two: {
                        "id": prompt_two,
                        "project_id": project_id,
                        "text": "Best DTC ecommerce products for Australian shoppers",
                        "market_code": "AU",
                        "city": "Australia",
                        "language": "en-AU",
                    },
                }

            def get_runtime_prompt(self, prompt_question_id: str):
                return self.prompts.get(prompt_question_id)

            def save_raw_evidence_records(self, records):
                self.saved_records = records

        csv_content = (
            "prompt_question_id,platform,surface,answer_text,citation_urls,screenshot_url,html_snapshot_url,"
            "sample_index,sample_size,device,notes\n"
            f'{prompt_one},google,google_ai_mode,"Manual answer one","https://examplebrand.example/au|'
            'https://reviews.example/manual",s3://manual/one.png,s3://manual/one.html,1,2,desktop,Row note\n'
            f'{prompt_two},google,google_ai_mode,"Manual answer two",https://examplebrand.example/au/manual-2,'
            "s3://manual/two.png,s3://manual/two.html,2,2,desktop,Row note"
        )
        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/evidence-runs/runtime/manual-backfill/import.csv",
                json={
                    "project_id": project_id,
                    "csv_content": csv_content,
                    "submitted_by": "runtime-console",
                    "notes": "Batch import for Google spike manual path",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["import_version"], "manual_backfill_csv_import_v1")
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(payload["imported_count"], 2)
        self.assertEqual(payload["citation_count"], 3)
        self.assertEqual(payload["evidence_asset_count"], 4)
        self.assertEqual(payload["audit_summary"]["event_type"], "manual_backfill_batch_imported")
        self.assertEqual(payload["audit_summary"]["method_version"], "manual_backfill_csv_import_v1")
        self.assertEqual(payload["audit_summary"]["individual_audit_event_type"], "manual_backfill_recorded")
        self.assertEqual(len(fake_repository.saved_records), 2)
        self.assertEqual(fake_repository.saved_records[0].audit_events[0].event_type, "manual_backfill_recorded")
        self.assertEqual(fake_repository.saved_records[0].audit_events[1].event_type, "manual_backfill_batch_imported")
        self.assertEqual(fake_repository.saved_records[0].answer_run.sample_index, 1)
        self.assertEqual(fake_repository.saved_records[1].answer_run.sample_index, 2)
        self.assertEqual(fake_repository.saved_records[0].citations[1].domain, "reviews.example")

    def test_runtime_manual_backfill_csv_import_prevalidates_before_writing(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        prompt_one = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        missing_prompt = "00000000-0000-0000-0000-000000009999"

        class FakeRepository:
            def __init__(self) -> None:
                self.saved_records = ()

            def get_runtime_prompt(self, prompt_question_id: str):
                if prompt_question_id == prompt_one:
                    return {
                        "id": prompt_one,
                        "project_id": project_id,
                        "text": "Is ExampleBrand visible in Google AI Mode?",
                        "market_code": "AU",
                        "city": "Sydney",
                        "language": "en-AU",
                    }
                return None

            def save_raw_evidence_records(self, records):
                self.saved_records = records

        csv_content = (
            "prompt_question_id,answer_text\n"
            f"{prompt_one},Manual answer one\n"
            f"{missing_prompt},Manual answer missing prompt"
        )
        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/evidence-runs/runtime/manual-backfill/import.csv",
                json={
                    "project_id": project_id,
                    "csv_content": csv_content,
                    "submitted_by": "runtime-console",
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["row"], 3)
        self.assertEqual(response.json()["detail"]["error"], "Prompt question not found")
        self.assertEqual(fake_repository.saved_records, ())

    def test_runtime_manual_backfill_csv_import_rejects_cross_project_prompt(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        other_project_id = "11111111-1111-1111-1111-111111111111"
        prompt_one = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"

        class FakeRepository:
            def __init__(self) -> None:
                self.saved_records = ()

            def get_runtime_prompt(self, prompt_question_id: str):
                return {
                    "id": prompt_question_id,
                    "project_id": other_project_id,
                    "text": "Other project prompt",
                    "market_code": "AU",
                    "city": "Sydney",
                    "language": "en-AU",
                }

            def save_raw_evidence_records(self, records):
                self.saved_records = records

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/evidence-runs/runtime/manual-backfill/import.csv",
                json={
                    "project_id": project_id,
                    "csv_content": f"prompt_question_id,answer_text\n{prompt_one},Manual answer",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "prompt does not belong to import project")
        self.assertEqual(response.json()["detail"]["prompt_project_id"], other_project_id)
        self.assertEqual(fake_repository.saved_records, ())

    def test_runtime_entity_aliases_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/entity-aliases/runtime?entity_kind=brand")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_candidates_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/entity-aliases/runtime/candidates?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&entity_kind=brand"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_candidate_review_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/entity-aliases/runtime/candidates/review",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "candidate_id": "candidate-1",
                "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                "entity_kind": "brand",
                "alias": "ExampleBrand AU",
                "alias_type": "alias",
                "decision": "rejected",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_candidate_reviews_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/entity-aliases/runtime/candidates/reviews"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&decision=rejected&entity_kind=brand"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_assignment_stats_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/entity-aliases/runtime/candidates/assignment-stats"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_assignment_workbench_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/entity-aliases/runtime/candidates/assignment-workbench"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&reviewer_id=runtime-console"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_assignment_workload_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/entity-aliases/runtime/candidates/assignment-workload"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_assignment_dispatch_plan_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/entity-aliases/runtime/candidates/assignment-dispatch-plan"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_candidates_endpoint_returns_evidence_metadata(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        entity_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        answer_run_id = "0e6cb35e-340c-55df-9b7c-ed6965b6582d"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def list_runtime_entity_alias_candidates(self, **kwargs):
                self.kwargs = kwargs
                return RuntimeEntityAliasCandidatePage(
                    total_count=1,
                    limit=kwargs["limit"],
                    offset=kwargs["offset"],
                    records=(
                        RuntimeEntityAliasCandidate(
                            candidate={
                                "id": "candidate-1",
                                "entity_id": entity_id,
                                "entity_kind": "brand",
                                "alias": "shop.examplebrand.com.au",
                                "alias_type": "domain",
                                "source": "evidence_citation_domain",
                                "confidence": 0.82,
                                "reason": "domain appears in stored answer citation evidence and matches the entity name",
                                "evidence_count": 2,
                                "evidence_answer_run_ids": [answer_run_id],
                                "evidence_urls": ["https://shop.examplebrand.com.au/mattresses"],
                            },
                            entity={
                                "id": entity_id,
                                "project_id": project_id,
                                "entity_kind": "brand",
                                "canonical_name": "ExampleBrand",
                            },
                            confirmed_aliases=(),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.get(
                f"/v1/entity-aliases/runtime/candidates?project_id={project_id}&entity_kind=brand&limit=10"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        candidate = payload["records"][0]["candidate"]
        self.assertEqual(candidate["source"], "evidence_citation_domain")
        self.assertEqual(candidate["evidence_count"], 2)
        self.assertEqual(candidate["evidence_answer_run_ids"], [answer_run_id])
        self.assertEqual(candidate["evidence_urls"], ["https://shop.examplebrand.com.au/mattresses"])
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)

    def test_runtime_entity_alias_candidate_reviews_endpoint_returns_review_history(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        entity_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def list_entity_alias_candidate_reviews(self, **kwargs):
                self.kwargs = kwargs
                return RuntimeEntityAliasCandidateReviewPage(
                    total_count=1,
                    limit=kwargs["limit"],
                    offset=kwargs["offset"],
                    records=(
                        RuntimeEntityAliasCandidateReview(
                            review={
                                "id": "review-1",
                                "project_id": project_id,
                                "candidate_id": "candidate-1",
                                "entity_id": entity_id,
                                "entity_kind": "brand",
                                "alias": "ExampleBrand AU",
                                "alias_type": "alias",
                                "source": "evidence_answer_text",
                                "confidence": 0.8,
                                "decision": "rejected",
                                "reviewed_by": "analyst-1",
                                "evidence_answer_run_ids": ["answer-run-1"],
                                "evidence_urls": ["https://examplebrand.com.au/reviews"],
                            },
                            audit_events=(
                                {
                                    "event_type": "entity_alias_candidate_review_recorded",
                                    "method_version": "entity_alias_candidate_review_v1",
                                },
                            ),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.get(
                f"/v1/entity-aliases/runtime/candidates/reviews?project_id={project_id}"
                "&decision=rejected&entity_kind=brand&assigned_to=reviewer@example.com"
                "&assignment_status=assigned&priority=high&due_before=2026-06-14T09:00:00Z"
                "&limit=8&offset=2"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["limit"], 8)
        self.assertEqual(payload["offset"], 2)
        self.assertEqual(payload["records"][0]["review"]["decision"], "rejected")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "entity_alias_candidate_review_recorded")
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["decision"], "rejected")
        self.assertEqual(fake_repository.kwargs["entity_kind"], "brand")
        self.assertEqual(fake_repository.kwargs["assigned_to"], "reviewer@example.com")
        self.assertEqual(fake_repository.kwargs["assignment_status"], "assigned")
        self.assertEqual(fake_repository.kwargs["priority"], "high")
        self.assertEqual(fake_repository.kwargs["due_before"].isoformat(), "2026-06-14T09:00:00+00:00")

    def test_runtime_entity_alias_assignment_stats_endpoint_returns_queue_health(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def get_entity_alias_candidate_assignment_queue_stats(self, **kwargs):
                self.kwargs = kwargs
                return RuntimeEntityAliasCandidateAssignmentQueueStats(
                    project_id=kwargs["project_id"],
                    generated_at=datetime(2026, 6, 13, 0, 0, tzinfo=UTC),
                    method_version="entity_alias_assignment_queue_stats_v1",
                    active_statuses=("assigned", "in_progress", "blocked"),
                    total_count=5,
                    active_count=3,
                    unassigned_count=1,
                    overdue_count=1,
                    due_soon_count=2,
                    status_counts={"assigned": 2, "blocked": 1, "completed": 1, "unassigned": 1},
                    priority_counts={"high": 2, "normal": 2, "urgent": 1},
                    oldest_due_at=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
                    next_due_at=datetime(2026, 6, 14, 0, 0, tzinfo=UTC),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.get(
                f"/v1/entity-aliases/runtime/candidates/assignment-stats?project_id={project_id}"
                "&due_soon_before=2026-06-20T00:00:00Z"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["method_version"], "entity_alias_assignment_queue_stats_v1")
        self.assertEqual(payload["active_statuses"], ["assigned", "in_progress", "blocked"])
        self.assertEqual(payload["total_count"], 5)
        self.assertEqual(payload["overdue_count"], 1)
        self.assertEqual(payload["due_soon_count"], 2)
        self.assertEqual(payload["status_counts"]["assigned"], 2)
        self.assertEqual(payload["priority_counts"]["urgent"], 1)
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["due_soon_before"].isoformat(), "2026-06-20T00:00:00+00:00")

    def test_runtime_entity_alias_assignment_workbench_endpoint_returns_reviewer_queue(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def get_entity_alias_assignment_workbench(self, **kwargs):
                self.kwargs = kwargs
                return RuntimeEntityAliasAssignmentWorkbench(
                    project_id=kwargs["project_id"],
                    reviewer_id=kwargs["reviewer_id"],
                    generated_at=datetime(2026, 6, 13, 0, 0, tzinfo=UTC),
                    method_version="entity_alias_assignment_workbench_v1",
                    active_statuses=("assigned", "in_progress", "blocked", "escalated"),
                    total_count=2,
                    active_count=2,
                    overdue_count=1,
                    due_soon_count=1,
                    escalated_count=1,
                    blocked_count=0,
                    status_counts={"assigned": 1, "escalated": 1},
                    priority_counts={"high": 1, "urgent": 1},
                    oldest_due_at=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
                    next_due_at=datetime(2026, 6, 14, 0, 0, tzinfo=UTC),
                    records=(
                        RuntimeEntityAliasCandidateReview(
                            review={
                                "id": "review-1",
                                "project_id": project_id,
                                "candidate_id": "candidate-1",
                                "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                                "entity_kind": "brand",
                                "alias": "ExampleBrand AU",
                                "alias_type": "alias",
                                "decision": "needs_review",
                                "assigned_to": kwargs["reviewer_id"],
                                "assignment_status": "escalated",
                                "priority": "urgent",
                            },
                            audit_events=(
                                {
                                    "event_type": "entity_alias_candidate_assignment_reassigned",
                                    "method_version": "entity_alias_candidate_assignment_reassignment_v1",
                                },
                            ),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.get(
                f"/v1/entity-aliases/runtime/candidates/assignment-workbench?project_id={project_id}"
                "&reviewer_id=runtime-console&due_soon_before=2026-06-20T00:00:00Z&limit=8"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["method_version"], "entity_alias_assignment_workbench_v1")
        self.assertEqual(payload["reviewer_id"], "runtime-console")
        self.assertEqual(payload["active_statuses"], ["assigned", "in_progress", "blocked", "escalated"])
        self.assertEqual(payload["total_count"], 2)
        self.assertEqual(payload["escalated_count"], 1)
        self.assertEqual(payload["records"][0]["review"]["assignment_status"], "escalated")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "entity_alias_candidate_assignment_reassigned")
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["reviewer_id"], "runtime-console")
        self.assertEqual(fake_repository.kwargs["limit"], 8)
        self.assertEqual(fake_repository.kwargs["due_soon_before"].isoformat(), "2026-06-20T00:00:00+00:00")

    def test_runtime_entity_alias_assignment_workload_endpoint_returns_reviewer_loads(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def get_entity_alias_assignment_workload_summary(self, **kwargs):
                self.kwargs = kwargs
                return RuntimeEntityAliasAssignmentWorkloadSummary(
                    project_id=kwargs["project_id"],
                    generated_at=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
                    method_version="entity_alias_assignment_workload_v1",
                    active_statuses=("assigned", "in_progress", "blocked", "escalated"),
                    total_active_count=3,
                    unassigned_count=1,
                    reviewer_count=2,
                    overdue_count=1,
                    due_soon_count=1,
                    escalated_count=1,
                    blocked_count=1,
                    reviewer_loads=(
                        {
                            "reviewer_id": "unassigned",
                            "active_count": 1,
                            "overdue_count": 0,
                            "due_soon_count": 0,
                            "escalated_count": 0,
                            "blocked_count": 0,
                            "urgent_count": 0,
                            "high_count": 0,
                            "oldest_due_at": None,
                            "next_due_at": None,
                            "status_counts": {"assigned": 1},
                            "priority_counts": {"normal": 1},
                        },
                        {
                            "reviewer_id": "reviewer-a@example.com",
                            "active_count": 2,
                            "overdue_count": 1,
                            "due_soon_count": 1,
                            "escalated_count": 1,
                            "blocked_count": 1,
                            "urgent_count": 1,
                            "high_count": 1,
                            "oldest_due_at": datetime(2026, 6, 14, 0, 0, tzinfo=UTC),
                            "next_due_at": datetime(2026, 6, 16, 0, 0, tzinfo=UTC),
                            "status_counts": {"blocked": 1, "escalated": 1},
                            "priority_counts": {"high": 1, "urgent": 1},
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.get(
                f"/v1/entity-aliases/runtime/candidates/assignment-workload?project_id={project_id}"
                "&due_soon_before=2026-06-20T00:00:00Z"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["method_version"], "entity_alias_assignment_workload_v1")
        self.assertEqual(payload["active_statuses"], ["assigned", "in_progress", "blocked", "escalated"])
        self.assertEqual(payload["total_active_count"], 3)
        self.assertEqual(payload["unassigned_count"], 1)
        self.assertEqual(payload["reviewer_count"], 2)
        self.assertEqual(payload["reviewer_loads"][0]["reviewer_id"], "unassigned")
        self.assertEqual(payload["reviewer_loads"][1]["urgent_count"], 1)
        self.assertEqual(payload["reviewer_loads"][1]["next_due_at"], "2026-06-16T00:00:00Z")
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["due_soon_before"].isoformat(), "2026-06-20T00:00:00+00:00")

    def test_runtime_entity_alias_assignment_dispatch_plan_endpoint_returns_dry_run_plan(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def build_entity_alias_assignment_dispatch_plan(self, plan_input):
                self.plan_input = plan_input
                return RuntimeEntityAliasAssignmentDispatchPlan(
                    project_id=plan_input.project_id,
                    generated_at=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
                    method_version="entity_alias_assignment_dispatch_plan_v1",
                    dry_run=True,
                    strategy=plan_input.strategy,
                    include_statuses=plan_input.include_statuses,
                    reviewer_ids=plan_input.reviewer_ids,
                    active_statuses=("assigned", "in_progress", "blocked", "escalated"),
                    max_per_reviewer=plan_input.max_per_reviewer,
                    candidate_count=2,
                    planned_assignment_count=1,
                    skipped_count=1,
                    reviewer_loads=(
                        {
                            "reviewer_id": "reviewer-a@example.com",
                            "current_active_count": 1,
                            "planned_assignment_count": 1,
                            "planned_active_count": 2,
                            "capacity_remaining": 0,
                            "over_capacity": False,
                        },
                    ),
                    proposed_assignments=(
                        {
                            "order": 1,
                            "review_id": "review-1",
                            "candidate_id": "candidate-1",
                            "alias": "ExampleBrand AU",
                            "current_assigned_to": None,
                            "current_assignment_status": "unassigned",
                            "priority": "urgent",
                            "due_at": datetime(2026, 6, 16, 0, 0, tzinfo=UTC),
                            "recommended_assigned_to": "reviewer-a@example.com",
                            "recommended_assignment_status": "assigned",
                            "reason": "least loaded eligible reviewer within capacity",
                        },
                    ),
                    skipped_candidates=(
                        {
                            "candidate_id": "candidate-2",
                            "assignment_status": "unassigned",
                            "reason": "reviewer capacity exhausted",
                        },
                    ),
                    source_summary={"dry_run_does_not_write_assignment_state": True},
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.get(
                f"/v1/entity-aliases/runtime/candidates/assignment-dispatch-plan?project_id={project_id}"
                "&reviewer_ids=reviewer-a@example.com,reviewer-b@example.com"
                "&include_statuses=unassigned,escalated&max_per_reviewer=2"
                "&due_soon_before=2026-06-20T00:00:00Z&limit=20"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["method_version"], "entity_alias_assignment_dispatch_plan_v1")
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["reviewer_ids"], ["reviewer-a@example.com", "reviewer-b@example.com"])
        self.assertEqual(payload["include_statuses"], ["unassigned", "escalated"])
        self.assertEqual(payload["planned_assignment_count"], 1)
        self.assertEqual(payload["skipped_count"], 1)
        self.assertEqual(payload["proposed_assignments"][0]["recommended_assigned_to"], "reviewer-a@example.com")
        self.assertEqual(fake_repository.plan_input.project_id, project_id)
        self.assertEqual(fake_repository.plan_input.reviewer_ids, ("reviewer-a@example.com", "reviewer-b@example.com"))
        self.assertEqual(fake_repository.plan_input.include_statuses, ("unassigned", "escalated"))
        self.assertEqual(fake_repository.plan_input.max_per_reviewer, 2)
        self.assertEqual(fake_repository.plan_input.limit, 20)
        self.assertEqual(fake_repository.plan_input.due_soon_before.isoformat(), "2026-06-20T00:00:00+00:00")

    def test_runtime_entity_alias_assignment_dispatch_apply_endpoint_applies_plan(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def apply_entity_alias_assignment_dispatch_plan(self, apply_input):
                self.apply_input = apply_input
                plan = RuntimeEntityAliasAssignmentDispatchPlan(
                    project_id=apply_input.project_id,
                    generated_at=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
                    method_version="entity_alias_assignment_dispatch_plan_v1",
                    dry_run=True,
                    strategy="least_loaded_round_robin",
                    include_statuses=apply_input.include_statuses,
                    reviewer_ids=apply_input.reviewer_ids,
                    active_statuses=("assigned", "in_progress", "blocked", "escalated"),
                    max_per_reviewer=apply_input.max_per_reviewer,
                    candidate_count=1,
                    planned_assignment_count=1,
                    skipped_count=0,
                    reviewer_loads=(),
                    proposed_assignments=(
                        {
                            "order": 1,
                            "candidate_id": "candidate-1",
                            "recommended_assigned_to": "reviewer-a@example.com",
                        },
                    ),
                    skipped_candidates=(),
                    source_summary={"dry_run_does_not_write_assignment_state": True},
                )
                return RuntimeEntityAliasAssignmentDispatchApplyResult(
                    project_id=apply_input.project_id,
                    method_version="entity_alias_assignment_dispatch_apply_v1",
                    requested_count=1,
                    applied_count=1,
                    failed_count=0,
                    records=(
                        RuntimeEntityAliasCandidateReview(
                            review={
                                "id": "review-1",
                                "project_id": apply_input.project_id,
                                "candidate_id": "candidate-1",
                                "assigned_to": "reviewer-a@example.com",
                                "assignment_status": apply_input.assignment_status,
                            },
                            audit_events=(
                                {
                                    "event_type": "entity_alias_candidate_assignment_dispatch_applied",
                                    "method_version": "entity_alias_assignment_dispatch_apply_v1",
                                },
                            ),
                        ),
                    ),
                    errors=(),
                    dispatch_plan=plan,
                    audit_summary={
                        "event_type": "entity_alias_assignment_dispatch_plan_applied",
                        "method_version": "entity_alias_assignment_dispatch_apply_v1",
                    },
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/assignment-dispatch-apply",
                json={
                    "project_id": project_id,
                    "reviewer_ids": ["reviewer-a@example.com", "reviewer-b@example.com"],
                    "include_statuses": ["unassigned", "escalated"],
                    "max_per_reviewer": 2,
                    "due_soon_before": "2026-06-20T00:00:00Z",
                    "limit": 20,
                    "applied_by": "lead@example.com",
                    "assignment_status": "assigned",
                    "priority": "high",
                    "assignment_note": "Apply dispatch plan",
                    "reason": "Apply dispatch plan",
                    "continue_on_error": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["method_version"], "entity_alias_assignment_dispatch_apply_v1")
        self.assertEqual(payload["applied_count"], 1)
        self.assertEqual(payload["audit_summary"]["event_type"], "entity_alias_assignment_dispatch_plan_applied")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "entity_alias_candidate_assignment_dispatch_applied")
        self.assertEqual(fake_repository.apply_input.project_id, project_id)
        self.assertEqual(fake_repository.apply_input.reviewer_ids, ("reviewer-a@example.com", "reviewer-b@example.com"))
        self.assertEqual(fake_repository.apply_input.include_statuses, ("unassigned", "escalated"))
        self.assertEqual(fake_repository.apply_input.max_per_reviewer, 2)
        self.assertEqual(fake_repository.apply_input.limit, 20)
        self.assertEqual(fake_repository.apply_input.applied_by, "lead@example.com")
        self.assertEqual(fake_repository.apply_input.priority, "high")
        self.assertEqual(fake_repository.apply_input.due_soon_before.isoformat(), "2026-06-20T00:00:00+00:00")

    def test_runtime_entity_alias_assignment_notifications_endpoint_passes_payload(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def enqueue_entity_alias_assignment_overdue_notifications(self, **kwargs):
                self.kwargs = kwargs
                return RuntimeEntityAliasAssignmentNotificationResult(
                    project_id=kwargs["project_id"],
                    notification_count=1,
                    delivery_count=1,
                    skipped_count=0,
                    notifications=(
                        {
                            "id": "notification-1",
                            "notification_type": "entity_alias_assignment_overdue",
                            "severity": "critical",
                            "target_type": "entity_alias_candidate_review",
                        },
                    ),
                    audit_events=(
                        {"event_type": "runtime_notification_created"},
                        {"event_type": "runtime_notification_delivery_queued"},
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/assignment-notifications",
                json={
                    "project_id": project_id,
                    "assigned_to": "reviewer@example.com",
                    "priority": "urgent",
                    "due_before": "2026-06-20T00:00:00Z",
                    "created_by": "analyst-1",
                    "reason": "notify overdue assignments",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["notification_count"], 1)
        self.assertEqual(payload["delivery_count"], 1)
        self.assertEqual(payload["notifications"][0]["notification_type"], "entity_alias_assignment_overdue")
        self.assertEqual(payload["audit_events"][1]["event_type"], "runtime_notification_delivery_queued")
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["assigned_to"], "reviewer@example.com")
        self.assertEqual(fake_repository.kwargs["priority"], "urgent")
        self.assertEqual(fake_repository.kwargs["due_before"].isoformat(), "2026-06-20T00:00:00+00:00")
        self.assertEqual(fake_repository.kwargs["created_by"], "analyst-1")

    def test_runtime_entity_alias_assignment_escalations_endpoint_passes_payload(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def escalate_entity_alias_assignment_overdue_reviews(self, **kwargs):
                self.kwargs = kwargs
                return RuntimeEntityAliasAssignmentEscalationResult(
                    project_id=kwargs["project_id"],
                    escalation_count=1,
                    skipped_count=0,
                    escalated_reviews=(
                        {
                            "id": "review-1",
                            "candidate_id": "candidate-1",
                            "assignment_status": "escalated",
                        },
                    ),
                    audit_events=(
                        {
                            "event_type": "entity_alias_candidate_assignment_escalated",
                            "method_version": "entity_alias_candidate_assignment_escalation_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/assignment-escalations",
                json={
                    "project_id": project_id,
                    "assigned_to": "reviewer@example.com",
                    "priority": "urgent",
                    "due_before": "2026-06-20T00:00:00Z",
                    "escalated_by": "lead-1",
                    "reason": "escalate overdue assignments",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["escalation_count"], 1)
        self.assertEqual(payload["escalated_reviews"][0]["assignment_status"], "escalated")
        self.assertEqual(payload["audit_events"][0]["event_type"], "entity_alias_candidate_assignment_escalated")
        self.assertEqual(fake_repository.kwargs["project_id"], project_id)
        self.assertEqual(fake_repository.kwargs["assigned_to"], "reviewer@example.com")
        self.assertEqual(fake_repository.kwargs["priority"], "urgent")
        self.assertEqual(fake_repository.kwargs["due_before"].isoformat(), "2026-06-20T00:00:00+00:00")
        self.assertEqual(fake_repository.kwargs["escalated_by"], "lead-1")

    def test_runtime_entity_alias_assignment_reassignments_endpoint_passes_payload(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def reassign_entity_alias_candidate_reviews(self, reassignment):
                self.reassignment = reassignment
                return RuntimeEntityAliasAssignmentReassignmentResult(
                    project_id=reassignment.project_id,
                    reassignment_count=1,
                    skipped_count=0,
                    reassigned_reviews=(
                        {
                            "id": "review-1",
                            "candidate_id": "candidate-1",
                            "assigned_to": reassignment.assigned_to,
                            "assignment_status": reassignment.assignment_status,
                        },
                    ),
                    audit_events=(
                        {
                            "event_type": "entity_alias_candidate_assignment_reassigned",
                            "method_version": "entity_alias_candidate_assignment_reassignment_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/assignment-reassignments",
                json={
                    "project_id": project_id,
                    "assigned_to": "reviewer-b@example.com",
                    "reassigned_by": "lead-1",
                    "from_assignment_status": "escalated",
                    "from_priority": "urgent",
                    "due_before": "2026-06-20T00:00:00Z",
                    "assignment_status": "assigned",
                    "priority": "high",
                    "due_at": "2026-06-21T00:00:00Z",
                    "assignment_note": "Reassign escalated reviews",
                    "reason": "rebalance alias assignment queue",
                    "limit": 25,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        reassignment = fake_repository.reassignment
        self.assertEqual(payload["reassignment_count"], 1)
        self.assertEqual(payload["reassigned_reviews"][0]["assigned_to"], "reviewer-b@example.com")
        self.assertEqual(payload["audit_events"][0]["event_type"], "entity_alias_candidate_assignment_reassigned")
        self.assertEqual(reassignment.project_id, project_id)
        self.assertEqual(reassignment.assigned_to, "reviewer-b@example.com")
        self.assertEqual(reassignment.reassigned_by, "lead-1")
        self.assertEqual(reassignment.from_assignment_status, "escalated")
        self.assertEqual(reassignment.from_priority, "urgent")
        self.assertEqual(reassignment.due_before.isoformat(), "2026-06-20T00:00:00+00:00")
        self.assertEqual(reassignment.due_at.isoformat(), "2026-06-21T00:00:00+00:00")
        self.assertEqual(reassignment.limit, 25)

    def test_runtime_entity_alias_candidate_review_endpoint_records_decision(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        entity_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def record_entity_alias_candidate_review(self, review):
                self.review = review
                return RuntimeEntityAliasCandidateReview(
                    review={
                        "id": "review-1",
                        "project_id": review.project_id,
                        "candidate_id": review.candidate_id,
                        "entity_id": review.entity_id,
                        "entity_kind": review.entity_kind,
                        "alias": review.alias,
                        "alias_type": review.alias_type,
                        "decision": review.decision,
                        "reviewed_by": review.reviewed_by,
                    },
                    audit_events=(
                        {
                            "event_type": "entity_alias_candidate_review_recorded",
                            "method_version": "entity_alias_candidate_review_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/review",
                json={
                    "project_id": project_id,
                    "candidate_id": "candidate-1",
                    "entity_id": entity_id,
                    "entity_kind": "brand",
                    "alias": "ExampleBrand AU",
                    "alias_type": "alias",
                    "decision": "rejected",
                    "reviewed_by": "analyst-1",
                    "source": "evidence_answer_text",
                    "confidence": 0.8,
                    "reason": "not an owned alias",
                    "notes": "Reject noisy candidate",
                    "evidence_answer_run_ids": ["answer-run-1"],
                    "evidence_urls": ["https://examplebrand.com.au/reviews"],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["review"]["decision"], "rejected")
        self.assertEqual(payload["audit_events"][0]["event_type"], "entity_alias_candidate_review_recorded")
        self.assertEqual(fake_repository.review.project_id, project_id)
        self.assertEqual(fake_repository.review.reviewed_by, "analyst-1")
        self.assertEqual(fake_repository.review.evidence_answer_run_ids, ("answer-run-1",))

    def test_runtime_entity_alias_candidate_review_batch_endpoint_records_decisions(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        entity_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def record_entity_alias_candidate_reviews(self, reviews, **kwargs):
                self.reviews = reviews
                self.kwargs = kwargs
                return RuntimeEntityAliasCandidateBatchReviewResult(
                    batch_version="entity_alias_candidate_review_batch_v1",
                    requested_count=len(reviews),
                    reviewed_count=len(reviews),
                    failed_count=0,
                    records=tuple(
                        RuntimeEntityAliasCandidateReview(
                            review={
                                "id": f"review-{index}",
                                "project_id": review.project_id,
                                "candidate_id": review.candidate_id,
                                "entity_id": review.entity_id,
                                "decision": review.decision,
                                "reviewed_by": review.reviewed_by,
                            },
                            audit_events=(
                                {
                                    "event_type": "entity_alias_candidate_review_recorded",
                                    "method_version": "entity_alias_candidate_review_v1",
                                },
                            ),
                        )
                        for index, review in enumerate(reviews)
                    ),
                    errors=(),
                    audit_summary={
                        "event_type": "entity_alias_candidate_batch_reviewed",
                        "method_version": "entity_alias_candidate_review_batch_v1",
                        "reviewed_count": len(reviews),
                        "failed_count": 0,
                    },
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/review-batch",
                json={
                    "reviewed_by": "analyst-1",
                    "notes": "Batch reject noisy candidates",
                    "reviews": [
                        {
                            "project_id": project_id,
                            "candidate_id": "candidate-1",
                            "entity_id": entity_id,
                            "entity_kind": "brand",
                            "alias": "ExampleBrand AU",
                            "alias_type": "alias",
                            "decision": "rejected",
                            "source": "evidence_answer_text",
                            "confidence": 0.8,
                            "evidence_answer_run_ids": ["answer-run-1"],
                            "evidence_urls": ["https://examplebrand.com.au/reviews"],
                        },
                        {
                            "project_id": project_id,
                            "candidate_id": "candidate-2",
                            "entity_id": entity_id,
                            "entity_kind": "brand",
                            "alias": "examplebrand-au.example",
                            "alias_type": "domain",
                            "decision": "rejected",
                            "source": "evidence_citation_domain",
                            "confidence": 0.72,
                        },
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["batch_version"], "entity_alias_candidate_review_batch_v1")
        self.assertEqual(payload["reviewed_count"], 2)
        self.assertEqual(payload["audit_summary"]["event_type"], "entity_alias_candidate_batch_reviewed")
        self.assertEqual(fake_repository.kwargs["reviewed_by"], "analyst-1")
        self.assertEqual(fake_repository.reviews[0].notes, "Batch reject noisy candidates")
        self.assertEqual(fake_repository.reviews[0].evidence_answer_run_ids, ("answer-run-1",))

    def test_runtime_entity_alias_candidate_review_batch_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/entity-aliases/runtime/candidates/review-batch",
            json={
                "reviews": [
                    {
                        "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                        "candidate_id": "candidate-1",
                        "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                        "entity_kind": "brand",
                        "alias": "ExampleBrand AU",
                        "alias_type": "alias",
                        "decision": "rejected",
                    }
                ]
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_candidate_assignment_endpoint_records_owner_sla(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def assign_entity_alias_candidate_review(self, assignment):
                self.assignment = assignment
                return RuntimeEntityAliasCandidateReview(
                    review={
                        "id": "review-1",
                        "project_id": assignment.project_id,
                        "candidate_id": assignment.candidate_id,
                        "assigned_to": assignment.assigned_to,
                        "assigned_by": assignment.assigned_by,
                        "assignment_status": assignment.assignment_status,
                        "priority": assignment.priority,
                        "due_at": assignment.due_at.isoformat() if assignment.due_at else None,
                    },
                    audit_events=(
                        {
                            "event_type": "entity_alias_candidate_assigned",
                            "method_version": "entity_alias_candidate_assignment_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/assign",
                json={
                    "project_id": project_id,
                    "candidate_id": "candidate-1",
                    "assigned_to": "reviewer@example.com",
                    "assigned_by": "lead@example.com",
                    "assignment_status": "assigned",
                    "priority": "high",
                    "due_at": "2026-06-14T09:00:00Z",
                    "assignment_note": "Review by Monday",
                    "reason": "Assign reviewer",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["review"]["assigned_to"], "reviewer@example.com")
        self.assertEqual(payload["review"]["priority"], "high")
        self.assertEqual(payload["audit_events"][0]["event_type"], "entity_alias_candidate_assigned")
        self.assertEqual(fake_repository.assignment.project_id, project_id)
        self.assertEqual(fake_repository.assignment.due_at.isoformat(), "2026-06-14T09:00:00+00:00")

    def test_runtime_entity_alias_candidate_assignment_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/entity-aliases/runtime/candidates/assign",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "candidate_id": "candidate-1",
                "assigned_to": "reviewer@example.com",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_candidate_assignment_action_endpoint_claims_review(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def apply_entity_alias_candidate_assignment_action(self, action):
                self.action = action
                return RuntimeEntityAliasCandidateReview(
                    review={
                        "id": "review-1",
                        "project_id": action.project_id,
                        "candidate_id": action.candidate_id,
                        "assigned_to": action.updated_by,
                        "assignment_status": "assigned",
                    },
                    audit_events=(
                        {
                            "event_type": "entity_alias_candidate_assignment_actioned",
                            "method_version": "entity_alias_candidate_assignment_action_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/assignment-action",
                json={
                    "project_id": project_id,
                    "candidate_id": "candidate-1",
                    "action": "claim",
                    "updated_by": "reviewer@example.com",
                    "note": "Claim from queue",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["review"]["assigned_to"], "reviewer@example.com")
        self.assertEqual(payload["audit_events"][0]["event_type"], "entity_alias_candidate_assignment_actioned")
        self.assertEqual(fake_repository.action.action, "claim")
        self.assertEqual(fake_repository.action.note, "Claim from queue")

    def test_runtime_entity_alias_candidate_assignment_action_endpoint_returns_conflict(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def apply_entity_alias_candidate_assignment_action(self, action):
                raise ValueError("entity alias candidate review is already assigned")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/assignment-action",
                json={
                    "project_id": project_id,
                    "candidate_id": "candidate-1",
                    "action": "claim",
                    "updated_by": "reviewer@example.com",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "entity alias candidate review is already assigned")

    def test_runtime_entity_alias_candidate_assignment_batch_action_endpoint_claims_reviews(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"

        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def apply_entity_alias_candidate_assignment_batch_action(self, batch):
                self.batch = batch
                return RuntimeEntityAliasAssignmentBatchActionResult(
                    project_id=batch.project_id,
                    action=batch.action,
                    requested_count=2,
                    actioned_count=1,
                    failed_count=1,
                    records=(
                        RuntimeEntityAliasCandidateReview(
                            review={
                                "id": "review-1",
                                "project_id": batch.project_id,
                                "candidate_id": "candidate-1",
                                "assigned_to": batch.updated_by,
                                "assignment_status": "assigned",
                            },
                            audit_events=(
                                {
                                    "event_type": "entity_alias_candidate_assignment_actioned",
                                    "method_version": "entity_alias_candidate_assignment_action_v1",
                                },
                            ),
                        ),
                    ),
                    errors=({"candidate_id": "candidate-2", "error": "entity alias candidate review is already assigned"},),
                    audit_summary={
                        "event_type": "entity_alias_candidate_assignment_batch_actioned",
                        "method_version": "entity_alias_candidate_assignment_batch_action_v1",
                    },
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/assignment-actions",
                json={
                    "project_id": project_id,
                    "candidate_ids": ["candidate-1", "candidate-2"],
                    "action": "claim",
                    "updated_by": "reviewer@example.com",
                    "note": "Batch claim from workbench",
                    "continue_on_error": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action"], "claim")
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(payload["actioned_count"], 1)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["audit_summary"]["event_type"], "entity_alias_candidate_assignment_batch_actioned")
        self.assertEqual(fake_repository.batch.candidate_ids, ("candidate-1", "candidate-2"))
        self.assertEqual(fake_repository.batch.note, "Batch claim from workbench")

    def test_runtime_entity_alias_candidate_assignment_batch_action_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/entity-aliases/runtime/candidates/assignment-actions",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "candidate_ids": ["candidate-1"],
                "action": "claim",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_candidate_review_batch_rejects_cross_project_reviews(self) -> None:
        class FakeRepository:
            connection = type("Connection", (), {"close": lambda self: None})()

            def record_entity_alias_candidate_reviews(self, reviews, **kwargs):
                raise AssertionError("batch review should reject cross-project payload before writing")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()):
            response = self.client.post(
                "/v1/entity-aliases/runtime/candidates/review-batch",
                json={
                    "reviews": [
                        {
                            "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                            "candidate_id": "candidate-1",
                            "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                            "entity_kind": "brand",
                            "alias": "ExampleBrand AU",
                            "alias_type": "alias",
                            "decision": "rejected",
                        },
                        {
                            "project_id": "other-project",
                            "candidate_id": "candidate-2",
                            "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                            "entity_kind": "brand",
                            "alias": "ExampleBrand Australia",
                            "alias_type": "alias",
                            "decision": "rejected",
                        },
                    ]
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "reviews must belong to one project")

    def test_runtime_entity_alias_confirm_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/entity-aliases/runtime/confirm",
            json={
                "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                "entity_kind": "brand",
                "alias": "ExampleBrand Australia",
                "alias_type": "alias",
                "confirmed_by": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_confirm_batch_endpoint_returns_audit_summary(self) -> None:
        class FakeRepository:
            def __init__(self) -> None:
                self.confirmed = []
                self.audit_events = []

            def confirm_entity_alias(self, alias):
                self.confirmed.append(alias)
                return RuntimeEntityAlias(
                    entity_alias={
                        "id": f"alias-{len(self.confirmed)}",
                        "entity_id": alias.entity_id,
                        "entity_kind": alias.entity_kind,
                        "alias": alias.alias,
                        "alias_type": alias.alias_type,
                        "confidence": alias.confidence,
                        "confirmed_by": alias.confirmed_by,
                    },
                    entity={
                        "id": alias.entity_id,
                        "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                        "entity_kind": alias.entity_kind,
                        "canonical_name": "ExampleBrand",
                        "status": "active",
                    },
                    audit_events=(
                        {
                            "event_type": "entity_alias_confirmed",
                            "target_id": f"alias-{len(self.confirmed)}",
                            "method_version": "entity_alias_confirm_v1",
                        },
                    ),
                )

            def save_audit_events(self, events):
                self.audit_events.extend(events)

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/entity-aliases/runtime/confirm-batch",
                json={
                    "confirmed_by": "runtime-console",
                    "notes": "Batch entity alias confirmation for parser disambiguation review queue",
                    "aliases": [
                        {
                            "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                            "entity_kind": "brand",
                            "alias": "ExampleBrand Australia",
                            "alias_type": "alias",
                            "confidence": 0.72,
                        },
                        {
                            "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                            "entity_kind": "brand",
                            "alias": "examplebrand.com.au",
                            "alias_type": "domain",
                            "confidence": 0.9,
                        },
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["batch_version"], "entity_alias_confirm_batch_v1")
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(payload["confirmed_count"], 2)
        self.assertEqual(payload["failed_count"], 0)
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "entity_alias_confirmed")
        self.assertEqual(payload["audit_summary"]["event_type"], "entity_alias_batch_confirmed")
        self.assertEqual(payload["audit_summary"]["method_version"], "entity_alias_confirm_batch_v1")
        self.assertEqual(payload["audit_summary"]["individual_audit_event_type"], "entity_alias_confirmed")
        self.assertEqual(fake_repository.audit_events[0].event_type, "entity_alias_batch_confirmed")
        self.assertEqual(fake_repository.audit_events[0].target_type, "entity_alias_batch")
        self.assertEqual(fake_repository.audit_events[0].method_version, "entity_alias_confirm_batch_v1")
        self.assertEqual(fake_repository.confirmed[0].confirmed_by, "runtime-console")
        self.assertEqual(
            fake_repository.confirmed[0].notes,
            "Batch entity alias confirmation for parser disambiguation review queue",
        )

    def test_runtime_entity_alias_confirm_batch_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/entity-aliases/runtime/confirm-batch",
            json={
                "aliases": [
                    {
                        "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                        "entity_kind": "brand",
                        "alias": "ExampleBrand Australia",
                        "alias_type": "alias",
                    }
                ]
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_entity_alias_confirm_batch_prevalidates_before_writing(self) -> None:
        class FakeRepository:
            def __init__(self) -> None:
                self.confirmed = []

            def get_entity_project_id(self, *, entity_id: str, entity_kind: str) -> str | None:
                if entity_id.endswith("9999"):
                    return None
                return "9a50797d-a341-55a4-8bdf-cc255c017e5c"

            def confirm_entity_alias(self, alias):
                self.confirmed.append(alias)
                return RuntimeEntityAlias(entity_alias={}, entity={}, audit_events=())

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/entity-aliases/runtime/confirm-batch",
                json={
                    "aliases": [
                        {
                            "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
                            "entity_kind": "brand",
                            "alias": "ExampleBrand Australia",
                            "alias_type": "alias",
                        },
                        {
                            "entity_id": "00000000-0000-0000-0000-000000009999",
                            "entity_kind": "brand",
                            "alias": "MissingBrand Australia",
                            "alias_type": "alias",
                        },
                    ]
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["index"], 1)
        self.assertEqual(response.json()["detail"]["error"], "entity not found")
        self.assertEqual(fake_repository.confirmed, [])

    def test_runtime_entity_alias_confirm_batch_rejects_cross_project_aliases(self) -> None:
        class FakeRepository:
            def __init__(self) -> None:
                self.confirmed = []

            def get_entity_project_id(self, *, entity_id: str, entity_kind: str) -> str | None:
                if entity_id.endswith("0001"):
                    return "11111111-1111-1111-1111-111111111111"
                return "22222222-2222-2222-2222-222222222222"

            def confirm_entity_alias(self, alias):
                self.confirmed.append(alias)
                return RuntimeEntityAlias(entity_alias={}, entity={}, audit_events=())

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/entity-aliases/runtime/confirm-batch",
                json={
                    "aliases": [
                        {
                            "entity_id": "00000000-0000-0000-0000-000000000001",
                            "entity_kind": "brand",
                            "alias": "Brand One Australia",
                            "alias_type": "alias",
                        },
                        {
                            "entity_id": "00000000-0000-0000-0000-000000000002",
                            "entity_kind": "brand",
                            "alias": "Brand Two Australia",
                            "alias_type": "alias",
                        },
                    ]
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "aliases must belong to one project")
        self.assertEqual(fake_repository.confirmed, [])

    def test_runtime_saved_views_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/runtime-saved-views?view_type=runtime_evidence")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_saved_view_save_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/runtime-saved-views",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "name": "Perplexity Sydney",
                "view_type": "runtime_evidence",
                "filters": {"platform": "perplexity", "city": "Sydney"},
                "sort": "cost_desc",
                "query_path": "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&sort=cost_desc&limit=5",
                "export_path": "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&sort=cost_desc&limit=200",
                "created_by": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_kit_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/project-brand-kits/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_kit_save_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/project-brand-kits/runtime",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "client_name": "Koala AU",
                "prepared_by": "Partner Agency",
                "logo_url": "https://koala.example/logo.png",
                "primary_color": "#0f766e",
                "secondary_color": "#111827",
                "footer_text": "Prepared for Koala AU board review",
                "updated_by": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_kit_endpoint_returns_saved_configuration(self) -> None:
        class FakeRepository:
            def get_project_brand_kit(self, **kwargs: object) -> RuntimeProjectBrandKit:
                self.kwargs = kwargs
                return RuntimeProjectBrandKit(
                    brand_kit={
                        "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
                        "project_id": kwargs["project_id"],
                        "client_name": "Koala AU",
                        "prepared_by": "Partner Agency",
                        "logo_url": "https://koala.example/logo.png",
                        "primary_color": "#0f766e",
                        "secondary_color": "#111827",
                        "footer_text": "Prepared for Koala AU board review",
                        "updated_by": "runtime-console",
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_kit_saved",
                            "target_type": "project_brand_kit",
                            "method_version": "project_brand_kit_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-brand-kits/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["brand_kit"]["client_name"], "Koala AU")
        self.assertEqual(payload["brand_kit"]["primary_color"], "#0f766e")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_kit_saved")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")

    def test_runtime_project_brand_kit_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_project_brand_kit(self, brand_kit: object) -> RuntimeProjectBrandKit:
                self.brand_kit = brand_kit
                return RuntimeProjectBrandKit(
                    brand_kit={
                        "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
                        "project_id": brand_kit.project_id,
                        "client_name": brand_kit.client_name,
                        "prepared_by": brand_kit.prepared_by,
                        "logo_url": brand_kit.logo_url,
                        "primary_color": brand_kit.primary_color,
                        "secondary_color": brand_kit.secondary_color,
                        "footer_text": brand_kit.footer_text,
                        "updated_by": brand_kit.updated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_kit_saved",
                            "target_type": "project_brand_kit",
                            "method_version": "project_brand_kit_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-kits/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "client_name": "Koala AU",
                    "prepared_by": "Partner Agency",
                    "logo_url": "https://koala.example/logo.png",
                    "primary_color": "#0f766e",
                    "secondary_color": "#111827",
                    "footer_text": "Prepared for Koala AU board review",
                    "updated_by": "runtime-console",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["brand_kit"]["prepared_by"], "Partner Agency")
        self.assertEqual(fake_repository.brand_kit.client_name, "Koala AU")
        self.assertEqual(fake_repository.brand_kit.logo_url, "https://koala.example/logo.png")

    def test_runtime_project_brand_logo_upload_endpoint_requires_object_store_config(self) -> None:
        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> object:
                self.kwargs = kwargs
                return type("RuntimeProjectPage", (), {"total_count": 1})()

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-kits/runtime/logo"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&filename=logo.png"
                "&uploaded_by=runtime-console",
                content=b"fake-logo-bytes",
                headers={"content-type": "image/png"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("OBJECT_STORE_ENDPOINT", response.json()["detail"])
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")

    def test_runtime_project_brand_logo_upload_endpoint_archives_and_saves(self) -> None:
        class FakeStore:
            def put_object(self, **kwargs: object) -> object:
                self.kwargs = kwargs
                return type(
                    "StoredObject",
                    (),
                    {
                        "uri": "s3://geno-reports/brand-assets/project/logo-25f766a3e701-logo.png",
                        "content_type": kwargs["content_type"],
                        "content_hash": "25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b",
                    },
                )()

        class FakeRepository:
            def list_runtime_projects(self, **kwargs: object) -> object:
                self.list_kwargs = kwargs
                return type("RuntimeProjectPage", (), {"total_count": 1})()

            def upload_project_brand_logo(self, upload: RuntimeProjectBrandLogoUpload) -> RuntimeProjectBrandKit:
                self.upload = upload
                return RuntimeProjectBrandKit(
                    brand_kit={
                        "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
                        "project_id": upload.project_id,
                        "client_name": "Koala AU",
                        "prepared_by": "Partner Agency",
                        "logo_url": upload.logo_url,
                        "primary_color": "#0f766e",
                        "secondary_color": "#111827",
                        "footer_text": "Prepared for Koala AU board review",
                        "updated_by": upload.uploaded_by,
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_logo_uploaded",
                            "target_type": "project_brand_kit",
                            "method_version": "project_brand_logo_upload_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        fake_store = FakeStore()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.build_object_store_from_env", return_value=fake_store
        ), patch("geno_api.main.close_repository_connection"):
            response = self.client.post(
                "/v1/project-brand-kits/runtime/logo"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&filename=Client%20Logo.png"
                "&uploaded_by=agency-user",
                content=b"fake-logo-bytes",
                headers={"content-type": "image/png"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["brand_kit"]["logo_url"], "s3://geno-reports/brand-assets/project/logo-25f766a3e701-logo.png")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_logo_uploaded")
        self.assertEqual(fake_store.kwargs["content"], b"fake-logo-bytes")
        self.assertEqual(fake_store.kwargs["content_type"], "image/png")
        self.assertEqual(fake_repository.upload.filename, "Client Logo.png")
        self.assertEqual(fake_repository.upload.uploaded_by, "agency-user")
        self.assertEqual(fake_repository.upload.content_hash, "25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b")

    def test_runtime_project_brand_asset_versions_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/project-brand-kits/runtime/assets?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_asset_versions_endpoint_returns_versions(self) -> None:
        class FakeRepository:
            def list_project_brand_asset_versions(self, **kwargs: object) -> RuntimeProjectBrandAssetVersionPage:
                self.kwargs = kwargs
                return RuntimeProjectBrandAssetVersionPage(
                    project_id=str(kwargs["project_id"]),
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeProjectBrandAssetVersion(
                            version_id="ce333139-53e7-44c8-8c85-ce498d841391",
                            project_id=str(kwargs["project_id"]),
                            asset_type="logo",
                            asset_url="s3://geno-reports/brand-assets/project/logo.png",
                            source_filename="Client Logo.png",
                            source_content_type="image/png",
                            content_hash="25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b",
                            uploaded_by="agency-user",
                            uploaded_at=None,
                            is_active=True,
                            audit_event={"event_type": "project_brand_logo_uploaded"},
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-brand-kits/runtime/assets"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&limit=5&offset=0"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["asset_type"], "logo")
        self.assertTrue(payload["records"][0]["is_active"])
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_project_brand_assets_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/project-brand-assets/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_project_brand_assets_endpoint_returns_assets(self) -> None:
        class FakeRepository:
            def list_project_brand_assets(self, **kwargs: object) -> RuntimeProjectBrandAssetPage:
                self.kwargs = kwargs
                return RuntimeProjectBrandAssetPage(
                    project_id=str(kwargs["project_id"]),
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeProjectBrandAsset(
                            asset={
                                "id": "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4",
                                "project_id": str(kwargs["project_id"]),
                                "asset_type": "image",
                                "asset_url": "s3://geno-reports/brand-assets/project/hero.png",
                                "category": "brand_creative",
                                "preview_url": "https://cdn.example.com/project/hero-preview.png",
                                "source_filename": "hero.png",
                                "source_content_type": "image/png",
                                "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
                                "storage_version": "etag-hero-v1",
                                "status": "active",
                                "scan_status": "passed",
                                "scan_checked_at": None,
                                "scan_method_version": "manual_asset_scan_v1",
                                "scan_notes": "Clean preview",
                                "uploaded_by": "agency-user",
                                "metadata": {"source": "runtime_console_asset_register"},
                            },
                            audit_events=(
                                {
                                    "event_type": "project_brand_asset_registered",
                                    "target_type": "project_brand_asset",
                                    "method_version": "project_brand_asset_library_v1",
                                },
                            ),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/project-brand-assets/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&asset_type=image&category=brand_creative&status=active&limit=5&offset=0"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["asset"]["asset_type"], "image")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "project_brand_asset_registered")
        self.assertEqual(fake_repository.kwargs["asset_type"], "image")
        self.assertEqual(fake_repository.kwargs["category"], "brand_creative")
        self.assertEqual(fake_repository.kwargs["status"], "active")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_project_brand_asset_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_project_brand_asset(self, asset: RuntimeProjectBrandAssetInput) -> RuntimeProjectBrandAsset:
                self.asset = asset
                return RuntimeProjectBrandAsset(
                    asset={
                        "id": "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4",
                        "project_id": asset.project_id,
                        "asset_type": asset.asset_type,
                        "asset_url": asset.asset_url,
                        "category": asset.category,
                        "preview_url": asset.preview_url,
                        "source_filename": asset.source_filename,
                        "source_content_type": asset.source_content_type,
                        "content_hash": asset.content_hash,
                        "storage_version": asset.storage_version,
                        "status": asset.status,
                        "scan_status": "pending",
                        "scan_checked_at": None,
                        "scan_method_version": None,
                        "scan_notes": None,
                        "uploaded_by": asset.uploaded_by,
                        "metadata": asset.metadata,
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_asset_registered",
                            "target_type": "project_brand_asset",
                            "method_version": "project_brand_asset_library_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-assets/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "asset_type": "image",
                    "asset_url": "s3://geno-reports/brand-assets/project/hero.png",
                    "category": "brand_creative",
                    "preview_url": "https://cdn.example.com/project/hero-preview.png",
                    "source_filename": "hero.png",
                    "source_content_type": "image/png",
                    "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
                    "storage_version": "etag-hero-v1",
                    "status": "active",
                    "uploaded_by": "agency-user",
                    "metadata": {"source": "runtime_console_asset_register"},
                    "reason": "register project asset",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["asset"]["asset_url"], "s3://geno-reports/brand-assets/project/hero.png")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_asset_registered")
        self.assertIsInstance(fake_repository.asset, RuntimeProjectBrandAssetInput)
        self.assertEqual(fake_repository.asset.category, "brand_creative")
        self.assertEqual(fake_repository.asset.preview_url, "https://cdn.example.com/project/hero-preview.png")
        self.assertEqual(fake_repository.asset.reason, "register project asset")

    def test_runtime_project_brand_asset_scan_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def get_project_brand_asset_project_id(self, **kwargs: object) -> str | None:
                self.project_lookup = kwargs
                return "9a50797d-a341-55a4-8bdf-cc255c017e5c"

            def update_project_brand_asset_scan_status(
                self,
                scan: RuntimeProjectBrandAssetScanInput,
            ) -> RuntimeProjectBrandAsset:
                self.scan = scan
                return RuntimeProjectBrandAsset(
                    asset={
                        "id": scan.asset_id,
                        "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                        "asset_type": "image",
                        "asset_url": "s3://geno-reports/brand-assets/project/hero.png",
                        "category": "brand_creative",
                        "preview_url": "https://cdn.example.com/project/hero-preview.png",
                        "source_filename": "hero.png",
                        "source_content_type": "image/png",
                        "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
                        "storage_version": "etag-hero-v1",
                        "status": "active",
                        "scan_status": scan.scan_status,
                        "scan_checked_at": None,
                        "scan_method_version": scan.scan_method_version,
                        "scan_notes": scan.scan_notes,
                        "uploaded_by": "agency-user",
                        "metadata": {"source": "runtime_console_asset_register"},
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_asset_scan_recorded",
                            "target_type": "project_brand_asset",
                            "method_version": scan.scan_method_version,
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-assets/runtime/ddc23a34-2ffb-5a56-a81a-3b98aaf843b4/scan-status",
                json={
                    "scan_status": "passed",
                    "scanned_by": "agency-user",
                    "scan_method_version": "manual_asset_scan_v1",
                    "scan_notes": "Clean preview",
                    "reason": "manual scan passed",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["asset"]["scan_status"], "passed")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_asset_scan_recorded")
        self.assertEqual(fake_repository.project_lookup["asset_id"], "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4")
        self.assertIsInstance(fake_repository.scan, RuntimeProjectBrandAssetScanInput)
        self.assertEqual(fake_repository.scan.scan_notes, "Clean preview")

    def test_runtime_project_brand_asset_activation_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def activate_project_brand_logo_version(self, activation: object) -> RuntimeProjectBrandKit:
                self.activation = activation
                return RuntimeProjectBrandKit(
                    brand_kit={
                        "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
                        "project_id": activation.project_id,
                        "client_name": "Koala AU",
                        "prepared_by": "Partner Agency",
                        "logo_url": activation.asset_url,
                        "primary_color": "#0f766e",
                        "secondary_color": "#111827",
                        "footer_text": "Prepared for Koala AU board review",
                        "updated_by": activation.activated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "project_brand_logo_version_activated",
                            "target_type": "project_brand_kit",
                            "method_version": "project_brand_logo_asset_version_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/project-brand-kits/runtime/assets/activate",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "asset_url": "s3://geno-reports/brand-assets/project/logo.png",
                    "activated_by": "agency-admin",
                    "reason": "restore previous logo",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["brand_kit"]["logo_url"], "s3://geno-reports/brand-assets/project/logo.png")
        self.assertEqual(payload["audit_events"][0]["event_type"], "project_brand_logo_version_activated")
        self.assertEqual(fake_repository.activation.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.activation.activated_by, "agency-admin")
        self.assertEqual(fake_repository.activation.reason, "restore previous logo")

    def test_runtime_score_weight_config_endpoint_returns_default_when_missing(self) -> None:
        class FakeRepository:
            def get_score_weight_config(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                return None

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/score-weight-configs/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score_weight_config"]["updated_by"], "system-default")
        self.assertEqual(round(sum(payload["score_weight_config"]["weights"].values()), 6), 1.0)
        self.assertEqual(fake_repository.kwargs["formula_version"], "au_visibility_v1")

    def test_runtime_score_formula_catalog_endpoint_lists_registered_versions(self) -> None:
        response = self.client.get("/v1/score-formulas/runtime")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        versions = {item["formula_version"] for item in payload["formulas"]}
        self.assertIn("au_visibility_v1", versions)
        self.assertIn("au_visibility_v1_1_local_boost", versions)
        local_boost = next(item for item in payload["formulas"] if item["formula_version"] == "au_visibility_v1_1_local_boost")
        self.assertEqual(local_boost["status"], "candidate")
        self.assertEqual(round(sum(local_boost["weights"].values()), 6), 1.0)

    def test_runtime_score_weight_config_endpoint_returns_formula_default_when_missing(self) -> None:
        class FakeRepository:
            def get_score_weight_config(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                return None

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/score-weight-configs/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&formula_version=au_visibility_v1_1_local_boost"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score_weight_config"]["formula_version"], "au_visibility_v1_1_local_boost")
        self.assertEqual(payload["score_weight_config"]["weights"]["LocalRelevanceScore"], 0.18)
        self.assertEqual(fake_repository.kwargs["formula_version"], "au_visibility_v1_1_local_boost")

    def test_runtime_score_weight_config_save_endpoint_passes_payload(self) -> None:
        weights = {
            "MentionScore": 0.20,
            "RecommendationScore": 0.22,
            "PositionScore": 0.12,
            "CitationScore": 0.16,
            "LocalRelevanceScore": 0.14,
            "SentimentScore": 0.08,
            "FreshnessScore": 0.03,
            "CompetitorShareScore": 0.05,
        }

        class FakeRepository:
            def save_score_weight_config(self, config: object) -> RuntimeScoreWeightConfig:
                self.config = config
                return RuntimeScoreWeightConfig(
                    score_weight_config={
                        "id": "7daa9492-8fb2-565e-827a-bfd3de846cde",
                        "project_id": config.project_id,
                        "formula_version": config.formula_version,
                        "weights": config.weights,
                        "updated_by": config.updated_by,
                        "notes": config.notes,
                    },
                    audit_events=(
                        {
                            "event_type": "score_weight_config_saved",
                            "target_type": "score_weight_config",
                            "method_version": "score_weight_config_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/score-weight-configs/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "weights": weights,
                    "updated_by": "runtime-console",
                    "notes": "prioritize mention",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["score_weight_config"]["weights"]["MentionScore"], 0.20)
        self.assertEqual(fake_repository.config.notes, "prioritize mention")

    def test_runtime_score_weight_config_save_endpoint_passes_formula_version(self) -> None:
        weights = {
            "MentionScore": 0.17,
            "RecommendationScore": 0.21,
            "PositionScore": 0.11,
            "CitationScore": 0.15,
            "LocalRelevanceScore": 0.18,
            "SentimentScore": 0.07,
            "FreshnessScore": 0.06,
            "CompetitorShareScore": 0.05,
        }

        class FakeRepository:
            def save_score_weight_config(self, config: object) -> RuntimeScoreWeightConfig:
                self.config = config
                return RuntimeScoreWeightConfig(
                    score_weight_config={
                        "id": "74ef8cfb-06e4-5659-a178-d1e3ee7dc7cb",
                        "project_id": config.project_id,
                        "formula_version": config.formula_version,
                        "weights": config.weights,
                        "updated_by": config.updated_by,
                        "notes": config.notes,
                    },
                    audit_events=(
                        {
                            "event_type": "score_weight_config_saved",
                            "target_type": "score_weight_config",
                            "method_version": "score_weight_config_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/score-weight-configs/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "formula_version": "au_visibility_v1_1_local_boost",
                    "weights": weights,
                    "updated_by": "runtime-console",
                    "notes": "test local boost formula",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["score_weight_config"]["formula_version"], "au_visibility_v1_1_local_boost")
        self.assertEqual(fake_repository.config.formula_version, "au_visibility_v1_1_local_boost")

    def test_runtime_human_reviews_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/human-reviews/runtime?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&target_type=content_draft"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_human_review_save_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/human-reviews/runtime",
            json={
                "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                "target_type": "visibility_score_snapshot",
                "target_id": "38f0251c-c380-4197-b6c9-3e630b127844",
                "review_status": "approved",
                "decision": "approved_for_report",
                "reviewer_id": "runtime-console",
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_human_review_queue_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/human-reviews/runtime/queue?queue_status=pending_review")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_human_reviews_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_human_reviews(self, **kwargs: object) -> RuntimeHumanReviewPage:
                self.kwargs = kwargs
                return RuntimeHumanReviewPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeHumanReviewRecord(
                            human_review={
                                "id": "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7",
                                "project_id": kwargs["project_id"],
                                "target_type": kwargs["target_type"],
                                "target_id": "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
                                "review_status": kwargs["review_status"],
                                "decision": "rewrite_local_examples",
                                "reviewer_id": "editor@example.com",
                            },
                            audit_events=(
                                {
                                    "event_type": "human_review_recorded",
                                    "target_type": "human_review_record",
                                    "method_version": "human_review_v1",
                                },
                            ),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/human-reviews/runtime"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&target_type=content_draft&review_status=needs_changes&limit=5&offset=1"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "human_review_recorded")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["target_type"], "content_draft")
        self.assertEqual(fake_repository.kwargs["review_status"], "needs_changes")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_human_reviews_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_human_reviews_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_human_reviews_csv",
                    filename="runtime-human-reviews.csv",
                    media_type="text/csv; charset=utf-8",
                    content="human_review_id,review_status\nreview-1,needs_changes\n",
                    content_hash="hash-human-reviews-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "target_type": kwargs["target_type"],
                        "review_status": kwargs["review_status"],
                    },
                    total_count=4,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/human-reviews/runtime/export.csv"
                "?project_id=project-1&target_type=content_draft&review_status=needs_changes&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-human-review-export-hash"], "hash-human-reviews-csv")
        self.assertEqual(response.headers["x-geno-human-review-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-human-review-target-type"], "content_draft")
        self.assertEqual(response.headers["x-geno-human-review-status"], "needs_changes")
        self.assertEqual(response.headers["x-geno-human-review-row-count"], "1")
        self.assertEqual(response.headers["x-geno-human-review-total-count"], "4")
        self.assertIn("runtime-human-reviews.csv", response.headers["content-disposition"])
        self.assertIn("review-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["target_type"], "content_draft")
        self.assertEqual(fake_repository.kwargs["review_status"], "needs_changes")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_visibility_scores_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_score_snapshots_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_score_snapshots_csv",
                    filename="runtime-score-snapshots.csv",
                    media_type="text/csv; charset=utf-8",
                    content="score_snapshot_id,component_name\nsnapshot-1,MentionScore\n",
                    content_hash="hash-score-snapshots-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "scope_type": kwargs["scope_type"],
                    },
                    total_count=3,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/visibility-scores/runtime/export.csv"
                "?project_id=project-1&scope_type=collection_slice&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-score-snapshot-export-hash"], "hash-score-snapshots-csv")
        self.assertEqual(response.headers["x-geno-score-snapshot-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-score-snapshot-scope-type"], "collection_slice")
        self.assertEqual(response.headers["x-geno-score-snapshot-row-count"], "1")
        self.assertEqual(response.headers["x-geno-score-snapshot-total-count"], "3")
        self.assertIn("runtime-score-snapshots.csv", response.headers["content-disposition"])
        self.assertIn("snapshot-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["scope_type"], "collection_slice")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_human_review_queue_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_human_review_queue(self, **kwargs: object) -> RuntimeHumanReviewQueuePage:
                self.kwargs = kwargs
                return RuntimeHumanReviewQueuePage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeHumanReviewQueueItem(
                            project_id=str(kwargs["project_id"]),
                            target_type=str(kwargs["target_type"]),
                            target_id="1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
                            title="AU shipping proof page",
                            queue_status=str(kwargs["queue_status"]),
                            priority=9,
                            reason="content_draft_pending_human_review",
                            created_at="2026-06-10T00:00:00+00:00",
                            latest_review=None,
                            evidence_refs={"answer_run_ids": ["438ab927-5873-5516-8df3-47f6c75ef007"]},
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/human-reviews/runtime/queue"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&target_type=content_draft&queue_status=pending_review&limit=5&offset=1"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["queue_status"], "pending_review")
        self.assertEqual(payload["records"][0]["evidence_refs"]["answer_run_ids"], ["438ab927-5873-5516-8df3-47f6c75ef007"])
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["target_type"], "content_draft")
        self.assertEqual(fake_repository.kwargs["queue_status"], "pending_review")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_human_review_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_human_review(self, review: object) -> RuntimeHumanReviewRecord:
                self.review = review
                return RuntimeHumanReviewRecord(
                    human_review={
                        "id": "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7",
                        "project_id": review.project_id,
                        "target_type": review.target_type,
                        "target_id": review.target_id,
                        "review_status": review.review_status,
                        "decision": review.decision,
                        "reviewer_id": review.reviewer_id,
                        "notes": review.notes,
                        "payload": review.payload,
                    },
                    audit_events=(
                        {
                            "event_type": "human_review_recorded",
                            "target_type": "human_review_record",
                            "method_version": "human_review_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/human-reviews/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "target_type": "visibility_score_snapshot",
                    "target_id": "38f0251c-c380-4197-b6c9-3e630b127844",
                    "review_status": "approved",
                    "decision": "approved_for_report",
                    "reviewer_id": "runtime-console",
                    "notes": "reviewed score evidence",
                    "payload": {"source": "runtime-console"},
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["human_review"]["decision"], "approved_for_report")
        self.assertEqual(payload["audit_events"][0]["event_type"], "human_review_recorded")
        self.assertEqual(fake_repository.review.target_type, "visibility_score_snapshot")
        self.assertEqual(fake_repository.review.payload["source"], "runtime-console")

    def test_runtime_human_review_save_endpoint_maps_missing_content_draft_to_404(self) -> None:
        class FakeRepository:
            def save_human_review(self, review: object) -> RuntimeHumanReviewRecord:
                raise ValueError("content draft not found")

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/human-reviews/runtime",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "target_type": "content_draft",
                    "target_id": "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
                    "review_status": "approved",
                    "decision": "approved_for_publish",
                    "reviewer_id": "runtime-console",
                },
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "content draft not found")

    def test_runtime_visibility_scores_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/visibility-scores/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_citation_graphs_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/citation-graphs/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_citation_graphs_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_citation_graphs_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_citation_graphs_csv",
                    filename="runtime-citation-graphs.csv",
                    media_type="text/csv; charset=utf-8",
                    content="project_id,source_graph_id\nproject-1,source-1\n",
                    content_hash="hash-citation-graphs-csv",
                    filters={"project_id": kwargs["project_id"]},
                    total_count=2,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/citation-graphs/runtime/export.csv?project_id=project-1&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-citation-graph-export-hash"], "hash-citation-graphs-csv")
        self.assertEqual(response.headers["x-geno-citation-graph-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-citation-graph-row-count"], "1")
        self.assertEqual(response.headers["x-geno-citation-graph-total-count"], "2")
        self.assertIn("runtime-citation-graphs.csv", response.headers["content-disposition"])
        self.assertIn("source-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_reports_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/reports/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_management_endpoint_requires_persistence_config(self) -> None:
        response = self.client.post(
            "/v1/reports/runtime/report-1/management-events",
            json={"status": "client_ready", "updated_by": "runtime-console"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_management_endpoint_records_status_event(self) -> None:
        class FakeRepository:
            def record_runtime_report_management_event(self, event: object) -> RuntimeReportExport:
                self.event = event
                return RuntimeReportExport(
                    report_export={"id": event.report_export_id, "project_id": "project-1", "report_version": "worker-runtime-v1"},
                    score_snapshots=(),
                    answer_runs=(),
                    citation_graph=None,
                    audit_events=(
                        {
                            "event_type": "report_export_management_recorded",
                            "target_type": "report_export",
                            "target_id": event.report_export_id,
                            "actor_id": event.updated_by,
                            "method_version": "report_export_management_v1",
                            "reason": event.note,
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/reports/runtime/report-1/management-events",
                json={"status": "client_ready", "updated_by": "runtime-console", "note": "Ready for client"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["report_export"]["id"], "report-1")
        self.assertEqual(payload["audit_events"][0]["event_type"], "report_export_management_recorded")
        self.assertEqual(fake_repository.event.report_export_id, "report-1")
        self.assertEqual(fake_repository.event.status, "client_ready")
        self.assertEqual(fake_repository.event.updated_by, "runtime-console")
        self.assertEqual(fake_repository.event.note, "Ready for client")

    def test_runtime_report_management_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_report_management_events_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_report_management_events_csv",
                    filename="runtime-report-management-events.csv",
                    media_type="text/csv; charset=utf-8",
                    content="report_export_id,management_status\nreport-1,client_ready\n",
                    content_hash="hash-report-management-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "status": kwargs["status"],
                        "report_type": kwargs["report_type"],
                    },
                    total_count=4,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/reports/runtime/management-events/export.csv"
                "?project_id=project-1&status=client_ready&report_type=worker_runtime&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-report-management-export-hash"], "hash-report-management-csv")
        self.assertEqual(response.headers["x-geno-report-management-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-report-management-status"], "client_ready")
        self.assertEqual(response.headers["x-geno-report-management-report-type"], "worker_runtime")
        self.assertEqual(response.headers["x-geno-report-management-row-count"], "1")
        self.assertEqual(response.headers["x-geno-report-management-total-count"], "4")
        self.assertIn("runtime-report-management-events.csv", response.headers["content-disposition"])
        self.assertIn("report-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["status"], "client_ready")
        self.assertEqual(fake_repository.kwargs["report_type"], "worker_runtime")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_report_export_jobs_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/report-export-jobs/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_export_jobs_endpoint_returns_jobs(self) -> None:
        class FakeRepository:
            def list_runtime_report_export_jobs(self, **kwargs: object) -> RuntimeReportExportJobPage:
                self.kwargs = kwargs
                return RuntimeReportExportJobPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeReportExportJob(
                            report_export_job={
                                "id": "job-1",
                                "project_id": kwargs["project_id"],
                                "status": "queued",
                                "artifact_type": "pdf",
                                "template": "white_label",
                                "filters": {"platform": "perplexity"},
                                "sort": "cost_desc",
                                "requested_by": "runtime-console",
                                "updated_by": "runtime-console",
                            },
                            audit_events=({"event_type": "report_export_job_queued"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/report-export-jobs/runtime?project_id=project-1&status=queued&limit=5&offset=0"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["report_export_job"]["template"], "white_label")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "report_export_job_queued")
        self.assertEqual(fake_repository.kwargs["status"], "queued")

    def test_runtime_report_export_jobs_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_report_export_jobs_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_report_export_jobs_csv",
                    filename="runtime-report-export-jobs.csv",
                    media_type="text/csv; charset=utf-8",
                    content="job_id,status\njob-1,queued\n",
                    content_hash="hash-report-jobs-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "status": kwargs["status"],
                        "report_export_id": kwargs["report_export_id"],
                    },
                    total_count=3,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/report-export-jobs/runtime/export.csv"
                "?project_id=project-1&status=queued&report_export_id=report-1&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-report-export-job-export-hash"], "hash-report-jobs-csv")
        self.assertEqual(response.headers["x-geno-report-export-job-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-report-export-job-status"], "queued")
        self.assertEqual(response.headers["x-geno-report-export-job-report-export-id"], "report-1")
        self.assertEqual(response.headers["x-geno-report-export-job-row-count"], "1")
        self.assertEqual(response.headers["x-geno-report-export-job-total-count"], "3")
        self.assertIn("runtime-report-export-jobs.csv", response.headers["content-disposition"])
        self.assertIn("job-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["status"], "queued")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "report-1")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_report_export_job_stats_endpoint_returns_queue_metrics(self) -> None:
        class FakeRepository:
            def get_runtime_report_export_job_queue_stats(self, **kwargs: object) -> RuntimeReportExportJobQueueStats:
                self.kwargs = kwargs
                return RuntimeReportExportJobQueueStats(
                    total_count=4,
                    status_counts={"queued": 2, "running": 1, "dead_letter": 1},
                    retryable_count=2,
                    expired_running_count=1,
                    max_attempts_reached_count=1,
                    oldest_queued_at=None,
                    generated_at=datetime.now(UTC),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get("/v1/report-export-jobs/runtime/stats?project_id=project-1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 4)
        self.assertEqual(payload["status_counts"]["dead_letter"], 1)
        self.assertEqual(payload["retryable_count"], 2)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")

    def test_runtime_notifications_endpoint_returns_project_inbox(self) -> None:
        class FakeRepository:
            def list_runtime_notifications(self, **kwargs: object) -> RuntimeNotificationPage:
                self.kwargs = kwargs
                return RuntimeNotificationPage(
                    total_count=1,
                    unread_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeNotification(
                            notification={
                                "id": "notification-1",
                                "project_id": kwargs["project_id"],
                                "notification_type": "report_export_job",
                                "severity": "critical",
                                "title": "Report export dead-lettered",
                                "message": "pdf/standard report export job dead_letter.",
                                "target_type": "report_export_job",
                                "target_id": "job-1",
                                "recipient_role": "project_member",
                                "status": "unread",
                                "payload": {"status": "dead_letter"},
                                "created_by": "runtime-worker",
                                "updated_by": "runtime-worker",
                            },
                            audit_events=({"event_type": "runtime_notification_created"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notifications?project_id=project-1&status=unread&notification_type=report_export_job&limit=5"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["unread_count"], 1)
        self.assertEqual(payload["records"][0]["notification"]["severity"], "critical")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "runtime_notification_created")
        self.assertEqual(fake_repository.kwargs["notification_type"], "report_export_job")

    def test_runtime_notifications_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_notifications_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_notifications_csv",
                    filename="runtime-notifications.csv",
                    media_type="text/csv; charset=utf-8",
                    content="notification_id,status\nnotification-1,unread\n",
                    content_hash="hash-notifications-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "status": kwargs["status"],
                        "notification_type": kwargs["notification_type"],
                    },
                    total_count=4,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notifications/export.csv"
                "?project_id=project-1&status=unread&notification_type=report_export_job&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-notification-export-hash"], "hash-notifications-csv")
        self.assertEqual(response.headers["x-geno-notification-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-notification-status"], "unread")
        self.assertEqual(response.headers["x-geno-notification-type"], "report_export_job")
        self.assertEqual(response.headers["x-geno-notification-row-count"], "1")
        self.assertEqual(response.headers["x-geno-notification-total-count"], "4")
        self.assertIn("runtime-notifications.csv", response.headers["content-disposition"])
        self.assertIn("notification-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["status"], "unread")
        self.assertEqual(fake_repository.kwargs["notification_type"], "report_export_job")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_notification_status_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def get_runtime_notification_project_id(self, *, notification_id: str) -> str:
                self.notification_id = notification_id
                return "project-1"

            def update_runtime_notification_status(self, update: object) -> RuntimeNotification:
                self.update = update
                return RuntimeNotification(
                    notification={
                        "id": update.notification_id,
                        "project_id": "project-1",
                        "notification_type": "report_export_job",
                        "severity": "info",
                        "title": "Report export succeeded",
                        "message": "pdf/standard report export job succeeded.",
                        "target_type": "report_export_job",
                        "target_id": "job-1",
                        "recipient_role": "project_member",
                        "status": update.status,
                        "payload": {"status": "succeeded"},
                        "created_by": "runtime-worker",
                        "updated_by": update.updated_by,
                    },
                    audit_events=({"event_type": "runtime_notification_status_updated"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notifications/notification-1/status",
                json={"status": "read", "updated_by": "runtime-console", "reason": "mark read"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["notification"]["status"], "read")
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_notification_status_updated")
        self.assertEqual(fake_repository.notification_id, "notification-1")
        self.assertEqual(fake_repository.update.reason, "mark read")

    def test_runtime_notification_subscriptions_endpoint_returns_page(self) -> None:
        class FakeRepository:
            def list_runtime_notification_subscriptions(self, **kwargs: object) -> RuntimeNotificationSubscriptionPage:
                self.kwargs = kwargs
                return RuntimeNotificationSubscriptionPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeNotificationSubscription(
                            subscription={
                                "id": "subscription-1",
                                "project_id": kwargs["project_id"],
                                "channel": "webhook",
                                "endpoint_url": "https://hooks.example.com/geno",
                                "event_types": ["report_export_job"],
                                "severity_threshold": "warning",
                                "status": "active",
                                "metadata": {"source": "contract"},
                                "created_by": "runtime-console",
                                "updated_by": "runtime-console",
                            },
                            audit_events=({"event_type": "runtime_notification_subscription_saved"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-subscriptions?project_id=project-1&status=active&limit=5"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["subscription"]["endpoint_url"], "https://hooks.example.com/geno")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "runtime_notification_subscription_saved")
        self.assertEqual(fake_repository.kwargs["status"], "active")

    def test_runtime_notification_subscriptions_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_notification_subscriptions_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_notification_subscriptions_csv",
                    filename="runtime-notification-subscriptions.csv",
                    media_type="text/csv; charset=utf-8",
                    content="subscription_id,status\nsubscription-1,active\n",
                    content_hash="hash-notification-subscriptions-csv",
                    filters={"project_id": kwargs["project_id"], "status": kwargs["status"]},
                    total_count=2,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-subscriptions/export.csv?project_id=project-1&status=active&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(
            response.headers["x-geno-notification-subscription-export-hash"],
            "hash-notification-subscriptions-csv",
        )
        self.assertEqual(response.headers["x-geno-notification-subscription-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-notification-subscription-status"], "active")
        self.assertEqual(response.headers["x-geno-notification-subscription-row-count"], "1")
        self.assertEqual(response.headers["x-geno-notification-subscription-total-count"], "2")
        self.assertIn("runtime-notification-subscriptions.csv", response.headers["content-disposition"])
        self.assertIn("subscription-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["status"], "active")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_notification_subscription_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_runtime_notification_subscription(self, subscription: object) -> RuntimeNotificationSubscription:
                self.subscription = subscription
                return RuntimeNotificationSubscription(
                    subscription={
                        "id": "subscription-1",
                        "project_id": subscription.project_id,
                        "channel": subscription.channel,
                        "endpoint_url": subscription.endpoint_url,
                        "event_types": list(subscription.event_types),
                        "severity_threshold": subscription.severity_threshold,
                        "status": subscription.status,
                        "metadata": subscription.metadata,
                        "created_by": subscription.updated_by,
                        "updated_by": subscription.updated_by,
                    },
                    audit_events=({"event_type": "runtime_notification_subscription_saved"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-subscriptions",
                json={
                    "project_id": "project-1",
                    "channel": "email",
                    "endpoint_url": "mailto:ops@example.com",
                    "event_types": ["report_export_job"],
                    "severity_threshold": "critical",
                    "status": "active",
                    "metadata": {
                        "source": "api-test",
                        "email_reply_to": "reports@example.com",
                        "email_unsubscribe_url": "https://app.example.com/notifications/unsubscribe",
                        "email_unsubscribe_mailto": "mailto:unsubscribe@example.com",
                        "email_preferences_url": "https://app.example.com/notifications/preferences",
                        "email_suppressed_recipients": ["muted@example.com"],
                    },
                    "updated_by": "runtime-console",
                    "reason": "save email subscription",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subscription"]["channel"], "email")
        self.assertEqual(payload["subscription"]["severity_threshold"], "critical")
        self.assertEqual(fake_repository.subscription.endpoint_url, "mailto:ops@example.com")
        self.assertEqual(fake_repository.subscription.metadata["email_reply_to"], "reports@example.com")
        self.assertEqual(
            fake_repository.subscription.metadata["email_unsubscribe_url"],
            "https://app.example.com/notifications/unsubscribe",
        )
        self.assertEqual(
            fake_repository.subscription.metadata["email_unsubscribe_mailto"],
            "mailto:unsubscribe@example.com",
        )
        self.assertEqual(
            fake_repository.subscription.metadata["email_preferences_url"],
            "https://app.example.com/notifications/preferences",
        )
        self.assertEqual(fake_repository.subscription.metadata["email_suppressed_recipients"], ["muted@example.com"])
        self.assertEqual(fake_repository.subscription.reason, "save email subscription")

    def test_runtime_notification_deliveries_endpoint_returns_page(self) -> None:
        class FakeRepository:
            def list_runtime_notification_deliveries(self, **kwargs: object) -> RuntimeNotificationDeliveryPage:
                self.kwargs = kwargs
                return RuntimeNotificationDeliveryPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeNotificationDelivery(
                            delivery={
                                "id": "delivery-1",
                                "project_id": kwargs["project_id"],
                                "notification_id": "notification-1",
                                "subscription_id": "subscription-1",
                                "channel": "webhook",
                                "endpoint_url": "https://hooks.example.com/geno",
                                "status": "queued",
                                "attempt_count": 0,
                                "max_attempts": 3,
                                "payload": {"delivery_version": "runtime_notification_delivery_v1"},
                                "updated_by": "runtime-worker",
                            },
                            notification={"id": "notification-1", "title": "Report export failed"},
                            subscription={"id": "subscription-1", "endpoint_url": "https://hooks.example.com/geno"},
                            audit_events=({"event_type": "runtime_notification_delivery_queued"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-deliveries?project_id=project-1&status=queued&limit=5"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["delivery"]["status"], "queued")
        self.assertEqual(payload["records"][0]["notification"]["title"], "Report export failed")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "runtime_notification_delivery_queued")
        self.assertEqual(fake_repository.kwargs["status"], "queued")

    def test_runtime_notification_deliveries_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_notification_deliveries_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_notification_deliveries_csv",
                    filename="runtime-notification-deliveries.csv",
                    media_type="text/csv; charset=utf-8",
                    content="delivery_id,status\nsubscription-1,queued\n",
                    content_hash="hash-notification-deliveries-csv",
                    filters={"project_id": kwargs["project_id"], "status": kwargs["status"]},
                    total_count=4,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-deliveries/export.csv"
                "?project_id=project-1&status=queued&notification_id=notification-1&subscription_id=subscription-1&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-notification-delivery-export-hash"], "hash-notification-deliveries-csv")
        self.assertEqual(response.headers["x-geno-notification-delivery-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-notification-delivery-status"], "queued")
        self.assertEqual(response.headers["x-geno-notification-delivery-row-count"], "1")
        self.assertEqual(response.headers["x-geno-notification-delivery-total-count"], "4")
        self.assertIn("runtime-notification-deliveries.csv", response.headers["content-disposition"])
        self.assertIn("subscription-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["status"], "queued")
        self.assertEqual(fake_repository.kwargs["notification_id"], "notification-1")
        self.assertEqual(fake_repository.kwargs["subscription_id"], "subscription-1")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_notification_email_feedback_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def get_runtime_notification_delivery_project_id(self, *, delivery_id: str) -> str:
                self.delivery_project_lookup = delivery_id
                return "project-1"

            def record_runtime_notification_email_feedback(self, feedback: object) -> RuntimeNotificationEmailFeedback:
                self.feedback = feedback
                return RuntimeNotificationEmailFeedback(
                    feedback_event={
                        "id": "feedback-1",
                        "project_id": "project-1",
                        "delivery_id": feedback.delivery_id,
                        "notification_id": "notification-1",
                        "subscription_id": "subscription-1",
                        "feedback_type": feedback.feedback_type,
                        "recipient_hash": "recipient-hash",
                        "provider": feedback.provider,
                        "provider_event_id_hash": "provider-event-hash",
                        "metadata": feedback.metadata,
                        "recorded_by": feedback.recorded_by,
                    },
                    delivery={
                        "id": feedback.delivery_id,
                        "project_id": "project-1",
                        "notification_id": "notification-1",
                        "subscription_id": "subscription-1",
                        "channel": "email",
                        "endpoint_url": "mailto:ops@example.com",
                        "status": "delivered",
                    },
                    notification={"id": "notification-1", "title": "Report export failed"},
                    subscription={"id": "subscription-1", "channel": "email"},
                    audit_events=({"event_type": "runtime_notification_email_feedback_recorded"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-deliveries/delivery-1/email-feedback",
                json={
                    "feedback_type": "complaint",
                    "recipient": "ops@example.com",
                    "provider": "smtp",
                    "provider_event_id": "smtp-feedback-1",
                    "metadata": {"source": "manual"},
                    "recorded_by": "runtime-console",
                    "reason": "manual complaint review",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["feedback_event"]["feedback_type"], "complaint")
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_notification_email_feedback_recorded")
        self.assertEqual(fake_repository.delivery_project_lookup, "delivery-1")
        self.assertEqual(fake_repository.feedback.delivery_id, "delivery-1")
        self.assertEqual(fake_repository.feedback.provider_event_id, "smtp-feedback-1")
        self.assertEqual(fake_repository.feedback.metadata["source"], "manual")
        self.assertEqual(fake_repository.feedback.reason, "manual complaint review")

    def test_runtime_notification_email_feedback_webhook_verifies_signature_and_records_feedback(self) -> None:
        class FakeRepository:
            def record_runtime_notification_email_feedback(self, feedback: object) -> RuntimeNotificationEmailFeedback:
                self.feedback = feedback
                return RuntimeNotificationEmailFeedback(
                    feedback_event={
                        "id": "feedback-1",
                        "project_id": "project-1",
                        "delivery_id": feedback.delivery_id,
                        "notification_id": "notification-1",
                        "subscription_id": "subscription-1",
                        "feedback_type": feedback.feedback_type,
                        "recipient_hash": feedback.recipient_hash,
                        "provider": feedback.provider,
                        "provider_event_id_hash": feedback.provider_event_id_hash,
                        "metadata": feedback.metadata,
                        "recorded_by": feedback.recorded_by,
                    },
                    delivery={
                        "id": feedback.delivery_id,
                        "project_id": "project-1",
                        "notification_id": "notification-1",
                        "subscription_id": "subscription-1",
                        "channel": "email",
                        "endpoint_url": "mailto:ops@example.com",
                        "status": "delivered",
                    },
                    notification={"id": "notification-1", "title": "Report export failed"},
                    subscription={"id": "subscription-1", "channel": "email"},
                    audit_events=({"event_type": "runtime_notification_email_feedback_recorded"},),
                )

        body = json.dumps(
            {
                "delivery_id": "delivery-1",
                "feedback_type": "bounce",
                "recipient_hash": "a" * 64,
                "provider": "geno",
                "provider_event_id_hash": "b" * 64,
                "metadata": {"provider_reason": "smtp 550"},
                "reason": "provider bounce webhook",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        payload_hash = runtime_notification_webhook_payload_hash(body)
        headers = {
            RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER: "delivery-1",
            RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER: "notification-1",
            RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER: payload_hash,
            **sign_runtime_notification_webhook(
                secret="feedback-secret",
                delivery_id="delivery-1",
                notification_id="notification-1",
                payload_hash=payload_hash,
            ),
        }

        fake_repository = FakeRepository()
        with patch.dict(
            os.environ,
            {
                "GENO_NOTIFICATION_EMAIL_FEEDBACK_WEBHOOK_SECRET": "feedback-secret",
                "GENO_NOTIFICATION_EMAIL_FEEDBACK_WEBHOOK_SECRET_ID": "feedback-v1",
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-feedback-webhooks/geno",
                content=body,
                headers=headers,
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["feedback_event"]["feedback_type"], "bounce")
        self.assertEqual(fake_repository.feedback.delivery_id, "delivery-1")
        self.assertEqual(fake_repository.feedback.recorded_by, "email-feedback-webhook")
        self.assertEqual(fake_repository.feedback.metadata["provider_reason"], "smtp 550")
        self.assertEqual(fake_repository.feedback.metadata["signature_payload_hash"], payload_hash)
        self.assertEqual(fake_repository.feedback.metadata["matched_secret_id"], "feedback-v1")
        self.assertNotIn("feedback-secret", str(fake_repository.feedback.metadata))

    def test_runtime_notification_email_feedback_webhook_rejects_missing_signature(self) -> None:
        with patch.dict(
            os.environ,
            {"GENO_NOTIFICATION_EMAIL_FEEDBACK_WEBHOOK_SECRET": "feedback-secret"},
            clear=False,
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-feedback-webhooks/geno",
                json={
                    "delivery_id": "delivery-1",
                    "feedback_type": "bounce",
                    "recipient_hash": "a" * 64,
                },
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("signature invalid", response.json()["detail"])

    def test_runtime_notification_email_provider_feedback_webhook_records_sendgrid_payload(self) -> None:
        class FakeRepository:
            def __init__(self) -> None:
                self.feedback_inputs: list[object] = []

            def record_runtime_notification_email_feedback(self, feedback: object) -> RuntimeNotificationEmailFeedback:
                self.feedback_inputs.append(feedback)
                return RuntimeNotificationEmailFeedback(
                    feedback_event={
                        "id": f"feedback-{len(self.feedback_inputs)}",
                        "project_id": "project-1",
                        "delivery_id": feedback.delivery_id,
                        "notification_id": "notification-1",
                        "subscription_id": "subscription-1",
                        "feedback_type": feedback.feedback_type,
                        "recipient_hash": feedback.recipient_hash,
                        "provider": feedback.provider,
                        "provider_event_id_hash": feedback.provider_event_id_hash,
                        "metadata": feedback.metadata,
                        "recorded_by": feedback.recorded_by,
                    },
                    delivery={
                        "id": feedback.delivery_id,
                        "project_id": "project-1",
                        "notification_id": "notification-1",
                        "subscription_id": "subscription-1",
                        "channel": "email",
                    },
                    notification={"id": "notification-1", "title": "Report export failed"},
                    subscription={"id": "subscription-1", "channel": "email"},
                    audit_events=({"event_type": "runtime_notification_email_feedback_recorded"},),
                )

        body = [
            {
                "event": "spamreport",
                "email": "Ops@Example.com",
                "sg_event_id": "sendgrid-event-1",
                "timestamp": 1781462400,
                "custom_args": {"geno_delivery_id": "delivery-1"},
            },
            {"event": "delivered", "email": "ignored@example.com"},
        ]
        fake_repository = FakeRepository()
        with patch.dict(
            os.environ,
            {
                "GENO_NOTIFICATION_EMAIL_FEEDBACK_WEBHOOK_SECRET": "feedback-secret",
                "GENO_NOTIFICATION_EMAIL_FEEDBACK_WEBHOOK_SECRET_ID": "provider-feedback-v1",
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-feedback-webhooks/sendgrid",
                json=body,
                headers={"x-geno-provider-webhook-secret": "feedback-secret"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "sendgrid")
        self.assertEqual(payload["record_count"], 1)
        self.assertEqual(payload["ignored_event_count"], 1)
        self.assertEqual(payload["ignored_event_types"], ["delivered"])
        self.assertEqual(fake_repository.feedback_inputs[0].delivery_id, "delivery-1")
        self.assertEqual(fake_repository.feedback_inputs[0].feedback_type, "complaint")
        self.assertEqual(fake_repository.feedback_inputs[0].provider, "sendgrid")
        self.assertEqual(fake_repository.feedback_inputs[0].recorded_by, "email-provider-webhook")
        metadata = fake_repository.feedback_inputs[0].metadata
        self.assertEqual(metadata["provider_webhook_secret_id"], "provider-feedback-v1")
        self.assertEqual(metadata["provider_ignored_event_count"], 1)
        self.assertNotIn("feedback-secret", str(payload))
        self.assertNotIn("feedback-secret", str(metadata))
        self.assertNotIn("Ops@Example.com", str(metadata))
        self.assertNotIn("sendgrid-event-1", str(metadata))

    def test_runtime_notification_email_provider_feedback_webhook_rejects_missing_secret(self) -> None:
        with patch.dict(
            os.environ,
            {"GENO_NOTIFICATION_EMAIL_FEEDBACK_WEBHOOK_SECRET": "feedback-secret"},
            clear=False,
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-feedback-webhooks/mailgun",
                json={"event-data": {"event": "failed", "recipient": "ops@example.com"}},
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("provider feedback webhook secret invalid", response.json()["detail"])

    def test_runtime_notification_email_provider_feedback_webhook_verifies_mailgun_native_signature(self) -> None:
        class FakeRepository:
            def __init__(self) -> None:
                self.feedback_inputs: list[object] = []

            def record_runtime_notification_email_feedback(self, feedback: object) -> RuntimeNotificationEmailFeedback:
                self.feedback_inputs.append(feedback)
                return RuntimeNotificationEmailFeedback(
                    feedback_event={
                        "id": "feedback-1",
                        "project_id": "project-1",
                        "delivery_id": feedback.delivery_id,
                        "notification_id": "notification-1",
                        "subscription_id": "subscription-1",
                        "feedback_type": feedback.feedback_type,
                        "provider": feedback.provider,
                        "metadata": feedback.metadata,
                        "recorded_by": feedback.recorded_by,
                    },
                    delivery={"id": feedback.delivery_id, "channel": "email"},
                    notification={"id": "notification-1", "title": "Report export failed"},
                    subscription={"id": "subscription-1", "channel": "email"},
                    audit_events=({"event_type": "runtime_notification_email_feedback_recorded"},),
                )

        timestamp = str(int(time.time()))
        token = "mailgun-token"
        signing_key = "mailgun-signing-key"
        signature = hmac.new(signing_key.encode("utf-8"), f"{timestamp}{token}".encode("utf-8"), hashlib.sha256).hexdigest()
        body = {
            "signature": {"timestamp": timestamp, "token": token, "signature": signature},
            "event-data": {
                "event": "failed",
                "recipient": "ops@example.com",
                "id": "mailgun-event-1",
                "user-variables": {"geno_delivery_id": "delivery-1"},
            },
        }
        fake_repository = FakeRepository()
        with patch.dict(
            os.environ,
            {
                "GENO_NOTIFICATION_EMAIL_FEEDBACK_WEBHOOK_SECRET": "feedback-secret",
                "GENO_NOTIFICATION_EMAIL_MAILGUN_SIGNING_KEY": signing_key,
            },
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-feedback-webhooks/mailgun",
                json=body,
                headers={"x-geno-provider-webhook-secret": "feedback-secret"},
            )
        self.assertEqual(response.status_code, 200)
        metadata = fake_repository.feedback_inputs[0].metadata
        self.assertEqual(metadata["provider_native_signature_status"], "verified")
        self.assertEqual(metadata["provider_native_signature_method"], "mailgun_hmac_sha256")
        self.assertEqual(metadata["provider_native_signature_checked_count"], 1)
        self.assertNotIn(signing_key, str(metadata))
        self.assertNotIn("mailgun-event-1", str(metadata))

    def test_runtime_notification_email_provider_feedback_webhook_rejects_bad_native_signature(self) -> None:
        timestamp = str(int(time.time()))
        with patch.dict(
            os.environ,
            {
                "GENO_NOTIFICATION_EMAIL_FEEDBACK_WEBHOOK_SECRET": "feedback-secret",
                "GENO_NOTIFICATION_EMAIL_MAILGUN_SIGNING_KEY": "mailgun-signing-key",
            },
            clear=False,
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-feedback-webhooks/mailgun",
                json={
                    "signature": {"timestamp": timestamp, "token": "mailgun-token", "signature": "bad"},
                    "event-data": {"event": "failed", "recipient": "ops@example.com"},
                },
                headers={"x-geno-provider-webhook-secret": "feedback-secret"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("provider native signature invalid", response.json()["detail"])

    def test_runtime_notification_email_feedback_events_endpoint_returns_page(self) -> None:
        class FakeRepository:
            def list_runtime_notification_email_feedback_events(self, **kwargs: object) -> RuntimeNotificationEmailFeedbackPage:
                self.kwargs = kwargs
                return RuntimeNotificationEmailFeedbackPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeNotificationEmailFeedback(
                            feedback_event={
                                "id": "feedback-1",
                                "project_id": kwargs["project_id"],
                                "delivery_id": kwargs["delivery_id"],
                                "notification_id": "notification-1",
                                "subscription_id": "subscription-1",
                                "feedback_type": kwargs["feedback_type"],
                                "recipient_hash": "recipient-hash",
                                "provider": kwargs["provider"],
                                "provider_event_id_hash": "provider-event-hash",
                                "recorded_by": "runtime-console",
                            },
                            delivery={"id": kwargs["delivery_id"], "channel": "email", "status": "delivered"},
                            notification={"id": "notification-1", "title": "Report export failed"},
                            subscription={"id": "subscription-1", "channel": "email"},
                            audit_events=({"event_type": "runtime_notification_email_feedback_recorded"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-email-feedback-events"
                "?project_id=project-1&delivery_id=delivery-1&feedback_type=bounce&provider=smtp&limit=5"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["feedback_event"]["feedback_type"], "bounce")
        self.assertEqual(payload["records"][0]["notification"]["title"], "Report export failed")
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "runtime_notification_email_feedback_recorded")
        self.assertEqual(fake_repository.kwargs["provider"], "smtp")
        self.assertEqual(fake_repository.kwargs["delivery_id"], "delivery-1")

    def test_runtime_notification_email_feedback_suppression_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def get_runtime_notification_email_feedback_project_id(self, *, feedback_event_id: str) -> str:
                self.feedback_project_lookup = feedback_event_id
                return "project-1"

            def apply_runtime_notification_email_feedback_suppression(self, suppression: object) -> RuntimeNotificationSubscription:
                self.suppression = suppression
                return RuntimeNotificationSubscription(
                    subscription={
                        "id": "subscription-1",
                        "project_id": "project-1",
                        "channel": "email",
                        "endpoint_url": "mailto:ops@example.com",
                        "event_types": ["runtime_alert"],
                        "severity_threshold": "warning",
                        "status": "active",
                        "metadata": {
                            "email_suppressed_recipient_hashes": ["recipient-hash"],
                            "email_suppression_feedback_event_ids": [suppression.feedback_event_id],
                        },
                        "created_by": "runtime-console",
                        "updated_by": suppression.updated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "runtime_notification_email_feedback_suppression_applied",
                            "method_version": "runtime_notification_email_feedback_suppression_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-feedback-events/feedback-1/suppress-recipient",
                json={
                    "updated_by": "runtime-console",
                    "reason": "apply complaint suppression",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["subscription"]["metadata"]["email_suppressed_recipient_hashes"], ["recipient-hash"])
        self.assertEqual(
            payload["audit_events"][0]["event_type"],
            "runtime_notification_email_feedback_suppression_applied",
        )
        self.assertEqual(fake_repository.feedback_project_lookup, "feedback-1")
        self.assertEqual(fake_repository.suppression.feedback_event_id, "feedback-1")
        self.assertEqual(fake_repository.suppression.reason, "apply complaint suppression")

    def test_runtime_notification_email_feedback_project_suppression_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def get_runtime_notification_email_feedback_project_id(self, *, feedback_event_id: str) -> str:
                self.feedback_project_lookup = feedback_event_id
                return "project-1"

            def apply_runtime_notification_email_feedback_project_suppression(
                self,
                suppression: object,
            ) -> RuntimeNotificationEmailSuppression:
                self.suppression = suppression
                return RuntimeNotificationEmailSuppression(
                    suppression={
                        "id": "suppression-1",
                        "project_id": "project-1",
                        "recipient_hash": "a" * 64,
                        "status": "active",
                        "source": "feedback",
                        "source_ref": suppression.feedback_event_id,
                        "metadata": {
                            "source": "runtime_notification_email_feedback_project_suppression",
                            "feedback_event_id": suppression.feedback_event_id,
                        },
                        "created_by": "runtime-console",
                        "updated_by": suppression.updated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "runtime_notification_email_feedback_project_suppression_applied",
                            "method_version": "runtime_notification_email_feedback_project_suppression_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-feedback-events/feedback-1/project-suppression",
                json={
                    "metadata": {"note": "manual review"},
                    "updated_by": "runtime-console",
                    "reason": "apply complaint project suppression",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["suppression"]["source"], "feedback")
        self.assertEqual(payload["suppression"]["source_ref"], "feedback-1")
        self.assertEqual(
            payload["audit_events"][0]["event_type"],
            "runtime_notification_email_feedback_project_suppression_applied",
        )
        self.assertEqual(fake_repository.feedback_project_lookup, "feedback-1")
        self.assertEqual(fake_repository.suppression.feedback_event_id, "feedback-1")
        self.assertEqual(fake_repository.suppression.metadata, {"note": "manual review"})
        self.assertEqual(fake_repository.suppression.reason, "apply complaint project suppression")

    def test_runtime_notification_email_suppressions_endpoint_returns_page(self) -> None:
        class FakeRepository:
            def list_runtime_notification_email_suppressions(self, **kwargs: object) -> RuntimeNotificationEmailSuppressionPage:
                self.kwargs = kwargs
                return RuntimeNotificationEmailSuppressionPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeNotificationEmailSuppression(
                            suppression={
                                "id": "suppression-1",
                                "project_id": kwargs["project_id"],
                                "recipient_hash": "a" * 64,
                                "status": "active",
                                "source": "manual",
                                "source_ref": "ticket-1",
                                "metadata": {"source": "contract"},
                                "created_by": "runtime-console",
                                "updated_by": "runtime-console",
                            },
                            audit_events=({"event_type": "runtime_notification_email_suppression_saved"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-email-suppressions?project_id=project-1&status=active&limit=5"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["suppression"]["recipient_hash"], "a" * 64)
        self.assertEqual(payload["records"][0]["audit_events"][0]["event_type"], "runtime_notification_email_suppression_saved")
        self.assertEqual(fake_repository.kwargs["status"], "active")

    def test_runtime_notification_email_suppressions_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_notification_email_suppressions_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_notification_email_suppressions_csv",
                    filename="runtime-notification-email-suppressions.csv",
                    media_type="text/csv; charset=utf-8",
                    content="suppression_id,recipient_hash\nsuppression-1,aaaaaaaa\n",
                    content_hash="hash-email-suppression-csv",
                    filters={"project_id": kwargs["project_id"], "status": kwargs["status"]},
                    total_count=3,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-notification-email-suppressions/export.csv?project_id=project-1&status=active&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-email-suppression-export-hash"], "hash-email-suppression-csv")
        self.assertEqual(response.headers["x-geno-email-suppression-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-email-suppression-status"], "active")
        self.assertEqual(response.headers["x-geno-email-suppression-row-count"], "1")
        self.assertEqual(response.headers["x-geno-email-suppression-total-count"], "3")
        self.assertIn("runtime-notification-email-suppressions.csv", response.headers["content-disposition"])
        self.assertIn("suppression-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["status"], "active")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_notification_email_suppression_save_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def save_runtime_notification_email_suppression(self, suppression: object) -> RuntimeNotificationEmailSuppression:
                self.suppression = suppression
                return RuntimeNotificationEmailSuppression(
                    suppression={
                        "id": "suppression-1",
                        "project_id": suppression.project_id,
                        "recipient_hash": suppression.recipient_hash,
                        "status": suppression.status,
                        "source": suppression.source,
                        "source_ref": suppression.source_ref,
                        "metadata": suppression.metadata,
                        "created_by": suppression.updated_by,
                        "updated_by": suppression.updated_by,
                    },
                    audit_events=({"event_type": "runtime_notification_email_suppression_saved"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-suppressions",
                json={
                    "project_id": "project-1",
                    "recipient_hash": "a" * 64,
                    "status": "active",
                    "source": "manual",
                    "source_ref": "ticket-1",
                    "metadata": {"source": "api-test"},
                    "updated_by": "runtime-console",
                    "reason": "manual project suppression",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["suppression"]["recipient_hash"], "a" * 64)
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_notification_email_suppression_saved")
        self.assertEqual(fake_repository.suppression.project_id, "project-1")
        self.assertEqual(fake_repository.suppression.recipient_hash, "a" * 64)
        self.assertEqual(fake_repository.suppression.reason, "manual project suppression")
        self.assertNotIn("ops@example.com", str(fake_repository.suppression))

    def test_runtime_notification_email_preference_unsubscribe_endpoint_verifies_token(self) -> None:
        class FakeRepository:
            def apply_runtime_notification_email_preference_unsubscribe(self, unsubscribe: object) -> RuntimeNotificationSubscription:
                self.unsubscribe = unsubscribe
                return RuntimeNotificationSubscription(
                    subscription={
                        "id": "subscription-1",
                        "project_id": "project-1",
                        "channel": "email",
                        "endpoint_url": "mailto:ops@example.com",
                        "event_types": ["runtime_alert"],
                        "severity_threshold": "warning",
                        "status": "active",
                        "metadata": {
                            "email_suppressed_recipient_hashes": [unsubscribe.recipient_hash],
                            "email_unsubscribe_token_hashes": [unsubscribe.token_hash],
                        },
                        "created_by": "runtime-console",
                        "updated_by": unsubscribe.updated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "runtime_notification_email_preference_unsubscribed",
                            "method_version": "runtime_notification_email_preference_unsubscribe_v1",
                        },
                    ),
                )

        token = sign_runtime_notification_email_preference_token(
            secret="preference-secret",
            project_id="project-1",
            delivery_id="delivery-1",
            notification_id="notification-1",
            subscription_id="subscription-1",
            recipient_hash="a" * 64,
            ttl_seconds=3600,
            now=datetime.now(UTC),
        )
        fake_repository = FakeRepository()
        with patch.dict(
            os.environ,
            {"GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET": "preference-secret"},
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-preferences/unsubscribe",
                json={"token": token, "reason": "one-click unsubscribe"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_notification_email_preference_unsubscribed")
        self.assertEqual(fake_repository.unsubscribe.project_id, "project-1")
        self.assertEqual(fake_repository.unsubscribe.delivery_id, "delivery-1")
        self.assertEqual(fake_repository.unsubscribe.recipient_hash, "a" * 64)
        self.assertNotIn(token, str(fake_repository.unsubscribe))

    def test_runtime_notification_email_preference_unsubscribe_requires_secret(self) -> None:
        with patch.dict(os.environ, {"GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET": ""}, clear=False):
            response = self.client.post(
                "/v1/runtime-notification-email-preferences/unsubscribe",
                json={"token": "token"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET", response.json()["detail"])

    def test_runtime_notification_email_preference_unsubscribe_accepts_query_token_for_one_click(self) -> None:
        class FakeRepository:
            def apply_runtime_notification_email_preference_unsubscribe(self, unsubscribe: object) -> RuntimeNotificationSubscription:
                self.unsubscribe = unsubscribe
                return RuntimeNotificationSubscription(
                    subscription={
                        "id": unsubscribe.subscription_id,
                        "project_id": unsubscribe.project_id,
                        "channel": "email",
                        "endpoint_url": "mailto:ops@example.com",
                        "event_types": ["runtime_alert"],
                        "severity_threshold": "warning",
                        "status": "active",
                        "metadata": {
                            "email_suppressed_recipient_hashes": [unsubscribe.recipient_hash],
                            "email_unsubscribe_token_hashes": [unsubscribe.token_hash],
                        },
                        "created_by": "runtime-console",
                        "updated_by": unsubscribe.updated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "runtime_notification_email_preference_unsubscribed",
                            "method_version": "runtime_notification_email_preference_unsubscribe_v1",
                        },
                    ),
                )

        token = sign_runtime_notification_email_preference_token(
            secret="preference-secret",
            project_id="project-1",
            delivery_id="delivery-1",
            notification_id="notification-1",
            subscription_id="subscription-1",
            recipient_hash="b" * 64,
            ttl_seconds=3600,
            now=datetime.now(UTC),
        )
        fake_repository = FakeRepository()
        with patch.dict(
            os.environ,
            {"GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET": "preference-secret"},
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                f"/v1/runtime-notification-email-preferences/unsubscribe?token={token}",
                headers={"content-type": "application/x-www-form-urlencoded"},
                content="List-Unsubscribe=One-Click",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.unsubscribe.subscription_id, "subscription-1")
        self.assertEqual(fake_repository.unsubscribe.reason, "apply runtime notification email preference unsubscribe token")

    def test_runtime_notification_email_preference_unsubscribe_accepts_manage_token_for_preferences_page(self) -> None:
        class FakeRepository:
            def apply_runtime_notification_email_preference_unsubscribe(self, unsubscribe: object) -> RuntimeNotificationSubscription:
                self.unsubscribe = unsubscribe
                return RuntimeNotificationSubscription(
                    subscription={
                        "id": unsubscribe.subscription_id,
                        "project_id": unsubscribe.project_id,
                        "channel": "email",
                        "endpoint_url": "mailto:ops@example.com",
                        "event_types": ["runtime_alert"],
                        "severity_threshold": "warning",
                        "status": "active",
                        "metadata": {
                            "email_suppressed_recipient_hashes": [unsubscribe.recipient_hash],
                            "email_unsubscribe_token_hashes": [unsubscribe.token_hash],
                        },
                        "created_by": "runtime-console",
                        "updated_by": unsubscribe.updated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "runtime_notification_email_preference_unsubscribed",
                            "method_version": "runtime_notification_email_preference_unsubscribe_v1",
                        },
                    ),
                )

        token = sign_runtime_notification_email_preference_token(
            secret="preference-secret",
            action="manage",
            project_id="project-1",
            delivery_id="delivery-1",
            notification_id="notification-1",
            subscription_id="subscription-1",
            recipient_hash="e" * 64,
            ttl_seconds=3600,
            now=datetime.now(UTC),
        )
        fake_repository = FakeRepository()
        with patch.dict(
            os.environ,
            {"GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET": "preference-secret"},
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-preferences/unsubscribe",
                json={"token": token, "reason": "turn email off"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fake_repository.unsubscribe.reason, "turn email off")
        self.assertEqual(fake_repository.unsubscribe.recipient_hash, "e" * 64)
        self.assertNotIn(token, str(fake_repository.unsubscribe))

    def test_runtime_notification_email_preference_status_endpoint_verifies_manage_token(self) -> None:
        class FakeRepository:
            def get_runtime_notification_email_preference_status(self, **kwargs: object) -> RuntimeNotificationEmailPreferenceStatus:
                self.status_kwargs = kwargs
                return RuntimeNotificationEmailPreferenceStatus(
                    preference={
                        "project_id": kwargs["project_id"],
                        "delivery_id": kwargs["delivery_id"],
                        "notification_id": kwargs["notification_id"],
                        "subscription_id": kwargs["subscription_id"],
                        "recipient_hash": kwargs["recipient_hash"],
                        "email_preference_token_hash": kwargs["token_hash"],
                        "status": "subscribed",
                        "suppressed": False,
                    },
                    delivery={
                        "id": kwargs["delivery_id"],
                        "project_id": kwargs["project_id"],
                        "notification_id": kwargs["notification_id"],
                        "subscription_id": kwargs["subscription_id"],
                        "channel": "email",
                        "status": "delivered",
                    },
                    notification={"id": kwargs["notification_id"], "project_id": kwargs["project_id"]},
                    subscription={
                        "id": kwargs["subscription_id"],
                        "project_id": kwargs["project_id"],
                        "channel": "email",
                        "metadata": {"email_suppressed_recipient_hash_count": 0},
                    },
                    audit_events=(),
                )

        token = sign_runtime_notification_email_preference_token(
            secret="preference-secret",
            action="manage",
            project_id="project-1",
            delivery_id="delivery-1",
            notification_id="notification-1",
            subscription_id="subscription-1",
            recipient_hash="c" * 64,
            ttl_seconds=3600,
            now=datetime.now(UTC),
        )
        fake_repository = FakeRepository()
        with patch.dict(
            os.environ,
            {"GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET": "preference-secret"},
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(f"/v1/runtime-notification-email-preferences/status?token={token}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["preference"]["status"], "subscribed")
        self.assertEqual(fake_repository.status_kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.status_kwargs["recipient_hash"], "c" * 64)
        self.assertNotIn(token, str(fake_repository.status_kwargs))

    def test_runtime_notification_email_preference_resubscribe_endpoint_verifies_manage_token(self) -> None:
        class FakeRepository:
            def apply_runtime_notification_email_preference_resubscribe(self, resubscribe: object) -> RuntimeNotificationSubscription:
                self.resubscribe = resubscribe
                return RuntimeNotificationSubscription(
                    subscription={
                        "id": resubscribe.subscription_id,
                        "project_id": resubscribe.project_id,
                        "channel": "email",
                        "endpoint_url": "mailto:ops@example.com",
                        "event_types": ["runtime_alert"],
                        "severity_threshold": "warning",
                        "status": "active",
                        "metadata": {
                            "email_suppressed_recipient_hashes": [],
                            "email_resubscribe_token_hashes": [resubscribe.token_hash],
                        },
                        "created_by": "runtime-console",
                        "updated_by": resubscribe.updated_by,
                    },
                    audit_events=(
                        {
                            "event_type": "runtime_notification_email_preference_resubscribed",
                            "method_version": "runtime_notification_email_preference_resubscribe_v1",
                        },
                    ),
                )

        token = sign_runtime_notification_email_preference_token(
            secret="preference-secret",
            action="manage",
            project_id="project-1",
            delivery_id="delivery-1",
            notification_id="notification-1",
            subscription_id="subscription-1",
            recipient_hash="d" * 64,
            ttl_seconds=3600,
            now=datetime.now(UTC),
        )
        fake_repository = FakeRepository()
        with patch.dict(
            os.environ,
            {"GENO_NOTIFICATION_EMAIL_PREFERENCE_TOKEN_SECRET": "preference-secret"},
            clear=False,
        ), patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-notification-email-preferences/resubscribe",
                json={"token": token, "reason": "turn email back on"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_notification_email_preference_resubscribed")
        self.assertEqual(fake_repository.resubscribe.reason, "turn email back on")
        self.assertEqual(fake_repository.resubscribe.recipient_hash, "d" * 64)
        self.assertNotIn(token, str(fake_repository.resubscribe))

    def test_runtime_report_export_job_enqueue_and_status_endpoints_pass_payload(self) -> None:
        class FakeRepository:
            def __init__(self) -> None:
                self.enqueued = None
                self.updated = None

            def get_report_export_job_project_id(self, *, job_id: str) -> str:
                self.job_id = job_id
                return "project-1"

            def enqueue_runtime_report_export_job(self, job: object) -> RuntimeReportExportJob:
                self.enqueued = job
                return RuntimeReportExportJob(
                    report_export_job={
                        "id": "job-1",
                        "project_id": job.project_id,
                        "report_export_id": job.report_export_id,
                        "status": "queued",
                        "artifact_type": job.artifact_type,
                        "template": job.template,
                        "filters": job.filters,
                        "sort": job.sort,
                        "requested_by": job.requested_by,
                        "updated_by": job.requested_by,
                    },
                    audit_events=({"event_type": "report_export_job_queued"},),
                )

            def update_runtime_report_export_job_status(self, update: object) -> RuntimeReportExportJob:
                self.updated = update
                return RuntimeReportExportJob(
                    report_export_job={
                        "id": update.job_id,
                        "project_id": "project-1",
                        "report_export_id": update.report_export_id,
                        "status": update.status,
                        "artifact_type": "pdf",
                        "template": "standard",
                        "filters": {},
                        "sort": "collected_at_desc",
                        "requested_by": "runtime-console",
                        "updated_by": update.updated_by,
                        "artifact_url": update.artifact_url,
                    },
                    audit_events=({"event_type": "report_export_job_status_updated"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            enqueue_response = self.client.post(
                "/v1/report-export-jobs/runtime",
                json={
                    "project_id": "project-1",
                    "report_export_id": "report-1",
                    "artifact_type": "pdf",
                    "template": "standard",
                    "filters": {"city": "Sydney"},
                    "sort": "cost_desc",
                    "requested_by": "runtime-console",
                },
            )
            status_response = self.client.post(
                "/v1/report-export-jobs/runtime/job-1/status",
                json={
                    "status": "succeeded",
                    "updated_by": "runtime-console",
                    "report_export_id": "report-1",
                    "artifact_url": "s3://geno-reports/report.pdf",
                },
            )
        self.assertEqual(enqueue_response.status_code, 200)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(enqueue_response.json()["audit_events"][0]["event_type"], "report_export_job_queued")
        self.assertEqual(status_response.json()["audit_events"][0]["event_type"], "report_export_job_status_updated")
        self.assertEqual(fake_repository.enqueued.filters["city"], "Sydney")
        self.assertEqual(fake_repository.updated.status, "succeeded")
        self.assertEqual(fake_repository.updated.artifact_url, "s3://geno-reports/report.pdf")

    def test_runtime_report_artifact_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/reports/runtime/report-1/artifact?type=markdown&platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_pdf_artifact_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/reports/runtime/report-1/artifact?type=pdf")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_report_white_label_pdf_artifact_endpoint_returns_template_headers(self) -> None:
        class FakeRepository:
            def get_runtime_report_artifact(self, **kwargs: object) -> RuntimeReportArtifact:
                self.kwargs = kwargs
                return RuntimeReportArtifact(
                    report_export={"id": kwargs["report_export_id"], "report_version": "worker-runtime-v1"},
                    artifact_type="pdf",
                    template="white_label",
                    template_payload={
                        "template": "white_label",
                        "client_name": kwargs["client_name"],
                        "prepared_by": kwargs["prepared_by"],
                    },
                    template_hash="template-hash",
                    filename="worker-runtime-v1-white-label.pdf",
                    media_type="application/pdf",
                    content=b"%PDF-1.4\nwhite-label\n%%EOF\n",
                    content_hash="artifact-hash",
                    filters={"platform": kwargs["platform"]},
                    filter_hash="filter-hash",
                    sort="cost_desc",
                    total_count=4,
                    row_count=2,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/reports/runtime/report-1/artifact"
                "?type=pdf&template=white_label&client_name=ExampleBrand%20AU"
                "&prepared_by=Partner%20Agency&platform=perplexity&sort=cost_desc"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="worker-runtime-v1-white-label.pdf"',
        )
        self.assertEqual(response.headers["x-geno-report-artifact-template"], "white_label")
        self.assertEqual(response.headers["x-geno-report-artifact-template-hash"], "template-hash")
        self.assertEqual(response.headers["x-geno-report-artifact-row-count"], "2")
        self.assertEqual(response.headers["x-geno-report-artifact-total-count"], "4")
        self.assertEqual(fake_repository.kwargs["template"], "white_label")
        self.assertEqual(fake_repository.kwargs["client_name"], "ExampleBrand AU")
        self.assertEqual(fake_repository.kwargs["prepared_by"], "Partner Agency")

    def test_runtime_report_artifact_signed_url_requires_signing_secret(self) -> None:
        class FakeRepository:
            def get_report_export_project_id(self, *, report_export_id: str) -> str:
                return "project-1"

        with patch("geno_api.main.build_repository_from_env", return_value=FakeRepository()), patch(
            "geno_api.main.close_repository_connection"
        ), patch.dict("os.environ", {}, clear=True):
            response = self.client.get("/v1/reports/runtime/report-1/artifact/signed-url?type=pdf")
        self.assertEqual(response.status_code, 503)
        self.assertIn("GENO_REPORT_ARTIFACT_SIGNING_SECRET", response.json()["detail"])

    def test_runtime_report_artifact_signed_url_downloads_and_rejects_tampering(self) -> None:
        class FakeRepository:
            def get_report_export_project_id(self, *, report_export_id: str) -> str:
                self.report_export_id = report_export_id
                return "project-1"

            def get_runtime_report_artifact(self, **kwargs: object) -> RuntimeReportArtifact:
                self.kwargs = kwargs
                return RuntimeReportArtifact(
                    report_export={"id": kwargs["report_export_id"], "report_version": "worker-runtime-v1"},
                    artifact_type=str(kwargs["artifact_type"]),
                    template=str(kwargs["template"]),
                    template_payload={"template": kwargs["template"]},
                    template_hash="template-hash",
                    filename=f"worker-runtime-v1.{kwargs['artifact_type']}",
                    media_type="text/markdown; charset=utf-8",
                    content="signed artifact content",
                    content_hash="artifact-hash",
                    filters={"platform": kwargs["platform"]},
                    filter_hash="filter-hash",
                    sort=str(kwargs["sort"]),
                    total_count=4,
                    row_count=2,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ), patch.dict(
            "os.environ",
            {
                "GENO_REPORT_ARTIFACT_SIGNING_SECRET": "signed-url-secret",
                "GENO_REPORT_ARTIFACT_SIGNED_URL_TTL_SECONDS": "600",
            },
            clear=True,
        ):
            signed_response = self.client.get(
                "/v1/reports/runtime/report-1/artifact/signed-url"
                "?type=markdown&platform=perplexity&sort=cost_desc"
            )
            self.assertEqual(signed_response.status_code, 200)
            payload = signed_response.json()
            self.assertEqual(payload["signature_version"], "report_artifact_hmac_sha256_v1")
            self.assertEqual(payload["ttl_seconds"], 600)
            self.assertIn("signature=", payload["download_url"])
            self.assertIn("expires_at=", payload["download_url"])

            download_path = payload["download_url"].replace("http://testserver", "")
            download_response = self.client.get(download_path)
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(download_response.text, "signed artifact content")
            self.assertEqual(download_response.headers["x-geno-report-artifact-signed"], "true")
            self.assertEqual(fake_repository.kwargs["platform"], "perplexity")

            tampered_path = download_path.replace("platform=perplexity", "platform=chatgpt")
            tampered_response = self.client.get(tampered_path)
            self.assertEqual(tampered_response.status_code, 401)
            self.assertIn("signature is invalid", tampered_response.json()["detail"])

    def test_runtime_report_artifact_signed_url_preserves_actor_under_access_control(self) -> None:
        class FakeRepository:
            def set_runtime_project_access_context(self, **kwargs: object) -> None:
                self.context = kwargs

            def get_report_export_project_id(self, *, report_export_id: str) -> str:
                self.report_export_id = report_export_id
                return "project-1"

            def get_project_member_role(self, *, project_id: str, actor_id: str) -> str:
                self.member_check = {"project_id": project_id, "actor_id": actor_id}
                return "owner"

            def get_runtime_report_artifact(self, **kwargs: object) -> RuntimeReportArtifact:
                return RuntimeReportArtifact(
                    report_export={"id": kwargs["report_export_id"], "report_version": "worker-runtime-v1"},
                    artifact_type=str(kwargs["artifact_type"]),
                    template=str(kwargs["template"]),
                    template_payload={"template": kwargs["template"]},
                    template_hash="template-hash",
                    filename="worker-runtime-v1.pdf",
                    media_type="application/pdf",
                    content=b"%PDF-1.4\nsigned\n%%EOF\n",
                    content_hash="artifact-hash",
                    filters={},
                    filter_hash="filter-hash",
                    sort=str(kwargs["sort"]),
                    total_count=1,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ), patch.dict(
            "os.environ",
            {
                "GENO_REPORT_ARTIFACT_SIGNING_SECRET": "signed-url-secret",
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
            },
            clear=True,
        ):
            signed_response = self.client.get(
                "/v1/reports/runtime/report-1/artifact/signed-url?type=pdf",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )
            self.assertEqual(signed_response.status_code, 200)
            download_url = signed_response.json()["download_url"]
            self.assertIn("signed_actor_id=agency-owner", download_url)

            download_path = download_url.replace("http://testserver", "")
            download_response = self.client.get(download_path)
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.headers["x-geno-report-artifact-signed"], "true")
        self.assertEqual(fake_repository.context["actor_id"], "agency-owner")
        self.assertEqual(fake_repository.member_check["actor_id"], "agency-owner")

    def test_runtime_action_plans_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/action-plans/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_action_plans_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_action_plans_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_action_plans_csv",
                    filename="runtime-action-plans.csv",
                    media_type="text/csv; charset=utf-8",
                    content="action_recommendation_id,status\nact-1,open\n",
                    content_hash="hash-action-plans-csv",
                    filters={"project_id": kwargs["project_id"], "status": kwargs["status"]},
                    total_count=2,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/action-plans/runtime/export.csv?project_id=project-1&status=open&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-action-plan-export-hash"], "hash-action-plans-csv")
        self.assertEqual(response.headers["x-geno-action-plan-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-action-plan-status"], "open")
        self.assertEqual(response.headers["x-geno-action-plan-row-count"], "1")
        self.assertEqual(response.headers["x-geno-action-plan-total-count"], "2")
        self.assertIn("runtime-action-plans.csv", response.headers["content-disposition"])
        self.assertIn("act-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["status"], "open")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_au_retest_scheduler_plan_endpoint_returns_replayable_plan(self) -> None:
        response = self.client.get("/v1/au-retest-scheduler-plan")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["plan_version"], "au_retest_scheduler_plan_v1")
        self.assertTrue(payload["retest_scheduler_plan_ready"])
        self.assertEqual(payload["scope"]["offsets_days"], [0, 7, 14, 30])
        self.assertEqual(payload["scope"]["planned_runs_per_window"], 2400)
        self.assertEqual(payload["scope"]["total_planned_runs"], 9600)
        self.assertEqual(payload["scheduler_policy"]["scheduler_status"], "planned_not_temporalized")
        self.assertFalse(payload["current_boundary"]["real_external_runs_completed"])
        self.assertEqual(payload["runtime_endpoints"]["retest_scheduler_plan"], "GET /v1/au-retest-scheduler-plan")

    def test_au_retest_execution_status_endpoint_reports_missing_window_artifacts(self) -> None:
        response = self.client.get("/v1/au-retest-execution-status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status_version"], "au_retest_execution_status_v1")
        self.assertEqual(payload["status"], "fail")
        self.assertTrue(payload["execution_status_report_ready"])
        self.assertFalse(payload["retest_execution_ready"])
        self.assertFalse(payload["comparison_allowed"])
        self.assertEqual(payload["summary"]["window_count"], 4)
        self.assertEqual(payload["summary"]["ready_window_count"], 0)
        self.assertEqual(payload["summary"]["missing_artifact_count"], 8)
        self.assertEqual(payload["next_action"], "run_retest_window:baseline")
        self.assertEqual(
            payload["runtime_endpoints"]["retest_execution_status"],
            "GET /v1/au-retest-execution-status",
        )

    def test_runtime_alerts_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/runtime-alerts")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_alerts_endpoint_passes_filters(self) -> None:
        class FakeRepository:
            def list_runtime_alerts(self, **kwargs: object) -> RuntimeAlertPage:
                self.kwargs = kwargs
                return RuntimeAlertPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    records=(
                        RuntimeAlertItem(
                            alert={
                                "id": "runtime-alert-1",
                                "project_id": kwargs["project_id"],
                                "alert_type": kwargs["alert_type"],
                                "severity": kwargs["severity"],
                                "title": "Brand mention coverage is below threshold",
                                "metric_name": "mention_rate",
                                "metric_value": 0.25,
                                "threshold": 0.5,
                                "rule_version": "runtime_alerts_v1",
                            },
                            evidence_refs=({"target_type": "visibility_score_snapshot", "target_id": "snapshot-1"},),
                            related_actions=({"id": "action-1", "title": "Improve brand mention coverage"},),
                            audit_events=({"event_type": "visibility_score_snapshot_created"},),
                        ),
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-alerts"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&alert_type=brand_absent&severity=high&limit=5&offset=2"
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["records"][0]["alert"]["rule_version"], "runtime_alerts_v1")
        self.assertEqual(payload["records"][0]["evidence_refs"][0]["target_type"], "visibility_score_snapshot")
        self.assertEqual(payload["records"][0]["related_actions"][0]["id"], "action-1")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["alert_type"], "brand_absent")
        self.assertEqual(fake_repository.kwargs["severity"], "high")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 2)

    def test_runtime_alerts_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_alerts_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_alerts_csv",
                    filename="runtime-alerts.csv",
                    media_type="text/csv; charset=utf-8",
                    content="alert_id,alert_type\nruntime-alert-1,brand_absent\n",
                    content_hash="hash-runtime-alerts-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "alert_type": kwargs["alert_type"],
                        "severity": kwargs["severity"],
                    },
                    total_count=3,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/runtime-alerts/export.csv?project_id=project-1&alert_type=brand_absent&severity=high&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-runtime-alert-export-hash"], "hash-runtime-alerts-csv")
        self.assertEqual(response.headers["x-geno-runtime-alert-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-runtime-alert-type"], "brand_absent")
        self.assertEqual(response.headers["x-geno-runtime-alert-severity"], "high")
        self.assertEqual(response.headers["x-geno-runtime-alert-row-count"], "1")
        self.assertEqual(response.headers["x-geno-runtime-alert-total-count"], "3")
        self.assertIn("runtime-alerts.csv", response.headers["content-disposition"])
        self.assertIn("runtime-alert-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["alert_type"], "brand_absent")
        self.assertEqual(fake_repository.kwargs["severity"], "high")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_alert_event_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def record_runtime_alert_event(self, event: object) -> RuntimeAlertEvent:
                self.event = event
                return RuntimeAlertEvent(
                    alert_event={
                        "id": "alert-event-1",
                        "project_id": event.project_id,
                        "alert_id": event.alert_id,
                        "alert_type": event.alert_type,
                        "source": event.source,
                        "source_id": event.source_id,
                        "status": event.status,
                        "updated_by": event.updated_by,
                        "note": event.note,
                        "metadata": event.metadata,
                        "created_at": datetime(2026, 6, 12, tzinfo=UTC),
                    },
                    audit_events=({"event_type": "runtime_alert_event_recorded"},),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-alerts/runtime-alert-1/events",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "alert_type": "brand_absent",
                    "source": "visibility_score_snapshot",
                    "source_id": "snapshot-1",
                    "status": "escalated",
                    "updated_by": "analyst-1",
                    "note": "SLA threshold breached",
                    "metadata": {"severity": "high"},
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["alert_event"]["status"], "escalated")
        self.assertEqual(payload["audit_events"][0]["event_type"], "runtime_alert_event_recorded")
        self.assertEqual(fake_repository.event.alert_id, "runtime-alert-1")
        self.assertEqual(fake_repository.event.project_id, "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.event.updated_by, "analyst-1")

    def test_runtime_alert_notifications_endpoint_passes_payload(self) -> None:
        class FakeRepository:
            def enqueue_runtime_alert_notifications(self, **kwargs: object) -> RuntimeAlertNotificationResult:
                self.kwargs = kwargs
                return RuntimeAlertNotificationResult(
                    project_id=str(kwargs["project_id"]),
                    notification_count=2,
                    delivery_count=1,
                    skipped_count=1,
                    notifications=(
                        {
                            "id": "notification-1",
                            "notification_type": "runtime_alert",
                            "severity": "warning",
                            "target_type": "runtime_alert",
                        },
                    ),
                    audit_events=(
                        {"event_type": "runtime_notification_created"},
                        {"event_type": "runtime_notification_delivery_queued"},
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.post(
                "/v1/runtime-alerts/notifications",
                json={
                    "project_id": "9a50797d-a341-55a4-8bdf-cc255c017e5c",
                    "alert_type": "brand_absent",
                    "severity": "high",
                    "created_by": "analyst-1",
                    "reason": "notify owner",
                    "include_resolved": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["notification_count"], 2)
        self.assertEqual(payload["delivery_count"], 1)
        self.assertEqual(payload["audit_events"][1]["event_type"], "runtime_notification_delivery_queued")
        self.assertEqual(fake_repository.kwargs["project_id"], "9a50797d-a341-55a4-8bdf-cc255c017e5c")
        self.assertEqual(fake_repository.kwargs["alert_type"], "brand_absent")
        self.assertEqual(fake_repository.kwargs["severity"], "high")
        self.assertEqual(fake_repository.kwargs["created_by"], "analyst-1")
        self.assertTrue(fake_repository.kwargs["include_resolved"])

    def test_runtime_content_engines_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/content-engines/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_content_engines_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_content_engines_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_content_engines_csv",
                    filename="runtime-content-engines.csv",
                    media_type="text/csv; charset=utf-8",
                    content="project_id,content_draft_id\nproject-1,draft-1\n",
                    content_hash="hash-content-engines-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "review_status": kwargs["review_status"],
                    },
                    total_count=2,
                    row_count=1,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/content-engines/runtime/export.csv"
                "?project_id=project-1&review_status=pending_human_review&limit=5",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-content-engine-export-hash"], "hash-content-engines-csv")
        self.assertEqual(response.headers["x-geno-content-engine-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-content-engine-review-status"], "pending_human_review")
        self.assertEqual(response.headers["x-geno-content-engine-row-count"], "1")
        self.assertEqual(response.headers["x-geno-content-engine-total-count"], "2")
        self.assertIn("runtime-content-engines.csv", response.headers["content-disposition"])
        self.assertIn("draft-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["review_status"], "pending_human_review")
        self.assertEqual(fake_repository.kwargs["limit"], 5)

    def test_runtime_knowledge_fact_search_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get(
            "/v1/knowledge-facts/runtime/search"
            "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c&query=Australia%20shipping"
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_knowledge_fact_search_endpoint_passes_query(self) -> None:
        class FakeRepository:
            def search_runtime_knowledge_facts(self, **kwargs: object) -> RuntimeKnowledgeSearchPage:
                self.kwargs = kwargs
                return RuntimeKnowledgeSearchPage(
                    total_count=1,
                    limit=int(kwargs["limit"]),
                    offset=int(kwargs["offset"]),
                    query=str(kwargs["query"]),
                    market_code=str(kwargs["market_code"]),
                    city=str(kwargs["city"]) if kwargs["city"] else None,
                    embedding_model=str(kwargs["embedding_model"]),
                    records=(
                        RuntimeKnowledgeSearchResult(
                            fact={
                                "id": "06975d61-853b-5a25-ae0e-b62bbfe82c15",
                                "market_code": "AU",
                                "fact_type": "australian_shipping_policy",
                                "subject": "ExampleBrand",
                                "predicate": "supports_market",
                                "object_value": "AU shipping",
                            },
                            score=0.91,
                            fallback_used=False,
                            embedding_model=str(kwargs["embedding_model"]),
                        ),
                    ),
                    audit_events=(
                        {
                            "event_type": "knowledge_fact_embeddings_indexed",
                            "target_type": "knowledge_fact_embedding_index",
                            "method_version": "knowledge_fact_embedding_v1",
                        },
                    ),
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/knowledge-facts/runtime/search"
                "?project_id=9a50797d-a341-55a4-8bdf-cc255c017e5c"
                "&query=Australia%20shipping&market_code=AU&city=Sydney&limit=5&offset=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["records"][0]["fact"]["fact_type"], "australian_shipping_policy")
        self.assertEqual(payload["audit_events"][0]["event_type"], "knowledge_fact_embeddings_indexed")
        self.assertEqual(fake_repository.kwargs["query"], "Australia shipping")
        self.assertEqual(fake_repository.kwargs["city"], "Sydney")
        self.assertEqual(fake_repository.kwargs["limit"], 5)
        self.assertEqual(fake_repository.kwargs["offset"], 1)

    def test_runtime_traceability_endpoint_requires_persistence_config(self) -> None:
        response = self.client.get("/v1/traceability/runtime")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.json()["detail"])

    def test_runtime_traceability_export_endpoint_returns_csv_with_hash_headers(self) -> None:
        class FakeRepository:
            def export_runtime_traceability_csv(self, **kwargs: object) -> RuntimeEvidenceExport:
                self.kwargs = kwargs
                return RuntimeEvidenceExport(
                    export_type="runtime_traceability_csv",
                    filename="runtime-traceability.csv",
                    media_type="text/csv; charset=utf-8",
                    content="traceability_bundle_id,project_id\nbundle-1,project-1\n",
                    content_hash="hash-traceability-csv",
                    filters={
                        "project_id": kwargs["project_id"],
                        "report_export_id": kwargs["report_export_id"],
                    },
                    total_count=1,
                    row_count=2,
                )

        fake_repository = FakeRepository()
        with patch("geno_api.main.build_repository_from_env", return_value=fake_repository), patch(
            "geno_api.main.close_repository_connection"
        ):
            response = self.client.get(
                "/v1/traceability/runtime/export.csv?project_id=project-1&report_export_id=report-1",
                headers={"X-GENO-Actor-Id": "agency-owner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["x-geno-traceability-export-hash"], "hash-traceability-csv")
        self.assertEqual(response.headers["x-geno-traceability-project-id"], "project-1")
        self.assertEqual(response.headers["x-geno-traceability-report-export-id"], "report-1")
        self.assertEqual(response.headers["x-geno-traceability-row-count"], "2")
        self.assertEqual(response.headers["x-geno-traceability-total-count"], "1")
        self.assertIn("runtime-traceability.csv", response.headers["content-disposition"])
        self.assertIn("bundle-1", response.text)
        self.assertEqual(fake_repository.kwargs["project_id"], "project-1")
        self.assertEqual(fake_repository.kwargs["report_export_id"], "report-1")

    def test_m2b_google_spike_plan_endpoint(self) -> None:
        response = self.client.get("/v1/google-spikes/au/plan")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["planned_runs"], 240)
        self.assertEqual(payload["prompt_count"], 30)
        self.assertEqual(payload["surfaces"], ["google_aio", "google_ai_mode"])

    def test_m2b_google_spike_fixture_gate_endpoint(self) -> None:
        response = self.client.get("/v1/google-spikes/au/fixture-gate")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["record_count"], 240)
        self.assertEqual(payload["gate"]["gate_status"], "pass")
        self.assertFalse(payload["gate"]["limited_coverage"])
        self.assertEqual(payload["readiness_gate"]["gate_status"], "fail")
        self.assertIn("insufficient_collection_paths=1/2", payload["readiness_gate"]["failure_reasons"])

    def test_m3_visibility_score_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/visibility-scores/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["analysis_count"], 40)
        self.assertEqual(payload["snapshot"]["formula_version"], "au_visibility_v1")
        self.assertEqual(len(payload["contributions"]), 8)
        self.assertEqual(payload["audit_event"]["event_type"], "visibility_score_snapshot_created")

    def test_m4_citation_graph_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/citation-graphs/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["node_count"], 3)
        self.assertGreater(payload["evidence_link_count"], 0)
        self.assertGreater(payload["source_gap_count"], 0)
        self.assertEqual(payload["competitor_count"], 4)
        self.assertTrue(any(item["answer_run_ids"] for item in payload["competitor_benchmarks"]))

    def test_m5_report_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/reports/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["report_export"]["report_version"], "p0a-fixture-v1")
        self.assertTrue(payload["report_export"]["markdown_url"].endswith(".md"))
        self.assertTrue(payload["report_export"]["pdf_url"].endswith(".pdf"))
        self.assertTrue(payload["report_export"]["csv_url"].endswith(".csv"))
        self.assertIn("GENO AU Evidence Report", payload["markdown"])
        self.assertIn("### Method Disclosure", payload["markdown"])
        self.assertIn("Google spike gate: fail", payload["markdown"])
        self.assertIn("Google limited coverage: yes", payload["markdown"])
        self.assertIn("API-vs-browser fidelity: not_run", payload["markdown"])
        self.assertIn("Trigger rate denominator: all attempted evidence records in this report window", payload["markdown"])
        self.assertIn("Mention rate denominator: surface_triggered evidence records, not all attempted records", payload["markdown"])
        self.assertIn("Report evidence attempted records:", payload["markdown"])
        self.assertIn("### Audit Summary", payload["markdown"])
        self.assertIn("Audit events attached: 1", payload["markdown"])
        score_rate_disclosure = payload["report_export"]["method_disclosure"]["score_rate_denominators"]
        self.assertEqual(
            score_rate_disclosure["definitions"]["recommendation_rate"]["formula"],
            "brand_recommended_records / surface_triggered_records",
        )
        self.assertGreater(score_rate_disclosure["evidence_denominators"]["attempted_records"], 0)
        audit_summary = payload["report_export"]["method_disclosure"]["audit_summary"]
        self.assertEqual(audit_summary["audit_event_count"], 1)
        self.assertEqual(audit_summary["event_type_distribution"]["visibility_score_snapshot_created"], 1)
        self.assertIn("answer_run_id", payload["csv_content"])
        self.assertGreater(payload["pdf_size_bytes"], 0)
        self.assertEqual(len(payload["pdf_content_hash"]), 64)
        self.assertEqual(payload["audit_event"]["event_type"], "report_export_created")
        self.assertEqual(
            payload["report_evidence_answer_run_ids"],
            payload["report_export"]["answer_run_ids"],
        )

    def test_m6_action_plan_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/action-plans/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreater(payload["action_count"], 0)
        self.assertEqual(payload["retest_schedule"]["offsets_days"], [0, 7, 14, 30])
        self.assertEqual(payload["retest_comparison"]["trend"], "improved")
        self.assertEqual(payload["audit_event"]["event_type"], "action_plan_created")
        self.assertEqual(payload["comparison_audit_event"]["event_type"], "retest_comparison_created")

    def test_m7_content_engine_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/content-engines/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreater(payload["knowledge_fact_count"], 0)
        self.assertGreater(payload["content_draft_count"], 0)
        self.assertEqual(payload["audit_event"]["event_type"], "content_engine_fixture_created")
        self.assertTrue(all(item["review_status"] == "pending_human_review" for item in payload["content_drafts"]))
        self.assertTrue(all(item["used_knowledge_fact_ids"] for item in payload["content_drafts"]))
        self.assertTrue(all(item["evidence_answer_run_ids"] for item in payload["content_drafts"]))
        self.assertEqual(len(payload["integration_connectors"]), 7)
        self.assertEqual(len(payload["manual_distribution_records"]), payload["content_draft_count"])

    def test_traceability_fixture_endpoint(self) -> None:
        response = self.client.get("/v1/traceability/au/p0a-fixture")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        bundle = payload["traceability_bundle"]
        self.assertEqual(payload["answer_run_count"], 40)
        self.assertEqual(payload["score_contribution_count"], 8)
        self.assertEqual(bundle["report_export_ids"], [payload["report_export"]["id"]])
        self.assertEqual(bundle["answer_run_ids"], payload["report_export"]["answer_run_ids"])
        self.assertEqual(len(bundle["raw_answer_ids"]), payload["answer_run_count"])
        self.assertGreater(len(bundle["answer_citation_ids"]), 0)
        self.assertGreater(len(bundle["evidence_asset_ids"]), 0)
        self.assertTrue(any(link["relation_type"] == "explained_by" for link in bundle["evidence_links"]))
        self.assertTrue(any(link["relation_type"] == "supports_draft" for link in bundle["evidence_links"]))

    def test_contracts_include_m7_content_integrations(self) -> None:
        response = self.client.get("/v1/contracts")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("CollectorBackend", payload["interfaces"])
        self.assertIn("ParserEngine", payload["interfaces"])
        self.assertIn("ScoringFormula", payload["interfaces"])
        self.assertIn("ReportExporter", payload["interfaces"])
        self.assertIn("NotConfiguredCollectorBackend", payload["interfaces"])
        self.assertIn("NotConfiguredParserEngine", payload["interfaces"])
        self.assertIn("NotConfiguredScoringFormula", payload["interfaces"])
        self.assertIn("NotConfiguredReportExporter", payload["interfaces"])
        self.assertIn("RegistryScoringFormula", payload["interfaces"])
        self.assertIn("LocalizedKnowledgeFact", payload["m7_content_integrations"])
        self.assertIn("ContentDraft", payload["m7_content_integrations"])
        self.assertIn("ManualDistributionRecord", payload["m7_content_integrations"])
        self.assertIn("KnowledgeFactEmbedding", payload["m7_content_integrations"])
        self.assertIn("RuntimeKnowledgeSearchResult", payload["m7_content_integrations"])
        self.assertIn("RuntimeKnowledgeSearchPage", payload["m7_content_integrations"])
        self.assertIn("InMemoryPgVectorStore", payload["m7_content_integrations"])
        self.assertIn("InMemoryQdrantVectorStore", payload["m7_content_integrations"])
        self.assertIn("summarize_vector_search", payload["m7_content_integrations"])
        self.assertIn("InMemoryPostgresAdjacencyGraphStore", payload["m4_graph_benchmark"])
        self.assertIn("InMemoryNeo4jCitationGraphStore", payload["m4_graph_benchmark"])
        self.assertIn("summarize_citation_graph_store", payload["m4_graph_benchmark"])
        self.assertIn("EntityAlias", payload["m1_bootstrap"])
        self.assertIn("EntityAliasInput", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAlias", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasBatchConfirmResult", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidate", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidatePage", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidateReview", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidateReviewPage", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidateAssignmentQueueStats", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasAssignmentWorkbench", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasAssignmentWorkloadSummary", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasAssignmentDispatchPlan", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasAssignmentDispatchApplyResult", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasAssignmentNotificationResult", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasAssignmentEscalationResult", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasAssignmentReassignmentResult", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasCandidateBatchReviewResult", payload["m1_bootstrap"])
        self.assertIn("EntityAliasCandidateAssignmentActionInput", payload["m1_bootstrap"])
        self.assertIn("EntityAliasCandidateAssignmentBatchActionInput", payload["m1_bootstrap"])
        self.assertIn("EntityAliasCandidateAssignmentInput", payload["m1_bootstrap"])
        self.assertIn("EntityAliasCandidateAssignmentReassignmentInput", payload["m1_bootstrap"])
        self.assertIn("EntityAliasAssignmentDispatchPlanInput", payload["m1_bootstrap"])
        self.assertIn("EntityAliasAssignmentDispatchApplyInput", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasAssignmentBatchActionResult", payload["m1_bootstrap"])
        self.assertIn("RuntimeEntityAliasPage", payload["m1_bootstrap"])
        self.assertIn("TraceabilityBundle", payload["auditability"])
        self.assertIn("RuntimeFidelityCheck", payload["auditability"])
        self.assertIn("RuntimeFidelityTrend", payload["auditability"])
        self.assertIn("RuntimeAlertItem", payload["auditability"])
        self.assertIn("RuntimeAlertPage", payload["auditability"])
        self.assertIn("RuntimeAlertEvent", payload["auditability"])
        self.assertIn("build_traceability_bundle", payload["traceability"])
        self.assertIn("CollectionRunSummary", payload["m2a_evidence"])
        self.assertIn("BrowserFidelitySamplingPlan", payload["m2a_evidence"])
        self.assertIn("P0ACollectionReadinessGate", payload["m2a_evidence"])
        self.assertIn("evaluate_p0a_collection_readiness", payload["m2a_evidence"])
        self.assertIn("build_browser_fidelity_sampling_plan", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityCheck", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityCheckPage", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityTrend", payload["m2a_evidence"])
        self.assertIn("RuntimeFidelityTrendPoint", payload["m2a_evidence"])
        self.assertIn("FixtureChatGPTSearchBrowserCollector", payload["m2a_evidence"])
        self.assertIn("PlaywrightChatGPTSearchCollector", payload["m2a_evidence"])
        self.assertIn("GoogleSpikeReadinessGate", payload["m2b_google_spike"])
        self.assertIn("evaluate_google_spike_readiness_gate", payload["m2b_google_spike"])
        self.assertIn("LLMJudgeAnswerParser", payload["m3_analysis_scoring"])
        self.assertIn("ComparativeAnswerParser", payload["m3_analysis_scoring"])
        self.assertIn("parser_ab_compare_v1", payload["m3_analysis_scoring"])
        self.assertIn("FixtureLLMGateway", payload["m3_analysis_scoring"])
        self.assertIn("LiteLLMGateway", payload["m3_analysis_scoring"])
        self.assertIn("LLMCallLog", payload["m3_analysis_scoring"])
        self.assertIn("RuntimeScoreWeightConfig", payload["m3_analysis_scoring"])
        self.assertIn("ScoreWeightConfigRequest", payload["m3_analysis_scoring"])
        self.assertIn("ScoreFormulaDefinition", payload["m3_analysis_scoring"])
        self.assertIn("RegistryScoringFormula", payload["m3_analysis_scoring"])
        self.assertIn("SCORE_FORMULA_REGISTRY", payload["m3_analysis_scoring"])
        self.assertIn("list_score_formulas", payload["m3_analysis_scoring"])
        self.assertIn("build_score_input_policy", payload["m3_analysis_scoring"])
        self.assertIn("rescore_snapshot_with_formula", payload["m3_analysis_scoring"])
        self.assertIn("RuntimeHumanReviewRecord", payload["m3_analysis_scoring"])
        self.assertIn("RuntimeHumanReviewQueuePage", payload["m3_analysis_scoring"])
        self.assertIn("RuntimeHumanReviewInput", payload["m3_analysis_scoring"])
        self.assertIn("HumanReviewRequest", payload["m3_analysis_scoring"])
        self.assertIn("LLMCallLog", payload["auditability"])
        self.assertIn("RuntimeHumanReviewRecord", payload["auditability"])
        self.assertIn("RuntimeHumanReviewQueuePage", payload["auditability"])
        self.assertIn("RuntimeEvidenceRun", payload["persistence"])
        self.assertIn("RuntimeEvidenceExport", payload["persistence"])
        self.assertIn("RuntimeCollectionRun", payload["persistence"])
        self.assertIn("RuntimeCollectionRunPage", payload["persistence"])
        self.assertIn("RuntimeFidelityCheck", payload["persistence"])
        self.assertIn("RuntimeFidelityCheckPage", payload["persistence"])
        self.assertIn("RuntimeFidelityTrend", payload["persistence"])
        self.assertIn("RuntimeFidelityTrendPoint", payload["persistence"])
        self.assertIn("RuntimeFidelityCheckRequest", payload["persistence"])
        self.assertIn("ManualBackfillInput", payload["persistence"])
        self.assertIn("EntityAliasInput", payload["persistence"])
        self.assertIn("RuntimeEntityAlias", payload["persistence"])
        self.assertIn("RuntimeEntityAliasBatchConfirmResult", payload["persistence"])
        self.assertIn("RuntimeEntityAliasCandidate", payload["persistence"])
        self.assertIn("RuntimeEntityAliasCandidatePage", payload["persistence"])
        self.assertIn("RuntimeEntityAliasCandidateReview", payload["persistence"])
        self.assertIn("RuntimeEntityAliasCandidateReviewPage", payload["persistence"])
        self.assertIn("RuntimeEntityAliasCandidateBatchReviewResult", payload["persistence"])
        self.assertIn("RuntimeEntityAliasAssignmentWorkbench", payload["persistence"])
        self.assertIn("RuntimeEntityAliasAssignmentWorkloadSummary", payload["persistence"])
        self.assertIn("RuntimeEntityAliasAssignmentDispatchPlan", payload["persistence"])
        self.assertIn("RuntimeEntityAliasAssignmentDispatchApplyResult", payload["persistence"])
        self.assertIn("RuntimeEntityAliasAssignmentEscalationResult", payload["persistence"])
        self.assertIn("RuntimeEntityAliasAssignmentReassignmentResult", payload["persistence"])
        self.assertIn("RuntimeEntityAliasAssignmentBatchActionResult", payload["persistence"])
        self.assertIn("EntityAliasCandidateReviewInput", payload["persistence"])
        self.assertIn("EntityAliasCandidateAssignmentActionInput", payload["persistence"])
        self.assertIn("EntityAliasCandidateAssignmentBatchActionInput", payload["persistence"])
        self.assertIn("EntityAliasCandidateAssignmentInput", payload["persistence"])
        self.assertIn("EntityAliasCandidateAssignmentReassignmentInput", payload["persistence"])
        self.assertIn("EntityAliasAssignmentDispatchPlanInput", payload["persistence"])
        self.assertIn("EntityAliasAssignmentDispatchApplyInput", payload["persistence"])
        self.assertIn("EntityAliasCandidateReviewRequest", payload["persistence"])
        self.assertIn("EntityAliasCandidateBatchReviewRequest", payload["persistence"])
        self.assertIn("EntityAliasCandidateAssignmentActionRequest", payload["persistence"])
        self.assertIn("EntityAliasCandidateAssignmentBatchActionRequest", payload["persistence"])
        self.assertIn("EntityAliasCandidateAssignmentRequest", payload["persistence"])
        self.assertIn("EntityAliasCandidateAssignmentReassignmentRequest", payload["persistence"])
        self.assertIn("EntityAliasAssignmentDispatchApplyRequest", payload["persistence"])
        self.assertIn("EntityAliasAssignmentNotificationRequest", payload["persistence"])
        self.assertIn("RuntimeEntityAliasPage", payload["persistence"])
        self.assertIn("RuntimeSavedView", payload["persistence"])
        self.assertIn("RuntimeSavedViewInput", payload["persistence"])
        self.assertIn("RuntimeSavedViewPage", payload["persistence"])
        self.assertIn("RuntimeProject", payload["persistence"])
        self.assertIn("RuntimeProjectPage", payload["persistence"])
        self.assertIn("RuntimeProjectLifecycleEvent", payload["persistence"])
        self.assertIn("RuntimeProjectLifecycleEventExport", payload["persistence"])
        self.assertIn("RuntimeProjectLifecycleEventPage", payload["persistence"])
        self.assertIn("RuntimeProjectActionInput", payload["persistence"])
        self.assertIn("RuntimeProjectActionRequest", payload["persistence"])
        self.assertIn("RuntimeProjectUpdateInput", payload["persistence"])
        self.assertIn("RuntimeProjectUpdateRequest", payload["persistence"])
        self.assertIn("RuntimeProjectMember", payload["persistence"])
        self.assertIn("RuntimeProjectMemberPage", payload["persistence"])
        self.assertIn("RuntimeProjectMemberInput", payload["persistence"])
        self.assertIn("ProjectMemberRequest", payload["persistence"])
        self.assertIn("RuntimeProjectMemberInvitation", payload["persistence"])
        self.assertIn("RuntimeProjectMemberInvitationPage", payload["persistence"])
        self.assertIn("RuntimeProjectMemberInvitationInput", payload["persistence"])
        self.assertIn("RuntimeProjectMemberInvitationActionInput", payload["persistence"])
        self.assertIn("RuntimeProjectMemberInvitationAcceptInput", payload["persistence"])
        self.assertIn("RuntimeProjectMemberInvitationEmailInput", payload["persistence"])
        self.assertIn("ProjectMemberInvitationRequest", payload["persistence"])
        self.assertIn("ProjectMemberInvitationActionRequest", payload["persistence"])
        self.assertIn("ProjectMemberInvitationAcceptRequest", payload["persistence"])
        self.assertIn("ProjectMemberInvitationEmailRequest", payload["persistence"])
        self.assertIn("POST /v1/projects/runtime/action", payload["persistence"])
        self.assertIn("PATCH /v1/projects/runtime", payload["persistence"])
        self.assertIn("/v1/projects/runtime/lifecycle-events", payload["persistence"])
        self.assertIn("/v1/project-member-invitations/runtime", payload["persistence"])
        self.assertIn("/v1/project-member-invitations/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/project-member-invitations/runtime/action", payload["persistence"])
        self.assertIn("/v1/project-member-invitations/runtime/email", payload["persistence"])
        self.assertIn("/v1/project-member-invitations/runtime/accept", payload["persistence"])
        self.assertIn("RuntimeProjectBrandKit", payload["persistence"])
        self.assertIn("RuntimeProjectBrandKitInput", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAsset", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetPage", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetInput", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetScanInput", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetVersion", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetVersionPage", payload["persistence"])
        self.assertIn("RuntimeProjectBrandAssetActivationInput", payload["persistence"])
        self.assertIn("RuntimeProjectBrandLogoUpload", payload["persistence"])
        self.assertIn("ProjectBrandKitRequest", payload["persistence"])
        self.assertIn("ProjectBrandAssetRequest", payload["persistence"])
        self.assertIn("ProjectBrandAssetScanRequest", payload["persistence"])
        self.assertIn("ProjectBrandAssetActivationRequest", payload["persistence"])
        self.assertIn("RuntimeScoreWeightConfig", payload["persistence"])
        self.assertIn("RuntimeScoreWeightConfigInput", payload["persistence"])
        self.assertIn("ScoreWeightConfigRequest", payload["persistence"])
        self.assertIn("ScoreFormulaDefinition", payload["persistence"])
        self.assertIn("RuntimeHumanReviewRecord", payload["persistence"])
        self.assertIn("RuntimeHumanReviewPage", payload["persistence"])
        self.assertIn("RuntimeHumanReviewQueueItem", payload["persistence"])
        self.assertIn("RuntimeHumanReviewQueuePage", payload["persistence"])
        self.assertIn("RuntimeHumanReviewInput", payload["persistence"])
        self.assertIn("HumanReviewRequest", payload["persistence"])
        self.assertIn("RuntimePromptPage", payload["persistence"])
        self.assertIn("RuntimePromptImportHistoryItem", payload["persistence"])
        self.assertIn("RuntimePromptImportHistoryPage", payload["persistence"])
        self.assertIn("RuntimePromptImportInput", payload["persistence"])
        self.assertIn("RuntimePromptImportResult", payload["persistence"])
        self.assertIn("RuntimePromptImportRequest", payload["persistence"])
        self.assertIn("RuntimeScoreSnapshot", payload["persistence"])
        self.assertIn("RuntimeCitationGraph", payload["persistence"])
        self.assertIn("RuntimeReportArtifact", payload["persistence"])
        self.assertIn("RuntimeReportExport", payload["persistence"])
        self.assertIn("RuntimeReportExportJob", payload["persistence"])
        self.assertIn("RuntimeReportExportJobPage", payload["persistence"])
        self.assertIn("RuntimeReportExportJobQueueStats", payload["persistence"])
        self.assertIn("RuntimeReportExportJobInput", payload["persistence"])
        self.assertIn("RuntimeReportExportJobStatusInput", payload["persistence"])
        self.assertIn("RuntimeReportExportJobRequest", payload["persistence"])
        self.assertIn("RuntimeReportExportJobStatusRequest", payload["persistence"])
        self.assertIn("RuntimeNotification", payload["persistence"])
        self.assertIn("RuntimeNotificationPage", payload["persistence"])
        self.assertIn("RuntimeNotificationStatusInput", payload["persistence"])
        self.assertIn("RuntimeNotificationStatusRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationSubscription", payload["persistence"])
        self.assertIn("RuntimeNotificationSubscriptionPage", payload["persistence"])
        self.assertIn("RuntimeNotificationSubscriptionInput", payload["persistence"])
        self.assertIn("RuntimeNotificationSubscriptionRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationDelivery", payload["persistence"])
        self.assertIn("RuntimeNotificationDeliveryPage", payload["persistence"])
        self.assertIn("RuntimeNotificationDeliveryStatusInput", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedback", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedbackInput", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedbackPage", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedbackRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedbackWebhookRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailProviderFeedbackAdapter", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedbackProjectSuppressionInput", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedbackProjectSuppressionRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedbackSuppressionInput", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailFeedbackSuppressionRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailSuppression", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailSuppressionInput", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailSuppressionPage", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailSuppressionRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailPreferenceStatus", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailPreferenceResubscribeInput", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailPreferenceResubscribeRequest", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailPreferenceUnsubscribeInput", payload["persistence"])
        self.assertIn("RuntimeNotificationEmailPreferenceUnsubscribeRequest", payload["persistence"])
        self.assertIn("RuntimeReportManagementInput", payload["persistence"])
        self.assertIn("RuntimeReportManagementEventRequest", payload["persistence"])
        self.assertIn("RuntimeActionPlan", payload["persistence"])
        self.assertIn("RuntimeActionPlanPage", payload["persistence"])
        self.assertIn("RuntimeAlertItem", payload["persistence"])
        self.assertIn("RuntimeAlertPage", payload["persistence"])
        self.assertIn("RuntimeAlertEvent", payload["persistence"])
        self.assertIn("RuntimeAlertEventInput", payload["persistence"])
        self.assertIn("RuntimeAlertEventRequest", payload["persistence"])
        self.assertIn("RuntimeAlertNotificationRequest", payload["persistence"])
        self.assertIn("RuntimeAlertNotificationResult", payload["persistence"])
        self.assertIn("RuntimeContentEngine", payload["persistence"])
        self.assertIn("RuntimeKnowledgeSearchResult", payload["persistence"])
        self.assertIn("RuntimeKnowledgeSearchPage", payload["persistence"])
        self.assertIn("RuntimeTraceabilityDetail", payload["persistence"])
        self.assertIn("RuntimeComponentDiagnostic", payload["persistence"])
        self.assertIn("RuntimeDiagnostics", payload["persistence"])
        self.assertIn("build_runtime_diagnostics", payload["persistence"])
        self.assertIn("runtime_database_diagnostic", payload["persistence"])
        self.assertIn("runtime_object_store_diagnostic", payload["persistence"])
        self.assertIn("runtime_auth_diagnostic", payload["persistence"])
        self.assertIn("build_object_store_from_env", payload["persistence"])
        self.assertIn("archive_project_brand_logo", payload["persistence"])
        self.assertIn("RuntimeAuditEvent", payload["persistence"])
        self.assertIn("RuntimeAuditEventPage", payload["persistence"])
        self.assertIn("RuntimeAuditEventExport", payload["persistence"])
        self.assertIn("/v1/projects/runtime", payload["persistence"])
        self.assertIn("/v1/projects/runtime/au/dtc-ecommerce", payload["persistence"])
        self.assertIn("/v1/projects/runtime/lifecycle-events", payload["persistence"])
        self.assertIn("/v1/projects/runtime/lifecycle-events/export.csv", payload["persistence"])
        self.assertIn("/v1/audit-events/runtime", payload["persistence"])
        self.assertIn("/v1/audit-events/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/project-members/runtime", payload["persistence"])
        self.assertIn("/v1/project-members/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/reviews", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-workbench", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-workload", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-dispatch-plan", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-dispatch-apply", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-notifications", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-escalations", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-reassignments", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/review", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/review-batch", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assign", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-action", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/candidates/assignment-actions", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/confirm", payload["persistence"])
        self.assertIn("/v1/entity-aliases/runtime/confirm-batch", payload["persistence"])
        self.assertIn("/v1/prompts/runtime", payload["persistence"])
        self.assertIn("/v1/prompts/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/prompts/runtime/imports", payload["persistence"])
        self.assertIn("/v1/prompts/runtime/import.csv", payload["persistence"])
        self.assertIn("/v1/prompts/runtime/import.file", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime", payload["persistence"])
        self.assertIn("/v1/collection-runs/runtime", payload["persistence"])
        self.assertIn("/v1/collection-runs/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/fidelity-checks/runtime", payload["persistence"])
        self.assertIn("/v1/fidelity-checks/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/fidelity-checks/runtime/trend", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/evidence-runs/runtime/manual-backfill", payload["persistence"])
        self.assertIn("/v1/runtime-saved-views", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime/logo", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime/assets", payload["persistence"])
        self.assertIn("/v1/project-brand-kits/runtime/assets/activate", payload["persistence"])
        self.assertIn("/v1/project-brand-assets/runtime", payload["persistence"])
        self.assertIn("/v1/score-weight-configs/runtime", payload["persistence"])
        self.assertIn("/v1/score-formulas/runtime", payload["persistence"])
        self.assertIn("/v1/human-reviews/runtime", payload["persistence"])
        self.assertIn("/v1/human-reviews/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/human-reviews/runtime/queue", payload["persistence"])
        self.assertIn("/v1/visibility-scores/runtime", payload["persistence"])
        self.assertIn("/v1/visibility-scores/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/citation-graphs/runtime", payload["persistence"])
        self.assertIn("/v1/citation-graphs/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/reports/runtime", payload["persistence"])
        self.assertIn("/v1/reports/runtime/management-events/export.csv", payload["persistence"])
        self.assertIn("/v1/report-export-jobs/runtime", payload["persistence"])
        self.assertIn("/v1/report-export-jobs/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/report-export-jobs/runtime/stats", payload["persistence"])
        self.assertIn("/v1/report-export-jobs/runtime/{job_id}/status", payload["persistence"])
        self.assertIn("/v1/runtime-notifications", payload["persistence"])
        self.assertIn("/v1/runtime-notifications/export.csv", payload["persistence"])
        self.assertIn("/v1/runtime-notification-subscriptions", payload["persistence"])
        self.assertIn("/v1/runtime-notification-deliveries", payload["persistence"])
        self.assertIn("/v1/runtime-notification-email-feedback-events", payload["persistence"])
        self.assertIn("/v1/runtime-notification-email-feedback-webhooks/geno", payload["persistence"])
        self.assertIn("/v1/runtime-notification-email-feedback-webhooks/{provider}", payload["persistence"])
        self.assertIn(
            "/v1/runtime-notification-email-feedback-events/{feedback_event_id}/suppress-recipient",
            payload["persistence"],
        )
        self.assertIn(
            "/v1/runtime-notification-email-feedback-events/{feedback_event_id}/project-suppression",
            payload["persistence"],
        )
        self.assertIn("/v1/runtime-notification-email-suppressions", payload["persistence"])
        self.assertIn("/v1/runtime-notification-email-suppressions/export.csv", payload["persistence"])
        self.assertIn("/v1/runtime-notification-email-preferences/status", payload["persistence"])
        self.assertIn("/v1/runtime-notification-email-preferences/resubscribe", payload["persistence"])
        self.assertIn("/v1/runtime-notification-email-preferences/unsubscribe", payload["persistence"])
        self.assertIn("/v1/runtime-notification-deliveries/{delivery_id}/email-feedback", payload["persistence"])
        self.assertIn("/v1/runtime-notifications/{notification_id}/status", payload["persistence"])
        self.assertIn("/v1/reports/runtime/{report_export_id}/management-events", payload["persistence"])
        self.assertIn("/v1/reports/runtime/{report_export_id}/artifact", payload["persistence"])
        self.assertIn("/v1/reports/runtime/{report_export_id}/artifact/signed-url", payload["persistence"])
        self.assertIn("/v1/action-plans/runtime", payload["persistence"])
        self.assertIn("/v1/action-plans/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/runtime-alerts", payload["persistence"])
        self.assertIn("/v1/runtime-alerts/export.csv", payload["persistence"])
        self.assertIn("/v1/runtime-alerts/notifications", payload["persistence"])
        self.assertIn("/v1/runtime-alerts/{alert_id}/events", payload["persistence"])
        self.assertIn("/v1/content-engines/runtime", payload["persistence"])
        self.assertIn("/v1/content-engines/runtime/export.csv", payload["persistence"])
        self.assertIn("/v1/knowledge-facts/runtime/search", payload["persistence"])
        self.assertIn("/v1/traceability/runtime", payload["persistence"])
        self.assertIn("/v1/traceability/runtime/export.csv", payload["persistence"])
        self.assertIn("/ready", payload["persistence"])
        self.assertIn("/v1/runtime-diagnostics", payload["persistence"])
        self.assertIn("/v1/launch-status/au", payload["persistence"])
        self.assertIn("/v1/launch-remediation-plan/au", payload["persistence"])
        self.assertIn("/v1/p0a-environment-checklist/au", payload["persistence"])
        self.assertIn("/v1/p0a-execution-checklist/au", payload["persistence"])
        self.assertIn("/v1/p0a-credential-request/au", payload["persistence"])
        self.assertIn("/v1/p0a-credential-fulfillment/au", payload["persistence"])
        self.assertIn("/v1/p0a-credential-clearance/au", payload["persistence"])
        self.assertIn("/v1/p0a-real-batch-request/au", payload["persistence"])
        self.assertIn("/v1/p0a-real-batch-fulfillment/au", payload["persistence"])
        self.assertIn("/v1/p0a-real-batch-clearance/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-execution-checklist/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-environment-request/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-environment-fulfillment/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-environment-clearance/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-manual-backfill-request/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-manual-backfill-fulfillment/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-manual-backfill-clearance/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-phase-execution-request/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-phase-execution-fulfillment/au", payload["persistence"])
        self.assertIn("/v1/p0b-google-phase-execution-clearance/au", payload["persistence"])
        self.assertIn("/v1/au-broader-platform-registry", payload["persistence"])
        self.assertIn("/v1/au-retest-scheduler-plan", payload["persistence"])
        self.assertIn("/v1/au-retest-execution-status", payload["persistence"])
        self.assertIn("/v1/handoff-dossier/au", payload["persistence"])
        self.assertIn("/v1/customer-handoff-readiness/au", payload["persistence"])
        self.assertIn("/v1/customer-handoff-clearance/au", payload["persistence"])
        self.assertIn("/v1/customer-handoff-package/au", payload["persistence"])
        self.assertIn("/v1/next-work-item/au", payload["persistence"])
        self.assertIn("/v1/delivery-progress/au", payload["persistence"])
        self.assertIn("/v1/external-dependency-handoff/au", payload["persistence"])
        self.assertIn("/v1/external-dependency-clearance/au", payload["persistence"])
        self.assertIn("/metrics", payload["persistence"])


if __name__ == "__main__":
    unittest.main()
