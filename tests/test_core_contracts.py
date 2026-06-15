from __future__ import annotations

import hashlib
import base64
import hmac
import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import NAMESPACE_URL, UUID, uuid5
from zipfile import ZipFile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from geno_core.action_plan import (
    build_action_plan_audit_event,
    build_action_recommendations,
    build_retest_schedule,
    build_retest_comparison_audit_event,
    compare_retest_windows,
)
from geno_core.audit import build_audit_event, hash_payload
from geno_core.analysis_pipeline import analyze_and_score_records
from geno_core.bootstrap import build_au_project_bootstrap
from geno_core.collection import (
    CollectionExecutionPolicy,
    build_collection_run_audit_event,
    build_collection_run_summary,
    build_manual_backfill_record,
    build_p0a_collection_plan,
    collect_prompt_once,
    collect_prompt_with_failure_record,
    evaluate_p0a_collection_readiness,
    run_collection_slice,
    run_fixture_collection_slice,
)
from geno_core.contracts import CollectorBackend, GraphStore, ParserEngine, ReportExporter, ScoringFormula, VectorStore
from geno_core.email_delivery import (
    PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE_VERSION,
    RUNTIME_NOTIFICATION_EMAIL_TEMPLATE_VERSION,
    render_project_member_invitation_email,
    render_runtime_notification_email,
    runtime_email_body_hash,
)
from geno_core.email_feedback_adapters import (
    RUNTIME_NOTIFICATION_EMAIL_PROVIDER_FEEDBACK_ADAPTER_VERSION,
    parse_runtime_notification_email_provider_feedback,
)
from geno_core.email_feedback_signatures import verify_runtime_notification_email_provider_signature
from geno_core.email_preferences import (
    RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_MANAGE_ACTION,
    runtime_notification_email_preference_token_hash,
    sign_runtime_notification_email_preference_token,
    verify_runtime_notification_email_preference_token,
)
from geno_core.collectors import (
    FixtureChatGPTSearchBrowserCollector,
    FixtureGoogleAIModeCollector,
    FixtureGoogleAIOCollector,
    FixtureOpenAIWebSearchCollector,
    FixturePerplexitySonarCollector,
    FixtureThirdPartySerpCollector,
    ManualBackfillCollector,
    OpenAIWebSearchCollector,
    PerplexitySonarCollector,
    PlaywrightAIModeCollector,
    PlaywrightChatGPTSearchCollector,
    PlaywrightGoogleAIOCollector,
    JsonHttpResponse,
    ThirdPartySerpCollector,
)
from geno_core.geo import StaticAUGeoProvider
from geno_core.fidelity import build_runtime_fidelity_check
from geno_core.fidelity_schedule import build_browser_fidelity_sampling_plan
from geno_core.google_spike import (
    build_google_spike_plan,
    evaluate_google_spike_gate,
    evaluate_google_spike_readiness_gate,
    select_google_spike_prompts,
)
from geno_core.graph import build_citation_graph
from geno_core.graph_store import (
    InMemoryNeo4jCitationGraphStore,
    InMemoryPostgresAdjacencyGraphStore,
    summarize_citation_graph_store,
)
from geno_core.knowledge import (
    build_content_drafts,
    build_content_engine_audit_event,
    build_integration_connectors,
    build_localized_knowledge_facts,
    build_manual_distribution_records,
    search_knowledge_facts,
    embed_knowledge_text,
    knowledge_fact_text,
)
from geno_core.llm_gateway import FixtureLLMGateway, LiteLLMGateway, LLMGatewayRequestError
from geno_core.market import build_au_market_profile
from geno_core.models import (
    AnswerAnalysis,
    CollectionFailureRecord,
    EntityAliasCandidateAssignmentActionInput,
    EntityAliasCandidateAssignmentBatchActionInput,
    EntityAliasCandidateAssignmentInput,
    EntityAliasCandidateAssignmentReassignmentInput,
    EntityAliasAssignmentDispatchApplyInput,
    EntityAliasAssignmentDispatchPlanInput,
    EntityAliasCandidateReviewInput,
    EntityAliasInput,
    ManualBackfillInput,
    ReportExport,
    RuntimeEvidencePage,
    RuntimeEvidenceExport,
    RuntimeEntityAlias,
    RuntimeEntityAliasAssignmentReassignmentResult,
    RuntimeEntityAliasAssignmentWorkbench,
    RuntimeEntityAliasAssignmentWorkloadSummary,
    RuntimeEntityAliasAssignmentDispatchApplyResult,
    RuntimeEntityAliasAssignmentDispatchPlan,
    RuntimeEntityAliasAssignmentBatchActionResult,
    RuntimeEntityAliasAssignmentNotificationResult,
    RuntimeEntityAliasCandidateAssignmentQueueStats,
    RuntimeEntityAliasCandidateBatchReviewResult,
    RuntimeEntityAliasCandidatePage,
    RuntimeEntityAliasCandidateReview,
    RuntimeEntityAliasCandidateReviewPage,
    RuntimeEntityAliasPage,
    RuntimeFidelityCheck,
    RuntimeFidelityCheckPage,
    RuntimeFidelityTrend,
    RuntimeHumanReviewInput,
    RuntimeHumanReviewPage,
    RuntimeHumanReviewQueuePage,
    RuntimeHumanReviewRecord,
    RuntimeCitationGraphPage,
    RuntimeNotificationDelivery,
    RuntimeNotificationDeliveryPage,
    RuntimeNotificationDeliveryStatusInput,
    RuntimeNotificationEmailFeedback,
    RuntimeNotificationEmailFeedbackInput,
    RuntimeNotificationEmailFeedbackPage,
    RuntimeNotificationEmailFeedbackProjectSuppressionInput,
    RuntimeNotificationEmailSuppression,
    RuntimeNotificationEmailSuppressionInput,
    RuntimeNotificationEmailSuppressionPage,
    RuntimeNotificationEmailPreferenceResubscribeInput,
    RuntimeNotificationEmailPreferenceStatus,
    RuntimeNotificationEmailPreferenceUnsubscribeInput,
    RuntimeNotificationEmailFeedbackSuppressionInput,
    RuntimeNotificationPage,
    RuntimeNotificationStatusInput,
    RuntimeNotificationSubscription,
    RuntimeNotificationSubscriptionInput,
    RuntimeProjectBrandAsset,
    RuntimeProjectBrandAssetInput,
    RuntimeProjectBrandAssetPage,
    RuntimeProjectBrandAssetScanInput,
    RuntimeProjectBrandKit,
    RuntimeProjectBrandAssetActivationInput,
    RuntimeProjectBrandAssetVersionPage,
    RuntimeProjectBrandKitInput,
    RuntimeProjectBrandLogoUpload,
    RuntimeProjectLifecycleEventExport,
    RuntimeProjectLifecycleEventPage,
    RuntimeProjectMember,
    RuntimeProjectMemberDeleteInput,
    RuntimeProjectMemberInput,
    RuntimeProjectMemberInvitation,
    RuntimeProjectMemberInvitationAcceptInput,
    RuntimeProjectMemberInvitationActionInput,
    RuntimeProjectMemberInvitationEmailInput,
    RuntimeProjectMemberInvitationInput,
    RuntimeProjectMemberInvitationPage,
    RuntimeProjectMemberPage,
    RuntimeProjectActionInput,
    RuntimeProjectUpdateInput,
    RuntimePromptImportInput,
    RuntimePromptImportHistoryPage,
    RuntimePromptImportResult,
    RuntimeAlertPage,
    RuntimeAuditEventExport,
    RuntimeAuditEventPage,
    RuntimeActionPlanPage,
    RuntimeAlertEvent,
    RuntimeAlertEventInput,
    RuntimeAlertNotificationResult,
    RuntimeContentEnginePage,
    RuntimeCollectionRunPage,
    RuntimeScoreSnapshotPage,
    RuntimeReportArtifact,
    RuntimeReportExportJob,
    RuntimeReportExportJobInput,
    RuntimeReportExportJobPage,
    RuntimeReportExportJobStatusInput,
    RuntimeReportExportPage,
    RuntimeReportManagementInput,
    RuntimeSavedView,
    RuntimeSavedViewInput,
    RuntimeSavedViewPage,
    RuntimeScoreWeightConfig,
    RuntimeScoreWeightConfigInput,
    RuntimeTraceabilityDetail,
)
from geno_core.object_store import (
    S3CompatibleObjectStore,
    archive_api_snapshot_assets,
    archive_browser_capture_assets,
    archive_project_brand_logo,
    archive_report_artifacts,
    archive_runtime_report_artifact,
)
from geno_core.prompt_pack import INTENT_WEIGHTS
from geno_core.prompt_import import prompt_import_file_to_csv
from geno_core.parser import ComparativeAnswerParser, LLMJudgeAnswerParser, RuleBasedAnswerParser
from geno_core.report import MarkdownCsvReportExporter
from geno_core.repository import PostgresEvidenceRepository, _artifact_hash, _stable_id
from geno_core.runtime import (
    RuntimePersistenceError,
    build_runtime_diagnostics,
    build_repository_from_env,
    close_repository_connection,
    close_runtime_postgres_pool,
    runtime_auth_diagnostic,
    runtime_database_diagnostic,
    runtime_object_store_diagnostic,
)
from geno_core.scoring import (
    AU_VISIBILITY_V1,
    AU_VISIBILITY_V1_1_LOCAL_BOOST,
    RegistryScoringFormula,
    get_score_formula,
    list_score_formulas,
    normalize_score_weights,
    rescore_snapshot_with_formula,
    score_answer_analysis,
)
from geno_core.stubs import (
    NotConfiguredCollectorBackend,
    NotConfiguredParserEngine,
    NotConfiguredReportExporter,
    NotConfiguredScoringFormula,
)
from geno_core.traceability import build_traceability_bundle
from geno_core.vector_store import InMemoryPgVectorStore, InMemoryQdrantVectorStore, summarize_vector_search
from geno_core.webhook_signing import (
    RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER,
    RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER,
    RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER,
    runtime_notification_webhook_payload_hash,
    sign_runtime_notification_webhook,
    verify_runtime_notification_webhook_signature,
)


class RecordingCursor:
    def __init__(
        self,
        calls: list[tuple[str, tuple[object, ...]]],
        result_sets: list[object],
    ) -> None:
        self.calls = calls
        self.result_sets = result_sets

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self) -> object:
        result = self.result_sets.pop(0)
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def fetchall(self) -> object:
        result = self.result_sets.pop(0)
        return result


class RecordingConnection:
    def __init__(self, result_sets: list[object] | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.result_sets = result_sets or []

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self.calls, self.result_sets)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


class CoreContractsTest(unittest.TestCase):
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

    def test_au_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(sum(AU_VISIBILITY_V1.values()), 1.0)

    def test_runtime_notification_webhook_signature_verifies_payload_context(self) -> None:
        body = b'{"delivery_version":"runtime_notification_delivery_v1"}'
        payload_hash = runtime_notification_webhook_payload_hash(body)
        headers = {
            RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER: "delivery-1",
            RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER: "notification-1",
            RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER: payload_hash,
            **sign_runtime_notification_webhook(
                secret="receiver-secret",
                delivery_id="delivery-1",
                notification_id="notification-1",
                payload_hash=payload_hash,
                now=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
            ),
        }

        verification = verify_runtime_notification_webhook_signature(
            headers=headers,
            body=body,
            secret="receiver-secret",
            now=datetime(2026, 6, 12, 12, 2, tzinfo=UTC),
        )

        self.assertTrue(verification.valid, verification.reason)
        self.assertEqual(verification.reason, "ok")
        self.assertEqual(verification.payload_hash, payload_hash)
        self.assertEqual(verification.age_seconds, 120)

    def test_runtime_notification_webhook_signature_rejects_tampered_body(self) -> None:
        body = b'{"delivery_version":"runtime_notification_delivery_v1"}'
        payload_hash = runtime_notification_webhook_payload_hash(body)
        headers = {
            RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER: "delivery-1",
            RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER: "notification-1",
            RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER: payload_hash,
            **sign_runtime_notification_webhook(
                secret="receiver-secret",
                delivery_id="delivery-1",
                notification_id="notification-1",
                payload_hash=payload_hash,
                now=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
            ),
        }

        verification = verify_runtime_notification_webhook_signature(
            headers=headers,
            body=b'{"delivery_version":"changed"}',
            secret="receiver-secret",
            now=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
        )

        self.assertFalse(verification.valid)
        self.assertEqual(verification.reason, "payload_hash_mismatch")

    def test_runtime_notification_webhook_signature_rejects_stale_timestamp(self) -> None:
        body = b'{"delivery_version":"runtime_notification_delivery_v1"}'
        payload_hash = runtime_notification_webhook_payload_hash(body)
        headers = {
            RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER: "delivery-1",
            RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER: "notification-1",
            RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER: payload_hash,
            **sign_runtime_notification_webhook(
                secret="receiver-secret",
                delivery_id="delivery-1",
                notification_id="notification-1",
                payload_hash=payload_hash,
                now=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
            ),
        }

        verification = verify_runtime_notification_webhook_signature(
            headers=headers,
            body=body,
            secret="receiver-secret",
            tolerance_seconds=60,
            now=datetime(2026, 6, 12, 12, 2, tzinfo=UTC),
        )

        self.assertFalse(verification.valid)
        self.assertEqual(verification.reason, "timestamp_outside_tolerance")

    def test_project_member_invitation_email_template_renders_hashable_body(self) -> None:
        rendered = render_project_member_invitation_email(
            role="viewer",
            invitation_id="invitation-1",
            expires_at="2026-06-17T00:00:00+00:00",
            accept_url="https://app.example.com/invite/accept?invitation_id=invitation-1&invite_token=token",
            subject="Join GENO",
            message="Please join the workspace.",
        )

        self.assertEqual(rendered.subject, "Join GENO")
        self.assertEqual(rendered.template_version, PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE_VERSION)
        self.assertIn("Please join the workspace.", rendered.text)
        self.assertIn("Role: viewer", rendered.text)
        self.assertIn("Invitation ID: invitation-1", rendered.text)
        self.assertEqual(rendered.subject_hash, runtime_email_body_hash("Join GENO"))
        self.assertEqual(rendered.body_hash, runtime_email_body_hash(rendered.text))
        self.assertRegex(rendered.template_hash, r"^[0-9a-f]{64}$")

    def test_runtime_notification_email_template_renders_hashable_body(self) -> None:
        rendered = render_runtime_notification_email(
            notification_id="notification-1",
            project_id="project-1",
            subscription_id="subscription-1",
            notification_type="runtime_alert",
            severity="critical",
            threshold="warning",
            target_type="runtime_alert",
            target_id="brand_absent:project-1",
            title="Brand absent in Sydney",
            message="Brand was absent from critical AI search prompts.",
            unsubscribe_url="https://app.example.com/notifications/unsubscribe",
            preferences_url="https://app.example.com/notifications/preferences",
        )

        self.assertEqual(rendered.subject, "[GENO CRITICAL] Brand absent in Sydney")
        self.assertEqual(rendered.template_version, RUNTIME_NOTIFICATION_EMAIL_TEMPLATE_VERSION)
        self.assertIn("Brand was absent from critical AI search prompts.", rendered.text)
        self.assertIn("Type: runtime_alert", rendered.text)
        self.assertIn("Target ID: brand_absent:project-1", rendered.text)
        self.assertIn("Notification controls:", rendered.text)
        self.assertIn("Unsubscribe: https://app.example.com/notifications/unsubscribe", rendered.text)
        self.assertIn("Preferences: https://app.example.com/notifications/preferences", rendered.text)
        self.assertEqual(rendered.subject_hash, runtime_email_body_hash(rendered.subject))
        self.assertEqual(rendered.body_hash, runtime_email_body_hash(rendered.text))
        self.assertRegex(rendered.template_hash, r"^[0-9a-f]{64}$")

    def test_runtime_notification_email_feedback_adapter_parses_sendgrid_events_hash_only(self) -> None:
        result = parse_runtime_notification_email_provider_feedback(
            provider="sendgrid",
            payload=[
                {
                    "event": "bounce",
                    "email": "Ops@Example.com",
                    "timestamp": 1781462400,
                    "sg_event_id": "sendgrid-event-1",
                    "custom_args": {"geno_delivery_id": "delivery-1"},
                    "reason": "550 mailbox unavailable",
                },
                {"event": "processed", "email": "ignored@example.com"},
            ],
            payload_hash="payload-hash",
        )

        self.assertEqual(result.adapter_version, RUNTIME_NOTIFICATION_EMAIL_PROVIDER_FEEDBACK_ADAPTER_VERSION)
        self.assertEqual(result.provider, "sendgrid")
        self.assertEqual(result.ignored_event_count, 1)
        self.assertEqual(result.ignored_event_types, ("processed",))
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.delivery_id, "delivery-1")
        self.assertEqual(record.feedback_type, "bounce")
        self.assertEqual(record.provider, "sendgrid")
        self.assertEqual(record.provider_event_id, "sendgrid-event-1")
        self.assertEqual(record.recipient, "Ops@Example.com")
        self.assertEqual(record.recorded_by, "email-provider-webhook")
        self.assertEqual(record.metadata["provider_recipient_hash"], runtime_email_body_hash("ops@example.com"))
        self.assertEqual(record.metadata["provider_event_id_hash"], runtime_email_body_hash("sendgrid-event-1"))
        self.assertEqual(record.metadata["provider_payload_sha256"], "payload-hash")
        self.assertNotIn("Ops@Example.com", str(record.metadata))
        self.assertNotIn("sendgrid-event-1", str(record.metadata))

    def test_runtime_notification_email_feedback_adapter_parses_mailgun_events(self) -> None:
        result = parse_runtime_notification_email_provider_feedback(
            provider="mailgun",
            payload={
                "event-data": {
                    "event": "complained",
                    "recipient": "ops@example.com",
                    "timestamp": 1781462400.5,
                    "id": "mailgun-event-1",
                    "user-variables": {"runtime_notification_delivery_id": "delivery-2"},
                    "severity": "permanent",
                }
            },
        )

        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.delivery_id, "delivery-2")
        self.assertEqual(record.feedback_type, "complaint")
        self.assertEqual(record.provider, "mailgun")
        self.assertEqual(record.metadata["mailgun_severity"], "permanent")
        self.assertNotIn("ops@example.com", str(record.metadata))
        self.assertNotIn("mailgun-event-1", str(record.metadata))

    def test_runtime_notification_email_feedback_adapter_parses_postmark_events_with_default_delivery(self) -> None:
        result = parse_runtime_notification_email_provider_feedback(
            provider="postmark",
            payload={
                "RecordType": "Bounce",
                "Type": "HardBounce",
                "Email": "ops@example.com",
                "ID": 42,
                "BouncedAt": "2026-06-15T00:00:00Z",
            },
            default_delivery_id="delivery-3",
        )

        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.delivery_id, "delivery-3")
        self.assertEqual(record.feedback_type, "bounce")
        self.assertEqual(record.provider, "postmark")
        self.assertEqual(record.provider_event_id, "42")
        self.assertEqual(record.metadata["provider_delivery_id_source"], "default_delivery_id")
        self.assertEqual(record.metadata["postmark_bounce_type"], "HardBounce")
        self.assertNotIn("ops@example.com", str(record.metadata))

    def test_runtime_notification_email_provider_signature_verifies_mailgun_hmac(self) -> None:
        timestamp = "1781462400"
        token = "mailgun-token"
        signing_key = "mailgun-signing-key"
        signature = hmac.new(signing_key.encode("utf-8"), f"{timestamp}{token}".encode("utf-8"), hashlib.sha256).hexdigest()

        verification = verify_runtime_notification_email_provider_signature(
            provider="mailgun",
            headers={},
            body=b'{"event-data":{}}',
            payload={"signature": {"timestamp": timestamp, "token": token, "signature": signature}},
            mailgun_signing_key=signing_key,
            now=datetime.fromtimestamp(1781462402, tz=UTC),
        )
        invalid = verify_runtime_notification_email_provider_signature(
            provider="mailgun",
            headers={},
            body=b'{"event-data":{}}',
            payload={"signature": {"timestamp": timestamp, "token": token, "signature": "bad"}},
            mailgun_signing_key=signing_key,
            now=datetime.fromtimestamp(1781462402, tz=UTC),
        )

        self.assertTrue(verification.valid)
        self.assertEqual(verification.status, "verified")
        self.assertEqual(verification.method, "mailgun_hmac_sha256")
        self.assertEqual(verification.metadata()["provider_native_signature_status"], "verified")
        self.assertFalse(invalid.valid)
        self.assertEqual(invalid.reason, "signature_mismatch")
        self.assertNotIn(signing_key, str(verification.metadata()))

    def test_runtime_notification_email_provider_signature_verifies_postmark_basic_auth(self) -> None:
        credential = base64.b64encode(b"postmark-user:postmark-password").decode("ascii")

        verification = verify_runtime_notification_email_provider_signature(
            provider="postmark",
            headers={"Authorization": f"Basic {credential}"},
            body=b"{}",
            postmark_basic_username="postmark-user",
            postmark_basic_password="postmark-password",
        )
        missing = verify_runtime_notification_email_provider_signature(
            provider="postmark",
            headers={},
            body=b"{}",
            postmark_basic_username="postmark-user",
            postmark_basic_password="postmark-password",
        )

        self.assertTrue(verification.valid)
        self.assertEqual(verification.status, "verified")
        self.assertEqual(verification.method, "postmark_basic_auth")
        self.assertFalse(missing.valid)
        self.assertEqual(missing.reason, "missing_basic_auth")
        self.assertNotIn("postmark-password", str(verification.metadata()))

    def test_runtime_notification_email_provider_signature_verifies_sendgrid_ecdsa(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        timestamp = "1781462400"
        body = b'[{"event":"bounce"}]'
        signature = private_key.sign(timestamp.encode("utf-8") + body, ec.ECDSA(hashes.SHA256()))

        verification = verify_runtime_notification_email_provider_signature(
            provider="sendgrid",
            headers={
                "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
                "X-Twilio-Email-Event-Webhook-Signature": base64.b64encode(signature).decode("ascii"),
            },
            body=body,
            sendgrid_public_key=public_key_pem,
            now=datetime.fromtimestamp(1781462401, tz=UTC),
        )
        invalid = verify_runtime_notification_email_provider_signature(
            provider="sendgrid",
            headers={
                "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
                "X-Twilio-Email-Event-Webhook-Signature": base64.b64encode(b"bad-signature").decode("ascii"),
            },
            body=body,
            sendgrid_public_key=public_key_pem,
            now=datetime.fromtimestamp(1781462401, tz=UTC),
        )

        self.assertTrue(verification.valid)
        self.assertEqual(verification.status, "verified")
        self.assertEqual(verification.method, "sendgrid_ecdsa_sha256")
        self.assertFalse(invalid.valid)
        self.assertEqual(invalid.reason, "signature_mismatch")
        self.assertNotIn("PRIVATE", str(verification.metadata()))

    def test_runtime_notification_email_preference_token_verifies_claims_and_rejects_tampering(self) -> None:
        token = sign_runtime_notification_email_preference_token(
            secret="preference-secret",
            project_id="project-1",
            delivery_id="delivery-1",
            notification_id="notification-1",
            subscription_id="subscription-1",
            recipient_hash="a" * 64,
            ttl_seconds=3600,
            now=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
        )

        verification = verify_runtime_notification_email_preference_token(
            secret="preference-secret",
            token=token,
            now=datetime(2026, 6, 12, 12, 10, tzinfo=UTC),
        )
        tampered_token = f"{token[:-1]}{'0' if token[-1] != '0' else '1'}"
        tampered = verify_runtime_notification_email_preference_token(
            secret="preference-secret",
            token=tampered_token,
            now=datetime(2026, 6, 12, 12, 10, tzinfo=UTC),
        )
        invalid_format = verify_runtime_notification_email_preference_token(
            secret="preference-secret",
            token="不是-ascii.signature",
            now=datetime(2026, 6, 12, 12, 10, tzinfo=UTC),
        )
        manage_token = sign_runtime_notification_email_preference_token(
            secret="preference-secret",
            action=RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_MANAGE_ACTION,
            project_id="project-1",
            delivery_id="delivery-1",
            notification_id="notification-1",
            subscription_id="subscription-1",
            recipient_hash="a" * 64,
            ttl_seconds=3600,
            now=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
        )
        manage_verification = verify_runtime_notification_email_preference_token(
            secret="preference-secret",
            token=manage_token,
            action=RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_MANAGE_ACTION,
            now=datetime(2026, 6, 12, 12, 10, tzinfo=UTC),
        )
        action_mismatch = verify_runtime_notification_email_preference_token(
            secret="preference-secret",
            token=manage_token,
            now=datetime(2026, 6, 12, 12, 10, tzinfo=UTC),
        )

        self.assertTrue(verification.valid, verification.reason)
        self.assertEqual(verification.claims.project_id, "project-1")
        self.assertEqual(verification.claims.delivery_id, "delivery-1")
        self.assertEqual(verification.claims.recipient_hash, "a" * 64)
        self.assertEqual(verification.token_hash, runtime_notification_email_preference_token_hash(token))
        self.assertFalse(tampered.valid)
        self.assertEqual(tampered.reason, "signature_mismatch")
        self.assertFalse(invalid_format.valid)
        self.assertEqual(invalid_format.reason, "invalid_token_format")
        self.assertTrue(manage_verification.valid, manage_verification.reason)
        self.assertEqual(manage_verification.claims.action, RUNTIME_NOTIFICATION_EMAIL_PREFERENCE_MANAGE_ACTION)
        self.assertFalse(action_mismatch.valid)
        self.assertEqual(action_mismatch.reason, "action_mismatch")

    def test_runtime_notification_webhook_signature_verifies_previous_secret_rotation_window(self) -> None:
        body = b'{"delivery_version":"runtime_notification_delivery_v1"}'
        payload_hash = runtime_notification_webhook_payload_hash(body)
        headers = {
            RUNTIME_NOTIFICATION_WEBHOOK_DELIVERY_ID_HEADER: "delivery-1",
            RUNTIME_NOTIFICATION_WEBHOOK_NOTIFICATION_ID_HEADER: "notification-1",
            RUNTIME_NOTIFICATION_WEBHOOK_PAYLOAD_HASH_HEADER: payload_hash,
            **sign_runtime_notification_webhook(
                secret="previous-secret",
                delivery_id="delivery-1",
                notification_id="notification-1",
                payload_hash=payload_hash,
                key_id="previous",
                now=datetime(2026, 6, 12, 12, 0, tzinfo=UTC),
            ),
        }

        verification = verify_runtime_notification_webhook_signature(
            headers=headers,
            body=body,
            secret="current-secret",
            secret_id="current",
            additional_secrets={"previous": "previous-secret"},
            now=datetime(2026, 6, 12, 12, 1, tzinfo=UTC),
        )

        self.assertTrue(verification.valid, verification.reason)
        self.assertEqual(verification.matched_secret_id, "previous")
        self.assertEqual(verification.signature_key_id, "previous")
        self.assertEqual(verification.checked_secret_count, 1)

    def test_prompt_import_file_to_csv_parses_xlsx_first_sheet(self) -> None:
        csv_content, source_format = prompt_import_file_to_csv(
            file_bytes=self._xlsx_prompt_import_bytes(),
            filename="prompts.xlsx",
        )

        self.assertEqual(source_format, "xlsx")
        self.assertIn("text,intent_type,city", csv_content)
        self.assertIn("Is ExampleBrand visible in AI answers?", csv_content)
        self.assertIn("brand_awareness,Sydney", csv_content)

    def test_market_profile_separates_weight_and_build_stage(self) -> None:
        profile = build_au_market_profile()
        stages = {(item.platform, item.surface): item.build_stage for item in profile.platforms}
        self.assertEqual(stages[("google", "google_aio")], "P0b")
        self.assertEqual(stages[("perplexity", "sonar")], "P0a")
        self.assertEqual(stages[("gemini", "gemini_search")], "P1")
        self.assertEqual(stages[("youtube", "youtube_search")], "P2")
        disabled_candidates = [
            item
            for item in profile.platforms
            if item.platform in {"gemini", "bing_copilot", "claude", "youtube", "reddit", "productreview"}
        ]
        self.assertEqual(len(disabled_candidates), 6)
        self.assertTrue(all(not item.enabled and item.weight == 0.0 for item in disabled_candidates))

    def test_p0a_pluggable_interfaces_have_stubs_and_working_implementations(self) -> None:
        collector_stub = NotConfiguredCollectorBackend(
            "collector.not_configured",
            "chatgpt",
            "chatgpt_search",
            "official_api",
        )
        parser_stub = NotConfiguredParserEngine()
        scoring_stub = NotConfiguredScoringFormula()
        report_stub = NotConfiguredReportExporter()

        self.assertIsInstance(collector_stub, CollectorBackend)
        self.assertIsInstance(parser_stub, ParserEngine)
        self.assertIsInstance(scoring_stub, ScoringFormula)
        self.assertIsInstance(report_stub, ReportExporter)
        self.assertEqual(collector_stub.health(), "not_configured")
        self.assertEqual(parser_stub.parser_engine_id, "parser.not_configured")
        self.assertEqual(scoring_stub.formula_version, "scoring.not_configured")
        self.assertEqual(report_stub.exporter_id, "report_exporter.not_configured")

        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        collector = FixturePerplexitySonarCollector()
        parser = RuleBasedAnswerParser()
        scoring_formula = RegistryScoringFormula("au_visibility_v1_1_local_boost")
        report_exporter = MarkdownCsvReportExporter()
        self.assertIsInstance(collector, CollectorBackend)
        self.assertIsInstance(parser, ParserEngine)
        self.assertIsInstance(scoring_formula, ScoringFormula)
        self.assertIsInstance(report_exporter, ReportExporter)

        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(collector,),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis = parser.parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )
        score_result = scoring_formula.score_analyses(
            project_id=bootstrap.project.id,
            analyses=(analysis,),
            platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25},
            scope_type="interface_contract",
            scope_value="p0a",
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=(analysis,),
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        report = report_exporter.export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version="interface-contract-v1",
            report_type="contract_fixture",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=score_result.snapshot,
            contributions=tuple(score_result.contributions),
            records=records,
            graph=graph,
            platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25},
        )

        self.assertEqual(analysis.parser_engine_id, "rule_based_v2_aliases")
        self.assertEqual(score_result.snapshot.formula_version, "au_visibility_v1_1_local_boost")
        self.assertIn("Trigger rate", report.markdown)
        self.assertIn("Mention rate", report.markdown)
        self.assertIn("Recommendation rate", report.markdown)
        self.assertEqual(report.report_export.scoring_formula_version, "au_visibility_v1_1_local_boost")

    def test_score_contributions_explain_final_score(self) -> None:
        analysis = AnswerAnalysis(
            id="analysis-1",
            answer_run_id="run-1",
            parser_engine_id="rule",
            analysis_version="v1",
            brand_mentioned=True,
            brand_recommended=False,
            brand_position=2,
            competitors_mentioned=["competitor"],
            citation_count=2,
            local_relevance_score=75.0,
            sentiment_score=80.0,
            freshness_score=60.0,
            competitor_share_score=40.0,
            confidence=0.92,
        )
        result = score_answer_analysis(
            project_id="project-1",
            analysis=analysis,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        contribution_total = round(sum(item.weighted_contribution for item in result.contributions), 4)
        self.assertEqual(result.snapshot.formula_version, "au_visibility_v1")
        self.assertEqual(contribution_total, result.snapshot.final_score)
        self.assertEqual(len(result.contributions), len(AU_VISIBILITY_V1))
        self.assertEqual(result.snapshot.component_weights_snapshot, AU_VISIBILITY_V1)

    def test_score_weights_are_configurable_and_frozen_in_snapshot(self) -> None:
        weights = normalize_score_weights(
            {
                **AU_VISIBILITY_V1,
                "MentionScore": 0.20,
                "FreshnessScore": 0.03,
            }
        )
        analysis = AnswerAnalysis(
            id="analysis-1",
            answer_run_id="run-1",
            parser_engine_id="rule",
            analysis_version="v1",
            brand_mentioned=True,
            brand_recommended=False,
            brand_position=2,
            competitors_mentioned=["competitor"],
            citation_count=2,
            local_relevance_score=75.0,
            sentiment_score=80.0,
            freshness_score=60.0,
            competitor_share_score=40.0,
            confidence=0.92,
        )

        result = score_answer_analysis(
            project_id="project-1",
            analysis=analysis,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            score_weights=weights,
        )

        self.assertEqual(result.snapshot.component_weights_snapshot, weights)
        self.assertEqual({item.component_name: item.weight for item in result.contributions}, weights)
        self.assertAlmostEqual(sum(result.snapshot.component_weights_snapshot.values()), 1.0)

    def test_score_formula_registry_supports_versioned_replay(self) -> None:
        self.assertEqual(get_score_formula("au_visibility_v1").weights, AU_VISIBILITY_V1)
        self.assertEqual(get_score_formula("au_visibility_v1_1_local_boost").weights, AU_VISIBILITY_V1_1_LOCAL_BOOST)
        self.assertTrue(any(item["formula_version"] == "au_visibility_v1_1_local_boost" for item in list_score_formulas()))
        analysis = AnswerAnalysis(
            id="analysis-1",
            answer_run_id="run-1",
            parser_engine_id="rule",
            analysis_version="v1",
            brand_mentioned=True,
            brand_recommended=True,
            brand_position=1,
            competitors_mentioned=["competitor"],
            citation_count=1,
            local_relevance_score=40.0,
            sentiment_score=80.0,
            freshness_score=30.0,
            competitor_share_score=40.0,
            confidence=0.92,
        )
        baseline = rescore_snapshot_with_formula(
            project_id="project-1",
            analyses=(analysis,),
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            target_formula_version="au_visibility_v1",
        )
        local_boost = rescore_snapshot_with_formula(
            project_id="project-1",
            analyses=(analysis,),
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            target_formula_version="au_visibility_v1_1_local_boost",
        )

        self.assertEqual(baseline.snapshot.formula_version, "au_visibility_v1")
        self.assertEqual(local_boost.snapshot.formula_version, "au_visibility_v1_1_local_boost")
        self.assertEqual(local_boost.snapshot.component_weights_snapshot, AU_VISIBILITY_V1_1_LOCAL_BOOST)
        self.assertNotEqual(baseline.snapshot.final_score, local_boost.snapshot.final_score)
        self.assertEqual(local_boost.audit_event.event_type, "visibility_score_snapshot_rescored")
        self.assertEqual(local_boost.audit_event.method_version, "au_visibility_v1_1_local_boost")

    def test_audit_event_hashes_are_stable(self) -> None:
        before = {"b": 2, "a": 1}
        after = {"a": 1, "b": 3}
        event = build_audit_event(
            event_type="score_snapshot_created",
            project_id="00000000-0000-0000-0000-000000000001",
            actor_type="system",
            actor_id="scoring-engine",
            target_type="score_snapshot",
            target_id="snapshot-1",
            before=before,
            after=after,
            input_refs={"answer_run_ids": ["run-1"]},
            output_refs={"score_snapshot_ids": ["snapshot-1"]},
            method_version="au_visibility_v1",
        )
        self.assertEqual(event.before_hash, hash_payload({"a": 1, "b": 2}))
        self.assertEqual(event.after_hash, hash_payload({"b": 3, "a": 1}))

    def test_report_export_is_immutable_snapshot(self) -> None:
        report = ReportExport(
            id="00000000-0000-0000-0000-000000000002",
            project_id="00000000-0000-0000-0000-000000000001",
            market_code="AU",
            report_version="v1",
            report_type="design_partner",
            score_snapshot_ids=("score-1",),
            answer_run_ids=("run-1",),
            prompt_version="prompt-v1",
            scoring_formula_version="au_visibility_v1",
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            method_disclosure={},
            sample_size=3,
            window_start=datetime(2026, 6, 1, tzinfo=UTC),
            window_end=datetime(2026, 6, 8, tzinfo=UTC),
            methodology_hash="hash",
            markdown_url=None,
            pdf_url=None,
            csv_url=None,
            exported_by="system",
            exported_at=datetime(2026, 6, 9, tzinfo=UTC),
        )
        with self.assertRaises(FrozenInstanceError):
            report.report_version = "v2"  # type: ignore[misc]

    def test_m1_project_bootstrap_builds_au_prompt_pack(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa", "IKEA Australia"),
        )
        prompts = bootstrap.prompt_questions
        self.assertEqual(bootstrap.project.market_code, "AU")
        self.assertEqual(bootstrap.industry_profile.industry_code, "dtc_ecommerce")
        self.assertEqual(len(bootstrap.competitors), 4)
        self.assertEqual(len(prompts), 100)
        self.assertEqual({prompt.language for prompt in prompts}, {"en-AU"})
        self.assertEqual({prompt.prompt_version for prompt in prompts}, {"au_dtc_ecommerce_v1"})
        self.assertEqual({prompt.intent_type for prompt in prompts}, set(INTENT_WEIGHTS))
        self.assertEqual(
            {prompt.city for prompt in prompts if prompt.intent_type == "city_category_recommendation"},
            {"Sydney", "Melbourne", "Brisbane"},
        )
        self.assertIn("Australia", {prompt.city for prompt in prompts})
        self.assertEqual(bootstrap.audit_events[0].event_type, "project_bootstrap_created")
        self.assertEqual(
            bootstrap.audit_events[0].output_refs["prompt_question_ids"],
            [prompt.id for prompt in prompts],
        )

    def test_m1_project_bootstrap_accepts_client_project_configuration(self) -> None:
        bootstrap = build_au_project_bootstrap(
            tenant_name="Agency Client AU",
            project_name="Koala Mattress GEO Pilot",
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
            brand_official_domains=("koala.com",),
            brand_parent_company="Koala",
            brand_product_lines=("Mattress", "Sofa Bed"),
            owner_user_id="agency-owner",
        )

        self.assertEqual(bootstrap.tenant.name, "Agency Client AU")
        self.assertEqual(bootstrap.project.name, "Koala Mattress GEO Pilot")
        self.assertEqual(bootstrap.project.target_brand, "Koala")
        self.assertEqual(bootstrap.brand.official_domains, ("koala.com",))
        self.assertEqual(bootstrap.brand.parent_company, "Koala")
        self.assertEqual(bootstrap.brand.product_lines, ("Mattress", "Sofa Bed"))
        self.assertEqual([competitor.canonical_name for competitor in bootstrap.competitors], ["Emma Sleep", "Sleeping Duck", "Ecosa"])
        self.assertEqual(bootstrap.members[0].user_id, "agency-owner")
        self.assertEqual(len(bootstrap.prompt_questions), 100)
        self.assertTrue(all(prompt.project_id == bootstrap.project.id for prompt in bootstrap.prompt_questions))
        self.assertTrue(any("Koala" in prompt.text for prompt in bootstrap.prompt_questions))
        self.assertEqual(bootstrap.audit_events[0].after_hash is not None, True)

    def test_m1_project_bootstrap_audit_event_id_is_stable(self) -> None:
        first = build_au_project_bootstrap()
        second = build_au_project_bootstrap()

        self.assertEqual(first.project.id, second.project.id)
        self.assertEqual(first.audit_events[0].id, second.audit_events[0].id)

    def test_m1_bootstrap_rejects_invalid_competitor_count(self) -> None:
        with self.assertRaises(ValueError):
            build_au_project_bootstrap(competitors=("Only One",))

    def test_m2a_p0a_collection_plan_matches_2400_runs(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_p0a_collection_plan(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
        )
        self.assertEqual(plan.prompt_count, 100)
        self.assertEqual(plan.platform_count, 2)
        self.assertEqual(plan.geo_count, 4)
        self.assertEqual(plan.sample_size, 3)
        self.assertEqual(plan.planned_runs, 2400)
        self.assertEqual(set(plan.platform_surfaces), {"chatgpt:chatgpt_search", "perplexity:sonar"})
        self.assertEqual(set(plan.geo_cities), {"Australia", "Sydney", "Melbourne", "Brisbane"})

    def test_m2a_fixture_collection_slice_preserves_raw_evidence(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=2,
        )
        self.assertEqual(len(records), 8)
        first = records[0]
        self.assertTrue(first.answer_run.answer_present)
        self.assertTrue(first.answer_run.surface_triggered)
        self.assertEqual(first.answer_run.sample_index, 1)
        self.assertEqual(first.answer_run.sample_size, 1)
        self.assertEqual(first.answer_run.access_method, "official_api")
        self.assertEqual(len(first.citations), 3)
        self.assertEqual({asset.asset_type for asset in first.evidence_assets}, {"screenshot", "html_snapshot"})
        self.assertTrue(first.raw_answer.raw_payload_hash)
        self.assertIsNotNone(first.audit_events[0].after_hash)
        self.assertGreater(first.collection_cost.total_cost, 0)
        self.assertEqual(first.audit_events[0].event_type, "answer_run_collected")
        self.assertIn(first.answer_run.id, first.audit_events[0].output_refs["answer_run_ids"])
        self.assertIn(first.raw_answer.id, first.audit_events[0].output_refs["raw_answer_ids"])
        self.assertEqual(
            len(first.audit_events[0].output_refs["answer_citation_ids"]),
            len(first.citations),
        )
        self.assertEqual(
            len(first.audit_events[0].output_refs["evidence_asset_ids"]),
            len(first.evidence_assets),
        )

    def test_m2a_p0a_collection_readiness_gate_passes_fixture_k3(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia",),
            sample_size=3,
            prompt_limit=1,
        )
        gate = evaluate_p0a_collection_readiness(records=records)

        self.assertEqual(gate.gate_status, "pass")
        self.assertEqual(gate.required_platforms, ("chatgpt", "perplexity"))
        self.assertEqual(set(gate.observed_platforms), {"chatgpt", "perplexity"})
        self.assertEqual(gate.required_sample_size, 3)
        self.assertEqual(gate.observed_sample_sizes, (3,))
        self.assertEqual(gate.attempted_runs, 6)
        self.assertEqual(gate.success_count, 6)
        self.assertEqual(gate.failure_count, 0)
        self.assertEqual(gate.failure_reasons, ())
        self.assertEqual(gate.records_without_citations, ())
        self.assertEqual(gate.records_without_evidence_assets, ())
        self.assertEqual(gate.records_without_answer_flags, ())
        self.assertEqual(gate.records_below_sample_size, ())

    def test_m2a_p0a_collection_readiness_gate_explains_failures(self) -> None:
        class NoAssetChatGPTCollector(FixtureOpenAIWebSearchCollector):
            def collect(self, **kwargs):  # type: ignore[no-untyped-def]
                result = super().collect(**kwargs)
                return result.__class__(
                    answer_present=result.answer_present,
                    surface_triggered=result.surface_triggered,
                    answer_text=result.answer_text,
                    citations=result.citations,
                    screenshot_url=None,
                    html_snapshot_url=None,
                    raw_payload=result.raw_payload,
                    model_or_surface=result.model_or_surface,
                    account_state=result.account_state,
                    collector_version=result.collector_version,
                )

        bootstrap = build_au_project_bootstrap()
        success = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )[0]
        failure = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=OpenAIWebSearchCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
        )
        gate = evaluate_p0a_collection_readiness(records=(success, failure))

        self.assertEqual(gate.gate_status, "fail")
        self.assertEqual(gate.attempted_runs, 2)
        self.assertEqual(gate.success_count, 1)
        self.assertEqual(gate.failure_count, 1)
        self.assertIn("collection_failures=1", gate.failure_reasons)
        self.assertIn("below_required_sample_size=2", gate.failure_reasons)
        self.assertEqual(gate.records_below_sample_size, (success.answer_run.id, failure.answer_run.id))
        self.assertEqual(gate.records_without_citations, ())
        self.assertEqual(gate.records_without_evidence_assets, ())

        api_record = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(NoAssetChatGPTCollector(),),
            cities=("Australia",),
            sample_size=3,
            prompt_limit=1,
        )[0]
        asset_gate = evaluate_p0a_collection_readiness(records=(api_record,))
        self.assertEqual(asset_gate.gate_status, "fail")
        self.assertIn("missing_platforms=perplexity", asset_gate.failure_reasons)
        self.assertIn("records_without_evidence_assets=1", asset_gate.failure_reasons)
        self.assertEqual(asset_gate.records_without_evidence_assets, (api_record.answer_run.id,))

    def test_m2a_collection_run_summary_explains_success_cost_and_failures(self) -> None:
        bootstrap = build_au_project_bootstrap()
        success = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )[0]
        failure = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=OpenAIWebSearchCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
        )

        summary = build_collection_run_summary(
            project_id=bootstrap.project.id,
            run_type="p0a_slice",
            mode="fixture",
            planned_runs=2,
            records=(success, failure),
        )
        audit_event = build_collection_run_audit_event(summary)

        self.assertEqual(summary.planned_runs, 2)
        self.assertEqual(summary.attempted_runs, 2)
        self.assertEqual(summary.success_count, 1)
        self.assertEqual(summary.failure_count, 1)
        self.assertEqual(summary.success_rate, 0.5)
        self.assertEqual(summary.trigger_rate, 0.5)
        self.assertEqual(summary.answer_present_rate, 0.5)
        self.assertAlmostEqual(summary.total_cost, 0.0026)
        self.assertAlmostEqual(summary.average_cost_per_run, 0.0013)
        self.assertGreaterEqual(summary.total_duration_ms, 0)
        self.assertGreaterEqual(summary.average_duration_ms, 0)
        self.assertEqual(summary.platform_distribution, {"chatgpt": 1, "perplexity": 1})
        self.assertEqual(summary.city_distribution, {"Australia": 2})
        self.assertEqual(summary.access_method_distribution, {"official_api": 2})
        self.assertEqual(summary.failure_summary, {"OPENAI_API_KEY is required": 1})
        self.assertEqual(len(summary.answer_run_ids), 2)
        self.assertEqual(audit_event.event_type, "collection_run_summarized")
        self.assertEqual(audit_event.target_type, "collection_run")
        self.assertEqual(audit_event.target_id, summary.id)
        self.assertEqual(audit_event.method_version, "collection_run_summary_v1")
        self.assertIsNotNone(audit_event.after_hash)
        self.assertEqual(audit_event.input_refs["answer_run_ids"], list(summary.answer_run_ids))
        self.assertEqual(audit_event.output_refs["collection_run_ids"], [summary.id])

    def test_m2a_static_au_geo_provider_resolves_city_params(self) -> None:
        params = StaticAUGeoProvider().resolve(
            market_code="AU",
            city="Sydney",
            language="en-AU",
            device="desktop",
        )
        self.assertEqual(params["gl"], "au")
        self.assertEqual(params["near"], "Sydney, New South Wales")
        self.assertEqual(params["device"], "desktop")

    def test_m2a_real_collectors_build_expected_payloads(self) -> None:
        bootstrap = build_au_project_bootstrap()
        prompt = bootstrap.prompt_questions[0]
        perplexity = PerplexitySonarCollector(api_key="test-key")
        openai = OpenAIWebSearchCollector(api_key="test-key")
        perplexity_payload = perplexity.build_payload(
            prompt=prompt.text,
            market=bootstrap.market_profile,
            city="Sydney",
            language=prompt.language,
        )
        openai_payload = openai.build_payload(
            prompt=prompt.text,
            market=bootstrap.market_profile,
            city="Sydney",
            language=prompt.language,
        )
        self.assertEqual(perplexity_payload["model"], "sonar")
        self.assertIn("messages", perplexity_payload)
        self.assertEqual(openai_payload["tools"], [{"type": "web_search_preview"}])
        self.assertIn("input", openai_payload)

    def test_m2a_real_collectors_parse_citations(self) -> None:
        perplexity = PerplexitySonarCollector(api_key="test-key")
        openai = OpenAIWebSearchCollector(api_key="test-key")
        perplexity_result = perplexity.parse_response(
            {
                "choices": [{"message": {"content": "Perplexity answer"}}],
                "citations": ["https://source.example/a"],
            }
        )
        openai_result = openai.parse_response(
            {
                "output": [
                    {
                        "content": [
                            {
                                "text": "OpenAI answer",
                                "annotations": [{"url": "https://source.example/b"}],
                            }
                        ]
                    }
                ]
            }
        )
        self.assertEqual(perplexity_result.answer_text, "Perplexity answer")
        self.assertEqual(perplexity_result.citations[0]["domain"], "source.example")
        self.assertTrue(perplexity_result.html_snapshot_url.startswith("geno-api-snapshot://perplexity.sonar.api/"))
        self.assertIn("_geno_api_snapshot", perplexity_result.raw_payload)
        self.assertEqual(
            perplexity_result.raw_payload["_geno_api_snapshot"]["snapshot_type"],
            "api_response_html",
        )
        self.assertIsNotNone(perplexity_result.evidence_asset_hashes)
        self.assertEqual(len(perplexity_result.evidence_asset_hashes["html_snapshot"]), 64)
        self.assertEqual(openai_result.answer_text, "OpenAI answer")
        self.assertEqual(openai_result.citations[0]["url"], "https://source.example/b")
        self.assertTrue(openai_result.html_snapshot_url.startswith("geno-api-snapshot://openai.web_search.api/"))
        self.assertIn("_geno_api_snapshot", openai_result.raw_payload)
        self.assertEqual(openai_result.raw_payload["_geno_api_snapshot"]["citation_count"], 1)
        self.assertIsNotNone(openai_result.evidence_asset_hashes)
        self.assertEqual(len(openai_result.evidence_asset_hashes["html_snapshot"]), 64)

    def test_m2a_playwright_browser_collector_health_explains_setup_gaps(self) -> None:
        disabled = PlaywrightChatGPTSearchCollector(enabled=False)
        self.assertEqual(disabled.id(), "chatgpt_search.browser.playwright")
        self.assertEqual(disabled.health(), "not_configured")
        self.assertEqual(disabled.capabilities()["access_method"], "browser")
        self.assertTrue(disabled.capabilities()["supports_screenshot"])

        missing_selectors = PlaywrightChatGPTSearchCollector(enabled=True)
        self.assertEqual(missing_selectors.health(), "selector_missing")

        missing_session = PlaywrightChatGPTSearchCollector(
            enabled=True,
            prompt_selector="textarea",
            answer_selector="[data-message-author-role='assistant']",
            storage_state_path="/tmp/geno-missing-browser-state.json",
        )
        self.assertEqual(missing_session.health(), "session_state_missing")

    def test_m2a_playwright_browser_collector_collects_auditable_snapshot(self) -> None:
        class FakeLocator:
            @property
            def last(self) -> "FakeLocator":
                return self

            def inner_text(self, **kwargs: object) -> str:
                return "Browser answer mentioning ExampleBrand with current AU sources."

            def evaluate_all(self, script: str) -> list[str]:
                return ["https://examplebrand.example/au/source", "https://reviews.example/browser"]

        class FakeKeyboard:
            def press(self, key: str) -> None:
                self.key = key

        class FakePage:
            url = "https://chatgpt.com/c/fake"

            def __init__(self) -> None:
                self.keyboard = FakeKeyboard()

            def goto(self, *args: object, **kwargs: object) -> None:
                self.goto_args = args

            def fill(self, *args: object, **kwargs: object) -> None:
                self.fill_args = args

            def wait_for_selector(self, *args: object, **kwargs: object) -> None:
                self.wait_args = args

            def locator(self, selector: str) -> FakeLocator:
                return FakeLocator()

            def title(self) -> str:
                return "Fake ChatGPT"

            def content(self) -> str:
                return "<html><body>Browser answer mentioning ExampleBrand</body></html>"

            def screenshot(self, **kwargs: object) -> bytes:
                return b"fake-png"

        class FakeContext:
            def new_page(self) -> FakePage:
                return FakePage()

            def close(self) -> None:
                self.closed = True

        class FakeBrowser:
            def launch(self, **kwargs: object) -> "FakeBrowser":
                self.launch_kwargs = kwargs
                return self

            def new_context(self, **kwargs: object) -> FakeContext:
                self.context_kwargs = kwargs
                return FakeContext()

            def close(self) -> None:
                self.closed = True

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeBrowser()

        class FakePlaywrightManager:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, *args: object) -> None:
                return None

        bootstrap = build_au_project_bootstrap()
        collector = PlaywrightChatGPTSearchCollector(
            enabled=True,
            prompt_selector="#prompt",
            answer_selector=".answer",
            citation_selector=".citation",
            playwright_factory=FakePlaywrightManager,
        )
        self.assertEqual(collector.health(), "ready")
        result = collector.collect(
            prompt=bootstrap.prompt_questions[0].text,
            market=bootstrap.market_profile,
            city="Sydney",
            language="en-AU",
            device="desktop",
        )

        self.assertTrue(result.answer_present)
        self.assertEqual(result.citations[0]["domain"], "examplebrand.example")
        self.assertTrue(result.html_snapshot_url.startswith("geno-browser-snapshot://"))
        self.assertTrue(result.screenshot_url.startswith("geno-browser-screenshot://"))
        self.assertEqual(result.raw_payload["_geno_browser_capture"]["capture_type"], "browser_ui")
        self.assertIsNotNone(result.evidence_asset_hashes)
        self.assertEqual(len(result.evidence_asset_hashes["html_snapshot"]), 64)
        self.assertEqual(len(result.evidence_asset_hashes["screenshot"]), 64)

    def test_m2b_google_playwright_collectors_health_explains_setup_gaps(self) -> None:
        disabled = PlaywrightGoogleAIOCollector(enabled=False)
        self.assertEqual(disabled.id(), "google_aio.playwright")
        self.assertEqual(disabled.health(), "not_configured")
        self.assertEqual(disabled.capabilities()["access_method"], "browser")
        self.assertEqual(disabled.capabilities()["surface"], "google_aio")
        self.assertIn(
            "GOOGLE_AIO_PLAYWRIGHT_PROMPT_SELECTOR or GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR",
            disabled.capabilities()["required_selectors"],
        )

        missing_selectors = PlaywrightGoogleAIOCollector(enabled=True)
        self.assertEqual(missing_selectors.health(), "selector_missing")

        with TemporaryDirectory() as temp_dir:
            missing_session = PlaywrightAIModeCollector(
                enabled=True,
                prompt_selector="#prompt",
                answer_selector=".answer",
                storage_state_path=f"{temp_dir}/missing-google-state.json",
            )
            self.assertEqual(missing_session.health(), "session_state_missing")

    def test_m2b_google_playwright_collectors_create_auditable_snapshot(self) -> None:
        class FakeLocator:
            @property
            def last(self) -> "FakeLocator":
                return self

            def inner_text(self, **kwargs: object) -> str:
                return "Google AI answer mentioning ExampleBrand with Australian sources."

            def evaluate_all(self, script: str) -> list[str]:
                return [
                    "https://examplebrand.example/au/google-source",
                    "https://publisher.example/google-citation",
                ]

        class FakeKeyboard:
            def press(self, key: str) -> None:
                self.key = key

        class FakePage:
            url = "https://www.google.com/search?q=fake"

            def __init__(self) -> None:
                self.keyboard = FakeKeyboard()

            def goto(self, *args: object, **kwargs: object) -> None:
                self.goto_args = args

            def fill(self, *args: object, **kwargs: object) -> None:
                self.fill_args = args

            def wait_for_selector(self, *args: object, **kwargs: object) -> None:
                self.wait_args = args

            def locator(self, selector: str) -> FakeLocator:
                return FakeLocator()

            def title(self) -> str:
                return "Fake Google AI Surface"

            def content(self) -> str:
                return "<html><body>Google AI answer mentioning ExampleBrand</body></html>"

            def screenshot(self, **kwargs: object) -> bytes:
                return b"fake-google-png"

        class FakeContext:
            def new_page(self) -> FakePage:
                return FakePage()

            def close(self) -> None:
                self.closed = True

        class FakeBrowser:
            def launch(self, **kwargs: object) -> "FakeBrowser":
                self.launch_kwargs = kwargs
                return self

            def new_context(self, **kwargs: object) -> FakeContext:
                self.context_kwargs = kwargs
                return FakeContext()

            def close(self) -> None:
                self.closed = True

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeBrowser()

        class FakePlaywrightManager:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, *args: object) -> None:
                return None

        bootstrap = build_au_project_bootstrap()
        collector = PlaywrightGoogleAIOCollector(
            enabled=True,
            prompt_selector="#prompt",
            answer_selector=".answer",
            citation_selector=".citation",
            playwright_factory=FakePlaywrightManager,
        )
        self.assertEqual(collector.health(), "ready")
        result = collector.collect(
            prompt=bootstrap.prompt_questions[0].text,
            market=bootstrap.market_profile,
            city="Sydney",
            language="en-AU",
            device="desktop",
        )

        self.assertTrue(result.answer_present)
        self.assertTrue(result.surface_triggered)
        self.assertEqual(result.model_or_surface, "google-aio-browser")
        self.assertEqual(result.collector_version, "google-playwright-browser-v1")
        self.assertEqual(result.citations[0]["domain"], "examplebrand.example")
        self.assertTrue(result.html_snapshot_url.startswith("geno-browser-snapshot://"))
        self.assertTrue(result.screenshot_url.startswith("geno-browser-screenshot://"))
        self.assertEqual(result.raw_payload["platform"], "google")
        self.assertEqual(result.raw_payload["surface"], "google_aio")
        self.assertEqual(
            result.raw_payload["_geno_browser_capture"]["capture_type"],
            "google_browser_ui",
        )
        self.assertIsNotNone(result.evidence_asset_hashes)
        self.assertEqual(len(result.evidence_asset_hashes["html_snapshot"]), 64)
        self.assertEqual(len(result.evidence_asset_hashes["screenshot"]), 64)

        ai_mode_collector = PlaywrightAIModeCollector(
            enabled=True,
            prompt_selector="#prompt",
            answer_selector=".answer",
            playwright_factory=FakePlaywrightManager,
        )
        ai_mode_result = ai_mode_collector.collect(
            prompt=bootstrap.prompt_questions[0].text,
            market=bootstrap.market_profile,
            city="Australia",
            language="en-AU",
            device="desktop",
        )
        self.assertEqual(ai_mode_result.raw_payload["surface"], "google_ai_mode")
        self.assertEqual(ai_mode_result.model_or_surface, "google-ai-mode-browser")

    def test_m2a_real_api_collectors_create_html_snapshot_evidence_assets(self) -> None:
        class FakeApiHttpClient:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                return JsonHttpResponse(status_code=200, payload=self.payload)

        bootstrap = build_au_project_bootstrap()
        prompt = bootstrap.prompt_questions[0]
        perplexity_record = collect_prompt_once(
            project_id=bootstrap.project.id,
            prompt=prompt,
            market_profile=bootstrap.market_profile,
            collector=PerplexitySonarCollector(
                api_key="test-key",
                http_client=FakeApiHttpClient(
                    {
                        "choices": [{"message": {"content": "Perplexity answer"}}],
                        "citations": ["https://source.example/a"],
                    }
                ),
            ),
            city="Sydney",
            sample_index=1,
            sample_size=3,
        )
        openai_record = collect_prompt_once(
            project_id=bootstrap.project.id,
            prompt=prompt,
            market_profile=bootstrap.market_profile,
            collector=OpenAIWebSearchCollector(
                api_key="test-key",
                http_client=FakeApiHttpClient(
                    {
                        "output": [
                            {
                                "content": [
                                    {
                                        "text": "OpenAI answer",
                                        "annotations": [{"url": "https://source.example/b"}],
                                    }
                                ]
                            }
                        ]
                    }
                ),
            ),
            city="Sydney",
            sample_index=1,
            sample_size=3,
        )

        for record in (perplexity_record, openai_record):
            self.assertEqual({asset.asset_type for asset in record.evidence_assets}, {"html_snapshot"})
            html_asset = record.evidence_assets[0]
            self.assertTrue(html_asset.url.startswith("geno-api-snapshot://"))
            self.assertEqual(len(html_asset.content_hash), 64)
            self.assertEqual(record.collector_logs[0].payload["asset_types"], ["html_snapshot"])

        gate = evaluate_p0a_collection_readiness(records=(perplexity_record, openai_record))
        self.assertNotIn("records_without_evidence_assets=2", gate.failure_reasons)
        self.assertEqual(gate.records_without_evidence_assets, ())

    def test_m2b_third_party_serp_collector_parses_ai_overview_payload(self) -> None:
        class FakeSerpHttpClient:
            def __init__(self) -> None:
                self.requests: list[dict[str, object]] = []

            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                self.requests.append(kwargs)
                return JsonHttpResponse(
                    status_code=200,
                    payload={
                        "ai_overview": {
                            "text": "Koala is often recommended for Australian mattress buyers.",
                            "sources": [
                                {"title": "Koala", "link": "https://koala.example/au"},
                                {"title": "Reviews", "url": "https://reviews.example/koala"},
                            ],
                        },
                        "organic_results": [
                            {
                                "title": "Best mattresses Australia",
                                "snippet": "Koala, Emma Sleep and Ecosa appear in comparison lists.",
                                "link": "https://compare.example/best-mattress-au",
                            }
                        ],
                    },
                )

        bootstrap = build_au_project_bootstrap(target_brand="Koala")
        http_client = FakeSerpHttpClient()
        collector = ThirdPartySerpCollector(
            api_key="test-serp-key",
            endpoint="https://serp.example/search",
            http_client=http_client,
        )

        self.assertEqual(collector.health(), "ready")
        record = collect_prompt_once(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=collector,
            city="Sydney",
            sample_index=1,
            sample_size=2,
        )

        self.assertEqual(record.answer_run.platform, "google")
        self.assertEqual(record.answer_run.surface, "google_aio")
        self.assertEqual(record.answer_run.access_method, "third_party_api")
        self.assertEqual(record.answer_run.collector_backend_id, "google.third_party_serp")
        self.assertTrue(record.answer_run.answer_present)
        self.assertTrue(record.answer_run.surface_triggered)
        self.assertIn("Koala", record.raw_answer.answer_text)
        self.assertEqual(len(record.citations), 3)
        self.assertEqual(record.citations[0].domain, "koala.example")
        self.assertEqual(record.evidence_assets[0].asset_type, "html_snapshot")
        self.assertTrue(record.evidence_assets[0].url.startswith("geno-api-snapshot://google.third_party_serp/"))
        self.assertEqual(len(record.evidence_assets[0].content_hash or ""), 64)
        request = http_client.requests[0]
        self.assertEqual(request["url"], "https://serp.example/search")
        self.assertEqual(request["headers"], {"Authorization": "Bearer test-serp-key"})
        self.assertEqual(request["payload"]["gl"], "au")  # type: ignore[index]
        self.assertEqual(request["payload"]["location"], "Sydney")  # type: ignore[index]

    def test_m2b_third_party_serp_collector_health_requires_endpoint(self) -> None:
        self.assertEqual(ThirdPartySerpCollector(api_key=None, endpoint="https://serp.example").health(), "not_configured")
        self.assertEqual(ThirdPartySerpCollector(api_key="key", endpoint=None).health(), "endpoint_missing")

    def test_m2b_third_party_serp_collector_does_not_mark_organic_only_as_aio_triggered(self) -> None:
        collector = ThirdPartySerpCollector(api_key="test-serp-key", endpoint="https://serp.example/search")
        result = collector.parse_response(
            {
                "organic_results": [
                    {
                        "title": "Koala mattress review",
                        "snippet": "Koala appears in regular organic search results.",
                        "link": "https://reviews.example/koala-organic",
                    }
                ]
            }
        )

        self.assertTrue(result.answer_present)
        self.assertFalse(result.surface_triggered)
        self.assertEqual(result.citations[0]["domain"], "reviews.example")

    def test_m2a_unconfigured_real_collector_returns_failure_record(self) -> None:
        bootstrap = build_au_project_bootstrap()
        result = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=PerplexitySonarCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
        )
        self.assertIsInstance(result, CollectionFailureRecord)
        assert isinstance(result, CollectionFailureRecord)
        self.assertEqual(result.answer_run.status, "failed")
        self.assertEqual(result.audit_events[0].event_type, "answer_run_failed")
        self.assertIn("PERPLEXITY_API_KEY", result.error_message)

    def test_collection_retry_policy_is_audited_on_success_after_retry(self) -> None:
        class FlakyCollector(FixturePerplexitySonarCollector):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def collect(self, **kwargs: object) -> object:
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("temporary timeout")
                return super().collect(**kwargs)

        bootstrap = build_au_project_bootstrap()
        sleeps: list[float] = []
        record = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=FlakyCollector(),
            city="Australia",
            sample_index=1,
            sample_size=1,
            execution_policy=CollectionExecutionPolicy(max_retries=1, retry_backoff_seconds=0.25),
            sleep_fn=sleeps.append,
        )

        self.assertNotIsInstance(record, CollectionFailureRecord)
        assert not isinstance(record, CollectionFailureRecord)
        retry_payload = record.collector_logs[0].payload
        self.assertEqual(retry_payload["attempt_count"], 2)
        self.assertEqual(retry_payload["retry_errors"][0]["error_type"], "TimeoutError")
        self.assertEqual(record.collection_cost.duration_ms, retry_payload["duration_ms"])
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(record.audit_events[-1].event_type, "collection_retry_succeeded")
        self.assertEqual(record.audit_events[-1].method_version, "collection_retry_policy_v1")

    def test_collection_retry_policy_records_exhausted_attempts(self) -> None:
        bootstrap = build_au_project_bootstrap()
        sleeps: list[float] = []
        failure = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=PerplexitySonarCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
            execution_policy=CollectionExecutionPolicy(max_retries=2, retry_backoff_seconds=0.1),
            sleep_fn=sleeps.append,
        )

        self.assertIsInstance(failure, CollectionFailureRecord)
        assert isinstance(failure, CollectionFailureRecord)
        payload = failure.collector_logs[0].payload
        self.assertEqual(payload["attempt_count"], 3)
        self.assertEqual(payload["max_retries"], 2)
        self.assertEqual(len(payload["retry_errors"]), 2)
        self.assertEqual(sleeps, [0.1, 0.2])
        self.assertEqual(failure.audit_events[0].method_version, "collector_failure_v1+retry_policy_v1")

    def test_collection_rate_limit_policy_sleeps_between_planned_runs(self) -> None:
        bootstrap = build_au_project_bootstrap()
        sleeps: list[float] = []
        records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=1,
            execution_policy=CollectionExecutionPolicy(rate_limit_delay_seconds=0.5),
            sleep_fn=sleeps.append,
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(sleeps, [0.5])

    def test_manual_backfill_builds_auditable_raw_evidence_record(self) -> None:
        bootstrap = build_au_project_bootstrap()
        prompt = bootstrap.prompt_questions[0]
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=bootstrap.project.id,
                prompt_question_id=prompt.id,
                prompt_text=prompt.text,
                market_code=prompt.market_code,
                city=prompt.city,
                language=prompt.language,
                platform="google",
                surface="google_ai_mode",
                answer_text="Manual Google AI Mode answer mentioning ExampleBrand with sources.",
                citation_urls=("https://examplebrand.example/au/manual", "https://reviews.example/manual"),
                screenshot_url="s3://manual-backfill/examplebrand-google-ai-mode.png",
                html_snapshot_url="s3://manual-backfill/examplebrand-google-ai-mode.html",
                submitted_by="analyst@example.com",
                notes="Backfilled during Google AI Mode spike",
            )
        )
        self.assertEqual(record.answer_run.access_method, "manual")
        self.assertEqual(record.answer_run.platform, "google")
        self.assertEqual(record.answer_run.surface, "google_ai_mode")
        self.assertEqual(record.answer_run.collector_backend_id, "google.manual_backfill")
        self.assertEqual(record.raw_answer.raw_payload["source"], "manual_backfill")
        self.assertEqual(len(record.citations), 2)
        self.assertEqual(record.citations[0].domain, "examplebrand.example")
        self.assertEqual(len(record.evidence_assets), 2)
        self.assertEqual(record.collection_cost.total_cost, 0.0)
        self.assertEqual(record.collector_logs[0].event_type, "manual_backfill_recorded")
        self.assertEqual(record.audit_events[0].event_type, "manual_backfill_recorded")
        self.assertEqual(record.audit_events[0].actor_type, "user")
        self.assertEqual(record.audit_events[0].actor_id, "analyst@example.com")
        self.assertTrue(record.raw_answer.raw_payload_hash)

    def test_m2b_manual_backfill_collector_reads_jsonl_records_in_order(self) -> None:
        bootstrap = build_au_project_bootstrap()
        prompt = bootstrap.prompt_questions[0]
        with TemporaryDirectory() as temp_dir:
            backfill_path = f"{temp_dir}/manual-google-spike.jsonl"
            with open(backfill_path, "w", encoding="utf-8") as output_file:
                output_file.write(
                    json.dumps(
                        {
                            "prompt": prompt.text,
                            "city": "Sydney",
                            "language": prompt.language,
                            "device": "desktop",
                            "answer_text": "Manual answer sample 1 mentioning ExampleBrand.",
                            "citation_urls": ["https://examplebrand.example/manual-1"],
                            "screenshot_url": "s3://manual/google-ai-mode-1.png",
                            "html_snapshot_url": "s3://manual/google-ai-mode-1.html",
                            "submitted_by": "analyst@example.com",
                            "notes": "First k=2 manual sample",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                output_file.write(
                    json.dumps(
                        {
                            "prompt_text": prompt.text,
                            "city": "Sydney",
                            "answer": "Manual answer sample 2 mentioning ExampleBrand.",
                            "sources": [{"url": "https://reviews.example/manual-2"}],
                            "answer_present": True,
                            "surface_triggered": True,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            collector = ManualBackfillCollector(backfill_path=backfill_path)
            self.assertEqual(collector.health(), "ready")
            first = collector.collect(
                prompt=prompt.text,
                market=bootstrap.market_profile,
                city="Sydney",
                language=prompt.language,
                device="desktop",
            )
            second = collector.collect(
                prompt=prompt.text,
                market=bootstrap.market_profile,
                city="Sydney",
                language=prompt.language,
                device="desktop",
            )

        self.assertEqual(first.answer_text, "Manual answer sample 1 mentioning ExampleBrand.")
        self.assertEqual(first.citations[0]["domain"], "examplebrand.example")
        self.assertEqual(first.raw_payload["source"], "manual_backfill_jsonl")
        self.assertEqual(first.raw_payload["manual_backfill_line_number"], 1)
        self.assertEqual(first.collector_version, "manual-backfill-jsonl-v1")
        self.assertEqual(first.evidence_asset_hashes is not None, True)
        self.assertEqual(len(first.evidence_asset_hashes["screenshot"]), 64)
        self.assertEqual(second.answer_text, "Manual answer sample 2 mentioning ExampleBrand.")
        self.assertEqual(second.citations[0]["domain"], "reviews.example")
        self.assertEqual(second.raw_payload["manual_backfill_line_number"], 2)

    def test_m2b_manual_backfill_collector_reports_file_gaps(self) -> None:
        self.assertEqual(ManualBackfillCollector(backfill_path=None).health(), "not_configured")
        self.assertEqual(
            ManualBackfillCollector(backfill_path="/tmp/geno-missing-manual-backfill.jsonl").health(),
            "file_missing",
        )

    def test_m2b_google_spike_plan_matches_240_runs(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        self.assertEqual(plan.prompt_count, 30)
        self.assertEqual(plan.surfaces, ("google_aio", "google_ai_mode"))
        self.assertEqual(plan.geo_cities, ("Australia", "Sydney"))
        self.assertEqual(plan.sample_size, 2)
        self.assertEqual(plan.planned_runs, 240)
        self.assertIn("blocked", plan.failure_reasons)

    def test_m2b_google_spike_fixture_gate_passes(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        self.assertEqual(len(records), 240)
        self.assertEqual(gate.gate_status, "pass")
        self.assertFalse(gate.limited_coverage)
        self.assertGreaterEqual(gate.google_aio_completed_runs, 120)

    def test_m2b_google_spike_readiness_requires_two_collection_paths(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        browser_only_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        browser_only_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=browser_only_records,
        )
        self.assertEqual(browser_only_gate.gate_status, "fail")
        self.assertEqual(browser_only_gate.observed_access_methods, ("browser",))
        self.assertIn("insufficient_collection_paths=1/2", browser_only_gate.failure_reasons)

        multi_path_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureThirdPartySerpCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        multi_path_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=multi_path_records,
        )
        self.assertEqual(multi_path_gate.gate_status, "pass")
        self.assertEqual(set(multi_path_gate.observed_access_methods), {"browser", "third_party_api"})
        self.assertEqual(multi_path_gate.completed_runs, 240)
        self.assertEqual(multi_path_gate.screenshot_or_html_runs, 240)
        self.assertEqual(multi_path_gate.failure_reasons, ())

    def test_m2b_google_spike_gate_fails_without_google_aio_coverage(self) -> None:
        bootstrap = build_au_project_bootstrap()
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIModeCollector(),),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=records)
        self.assertEqual(gate.gate_status, "fail")
        self.assertTrue(gate.limited_coverage)

    def test_m3_rule_parser_extracts_brand_competitors_and_citations(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis = RuleBasedAnswerParser().parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )
        self.assertTrue(analysis.brand_mentioned)
        self.assertTrue(analysis.brand_recommended)
        self.assertEqual(analysis.citation_count, 3)
        self.assertGreaterEqual(analysis.local_relevance_score, 40)
        self.assertEqual(analysis.parser_engine_id, "rule_based_v2_aliases")

    def test_m3_comparative_parser_records_judge_result_and_agreement(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        judge_analysis = LLMJudgeAnswerParser().parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )
        analysis = ComparativeAnswerParser().parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )
        self.assertEqual(judge_analysis.parser_engine_id, "llm_judge_fixture_v1")
        self.assertEqual(analysis.parser_engine_id, "rule_based_v2_aliases")
        self.assertEqual(analysis.analysis_version, "rule_based_v2_aliases+llm_judge_fixture_v1")
        self.assertIsNotNone(analysis.parser_comparison)
        comparison = analysis.parser_comparison or {}
        self.assertEqual(comparison["secondary_parser_engine_id"], "llm_judge_fixture_v1")
        self.assertEqual(comparison["comparison_method_version"], "parser_ab_compare_v1")
        self.assertIn("agreement_rate", comparison)
        self.assertGreaterEqual(comparison["agreement_rate"], 0)
        self.assertLessEqual(comparison["agreement_rate"], 1)
        self.assertIn("secondary_result", comparison)
        self.assertEqual(comparison["secondary_prompt_version"], "llm_judge_prompt_v1")
        call_log = comparison["secondary_result"]["llm_call_log"]
        self.assertEqual(call_log["purpose"], "parser_judge")
        self.assertEqual(call_log["provider"], "fixture")
        self.assertEqual(call_log["model"], "local-fixture-judge")
        self.assertEqual(call_log["prompt_version"], "llm_judge_prompt_v1")
        self.assertEqual(call_log["status"], "succeeded")
        self.assertGreater(call_log["total_tokens"], 0)
        self.assertEqual(len(call_log["request_hash"]), 64)
        self.assertEqual(len(call_log["response_hash"]), 64)

    def test_m0_fixture_llm_gateway_records_auditable_chat_log(self) -> None:
        gateway = FixtureLLMGateway()

        response = gateway.chat(
            messages=[{"role": "user", "content": "Judge Koala in Australia."}],
            model="local-fixture-judge",
            metadata={"project_id": "project-1", "answer_run_id": "run-1", "purpose": "parser_judge"},
        )

        call_log = response["call_log"]
        self.assertEqual(call_log["project_id"], "project-1")
        self.assertEqual(call_log["answer_run_id"], "run-1")
        self.assertEqual(call_log["purpose"], "parser_judge")
        self.assertEqual(call_log["provider"], "fixture")
        self.assertEqual(call_log["status"], "succeeded")
        self.assertGreater(call_log["prompt_tokens"], 0)
        self.assertGreater(call_log["completion_tokens"], 0)
        self.assertEqual(call_log["total_tokens"], call_log["prompt_tokens"] + call_log["completion_tokens"])

    def test_m0_litellm_gateway_records_auditable_chat_and_embedding_calls(self) -> None:
        class FakeLiteLLMHttpClient:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def post_json(
                self,
                *,
                url: str,
                headers: dict[str, str],
                payload: dict[str, object],
                timeout_seconds: float,
            ) -> dict[str, object]:
                self.calls.append(
                    {
                        "url": url,
                        "headers": headers,
                        "payload": payload,
                        "timeout_seconds": timeout_seconds,
                    }
                )
                if url.endswith("/embeddings"):
                    return {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
                return {
                    "choices": [{"message": {"content": "{\"status\":\"succeeded\"}"}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                }

        http_client = FakeLiteLLMHttpClient()
        gateway = LiteLLMGateway(
            base_url="http://litellm.local",
            api_key="test-key",
            http_client=http_client,
            cost_per_1k_tokens=0.02,
        )

        response = gateway.chat(
            messages=[{"role": "user", "content": "Judge Koala in Australia."}],
            model="gpt-4.1-mini",
            metadata={"project_id": "project-1", "answer_run_id": "run-1", "purpose": "parser_judge"},
        )
        embeddings = gateway.embed(texts=["koala", "mattress"], model="text-embedding-3-small")

        self.assertEqual(response["provider"], "litellm")
        self.assertEqual(response["content"], "{\"status\":\"succeeded\"}")
        self.assertEqual(response["usage"]["total_tokens"], 18)
        self.assertEqual(response["usage"]["estimated_cost"], 0.00036)
        call_log = response["call_log"]
        self.assertEqual(call_log["provider"], "litellm")
        self.assertEqual(call_log["model"], "gpt-4.1-mini")
        self.assertEqual(call_log["purpose"], "parser_judge")
        self.assertEqual(call_log["status"], "succeeded")
        self.assertEqual(call_log["prompt_tokens"], 11)
        self.assertEqual(call_log["completion_tokens"], 7)
        self.assertEqual(call_log["total_tokens"], 18)
        self.assertEqual(len(call_log["request_hash"]), 64)
        self.assertEqual(len(call_log["response_hash"]), 64)
        self.assertEqual(embeddings, [[0.1, 0.2], [0.3, 0.4]])
        self.assertEqual(http_client.calls[0]["url"], "http://litellm.local/chat/completions")
        self.assertEqual(http_client.calls[0]["headers"], {"Authorization": "Bearer test-key"})
        self.assertEqual(http_client.calls[1]["url"], "http://litellm.local/embeddings")

    def test_m0_litellm_gateway_retries_and_prefers_response_cost(self) -> None:
        class FlakyLiteLLMHttpClient:
            def __init__(self) -> None:
                self.call_count = 0

            def post_json(self, **kwargs: object) -> dict[str, object]:
                self.call_count += 1
                if self.call_count == 1:
                    raise RuntimeError("rate limited")
                return {
                    "choices": [{"message": {"content": "{\"status\":\"succeeded\"}"}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.1234567},
                }

        sleep_calls: list[float] = []
        http_client = FlakyLiteLLMHttpClient()
        gateway = LiteLLMGateway(
            base_url="http://litellm.local",
            api_key="test-key",
            http_client=http_client,
            cost_per_1k_tokens=99.0,
            max_retries=2,
            retry_backoff_seconds=0.5,
            sleep_fn=sleep_calls.append,
        )

        response = gateway.chat(
            messages=[{"role": "user", "content": "Judge Koala in Australia."}],
            model="gpt-4.1-mini",
            metadata={"project_id": "project-1", "answer_run_id": "run-1", "purpose": "parser_judge"},
        )

        self.assertEqual(http_client.call_count, 2)
        self.assertEqual(sleep_calls, [0.5])
        self.assertEqual(response["usage"]["attempt_count"], 2)
        self.assertEqual(response["usage"]["retry_errors"], ["rate limited"])
        self.assertEqual(response["usage"]["estimated_cost"], 0.123457)
        self.assertEqual(response["call_log"]["estimated_cost"], 0.123457)
        self.assertEqual(response["raw_response"]["_geno_retry"]["attempt_count"], 2)
        self.assertEqual(response["raw_response"]["_geno_retry"]["prior_errors"], ["rate limited"])

    def test_m0_litellm_gateway_failed_request_keeps_auditable_call_log(self) -> None:
        class FailingLiteLLMHttpClient:
            def __init__(self) -> None:
                self.call_count = 0

            def post_json(self, **kwargs: object) -> dict[str, object]:
                self.call_count += 1
                raise RuntimeError("upstream unavailable")

        http_client = FailingLiteLLMHttpClient()
        sleep_calls: list[float] = []
        gateway = LiteLLMGateway(
            base_url="http://litellm.local",
            api_key="test-key",
            http_client=http_client,
            max_retries=1,
            retry_backoff_seconds=0.25,
            sleep_fn=sleep_calls.append,
        )

        with self.assertRaises(LLMGatewayRequestError) as context:
            gateway.chat(
                messages=[{"role": "user", "content": "Judge Koala in Australia."}],
                model="gpt-4.1-mini",
                metadata={"project_id": "project-1", "answer_run_id": "run-1", "purpose": "parser_judge"},
            )

        call_log = context.exception.call_log
        self.assertEqual(http_client.call_count, 2)
        self.assertEqual(sleep_calls, [0.25])
        self.assertEqual(call_log["provider"], "litellm")
        self.assertEqual(call_log["status"], "failed")
        self.assertIn("upstream unavailable", call_log["error_message"])
        self.assertIn("attempts=2", call_log["error_message"])
        self.assertIn("prior_errors", call_log["error_message"])
        self.assertEqual(len(call_log["request_hash"]), 64)
        self.assertEqual(len(call_log["response_hash"]), 64)

    def test_m3_litellm_judge_failure_degrades_with_call_log(self) -> None:
        class FailingLiteLLMHttpClient:
            def post_json(self, **kwargs: object) -> dict[str, object]:
                raise RuntimeError("upstream unavailable")

        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        judge_parser = LLMJudgeAnswerParser(
            model="gpt-4.1-mini",
            gateway=LiteLLMGateway(base_url="http://litellm.local", api_key="test-key", http_client=FailingLiteLLMHttpClient()),
        )

        analysis = judge_parser.parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )

        comparison = analysis.parser_comparison or {}
        call_log = comparison["llm_call_log"]
        self.assertEqual(call_log["provider"], "litellm")
        self.assertEqual(call_log["status"], "failed")
        self.assertIn("upstream unavailable", call_log["error_message"])
        self.assertIn("attempts=1", call_log["error_message"])
        self.assertIn("llm_gateway_failed", analysis.uncertainty_flags)
        self.assertIn("LiteLLM chat request failed", comparison["llm_gateway_error"])

    def test_m3_litellm_gateway_can_back_llm_judge_without_parser_changes(self) -> None:
        class FakeLiteLLMHttpClient:
            def post_json(self, **kwargs: object) -> dict[str, object]:
                return {
                    "choices": [{"message": {"content": "{\"brand_mentioned\":true}"}}],
                    "usage": {"prompt_tokens": 17, "completion_tokens": 5},
                }

        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        judge_parser = LLMJudgeAnswerParser(
            model="gpt-4.1-mini",
            gateway=LiteLLMGateway(base_url="http://litellm.local", api_key="test-key", http_client=FakeLiteLLMHttpClient()),
        )

        analysis = ComparativeAnswerParser(judge_parser=judge_parser).parse_record(
            record=records[0],
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
        )

        comparison = analysis.parser_comparison or {}
        call_log = comparison["secondary_result"]["llm_call_log"]
        self.assertEqual(call_log["provider"], "litellm")
        self.assertEqual(call_log["model"], "gpt-4.1-mini")
        self.assertEqual(call_log["status"], "succeeded")
        self.assertEqual(comparison["secondary_prompt_version"], "llm_judge_prompt_v1")

    def test_m3_analysis_pipeline_accepts_litellm_judge_parser_adapter(self) -> None:
        class FakeLiteLLMHttpClient:
            def post_json(self, **kwargs: object) -> dict[str, object]:
                return {
                    "choices": [{"message": {"content": "{\"brand_mentioned\":true}"}}],
                    "usage": {"prompt_tokens": 17, "completion_tokens": 5},
                }

        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        parser = ComparativeAnswerParser(
            judge_parser=LLMJudgeAnswerParser(
                model="gpt-4.1-mini",
                gateway=LiteLLMGateway(base_url="http://litellm.local", api_key="test-key", http_client=FakeLiteLLMHttpClient()),
            )
        )

        result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            parser=parser,
        )

        call_log = result.analyses[0].parser_comparison["secondary_result"]["llm_call_log"]  # type: ignore[index]
        self.assertEqual(call_log["provider"], "litellm")
        self.assertEqual(result.audit_event.event_type, "visibility_score_snapshot_created")

    def test_m3_rule_parser_uses_confirmed_entity_aliases(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        prompt = bootstrap.prompt_questions[0]
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=bootstrap.project.id,
                prompt_question_id=prompt.id,
                prompt_text=prompt.text,
                market_code=prompt.market_code,
                city=prompt.city,
                language=prompt.language,
                platform="google",
                surface="google_ai_mode",
                answer_text=(
                    "K-Brand AU is a good choice in Sydney. "
                    "Emma-Sleep-AU is also visible in Australian recommendations."
                ),
                citation_urls=("https://example.com/koala-alias",),
            )
        )
        analysis = RuleBasedAnswerParser().parse_record(
            record=record,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            entity_aliases={
                bootstrap.brand.id: ("K-Brand AU",),
                bootstrap.competitors[0].id: ("Emma-Sleep-AU",),
            },
        )
        self.assertTrue(analysis.brand_mentioned)
        self.assertTrue(analysis.brand_recommended)
        self.assertEqual(analysis.brand_position, 1)
        self.assertEqual(analysis.competitors_mentioned, ["Emma Sleep"])
        self.assertIn("brand_alias_matched", analysis.uncertainty_flags)
        self.assertIn("competitor_alias_matched:Emma Sleep", analysis.uncertainty_flags)
        self.assertNotIn("brand_not_mentioned", analysis.uncertainty_flags)

    def test_m3_analysis_pipeline_creates_aggregate_score_and_explanation(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=10,
        )
        result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        contribution_total = round(sum(item.weighted_contribution for item in result.contributions), 4)
        self.assertEqual(len(result.analyses), 40)
        self.assertEqual(len(result.contributions), len(AU_VISIBILITY_V1))
        self.assertTrue(all(analysis.parser_comparison for analysis in result.analyses))
        self.assertTrue(all("parser_ab_agreement=" in item.confidence_note for item in result.contributions))
        self.assertEqual(contribution_total, result.snapshot.final_score)
        self.assertGreater(result.snapshot.mention_rate, 0)
        self.assertLessEqual(result.snapshot.mention_rate, 1)
        self.assertGreaterEqual(result.snapshot.dispersion, 0)
        self.assertEqual(result.audit_event.event_type, "visibility_score_snapshot_created")
        self.assertEqual(
            result.audit_event.output_refs["score_snapshot_ids"],
            [result.snapshot.id],
        )

    def test_m3_score_input_policy_excludes_google_until_both_spike_gates_pass(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        stable_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        plan = build_google_spike_plan(project_id=bootstrap.project.id, prompts=bootstrap.prompt_questions)
        google_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureGoogleAIModeCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        google_gate = evaluate_google_spike_gate(project_id=bootstrap.project.id, plan=plan, records=google_records)
        browser_only_readiness_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=google_records,
        )
        limited_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=stable_records + google_records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            google_spike_gate=google_gate,
            google_spike_readiness_gate=browser_only_readiness_gate,
        )
        self.assertEqual(len(limited_result.analyses), len(stable_records) + len(google_records))
        self.assertEqual(len(limited_result.score_input_analyses), len(stable_records))
        self.assertEqual(set(limited_result.snapshot.answer_run_ids), {record.answer_run.id for record in stable_records})
        self.assertEqual(limited_result.score_input_policy["google_gate_status"], "pass")
        self.assertEqual(limited_result.score_input_policy["google_readiness_gate_status"], "fail")
        self.assertFalse(limited_result.score_input_policy["google_main_scoring_allowed"])
        self.assertEqual(limited_result.score_input_policy["excluded_google_record_count"], len(google_records))
        self.assertEqual(
            limited_result.audit_event.input_refs["score_input_answer_run_ids"],
            [record.answer_run.id for record in stable_records],
        )
        self.assertEqual(
            set(limited_result.audit_event.input_refs["excluded_google_answer_run_ids"]),
            {record.answer_run.id for record in google_records},
        )
        self.assertTrue(
            all("excluded_answer_runs=240" in contribution.confidence_note for contribution in limited_result.contributions)
        )

        multi_path_google_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=select_google_spike_prompts(bootstrap.prompt_questions),
            market_profile=bootstrap.market_profile,
            collectors=(FixtureGoogleAIOCollector(), FixtureThirdPartySerpCollector()),
            cities=plan.geo_cities,
            sample_size=plan.sample_size,
            prompt_limit=plan.prompt_count,
        )
        multi_path_gate = evaluate_google_spike_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=multi_path_google_records,
        )
        multi_path_readiness_gate = evaluate_google_spike_readiness_gate(
            project_id=bootstrap.project.id,
            plan=plan,
            records=multi_path_google_records,
        )
        allowed_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=stable_records + multi_path_google_records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            google_spike_gate=multi_path_gate,
            google_spike_readiness_gate=multi_path_readiness_gate,
        )
        self.assertTrue(allowed_result.score_input_policy["google_main_scoring_allowed"])
        self.assertEqual(allowed_result.score_input_policy["excluded_google_record_count"], 0)
        self.assertEqual(len(allowed_result.score_input_analyses), len(stable_records) + len(multi_path_google_records))

    def test_m3_score_input_policy_excludes_browser_fidelity_samples_from_main_score(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(
                FixturePerplexitySonarCollector(),
                FixtureOpenAIWebSearchCollector(),
                FixtureChatGPTSearchBrowserCollector(),
            ),
            cities=("Sydney",),
            sample_size=1,
            prompt_limit=1,
        )

        result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )

        browser_records = tuple(record for record in records if record.answer_run.access_method == "browser")
        self.assertEqual(len(records), 3)
        self.assertEqual(len(browser_records), 1)
        self.assertEqual(len(result.analyses), 3)
        self.assertEqual(len(result.score_input_records), 2)
        self.assertNotIn(browser_records[0].answer_run.id, result.snapshot.answer_run_ids)
        self.assertEqual(result.score_input_policy["excluded_fidelity_sample_record_count"], 1)
        self.assertEqual(
            result.score_input_policy["excluded_fidelity_sample_answer_run_ids"],
            [browser_records[0].answer_run.id],
        )
        self.assertEqual(
            result.score_input_policy["exclusion_reasons_by_answer_run_id"][browser_records[0].answer_run.id],
            "api_browser_fidelity_sample_only",
        )
        self.assertIn(
            browser_records[0].answer_run.id,
            result.audit_event.input_refs["excluded_fidelity_sample_answer_run_ids"],
        )

    def test_m3_analysis_pipeline_scores_alias_only_mentions(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        prompt = bootstrap.prompt_questions[0]
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=bootstrap.project.id,
                prompt_question_id=prompt.id,
                prompt_text=prompt.text,
                market_code=prompt.market_code,
                city=prompt.city,
                language=prompt.language,
                platform="perplexity",
                surface="sonar",
                answer_text="K-Brand AU is recommended for Australian mattress shoppers.",
                citation_urls=("https://example.com/k-brand",),
            )
        )
        without_alias = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=(record,),
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        with_alias = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=(record,),
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            entity_aliases={bootstrap.brand.id: ("K-Brand AU",)},
        )
        self.assertEqual(without_alias.snapshot.mention_rate, 0.0)
        self.assertEqual(with_alias.snapshot.mention_rate, 1.0)
        self.assertEqual(with_alias.snapshot.recommendation_rate, 1.0)
        self.assertIn("brand_alias_matched", with_alias.analyses[0].uncertainty_flags)

    def test_m4_citation_graph_and_competitor_benchmark_trace_to_answer_runs(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=10,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        self.assertGreaterEqual(len(graph.nodes), 3)
        self.assertGreater(len(graph.evidence_links), 0)
        self.assertTrue(graph.source_gaps)
        self.assertEqual(len(graph.competitor_benchmarks), 3)
        self.assertTrue(all(node.answer_run_ids for node in graph.nodes))
        self.assertTrue(all(link.answer_run_id for link in graph.evidence_links))
        self.assertTrue(any(item.mention_count > 0 for item in graph.competitor_benchmarks))

    def test_graph_store_pg_and_neo4j_projection_keep_citation_queries_stable(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=10,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        pg_store = InMemoryPostgresAdjacencyGraphStore()
        neo4j_store = InMemoryNeo4jCitationGraphStore()

        self.assertIsInstance(pg_store, GraphStore)
        self.assertIsInstance(neo4j_store, GraphStore)
        pg_store.save_citation_graph(project_id=bootstrap.project.id, graph=graph)
        neo4j_store.save_citation_graph(project_id=bootstrap.project.id, graph=graph)

        pg_summary = summarize_citation_graph_store(pg_store, project_id=bootstrap.project.id)
        neo4j_summary = summarize_citation_graph_store(neo4j_store, project_id=bootstrap.project.id)
        self.assertEqual(pg_summary, neo4j_summary)
        self.assertGreater(pg_summary["source_node_count"], 0)
        self.assertGreater(pg_summary["evidence_link_count"], 0)
        self.assertEqual(set(pg_summary["competitor_names"]), {"Emma Sleep", "Sleeping Duck", "Ecosa"})

    def test_m5_report_export_freezes_snapshot_and_evidence_refs(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=10,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        report = MarkdownCsvReportExporter().export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version="p0a-fixture-v1",
            report_type="design_partner_fixture",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=records,
            graph=graph,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            score_input_policy=analysis_result.score_input_policy,
            audit_events=(analysis_result.audit_event,),
        )
        self.assertEqual(report.report_export.score_snapshot_ids, (analysis_result.snapshot.id,))
        self.assertEqual(report.report_export.answer_run_ids, tuple(record.answer_run.id for record in records))
        self.assertTrue(report.report_export.markdown_url.endswith(".md"))
        assert report.report_export.pdf_url is not None
        self.assertTrue(report.report_export.pdf_url.endswith(".pdf"))
        self.assertTrue(report.report_export.csv_url.endswith(".csv"))
        self.assertIn("GENO AU Evidence Report", report.markdown)
        self.assertIn("### Method Disclosure", report.markdown)
        self.assertIn("Google spike gate: not_run", report.markdown)
        self.assertIn("Google limited coverage: yes", report.markdown)
        self.assertIn("Main scoring Google allowed: False", report.markdown)
        self.assertIn("Main scoring records: 40", report.markdown)
        self.assertIn("Excluded Google records from main scoring: 0", report.markdown)
        self.assertIn("API-vs-browser fidelity: not_run", report.markdown)
        self.assertIn("Trigger rate denominator: all attempted evidence records in this report window", report.markdown)
        self.assertIn("Mention rate denominator: surface_triggered evidence records, not all attempted records", report.markdown)
        self.assertIn(
            "Recommendation rate denominator: surface_triggered evidence records, not all attempted records",
            report.markdown,
        )
        self.assertIn("Report evidence attempted records: 40", report.markdown)
        self.assertIn("Report evidence surface-triggered records: 40", report.markdown)
        self.assertIn("Access method distribution", report.markdown)
        self.assertIn("### Audit Summary", report.markdown)
        self.assertIn("Audit events attached: 1", report.markdown)
        self.assertIn("visibility_score_snapshot_created", report.markdown)
        score_rate_disclosure = report.report_export.method_disclosure["score_rate_denominators"]
        self.assertEqual(
            score_rate_disclosure["definitions"]["trigger_rate"]["formula"],
            "surface_triggered_records / attempted_records",
        )
        self.assertEqual(
            score_rate_disclosure["definitions"]["mention_rate"]["denominator"],
            "surface_triggered evidence records, not all attempted records",
        )
        self.assertEqual(score_rate_disclosure["evidence_denominators"]["attempted_records"], len(records))
        self.assertEqual(score_rate_disclosure["evidence_denominators"]["surface_triggered_records"], len(records))
        self.assertEqual(report.report_export.method_disclosure["score_input_policy"], analysis_result.score_input_policy)
        audit_summary = report.report_export.method_disclosure["audit_summary"]
        self.assertEqual(audit_summary["audit_event_count"], 1)
        self.assertEqual(audit_summary["event_type_distribution"]["visibility_score_snapshot_created"], 1)
        self.assertIn("score_snapshot_ids", audit_summary["output_ref_keys"])
        self.assertIn("answer_run_id", report.csv_content)
        self.assertTrue(report.pdf_content.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", report.pdf_content)
        self.assertEqual(report.audit_event.event_type, "report_export_created")
        self.assertEqual(report.audit_event.output_refs["report_export_ids"], [report.report_export.id])
        self.assertEqual(report.report_evidence_answer_run_ids, report.report_export.answer_run_ids)

    def test_m5_report_method_disclosure_can_use_fidelity_records_without_changing_report_denominator(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        all_records = run_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(
                FixturePerplexitySonarCollector(),
                FixtureOpenAIWebSearchCollector(),
                FixtureChatGPTSearchBrowserCollector(),
            ),
            cities=("Sydney",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=all_records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=analysis_result.score_input_records,
            analyses=analysis_result.score_input_analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        report = MarkdownCsvReportExporter().export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version="p0a-fidelity-fixture-v1",
            report_type="design_partner_fixture",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=analysis_result.score_input_records,
            graph=graph,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
            score_input_policy=analysis_result.score_input_policy,
            fidelity_records=all_records,
        )

        self.assertEqual(report.report_export.sample_size, 2)
        self.assertEqual(len(report.report_export.answer_run_ids), 2)
        self.assertEqual(
            report.report_export.method_disclosure["score_rate_denominators"]["evidence_denominators"][
                "attempted_records"
            ],
            2,
        )
        fidelity = report.report_export.method_disclosure["api_browser_fidelity"]
        self.assertEqual(fidelity["status"], "sampled")
        self.assertEqual(fidelity["official_api_records"], 2)
        self.assertEqual(fidelity["browser_records"], 1)
        self.assertEqual(fidelity["comparable_prompt_city_pairs"], 1)
        self.assertEqual(fidelity["difference_rate"], 0.0)
        self.assertIn("API-vs-browser fidelity: sampled", report.markdown)
        self.assertIn("Official API records: 2", report.markdown)
        self.assertIn("Browser records: 1", report.markdown)
        self.assertIn("Report evidence attempted records: 2", report.markdown)

    def test_report_artifacts_archive_to_s3_compatible_store(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        report = MarkdownCsvReportExporter().export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version="p0a-fixture-v1",
            report_type="design_partner_fixture",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=records,
            graph=graph,
            platform_weights_snapshot={"chatgpt": 0.30, "perplexity": 0.25},
        )
        requests: list[tuple[str, str, dict[str, str], bytes]] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append((method, url, dict(headers), body))
            return 200, {"ETag": '"test-etag"'}, b""

        store = S3CompatibleObjectStore(
            endpoint="http://minio:9000",
            bucket="geno-reports",
            access_key="minio",
            secret_key="minio123",
            requester=requester,
        )
        stored = archive_report_artifacts(report, store)

        self.assertEqual(len(stored), 3)
        self.assertEqual(
            [item.content_type for item in stored],
            ["text/markdown; charset=utf-8", "application/pdf", "text/csv; charset=utf-8"],
        )
        self.assertTrue(all(item.uri.startswith("s3://geno-reports/") for item in stored))
        self.assertTrue(all(item.content_hash for item in stored))
        object_puts = [item for item in requests if item[0] == "PUT" and item[1].count("/") > 3]
        self.assertEqual(len(object_puts), 3)
        self.assertTrue(any(item[1].endswith(".pdf") and item[3].startswith(b"%PDF-1.4") for item in object_puts))

    def test_project_brand_logo_archive_to_s3_compatible_store(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        requests: list[tuple[str, str, dict[str, str], bytes]] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append((method, url, dict(headers), body))
            return 200, {"ETag": '"logo-etag"'}, b""

        store = S3CompatibleObjectStore(
            endpoint="http://minio:9000",
            bucket="geno-reports",
            access_key="minio",
            secret_key="minio123",
            requester=requester,
        )
        stored = archive_project_brand_logo(
            project_id=project_id,
            filename="../Client Logo Final.PNG",
            content=b"fake-logo-bytes",
            content_type="image/png",
            store=store,
        )

        self.assertEqual(stored.content_type, "image/png")
        self.assertEqual(stored.content_hash, "3a4fbb95f7aa11b1ad48768f3b59e812ce35f94ab2795c8feefda65f67916f2f")
        self.assertEqual(stored.uri, f"s3://geno-reports/brand-assets/{project_id}/logo-3a4fbb95f7aa-Client-Logo-Final.PNG")
        object_puts = [item for item in requests if item[0] == "PUT" and "brand-assets" in item[1]]
        self.assertEqual(len(object_puts), 1)
        self.assertTrue(object_puts[0][1].endswith("/brand-assets/9a50797d-a341-55a4-8bdf-cc255c017e5c/logo-3a4fbb95f7aa-Client-Logo-Final.PNG"))
        self.assertEqual(object_puts[0][3], b"fake-logo-bytes")

    def test_runtime_report_artifact_archive_to_s3_compatible_store(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        requests: list[tuple[str, str, dict[str, str], bytes]] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append((method, url, dict(headers), body))
            return 200, {"ETag": '"runtime-report-etag"'}, b""

        store = S3CompatibleObjectStore(
            endpoint="http://minio:9000",
            bucket="geno-reports",
            access_key="minio",
            secret_key="minio123",
            requester=requester,
        )
        artifact = RuntimeReportArtifact(
            report_export={"id": report_export_id, "project_id": project_id, "report_version": "worker-runtime-v1"},
            artifact_type="pdf",
            template="white_label",
            template_payload={"template": "white_label", "client_name": "ExampleBrand AU"},
            template_hash="template-hash",
            filename="worker-runtime-v1-white-label.pdf",
            media_type="application/pdf",
            content=b"%PDF-1.4 runtime report\n%%EOF",
            content_hash="report-content-hash",
            filters={"platform": "perplexity"},
            filter_hash="filter-hash",
            sort="cost_desc",
            total_count=10,
            row_count=4,
        )

        stored = archive_runtime_report_artifact(project_id=project_id, artifact=artifact, store=store)

        self.assertEqual(stored.content_type, "application/pdf")
        self.assertEqual(stored.uri, (
            "s3://geno-reports/report-artifacts/"
            "9a50797d-a341-55a4-8bdf-cc255c017e5c/"
            "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad/"
            "white_label/filter-hash/cost_desc/report-conte-worker-runtime-v1-white-label.pdf"
        ))
        object_puts = [item for item in requests if item[0] == "PUT" and "report-artifacts" in item[1]]
        self.assertEqual(len(object_puts), 1)
        self.assertTrue(object_puts[0][1].endswith(
            "/report-artifacts/9a50797d-a341-55a4-8bdf-cc255c017e5c/"
            "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad/white_label/filter-hash/cost_desc/"
            "report-conte-worker-runtime-v1-white-label.pdf"
        ))
        self.assertEqual(object_puts[0][3], b"%PDF-1.4 runtime report\n%%EOF")

    def test_api_snapshot_assets_archive_to_s3_compatible_store(self) -> None:
        class FakeApiHttpClient:
            def post_json(self, **kwargs: object) -> JsonHttpResponse:
                return JsonHttpResponse(
                    status_code=200,
                    payload={
                        "choices": [{"message": {"content": "Perplexity answer"}}],
                        "citations": ["https://source.example/a"],
                    },
                )

        bootstrap = build_au_project_bootstrap()
        record = collect_prompt_once(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=PerplexitySonarCollector(api_key="test-key", http_client=FakeApiHttpClient()),
            city="Sydney",
            sample_index=1,
            sample_size=3,
        )
        self.assertTrue(record.evidence_assets[0].url.startswith("geno-api-snapshot://"))
        requests: list[tuple[str, str, dict[str, str], bytes]] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append((method, url, dict(headers), body))
            return 200, {"ETag": '"snapshot-etag"'}, b""

        store = S3CompatibleObjectStore(
            endpoint="http://minio:9000",
            bucket="geno-reports",
            access_key="minio",
            secret_key="minio123",
            requester=requester,
        )
        archived_records, stored = archive_api_snapshot_assets(records=(record,), store=store)

        self.assertEqual(len(stored), 1)
        self.assertTrue(stored[0].uri.startswith(f"s3://geno-reports/evidence/{bootstrap.project.id}/"))
        self.assertEqual(stored[0].content_type, "text/html; charset=utf-8")
        archived_asset = archived_records[0].evidence_assets[0]
        self.assertEqual(archived_asset.url, stored[0].uri)
        self.assertEqual(archived_asset.content_hash, stored[0].content_hash)
        object_puts = [item for item in requests if item[0] == "PUT" and item[1].count("/") > 3]
        self.assertEqual(len(object_puts), 1)
        self.assertIn(b"GENO Official API Response Snapshot", object_puts[0][3])
        self.assertIn(b"Perplexity answer", object_puts[0][3])

    def test_browser_capture_assets_archive_to_s3_compatible_store(self) -> None:
        class FakeLocator:
            @property
            def last(self) -> "FakeLocator":
                return self

            def inner_text(self, **kwargs: object) -> str:
                return "Browser answer with durable artifacts."

            def evaluate_all(self, script: str) -> list[str]:
                return ["https://source.example/browser"]

        class FakeKeyboard:
            def press(self, key: str) -> None:
                self.key = key

        class FakePage:
            url = "https://chatgpt.com/c/fake-browser-archive"

            def __init__(self) -> None:
                self.keyboard = FakeKeyboard()

            def goto(self, *args: object, **kwargs: object) -> None:
                return None

            def fill(self, *args: object, **kwargs: object) -> None:
                return None

            def wait_for_selector(self, *args: object, **kwargs: object) -> None:
                return None

            def locator(self, selector: str) -> FakeLocator:
                return FakeLocator()

            def title(self) -> str:
                return "Fake Browser Archive"

            def content(self) -> str:
                return "<html><body>Browser archive HTML</body></html>"

            def screenshot(self, **kwargs: object) -> bytes:
                return b"browser-png"

        class FakeContext:
            def new_page(self) -> FakePage:
                return FakePage()

            def close(self) -> None:
                return None

        class FakeBrowser:
            def launch(self, **kwargs: object) -> "FakeBrowser":
                return self

            def new_context(self, **kwargs: object) -> FakeContext:
                return FakeContext()

            def close(self) -> None:
                return None

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeBrowser()

        class FakePlaywrightManager:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, *args: object) -> None:
                return None

        requests: list[tuple[str, str, dict[str, str], bytes]] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append((method, url, dict(headers), body))
            return 200, {"ETag": '"browser-etag"'}, b""

        bootstrap = build_au_project_bootstrap()
        with TemporaryDirectory() as artifact_dir:
            record = collect_prompt_once(
                project_id=bootstrap.project.id,
                prompt=bootstrap.prompt_questions[0],
                market_profile=bootstrap.market_profile,
                collector=PlaywrightChatGPTSearchCollector(
                    enabled=True,
                    prompt_selector="#prompt",
                    answer_selector=".answer",
                    citation_selector=".citation",
                    artifact_dir=artifact_dir,
                    playwright_factory=FakePlaywrightManager,
                ),
                city="Sydney",
                sample_index=1,
                sample_size=1,
            )
            self.assertEqual(record.answer_run.access_method, "browser")
            self.assertTrue(all(asset.url.startswith("file://") for asset in record.evidence_assets))
            store = S3CompatibleObjectStore(
                endpoint="http://minio:9000",
                bucket="geno-reports",
                access_key="minio",
                secret_key="minio123",
                requester=requester,
            )
            archived_records, stored = archive_browser_capture_assets(records=(record,), store=store)

        self.assertEqual(len(stored), 2)
        self.assertEqual({item.content_type for item in stored}, {"text/html; charset=utf-8", "image/png"})
        archived_assets = archived_records[0].evidence_assets
        self.assertTrue(all(asset.url.startswith("s3://geno-reports/evidence/") for asset in archived_assets))
        self.assertTrue(all(asset.content_hash for asset in archived_assets))
        object_puts = [item for item in requests if item[0] == "PUT" and item[1].count("/") > 3]
        self.assertEqual(len(object_puts), 2)
        self.assertTrue(any(b"Browser archive HTML" in item[3] for item in object_puts))
        self.assertTrue(any(item[3] == b"browser-png" for item in object_puts))

    def test_m6_action_plan_and_retest_schedule_trace_evidence(self) -> None:
        bootstrap = build_au_project_bootstrap(
            target_brand="Koala",
            category="mattresses",
            competitors=("Emma Sleep", "Sleeping Duck", "Ecosa"),
        )
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=10,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        actions = build_action_recommendations(
            project_id=bootstrap.project.id,
            graph=graph,
            snapshot=analysis_result.snapshot,
            owner_id="owner-1",
            now=datetime(2026, 6, 10, tzinfo=UTC),
        )
        schedule = build_retest_schedule(
            project_id=bootstrap.project.id,
            prompt_version=bootstrap.project.prompt_version,
            sample_size=1,
            answer_run_ids=tuple(record.answer_run.id for record in records),
            start_at=datetime(2026, 6, 10, tzinfo=UTC),
        )
        audit_event = build_action_plan_audit_event(
            project_id=bootstrap.project.id,
            actions=actions,
            schedule=schedule,
        )
        self.assertTrue(actions)
        self.assertTrue(all(action.status == "open" for action in actions))
        self.assertTrue(all(action.next_check_date for action in actions))
        self.assertTrue(all(action.evidence_answer_run_ids for action in actions))
        self.assertEqual(schedule.offsets_days, (0, 7, 14, 30))
        self.assertEqual(len(schedule.scheduled_dates), 4)
        self.assertEqual(schedule.answer_run_ids, tuple(record.answer_run.id for record in records))
        self.assertEqual(audit_event.event_type, "action_plan_created")
        self.assertEqual(audit_event.output_refs["retest_schedule_ids"], [schedule.id])

    def test_m6_retest_comparison_classifies_trend(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=2,
        )
        baseline = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        ).snapshot
        retest = baseline.__class__(
            **{
                **baseline.__dict__,
                "id": "retest-snapshot",
                "final_score": baseline.final_score + 3,
            }
        )
        comparison = compare_retest_windows(
            project_id=bootstrap.project.id,
            baseline=baseline,
            retest=retest,
            now=datetime(2026, 6, 17, tzinfo=UTC),
        )
        self.assertEqual(comparison.trend, "improved")
        self.assertEqual(comparison.score_delta, 3)
        self.assertEqual(comparison.baseline_answer_run_ids, tuple(baseline.answer_run_ids))
        audit_event = build_retest_comparison_audit_event(
            project_id=bootstrap.project.id,
            comparison=comparison,
        )
        self.assertEqual(audit_event.event_type, "retest_comparison_created")
        self.assertEqual(audit_event.output_refs["retest_comparison_ids"], [comparison.id])

    def test_m7_content_drafts_bind_knowledge_gap_and_evidence(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=10,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        actions = build_action_recommendations(
            project_id=bootstrap.project.id,
            graph=graph,
            snapshot=analysis_result.snapshot,
        )
        facts = build_localized_knowledge_facts(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            brand=bootstrap.brand,
            category=bootstrap.project.category,
            answer_run_ids=tuple(record.answer_run.id for record in records),
            now=datetime(2026, 6, 10, tzinfo=UTC),
        )
        search_results = search_knowledge_facts(
            facts=facts,
            query="ExampleBrand Australia shipping review Sydney",
            market_code="AU",
            city="Sydney",
            limit=6,
        )
        drafts = build_content_drafts(
            project_id=bootstrap.project.id,
            target_brand=bootstrap.project.target_brand,
            category=bootstrap.project.category,
            actions=actions,
            prompts=bootstrap.prompt_questions,
            knowledge_results=search_results,
            now=datetime(2026, 6, 10, tzinfo=UTC),
        )
        connectors = build_integration_connectors(project_id=bootstrap.project.id)
        distribution_records = build_manual_distribution_records(project_id=bootstrap.project.id, drafts=drafts)
        audit_event = build_content_engine_audit_event(
            project_id=bootstrap.project.id,
            facts=facts,
            drafts=drafts,
            connectors=connectors,
            distribution_records=distribution_records,
        )
        self.assertTrue(facts)
        self.assertTrue(search_results)
        self.assertTrue(any(result.fallback_used for result in search_results))
        self.assertTrue(drafts)
        self.assertTrue(all(draft.review_status == "pending_human_review" for draft in drafts))
        self.assertTrue(all(draft.used_knowledge_fact_ids for draft in drafts))
        self.assertTrue(all(draft.source_gap_types for draft in drafts))
        self.assertTrue(all(draft.evidence_answer_run_ids for draft in drafts))
        self.assertEqual(len(connectors), 7)
        self.assertEqual(len(distribution_records), len(drafts))
        self.assertEqual(audit_event.event_type, "content_engine_fixture_created")
        self.assertEqual(audit_event.output_refs["content_draft_ids"], [draft.id for draft in drafts])

    def test_traceability_bundle_connects_report_to_raw_evidence_and_actions(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(), FixtureOpenAIWebSearchCollector()),
            cities=("Australia", "Sydney"),
            sample_size=1,
            prompt_limit=10,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        report = MarkdownCsvReportExporter().export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version="p0a-fixture-v1",
            report_type="design_partner_fixture",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=records,
            graph=graph,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        actions = build_action_recommendations(
            project_id=bootstrap.project.id,
            graph=graph,
            snapshot=analysis_result.snapshot,
        )
        facts = build_localized_knowledge_facts(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            brand=bootstrap.brand,
            category=bootstrap.project.category,
            answer_run_ids=tuple(record.answer_run.id for record in records),
        )
        search_results = search_knowledge_facts(
            facts=facts,
            query="ExampleBrand Australia shipping review Sydney",
            market_code="AU",
            city="Sydney",
            limit=5,
        )
        drafts = build_content_drafts(
            project_id=bootstrap.project.id,
            target_brand=bootstrap.project.target_brand,
            category=bootstrap.project.category,
            actions=actions,
            prompts=bootstrap.prompt_questions,
            knowledge_results=search_results,
        )
        bundle = build_traceability_bundle(
            project_id=bootstrap.project.id,
            report_export=report.report_export,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=records,
            graph=graph,
            actions=actions,
            content_drafts=drafts,
            audit_events=tuple(record.audit_events[0] for record in records)
            + (analysis_result.audit_event, report.audit_event),
        )
        self.assertEqual(bundle.report_export_ids, (report.report_export.id,))
        self.assertEqual(bundle.score_snapshot_ids, (analysis_result.snapshot.id,))
        self.assertEqual(bundle.answer_run_ids, report.report_export.answer_run_ids)
        self.assertEqual(len(bundle.score_contribution_ids), len(analysis_result.contributions))
        self.assertEqual(len(bundle.raw_answer_ids), len(records))
        self.assertGreater(len(bundle.answer_citation_ids), 0)
        self.assertGreater(len(bundle.evidence_asset_ids), 0)
        self.assertEqual(bundle.action_recommendation_ids, tuple(action.id for action in actions))
        self.assertEqual(bundle.content_draft_ids, tuple(draft.id for draft in drafts))
        self.assertTrue(any(link.relation_type == "explained_by" for link in bundle.evidence_links))
        self.assertTrue(any(link.relation_type == "supports_draft" for link in bundle.evidence_links))
        self.assertIn("answer runs", bundle.explanation_summary)

    def test_postgres_repository_maps_fixture_chain_to_runtime_tables(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        analysis_result = analyze_and_score_records(
            project_id=bootstrap.project.id,
            records=records,
            brand=bootstrap.brand,
            competitors=bootstrap.competitors,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        graph = build_citation_graph(
            project_id=bootstrap.project.id,
            records=records,
            analyses=analysis_result.analyses,
            competitors=bootstrap.competitors,
            industry_profile=bootstrap.industry_profile,
        )
        report = MarkdownCsvReportExporter().export(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            report_version="repository-fixture-v1",
            report_type="repository_fixture",
            prompt_version=bootstrap.project.prompt_version,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=records,
            graph=graph,
            platform_weights_snapshot={"google": 0.45, "chatgpt": 0.30, "perplexity": 0.25},
        )
        actions = build_action_recommendations(
            project_id=bootstrap.project.id,
            graph=graph,
            snapshot=analysis_result.snapshot,
        )
        schedule = build_retest_schedule(
            project_id=bootstrap.project.id,
            prompt_version=bootstrap.project.prompt_version,
            sample_size=1,
            answer_run_ids=tuple(record.answer_run.id for record in records),
        )
        action_audit = build_action_plan_audit_event(
            project_id=bootstrap.project.id,
            actions=actions,
            schedule=schedule,
        )
        facts = build_localized_knowledge_facts(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            brand=bootstrap.brand,
            category=bootstrap.project.category,
            answer_run_ids=tuple(record.answer_run.id for record in records),
        )
        search_results = search_knowledge_facts(
            facts=facts,
            query="ExampleBrand Australia shipping",
            market_code="AU",
            limit=3,
        )
        drafts = build_content_drafts(
            project_id=bootstrap.project.id,
            target_brand=bootstrap.project.target_brand,
            category=bootstrap.project.category,
            actions=actions,
            prompts=bootstrap.prompt_questions,
            knowledge_results=search_results,
        )
        connectors = build_integration_connectors(project_id=bootstrap.project.id)
        distribution_records = build_manual_distribution_records(project_id=bootstrap.project.id, drafts=drafts)
        content_audit = build_content_engine_audit_event(
            project_id=bootstrap.project.id,
            facts=facts,
            drafts=drafts,
            connectors=connectors,
            distribution_records=distribution_records,
        )
        bundle = build_traceability_bundle(
            project_id=bootstrap.project.id,
            report_export=report.report_export,
            snapshot=analysis_result.snapshot,
            contributions=analysis_result.contributions,
            records=records,
            graph=graph,
            actions=actions,
            content_drafts=drafts,
            audit_events=tuple(record.audit_events[0] for record in records)
            + (analysis_result.audit_event, report.audit_event, action_audit, content_audit),
        )
        connection = RecordingConnection()
        repository = PostgresEvidenceRepository(
            connection,
            email_preference_base_url="https://app.example.com/notifications/unsubscribe",
            email_preference_token_secret="preference-secret",
            email_preference_token_ttl_seconds=3600,
        )
        repository.save_raw_evidence_records(records)
        repository.save_answer_analyses(analysis_result.analyses)
        repository.save_score_snapshot(
            analysis_result.snapshot,
            analysis_result.contributions,
            analysis_result.audit_event,
        )
        repository.save_citation_graph(bootstrap.project.id, graph)
        repository.save_report_export(report.report_export, report.audit_event)
        fidelity_check, fidelity_audit = build_runtime_fidelity_check(
            project_id=bootstrap.project.id,
            report_export_id=report.report_export.id,
            answer_run_rows=tuple(
                {
                    "id": record.answer_run.id,
                    "prompt_question_id": record.answer_run.prompt_question_id,
                    "access_method": record.answer_run.access_method,
                    "city": record.answer_run.city,
                    "answer_present": record.answer_run.answer_present,
                    "surface_triggered": record.answer_run.surface_triggered,
                }
                for record in records
            ),
            checked_by="unit-test",
        )
        repository.save_fidelity_check(fidelity_check, fidelity_audit)
        repository.save_action_plan(
            actions=actions,
            schedule=schedule,
            comparison=None,
            audit_events=(action_audit,),
        )
        repository.save_content_engine(
            facts=facts,
            drafts=drafts,
            connectors=connectors,
            distribution_records=distribution_records,
            audit_event=content_audit,
        )
        repository.save_traceability_bundle(bundle)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        expected_tables = (
            "answer_runs",
            "raw_answers",
            "answer_citations",
            "evidence_assets",
            "collector_logs",
            "collection_costs",
            "answer_analyses",
            "llm_call_logs",
            "visibility_score_snapshots",
            "score_contributions",
            "source_graphs",
            "source_gaps",
            "competitor_benchmarks",
            "report_exports",
            "api_browser_fidelity_checks",
            "action_recommendations",
            "retest_schedules",
            "localized_knowledge_facts",
            "knowledge_fact_embeddings",
            "content_drafts",
            "integration_connectors",
            "manual_distribution_records",
            "evidence_links",
            "traceability_bundles",
            "audit_events",
        )
        for table in expected_tables:
            self.assertIn(f"INSERT INTO {table}", executed_sql)
        self.assertIn("method_disclosure", executed_sql)
        audit_inserts = [params for sql, params in connection.calls if "INSERT INTO audit_events" in sql]
        self.assertTrue(any(params[1] == "api_browser_fidelity_checked" for params in audit_inserts))
        self.assertGreaterEqual(connection.commit_count, 8)
        first_answer_run_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_runs" in sql)
        self.assertEqual(str(first_answer_run_insert[0]), records[0].answer_run.id)
        first_analysis_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_analyses" in sql)
        self.assertEqual(str(first_analysis_insert[0]), analysis_result.analyses[0].id)
        self.assertEqual(len(str(first_analysis_insert[0])), 36)
        first_llm_call_insert = next(params for sql, params in connection.calls if "INSERT INTO llm_call_logs" in sql)
        self.assertEqual(str(first_llm_call_insert[2]), records[0].answer_run.id)
        self.assertEqual(first_llm_call_insert[3], "parser_judge")

    def test_postgres_repository_searches_runtime_knowledge_facts_with_pgvector(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        fact_id = "06975d61-853b-5a25-ae0e-b62bbfe82c15"
        fact_row = {
            "id": fact_id,
            "project_id": project_id,
            "market_code": "AU",
            "fact_type": "australian_shipping_policy",
            "subject": "ExampleBrand",
            "predicate": "supports_market",
            "object_value": "AU shipping and returns",
            "city": None,
            "evidence_source_id": "438ab927-5873-5516-8df3-47f6c75ef007",
            "confidence": 0.72,
            "status": "active",
            "valid_from": now,
            "valid_until": None,
            "embedding_model": "fixture-knowledge-embedding-v1",
            "vector_score": 0.91,
            "fallback_used": False,
        }
        audit_row = {
            "id": "425f980b-138f-4afa-8784-79d6f16f92ce",
            "event_type": "knowledge_fact_embeddings_indexed",
            "project_id": project_id,
            "actor_type": "system",
            "actor_id": "geno-core.knowledge",
            "target_type": "knowledge_fact_embedding_index",
            "target_id": project_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"knowledge_fact_ids": [fact_id]},
            "output_refs": {"knowledge_fact_embedding_ids": ["embedding-1"]},
            "method_version": "knowledge_fact_embedding_v1",
            "reason": "index localized knowledge facts into pgvector for runtime retrieval",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [fact_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).search_runtime_knowledge_facts(
            project_id=project_id,
            query="Australia shipping returns",
            market_code="AU",
            city="Sydney",
            limit=5,
            offset=0,
        )

        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].fact["fact_type"], "australian_shipping_policy")
        self.assertEqual(page.records[0].score, 0.91)
        self.assertFalse(page.records[0].fallback_used)
        self.assertEqual(page.audit_events[0]["event_type"], "knowledge_fact_embeddings_indexed")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("JOIN knowledge_fact_embeddings kfe ON kfe.knowledge_fact_id = kf.id", executed_sql)
        self.assertIn("kfe.embedding <=> %s::vector", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_vector_store_pgvector_and_qdrant_projection_keep_search_results_stable(self) -> None:
        bootstrap = build_au_project_bootstrap()
        facts = build_localized_knowledge_facts(
            project_id=bootstrap.project.id,
            market_code=bootstrap.project.market_code,
            brand=bootstrap.brand,
            category=bootstrap.project.category,
            answer_run_ids=("answer-run-1",),
            now=datetime(2026, 6, 11, tzinfo=UTC),
        )
        collection = f"knowledge_facts:{bootstrap.project.id}"
        ids = [fact.id for fact in facts]
        vectors = [list(embed_knowledge_text(knowledge_fact_text(fact))) for fact in facts]
        query_vector = list(embed_knowledge_text("Australia shipping returns local reviews"))
        pgvector_store = InMemoryPgVectorStore()
        qdrant_store = InMemoryQdrantVectorStore()

        self.assertIsInstance(pgvector_store, VectorStore)
        self.assertIsInstance(qdrant_store, VectorStore)
        pgvector_store.upsert(collection=collection, ids=ids, vectors=vectors)
        qdrant_store.upsert(collection=collection, ids=ids, vectors=vectors)

        pgvector_summary = summarize_vector_search(
            pgvector_store,
            collection=collection,
            vector=query_vector,
            limit=5,
        )
        qdrant_summary = summarize_vector_search(
            qdrant_store,
            collection=collection,
            vector=query_vector,
            limit=5,
        )
        self.assertEqual(pgvector_summary, qdrant_summary)
        self.assertEqual(len(pgvector_summary), 5)
        self.assertTrue(all(score <= 1.0 for _, score in pgvector_summary))

    def test_postgres_repository_persists_project_bootstrap_metadata(self) -> None:
        bootstrap = build_au_project_bootstrap()
        connection = RecordingConnection()

        PostgresEvidenceRepository(connection).save_project_bootstrap(bootstrap)

        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        expected_tables = (
            "market_profiles",
            "industry_profiles",
            "tenants",
            "projects",
            "project_members",
            "brand_entities",
            "competitor_entities",
            "prompt_questions",
            "audit_events",
        )
        for table in expected_tables:
            self.assertIn(f"INSERT INTO {table}", executed_sql)
        prompt_inserts = [params for sql, params in connection.calls if "INSERT INTO prompt_questions" in sql]
        competitor_inserts = [params for sql, params in connection.calls if "INSERT INTO competitor_entities" in sql]
        first_project_insert = next(params for sql, params in connection.calls if "INSERT INTO projects" in sql)
        first_prompt_insert = prompt_inserts[0]
        self.assertEqual(len(prompt_inserts), 100)
        self.assertEqual(len(competitor_inserts), 4)
        self.assertEqual(str(first_project_insert[0]), bootstrap.project.id)
        self.assertEqual(str(first_prompt_insert[0]), bootstrap.prompt_questions[0].id)
        self.assertEqual(first_prompt_insert[4], bootstrap.prompt_questions[0].text)
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_reads_runtime_project_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        tenant_id = "8330ea73-6914-5278-90cb-147f8369fed6"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": project_id,
                        "tenant_id": tenant_id,
                        "name": "AU DTC Evidence Pilot",
                        "market_code": "AU",
                        "industry_code": "dtc_ecommerce",
                        "target_brand": "ExampleBrand",
                        "category": "DTC ecommerce products",
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "status": "configured",
                        "created_at": now,
                    }
                ],
                {
                    "id": tenant_id,
                    "name": "Design Partner AU",
                    "slug": "design-partner-au",
                    "created_at": now,
                },
                {
                    "id": "a44c30bf-27e5-55ff-988e-cfe61130e2a9",
                    "project_id": project_id,
                    "canonical_name": "ExampleBrand",
                    "official_domains": [],
                    "parent_company": None,
                    "product_lines": [],
                    "status": "active",
                },
                [
                    {
                        "id": "78db4b2e-1bc6-5cd1-ab03-6a9243a0993c",
                        "project_id": project_id,
                        "canonical_name": "Ecosa",
                        "official_domains": [],
                        "parent_company": None,
                        "product_lines": [],
                        "status": "active",
                    }
                ],
                {"count": 100},
                [
                    {
                        "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
                        "event_type": "project_bootstrap_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.bootstrap",
                        "target_type": "project",
                        "target_id": project_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {},
                        "output_refs": {"prompt_question_ids": ["prompt-1"]},
                        "method_version": "m1_project_bootstrap_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_projects(
            market_code="AU",
            limit=10,
            offset=0,
        )

        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.project["id"], project_id)
        self.assertEqual(record.tenant["name"], "Design Partner AU")
        assert record.brand is not None
        self.assertEqual(record.brand["canonical_name"], "ExampleBrand")
        self.assertEqual(record.competitors[0]["canonical_name"], "Ecosa")
        self.assertEqual(record.prompt_count, 100)
        self.assertEqual(record.audit_events[0]["event_type"], "project_bootstrap_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM projects p WHERE p.market_code = %s AND p.status <> %s", executed_sql)
        self.assertIn("FROM tenants WHERE id = %s", executed_sql)
        self.assertIn("FROM prompt_questions WHERE project_id = %s", executed_sql)
        self.assertEqual(connection.calls[0][1], ("AU", "archived"))
        self.assertEqual(connection.calls[1][1], ("AU", "archived", 10, 0))

    def test_postgres_repository_filters_runtime_project_page_by_id(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(result_sets=[{"count": 0}, []])

        page = PostgresEvidenceRepository(connection).list_runtime_projects(
            project_id=project_id,
            market_code="AU",
            limit=10,
            offset=0,
        )

        self.assertEqual(page.total_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM projects p WHERE p.id = %s AND p.market_code = %s AND p.status <> %s", executed_sql)
        self.assertEqual(connection.calls[0][1], (UUID(project_id), "AU", "archived"))
        self.assertEqual(connection.calls[1][1], (UUID(project_id), "AU", "archived", 10, 0))

    def test_postgres_repository_filters_runtime_project_page_by_actor_membership(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(result_sets=[{"count": 0}, []])

        page = PostgresEvidenceRepository(connection).list_runtime_projects(
            project_id=project_id,
            market_code="AU",
            actor_id="agency-owner",
            limit=10,
            offset=0,
        )

        self.assertEqual(page.total_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_members pm", executed_sql)
        self.assertIn("pm.project_id = p.id AND pm.user_id = %s", executed_sql)
        self.assertEqual(connection.calls[0][1], (UUID(project_id), "AU", "archived", "agency-owner"))
        self.assertEqual(connection.calls[1][1], (UUID(project_id), "AU", "archived", "agency-owner", 10, 0))

    def test_postgres_repository_lists_archived_runtime_projects_when_requested(self) -> None:
        connection = RecordingConnection(result_sets=[{"count": 0}, []])

        page = PostgresEvidenceRepository(connection).list_runtime_projects(
            market_code="AU",
            status="archived",
            limit=10,
            offset=0,
        )

        self.assertEqual(page.total_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM projects p WHERE p.market_code = %s AND p.status = %s", executed_sql)
        self.assertNotIn("p.status <> %s", executed_sql)
        self.assertEqual(connection.calls[0][1], ("AU", "archived"))
        self.assertEqual(connection.calls[1][1], ("AU", "archived", 10, 0))

    def test_postgres_repository_updates_runtime_project_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        tenant_id = "8330ea73-6914-5278-90cb-147f8369fed6"
        before_project = {
            "id": project_id,
            "tenant_id": tenant_id,
            "name": "AU DTC Evidence Pilot",
            "market_code": "AU",
            "industry_code": "dtc_ecommerce",
            "target_brand": "ExampleBrand",
            "category": "DTC ecommerce products",
            "prompt_version": "au_dtc_ecommerce_v1",
            "status": "configured",
            "created_at": now,
        }
        after_project = {
            **before_project,
            "name": "Koala GEO Pilot",
            "target_brand": "Koala",
            "category": "mattresses",
            "status": "active",
        }
        connection = RecordingConnection(
            result_sets=[
                before_project,
                after_project,
                {
                    "id": tenant_id,
                    "name": "Design Partner AU",
                    "slug": "design-partner-au",
                    "created_at": now,
                },
                {
                    "id": "a44c30bf-27e5-55ff-988e-cfe61130e2a9",
                    "project_id": project_id,
                    "canonical_name": "Koala",
                    "official_domains": [],
                    "parent_company": None,
                    "product_lines": [],
                    "status": "active",
                },
                [],
                {"count": 100},
                [
                    {
                        "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
                        "event_type": "project_updated",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "agency-owner",
                        "target_type": "project",
                        "target_id": project_id,
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {"changed_fields": ["name", "target_brand", "category", "status"]},
                        "output_refs": {"project_ids": [project_id]},
                        "method_version": "runtime_project_update_v1",
                        "reason": "refresh client metadata",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).update_runtime_project(
            RuntimeProjectUpdateInput(
                project_id=project_id,
                name="Koala GEO Pilot",
                target_brand="Koala",
                category="mattresses",
                status="active",
                updated_by="agency-owner",
                reason="refresh client metadata",
            )
        )

        self.assertEqual(record.project["name"], "Koala GEO Pilot")
        self.assertEqual(record.project["target_brand"], "Koala")
        self.assertEqual(record.project["status"], "active")
        assert record.brand is not None
        self.assertEqual(record.brand["canonical_name"], "Koala")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT id, tenant_id, name, market_code, industry_code, target_brand", executed_sql)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("UPDATE projects SET name = %s, target_brand = %s, category = %s, status = %s", executed_sql)
        self.assertIn("UPDATE brand_entities SET canonical_name = %s WHERE project_id = %s", executed_sql)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "project_updated")
        self.assertEqual(audit_insert[11], "runtime_project_update_v1")
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_archives_runtime_project_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        tenant_id = "8330ea73-6914-5278-90cb-147f8369fed6"
        before_project = {
            "id": project_id,
            "tenant_id": tenant_id,
            "name": "AU DTC Evidence Pilot",
            "market_code": "AU",
            "industry_code": "dtc_ecommerce",
            "target_brand": "ExampleBrand",
            "category": "DTC ecommerce products",
            "prompt_version": "au_dtc_ecommerce_v1",
            "status": "active",
            "created_at": now,
        }
        after_project = {**before_project, "status": "archived"}
        connection = RecordingConnection(
            result_sets=[
                before_project,
                after_project,
                {
                    "id": tenant_id,
                    "name": "Design Partner AU",
                    "slug": "design-partner-au",
                    "created_at": now,
                },
                None,
                [],
                {"count": 100},
                [
                    {
                        "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
                        "event_type": "project_archived",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "agency-owner",
                        "target_type": "project",
                        "target_id": project_id,
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {"action": ["archive"]},
                        "output_refs": {"status": ["archived"]},
                        "method_version": "runtime_project_archive_v1",
                        "reason": "archive stale pilot",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).apply_runtime_project_action(
            RuntimeProjectActionInput(
                project_id=project_id,
                action="archive",
                updated_by="agency-owner",
                reason="archive stale pilot",
            )
        )

        self.assertEqual(record.project["status"], "archived")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("UPDATE projects SET status = %s WHERE id = %s", executed_sql)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "project_archived")
        self.assertEqual(audit_insert[11], "runtime_project_archive_v1")
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_restores_runtime_project_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        tenant_id = "8330ea73-6914-5278-90cb-147f8369fed6"
        before_project = {
            "id": project_id,
            "tenant_id": tenant_id,
            "name": "AU DTC Evidence Pilot",
            "market_code": "AU",
            "industry_code": "dtc_ecommerce",
            "target_brand": "ExampleBrand",
            "category": "DTC ecommerce products",
            "prompt_version": "au_dtc_ecommerce_v1",
            "status": "archived",
            "created_at": now,
        }
        after_project = {**before_project, "status": "paused"}
        connection = RecordingConnection(
            result_sets=[
                before_project,
                ({"status_before": ["paused"], "status_after": ["archived"]},),
                after_project,
                {
                    "id": tenant_id,
                    "name": "Design Partner AU",
                    "slug": "design-partner-au",
                    "created_at": now,
                },
                None,
                [],
                {"count": 100},
                [
                    {
                        "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
                        "event_type": "project_restored",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "agency-owner",
                        "target_type": "project",
                        "target_id": project_id,
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {"action": ["restore"]},
                        "output_refs": {"status": ["paused"]},
                        "method_version": "runtime_project_restore_v1",
                        "reason": "restore pilot",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).apply_runtime_project_action(
            RuntimeProjectActionInput(
                project_id=project_id,
                action="restore",
                updated_by="agency-owner",
                reason="restore pilot",
            )
        )

        self.assertEqual(record.project["status"], "paused")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("event_type = 'project_archived'", executed_sql)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "project_restored")
        self.assertEqual(audit_insert[11], "runtime_project_restore_v1")
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_restores_runtime_project_to_active_without_archive_audit(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        tenant_id = "8330ea73-6914-5278-90cb-147f8369fed6"
        before_project = {
            "id": project_id,
            "tenant_id": tenant_id,
            "name": "AU DTC Evidence Pilot",
            "market_code": "AU",
            "industry_code": "dtc_ecommerce",
            "target_brand": "ExampleBrand",
            "category": "DTC ecommerce products",
            "prompt_version": "au_dtc_ecommerce_v1",
            "status": "archived",
            "created_at": now,
        }
        after_project = {**before_project, "status": "active"}
        connection = RecordingConnection(
            result_sets=[
                before_project,
                None,
                after_project,
                {
                    "id": tenant_id,
                    "name": "Design Partner AU",
                    "slug": "design-partner-au",
                    "created_at": now,
                },
                None,
                [],
                {"count": 100},
                [],
            ]
        )

        record = PostgresEvidenceRepository(connection).apply_runtime_project_action(
            RuntimeProjectActionInput(
                project_id=project_id,
                action="restore",
                updated_by="agency-owner",
                reason="restore legacy archived pilot",
            )
        )

        self.assertEqual(record.project["status"], "active")
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "project_restored")
        self.assertEqual(audit_insert[11], "runtime_project_restore_v1")

    def test_postgres_repository_lists_runtime_project_lifecycle_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        archive_audit = {
            "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
            "event_type": "project_archived",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-owner",
            "target_type": "project",
            "target_id": project_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "project_ids": [project_id],
                "action": ["archive"],
                "status_before": ["paused"],
                "status_after": ["archived"],
            },
            "output_refs": {"project_ids": [project_id], "status": ["archived"]},
            "method_version": "runtime_project_archive_v1",
            "reason": "archive stale pilot",
            "created_at": now,
        }
        update_audit = {
            **archive_audit,
            "id": "23a979b2-e258-4847-92e7-9a0d6e5e9777",
            "event_type": "project_updated",
            "input_refs": {"project_ids": [project_id], "changed_fields": ["name", "status"]},
            "output_refs": {"project_ids": [project_id], "status": ["paused"]},
            "method_version": "runtime_project_update_v1",
            "reason": "pause client project",
        }
        connection = RecordingConnection(result_sets=[{"count": 2}, [archive_audit, update_audit]])

        page = PostgresEvidenceRepository(connection).list_runtime_project_lifecycle_events(
            project_id=project_id,
            limit=5,
            offset=1,
        )

        self.assertIsInstance(page, RuntimeProjectLifecycleEventPage)
        self.assertEqual(page.total_count, 2)
        self.assertEqual(page.records[0].lifecycle_event["event_type"], "project_archived")
        self.assertEqual(page.records[0].lifecycle_event["action"], "archive")
        self.assertEqual(page.records[0].lifecycle_event["status_before"], "paused")
        self.assertEqual(page.records[0].lifecycle_event["status_after"], "archived")
        self.assertEqual(page.records[1].lifecycle_event["changed_fields"], ["name", "status"])
        self.assertEqual(page.records[1].audit_events[0]["method_version"], "runtime_project_update_v1")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM audit_events", executed_sql)
        self.assertIn("event_type = ANY", executed_sql)
        self.assertEqual(connection.calls[0][1], (UUID(project_id), list(("project_bootstrap_created", "project_updated", "project_archived", "project_restored"))))
        self.assertEqual(
            connection.calls[1][1],
            (UUID(project_id), list(("project_bootstrap_created", "project_updated", "project_archived", "project_restored")), 5, 1),
        )

    def test_postgres_repository_exports_runtime_project_lifecycle_events_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        audit_row = {
            "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
            "event_type": "project_archived",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-owner",
            "target_type": "project",
            "target_id": project_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "project_ids": [project_id],
                "action": ["archive"],
                "status_before": ["paused"],
                "status_after": ["archived"],
                "changed_fields": ["status"],
            },
            "output_refs": {"project_ids": [project_id], "status": ["archived"]},
            "method_version": "runtime_project_archive_v1",
            "reason": "archive stale pilot",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [audit_row]])

        export = PostgresEvidenceRepository(connection).export_runtime_project_lifecycle_events_csv(
            project_id=project_id,
            limit=10,
            offset=0,
        )

        self.assertIsInstance(export, RuntimeProjectLifecycleEventExport)
        self.assertEqual(export.export_type, "runtime_project_lifecycle_events_csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.method_version, "runtime_project_lifecycle_export_v1")
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.total_count, 1)
        self.assertIn("audit_event_id,project_id,event_type", str(export.content))
        self.assertIn("project_archived", str(export.content))
        self.assertIn("archive stale pilot", str(export.content))
        self.assertIn("status", str(export.content))
        self.assertEqual(export.content_hash, hashlib.sha256(str(export.content).encode("utf-8")).hexdigest())
        self.assertEqual(
            connection.calls[1][1],
            (UUID(project_id), list(("project_bootstrap_created", "project_updated", "project_archived", "project_restored")), 10, 0),
        )

    def test_postgres_repository_lists_runtime_audit_events_with_filters(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        audit_row = {
            "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
            "event_type": "runtime_prompts_imported",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-owner",
            "target_type": "prompt_import",
            "target_id": "prompt-import-1",
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"source_filename": ["prompts.csv"]},
            "output_refs": {"prompt_question_ids": ["prompt-1"]},
            "method_version": "runtime_prompt_import_csv_v1",
            "reason": "import prompts",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_audit_events(
            project_id=project_id,
            event_type="runtime_prompts_imported",
            target_type="prompt_import",
            actor_id="agency-owner",
            limit=10,
            offset=2,
        )

        self.assertIsInstance(page, RuntimeAuditEventPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.filters["project_id"], project_id)
        self.assertEqual(page.filters["event_type"], "runtime_prompts_imported")
        self.assertEqual(page.records[0].audit_event["method_version"], "runtime_prompt_import_csv_v1")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM audit_events", executed_sql)
        self.assertIn("event_type = %s", executed_sql)
        self.assertIn("target_type = %s", executed_sql)
        self.assertIn("actor_id = %s", executed_sql)
        self.assertEqual(
            connection.calls[1][1],
            (UUID(project_id), "runtime_prompts_imported", "prompt_import", "agency-owner", 10, 2),
        )

    def test_postgres_repository_exports_runtime_audit_events_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        audit_row = {
            "id": "7f28023e-977f-4c14-9007-95e7e84db71a",
            "event_type": "runtime_prompts_imported",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-owner",
            "target_type": "prompt_import",
            "target_id": "prompt-import-1",
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"source_filename": ["prompts.csv"]},
            "output_refs": {"prompt_question_ids": ["prompt-1"]},
            "method_version": "runtime_prompt_import_csv_v1",
            "reason": "import prompts",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [audit_row]])

        export = PostgresEvidenceRepository(connection).export_runtime_audit_events_csv(
            project_id=project_id,
            event_type="runtime_prompts_imported",
            limit=10,
            offset=0,
        )

        self.assertIsInstance(export, RuntimeAuditEventExport)
        self.assertEqual(export.export_type, "runtime_audit_events_csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.method_version, "runtime_audit_events_export_v1")
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertIn("audit_event_id,project_id,event_type", str(export.content))
        self.assertIn("runtime_prompts_imported", str(export.content))
        self.assertIn("source_filename", str(export.content))
        self.assertIn("prompt_question_ids", str(export.content))
        self.assertEqual(export.content_hash, hashlib.sha256(str(export.content).encode("utf-8")).hexdigest())

    def test_postgres_repository_checks_project_membership(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(result_sets=[{"?column?": 1}])

        can_access = PostgresEvidenceRepository(connection).user_can_access_project(
            project_id=project_id,
            actor_id="agency-owner",
        )

        self.assertTrue(can_access)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_members", executed_sql)
        self.assertEqual(connection.calls[0][1], (UUID(project_id), "agency-owner"))

    def test_postgres_repository_sets_runtime_project_access_context(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection()

        PostgresEvidenceRepository(connection).set_runtime_project_access_context(
            actor_id="agency-owner",
            project_id=project_id,
        )

        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("set_config", executed_sql)
        self.assertIn("set_config(%s, %s, false)", executed_sql)
        self.assertEqual(
            connection.calls[0][1],
                (
                    "geno.runtime_project_access_control",
                    "1",
                    "geno.runtime_actor_id",
                    "agency-owner",
                    "geno.runtime_project_id",
                    project_id,
                ),
        )

    def test_postgres_repository_sets_runtime_invitation_accept_context(self) -> None:
        connection = RecordingConnection()

        PostgresEvidenceRepository(connection).set_runtime_project_invitation_accept_context(
            invite_token_hash="token-hash",
        )

        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("set_config", executed_sql)
        self.assertEqual(
            connection.calls[0][1],
            (
                "geno.runtime_project_access_control",
                "1",
                "geno.runtime_actor_id",
                "",
                "geno.runtime_project_id",
                "",
                "geno.runtime_invitation_token_hash",
                "token-hash",
            ),
        )

    def test_postgres_repository_reads_project_member_role(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(result_sets=[{"role": "admin"}])

        role = PostgresEvidenceRepository(connection).get_project_member_role(
            project_id=project_id,
            actor_id="agency-admin",
        )

        self.assertEqual(role, "admin")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT role FROM project_members", executed_sql)
        self.assertEqual(connection.calls[0][1], (UUID(project_id), "agency-admin"))

    def test_postgres_repository_returns_none_for_missing_project_member_role(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(result_sets=[None])

        role = PostgresEvidenceRepository(connection).get_project_member_role(
            project_id=project_id,
            actor_id="missing-user",
        )

        self.assertIsNone(role)

    def test_postgres_repository_lists_runtime_project_members_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        member_id = "d83a98ab-57c1-52e8-90b9-8c488f263e48"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": member_id,
                        "project_id": project_id,
                        "user_id": "analyst@example.com",
                        "role": "analyst",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
                        "event_type": "project_member_saved",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "agency-owner",
                        "target_type": "project_member",
                        "target_id": member_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"project_ids": [project_id], "user_ids": ["analyst@example.com"]},
                        "output_refs": {"project_member_ids": [member_id]},
                        "method_version": "project_member_v1",
                        "reason": "add analyst",
                        "created_at": now,
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_project_members(
            project_id=project_id,
            limit=10,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeProjectMemberPage)
        self.assertEqual(page.total_count, 1)
        self.assertIsInstance(page.records[0], RuntimeProjectMember)
        self.assertEqual(page.records[0].member["user_id"], "analyst@example.com")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "project_member_saved")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_members WHERE project_id = %s", executed_sql)
        self.assertIn("target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_exports_runtime_project_members_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        member_id = "d83a98ab-57c1-52e8-90b9-8c488f263e48"
        user_id = "owner@example.com"
        audit_row = {
            "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
            "event_type": "project_member_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-owner",
            "target_type": "project_member",
            "target_id": member_id,
            "before_hash": None,
            "after_hash": "member-after-hash",
            "input_refs": {"project_ids": [project_id], "user_ids": [user_id]},
            "output_refs": {"project_member_ids": [member_id]},
            "method_version": "project_member_v1",
            "reason": "add owner",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": member_id,
                        "project_id": project_id,
                        "user_id": user_id,
                        "role": "owner",
                        "created_at": now,
                    }
                ],
                [audit_row],
            ]
        )

        export = PostgresEvidenceRepository(connection).export_runtime_project_members_csv(
            project_id=project_id,
            limit=5,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_project_members_csv")
        self.assertEqual(export.filename, "runtime-project-members.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertIn("member_id,project_id,user_id_hash,role,created_at", export.content)
        self.assertIn(member_id, export.content)
        self.assertIn("owner", export.content)
        self.assertIn(_artifact_hash(user_id), export.content)
        self.assertIn("project_member_v1", export.content)
        self.assertIn("member-after-hash", export.content)
        self.assertNotIn(user_id, export.content)

    def test_postgres_repository_saves_runtime_project_member_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                None,
                {
                    "id": "d83a98ab-57c1-52e8-90b9-8c488f263e48",
                    "project_id": project_id,
                    "user_id": "analyst@example.com",
                    "role": "analyst",
                    "created_at": now,
                },
            ]
        )

        record = PostgresEvidenceRepository(connection).save_runtime_project_member(
            RuntimeProjectMemberInput(
                project_id=project_id,
                user_id="analyst@example.com",
                role="analyst",
                updated_by="agency-owner",
                reason="add analyst",
            )
        )

        self.assertIsInstance(record, RuntimeProjectMember)
        self.assertEqual(record.member["user_id"], "analyst@example.com")
        self.assertEqual(record.member["role"], "analyst")
        self.assertEqual(record.audit_events[0]["event_type"], "project_member_saved")
        self.assertEqual(record.audit_events[0]["actor_id"], "agency-owner")
        self.assertEqual(record.audit_events[0]["method_version"], "project_member_v1")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO project_members", executed_sql)
        self.assertIn("ON CONFLICT (project_id, user_id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_deletes_runtime_project_member_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": "d83a98ab-57c1-52e8-90b9-8c488f263e48",
                    "project_id": project_id,
                    "user_id": "viewer@example.com",
                    "role": "viewer",
                    "created_at": now,
                },
            ]
        )

        record = PostgresEvidenceRepository(connection).delete_runtime_project_member(
            RuntimeProjectMemberDeleteInput(
                project_id=project_id,
                user_id="viewer@example.com",
                deleted_by="agency-owner",
                reason="remove viewer",
            )
        )

        self.assertIsInstance(record, RuntimeProjectMember)
        self.assertEqual(record.member["user_id"], "viewer@example.com")
        self.assertEqual(record.audit_events[0]["event_type"], "project_member_deleted")
        self.assertEqual(record.audit_events[0]["actor_id"], "agency-owner")
        self.assertEqual(record.audit_events[0]["method_version"], "project_member_delete_v1")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("DELETE FROM project_members", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_blocks_deleting_last_project_owner(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": "d83a98ab-57c1-52e8-90b9-8c488f263e48",
                    "project_id": project_id,
                    "user_id": "owner@example.com",
                    "role": "owner",
                    "created_at": now,
                },
                {"count": 0},
            ]
        )

        with self.assertRaisesRegex(ValueError, "last project owner"):
            PostgresEvidenceRepository(connection).delete_runtime_project_member(
                RuntimeProjectMemberDeleteInput(
                    project_id=project_id,
                    user_id="owner@example.com",
                    deleted_by="agency-owner",
                )
            )

        self.assertEqual(connection.commit_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("role = %s AND user_id <> %s", executed_sql)
        self.assertNotIn("DELETE FROM project_members", executed_sql)

    def test_postgres_repository_blocks_downgrading_last_project_owner(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                {
                    "id": "d83a98ab-57c1-52e8-90b9-8c488f263e48",
                    "project_id": project_id,
                    "user_id": "owner@example.com",
                    "role": "owner",
                    "created_at": now,
                },
                {"count": 0},
            ]
        )

        with self.assertRaisesRegex(ValueError, "last project owner"):
            PostgresEvidenceRepository(connection).save_runtime_project_member(
                RuntimeProjectMemberInput(
                    project_id=project_id,
                    user_id="owner@example.com",
                    role="admin",
                    updated_by="agency-owner",
                )
            )

        self.assertEqual(connection.commit_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("role = %s AND user_id <> %s", executed_sql)
        self.assertNotIn("ON CONFLICT (project_id, user_id) DO UPDATE", executed_sql)

    def test_postgres_repository_lists_runtime_project_member_invitations_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": invitation_id,
                        "project_id": project_id,
                        "email": "viewer@example.com",
                        "role": "viewer",
                        "status": "pending",
                        "invite_token_hash": "hash",
                        "invited_by": "agency-owner",
                        "expires_at": now + timedelta(days=7),
                        "accepted_at": None,
                        "revoked_at": None,
                        "metadata": {"source": "runtime-console"},
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
                [
                    {
                        "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
                        "event_type": "project_member_invitation_created",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "agency-owner",
                        "target_type": "project_member_invitation",
                        "target_id": invitation_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"project_ids": [project_id], "emails": ["viewer@example.com"]},
                        "output_refs": {"project_member_invitation_ids": [invitation_id]},
                        "method_version": "project_member_invitation_v1",
                        "reason": "invite viewer",
                        "created_at": now,
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_project_member_invitations(
            project_id=project_id,
            status="pending",
            limit=10,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeProjectMemberInvitationPage)
        self.assertEqual(page.total_count, 1)
        self.assertIsInstance(page.records[0], RuntimeProjectMemberInvitation)
        self.assertEqual(page.records[0].invitation["email"], "viewer@example.com")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "project_member_invitation_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_member_invitations WHERE project_id = %s AND status = %s", executed_sql)
        self.assertIn("target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_exports_runtime_project_member_invitations_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        email = "viewer@example.com"
        invited_by = "agency-owner"
        token_hash = "stored-invite-token-hash"
        audit_row = {
            "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
            "event_type": "project_member_invitation_created",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": invited_by,
            "target_type": "project_member_invitation",
            "target_id": invitation_id,
            "before_hash": None,
            "after_hash": "invitation-after-hash",
            "input_refs": {"project_ids": [project_id], "emails": [email]},
            "output_refs": {"project_member_invitation_ids": [invitation_id]},
            "method_version": "project_member_invitation_v1",
            "reason": "invite viewer",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": invitation_id,
                        "project_id": project_id,
                        "email": email,
                        "role": "viewer",
                        "status": "pending",
                        "invite_token_hash": token_hash,
                        "invited_by": invited_by,
                        "expires_at": now + timedelta(days=7),
                        "accepted_at": None,
                        "revoked_at": None,
                        "metadata": {"source": "runtime-console"},
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
                [audit_row],
            ]
        )

        export = PostgresEvidenceRepository(connection).export_runtime_project_member_invitations_csv(
            project_id=project_id,
            status="pending",
            limit=5,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_project_member_invitations_csv")
        self.assertEqual(export.filename, "runtime-project-member-invitations.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["status"], "pending")
        self.assertIn("invitation_id,project_id,email_hash,role,status", export.content)
        self.assertIn(invitation_id, export.content)
        self.assertIn("viewer", export.content)
        self.assertIn("pending", export.content)
        self.assertIn("True", export.content)
        self.assertIn(_artifact_hash(email), export.content)
        self.assertIn(_artifact_hash(invited_by), export.content)
        self.assertIn("project_member_invitation_v1", export.content)
        self.assertIn("invitation-after-hash", export.content)
        self.assertNotIn(email, export.content)
        self.assertNotIn(invited_by, export.content)
        self.assertNotIn(token_hash, export.content)

    def test_postgres_repository_creates_runtime_project_member_invitation_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        expires_at = now + timedelta(days=7)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                None,
                {
                    "id": invitation_id,
                    "project_id": project_id,
                    "email": "viewer@example.com",
                    "role": "viewer",
                    "status": "pending",
                    "invite_token_hash": "hash",
                    "invited_by": "agency-owner",
                    "expires_at": expires_at,
                    "accepted_at": None,
                    "revoked_at": None,
                    "metadata": {"source": "runtime-console"},
                    "created_at": now,
                    "updated_at": now,
                },
            ]
        )

        record = PostgresEvidenceRepository(connection).create_runtime_project_member_invitation(
            RuntimeProjectMemberInvitationInput(
                project_id=project_id,
                email="Viewer@Example.com",
                role="viewer",
                invited_by="agency-owner",
                expires_at=expires_at,
                metadata={"source": "runtime-console"},
                reason="invite viewer",
            )
        )

        self.assertIsInstance(record, RuntimeProjectMemberInvitation)
        self.assertEqual(record.invitation["email"], "viewer@example.com")
        self.assertEqual(record.invitation["role"], "viewer")
        self.assertEqual(record.invitation["status"], "pending")
        self.assertIn("invite_token", record.invitation)
        self.assertEqual(
            hashlib.sha256(record.invitation["invite_token"].encode("utf-8")).hexdigest(),
            record.audit_events[0]["output_refs"]["invite_token_hashes"][0],
        )
        self.assertEqual(record.audit_events[0]["event_type"], "project_member_invitation_created")
        self.assertEqual(record.audit_events[0]["actor_id"], "agency-owner")
        self.assertEqual(record.audit_events[0]["method_version"], "project_member_invitation_v1")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO project_member_invitations", executed_sql)
        self.assertIn("ON CONFLICT (project_id, email, role, status) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        insert_params = next(params for sql, params in connection.calls if "INSERT INTO project_member_invitations" in sql)
        old_stable_id = uuid5(
            NAMESPACE_URL,
            "geno:project-member-invitation:"
            f"{project_id}:viewer@example.com:viewer:pending",
        )
        self.assertNotEqual(str(insert_params[0]), str(old_stable_id))

    def test_postgres_repository_revokes_runtime_project_member_invitation_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        pending_invitation = {
            "id": invitation_id,
            "project_id": project_id,
            "email": "viewer@example.com",
            "role": "viewer",
            "status": "pending",
            "invite_token_hash": "hash",
            "invited_by": "agency-owner",
            "expires_at": now + timedelta(days=7),
            "accepted_at": None,
            "revoked_at": None,
            "metadata": {"source": "runtime-console"},
            "created_at": now,
            "updated_at": now,
        }
        revoked_invitation = {
            **pending_invitation,
            "status": "revoked",
            "revoked_at": now,
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[pending_invitation, revoked_invitation])

        record = PostgresEvidenceRepository(connection).apply_runtime_project_member_invitation_action(
            RuntimeProjectMemberInvitationActionInput(
                project_id=project_id,
                invitation_id=invitation_id,
                action="revoke",
                updated_by="agency-admin",
                reason="wrong email",
            )
        )

        self.assertEqual(record.invitation["status"], "revoked")
        self.assertEqual(record.audit_events[0]["event_type"], "project_member_invitation_revoked")
        self.assertEqual(record.audit_events[0]["actor_id"], "agency-admin")
        self.assertEqual(record.audit_events[0]["method_version"], "project_member_invitation_action_v1")
        self.assertEqual(record.audit_events[0]["input_refs"]["actions"], ["revoke"])
        self.assertEqual(record.audit_events[0]["output_refs"]["status"], ["revoked"])
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("UPDATE project_member_invitations SET status = %s, revoked_at = now()", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_expires_runtime_project_member_invitation_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        pending_invitation = {
            "id": invitation_id,
            "project_id": project_id,
            "email": "viewer@example.com",
            "role": "viewer",
            "status": "pending",
            "invite_token_hash": "hash",
            "invited_by": "agency-owner",
            "expires_at": now - timedelta(days=1),
            "accepted_at": None,
            "revoked_at": None,
            "metadata": {"source": "runtime-console"},
            "created_at": now - timedelta(days=8),
            "updated_at": now,
        }
        expired_invitation = {
            **pending_invitation,
            "status": "expired",
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[pending_invitation, expired_invitation])

        record = PostgresEvidenceRepository(connection).apply_runtime_project_member_invitation_action(
            RuntimeProjectMemberInvitationActionInput(
                project_id=project_id,
                invitation_id=invitation_id,
                action="expire",
                updated_by="agency-admin",
                reason="past validity window",
            )
        )

        self.assertEqual(record.invitation["status"], "expired")
        self.assertEqual(record.audit_events[0]["event_type"], "project_member_invitation_expired")
        self.assertEqual(record.audit_events[0]["input_refs"]["actions"], ["expire"])
        self.assertEqual(record.audit_events[0]["output_refs"]["status"], ["expired"])
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("UPDATE project_member_invitations SET status = %s, updated_at = now()", executed_sql)

    def test_postgres_repository_rejects_project_member_invitation_action_for_non_pending_status(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": invitation_id,
                    "project_id": project_id,
                    "email": "viewer@example.com",
                    "role": "viewer",
                    "status": "revoked",
                    "invite_token_hash": "hash",
                    "invited_by": "agency-owner",
                    "expires_at": now + timedelta(days=7),
                    "accepted_at": None,
                    "revoked_at": now,
                    "metadata": {"source": "runtime-console"},
                    "created_at": now,
                    "updated_at": now,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "cannot revoke invitation with status revoked"):
            PostgresEvidenceRepository(connection).apply_runtime_project_member_invitation_action(
                RuntimeProjectMemberInvitationActionInput(
                    project_id=project_id,
                    invitation_id=invitation_id,
                    action="revoke",
                    updated_by="agency-admin",
                )
            )

        self.assertEqual(connection.commit_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertNotIn("UPDATE project_member_invitations SET status", executed_sql)

    def test_postgres_repository_accepts_runtime_project_member_invitation_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        invite_token = "geno-invite-token"
        invite_token_hash = hashlib.sha256(invite_token.encode("utf-8")).hexdigest()
        pending_invitation = {
            "id": invitation_id,
            "project_id": project_id,
            "email": "viewer@example.com",
            "role": "viewer",
            "status": "pending",
            "invite_token_hash": invite_token_hash,
            "invited_by": "agency-owner",
            "expires_at": now + timedelta(days=7),
            "accepted_at": None,
            "revoked_at": None,
            "metadata": {"source": "runtime-console"},
            "created_at": now,
            "updated_at": now,
        }
        member_id = str(uuid5(NAMESPACE_URL, f"geno:project-member:{project_id}:viewer@example.com"))
        saved_member = {
            "id": member_id,
            "project_id": project_id,
            "user_id": "viewer@example.com",
            "role": "viewer",
            "created_at": now,
        }
        accepted_invitation = {
            **pending_invitation,
            "status": "accepted",
            "accepted_at": now,
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[pending_invitation, None, saved_member, accepted_invitation])

        record = PostgresEvidenceRepository(connection).accept_runtime_project_member_invitation(
            RuntimeProjectMemberInvitationAcceptInput(
                invitation_id=invitation_id,
                invite_token=invite_token,
                accepted_by="viewer@example.com",
                reason="accept invite",
            )
        )

        self.assertEqual(record.invitation["status"], "accepted")
        self.assertEqual(record.invitation["member"]["user_id"], "viewer@example.com")
        self.assertEqual(
            [event["event_type"] for event in record.audit_events],
            ["project_member_saved", "project_member_invitation_accepted"],
        )
        self.assertEqual(record.audit_events[1]["method_version"], "project_member_invitation_accept_v1")
        self.assertNotIn("geno-invite-token", str(record.audit_events))
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("WHERE id = %s AND invite_token_hash = %s FOR UPDATE", executed_sql)
        self.assertIn("INSERT INTO project_members", executed_sql)
        self.assertIn("UPDATE project_member_invitations SET status = %s, accepted_at = now()", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_sends_runtime_project_member_invitation_email_without_auditing_raw_token(
        self,
    ) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        invite_token = "geno-invite-token"
        invite_token_hash = hashlib.sha256(invite_token.encode("utf-8")).hexdigest()
        pending_invitation = {
            "id": invitation_id,
            "project_id": project_id,
            "email": "viewer@example.com",
            "role": "viewer",
            "status": "pending",
            "invite_token_hash": invite_token_hash,
            "invited_by": "agency-owner",
            "expires_at": now + timedelta(days=7),
            "accepted_at": None,
            "revoked_at": None,
            "metadata": {"source": "runtime-console"},
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
            "event_type": "project_member_invitation_email_sent",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-owner",
            "target_type": "project_member_invitation",
            "target_id": invitation_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "project_member_invitation_ids": [invitation_id],
                "invite_token_hashes": [invite_token_hash],
            },
            "output_refs": {"delivery_status": ["sent"]},
            "method_version": "project_member_invitation_email_v1",
            "reason": "send invite email",
            "created_at": now,
        }
        sent: list[tuple[dict[str, object], object, list[str]]] = []

        def email_sender(config: dict[str, object], message: object, recipients: list[str]) -> tuple[int, bytes]:
            sent.append((config, message, recipients))
            return 250, b"queued"

        connection = RecordingConnection(result_sets=[pending_invitation, [audit_row]])
        with patch.dict(
            "os.environ",
            {
                "GENO_TEST_SMTP_HOST": "smtp.example.com",
                "GENO_TEST_SMTP_PORT": "2525",
                "GENO_TEST_SMTP_TLS": "0",
                "GENO_TEST_SMTP_FROM": "invites@example.com",
            },
        ):
            record = PostgresEvidenceRepository(connection, email_sender=email_sender).send_runtime_project_member_invitation_email(
                RuntimeProjectMemberInvitationEmailInput(
                    project_id=project_id,
                    invitation_id=invitation_id,
                    invite_token=invite_token,
                    accept_base_url="https://app.example.com/invite/accept",
                    sent_by="agency-owner",
                    smtp_env_prefix="GENO_TEST_SMTP",
                    subject="Join GENO",
                    message="Please join the workspace.",
                    reason="send invite email",
                )
            )

        self.assertEqual(record.invitation["status"], "pending")
        self.assertEqual(record.audit_events[0]["event_type"], "project_member_invitation_email_sent")
        self.assertEqual(sent[0][2], ["viewer@example.com"])
        self.assertIn(invite_token, sent[0][1].get_content())
        self.assertEqual(sent[0][1]["Subject"], "Join GENO")
        self.assertEqual(sent[0][1]["X-GENO-Email-Template-Version"], PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE_VERSION)
        self.assertNotIn(invite_token, str(record.audit_events))
        self.assertIn(invite_token_hash, str(record.audit_events))
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("WHERE project_id = %s AND id = %s AND invite_token_hash = %s FOR UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        audit_params = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertNotIn(invite_token, str(audit_params))
        self.assertNotIn("https://app.example.com/invite/accept?", str(audit_params))
        rendered_email = render_project_member_invitation_email(
            role="viewer",
            invitation_id=invitation_id,
            expires_at=pending_invitation["expires_at"].isoformat(),
            accept_url=f"https://app.example.com/invite/accept?invitation_id={invitation_id}&invite_token={invite_token}",
            subject="Join GENO",
            message="Please join the workspace.",
        )
        self.assertIn(PROJECT_MEMBER_INVITATION_EMAIL_TEMPLATE_VERSION, str(audit_params))
        self.assertIn("email_template_hashes", str(audit_params))
        self.assertIn("email_subject_hashes", str(audit_params))
        self.assertIn("email_body_hashes", str(audit_params))
        self.assertIn(rendered_email.subject_hash, str(audit_params))
        self.assertIn(rendered_email.body_hash, str(audit_params))

    def test_postgres_repository_rejects_invitation_email_for_non_pending_status(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        invite_token = "geno-invite-token"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": invitation_id,
                    "project_id": "6624961f-36ae-539b-9d48-51619b42e37e",
                    "email": "viewer@example.com",
                    "role": "viewer",
                    "status": "accepted",
                    "invite_token_hash": hashlib.sha256(invite_token.encode("utf-8")).hexdigest(),
                    "invited_by": "agency-owner",
                    "expires_at": now + timedelta(days=7),
                    "accepted_at": now,
                    "revoked_at": None,
                    "metadata": {"source": "runtime-console"},
                    "created_at": now,
                    "updated_at": now,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "cannot email invitation with status accepted"):
            PostgresEvidenceRepository(connection).send_runtime_project_member_invitation_email(
                RuntimeProjectMemberInvitationEmailInput(
                    project_id="6624961f-36ae-539b-9d48-51619b42e37e",
                    invitation_id=invitation_id,
                    invite_token=invite_token,
                    accept_base_url="https://app.example.com/invite/accept",
                )
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(len([sql for sql, _ in connection.calls if "INSERT INTO audit_events" in sql]), 0)

    def test_postgres_repository_rejects_expired_runtime_project_member_invitation_acceptance(self) -> None:
        now = datetime.now(UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        invitation_id = "21a98a17-7930-5504-a6fa-cd08990fbf07"
        invite_token = "geno-invite-token"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": invitation_id,
                    "project_id": project_id,
                    "email": "viewer@example.com",
                    "role": "viewer",
                    "status": "pending",
                    "invite_token_hash": hashlib.sha256(invite_token.encode("utf-8")).hexdigest(),
                    "invited_by": "agency-owner",
                    "expires_at": now - timedelta(seconds=1),
                    "accepted_at": None,
                    "revoked_at": None,
                    "metadata": {"source": "runtime-console"},
                    "created_at": now - timedelta(days=7),
                    "updated_at": now,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "project member invitation expired"):
            PostgresEvidenceRepository(connection).accept_runtime_project_member_invitation(
                RuntimeProjectMemberInvitationAcceptInput(
                    invitation_id=invitation_id,
                    invite_token=invite_token,
                )
            )

        self.assertEqual(connection.commit_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertNotIn("INSERT INTO project_members", executed_sql)

    def test_postgres_repository_reads_runtime_prompt_page(self) -> None:
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        prompt_id = "5b9615f3-533b-5f18-96fb-5c8cbcb934c1"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": prompt_id,
                        "project_id": project_id,
                        "market_code": "AU",
                        "industry_code": "dtc_ecommerce",
                        "text": "Is ExampleBrand good in Australia?",
                        "intent_type": "brand_awareness",
                        "city": "Australia",
                        "language": "en-AU",
                        "target_brand": "ExampleBrand",
                        "competitors": ["Emma Sleep", "Sleeping Duck", "Ecosa", "IKEA Australia"],
                        "priority": 1,
                        "intent_weight": 0.9,
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "status": "active",
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_prompts(
            project_id=project_id,
            intent_type="brand_awareness",
            city="Australia",
            status="active",
            limit=10,
            offset=0,
        )

        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0]["id"], prompt_id)
        self.assertEqual(page.records[0]["text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(page.records[0]["competitors"][0], "Emma Sleep")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM prompt_questions WHERE project_id = %s", executed_sql)
        self.assertIn("intent_type = %s", executed_sql)
        self.assertIn("ORDER BY priority ASC, id ASC", executed_sql)

    def test_postgres_repository_imports_runtime_prompts_csv_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        prompt_id = "c5070b70-1c9b-55a1-aad1-457ed04b9707"
        audit_id = "f858da95-fb57-4086-9fa2-eac9e13c0d19"
        imported_prompt_row = {
            "id": prompt_id,
            "project_id": project_id,
            "market_code": "AU",
            "industry_code": "dtc_ecommerce",
            "text": "Is ExampleBrand visible in Sydney AI recommendations?",
            "intent_type": "brand_awareness",
            "city": "Sydney",
            "language": "en-AU",
            "target_brand": "ExampleBrand",
            "competitors": ["Emma Sleep", "Sleeping Duck", "Ecosa"],
            "priority": 1,
            "intent_weight": 0.9,
            "prompt_version": "au_dtc_ecommerce_v1_imported",
            "status": "active",
        }
        audit_row = {
            "id": audit_id,
            "event_type": "runtime_prompts_imported",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "prompt_import",
            "target_id": "prompt-import-1",
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "csv_sha256": "hash",
                "source_format": "xlsx",
                "source_filename": "prompts.xlsx",
                "source_content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            "output_refs": {"prompt_question_ids": [prompt_id]},
            "method_version": "runtime_prompt_import_xlsx_v1",
            "reason": "import runtime prompts from xlsx",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": project_id,
                    "market_code": "AU",
                    "industry_code": "dtc_ecommerce",
                    "target_brand": "ExampleBrand",
                    "prompt_version": "au_dtc_ecommerce_v1",
                },
                [
                    {"canonical_name": "Emma Sleep"},
                    {"canonical_name": "Sleeping Duck"},
                    {"canonical_name": "Ecosa"},
                ],
                imported_prompt_row,
                [audit_row],
            ]
        )
        result = PostgresEvidenceRepository(connection).import_runtime_prompts_csv(
            RuntimePromptImportInput(
                project_id=project_id,
                csv_content=(
                    "text,intent_type,city,priority,intent_weight,prompt_version\n"
                    "Is ExampleBrand visible in Sydney AI recommendations?,brand_awareness,Sydney,1,0.9,au_dtc_ecommerce_v1_imported\n"
                ),
                imported_by="runtime-console",
                source_filename="prompts.xlsx",
                source_format="xlsx",
                source_content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )
        self.assertIsInstance(result, RuntimePromptImportResult)
        self.assertEqual(result.prompt_import["prompt_count"], 1)
        self.assertEqual(result.prompt_import["source_format"], "xlsx")
        self.assertEqual(result.prompt_import["source_filename"], "prompts.xlsx")
        self.assertEqual(result.prompts[0]["text"], "Is ExampleBrand visible in Sydney AI recommendations?")
        self.assertEqual(result.audit_events[0]["event_type"], "runtime_prompts_imported")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO prompt_questions", executed_sql)
        self.assertIn("ON CONFLICT (id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_runtime_prompt_import_history(self) -> None:
        now = datetime(2026, 6, 11, tzinfo=UTC)
        project_id = "6624961f-36ae-539b-9d48-51619b42e37e"
        audit_id = "f858da95-fb57-4086-9fa2-eac9e13c0d19"
        prompt_id = "c5070b70-1c9b-55a1-aad1-457ed04b9707"
        audit_row = {
            "id": audit_id,
            "event_type": "runtime_prompts_imported",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "prompt_import",
            "target_id": "prompt-import-1",
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "csv_sha256": ["hash"],
                "source_format": "xlsx",
                "source_filename": "prompts.xlsx",
                "source_content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            "output_refs": {"prompt_question_ids": [prompt_id]},
            "method_version": "runtime_prompt_import_xlsx_v1",
            "reason": "import runtime prompts from xlsx",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_prompt_imports(
            project_id=project_id,
            source_format="xlsx",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimePromptImportHistoryPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].prompt_import["source_format"], "xlsx")
        self.assertEqual(page.records[0].prompt_import["source_filename"], "prompts.xlsx")
        self.assertEqual(page.records[0].prompt_import["csv_sha256"], "hash")
        self.assertEqual(page.records[0].prompt_import["prompt_count"], 1)
        self.assertEqual(page.records[0].audit_events[0]["method_version"], "runtime_prompt_import_xlsx_v1")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM audit_events", executed_sql)
        self.assertIn("event_type = %s", executed_sql)
        self.assertIn("COALESCE(input_refs ->> 'source_format', 'csv') = %s", executed_sql)
        self.assertIn("ORDER BY created_at DESC, id DESC", executed_sql)

    def test_runtime_repository_requires_database_url(self) -> None:
        with self.assertRaises(RuntimePersistenceError):
            build_repository_from_env({})

    def test_runtime_repository_uses_database_url_connector(self) -> None:
        seen_urls: list[str] = []
        connection = RecordingConnection()

        def connector(database_url: str) -> RecordingConnection:
            seen_urls.append(database_url)
            return connection

        repository = build_repository_from_env(
            {"DATABASE_URL": "postgresql://geno:geno@localhost:5432/geno"},
            connector=connector,
        )
        self.assertIsInstance(repository, PostgresEvidenceRepository)
        self.assertEqual(seen_urls, ["postgresql://geno:geno@localhost:5432/geno"])

    def test_runtime_repository_pool_reuses_connection_and_resets_on_return(self) -> None:
        connections: list[RecordingConnection] = []

        def connector(database_url: str) -> RecordingConnection:
            connections.append(RecordingConnection())
            return connections[-1]

        env = {
            "DATABASE_URL": "postgresql://geno:geno@localhost:5432/geno",
            "GENO_RUNTIME_DB_POOL_ENABLED": "1",
            "GENO_RUNTIME_DB_POOL_MAX_SIZE": "2",
            "GENO_RUNTIME_DB_POOL_TIMEOUT_SECONDS": "0",
        }
        try:
            repository = build_repository_from_env(env, connector=connector)
            self.assertIsInstance(repository, PostgresEvidenceRepository)
            close_repository_connection(repository)
            self.assertEqual(len(connections), 1)
            self.assertEqual(connections[0].rollback_count, 1)
            self.assertEqual(connections[0].commit_count, 1)
            self.assertEqual(connections[0].close_count, 0)
            reset_sql = "\n".join(sql for sql, _ in connections[0].calls)
            self.assertIn("set_config(%s, %s, false)", reset_sql)
            self.assertEqual(
                connections[0].calls[0][1],
                (
                    "geno.runtime_project_access_control",
                    "",
                    "geno.runtime_actor_id",
                    "",
                    "geno.runtime_project_id",
                    "",
                    "geno.runtime_invitation_token_hash",
                    "",
                ),
            )

            second_repository = build_repository_from_env(env, connector=connector)
            close_repository_connection(second_repository)
            self.assertEqual(len(connections), 1)
            self.assertEqual(connections[0].rollback_count, 2)
            self.assertEqual(connections[0].commit_count, 2)
        finally:
            close_runtime_postgres_pool()
        self.assertEqual(connections[0].close_count, 1)

    def test_runtime_repository_pool_times_out_when_exhausted(self) -> None:
        connections: list[RecordingConnection] = []

        def connector(database_url: str) -> RecordingConnection:
            connections.append(RecordingConnection())
            return connections[-1]

        env = {
            "DATABASE_URL": "postgresql://geno:geno@localhost:5432/geno",
            "GENO_RUNTIME_DB_POOL_ENABLED": "1",
            "GENO_RUNTIME_DB_POOL_MAX_SIZE": "1",
            "GENO_RUNTIME_DB_POOL_TIMEOUT_SECONDS": "0",
        }
        repository = build_repository_from_env(env, connector=connector)
        try:
            with self.assertRaises(RuntimePersistenceError):
                build_repository_from_env(env, connector=connector)
        finally:
            close_repository_connection(repository)
            close_runtime_postgres_pool()
        self.assertEqual(len(connections), 1)
        self.assertEqual(connections[0].rollback_count, 1)
        self.assertEqual(connections[0].commit_count, 1)
        self.assertEqual(connections[0].close_count, 1)

    def test_runtime_repository_pool_validates_config(self) -> None:
        with self.assertRaises(RuntimePersistenceError):
            build_repository_from_env(
                {
                    "DATABASE_URL": "postgresql://geno:geno@localhost:5432/geno",
                    "GENO_RUNTIME_DB_POOL_ENABLED": "1",
                    "GENO_RUNTIME_DB_POOL_MAX_SIZE": "0",
                },
                connector=lambda database_url: RecordingConnection(),
            )

    def test_runtime_database_diagnostic_reports_missing_database_url(self) -> None:
        diagnostic = runtime_database_diagnostic({})

        self.assertEqual(diagnostic.name, "database")
        self.assertEqual(diagnostic.status, "fail")
        self.assertEqual(diagnostic.metadata["database_url"], "missing")

    def test_runtime_database_diagnostic_runs_select_one_and_closes_connection(self) -> None:
        connections: list[RecordingConnection] = []

        def connector(database_url: str) -> RecordingConnection:
            connections.append(RecordingConnection(result_sets=[{"?column?": 1}]))
            return connections[-1]

        diagnostic = runtime_database_diagnostic(
            {"DATABASE_URL": "postgresql://geno:geno@localhost:5432/geno"},
            connector=connector,
        )

        self.assertEqual(diagnostic.status, "pass")
        self.assertEqual(diagnostic.metadata["database_url"], "configured")
        self.assertEqual(len(connections), 1)
        self.assertIn("SELECT 1", "\n".join(sql for sql, _ in connections[0].calls))
        self.assertEqual(connections[0].close_count, 1)

    def test_runtime_object_store_diagnostic_is_config_only(self) -> None:
        missing = runtime_object_store_diagnostic({})
        configured = runtime_object_store_diagnostic(
            {
                "OBJECT_STORE_ENDPOINT": "http://minio:9000",
                "OBJECT_STORE_BUCKET": "geno-reports",
                "OBJECT_STORE_ACCESS_KEY": "minio",
                "OBJECT_STORE_SECRET_KEY": "minio123",
            }
        )

        self.assertEqual(missing.status, "warn")
        self.assertEqual(missing.metadata["network_check"], "not_run")
        self.assertEqual(configured.status, "pass")
        self.assertEqual(configured.metadata["endpoint"], "configured")

    def test_runtime_auth_diagnostic_validates_jwt_secret(self) -> None:
        diagnostic = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
            }
        )
        valid = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "secret",
            }
        )

        self.assertEqual(diagnostic.status, "fail")
        self.assertIn("GENO_RUNTIME_JWT_SECRET", diagnostic.detail)
        self.assertEqual(valid.status, "pass")

    def test_runtime_auth_diagnostic_validates_jwks_json(self) -> None:
        missing = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
            }
        )
        invalid = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": "{}",
            }
        )
        valid = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": '{"keys":[{"kty":"RSA","kid":"runtime-key-1","n":"AQ","e":"AQAB"}]}',
            }
        )

        self.assertEqual(missing.status, "fail")
        self.assertIn("GENO_RUNTIME_JWKS_JSON", missing.detail)
        self.assertEqual(invalid.status, "fail")
        self.assertIn("keys array", invalid.detail)
        self.assertEqual(valid.status, "pass")
        self.assertEqual(valid.metadata["jwks_key_count"], 1)

    def test_runtime_auth_diagnostic_accepts_jwks_url_without_network_check(self) -> None:
        diagnostic = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_URL": "https://idp.example.test/.well-known/jwks.json",
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "120",
                "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS": "30",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            }
        )
        invalid_url = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_URL": "file:///tmp/jwks.json",
            }
        )
        invalid_ttl = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_URL": "https://idp.example.test/.well-known/jwks.json",
                "GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS": "-1",
            }
        )
        invalid_stale_if_error = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_URL": "https://idp.example.test/.well-known/jwks.json",
                "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS": "-1",
            }
        )

        self.assertEqual(diagnostic.status, "pass")
        self.assertEqual(diagnostic.metadata["jwks_url"], "configured")
        self.assertEqual(diagnostic.metadata["jwks_url_network_check"], "not_run")
        self.assertEqual(diagnostic.metadata["jwks_stale_if_error_seconds"], "30")
        self.assertEqual(invalid_url.status, "fail")
        self.assertIn("GENO_RUNTIME_JWKS_URL", invalid_url.detail)
        self.assertEqual(invalid_ttl.status, "fail")
        self.assertIn("GENO_RUNTIME_JWKS_CACHE_TTL_SECONDS", invalid_ttl.detail)
        self.assertEqual(invalid_stale_if_error.status, "fail")
        self.assertIn("GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS", invalid_stale_if_error.detail)

    def test_runtime_auth_diagnostic_accepts_oidc_discovery_without_network_check(self) -> None:
        explicit_discovery = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_OIDC_DISCOVERY_URL": "https://idp.example.test/.well-known/openid-configuration",
                "GENO_RUNTIME_JWKS_STALE_IF_ERROR_SECONDS": "60",
                "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS": "120",
                "GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS": "30",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            }
        )
        issuer_discovery = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWT_ISSUER": "https://idp.example.test/realms/geno",
                "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS": "120",
                "GENO_RUNTIME_JWKS_FETCH_TIMEOUT_SECONDS": "1.5",
            }
        )
        invalid_discovery_url = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_OIDC_DISCOVERY_URL": "file:///tmp/openid-configuration",
            }
        )
        invalid_issuer_fallback = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWT_ISSUER": "issuer-name",
            }
        )
        invalid_discovery_ttl = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_OIDC_DISCOVERY_URL": "https://idp.example.test/.well-known/openid-configuration",
                "GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS": "-1",
            }
        )
        invalid_discovery_stale_if_error = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_OIDC_DISCOVERY_URL": "https://idp.example.test/.well-known/openid-configuration",
                "GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS": "-1",
            }
        )

        self.assertEqual(explicit_discovery.status, "pass")
        self.assertEqual(explicit_discovery.metadata["oidc_discovery_url"], "configured")
        self.assertEqual(explicit_discovery.metadata["oidc_discovery_source"], "explicit")
        self.assertEqual(explicit_discovery.metadata["oidc_discovery_network_check"], "not_run")
        self.assertEqual(explicit_discovery.metadata["jwks_stale_if_error_seconds"], "60")
        self.assertEqual(explicit_discovery.metadata["oidc_discovery_stale_if_error_seconds"], "30")
        self.assertEqual(issuer_discovery.status, "pass")
        self.assertEqual(issuer_discovery.metadata["oidc_discovery_source"], "jwt_issuer")
        self.assertEqual(issuer_discovery.metadata["jwt_issuer"], "configured")
        self.assertEqual(invalid_discovery_url.status, "fail")
        self.assertIn("GENO_RUNTIME_OIDC_DISCOVERY_URL", invalid_discovery_url.detail)
        self.assertEqual(invalid_issuer_fallback.status, "fail")
        self.assertIn("GENO_RUNTIME_JWT_ISSUER", invalid_issuer_fallback.detail)
        self.assertEqual(invalid_discovery_ttl.status, "fail")
        self.assertIn("GENO_RUNTIME_OIDC_DISCOVERY_CACHE_TTL_SECONDS", invalid_discovery_ttl.detail)
        self.assertEqual(invalid_discovery_stale_if_error.status, "fail")
        self.assertIn(
            "GENO_RUNTIME_OIDC_DISCOVERY_STALE_IF_ERROR_SECONDS",
            invalid_discovery_stale_if_error.detail,
        )

    def test_runtime_auth_diagnostic_prefers_inline_jwks_over_url(self) -> None:
        diagnostic = runtime_auth_diagnostic(
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwks",
                "GENO_RUNTIME_JWKS_JSON": '{"keys":[{"kty":"RSA","kid":"runtime-key-1","n":"AQ","e":"AQAB"}]}',
                "GENO_RUNTIME_JWKS_URL": "file:///tmp/jwks.json",
            }
        )

        self.assertEqual(diagnostic.status, "pass")
        self.assertEqual(diagnostic.metadata["jwks_json"], "configured")
        self.assertEqual(diagnostic.metadata["jwks_url"], "configured")
        self.assertEqual(diagnostic.metadata["jwks_url_network_check"], "not_run")

    def test_build_runtime_diagnostics_aggregates_component_status(self) -> None:
        diagnostic = build_runtime_diagnostics({})

        self.assertEqual(diagnostic.status, "fail")
        self.assertEqual([check.name for check in diagnostic.checks], ["database", "object_store", "runtime_auth"])
        self.assertEqual(diagnostic.to_dict()["status"], "fail")

    def test_postgres_repository_maps_collection_failures_to_audit_tables(self) -> None:
        bootstrap = build_au_project_bootstrap()
        failure = collect_prompt_with_failure_record(
            project_id=bootstrap.project.id,
            prompt=bootstrap.prompt_questions[0],
            market_profile=bootstrap.market_profile,
            collector=OpenAIWebSearchCollector(api_key=""),
            city="Australia",
            sample_index=1,
            sample_size=1,
        )
        self.assertIsInstance(failure, CollectionFailureRecord)
        assert isinstance(failure, CollectionFailureRecord)
        connection = RecordingConnection()
        PostgresEvidenceRepository(connection).save_collection_failure_records((failure,))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO answer_runs", executed_sql)
        self.assertIn("INSERT INTO collector_logs", executed_sql)
        self.assertIn("INSERT INTO collection_costs", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        first_answer_run_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_runs" in sql)
        self.assertEqual(first_answer_run_insert[19], "failed")
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_maps_manual_backfill_to_raw_evidence_tables(self) -> None:
        bootstrap = build_au_project_bootstrap()
        prompt = bootstrap.prompt_questions[0]
        record = build_manual_backfill_record(
            ManualBackfillInput(
                project_id=bootstrap.project.id,
                prompt_question_id=prompt.id,
                prompt_text=prompt.text,
                market_code=prompt.market_code,
                city=prompt.city,
                language=prompt.language,
                platform="google",
                surface="google_ai_mode",
                answer_text="Manual Google AI Mode answer mentioning ExampleBrand with sources.",
                citation_urls=("https://examplebrand.example/au/manual",),
                screenshot_url="s3://manual-backfill/examplebrand-google-ai-mode.png",
                submitted_by="runtime-console",
            )
        )
        connection = RecordingConnection()
        PostgresEvidenceRepository(connection).save_raw_evidence_records((record,))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO answer_runs", executed_sql)
        self.assertIn("INSERT INTO raw_answers", executed_sql)
        self.assertIn("INSERT INTO answer_citations", executed_sql)
        self.assertIn("INSERT INTO evidence_assets", executed_sql)
        self.assertIn("INSERT INTO collector_logs", executed_sql)
        self.assertIn("INSERT INTO collection_costs", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        first_answer_run_insert = next(params for sql, params in connection.calls if "INSERT INTO answer_runs" in sql)
        self.assertEqual(first_answer_run_insert[5], "manual")
        self.assertEqual(first_answer_run_insert[16], "google.manual_backfill")
        self.assertEqual(first_answer_run_insert[19], "completed")
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "manual_backfill_recorded")
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_saves_collection_run_summary_with_audit_event(self) -> None:
        bootstrap = build_au_project_bootstrap()
        records = run_fixture_collection_slice(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            market_profile=bootstrap.market_profile,
            collectors=(FixturePerplexitySonarCollector(),),
            cities=("Australia",),
            sample_size=1,
            prompt_limit=1,
        )
        summary = build_collection_run_summary(
            project_id=bootstrap.project.id,
            run_type="p0a_slice",
            mode="fixture",
            planned_runs=1,
            records=records,
        )
        audit_event = build_collection_run_audit_event(summary)
        connection = RecordingConnection()

        PostgresEvidenceRepository(connection).save_collection_run_summary(summary, audit_event)

        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO collection_run_summaries", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        self.assertIn("ON CONFLICT (id) DO NOTHING", executed_sql)
        collection_run_insert = next(
            params for sql, params in connection.calls if "INSERT INTO collection_run_summaries" in sql
        )
        self.assertEqual(str(collection_run_insert[0]), summary.id)
        self.assertEqual(str(collection_run_insert[1]), bootstrap.project.id)
        self.assertEqual(collection_run_insert[2], "p0a_slice")
        self.assertEqual(collection_run_insert[3], "fixture")
        self.assertEqual(collection_run_insert[4], 1)
        self.assertEqual(collection_run_insert[5], 1)
        self.assertEqual(collection_run_insert[13], summary.total_duration_ms)
        self.assertEqual(collection_run_insert[14], summary.average_duration_ms)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "collection_run_summarized")
        self.assertEqual(audit_insert[5], "collection_run")
        self.assertEqual(str(audit_insert[6]), summary.id)
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_reads_runtime_evidence_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": answer_run_id,
                        "project_id": project_id,
                        "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                        "platform": "perplexity",
                        "surface": "sonar",
                        "access_method": "official_api",
                        "market_code": "AU",
                        "city": "Australia",
                        "language": "en-AU",
                        "device": "desktop",
                        "answer_present": True,
                        "surface_triggered": True,
                        "sample_index": 1,
                        "sample_size": 1,
                        "model_or_surface": "sonar",
                        "account_state": "api_key",
                        "collector_backend_id": "fixture_perplexity_sonar",
                        "collector_version": "fixture-v1",
                        "collected_at": now,
                        "status": "completed",
                        "prompt_text": "Best mattresses in Australia",
                        "prompt_intent_type": "category_recommendation",
                        "prompt_priority": 1,
                        "prompt_version": "au_dtc_ecommerce_v1",
                    }
                ],
                {
                    "id": "5d714ed1-25aa-5651-b8b3-5e4b275d278a",
                    "answer_run_id": answer_run_id,
                    "answer_text": "answer",
                    "raw_payload": {"citations": 1},
                    "raw_payload_hash": "hash",
                    "created_at": now,
                },
                [
                    {
                        "id": "6e5c424e-1674-58ce-b075-6c52259bbbe5",
                        "answer_run_id": answer_run_id,
                        "url": "https://reviews.example/koala",
                        "domain": "reviews.example",
                        "position": 1,
                        "source_type": "review_site",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "29a279b8-3313-5306-a959-4f0f0de9c950",
                        "answer_run_id": answer_run_id,
                        "asset_type": "html_snapshot",
                        "url": "s3://asset.html",
                        "content_hash": "asset-hash",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "09e818ce-9c02-5fb4-af15-60f3fef55d55",
                        "answer_run_id": answer_run_id,
                        "collector_backend_id": "fixture_perplexity_sonar",
                        "event_type": "collection_completed",
                        "payload": {"answer_present": True},
                        "created_at": now,
                    }
                ],
                {
                    "id": "a428e674-b6ee-51cb-b59c-f0676654c46f",
                    "answer_run_id": answer_run_id,
                    "project_id": project_id,
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "llm_provider": "perplexity",
                    "llm_tokens": 12,
                    "llm_cost": 0.001,
                    "proxy_or_vendor_cost": 0.001,
                    "compute_cost": 0.0005,
                    "total_cost": 0.0015,
                    "duration_ms": 123,
                    "created_at": now,
                },
                [
                    {
                        "id": "495d24da-90cf-4073-bd9c-16afeb5b3169",
                        "event_type": "answer_run_collected",
                        "project_id": project_id,
                        "actor_type": "worker",
                        "actor_id": "fixture_perplexity_sonar",
                        "target_type": "answer_run",
                        "target_id": answer_run_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"prompt_question_ids": ["prompt"]},
                        "output_refs": {"answer_run_ids": [answer_run_id]},
                        "method_version": "fixture-v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_evidence_runs(
            project_id=project_id,
            platform="perplexity",
            city="Australia",
            intent_type="category_recommendation",
            status="completed",
            sort="citation_count_desc",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeEvidencePage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.sort, "citation_count_desc")
        self.assertEqual(len(page.records), 1)
        record = page.records[0]
        self.assertEqual(record.answer_run["id"], answer_run_id)
        self.assertEqual(record.answer_run["prompt_text"], "Best mattresses in Australia")
        self.assertEqual(record.answer_run["prompt_version"], "au_dtc_ecommerce_v1")
        self.assertEqual(record.raw_answer["raw_payload"]["citations"], 1)
        self.assertEqual(record.citations[0]["domain"], "reviews.example")
        self.assertEqual(record.evidence_assets[0]["asset_type"], "html_snapshot")
        self.assertEqual(record.collector_logs[0]["event_type"], "collection_completed")
        self.assertEqual(record.collection_cost["total_cost"], 0.0015)
        self.assertEqual(record.collection_cost["duration_ms"], 123)
        self.assertEqual(record.audit_events[0]["event_type"], "answer_run_collected")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM answer_runs ar LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id", executed_sql)
        self.assertIn(
            "WHERE ar.project_id = %s AND ar.platform = %s AND ar.city = %s AND pq.intent_type = %s AND ar.status = %s",
            executed_sql,
        )
        self.assertIn("ORDER BY citation_counts.citation_count DESC NULLS LAST", executed_sql)
        self.assertIn("LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id", executed_sql)
        self.assertIn("LEFT JOIN collection_costs cc ON cc.answer_run_id = ar.id", executed_sql)
        self.assertIn("FROM raw_answers", executed_sql)

    def test_postgres_repository_reads_runtime_collection_run_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        collection_run_id = "67b5d761-bd78-51c8-923e-f934ac31cae2"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": collection_run_id,
                        "project_id": project_id,
                        "run_type": "p0a_slice",
                        "mode": "fixture",
                        "planned_runs": 4,
                        "attempted_runs": 4,
                        "success_count": 3,
                        "failure_count": 1,
                        "success_rate": 0.75,
                        "trigger_rate": 0.75,
                        "answer_present_rate": 0.75,
                        "total_cost": 0.0076,
                        "average_cost_per_run": 0.0019,
                        "total_duration_ms": 400,
                        "average_duration_ms": 100,
                        "collector_backend_ids": ["perplexity.sonar.fixture", "openai.web_search.api"],
                        "platform_distribution": {"perplexity": 3, "chatgpt": 1},
                        "city_distribution": {"Australia": 4},
                        "access_method_distribution": {"official_api": 4},
                        "failure_summary": {"OPENAI_API_KEY is required": 1},
                        "answer_run_ids": [answer_run_id],
                        "started_at": now,
                        "completed_at": now,
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "495d24da-90cf-4073-bd9c-16afeb5b3169",
                        "event_type": "collection_run_summarized",
                        "project_id": project_id,
                        "actor_type": "worker",
                        "actor_id": "collector_worker",
                        "target_type": "collection_run",
                        "target_id": collection_run_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"collection_run_ids": [collection_run_id]},
                        "method_version": "collection_run_summary_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_collection_runs(
            project_id=project_id,
            run_type="p0a_slice",
            limit=10,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeCollectionRunPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(len(page.records), 1)
        record = page.records[0]
        self.assertEqual(record.collection_run["id"], collection_run_id)
        self.assertEqual(record.collection_run["success_rate"], 0.75)
        self.assertIsInstance(record.collection_run["success_rate"], float)
        self.assertIsInstance(record.collection_run["planned_runs"], int)
        self.assertEqual(record.collection_run["total_duration_ms"], 400)
        self.assertEqual(record.collection_run["average_duration_ms"], 100)
        self.assertIsInstance(record.collection_run["average_duration_ms"], int)
        self.assertEqual(record.collection_run["failure_summary"], {"OPENAI_API_KEY is required": 1})
        self.assertEqual(record.audit_events[0]["event_type"], "collection_run_summarized")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM collection_run_summaries WHERE project_id = %s AND run_type = %s", executed_sql)
        self.assertIn("ORDER BY created_at DESC, id DESC", executed_sql)
        self.assertIn("WHERE target_type = %s AND target_id = %s", executed_sql)

    def test_runtime_fidelity_check_records_mismatch_and_audit_event(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        prompt_id = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        check, audit_event = build_runtime_fidelity_check(
            project_id=project_id,
            report_export_id=report_export_id,
            answer_run_rows=(
                {
                    "id": "438ab927-5873-5516-8df3-47f6c75ef007",
                    "project_id": project_id,
                    "prompt_question_id": prompt_id,
                    "platform": "chatgpt",
                    "surface": "chatgpt_search",
                    "access_method": "official_api",
                    "city": "Sydney",
                    "answer_present": True,
                    "surface_triggered": True,
                    "screenshot_count": 0,
                    "html_snapshot_count": 0,
                },
                {
                    "id": "4c498fd9-7aac-5f62-b29f-f15450c836d3",
                    "project_id": project_id,
                    "prompt_question_id": prompt_id,
                    "platform": "chatgpt",
                    "surface": "chatgpt_search",
                    "access_method": "browser",
                    "city": "Sydney",
                    "answer_present": False,
                    "surface_triggered": True,
                    "screenshot_count": 1,
                    "html_snapshot_count": 1,
                },
            ),
            checked_by="unit-test",
        )

        self.assertEqual(check["status"], "sampled")
        self.assertEqual(check["official_api_records"], 1)
        self.assertEqual(check["browser_records"], 1)
        self.assertEqual(check["comparable_prompt_city_pairs"], 1)
        self.assertEqual(check["mismatch_count"], 1)
        self.assertEqual(check["difference_rate"], 1.0)
        self.assertEqual(len(check["payload_hash"]), 64)
        self.assertEqual(audit_event.event_type, "api_browser_fidelity_checked")
        self.assertEqual(audit_event.target_type, "api_browser_fidelity_check")
        self.assertEqual(audit_event.method_version, "api_browser_fidelity_check_v1")
        self.assertEqual(audit_event.input_refs["report_export_ids"], [report_export_id])

    def test_browser_fidelity_sampling_plan_is_deterministic_and_auditable(self) -> None:
        bootstrap = build_au_project_bootstrap()
        run_date = datetime(2026, 6, 11, tzinfo=UTC).date()
        plan, audit_event = build_browser_fidelity_sampling_plan(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            available_cities=tuple(bootstrap.market_profile.cities),
            run_date=run_date,
            prompt_count=4,
            city_count=2,
            sample_size=1,
            selection_seed="fixed-seed",
        )
        plan_again, _ = build_browser_fidelity_sampling_plan(
            project_id=bootstrap.project.id,
            prompts=bootstrap.prompt_questions,
            available_cities=tuple(bootstrap.market_profile.cities),
            run_date=run_date,
            prompt_count=4,
            city_count=2,
            sample_size=1,
            selection_seed="fixed-seed",
        )

        self.assertEqual(plan.prompt_question_ids, plan_again.prompt_question_ids)
        self.assertEqual(plan.cities, plan_again.cities)
        self.assertEqual(plan.prompt_count, 4)
        self.assertEqual(plan.city_count, 2)
        self.assertEqual(plan.planned_runs, 24)
        self.assertEqual(plan.official_api_backend_ids, ("perplexity.sonar.api", "openai.web_search.api"))
        self.assertEqual(plan.browser_backend_ids, ("chatgpt_search.browser.playwright",))
        self.assertIn("--prompt-ids", plan.recommended_worker_args)
        self.assertIn("--prompt-limit", plan.recommended_worker_args)
        self.assertIn("--include-browser-fidelity-playwright", plan.recommended_worker_args)
        self.assertEqual(audit_event.event_type, "browser_fidelity_sampling_planned")
        self.assertEqual(audit_event.target_id, plan.id)
        self.assertEqual(audit_event.method_version, "browser_fidelity_sampling_plan_v1")
        self.assertEqual(audit_event.input_refs["prompt_question_ids"], list(plan.prompt_question_ids))

    def test_postgres_repository_creates_runtime_fidelity_check_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        official_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        browser_run_id = "4c498fd9-7aac-5f62-b29f-f15450c836d3"
        prompt_id = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        official_answer_row = {
            "id": official_run_id,
            "project_id": project_id,
            "prompt_question_id": prompt_id,
            "platform": "chatgpt",
            "surface": "chatgpt_search",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Sydney",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "gpt-search",
            "account_state": "api_key",
            "collector_backend_id": "fixture_openai_web_search",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "screenshot_count": 0,
            "html_snapshot_count": 0,
        }
        browser_answer_row = {
            **official_answer_row,
            "id": browser_run_id,
            "access_method": "browser",
            "answer_present": False,
            "collector_backend_id": "browser_chatgpt_search",
            "screenshot_count": 1,
            "html_snapshot_count": 1,
        }
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                {"id": report_export_id},
                [{"answer_run_id": official_run_id}, {"answer_run_id": browser_run_id}],
                [official_answer_row, browser_answer_row],
                [
                    {
                        "id": "d0ba559d-13f3-4b79-a984-b39cb273b6a4",
                        "event_type": "api_browser_fidelity_checked",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "runtime-console",
                        "target_type": "api_browser_fidelity_check",
                        "target_id": "check-id",
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [official_run_id, browser_run_id]},
                        "output_refs": {"api_browser_fidelity_check_ids": ["check-id"]},
                        "method_version": "api_browser_fidelity_check_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).create_runtime_fidelity_check(
            project_id=project_id,
            report_export_id=report_export_id,
            checked_by="runtime-console",
        )

        self.assertIsInstance(record, RuntimeFidelityCheck)
        self.assertEqual(record.fidelity_check["status"], "sampled")
        self.assertEqual(record.fidelity_check["mismatch_count"], 1)
        self.assertEqual(record.audit_events[0]["event_type"], "api_browser_fidelity_checked")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM report_evidence", executed_sql)
        self.assertIn("GROUP BY ar.id", executed_sql)
        self.assertIn("INSERT INTO api_browser_fidelity_checks", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "api_browser_fidelity_checked")

    def test_postgres_repository_lists_runtime_fidelity_checks_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        check_id = "9128c59e-54ca-5ceb-9272-3efe226bd07b"
        check_row = {
            "id": check_id,
            "project_id": project_id,
            "report_export_id": report_export_id,
            "status": "not_run",
            "official_api_records": 4,
            "browser_records": 0,
            "comparable_prompt_city_pairs": 0,
            "mismatch_count": 0,
            "difference_rate": None,
            "payload": {"status": "not_run", "summary": "browser sample not collected"},
            "payload_hash": "f" * 64,
            "answer_run_ids": ["438ab927-5873-5516-8df3-47f6c75ef007"],
            "checked_by": "collector_worker",
            "checked_at": now,
        }
        audit_row = {
            "id": "d0ba559d-13f3-4b79-a984-b39cb273b6a4",
            "event_type": "api_browser_fidelity_checked",
            "project_id": project_id,
            "actor_type": "system",
            "actor_id": "collector_worker",
            "target_type": "api_browser_fidelity_check",
            "target_id": check_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"report_export_ids": [report_export_id]},
            "output_refs": {"api_browser_fidelity_check_ids": [check_id]},
            "method_version": "api_browser_fidelity_check_v1",
            "reason": "test",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [check_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_fidelity_checks(
            project_id=project_id,
            report_export_id=report_export_id,
            status="not_run",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeFidelityCheckPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].fidelity_check["payload_hash"], "f" * 64)
        self.assertEqual(page.records[0].audit_events[0]["method_version"], "api_browser_fidelity_check_v1")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn(
            "FROM api_browser_fidelity_checks WHERE project_id = %s AND report_export_id = %s AND status = %s",
            executed_sql,
        )
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_builds_runtime_fidelity_trend(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        rows_desc = [
            {
                "id": "a128c7bb-1264-51c0-97f8-0fb8ea32ae81",
                "project_id": project_id,
                "report_export_id": report_export_id,
                "status": "sampled",
                "official_api_records": 10,
                "browser_records": 10,
                "comparable_prompt_city_pairs": 4,
                "mismatch_count": 2,
                "difference_rate": 0.5,
                "payload": {"status": "sampled"},
                "payload_hash": "a" * 64,
                "answer_run_ids": [],
                "checked_by": "scheduler",
                "checked_at": now,
            },
            {
                "id": "9d0ccf2f-4058-5efd-a3d3-fef60a73191a",
                "project_id": project_id,
                "report_export_id": report_export_id,
                "status": "sampled",
                "official_api_records": 10,
                "browser_records": 10,
                "comparable_prompt_city_pairs": 4,
                "mismatch_count": 1,
                "difference_rate": 0.25,
                "payload": {"status": "sampled"},
                "payload_hash": "b" * 64,
                "answer_run_ids": [],
                "checked_by": "scheduler",
                "checked_at": now.replace(hour=0),
            },
        ]
        connection = RecordingConnection(result_sets=[{"count": 2}, rows_desc])

        trend = PostgresEvidenceRepository(connection).get_runtime_fidelity_trend(
            project_id=project_id,
            report_export_id=report_export_id,
            limit=10,
        )

        self.assertIsInstance(trend, RuntimeFidelityTrend)
        self.assertEqual(trend.total_count, 2)
        self.assertEqual(trend.sampled_count, 2)
        self.assertEqual(trend.latest_status, "sampled")
        self.assertEqual(trend.earliest_difference_rate, 0.25)
        self.assertEqual(trend.latest_difference_rate, 0.5)
        self.assertEqual(trend.average_difference_rate, 0.375)
        self.assertEqual(trend.max_difference_rate, 0.5)
        self.assertEqual(trend.trend_direction, "worsening")
        self.assertEqual([point.difference_rate for point in trend.points], [0.25, 0.5])
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM api_browser_fidelity_checks WHERE project_id = %s AND report_export_id = %s", executed_sql)
        self.assertIn("ORDER BY checked_at DESC, id DESC", executed_sql)

    def test_postgres_repository_exports_filtered_runtime_evidence_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": answer_run_id,
                        "project_id": project_id,
                        "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                        "platform": "perplexity",
                        "surface": "sonar",
                        "access_method": "official_api",
                        "market_code": "AU",
                        "city": "Sydney",
                        "language": "en-AU",
                        "device": "desktop",
                        "answer_present": True,
                        "surface_triggered": True,
                        "sample_index": 1,
                        "sample_size": 1,
                        "model_or_surface": "sonar",
                        "account_state": "api_key",
                        "collector_backend_id": "fixture_perplexity_sonar",
                        "collector_version": "fixture-v1",
                        "collected_at": now,
                        "status": "completed",
                        "prompt_text": "Is ExampleBrand good in Australia?",
                        "prompt_intent_type": "brand_awareness",
                        "prompt_priority": 1,
                        "prompt_version": "au_dtc_ecommerce_v1",
                    }
                ],
                {
                    "id": "5d714ed1-25aa-5651-b8b3-5e4b275d278a",
                    "answer_run_id": answer_run_id,
                    "answer_text": "answer",
                    "raw_payload": {"citations": 1},
                    "raw_payload_hash": "raw-hash",
                    "created_at": now,
                },
                [
                    {
                        "id": "6e5c424e-1674-58ce-b075-6c52259bbbe5",
                        "answer_run_id": answer_run_id,
                        "url": "https://reviews.example/koala",
                        "domain": "reviews.example",
                        "position": 1,
                        "source_type": "review_site",
                        "created_at": now,
                    }
                ],
                [],
                [],
                {
                    "id": "a428e674-b6ee-51cb-b59c-f0676654c46f",
                    "answer_run_id": answer_run_id,
                    "project_id": project_id,
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "llm_provider": "perplexity",
                    "llm_tokens": 12,
                    "llm_cost": 0.001,
                    "proxy_or_vendor_cost": 0.001,
                    "compute_cost": 0.0005,
                    "total_cost": 0.0015,
                    "created_at": now,
                },
                [
                    {
                        "id": "495d24da-90cf-4073-bd9c-16afeb5b3169",
                        "event_type": "answer_run_collected",
                        "project_id": project_id,
                        "actor_type": "worker",
                        "actor_id": "fixture_perplexity_sonar",
                        "target_type": "answer_run",
                        "target_id": answer_run_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"prompt_question_ids": ["prompt"]},
                        "output_refs": {"answer_run_ids": [answer_run_id]},
                        "method_version": "fixture-v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )
        export = PostgresEvidenceRepository(connection).export_runtime_evidence_csv(
            platform="perplexity",
            city="Sydney",
            intent_type="brand_awareness",
            sort="cost_desc",
            limit=200,
            offset=0,
        )
        self.assertIsInstance(export, RuntimeEvidenceExport)
        self.assertEqual(export.filename, "runtime-evidence.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["platform"], "perplexity")
        self.assertEqual(export.filters["sort"], "cost_desc")
        self.assertIn("answer_run_id", export.content)
        self.assertIn("prompt_intent_type", export.content)
        self.assertIn("Is ExampleBrand good in Australia?", export.content)
        self.assertIn("raw-hash", export.content)
        self.assertTrue(export.content_hash)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("pq.intent_type = %s", executed_sql)
        self.assertIn("ORDER BY cc.total_cost DESC NULLS LAST", executed_sql)

    def test_postgres_repository_falls_back_for_unknown_runtime_evidence_sort(self) -> None:
        connection = RecordingConnection(result_sets=[{"count": 0}, []])
        page = PostgresEvidenceRepository(connection).list_runtime_evidence_runs(
            sort="cc.total_cost DESC; DROP TABLE answer_runs",
            limit=5,
            offset=0,
        )
        self.assertEqual(page.sort, "collected_at_desc")
        self.assertEqual(page.total_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("ORDER BY ar.collected_at DESC, ar.id DESC", executed_sql)
        self.assertNotIn("DROP TABLE", executed_sql)

    def test_postgres_repository_reads_runtime_score_snapshot_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": snapshot_id,
                        "project_id": project_id,
                        "scope_type": "collection_slice",
                        "scope_value": "worker_runtime",
                        "formula_version": "au_visibility_v1",
                        "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                        "final_score": 72.5,
                        "trigger_rate": 1.0,
                        "mention_rate": 1.0,
                        "recommendation_rate": 0.75,
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                        "dispersion": 2.5,
                    }
                ],
                [
                    {
                        "id": "df03794b-e8fc-4b69-aa62-2304a55ff3a9",
                        "score_snapshot_id": snapshot_id,
                        "component_name": "MentionScore",
                        "component_score": 100.0,
                        "weight": 0.18,
                        "weighted_contribution": 18.0,
                        "denominator": "surface_triggered",
                        "evidence_answer_run_ids": [answer_run_id],
                        "positive_evidence_summary": "brand mentioned",
                        "negative_evidence_summary": "",
                        "confidence_note": "avg_parser_confidence=0.9",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": answer_run_id,
                        "project_id": project_id,
                        "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                        "platform": "perplexity",
                        "surface": "sonar",
                        "access_method": "official_api",
                        "market_code": "AU",
                        "city": "Australia",
                        "language": "en-AU",
                        "device": "desktop",
                        "answer_present": True,
                        "surface_triggered": True,
                        "sample_index": 1,
                        "sample_size": 1,
                        "model_or_surface": "sonar",
                        "account_state": "api_key",
                        "collector_backend_id": "fixture_perplexity_sonar",
                        "collector_version": "fixture-v1",
                        "collected_at": now,
                        "status": "completed",
                        "prompt_text": "Is ExampleBrand good in Australia?",
                        "prompt_intent_type": "brand_awareness",
                        "prompt_priority": 1,
                        "prompt_version": "au_dtc_ecommerce_v1",
                    }
                ],
                {
                    "id": "d1466dad-237b-5f5f-b7cc-44e67d628d15",
                    "answer_run_id": answer_run_id,
                    "parser_engine_id": "rule_based_v2_aliases",
                    "analysis_version": "rule_based_v2_aliases",
                    "payload": {"brand_mentioned": True},
                    "confidence": 0.9,
                    "created_at": now,
                },
                [
                    {
                        "id": "9b663656-4a0e-4fda-a764-0a4d62fa15f1",
                        "event_type": "visibility_score_snapshot_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.scoring",
                        "target_type": "visibility_score_snapshot",
                        "target_id": snapshot_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"score_snapshot_ids": [snapshot_id]},
                        "method_version": "au_visibility_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_score_snapshots(
            project_id=project_id,
            scope_type="collection_slice",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeScoreSnapshotPage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.snapshot["final_score"], 72.5)
        self.assertEqual(record.contributions[0]["component_name"], "MentionScore")
        self.assertEqual(record.answer_runs[0].answer_run["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(record.answer_runs[0].analysis["payload"]["brand_mentioned"], True)
        self.assertEqual(record.audit_events[0]["event_type"], "visibility_score_snapshot_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM visibility_score_snapshots WHERE project_id = %s AND scope_type = %s", executed_sql)
        self.assertIn("FROM score_snapshot_runs ssr JOIN answer_runs ar ON ar.id = ssr.answer_run_id", executed_sql)
        self.assertIn("LEFT JOIN prompt_questions pq ON pq.id = ar.prompt_question_id", executed_sql)

    def test_postgres_repository_exports_runtime_score_snapshots_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": snapshot_id,
                        "project_id": project_id,
                        "scope_type": "collection_slice",
                        "scope_value": "worker_runtime",
                        "formula_version": "au_visibility_v1",
                        "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                        "final_score": 72.5,
                        "trigger_rate": 1.0,
                        "mention_rate": 1.0,
                        "recommendation_rate": 0.75,
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                        "dispersion": 2.5,
                        "component_weights_snapshot": {"MentionScore": 0.18, "FreshnessScore": 0.03},
                    }
                ],
                [
                    {
                        "id": "df03794b-e8fc-4b69-aa62-2304a55ff3a9",
                        "score_snapshot_id": snapshot_id,
                        "component_name": "MentionScore",
                        "component_score": 100.0,
                        "weight": 0.18,
                        "weighted_contribution": 18.0,
                        "denominator": "surface_triggered",
                        "evidence_answer_run_ids": [answer_run_id],
                        "positive_evidence_summary": "brand mentioned",
                        "negative_evidence_summary": "competitor preferred",
                        "confidence_note": "avg_parser_confidence=0.9",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": answer_run_id,
                        "project_id": project_id,
                        "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                        "platform": "perplexity",
                        "surface": "sonar",
                        "access_method": "official_api",
                        "market_code": "AU",
                        "city": "Australia",
                        "language": "en-AU",
                        "device": "desktop",
                        "answer_present": True,
                        "surface_triggered": True,
                        "sample_index": 1,
                        "sample_size": 1,
                        "model_or_surface": "sonar",
                        "account_state": "api_key",
                        "collector_backend_id": "fixture_perplexity_sonar",
                        "collector_version": "fixture-v1",
                        "collected_at": now,
                        "status": "completed",
                        "prompt_text": "Is ExampleBrand good in Australia?",
                        "prompt_intent_type": "brand_awareness",
                        "prompt_priority": 1,
                        "prompt_version": "au_dtc_ecommerce_v1",
                    }
                ],
                {
                    "id": "d1466dad-237b-5f5f-b7cc-44e67d628d15",
                    "answer_run_id": answer_run_id,
                    "parser_engine_id": "rule_based_v2_aliases",
                    "analysis_version": "rule_based_v2_aliases",
                    "payload": {"brand_mentioned": True},
                    "confidence": 0.9,
                    "created_at": now,
                },
                [
                    {
                        "id": "9b663656-4a0e-4fda-a764-0a4d62fa15f1",
                        "event_type": "visibility_score_snapshot_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.scoring",
                        "target_type": "visibility_score_snapshot",
                        "target_id": snapshot_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"score_snapshot_ids": [snapshot_id]},
                        "method_version": "au_visibility_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )

        export = PostgresEvidenceRepository(connection).export_runtime_score_snapshots_csv(
            project_id=project_id,
            scope_type="collection_slice",
            limit=10,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_score_snapshots_csv")
        self.assertEqual(export.filename, "runtime-score-snapshots.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["scope_type"], "collection_slice")
        self.assertIn("score_snapshot_id,project_id,scope_type,scope_value", export.content)
        self.assertIn(snapshot_id, export.content)
        self.assertIn("MentionScore", export.content)
        self.assertIn("surface_triggered", export.content)
        self.assertIn("FreshnessScore|MentionScore", export.content)
        self.assertIn("chatgpt|perplexity", export.content)
        self.assertIn("rule_based_v2_aliases", export.content)
        self.assertIn("fixture-v1", export.content)
        self.assertIn(_artifact_hash("brand mentioned"), export.content)
        self.assertIn(_artifact_hash("competitor preferred"), export.content)
        self.assertIn(_artifact_hash("avg_parser_confidence=0.9"), export.content)
        self.assertIn(_artifact_hash("Is ExampleBrand good in Australia?"), export.content)
        self.assertIn("visibility_score_snapshot_created", export.content)
        self.assertIn("au_visibility_v1", export.content)
        self.assertIn("after", export.content)
        self.assertNotIn("brand mentioned", export.content)
        self.assertNotIn("competitor preferred", export.content)
        self.assertNotIn("avg_parser_confidence=0.9", export.content)
        self.assertNotIn("Is ExampleBrand good in Australia?", export.content)
        self.assertEqual(export.content_hash, hashlib.sha256(export.content.encode("utf-8")).hexdigest())

    def test_postgres_repository_reads_runtime_citation_graph_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        source_graph_id = "41c2fd71-a32f-51a7-92e4-3d4c0f7ab1c2"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [{"project_id": project_id}],
                [
                    {
                        "id": source_graph_id,
                        "project_id": project_id,
                        "source_url": "https://reviews.example/koala",
                        "source_domain": "reviews.example",
                        "source_type": "review_site",
                        "topic": "reviews",
                        "source_gap_type": None,
                        "answer_run_ids": [answer_run_id],
                        "citation_count": 4,
                        "created_at": now,
                    }
                ],
                {
                    "id": answer_run_id,
                    "project_id": project_id,
                    "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                    "platform": "perplexity",
                    "surface": "sonar",
                    "access_method": "official_api",
                    "market_code": "AU",
                    "city": "Australia",
                    "language": "en-AU",
                    "device": "desktop",
                    "answer_present": True,
                    "surface_triggered": True,
                    "sample_index": 1,
                    "sample_size": 1,
                    "model_or_surface": "sonar",
                    "account_state": "api_key",
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "collector_version": "fixture-v1",
                    "collected_at": now,
                    "status": "completed",
                    "prompt_text": "Is ExampleBrand good in Australia?",
                    "prompt_intent_type": "brand_awareness",
                    "prompt_priority": 1,
                    "prompt_version": "au_dtc_ecommerce_v1",
                },
                [
                    {
                        "id": "36bf7c88-0d03-52a9-87f5-7f2a0e35e72a",
                        "source_graph_id": source_graph_id,
                        "answer_run_id": answer_run_id,
                        "answer_citation_id": "6e5c424e-1674-58ce-b075-6c52259bbbe5",
                        "relation_type": "cited_by_answer",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "7cc36d44-0f20-5681-8613-3998050e3267",
                        "project_id": project_id,
                        "source_type": "official_site",
                        "gap_type": "missing_high_weight_source_type",
                        "observed_count": 0,
                        "expected_weight": 0.95,
                        "recommendation": "Add official AU evidence",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "8c6e21aa-5df2-558e-ad5d-220b0de78a98",
                        "project_id": project_id,
                        "competitor_name": "Emma Sleep",
                        "metric_scope": "project",
                        "payload": {"mention_count": 2},
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_citation_graphs(
            project_id=project_id,
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeCitationGraphPage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.project_id, project_id)
        self.assertEqual(record.nodes[0].node["source_domain"], "reviews.example")
        self.assertEqual(record.nodes[0].answer_runs[0]["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(record.evidence_links[0]["relation_type"], "cited_by_answer")
        self.assertEqual(record.source_gaps[0]["source_type"], "official_site")
        self.assertEqual(record.competitor_benchmarks[0]["competitor_name"], "Emma Sleep")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM source_graphs WHERE project_id = %s", executed_sql)
        self.assertIn("FROM source_graph_evidence sge JOIN source_graphs sg ON sg.id = sge.source_graph_id", executed_sql)
        self.assertIn("FROM source_gaps", executed_sql)
        self.assertIn("FROM competitor_benchmarks", executed_sql)

    def test_postgres_repository_reads_runtime_report_export_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        source_graph_id = "41c2fd71-a32f-51a7-92e4-3d4c0f7ab1c2"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "method_disclosure": {
                "google_coverage": "limited_coverage_appendix_only",
                "google_spike_gate": {
                    "gate_status": "fail",
                    "planned_runs": 240,
                    "completed_runs": 0,
                    "google_aio_completed_runs": 0,
                    "success_rate": 0.0,
                    "trigger_rate": 0.0,
                    "limited_coverage": True,
                    "recommendation": "Keep Google in limited coverage appendix until a google_aio backend reaches 80% completion",
                },
                "api_browser_fidelity": {
                    "status": "not_run",
                    "official_api_records": 1,
                    "browser_records": 0,
                    "comparable_prompt_city_pairs": 0,
                    "difference_rate": None,
                },
                "access_method_distribution": {"official_api": 1},
                "platform_distribution": {"perplexity": 1},
                "audit_summary": {
                    "audit_event_count": 1,
                    "event_type_distribution": {"report_export_created": 1},
                    "target_type_distribution": {"report_export": 1},
                    "method_version_distribution": {"markdown_csv_report_exporter_v1": 1},
                    "actor_type_distribution": {"system": 1},
                    "input_ref_keys": ["answer_run_ids"],
                    "output_ref_keys": ["report_export_ids"],
                    "first_event_at": "2026-06-10T00:00:00+00:00",
                    "last_event_at": "2026-06-10T00:00:00+00:00",
                    "event_ids": ["d5f57d79-4834-4bd3-92a3-a1c917fbb3cf"],
                    "summary": "1 upstream audit events attached to this report export.",
                },
                "evidence_asset_coverage": {"screenshot_records": 1, "html_snapshot_records": 1},
            },
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": None,
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Sydney",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
        }
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [report_row],
                {
                    "id": snapshot_id,
                    "project_id": project_id,
                    "scope_type": "collection_slice",
                    "scope_value": "worker_runtime",
                    "formula_version": "au_visibility_v1",
                    "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                    "final_score": 87.35,
                    "trigger_rate": 1.0,
                    "mention_rate": 1.0,
                    "recommendation_rate": 1.0,
                    "answer_run_ids": [answer_run_id],
                    "created_at": now,
                    "dispersion": 0.0,
                },
                answer_run_row,
                [
                    {
                        "id": "d5f57d79-4834-4bd3-92a3-a1c917fbb3cf",
                        "event_type": "report_export_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "markdown_csv_report_exporter_v1",
                        "target_type": "report_export",
                        "target_id": report_export_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"report_export_ids": [report_export_id]},
                        "method_version": "markdown_csv_report_exporter_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
                {"count": 1},
                [
                    {
                        "id": source_graph_id,
                        "project_id": project_id,
                        "source_url": "https://reviews.example/koala",
                        "source_domain": "reviews.example",
                        "source_type": "review_site",
                        "topic": "reviews",
                        "source_gap_type": None,
                        "answer_run_ids": [answer_run_id],
                        "citation_count": 1,
                        "created_at": now,
                    }
                ],
                answer_run_row,
                [],
                [],
                [],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_report_exports(
            project_id=project_id,
            report_type="worker_runtime",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeReportExportPage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.report_export["report_version"], "worker-runtime-v1")
        self.assertEqual(record.score_snapshots[0]["final_score"], 87.35)
        self.assertEqual(record.answer_runs[0]["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertIsNotNone(record.citation_graph)
        assert record.citation_graph is not None
        self.assertEqual(record.citation_graph.nodes[0].node["source_domain"], "reviews.example")
        self.assertEqual(record.audit_events[0]["event_type"], "report_export_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM report_exports WHERE project_id = %s AND report_type = %s", executed_sql)
        self.assertIn("FROM report_evidence re JOIN answer_runs ar ON ar.id = re.answer_run_id", executed_sql)
        self.assertIn("SELECT count(*) FROM source_graphs WHERE project_id = %s", executed_sql)

    def test_postgres_repository_records_report_management_event_without_mutating_report(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "method_disclosure": {},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": "s3://geno-reports/report.pdf",
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Sydney",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
            "total_cost": 0.04,
            "citation_count": 1,
            "audit_event_count": 1,
        }
        existing_management_event = {
            "id": "2778aa22-c350-5d59-a52a-946e5fbdeee1",
            "event_type": "report_export_management_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "report_export",
            "target_id": report_export_id,
            "before_hash": None,
            "after_hash": "old-hash",
            "input_refs": {"status": ["internal_review"]},
            "output_refs": {},
            "method_version": "report_export_management_v1",
            "reason": "Internal review started",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                report_row,
                existing_management_event,
                {"id": snapshot_id, "project_id": project_id, "final_score": 87.35},
                answer_run_row,
                [existing_management_event],
                {"count": 0},
            ]
        )

        record = PostgresEvidenceRepository(connection).record_runtime_report_management_event(
            RuntimeReportManagementInput(
                report_export_id=report_export_id,
                status="client_ready",
                updated_by="runtime-console",
                note="Ready for client delivery",
            )
        )

        self.assertEqual(record.report_export["id"], report_export_id)
        self.assertEqual(record.audit_events[0]["event_type"], "report_export_management_recorded")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        self.assertNotIn("UPDATE report_exports", executed_sql)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "report_export_management_recorded")
        self.assertEqual(audit_insert[4], "runtime-console")
        self.assertEqual(audit_insert[5], "report_export")
        self.assertEqual(audit_insert[6], report_export_id)
        self.assertEqual(audit_insert[11], "report_export_management_v1")
        self.assertEqual(audit_insert[12], "Ready for client delivery")

    def test_postgres_repository_exports_report_management_events_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        markdown_url = "s3://geno-reports/private/report.md"
        pdf_url = "s3://geno-reports/private/report.pdf"
        csv_url = "s3://geno-reports/private/report.csv"
        actor_id = "delivery-manager@example.com"
        note = "Ready for client delivery after internal QA"
        row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [],
            "answer_run_ids": [],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30},
            "method_disclosure": {},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": markdown_url,
            "pdf_url": pdf_url,
            "csv_url": csv_url,
            "exported_by": "system",
            "exported_at": now,
            "management_id": "2778aa22-c350-5d59-a52a-946e5fbdeee1",
            "management_event_type": "report_export_management_recorded",
            "management_project_id": project_id,
            "management_actor_type": "user",
            "management_actor_id": actor_id,
            "management_target_type": "report_export",
            "management_target_id": report_export_id,
            "management_before_hash": "before-management-hash",
            "management_after_hash": "after-management-hash",
            "management_input_refs": {"status": ["client_ready"]},
            "management_output_refs": {"audit_event_ids": ["2778aa22-c350-5d59-a52a-946e5fbdeee1"]},
            "management_method_version": "report_export_management_v1",
            "management_reason": note,
            "management_created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [row]])

        export = PostgresEvidenceRepository(connection).export_runtime_report_management_events_csv(
            project_id=project_id,
            status="client_ready",
            report_type="worker_runtime",
            limit=5,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_report_management_events_csv")
        self.assertEqual(export.filename, "runtime-report-management-events.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["status"], "client_ready")
        self.assertIn("report_export_id,project_id,report_version,report_type", export.content)
        self.assertIn(report_export_id, export.content)
        self.assertIn("client_ready", export.content)
        self.assertIn("report_export_management_v1", export.content)
        self.assertIn("after-management-hash", export.content)
        self.assertIn(_artifact_hash(actor_id), export.content)
        self.assertIn(_artifact_hash(note), export.content)
        self.assertIn(_artifact_hash(markdown_url), export.content)
        self.assertIn(_artifact_hash(pdf_url), export.content)
        self.assertIn(_artifact_hash(csv_url), export.content)
        self.assertNotIn(actor_id, export.content)
        self.assertNotIn(note, export.content)
        self.assertNotIn(markdown_url, export.content)
        self.assertNotIn("private/report.pdf", export.content)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM report_exports re", executed_sql)
        self.assertIn("JOIN audit_events ae", executed_sql)
        self.assertIn("ae.input_refs->'status' ? %s", executed_sql)

    def test_postgres_repository_enqueues_report_export_job_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        job_id = "8f4f2a24-d6cf-5050-96a4-942d2c337fd0"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [],
            "answer_run_ids": [],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {},
            "method_disclosure": {},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": None,
            "pdf_url": None,
            "csv_url": None,
            "exported_by": "system",
            "exported_at": now,
        }
        job_row = {
            "id": job_id,
            "project_id": project_id,
            "report_export_id": report_export_id,
            "status": "queued",
            "artifact_type": "pdf",
            "template": "white_label",
            "filters": {"platform": "perplexity"},
            "sort": "cost_desc",
            "requested_by": "runtime-console",
            "requested_at": now,
            "started_at": None,
            "completed_at": None,
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "artifact_url": None,
            "error_message": None,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "e011f214-7cf4-40e4-b73e-8cc4308cc7d9",
            "event_type": "report_export_job_queued",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "report_export_job",
            "target_id": job_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"report_export_ids": [report_export_id], "artifact_type": ["pdf"]},
            "output_refs": {"report_export_job_ids": [job_id], "status": ["queued"]},
            "method_version": "runtime_report_export_job_v1",
            "reason": "enqueue filtered white-label export",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, report_row, job_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).enqueue_runtime_report_export_job(
            RuntimeReportExportJobInput(
                project_id=project_id,
                report_export_id=report_export_id,
                artifact_type="pdf",
                template="white_label",
                filters={"platform": "perplexity"},
                sort="cost_desc",
                requested_by="runtime-console",
                reason="enqueue filtered white-label export",
            )
        )

        self.assertEqual(record.report_export_job["status"], "queued")
        self.assertEqual(record.report_export_job["template"], "white_label")
        self.assertEqual(record.audit_events[0]["event_type"], "report_export_job_queued")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO report_export_jobs", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_report_export_jobs_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        job_id = "8f4f2a24-d6cf-5050-96a4-942d2c337fd0"
        job_row = {
            "id": job_id,
            "project_id": project_id,
            "report_export_id": None,
            "status": "queued",
            "artifact_type": "csv",
            "template": "standard",
            "filters": {"city": "Sydney"},
            "sort": "collected_at_desc",
            "requested_by": "runtime-console",
            "requested_at": now,
            "started_at": None,
            "completed_at": None,
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "artifact_url": None,
            "error_message": None,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "e011f214-7cf4-40e4-b73e-8cc4308cc7d9",
            "event_type": "report_export_job_queued",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "report_export_job",
            "target_id": job_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {},
            "output_refs": {"report_export_job_ids": [job_id]},
            "method_version": "runtime_report_export_job_v1",
            "reason": "enqueue report export artifact job",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [job_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_report_export_jobs(
            project_id=project_id,
            status="queued",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeReportExportJobPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].report_export_job["artifact_type"], "csv")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "report_export_job_queued")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM report_export_jobs WHERE project_id = %s AND status = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_exports_report_export_jobs_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        job_id = "8f4f2a24-d6cf-5050-96a4-942d2c337fd0"
        artifact_url = "s3://geno-reports/private/report.pdf"
        error_message = "renderer failed with private object detail"
        job_row = {
            "id": job_id,
            "project_id": project_id,
            "report_export_id": report_export_id,
            "status": "dead_letter",
            "artifact_type": "pdf",
            "template": "white_label",
            "filters": {"city": "Sydney", "platform": "perplexity"},
            "sort": "cost_desc",
            "requested_by": "runtime-console",
            "requested_at": now,
            "started_at": now,
            "completed_at": now,
            "attempt_count": 3,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "artifact_url": artifact_url,
            "error_message": error_message,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        audit_row = {
            "id": "e011f214-7cf4-40e4-b73e-8cc4308cc7d9",
            "event_type": "report_export_job_status_updated",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "runtime-worker",
            "target_type": "report_export_job",
            "target_id": job_id,
            "before_hash": "before",
            "after_hash": "job-after-hash",
            "input_refs": {"report_export_job_ids": [job_id], "status": ["dead_letter"]},
            "output_refs": {"report_export_job_ids": [job_id], "status": ["dead_letter"]},
            "method_version": "runtime_report_export_job_status_v1",
            "reason": "report export job dead-lettered",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [job_row], [audit_row]])

        export = PostgresEvidenceRepository(connection).export_runtime_report_export_jobs_csv(
            project_id=project_id,
            status="dead_letter",
            report_export_id=report_export_id,
            limit=5,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_report_export_jobs_csv")
        self.assertEqual(export.filename, "runtime-report-export-jobs.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["status"], "dead_letter")
        self.assertEqual(export.filters["report_export_id"], report_export_id)
        self.assertIn("job_id,project_id,report_export_id,status,artifact_type,template,filter_keys", export.content)
        self.assertIn(job_id, export.content)
        self.assertIn("dead_letter", export.content)
        self.assertIn("city|platform", export.content)
        self.assertIn("runtime_report_export_job_status_v1", export.content)
        self.assertIn("job-after-hash", export.content)
        self.assertIn(_artifact_hash(artifact_url), export.content)
        self.assertIn(_artifact_hash(error_message), export.content)
        self.assertNotIn(artifact_url, export.content)
        self.assertNotIn("private/report.pdf", export.content)
        self.assertNotIn(error_message, export.content)

    def test_postgres_repository_claims_next_report_export_job_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        job_id = "8f4f2a24-d6cf-5050-96a4-942d2c337fd0"
        before_row = {
            "id": job_id,
            "project_id": project_id,
            "report_export_id": None,
            "status": "queued",
            "artifact_type": "pdf",
            "template": "standard",
            "filters": {"city": "Sydney"},
            "sort": "collected_at_desc",
            "requested_by": "runtime-console",
            "requested_at": now,
            "started_at": None,
            "completed_at": None,
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "artifact_url": None,
            "error_message": None,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        after_row = {
            **before_row,
            "status": "running",
            "started_at": now,
            "attempt_count": 1,
            "lease_expires_at": now,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        audit_row = {
            "id": "e011f214-7cf4-40e4-b73e-8cc4308cc7d9",
            "event_type": "report_export_job_status_updated",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "runtime-worker",
            "target_type": "report_export_job",
            "target_id": job_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"status": ["running"], "report_export_job_ids": [job_id]},
            "output_refs": {"claimed": [True]},
            "method_version": "runtime_report_export_job_claim_v1",
            "reason": "claim queued report export job",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[before_row, after_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).claim_next_runtime_report_export_job(updated_by="runtime-worker")

        self.assertIsInstance(record, RuntimeReportExportJob)
        assert record is not None
        self.assertEqual(record.report_export_job["status"], "running")
        self.assertEqual(record.report_export_job["attempt_count"], 1)
        self.assertEqual(record.audit_events[0]["method_version"], "runtime_report_export_job_claim_v1")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE SKIP LOCKED", executed_sql)
        self.assertIn("UPDATE report_export_jobs SET status = %s", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_reads_report_export_job_queue_stats(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        now = datetime(2026, 6, 10, tzinfo=UTC)
        connection = RecordingConnection(
            result_sets=[
                {"count": 4},
                [{"status": "queued", "count": 2}, {"status": "running", "count": 1}, {"status": "dead_letter", "count": 1}],
                {
                    "retryable_count": 2,
                    "expired_running_count": 1,
                    "max_attempts_reached_count": 1,
                    "oldest_queued_at": now,
                },
            ]
        )

        stats = PostgresEvidenceRepository(connection).get_runtime_report_export_job_queue_stats(project_id=project_id)

        self.assertEqual(stats.total_count, 4)
        self.assertEqual(stats.status_counts["dead_letter"], 1)
        self.assertEqual(stats.retryable_count, 2)
        self.assertEqual(stats.expired_running_count, 1)
        self.assertEqual(stats.max_attempts_reached_count, 1)
        self.assertEqual(stats.oldest_queued_at, str(now))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("GROUP BY status", executed_sql)
        self.assertIn("lease_expires_at <= now()", executed_sql)
        self.assertIn("attempt_count >= max_attempts", executed_sql)

    def test_postgres_repository_updates_report_export_job_status_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        job_id = "8f4f2a24-d6cf-5050-96a4-942d2c337fd0"
        before_row = {
            "id": job_id,
            "project_id": project_id,
            "report_export_id": None,
            "status": "running",
            "artifact_type": "pdf",
            "template": "standard",
            "filters": {},
            "sort": "collected_at_desc",
            "requested_by": "runtime-console",
            "requested_at": now,
            "started_at": now,
            "completed_at": None,
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": now,
            "next_attempt_at": None,
            "artifact_url": None,
            "error_message": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [],
            "answer_run_ids": [],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {},
            "method_disclosure": {},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": None,
            "pdf_url": None,
            "csv_url": None,
            "exported_by": "system",
            "exported_at": now,
        }
        after_row = {
            **before_row,
            "report_export_id": report_export_id,
            "status": "succeeded",
            "completed_at": now,
            "artifact_url": "s3://geno-reports/report.pdf",
            "updated_at": now,
        }
        audit_row = {
            "id": "e011f214-7cf4-40e4-b73e-8cc4308cc7d9",
            "event_type": "report_export_job_status_updated",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "runtime-worker",
            "target_type": "report_export_job",
            "target_id": job_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"status": ["succeeded"], "report_export_job_ids": [job_id]},
            "output_refs": {"artifact_url": ["s3://geno-reports/report.pdf"]},
            "method_version": "runtime_report_export_job_status_v1",
            "reason": "artifact archived",
            "created_at": now,
        }
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "info",
            "title": "Report export succeeded",
            "message": "pdf/standard report export job succeeded. Artifact is ready.",
            "target_type": "report_export_job",
            "target_id": job_id,
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"report_export_job_id": job_id, "status": "succeeded"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[before_row, report_row, after_row, notification_row, [], [audit_row]])

        record = PostgresEvidenceRepository(connection).update_runtime_report_export_job_status(
            RuntimeReportExportJobStatusInput(
                job_id=job_id,
                status="succeeded",
                updated_by="runtime-worker",
                report_export_id=report_export_id,
                artifact_url="s3://geno-reports/report.pdf",
                reason="artifact archived",
            )
        )

        self.assertEqual(record.report_export_job["status"], "succeeded")
        self.assertEqual(record.report_export_job["artifact_url"], "s3://geno-reports/report.pdf")
        self.assertEqual(record.audit_events[0]["event_type"], "report_export_job_status_updated")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("UPDATE report_export_jobs SET status = %s", executed_sql)
        self.assertIn("INSERT INTO runtime_notifications", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_runtime_notifications_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "critical",
            "title": "Report export dead-lettered",
            "message": "pdf/standard report export job dead_letter.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "dead_letter"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        audit_row = {
            "id": "4fbc0529-5523-4879-a217-f0d07955ff69",
            "event_type": "runtime_notification_created",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "runtime-worker",
            "target_type": "runtime_notification",
            "target_id": notification_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"status": ["dead_letter"]},
            "output_refs": {"runtime_notification_ids": [notification_id]},
            "method_version": "runtime_notification_v1",
            "reason": "report export job dead_letter",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, {"count": 1}, [notification_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_notifications(
            project_id=project_id,
            status="unread",
            notification_type="report_export_job",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeNotificationPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.unread_count, 1)
        self.assertEqual(page.records[0].notification["severity"], "critical")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "runtime_notification_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM runtime_notifications WHERE project_id = %s AND status = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_updates_runtime_notification_status_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        before_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "info",
            "title": "Report export succeeded",
            "message": "pdf/standard report export job succeeded.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "succeeded"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        after_row = {
            **before_row,
            "status": "read",
            "read_at": now,
            "updated_by": "runtime-console",
        }
        audit_row = {
            "id": "b6b7c7c1-5d19-44c2-95e8-18437a84db53",
            "event_type": "runtime_notification_status_updated",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification",
            "target_id": notification_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"status": ["read"]},
            "output_refs": {"runtime_notification_ids": [notification_id], "status": ["read"]},
            "method_version": "runtime_notification_status_v1",
            "reason": "mark read",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[before_row, after_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).update_runtime_notification_status(
            RuntimeNotificationStatusInput(
                notification_id=notification_id,
                status="read",
                updated_by="runtime-console",
                reason="mark read",
            )
        )

        self.assertEqual(record.notification["status"], "read")
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_status_updated")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("UPDATE runtime_notifications SET status = %s", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_exports_runtime_notifications_csv(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        title = "Report export dead-lettered"
        message = "pdf/standard report export job dead_letter with raw detail"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "critical",
            "title": title,
            "message": message,
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {
                "status": "dead_letter",
                "artifact_type": "pdf",
                "template": "white_label",
                "raw_note": "do not export payload value",
            },
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        audit_row = {
            "id": "b6b7c7c1-5d19-44c2-95e8-18437a84db53",
            "event_type": "runtime_notification_created",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "runtime-worker",
            "target_type": "runtime_notification",
            "target_id": notification_id,
            "before_hash": None,
            "after_hash": "notification-after-hash",
            "input_refs": {"runtime_report_export_job_ids": ["job-1"]},
            "output_refs": {"runtime_notification_ids": [notification_id]},
            "method_version": "runtime_notification_v1",
            "reason": "queue terminal notification",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, {"count": 1}, [notification_row], [audit_row]])

        export = PostgresEvidenceRepository(connection).export_runtime_notifications_csv(
            project_id=project_id,
            status="unread",
            notification_type="report_export_job",
            limit=5,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_notifications_csv")
        self.assertEqual(export.filename, "runtime-notifications.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["status"], "unread")
        self.assertEqual(export.filters["notification_type"], "report_export_job")
        self.assertIn("notification_id,project_id,notification_type,severity,status,target_type", export.content)
        self.assertIn(notification_id, export.content)
        self.assertIn("dead_letter", export.content)
        self.assertIn("pdf", export.content)
        self.assertIn("white_label", export.content)
        self.assertIn("runtime_notification_v1", export.content)
        self.assertIn("notification-after-hash", export.content)
        self.assertIn(_artifact_hash(title), export.content)
        self.assertIn(_artifact_hash(message), export.content)
        self.assertNotIn(title, export.content)
        self.assertNotIn(message, export.content)
        self.assertNotIn("do not export payload value", export.content)

    def test_postgres_repository_saves_runtime_notification_subscription_with_audit_event(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "event_types": ["report_export_job"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {"source": "contract"},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "de6e0fec-0084-43c7-8f64-b16e412aab9e",
            "event_type": "runtime_notification_subscription_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_subscription",
            "target_id": subscription_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"event_types": ["report_export_job"]},
            "output_refs": {"runtime_notification_subscription_ids": [subscription_id]},
            "method_version": "runtime_notification_subscription_v1",
            "reason": "save webhook",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, subscription_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_runtime_notification_subscription(
            RuntimeNotificationSubscriptionInput(
                project_id=project_id,
                endpoint_url="https://hooks.example.com/geno",
                event_types=("report_export_job",),
                severity_threshold="warning",
                metadata={"source": "contract"},
                updated_by="runtime-console",
                reason="save webhook",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationSubscription)
        self.assertEqual(record.subscription["endpoint_url"], "https://hooks.example.com/geno")
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_subscription_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_notification_subscriptions", executed_sql)
        self.assertIn("ON CONFLICT (project_id, channel, endpoint_url) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_exports_runtime_notification_subscriptions_csv(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        endpoint_url = "https://hooks.example.com/geno/raw-secret-path"
        reply_to = "reports@example.com"
        unsubscribe_url = "https://app.example.com/notifications/unsubscribe"
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": endpoint_url,
            "event_types": ["report_export_job", "runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {
                "source": "contract",
                "signing_secret_env": "GENO_TEST_WEBHOOK_SECRET",
                "signing_secret_key_id": "current-v1",
                "previous_signing_secret_env": "GENO_TEST_WEBHOOK_SECRET_PREVIOUS",
                "previous_signing_secret_key_id": "previous-v1",
                "slack_channel": "#geno-alerts",
                "email_reply_to": reply_to,
                "email_unsubscribe_url": unsubscribe_url,
                "email_unsubscribe_mailto": "mailto:unsubscribe@example.com",
                "email_preferences_url": "https://app.example.com/notifications/preferences",
                "email_suppressed_recipient_hashes": [runtime_email_body_hash("muted@example.com")],
                "do_not_export": "raw metadata value",
            },
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "de6e0fec-0084-43c7-8f64-b16e412aab9e",
            "event_type": "runtime_notification_subscription_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_subscription",
            "target_id": subscription_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"event_types": ["report_export_job"]},
            "output_refs": {"runtime_notification_subscription_ids": [subscription_id]},
            "method_version": "runtime_notification_subscription_v1",
            "reason": "save webhook",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [subscription_row], [audit_row]])

        export = PostgresEvidenceRepository(connection).export_runtime_notification_subscriptions_csv(
            project_id=project_id,
            status="active",
            limit=5,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_notification_subscriptions_csv")
        self.assertEqual(export.filename, "runtime-notification-subscriptions.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["status"], "active")
        self.assertIn("subscription_id,project_id,channel,endpoint_url_hash,event_types", export.content)
        self.assertIn(subscription_id, export.content)
        self.assertIn("report_export_job|runtime_alert", export.content)
        self.assertIn("runtime_notification_subscription_v1", export.content)
        self.assertIn("signing_secret_env", export.content)
        self.assertIn(_artifact_hash(endpoint_url), export.content)
        self.assertIn(runtime_email_body_hash(reply_to), export.content)
        self.assertIn(_artifact_hash(unsubscribe_url), export.content)
        self.assertNotIn(endpoint_url, export.content)
        self.assertNotIn("raw-secret-path", export.content)
        self.assertNotIn("raw metadata value", export.content)
        self.assertNotIn("muted@example.com", export.content)

    def test_postgres_repository_saves_slack_notification_subscription_with_audit_event(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "slack",
            "endpoint_url": "https://hooks.slack.com/services/T000/B000/XXX",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {"source": "contract", "slack_channel": "#geno-alerts"},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "de6e0fec-0084-43c7-8f64-b16e412aab9e",
            "event_type": "runtime_notification_subscription_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_subscription",
            "target_id": subscription_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"event_types": ["runtime_alert"]},
            "output_refs": {"runtime_notification_subscription_ids": [subscription_id]},
            "method_version": "runtime_notification_subscription_v1",
            "reason": "save slack subscription",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, subscription_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_runtime_notification_subscription(
            RuntimeNotificationSubscriptionInput(
                project_id=project_id,
                channel="slack",
                endpoint_url="https://hooks.slack.com/services/T000/B000/XXX",
                event_types=("runtime_alert",),
                severity_threshold="warning",
                metadata={"source": "contract", "slack_channel": "#geno-alerts"},
                updated_by="runtime-console",
                reason="save slack subscription",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationSubscription)
        self.assertEqual(record.subscription["channel"], "slack")
        self.assertEqual(record.subscription["metadata"]["slack_channel"], "#geno-alerts")
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_subscription_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_notification_subscriptions", executed_sql)
        self.assertIn("ON CONFLICT (project_id, channel, endpoint_url) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_saves_email_notification_subscription_with_audit_event(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {"source": "contract", "email_reply_to": "reports@example.com"},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "de6e0fec-0084-43c7-8f64-b16e412aab9e",
            "event_type": "runtime_notification_subscription_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_subscription",
            "target_id": subscription_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"event_types": ["runtime_alert"]},
            "output_refs": {"runtime_notification_subscription_ids": [subscription_id]},
            "method_version": "runtime_notification_subscription_v1",
            "reason": "save email subscription",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, subscription_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_runtime_notification_subscription(
            RuntimeNotificationSubscriptionInput(
                project_id=project_id,
                channel="email",
                endpoint_url="mailto:ops@example.com",
                event_types=("runtime_alert",),
                severity_threshold="warning",
                metadata={"source": "contract", "email_reply_to": "reports@example.com"},
                updated_by="runtime-console",
                reason="save email subscription",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationSubscription)
        self.assertEqual(record.subscription["channel"], "email")
        self.assertEqual(record.subscription["endpoint_url"], "mailto:ops@example.com")
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_subscription_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_notification_subscriptions", executed_sql)
        self.assertIn("ON CONFLICT (project_id, channel, endpoint_url) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_queues_notification_delivery_for_matching_subscription(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        job_id = "8f4f2a24-d6cf-5050-96a4-942d2c337fd0"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        before_row = {
            "id": job_id,
            "project_id": project_id,
            "report_export_id": None,
            "status": "running",
            "artifact_type": "pdf",
            "template": "standard",
            "filters": {},
            "sort": "collected_at_desc",
            "requested_by": "runtime-console",
            "requested_at": now,
            "started_at": now,
            "completed_at": None,
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": now,
            "next_attempt_at": None,
            "artifact_url": None,
            "error_message": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [],
            "answer_run_ids": [],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {},
            "method_disclosure": {},
            "methodology_hash": "method-hash",
            "sample_size": 0,
            "window_start": now,
            "window_end": now,
            "exported_by": "runtime-worker",
            "exported_at": now,
            "artifact_url": None,
        }
        after_row = {**before_row, "status": "succeeded", "report_export_id": report_export_id, "artifact_url": "s3://geno-reports/report.pdf"}
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "info",
            "title": "Report export succeeded",
            "message": "pdf/standard report export job succeeded. Artifact is ready.",
            "target_type": "report_export_job",
            "target_id": job_id,
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"report_export_job_id": job_id, "status": "succeeded"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "event_types": ["report_export_job"],
            "severity_threshold": "info",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_v1"},
            "created_at": now,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        audit_row = {
            "id": "e011f214-7cf4-40e4-b73e-8cc4308cc7d9",
            "event_type": "report_export_job_status_updated",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "runtime-worker",
            "target_type": "report_export_job",
            "target_id": job_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"status": ["succeeded"]},
            "output_refs": {"artifact_url": ["s3://geno-reports/report.pdf"]},
            "method_version": "runtime_report_export_job_status_v1",
            "reason": "artifact archived",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[before_row, report_row, after_row, notification_row, [subscription_row], delivery_row, [audit_row]]
        )

        record = PostgresEvidenceRepository(connection).update_runtime_report_export_job_status(
            RuntimeReportExportJobStatusInput(
                job_id=job_id,
                status="succeeded",
                updated_by="runtime-worker",
                report_export_id=report_export_id,
                artifact_url="s3://geno-reports/report.pdf",
                reason="artifact archived",
            )
        )

        self.assertEqual(record.report_export_job["status"], "succeeded")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT id, project_id, channel, endpoint_url, event_types", executed_sql)
        self.assertIn("INSERT INTO runtime_notification_deliveries", executed_sql)
        inserted_audit_params = [params for sql, params in connection.calls if "INSERT INTO audit_events" in sql][-1]
        self.assertIn("runtime_notification_delivery_queued", str(inserted_audit_params))

    def test_postgres_repository_queues_slack_notification_delivery_payload(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "runtime_alert",
            "severity": "critical",
            "title": "Brand absent in Sydney",
            "message": "Brand was absent from critical AI search prompts.",
            "target_type": "runtime_alert",
            "target_id": "brand_absent:project-1",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"alert_type": "brand_absent"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "slack",
            "endpoint_url": "https://hooks.slack.com/services/T000/B000/XXX",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {"slack_channel": "#geno-alerts"},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "slack",
            "endpoint_url": "https://hooks.slack.com/services/T000/B000/XXX",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_slack_v1"},
            "created_at": now,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[[subscription_row], delivery_row])
        repository = PostgresEvidenceRepository(connection)

        with connection.cursor() as cursor:
            deliveries, audit_events = repository._enqueue_runtime_notification_deliveries(
                cursor=cursor,
                notification=notification_row,
                updated_by="runtime-worker",
            )

        self.assertEqual(deliveries[0]["channel"], "slack")
        self.assertEqual(audit_events[0].event_type, "runtime_notification_delivery_queued")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("channel = ANY(%s)", executed_sql)
        delivery_insert_params = next(
            params for sql, params in connection.calls if "INSERT INTO runtime_notification_deliveries" in sql
        )
        self.assertEqual(delivery_insert_params[4], "slack")
        self.assertIn("https://hooks.slack.com/services/T000/B000/XXX", str(delivery_insert_params[5]))
        self.assertIn("runtime_notification_delivery_slack_v1", str(delivery_insert_params[8]))
        self.assertIn("Brand absent in Sydney", str(delivery_insert_params[8]))
        self.assertIn("blocks", str(delivery_insert_params[8]))

    def test_postgres_repository_queues_email_notification_delivery_payload(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "runtime_alert",
            "severity": "critical",
            "title": "Brand absent in Sydney",
            "message": "Brand was absent from critical AI search prompts.",
            "target_type": "runtime_alert",
            "target_id": "brand_absent:project-1",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"alert_type": "brand_absent"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com,muted@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {
                "email_reply_to": "reports@example.com",
                "email_unsubscribe_url": "https://app.example.com/notifications/unsubscribe",
                "email_unsubscribe_mailto": "mailto:unsubscribe@example.com",
                "email_preferences_url": "https://app.example.com/notifications/preferences",
                "email_suppressed_recipients": ["muted@example.com"],
            },
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com,muted@example.com",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[[subscription_row], [], delivery_row])
        repository = PostgresEvidenceRepository(
            connection,
            email_preference_base_url="https://app.example.com/notifications/unsubscribe",
            email_preference_token_secret="preference-secret",
            email_preference_token_ttl_seconds=3600,
        )

        with connection.cursor() as cursor:
            deliveries, audit_events = repository._enqueue_runtime_notification_deliveries(
                cursor=cursor,
                notification=notification_row,
                updated_by="runtime-worker",
            )

        self.assertEqual(deliveries[0]["channel"], "email")
        self.assertEqual(audit_events[0].event_type, "runtime_notification_delivery_queued")
        delivery_insert_params = next(
            params for sql, params in connection.calls if "INSERT INTO runtime_notification_deliveries" in sql
        )
        self.assertEqual(delivery_insert_params[4], "email")
        self.assertEqual(delivery_insert_params[5], "mailto:ops@example.com,muted@example.com")
        self.assertIn("runtime_notification_delivery_email_v1", str(delivery_insert_params[8]))
        self.assertIn("ops@example.com", str(delivery_insert_params[8]))
        self.assertNotIn('"muted@example.com"', str(delivery_insert_params[8]))
        self.assertIn("[GENO CRITICAL] Brand absent in Sydney", str(delivery_insert_params[8]))
        self.assertIn(RUNTIME_NOTIFICATION_EMAIL_TEMPLATE_VERSION, str(delivery_insert_params[8]))
        self.assertIn("email_template_hash", str(delivery_insert_params[8]))
        self.assertIn("email_subject_hash", str(delivery_insert_params[8]))
        self.assertIn("email_body_hash", str(delivery_insert_params[8]))
        self.assertIn("List-Unsubscribe", str(delivery_insert_params[8]))
        self.assertIn("List-Unsubscribe=One-Click", str(delivery_insert_params[8]))
        self.assertIn("token=", str(delivery_insert_params[8]))
        self.assertIn("email_preference_token_hash", str(delivery_insert_params[8]))
        self.assertIn("email_preference_manage_token_hash", str(delivery_insert_params[8]))
        self.assertIn("email_tokenized_unsubscribe_url_hash", str(delivery_insert_params[8]))
        self.assertIn("email_tokenized_preferences_url_hash", str(delivery_insert_params[8]))
        self.assertNotIn("preference-secret", str(delivery_insert_params[8]))
        self.assertIn("Reply-To", str(delivery_insert_params[8]))
        self.assertIn("X-GENO-Notification-Preferences-Url", str(delivery_insert_params[8]))
        self.assertIn("Notification controls:", str(delivery_insert_params[8]))
        self.assertIn("email_control_hashes", str(delivery_insert_params[8]))
        self.assertIn("email_reply_to_hash", str(delivery_insert_params[8]))
        self.assertIn("email_suppressed_recipient_hashes", str(delivery_insert_params[8]))
        self.assertIn("email_filtered_recipient_count", str(delivery_insert_params[8]))
        self.assertIn("email_template_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_subject_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_body_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_reply_to_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_control_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_preference_token_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_preference_manage_token_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_tokenized_unsubscribe_url_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_tokenized_preferences_url_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_suppressed_recipient_hashes", str(audit_events[0].output_refs))

    def test_postgres_repository_suppresses_email_notification_delivery_when_all_recipients_filtered(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "runtime_alert",
            "severity": "critical",
            "title": "Brand absent in Sydney",
            "message": "Brand was absent from critical AI search prompts.",
            "target_type": "runtime_alert",
            "target_id": "brand_absent:project-1",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"alert_type": "brand_absent"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com,muted@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {"email_suppressed_recipients": "ops@example.com, muted@example.com"},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[[subscription_row], []])
        repository = PostgresEvidenceRepository(connection)

        with connection.cursor() as cursor:
            deliveries, audit_events = repository._enqueue_runtime_notification_deliveries(
                cursor=cursor,
                notification=notification_row,
                updated_by="runtime-worker",
            )

        self.assertEqual(deliveries, ())
        self.assertEqual(len(audit_events), 1)
        self.assertEqual(audit_events[0].event_type, "runtime_notification_delivery_suppressed")
        self.assertEqual(audit_events[0].target_type, "runtime_notification_subscription")
        self.assertIn("email_suppressed_recipient_hashes", str(audit_events[0].output_refs))
        self.assertIn("email_configured_suppression_hashes", str(audit_events[0].output_refs))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertNotIn("INSERT INTO runtime_notification_deliveries", executed_sql)

    def test_postgres_repository_suppresses_email_notification_delivery_by_recipient_hash(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        muted_hash = runtime_email_body_hash("muted@example.com")
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "runtime_alert",
            "severity": "critical",
            "title": "Brand absent in Sydney",
            "message": "Brand was absent from critical AI search prompts.",
            "target_type": "runtime_alert",
            "target_id": "brand_absent:project-1",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"alert_type": "brand_absent"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com,muted@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {"email_suppressed_recipient_hashes": [muted_hash]},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": "118e5c66-7bb4-558e-ab97-e74ef9928b46",
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com,muted@example.com",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[[subscription_row], [], delivery_row])
        repository = PostgresEvidenceRepository(connection)

        with connection.cursor() as cursor:
            deliveries, audit_events = repository._enqueue_runtime_notification_deliveries(
                cursor=cursor,
                notification=notification_row,
                updated_by="runtime-worker",
            )

        self.assertEqual(deliveries[0]["channel"], "email")
        self.assertEqual(audit_events[0].event_type, "runtime_notification_delivery_queued")
        delivery_insert_params = next(
            params for sql, params in connection.calls if "INSERT INTO runtime_notification_deliveries" in sql
        )
        self.assertIn("ops@example.com", str(delivery_insert_params[8]))
        self.assertNotIn('"muted@example.com"', str(delivery_insert_params[8]))
        self.assertIn(muted_hash, str(delivery_insert_params[8]))
        self.assertIn(muted_hash, str(audit_events[0].output_refs))

    def test_postgres_repository_suppresses_email_notification_delivery_by_project_suppression_hash(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        muted_hash = runtime_email_body_hash("muted@example.com")
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "runtime_alert",
            "severity": "critical",
            "title": "Brand absent in Sydney",
            "message": "Brand was absent from critical AI search prompts.",
            "target_type": "runtime_alert",
            "target_id": "brand_absent:project-1",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"alert_type": "brand_absent"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com,muted@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": "118e5c66-7bb4-558e-ab97-e74ef9928b46",
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com,muted@example.com",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        connection = RecordingConnection(
            result_sets=[[subscription_row], [{"recipient_hash": muted_hash}], delivery_row]
        )
        repository = PostgresEvidenceRepository(connection)

        with connection.cursor() as cursor:
            deliveries, audit_events = repository._enqueue_runtime_notification_deliveries(
                cursor=cursor,
                notification=notification_row,
                updated_by="runtime-worker",
            )

        self.assertEqual(deliveries[0]["channel"], "email")
        delivery_insert_params = next(
            params for sql, params in connection.calls if "INSERT INTO runtime_notification_deliveries" in sql
        )
        self.assertIn("ops@example.com", str(delivery_insert_params[8]))
        self.assertNotIn('"muted@example.com"', str(delivery_insert_params[8]))
        self.assertIn("email_project_suppression_hashes", str(delivery_insert_params[8]))
        self.assertIn(muted_hash, str(delivery_insert_params[8]))
        self.assertIn(muted_hash, str(audit_events[0].output_refs))
        self.assertIn("email_project_suppression_hash_count", str(audit_events[0].output_refs))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM runtime_notification_email_suppressions", executed_sql)

    def test_postgres_repository_lists_runtime_notification_deliveries_with_context(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "warning",
            "title": "Report export failed",
            "message": "pdf/standard report export job failed.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "failed"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "event_types": ["report_export_job"],
            "severity_threshold": "info",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_v1"},
            "created_at": now,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        audit_row = {
            "id": "37931ff6-07d0-4825-8d41-46b7d197f98e",
            "event_type": "runtime_notification_delivery_queued",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "runtime-worker",
            "target_type": "runtime_notification_delivery",
            "target_id": delivery_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"runtime_notification_ids": [notification_id]},
            "output_refs": {"runtime_notification_delivery_ids": [delivery_id]},
            "method_version": "runtime_notification_delivery_v1",
            "reason": "queue runtime notification delivery",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [delivery_row], notification_row, subscription_row, [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_notification_deliveries(
            project_id=project_id,
            status="queued",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeNotificationDeliveryPage)
        self.assertIsInstance(page.records[0], RuntimeNotificationDelivery)
        self.assertEqual(page.records[0].notification["title"], "Report export failed")
        self.assertEqual(page.records[0].subscription["endpoint_url"], "https://hooks.example.com/geno")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "runtime_notification_delivery_queued")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM runtime_notification_deliveries WHERE project_id = %s AND status = %s", executed_sql)

    def test_postgres_repository_exports_runtime_notification_deliveries_csv(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        endpoint_url = "https://hooks.example.com/geno/raw-secret-path"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "warning",
            "title": "Report export failed",
            "message": "pdf/standard report export job failed.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "failed"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": endpoint_url,
            "event_types": ["report_export_job"],
            "severity_threshold": "info",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "webhook",
            "endpoint_url": endpoint_url,
            "status": "dead_letter",
            "attempt_count": 3,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": 500,
            "response_body_hash": "response-body-hash",
            "error_message": "webhook secret leaked in upstream error",
            "payload": {
                "delivery_version": "runtime_notification_delivery_v1",
                "metadata": {
                    "signing_secret_env": "GENO_TEST_WEBHOOK_SECRET",
                    "do_not_export": "raw payload metadata value",
                },
            },
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        }
        audit_row = {
            "id": "37931ff6-07d0-4825-8d41-46b7d197f98e",
            "event_type": "runtime_notification_delivery_status_updated",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "notification-worker",
            "target_type": "runtime_notification_delivery",
            "target_id": delivery_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"runtime_notification_delivery_ids": [delivery_id]},
            "output_refs": {"runtime_notification_delivery_ids": [delivery_id]},
            "method_version": "runtime_notification_delivery_status_v1",
            "reason": "runtime notification delivery dead-lettered",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [delivery_row], notification_row, subscription_row, [audit_row]])

        export = PostgresEvidenceRepository(connection).export_runtime_notification_deliveries_csv(
            project_id=project_id,
            status="dead_letter",
            limit=5,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_notification_deliveries_csv")
        self.assertEqual(export.filename, "runtime-notification-deliveries.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["status"], "dead_letter")
        self.assertIn("delivery_id,project_id,notification_id,subscription_id,channel,endpoint_url_hash", export.content)
        self.assertIn(delivery_id, export.content)
        self.assertIn("dead_letter", export.content)
        self.assertIn("runtime_notification_delivery_status_v1", export.content)
        self.assertIn("payload_metadata_keys", export.content)
        self.assertIn("signing_secret_env", export.content)
        self.assertIn(_artifact_hash(endpoint_url), export.content)
        self.assertIn(_artifact_hash("webhook secret leaked in upstream error"), export.content)
        self.assertNotIn(endpoint_url, export.content)
        self.assertNotIn("raw-secret-path", export.content)
        self.assertNotIn("raw payload metadata value", export.content)
        self.assertNotIn("webhook secret leaked in upstream error", export.content)

    def test_postgres_repository_claims_next_runtime_notification_delivery_with_audit_event(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        before_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_v1"},
            "created_at": now,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        after_row = {**before_row, "status": "sending", "attempt_count": 1, "lease_expires_at": now, "updated_by": "notification-worker"}
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "info",
            "title": "Report export succeeded",
            "message": "pdf/standard report export job succeeded.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "succeeded"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "event_types": ["report_export_job"],
            "severity_threshold": "info",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "37931ff6-07d0-4825-8d41-46b7d197f98e",
            "event_type": "runtime_notification_delivery_status_updated",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "notification-worker",
            "target_type": "runtime_notification_delivery",
            "target_id": delivery_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"status": ["sending"]},
            "output_refs": {"runtime_notification_delivery_ids": [delivery_id]},
            "method_version": "runtime_notification_delivery_claim_v1",
            "reason": "claim runtime notification delivery",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[before_row, after_row, notification_row, subscription_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).claim_next_runtime_notification_delivery(
            updated_by="notification-worker",
            lease_seconds=120,
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.delivery["status"], "sending")
        self.assertEqual(record.delivery["attempt_count"], 1)
        self.assertEqual(record.audit_events[0]["method_version"], "runtime_notification_delivery_claim_v1")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE SKIP LOCKED", executed_sql)
        self.assertIn("UPDATE runtime_notification_deliveries SET status = %s", executed_sql)

    def test_postgres_repository_updates_runtime_notification_delivery_status_with_audit_event(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        before_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "status": "sending",
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": now,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_v1"},
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        }
        after_row = {
            **before_row,
            "status": "delivered",
            "lease_expires_at": None,
            "response_status": 204,
            "response_body_hash": "response-hash",
        }
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "info",
            "title": "Report export succeeded",
            "message": "pdf/standard report export job succeeded.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "succeeded"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "event_types": ["report_export_job"],
            "severity_threshold": "info",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_delivery_status_updated",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "notification-worker",
            "target_type": "runtime_notification_delivery",
            "target_id": delivery_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"status": ["delivered"]},
            "output_refs": {"response_status": ["204"]},
            "method_version": "runtime_notification_delivery_status_v1",
            "reason": "delivered",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[before_row, after_row, notification_row, subscription_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).update_runtime_notification_delivery_status(
            RuntimeNotificationDeliveryStatusInput(
                delivery_id=delivery_id,
                status="delivered",
                updated_by="notification-worker",
                response_status=204,
                response_body_hash="response-hash",
                reason="delivered",
            )
        )

        self.assertEqual(record.delivery["status"], "delivered")
        self.assertEqual(record.delivery["response_status"], 204)
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_delivery_status_updated")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("UPDATE runtime_notification_deliveries SET status = %s", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_records_runtime_notification_email_feedback_with_hash_refs(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        feedback_id = "a0129f72-7ac9-48d5-89cf-32d9b897b02d"
        recipient_hash = runtime_email_body_hash("ops@example.com")
        provider_event_id_hash = runtime_email_body_hash("smtp-bounce-1")
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "status": "delivered",
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": 250,
            "response_body_hash": "smtp-response-hash",
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        }
        feedback_row = {
            "id": feedback_id,
            "project_id": project_id,
            "delivery_id": delivery_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "feedback_type": "bounce",
            "recipient_hash": recipient_hash,
            "provider": "smtp",
            "provider_event_id_hash": provider_event_id_hash,
            "occurred_at": now,
            "metadata": {"source": "manual"},
            "recorded_by": "runtime-console",
            "created_at": now,
        }
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "warning",
            "title": "Report export failed",
            "message": "pdf/standard report export job failed.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "failed"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "event_types": ["report_export_job"],
            "severity_threshold": "info",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_feedback_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_delivery",
            "target_id": delivery_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"feedback_type": ["bounce"]},
            "output_refs": {
                "runtime_notification_email_feedback_event_ids": [feedback_id],
                "recipient_hashes": [recipient_hash],
                "provider_event_id_hashes": [provider_event_id_hash],
            },
            "method_version": "runtime_notification_email_feedback_v1",
            "reason": "record bounce",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[delivery_row, [], feedback_row, notification_row, subscription_row, [audit_row]]
        )

        record = PostgresEvidenceRepository(connection).record_runtime_notification_email_feedback(
            RuntimeNotificationEmailFeedbackInput(
                delivery_id=delivery_id,
                feedback_type="bounce",
                recipient="Ops@Example.com",
                provider="smtp",
                provider_event_id="smtp-bounce-1",
                occurred_at=now,
                metadata={"source": "manual"},
                recorded_by="runtime-console",
                reason="record bounce",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationEmailFeedback)
        self.assertEqual(record.feedback_event["feedback_type"], "bounce")
        self.assertEqual(record.feedback_event["recipient_hash"], recipient_hash)
        self.assertEqual(record.feedback_event["provider_event_id_hash"], provider_event_id_hash)
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_email_feedback_recorded")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_notification_email_feedback_events", executed_sql)
        inserted_feedback_params = [
            params for sql, params in connection.calls if "INSERT INTO runtime_notification_email_feedback_events" in sql
        ][0]
        self.assertIn(recipient_hash, str(inserted_feedback_params))
        self.assertIn(provider_event_id_hash, str(inserted_feedback_params))
        self.assertNotIn("Ops@Example.com", str(inserted_feedback_params))
        self.assertNotIn("smtp-bounce-1", str(inserted_feedback_params))

    def test_postgres_repository_ignores_duplicate_runtime_notification_email_feedback_provider_event(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        feedback_id = "a0129f72-7ac9-48d5-89cf-32d9b897b02d"
        recipient_hash = runtime_email_body_hash("ops@example.com")
        provider_event_id_hash = runtime_email_body_hash("smtp-bounce-1")
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "status": "delivered",
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": 250,
            "response_body_hash": "smtp-response-hash",
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        }
        existing_feedback_row = {
            "id": feedback_id,
            "project_id": project_id,
            "delivery_id": delivery_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "feedback_type": "bounce",
            "recipient_hash": recipient_hash,
            "provider": "smtp",
            "provider_event_id_hash": provider_event_id_hash,
            "occurred_at": now,
            "metadata": {"source": "email-feedback-webhook"},
            "recorded_by": "email-feedback-webhook",
            "created_at": now,
        }
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "warning",
            "title": "Report export failed",
            "message": "pdf/standard report export job failed.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "failed"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "event_types": ["report_export_job"],
            "severity_threshold": "info",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        duplicate_audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_feedback_duplicate_ignored",
            "project_id": project_id,
            "actor_type": "system",
            "actor_id": "email-feedback-webhook",
            "target_type": "runtime_notification_delivery",
            "target_id": delivery_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "feedback_type": ["bounce"],
                "provider_event_id_hashes": [provider_event_id_hash],
            },
            "output_refs": {
                "runtime_notification_email_feedback_event_ids": [feedback_id],
                "duplicate_ignored": [True],
            },
            "method_version": "runtime_notification_email_feedback_idempotency_v1",
            "reason": "ignore duplicate bounce",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                delivery_row,
                existing_feedback_row,
                notification_row,
                subscription_row,
                [duplicate_audit_row],
            ]
        )

        record = PostgresEvidenceRepository(connection).record_runtime_notification_email_feedback(
            RuntimeNotificationEmailFeedbackInput(
                delivery_id=delivery_id,
                feedback_type="bounce",
                recipient="Ops@Example.com",
                provider="smtp",
                provider_event_id="smtp-bounce-1",
                occurred_at=now,
                metadata={"source": "retry"},
                recorded_by="email-feedback-webhook",
                reason="ignore duplicate bounce",
            )
        )

        self.assertEqual(record.feedback_event["id"], feedback_id)
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_email_feedback_duplicate_ignored")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("provider_event_id_hash = %s", executed_sql)
        self.assertNotIn("INSERT INTO runtime_notification_email_feedback_events", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        inserted_audit_params = [params for sql, params in connection.calls if "INSERT INTO audit_events" in sql][0]
        self.assertIn("system", str(inserted_audit_params))
        self.assertIn("email-feedback-webhook", str(inserted_audit_params))

    def test_postgres_repository_lists_runtime_notification_email_feedback_with_context(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        feedback_id = "a0129f72-7ac9-48d5-89cf-32d9b897b02d"
        feedback_row = {
            "id": feedback_id,
            "project_id": project_id,
            "delivery_id": delivery_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "feedback_type": "complaint",
            "recipient_hash": runtime_email_body_hash("ops@example.com"),
            "provider": "smtp",
            "provider_event_id_hash": runtime_email_body_hash("smtp-feedback-1"),
            "occurred_at": now,
            "metadata": {"source": "manual"},
            "recorded_by": "runtime-console",
            "created_at": now,
        }
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "status": "delivered",
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": 250,
            "response_body_hash": "smtp-response-hash",
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        }
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "report_export_job",
            "severity": "warning",
            "title": "Report export failed",
            "message": "pdf/standard report export job failed.",
            "target_type": "report_export_job",
            "target_id": "8f4f2a24-d6cf-5050-96a4-942d2c337fd0",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"status": "failed"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "event_types": ["report_export_job"],
            "severity_threshold": "info",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_feedback_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_delivery",
            "target_id": delivery_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"feedback_type": ["complaint"]},
            "output_refs": {"runtime_notification_email_feedback_event_ids": [feedback_id]},
            "method_version": "runtime_notification_email_feedback_v1",
            "reason": "record complaint",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[{"count": 1}, [feedback_row], delivery_row, notification_row, subscription_row, [audit_row]]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_notification_email_feedback_events(
            project_id=project_id,
            delivery_id=delivery_id,
            feedback_type="complaint",
            provider="smtp",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeNotificationEmailFeedbackPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].feedback_event["feedback_type"], "complaint")
        self.assertEqual(page.records[0].delivery["channel"], "email")
        self.assertEqual(page.records[0].notification["title"], "Report export failed")
        self.assertEqual(page.records[0].subscription["channel"], "email")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "runtime_notification_email_feedback_recorded")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn(
            "FROM runtime_notification_email_feedback_events WHERE project_id = %s AND delivery_id = %s",
            executed_sql,
        )

    def test_postgres_repository_applies_runtime_notification_email_feedback_suppression(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        feedback_id = "a0129f72-7ac9-48d5-89cf-32d9b897b02d"
        existing_hash = runtime_email_body_hash("existing@example.com")
        recipient_hash = runtime_email_body_hash("ops@example.com")
        feedback_row = {
            "id": feedback_id,
            "project_id": project_id,
            "delivery_id": delivery_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "feedback_type": "complaint",
            "recipient_hash": recipient_hash,
            "provider": "smtp",
            "provider_event_id_hash": runtime_email_body_hash("smtp-feedback-1"),
            "occurred_at": now,
            "metadata": {"source": "manual"},
            "recorded_by": "runtime-console",
            "created_at": now,
        }
        subscription_before = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com,muted@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {
                "source": "api-test",
                "email_suppressed_recipient_hashes": [existing_hash],
                "email_suppression_feedback_event_ids": ["existing-feedback"],
            },
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        subscription_after = {
            **subscription_before,
            "metadata": {
                "source": "api-test",
                "email_suppressed_recipient_hashes": [existing_hash, recipient_hash],
                "email_suppression_feedback_event_ids": ["existing-feedback", feedback_id],
            },
            "updated_by": "runtime-console",
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_feedback_suppression_applied",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_subscription",
            "target_id": subscription_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"runtime_notification_email_feedback_event_ids": [feedback_id]},
            "output_refs": {"email_suppression_hashes": [existing_hash, recipient_hash]},
            "method_version": "runtime_notification_email_feedback_suppression_v1",
            "reason": "apply complaint suppression",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[feedback_row, subscription_before, subscription_after, [audit_row]])

        record = PostgresEvidenceRepository(connection).apply_runtime_notification_email_feedback_suppression(
            RuntimeNotificationEmailFeedbackSuppressionInput(
                feedback_event_id=feedback_id,
                updated_by="runtime-console",
                reason="apply complaint suppression",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationSubscription)
        self.assertEqual(record.subscription["metadata"]["email_suppressed_recipient_hashes"], [existing_hash, recipient_hash])
        self.assertEqual(record.subscription["metadata"]["email_suppression_feedback_event_ids"], ["existing-feedback", feedback_id])
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_email_feedback_suppression_applied")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("UPDATE runtime_notification_subscriptions SET metadata = %s", executed_sql)
        update_params = [
            params for sql, params in connection.calls if "UPDATE runtime_notification_subscriptions SET metadata" in sql
        ][0]
        self.assertIn(recipient_hash, str(update_params))
        self.assertIn(feedback_id, str(update_params))
        self.assertNotIn("ops@example.com", str(update_params))

    def test_postgres_repository_applies_runtime_notification_email_feedback_project_suppression(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        feedback_id = "a0129f72-7ac9-48d5-89cf-32d9b897b02d"
        suppression_id = "29b509ef-0c07-4588-a6ed-e0d25d48cfb2"
        recipient_hash = runtime_email_body_hash("ops@example.com")
        provider_event_id_hash = runtime_email_body_hash("smtp-feedback-1")
        feedback_row = {
            "id": feedback_id,
            "project_id": project_id,
            "delivery_id": delivery_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "feedback_type": "complaint",
            "recipient_hash": recipient_hash,
            "provider": "smtp",
            "provider_event_id_hash": provider_event_id_hash,
            "occurred_at": now,
            "metadata": {"source": "manual"},
            "recorded_by": "runtime-console",
            "created_at": now,
        }
        suppression_row = {
            "id": suppression_id,
            "project_id": project_id,
            "recipient_hash": recipient_hash,
            "status": "active",
            "source": "feedback",
            "source_ref": feedback_id,
            "metadata": {
                "source": "runtime_notification_email_feedback_project_suppression",
                "feedback_event_id": feedback_id,
                "delivery_id": delivery_id,
                "notification_id": notification_id,
                "subscription_id": subscription_id,
                "feedback_type": "complaint",
                "recipient_hash": recipient_hash,
                "provider": "smtp",
                "provider_event_id_hash": provider_event_id_hash,
                "note": "manual review",
            },
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[feedback_row, None, suppression_row])

        record = PostgresEvidenceRepository(connection).apply_runtime_notification_email_feedback_project_suppression(
            RuntimeNotificationEmailFeedbackProjectSuppressionInput(
                feedback_event_id=feedback_id,
                metadata={"note": "manual review"},
                updated_by="runtime-console",
                reason="apply complaint project suppression",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationEmailSuppression)
        self.assertEqual(record.suppression["id"], suppression_id)
        self.assertEqual(record.suppression["recipient_hash"], recipient_hash)
        self.assertEqual(record.suppression["source"], "feedback")
        self.assertEqual(record.suppression["source_ref"], feedback_id)
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_email_feedback_project_suppression_applied")
        self.assertEqual(record.audit_events[0]["method_version"], "runtime_notification_email_feedback_project_suppression_v1")
        self.assertEqual(record.audit_events[0]["input_refs"]["recipient_hashes"], [recipient_hash])
        self.assertEqual(record.audit_events[0]["input_refs"]["provider_event_id_hashes"], [provider_event_id_hash])
        self.assertEqual(record.audit_events[0]["output_refs"]["runtime_notification_email_suppression_ids"], [suppression_id])
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_notification_email_suppressions", executed_sql)
        self.assertIn("ON CONFLICT (project_id, recipient_hash) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        insert_params = [
            params for sql, params in connection.calls if "INSERT INTO runtime_notification_email_suppressions" in sql
        ][0]
        self.assertIn(recipient_hash, str(insert_params))
        self.assertIn(feedback_id, str(insert_params))
        self.assertIn("runtime_notification_email_feedback_project_suppression", str(insert_params))
        self.assertNotIn("ops@example.com", str(connection.calls))
        self.assertNotIn("smtp-feedback-1", str(connection.calls))

    def test_postgres_repository_rejects_raw_metadata_for_feedback_project_suppression(self) -> None:
        connection = RecordingConnection()

        with self.assertRaisesRegex(ValueError, "metadata must be hash-only"):
            PostgresEvidenceRepository(connection).apply_runtime_notification_email_feedback_project_suppression(
                RuntimeNotificationEmailFeedbackProjectSuppressionInput(
                    feedback_event_id="a0129f72-7ac9-48d5-89cf-32d9b897b02d",
                    metadata={"recipient": "ops@example.com"},
                    updated_by="runtime-console",
                    reason="apply complaint project suppression",
                )
            )

        self.assertEqual(connection.commit_count, 0)
        self.assertEqual(connection.calls, [])

    def test_postgres_repository_saves_runtime_notification_email_suppression_with_hash_only_audit(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        suppression_id = "29b509ef-0c07-4588-a6ed-e0d25d48cfb2"
        recipient_hash = runtime_email_body_hash("ops@example.com")
        suppression_row = {
            "id": suppression_id,
            "project_id": project_id,
            "recipient_hash": recipient_hash,
            "status": "active",
            "source": "manual",
            "source_ref": "support-ticket-1",
            "metadata": {"source": "contract"},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[None, suppression_row])

        record = PostgresEvidenceRepository(connection).save_runtime_notification_email_suppression(
            RuntimeNotificationEmailSuppressionInput(
                project_id=project_id,
                recipient_hash=recipient_hash,
                status="active",
                source="manual",
                source_ref="support-ticket-1",
                metadata={"source": "contract"},
                updated_by="runtime-console",
                reason="manual project suppression",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationEmailSuppression)
        self.assertEqual(record.suppression["recipient_hash"], recipient_hash)
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_email_suppression_saved")
        self.assertEqual(record.audit_events[0]["method_version"], "runtime_notification_email_suppression_v1")
        self.assertEqual(record.audit_events[0]["input_refs"]["recipient_hashes"], [recipient_hash])
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_notification_email_suppressions", executed_sql)
        self.assertIn("ON CONFLICT (project_id, recipient_hash) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        self.assertNotIn("ops@example.com", str(connection.calls))

    def test_postgres_repository_lists_runtime_notification_email_suppressions_with_audit_events(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        suppression_id = "29b509ef-0c07-4588-a6ed-e0d25d48cfb2"
        recipient_hash = runtime_email_body_hash("ops@example.com")
        suppression_row = {
            "id": suppression_id,
            "project_id": project_id,
            "recipient_hash": recipient_hash,
            "status": "active",
            "source": "feedback",
            "source_ref": "feedback-1",
            "metadata": {"source": "contract"},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_suppression_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_email_suppression",
            "target_id": suppression_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"recipient_hashes": [recipient_hash]},
            "output_refs": {"runtime_notification_email_suppression_ids": [suppression_id]},
            "method_version": "runtime_notification_email_suppression_v1",
            "reason": "manual project suppression",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[(1,), [suppression_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_notification_email_suppressions(
            project_id=project_id,
            status="active",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeNotificationEmailSuppressionPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].suppression["recipient_hash"], recipient_hash)
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "runtime_notification_email_suppression_saved")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn(
            "FROM runtime_notification_email_suppressions WHERE project_id = %s AND status = %s",
            executed_sql,
        )
        self.assertIn("target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_exports_runtime_notification_email_suppressions_csv(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        suppression_id = "29b509ef-0c07-4588-a6ed-e0d25d48cfb2"
        recipient_hash = runtime_email_body_hash("ops@example.com")
        provider_event_id_hash = runtime_email_body_hash("smtp-feedback-1")
        suppression_row = {
            "id": suppression_id,
            "project_id": project_id,
            "recipient_hash": recipient_hash,
            "status": "active",
            "source": "feedback",
            "source_ref": "feedback-1",
            "metadata": {
                "feedback_event_id": "feedback-1",
                "delivery_id": "delivery-1",
                "notification_id": "notification-1",
                "subscription_id": "subscription-1",
                "feedback_type": "complaint",
                "provider": "smtp",
                "provider_event_id_hash": provider_event_id_hash,
                "note": "do not export raw metadata",
            },
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_feedback_project_suppression_applied",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_notification_email_suppression",
            "target_id": suppression_id,
            "before_hash": None,
            "after_hash": "after-hash",
            "input_refs": {"recipient_hashes": [recipient_hash]},
            "output_refs": {"runtime_notification_email_suppression_ids": [suppression_id]},
            "method_version": "runtime_notification_email_feedback_project_suppression_v1",
            "reason": "apply complaint project suppression",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[(1,), [suppression_row], [audit_row]])

        export = PostgresEvidenceRepository(connection).export_runtime_notification_email_suppressions_csv(
            project_id=project_id,
            status="active",
            limit=5,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_notification_email_suppressions_csv")
        self.assertEqual(export.filename, "runtime-notification-email-suppressions.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["status"], "active")
        self.assertIn("suppression_id,project_id,recipient_hash,status,source", export.content)
        self.assertIn(suppression_id, export.content)
        self.assertIn(recipient_hash, export.content)
        self.assertIn(provider_event_id_hash, export.content)
        self.assertIn("runtime_notification_email_feedback_project_suppression_v1", export.content)
        self.assertIn("metadata_keys", export.content)
        self.assertNotIn("ops@example.com", export.content)
        self.assertNotIn("do not export raw metadata", export.content)

    def test_postgres_repository_applies_runtime_notification_email_preference_unsubscribe(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        existing_hash = runtime_email_body_hash("existing@example.com")
        recipient_hash = runtime_email_body_hash("ops@example.com")
        token_hash = runtime_email_body_hash("preference-token")
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "status": "delivered",
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": 250,
            "response_body_hash": "smtp-response-hash",
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        }
        subscription_before = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {"email_suppressed_recipient_hashes": [existing_hash]},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        subscription_after = {
            **subscription_before,
            "metadata": {
                "email_suppressed_recipient_hashes": [existing_hash, recipient_hash],
                "email_unsubscribe_token_hashes": [token_hash],
                "email_unsubscribe_source": "runtime_notification_email_preference_token",
            },
            "updated_by": "email-preference-token",
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_preference_unsubscribed",
            "project_id": project_id,
            "actor_type": "system",
            "actor_id": "email-preference-token",
            "target_type": "runtime_notification_subscription",
            "target_id": subscription_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"email_preference_token_hashes": [token_hash]},
            "output_refs": {"email_suppression_hashes": [existing_hash, recipient_hash]},
            "method_version": "runtime_notification_email_preference_unsubscribe_v1",
            "reason": "unsubscribe",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[delivery_row, subscription_before, subscription_after, [audit_row]])

        record = PostgresEvidenceRepository(connection).apply_runtime_notification_email_preference_unsubscribe(
            RuntimeNotificationEmailPreferenceUnsubscribeInput(
                project_id=project_id,
                delivery_id=delivery_id,
                notification_id=notification_id,
                subscription_id=subscription_id,
                recipient_hash=recipient_hash,
                token_hash=token_hash,
                updated_by="email-preference-token",
                reason="unsubscribe",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationSubscription)
        self.assertEqual(record.subscription["metadata"]["email_suppressed_recipient_hashes"], [existing_hash, recipient_hash])
        self.assertEqual(record.subscription["metadata"]["email_unsubscribe_token_hashes"], [token_hash])
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_email_preference_unsubscribed")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT id, project_id, notification_id, subscription_id, channel", executed_sql)
        self.assertIn("UPDATE runtime_notification_subscriptions SET metadata = %s", executed_sql)
        update_params = [
            params for sql, params in connection.calls if "UPDATE runtime_notification_subscriptions SET metadata" in sql
        ][0]
        self.assertIn(recipient_hash, str(update_params))
        self.assertIn(token_hash, str(update_params))
        self.assertNotIn("ops@example.com", str(update_params))

    def test_postgres_repository_gets_runtime_notification_email_preference_status(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        recipient_hash = runtime_email_body_hash("ops@example.com")
        token_hash = runtime_email_body_hash("manage-token")
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "status": "delivered",
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": 250,
            "response_body_hash": "smtp-response-hash",
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {
                "email_suppressed_recipient_hashes": [recipient_hash],
                "email_unsubscribe_token_hashes": ["a" * 64],
                "email_unsubscribe_source": "runtime_notification_email_preference_token",
            },
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "email-preference-token",
            "updated_at": now,
        }
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "runtime_alert",
            "severity": "critical",
            "title": "Brand absent in Sydney",
            "message": "Brand was absent from critical AI search prompts.",
            "target_type": "runtime_alert",
            "target_id": "brand_absent:project-1",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"alert_type": "brand_absent"},
            "created_by": "runtime-worker",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-worker",
            "updated_at": now,
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_preference_unsubscribed",
            "project_id": project_id,
            "actor_type": "system",
            "actor_id": "email-preference-token",
            "target_type": "runtime_notification_subscription",
            "target_id": subscription_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"email_preference_token_hashes": ["a" * 64]},
            "output_refs": {"email_suppression_hashes": [recipient_hash]},
            "method_version": "runtime_notification_email_preference_unsubscribe_v1",
            "reason": "unsubscribe",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[delivery_row, subscription_row, notification_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).get_runtime_notification_email_preference_status(
            project_id=project_id,
            delivery_id=delivery_id,
            notification_id=notification_id,
            subscription_id=subscription_id,
            recipient_hash=recipient_hash,
            token_hash=token_hash,
        )

        self.assertIsInstance(record, RuntimeNotificationEmailPreferenceStatus)
        self.assertEqual(record.preference["status"], "unsubscribed")
        self.assertTrue(record.preference["suppressed"])
        self.assertEqual(record.preference["email_preference_token_hash"], token_hash)
        self.assertEqual(record.subscription["metadata"]["email_suppressed_recipient_hash_count"], 1)
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_email_preference_unsubscribed")
        self.assertNotIn("ops@example.com", str(record))
        self.assertEqual(connection.commit_count, 0)

    def test_postgres_repository_applies_runtime_notification_email_preference_resubscribe(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        notification_id = "3ba5d5b7-8759-557b-a8a8-7297f98e2339"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "118e5c66-7bb4-558e-ab97-e74ef9928b46"
        existing_hash = runtime_email_body_hash("existing@example.com")
        recipient_hash = runtime_email_body_hash("ops@example.com")
        token_hash = runtime_email_body_hash("manage-token")
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "status": "delivered",
            "attempt_count": 1,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": 250,
            "response_body_hash": "smtp-response-hash",
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_email_v1"},
            "created_at": now,
            "updated_by": "notification-worker",
            "updated_at": now,
        }
        subscription_before = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "email",
            "endpoint_url": "mailto:ops@example.com",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {"email_suppressed_recipient_hashes": [existing_hash, recipient_hash]},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "email-preference-token",
            "updated_at": now,
        }
        subscription_after = {
            **subscription_before,
            "metadata": {
                "email_suppressed_recipient_hashes": [existing_hash],
                "email_resubscribe_token_hashes": [token_hash],
                "email_resubscribe_source": "runtime_notification_email_preference_token",
            },
            "updated_by": "email-preference-token",
        }
        audit_row = {
            "id": "2ce4310a-1c5f-4272-8a61-6d8b1aa9ea99",
            "event_type": "runtime_notification_email_preference_resubscribed",
            "project_id": project_id,
            "actor_type": "system",
            "actor_id": "email-preference-token",
            "target_type": "runtime_notification_subscription",
            "target_id": subscription_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"email_preference_token_hashes": [token_hash]},
            "output_refs": {"email_removed_suppression_hashes": [recipient_hash]},
            "method_version": "runtime_notification_email_preference_resubscribe_v1",
            "reason": "resubscribe",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[delivery_row, subscription_before, subscription_after, [audit_row]])

        record = PostgresEvidenceRepository(connection).apply_runtime_notification_email_preference_resubscribe(
            RuntimeNotificationEmailPreferenceResubscribeInput(
                project_id=project_id,
                delivery_id=delivery_id,
                notification_id=notification_id,
                subscription_id=subscription_id,
                recipient_hash=recipient_hash,
                token_hash=token_hash,
                updated_by="email-preference-token",
                reason="resubscribe",
            )
        )

        self.assertIsInstance(record, RuntimeNotificationSubscription)
        self.assertEqual(record.subscription["metadata"]["email_suppressed_recipient_hashes"], [existing_hash])
        self.assertEqual(record.subscription["metadata"]["email_resubscribe_token_hashes"], [token_hash])
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_notification_email_preference_resubscribed")
        self.assertEqual(connection.commit_count, 1)
        update_params = [
            params for sql, params in connection.calls if "UPDATE runtime_notification_subscriptions SET metadata" in sql
        ][0]
        self.assertIn(token_hash, str(update_params))
        self.assertNotIn(recipient_hash, str(update_params[0]["email_suppressed_recipient_hashes"]))
        self.assertNotIn("ops@example.com", str(update_params))

    def test_postgres_repository_renders_runtime_report_artifact(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "method_disclosure": {
                "google_coverage": "limited_coverage_appendix_only",
                "google_spike_gate": {
                    "gate_status": "fail",
                    "planned_runs": 240,
                    "completed_runs": 0,
                    "google_aio_completed_runs": 0,
                    "success_rate": 0.0,
                    "trigger_rate": 0.0,
                    "limited_coverage": True,
                    "recommendation": "Keep Google in limited coverage appendix until a google_aio backend reaches 80% completion",
                },
                "api_browser_fidelity": {
                    "status": "not_run",
                    "official_api_records": 1,
                    "browser_records": 0,
                    "comparable_prompt_city_pairs": 0,
                    "difference_rate": None,
                },
                "access_method_distribution": {"official_api": 1},
                "platform_distribution": {"perplexity": 1},
                "evidence_asset_coverage": {"screenshot_records": 1, "html_snapshot_records": 1},
            },
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": None,
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Sydney",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
        }
        connection = RecordingConnection(
            result_sets=[
                report_row,
                {
                    "id": snapshot_id,
                    "project_id": project_id,
                    "scope_type": "collection_slice",
                    "scope_value": "worker_runtime",
                    "formula_version": "au_visibility_v1",
                    "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                    "final_score": 87.35,
                    "trigger_rate": 1.0,
                    "mention_rate": 1.0,
                    "recommendation_rate": 1.0,
                    "answer_run_ids": [answer_run_id],
                    "created_at": now,
                    "dispersion": 0.0,
                },
                answer_run_row,
                [
                    {
                        "id": "d5f57d79-4834-4bd3-92a3-a1c917fbb3cf",
                        "event_type": "report_export_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "markdown_csv_report_exporter_v1",
                        "target_type": "report_export",
                        "target_id": report_export_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"report_export_ids": [report_export_id]},
                        "method_version": "markdown_csv_report_exporter_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
                {"count": 0},
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="markdown",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.filename, "worker-runtime-v1.md")
        self.assertEqual(artifact.media_type, "text/markdown; charset=utf-8")
        self.assertIn("GENO AU Evidence Report", artifact.content)
        self.assertIn("Is ExampleBrand good in Australia?", artifact.content)
        self.assertIn("## Method Disclosure", artifact.content)
        self.assertIn("Google spike gate: fail", artifact.content)
        self.assertIn("Google limited coverage: yes", artifact.content)
        self.assertIn("Google AIO completed runs: 0 / planned 240", artifact.content)
        self.assertIn("API-vs-browser fidelity: not_run", artifact.content)
        self.assertIn("Trigger rate denominator: all attempted evidence records in this report window", artifact.content)
        self.assertIn("Mention rate denominator: surface_triggered evidence records, not all attempted records", artifact.content)
        self.assertIn("Report evidence attempted records: 1", artifact.content)
        self.assertIn("Report evidence surface-triggered records: 1", artifact.content)
        self.assertIn("Screenshot records: 1", artifact.content)
        self.assertIn("HTML snapshot records: 1", artifact.content)
        self.assertIn("## Audit Summary", artifact.content)
        self.assertIn("Audit events attached: 1", artifact.content)
        self.assertIn("report_export_created", artifact.content)
        self.assertIn("ReportExport -> VisibilityScoreSnapshot", artifact.content)
        self.assertTrue(artifact.content_hash)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM report_exports WHERE id = %s", executed_sql)

    def test_postgres_repository_renders_runtime_report_csv_artifact(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        other_answer_run_id = "a20ec948-0443-5de5-8151-5ec1db8aef01"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id, other_answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": None,
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Sydney",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
        }
        other_answer_run_row = {
            **answer_run_row,
            "id": other_answer_run_id,
            "platform": "chatgpt",
            "surface": "chatgpt_search",
            "city": "Melbourne",
            "prompt_text": "Best ExampleBrand alternatives in Melbourne",
            "prompt_intent_type": "alternative",
        }
        connection = RecordingConnection(
            result_sets=[
                report_row,
                {
                    "id": snapshot_id,
                    "project_id": project_id,
                    "scope_type": "collection_slice",
                    "scope_value": "worker_runtime",
                    "formula_version": "au_visibility_v1",
                    "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                    "final_score": 87.35,
                    "trigger_rate": 1.0,
                    "mention_rate": 1.0,
                    "recommendation_rate": 1.0,
                    "answer_run_ids": [answer_run_id, other_answer_run_id],
                    "created_at": now,
                    "dispersion": 0.0,
                },
                answer_run_row,
                other_answer_run_row,
                [],
                {"count": 0},
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="csv",
            platform="perplexity",
            city="Sydney",
            intent_type="brand_awareness",
            sort="cost_desc",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.filename, "worker-runtime-v1.csv")
        self.assertEqual(artifact.media_type, "text/csv; charset=utf-8")
        self.assertEqual(artifact.filters["platform"], "perplexity")
        self.assertEqual(artifact.sort, "cost_desc")
        self.assertEqual(artifact.total_count, 2)
        self.assertEqual(artifact.row_count, 1)
        self.assertIn("answer_run_id", artifact.content)
        self.assertIn("Is ExampleBrand good in Australia?", artifact.content)
        self.assertNotIn("Best ExampleBrand alternatives in Melbourne", artifact.content)
        self.assertTrue(artifact.content_hash)
        self.assertTrue(artifact.filter_hash)

    def test_postgres_repository_renders_runtime_report_pdf_artifact(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": None,
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Australia",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
        }
        connection = RecordingConnection(
            result_sets=[
                report_row,
                {
                    "id": snapshot_id,
                    "project_id": project_id,
                    "scope_type": "collection_slice",
                    "scope_value": "worker_runtime",
                    "formula_version": "au_visibility_v1",
                    "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                    "final_score": 87.35,
                    "trigger_rate": 1.0,
                    "mention_rate": 1.0,
                    "recommendation_rate": 1.0,
                    "answer_run_ids": [answer_run_id],
                    "created_at": now,
                    "dispersion": 0.0,
                },
                answer_run_row,
                [],
                {"count": 0},
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="pdf",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.filename, "worker-runtime-v1.pdf")
        self.assertEqual(artifact.template, "standard")
        self.assertEqual(artifact.template_payload, {"template": "standard"})
        self.assertTrue(artifact.template_hash)
        self.assertEqual(artifact.media_type, "application/pdf")
        self.assertIsInstance(artifact.content, bytes)
        self.assertTrue(artifact.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", artifact.content)
        self.assertTrue(artifact.content_hash)

    def test_postgres_repository_renders_runtime_report_white_label_pdf_artifact(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": None,
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Australia",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
        }
        connection = RecordingConnection(
            result_sets=[
                report_row,
                {
                    "id": snapshot_id,
                    "project_id": project_id,
                    "scope_type": "collection_slice",
                    "scope_value": "worker_runtime",
                    "formula_version": "au_visibility_v1",
                    "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                    "final_score": 87.35,
                    "trigger_rate": 1.0,
                    "mention_rate": 1.0,
                    "recommendation_rate": 1.0,
                    "answer_run_ids": [answer_run_id],
                    "created_at": now,
                    "dispersion": 0.0,
                },
                answer_run_row,
                [],
                {"count": 0},
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="pdf",
            template="white_label",
            client_name="ExampleBrand AU",
            prepared_by="Partner Agency",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.filename, "worker-runtime-v1-white-label.pdf")
        self.assertEqual(artifact.template, "white_label")
        self.assertEqual(artifact.template_payload["client_name"], "ExampleBrand AU")
        self.assertEqual(artifact.template_payload["prepared_by"], "Partner Agency")
        self.assertTrue(artifact.template_hash)
        self.assertEqual(artifact.media_type, "application/pdf")
        self.assertIsInstance(artifact.content, bytes)
        self.assertTrue(artifact.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"ExampleBrand AU GEO Evidence Report", artifact.content)
        self.assertIn(b"white-label template", artifact.content)
        self.assertIn(b"%%EOF", artifact.content)
        self.assertTrue(artifact.content_hash)

    def test_postgres_repository_renders_runtime_report_white_label_pdf_from_project_brand_kit(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": None,
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Australia",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
        }
        brand_kit_row = {
            "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
            "project_id": project_id,
            "client_name": "Koala AU",
            "prepared_by": "Partner Agency",
            "logo_url": "https://koala.example/logo.png",
            "primary_color": "#0f766e",
            "secondary_color": "#111827",
            "footer_text": "Prepared for Koala AU board review",
            "updated_by": "runtime-console",
            "created_at": now,
            "updated_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                report_row,
                {
                    "id": snapshot_id,
                    "project_id": project_id,
                    "scope_type": "collection_slice",
                    "scope_value": "worker_runtime",
                    "formula_version": "au_visibility_v1",
                    "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
                    "final_score": 87.35,
                    "trigger_rate": 1.0,
                    "mention_rate": 1.0,
                    "recommendation_rate": 1.0,
                    "answer_run_ids": [answer_run_id],
                    "created_at": now,
                    "dispersion": 0.0,
                },
                answer_run_row,
                [],
                {"count": 0},
                brand_kit_row,
            ]
        )
        artifact = PostgresEvidenceRepository(connection).get_runtime_report_artifact(
            report_export_id=report_export_id,
            artifact_type="pdf",
            template="white_label",
        )
        self.assertIsInstance(artifact, RuntimeReportArtifact)
        assert artifact is not None
        self.assertEqual(artifact.template_payload["client_name"], "Koala AU")
        self.assertEqual(artifact.template_payload["prepared_by"], "Partner Agency")
        self.assertEqual(artifact.template_payload["logo_url"], "https://koala.example/logo.png")
        self.assertEqual(artifact.template_payload["primary_color"], "#0f766e")
        self.assertEqual(artifact.template_payload["source"], "project_brand_kit")
        self.assertIn(b"Koala AU GEO Evidence Report", artifact.content)
        self.assertIn(b"Partner Agency", artifact.content)
        self.assertIn(b"Prepared for Koala AU board review", artifact.content)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_brand_kits WHERE project_id = %s", executed_sql)

    def test_postgres_repository_reads_runtime_action_plan_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        schedule_id = "7fbc98b0-6b37-529d-ad3c-1c70b8f6a880"
        action_id = "4cfd7cd0-a0cc-580f-b448-7b52f3b2937e"
        comparison_id = "fd17704e-8f18-5cb5-a1e4-28f6d0af62cf"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": schedule_id,
                        "project_id": project_id,
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "sample_size": 1,
                        "offsets_days": [0, 7, 14, 30],
                        "scheduled_dates": [now],
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": action_id,
                        "project_id": project_id,
                        "title": "Strengthen AU review evidence",
                        "description": "Add review evidence",
                        "priority": "high",
                        "status": "open",
                        "owner_id": "system",
                        "source_gap_type": "missing_high_weight_source_type",
                        "evidence_answer_run_ids": [answer_run_id],
                        "related_source_types": ["review_site"],
                        "next_check_date": now,
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": comparison_id,
                        "project_id": project_id,
                        "baseline_score": 87.35,
                        "retest_score": 89.85,
                        "score_delta": 2.5,
                        "baseline_answer_run_ids": [answer_run_id],
                        "retest_answer_run_ids": [answer_run_id],
                        "trend": "improved",
                        "created_at": now,
                    }
                ],
                {
                    "id": answer_run_id,
                    "project_id": project_id,
                    "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                    "platform": "perplexity",
                    "surface": "sonar",
                    "access_method": "official_api",
                    "market_code": "AU",
                    "city": "Australia",
                    "language": "en-AU",
                    "device": "desktop",
                    "answer_present": True,
                    "surface_triggered": True,
                    "sample_index": 1,
                    "sample_size": 1,
                    "model_or_surface": "sonar",
                    "account_state": "api_key",
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "collector_version": "fixture-v1",
                    "collected_at": now,
                    "status": "completed",
                    "prompt_text": "Is ExampleBrand good in Australia?",
                    "prompt_intent_type": "brand_awareness",
                    "prompt_priority": 1,
                    "prompt_version": "au_dtc_ecommerce_v1",
                },
                [
                    {
                        "id": "425f980b-138f-4afa-8784-79d6f16f92ce",
                        "event_type": "action_plan_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.action_plan",
                        "target_type": "action_plan",
                        "target_id": schedule_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"retest_schedule_ids": [schedule_id]},
                        "method_version": "action_plan_v1",
                        "reason": "test",
                        "created_at": datetime(2026, 6, 10, 8, tzinfo=UTC),
                    }
                ],
                [
                    {
                        "id": "e0d7a395-b585-481a-bffa-07c3375416fe",
                        "event_type": "retest_comparison_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.action_plan",
                        "target_type": "retest_comparison",
                        "target_id": comparison_id,
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {"baseline_answer_run_ids": [answer_run_id]},
                        "output_refs": {"retest_comparison_ids": [comparison_id]},
                        "method_version": "retest_comparison_v1",
                        "reason": "test",
                        "created_at": datetime(2026, 6, 10, 7, tzinfo=UTC),
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_action_plans(
            project_id=project_id,
            status="open",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeActionPlanPage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.retest_schedule["prompt_version"], "au_dtc_ecommerce_v1")
        self.assertEqual(record.action_recommendations[0]["status"], "open")
        self.assertEqual(record.retest_comparisons[0]["trend"], "improved")
        self.assertEqual(record.answer_runs[0]["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(record.audit_events[0]["event_type"], "action_plan_created")
        self.assertEqual(record.audit_events[1]["event_type"], "retest_comparison_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM retest_schedules rs WHERE rs.project_id = %s", executed_sql)
        self.assertIn("FROM action_recommendations WHERE project_id = %s AND status = %s", executed_sql)
        self.assertIn("FROM retest_comparisons", executed_sql)
        self.assertIn("WHERE target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_exports_runtime_action_plans_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        schedule_id = "7fbc98b0-6b37-529d-ad3c-1c70b8f6a880"
        action_id = "4cfd7cd0-a0cc-580f-b448-7b52f3b2937e"
        comparison_id = "fd17704e-8f18-5cb5-a1e4-28f6d0af62cf"
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": schedule_id,
                        "project_id": project_id,
                        "prompt_version": "au_dtc_ecommerce_v1",
                        "sample_size": 1,
                        "offsets_days": [0, 7, 14, 30],
                        "scheduled_dates": [now],
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": action_id,
                        "project_id": project_id,
                        "title": "Strengthen AU review evidence",
                        "description": "Add review evidence",
                        "priority": "high",
                        "status": "open",
                        "owner_id": "agency-owner",
                        "source_gap_type": "missing_high_weight_source_type",
                        "evidence_answer_run_ids": [answer_run_id],
                        "related_source_types": ["review_site"],
                        "next_check_date": now,
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": comparison_id,
                        "project_id": project_id,
                        "baseline_score": 87.35,
                        "retest_score": 89.85,
                        "score_delta": 2.5,
                        "baseline_answer_run_ids": [answer_run_id],
                        "retest_answer_run_ids": [answer_run_id],
                        "trend": "improved",
                        "created_at": now,
                    }
                ],
                {
                    "id": answer_run_id,
                    "project_id": project_id,
                    "prompt_question_id": "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0",
                    "platform": "perplexity",
                    "surface": "sonar",
                    "access_method": "official_api",
                    "market_code": "AU",
                    "city": "Australia",
                    "language": "en-AU",
                    "device": "desktop",
                    "answer_present": True,
                    "surface_triggered": True,
                    "sample_index": 1,
                    "sample_size": 1,
                    "model_or_surface": "sonar",
                    "account_state": "api_key",
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "collector_version": "fixture-v1",
                    "collected_at": now,
                    "status": "completed",
                    "prompt_text": "Is ExampleBrand good in Australia?",
                    "prompt_intent_type": "brand_awareness",
                    "prompt_priority": 1,
                    "prompt_version": "au_dtc_ecommerce_v1",
                },
                [
                    {
                        "id": "425f980b-138f-4afa-8784-79d6f16f92ce",
                        "event_type": "action_plan_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.action_plan",
                        "target_type": "action_plan",
                        "target_id": schedule_id,
                        "before_hash": None,
                        "after_hash": "action-after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"retest_schedule_ids": [schedule_id]},
                        "method_version": "action_plan_v1",
                        "reason": "test",
                        "created_at": datetime(2026, 6, 10, 8, tzinfo=UTC),
                    }
                ],
                [
                    {
                        "id": "e0d7a395-b585-481a-bffa-07c3375416fe",
                        "event_type": "retest_comparison_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.action_plan",
                        "target_type": "retest_comparison",
                        "target_id": comparison_id,
                        "before_hash": "before",
                        "after_hash": "comparison-after",
                        "input_refs": {"baseline_answer_run_ids": [answer_run_id]},
                        "output_refs": {"retest_comparison_ids": [comparison_id]},
                        "method_version": "retest_comparison_v1",
                        "reason": "test",
                        "created_at": datetime(2026, 6, 10, 7, tzinfo=UTC),
                    }
                ],
            ]
        )

        export = PostgresEvidenceRepository(connection).export_runtime_action_plans_csv(
            project_id=project_id,
            status="open",
            limit=10,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_action_plans_csv")
        self.assertEqual(export.filename, "runtime-action-plans.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["status"], "open")
        self.assertIn("action_recommendation_id,project_id,retest_schedule_id", export.content)
        self.assertIn(action_id, export.content)
        self.assertIn(schedule_id, export.content)
        self.assertIn(comparison_id, export.content)
        self.assertIn("improved", export.content)
        self.assertIn("2.5", export.content)
        self.assertIn(_artifact_hash("Strengthen AU review evidence"), export.content)
        self.assertIn(_artifact_hash("Add review evidence"), export.content)
        self.assertIn(_artifact_hash("agency-owner"), export.content)
        self.assertIn("action_plan_created", export.content)
        self.assertIn("action_plan_v1", export.content)
        self.assertIn("action-after", export.content)
        self.assertNotIn("Strengthen AU review evidence", export.content)
        self.assertNotIn("Add review evidence", export.content)
        self.assertNotIn("agency-owner", export.content)
        self.assertEqual(export.content_hash, hashlib.sha256(export.content.encode("utf-8")).hexdigest())

    def test_postgres_repository_builds_runtime_alerts_from_score_graph_and_actions(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        mention_contribution_id = "1dd2957f-050b-5d02-899a-2dfe889136dd"
        recommendation_contribution_id = "22a5f0de-f65a-59c8-8383-ed30361d68a1"
        action_id = "e5f3964b-54d5-5d2f-9ff7-9ec9ea24eb47"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        analysis_id = "78ec34ba-1077-5d23-9834-c9c0284f9633"
        snapshot_row = {
            "id": snapshot_id,
            "project_id": project_id,
            "scope_type": "collection_slice",
            "scope_value": "p0a_runtime",
            "formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"perplexity": 0.25},
            "final_score": 42.0,
            "trigger_rate": 1.0,
            "mention_rate": 0.25,
            "recommendation_rate": 0.1,
            "answer_run_ids": [answer_run_id],
            "created_at": now,
            "dispersion": 0.2,
            "component_weights_snapshot": {"MentionScore": 0.18},
        }
        connection = RecordingConnection(
            result_sets=[
                snapshot_row,
                [
                    {
                        "id": mention_contribution_id,
                        "score_snapshot_id": snapshot_id,
                        "component_name": "MentionScore",
                        "component_score": 25.0,
                        "weight": 0.18,
                        "weighted_contribution": 4.5,
                        "denominator": "all_answer_runs",
                        "evidence_answer_run_ids": [answer_run_id],
                        "positive_evidence_summary": "few mentions",
                        "negative_evidence_summary": "brand missing in many answers",
                        "confidence_note": "fixture",
                        "created_at": now,
                    },
                    {
                        "id": recommendation_contribution_id,
                        "score_snapshot_id": snapshot_id,
                        "component_name": "RecommendationScore",
                        "component_score": 10.0,
                        "weight": 0.22,
                        "weighted_contribution": 2.2,
                        "denominator": "surface_triggered_runs",
                        "evidence_answer_run_ids": [answer_run_id],
                        "positive_evidence_summary": "some recs",
                        "negative_evidence_summary": "weak recommendations",
                        "confidence_note": "fixture",
                        "created_at": now,
                    },
                ],
                [
                    {
                        "id": "7cc36d44-0f20-5681-8613-3998050e3267",
                        "project_id": project_id,
                        "source_type": "official_site",
                        "gap_type": "missing_high_weight_source_type",
                        "observed_count": 0,
                        "expected_weight": 0.95,
                        "recommendation": "Add official AU evidence",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "8c6e21aa-5df2-558e-ad5d-220b0de78a98",
                        "project_id": project_id,
                        "competitor_name": "Emma Sleep",
                        "metric_scope": "project",
                        "payload": {"mention_count": 2, "mention_rate": 0.75},
                        "answer_run_ids": [answer_run_id],
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": action_id,
                        "project_id": project_id,
                        "title": "Improve brand mention coverage",
                        "description": "Create citation ready pages",
                        "priority": "high",
                        "status": "open",
                        "owner_id": "system",
                        "source_gap_type": "low_mention_rate",
                        "evidence_answer_run_ids": [answer_run_id],
                        "related_source_types": [],
                        "next_check_date": now,
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": analysis_id,
                        "answer_run_id": answer_run_id,
                        "parser_engine_id": "rule_based_v2_aliases",
                        "analysis_version": "rule_based_v2_aliases",
                        "payload": {
                            "sentiment_score": 18.0,
                            "uncertainty_flags": ["negative_terms_detected"],
                        },
                        "confidence": 0.82,
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": "9b663656-4a0e-4fda-a764-0a4d62fa15f1",
                        "event_type": "visibility_score_snapshot_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.scoring",
                        "target_type": "visibility_score_snapshot",
                        "target_id": snapshot_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"score_snapshot_ids": [snapshot_id]},
                        "method_version": "au_visibility_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
                [],
                [],
                [],
                [],
                [],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_alerts(project_id=project_id, limit=10, offset=0)

        self.assertIsInstance(page, RuntimeAlertPage)
        self.assertEqual(page.total_count, 5)
        self.assertEqual(page.records[0].alert["alert_type"], "competitor_pressure")
        self.assertEqual(page.records[0].alert["severity"], "critical")
        alert_types = {item.alert["alert_type"] for item in page.records}
        self.assertEqual(
            alert_types,
            {"brand_absent", "low_recommendation_rate", "source_gap", "competitor_pressure", "negative_sentiment"},
        )
        mention_alert = next(item for item in page.records if item.alert["alert_type"] == "brand_absent")
        self.assertEqual(mention_alert.alert["metric_value"], 0.25)
        self.assertEqual(mention_alert.related_actions[0]["id"], action_id)
        self.assertTrue(any(ref["target_type"] == "score_contribution" for ref in mention_alert.evidence_refs))
        self.assertEqual(mention_alert.audit_events[0]["event_type"], "visibility_score_snapshot_created")
        negative_alert = next(item for item in page.records if item.alert["alert_type"] == "negative_sentiment")
        self.assertEqual(negative_alert.alert["metric_value"], 18.0)
        self.assertEqual(negative_alert.alert["severity"], "critical")
        self.assertTrue(any(ref["target_type"] == "answer_analysis" and ref["target_id"] == analysis_id for ref in negative_alert.evidence_refs))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM visibility_score_snapshots WHERE project_id = %s", executed_sql)
        self.assertIn("FROM source_gaps WHERE project_id = %s", executed_sql)
        self.assertIn("FROM competitor_benchmarks WHERE project_id = %s", executed_sql)
        self.assertIn("FROM action_recommendations WHERE project_id = %s", executed_sql)
        self.assertIn("FROM answer_analyses", executed_sql)
        self.assertIn("FROM runtime_alert_events", executed_sql)

    def test_postgres_repository_exports_runtime_alerts_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        mention_contribution_id = "1dd2957f-050b-5d02-899a-2dfe889136dd"
        action_id = "e5f3964b-54d5-5d2f-9ff7-9ec9ea24eb47"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        snapshot_row = {
            "id": snapshot_id,
            "project_id": project_id,
            "scope_type": "collection_slice",
            "scope_value": "p0a_runtime",
            "formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"perplexity": 0.25},
            "final_score": 42.0,
            "trigger_rate": 1.0,
            "mention_rate": 0.25,
            "recommendation_rate": 0.5,
            "answer_run_ids": [answer_run_id],
            "created_at": now,
            "dispersion": 0.2,
            "component_weights_snapshot": {"MentionScore": 0.18},
        }
        management_event = {
            "id": "e7b5cf79-3fc6-4f0f-8eb4-89882d0bf212",
            "project_id": project_id,
            "alert_id": _stable_id("runtime-alert", project_id, snapshot_id, "brand_absent"),
            "alert_type": "brand_absent",
            "source": "visibility_score_snapshot",
            "source_id": snapshot_id,
            "status": "acknowledged",
            "updated_by": "analyst-1",
            "note": "Investigating mention gap",
            "metadata": {"severity": "high", "owner": "ops"},
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                snapshot_row,
                [
                    {
                        "id": mention_contribution_id,
                        "score_snapshot_id": snapshot_id,
                        "component_name": "MentionScore",
                        "component_score": 25.0,
                        "weight": 0.18,
                        "weighted_contribution": 4.5,
                        "denominator": "all_answer_runs",
                        "evidence_answer_run_ids": [answer_run_id],
                        "positive_evidence_summary": "few mentions",
                        "negative_evidence_summary": "brand missing in many answers",
                        "confidence_note": "fixture",
                        "created_at": now,
                    }
                ],
                [],
                [],
                [
                    {
                        "id": action_id,
                        "project_id": project_id,
                        "title": "Improve brand mention coverage",
                        "description": "Create citation ready pages",
                        "priority": "high",
                        "status": "open",
                        "owner_id": "system",
                        "source_gap_type": "low_mention_rate",
                        "evidence_answer_run_ids": [answer_run_id],
                        "related_source_types": [],
                        "next_check_date": now,
                        "created_at": now,
                    }
                ],
                [],
                [
                    {
                        "id": "9b663656-4a0e-4fda-a764-0a4d62fa15f1",
                        "event_type": "visibility_score_snapshot_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.scoring",
                        "target_type": "visibility_score_snapshot",
                        "target_id": snapshot_id,
                        "before_hash": None,
                        "after_hash": "snapshot-after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"score_snapshot_ids": [snapshot_id]},
                        "method_version": "au_visibility_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
                [management_event],
            ]
        )

        export = PostgresEvidenceRepository(connection).export_runtime_alerts_csv(
            project_id=project_id,
            alert_type="brand_absent",
            severity="high",
            limit=10,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_alerts_csv")
        self.assertEqual(export.filename, "runtime-alerts.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["alert_type"], "brand_absent")
        self.assertEqual(export.filters["severity"], "high")
        self.assertIn("alert_id,project_id,alert_type,severity", export.content)
        self.assertIn("brand_absent", export.content)
        self.assertIn("mention_rate", export.content)
        self.assertIn("visibility_score_snapshot", export.content)
        self.assertIn(snapshot_id, export.content)
        self.assertIn(action_id, export.content)
        self.assertIn(_artifact_hash("Brand mention coverage is below threshold"), export.content)
        self.assertIn(_artifact_hash("Investigating mention gap"), export.content)
        self.assertIn(_artifact_hash("analyst-1"), export.content)
        self.assertIn("owner|severity", export.content)
        self.assertIn("visibility_score_snapshot_created", export.content)
        self.assertIn("snapshot-after", export.content)
        self.assertNotIn("Brand mention coverage is below threshold", export.content)
        self.assertNotIn("AI answers are not mentioning", export.content)
        self.assertNotIn("Improve brand mention coverage", export.content)
        self.assertNotIn("Investigating mention gap", export.content)
        self.assertNotIn("analyst-1", export.content)
        self.assertEqual(export.content_hash, hashlib.sha256(export.content.encode("utf-8")).hexdigest())

    def test_postgres_repository_records_runtime_alert_event_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        existing_event = {
            "id": "e7b5cf79-3fc6-4f0f-8eb4-89882d0bf212",
            "project_id": project_id,
            "alert_id": "runtime-alert-1",
            "alert_type": "brand_absent",
            "source": "visibility_score_snapshot",
            "source_id": "snapshot-1",
            "status": "acknowledged",
            "updated_by": "analyst-1",
            "note": "Investigating",
            "metadata": {"severity": "high"},
            "created_at": now,
        }
        saved_event = {
            **existing_event,
            "id": "75610089-4a47-45d5-9b65-21e3ced34cf1",
            "status": "resolved",
            "updated_by": "analyst-2",
            "note": "Resolved in current sprint",
        }
        connection = RecordingConnection(
            result_sets=[
                [{"id": project_id}],
                [existing_event],
                [saved_event],
                [
                    {
                        "id": "6a7b6576-7064-44f0-85c9-9707f11c0e9c",
                        "event_type": "runtime_alert_event_recorded",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "analyst-2",
                        "target_type": "runtime_alert",
                        "target_id": "runtime-alert-1",
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {"runtime_alert_ids": ["runtime-alert-1"]},
                        "output_refs": {"runtime_alert_event_ids": [saved_event["id"]]},
                        "method_version": "runtime_alert_event_v1",
                        "reason": "Resolved in current sprint",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).record_runtime_alert_event(
            RuntimeAlertEventInput(
                project_id=project_id,
                alert_id="runtime-alert-1",
                alert_type="brand_absent",
                source="visibility_score_snapshot",
                source_id="snapshot-1",
                status="resolved",
                updated_by="analyst-2",
                note="Resolved in current sprint",
                metadata={"severity": "high"},
            )
        )

        self.assertIsInstance(record, RuntimeAlertEvent)
        self.assertEqual(record.alert_event["status"], "resolved")
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_alert_event_recorded")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_alert_events", executed_sql)
        self.assertIn("runtime_alert_event_recorded", str(connection.calls))
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_records_escalated_runtime_alert_event(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        saved_event = {
            "id": "75610089-4a47-45d5-9b65-21e3ced34cf1",
            "project_id": project_id,
            "alert_id": "runtime-alert-1",
            "alert_type": "negative_sentiment",
            "source": "answer_analysis",
            "source_id": "analysis-1",
            "status": "escalated",
            "updated_by": "runtime-alert-escalation-worker",
            "note": "Runtime alert breached escalation threshold",
            "metadata": {"escalation_policy_version": "runtime_alert_escalation_worker_v1"},
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                [{"id": project_id}],
                [],
                [saved_event],
                [
                    {
                        "id": "6a7b6576-7064-44f0-85c9-9707f11c0e9c",
                        "event_type": "runtime_alert_event_recorded",
                        "project_id": project_id,
                        "actor_type": "worker",
                        "actor_id": "runtime-alert-escalation-worker",
                        "target_type": "runtime_alert",
                        "target_id": "runtime-alert-1",
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"status": ["escalated"]},
                        "output_refs": {"runtime_alert_event_ids": [saved_event["id"]]},
                        "method_version": "runtime_alert_event_v1",
                        "reason": "Runtime alert breached escalation threshold",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).record_runtime_alert_event(
            RuntimeAlertEventInput(
                project_id=project_id,
                alert_id="runtime-alert-1",
                alert_type="negative_sentiment",
                source="answer_analysis",
                source_id="analysis-1",
                status="escalated",
                updated_by="runtime-alert-escalation-worker",
                note="Runtime alert breached escalation threshold",
                metadata={"escalation_policy_version": "runtime_alert_escalation_worker_v1"},
            )
        )

        self.assertEqual(record.alert_event["status"], "escalated")
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[3], "worker")
        self.assertEqual(record.audit_events[0]["input_refs"]["status"], ["escalated"])
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_enqueues_runtime_alert_notifications_with_delivery(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        notification_id = "dfaa703e-e168-58d1-b951-6853a7ba0810"
        delivery_id = "f204f229-b9af-5525-8a87-f0c6b79edc12"
        snapshot_row = {
            "id": snapshot_id,
            "project_id": project_id,
            "scope_type": "collection_slice",
            "scope_value": "p0a_runtime",
            "formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"perplexity": 0.25},
            "final_score": 42.0,
            "trigger_rate": 1.0,
            "mention_rate": 0.25,
            "recommendation_rate": 0.8,
            "answer_run_ids": [answer_run_id],
            "created_at": now,
            "dispersion": 0.2,
            "component_weights_snapshot": {"MentionScore": 0.18},
        }
        contribution_row = {
            "id": "1dd2957f-050b-5d02-899a-2dfe889136dd",
            "score_snapshot_id": snapshot_id,
            "component_name": "MentionScore",
            "component_score": 25.0,
            "weight": 0.18,
            "weighted_contribution": 4.5,
            "denominator": "all_answer_runs",
            "evidence_answer_run_ids": [answer_run_id],
            "positive_evidence_summary": "few mentions",
            "negative_evidence_summary": "brand missing in many answers",
            "confidence_note": "fixture",
            "created_at": now,
        }
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "runtime_alert",
            "severity": "warning",
            "title": "Runtime alert: Brand mention coverage is below threshold",
            "message": "brand_absent alert from visibility_score_snapshot. mention_rate=0.25. threshold=0.5.",
            "target_type": "runtime_alert",
            "target_id": "runtime-alert-1",
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"alert_type": "brand_absent"},
            "created_by": "runtime-console",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "event_types": ["runtime_alert"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_v1"},
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                [{"id": project_id}],
                snapshot_row,
                [contribution_row],
                [],
                [],
                [],
                [],
                [
                    {
                        "id": "9b663656-4a0e-4fda-a764-0a4d62fa15f1",
                        "event_type": "visibility_score_snapshot_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.scoring",
                        "target_type": "visibility_score_snapshot",
                        "target_id": snapshot_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"answer_run_ids": [answer_run_id]},
                        "output_refs": {"score_snapshot_ids": [snapshot_id]},
                        "method_version": "au_visibility_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
                [],
                notification_row,
                [subscription_row],
                delivery_row,
            ]
        )

        result = PostgresEvidenceRepository(connection).enqueue_runtime_alert_notifications(
            project_id=project_id,
            created_by="runtime-console",
            reason="queue runtime alert notification",
        )

        self.assertIsInstance(result, RuntimeAlertNotificationResult)
        self.assertEqual(result.notification_count, 1)
        self.assertEqual(result.delivery_count, 1)
        self.assertEqual(result.notifications[0]["notification_type"], "runtime_alert")
        self.assertTrue(any(event["event_type"] == "runtime_notification_created" for event in result.audit_events))
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_notifications", executed_sql)
        self.assertIn("INSERT INTO runtime_notification_deliveries", executed_sql)
        self.assertIn("runtime_notification_delivery_queued", str(connection.calls))

    def test_postgres_repository_reads_runtime_content_engine_page(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        draft_id = "51dcc4cb-c798-5eac-a08d-86f596c78f0f"
        fact_id = "06975d61-853b-5a25-ae0e-b62bbfe82c15"
        prompt_id = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        action_id = "4cfd7cd0-a0cc-580f-b448-7b52f3b2937e"
        distribution_id = "042f3450-77b4-5cb3-8a61-8057db7c11bd"
        connector_id = "70655f5b-4b7e-56cc-9974-84d6d5f08020"
        fact_row = {
            "id": fact_id,
            "project_id": project_id,
            "market_code": "AU",
            "fact_type": "australian_shipping_policy",
            "subject": "ExampleBrand",
            "predicate": "supports_market",
            "object_value": "AU",
            "city": None,
            "evidence_source_id": answer_run_id,
            "confidence": 0.72,
            "status": "active",
            "valid_from": now,
            "valid_until": None,
        }
        draft_row = {
            "id": draft_id,
            "project_id": project_id,
            "title": "ExampleBrand FAQ for Australian customers",
            "content_type": "evidence_backed_outline",
            "content_template_id": "faq_for_australian_customers",
            "target_question_ids": [prompt_id],
            "target_city": "Sydney",
            "target_platform": "chatgpt/perplexity",
            "target_source_type": "official_site",
            "used_knowledge_fact_ids": [fact_id],
            "source_gap_types": ["low_mention_rate"],
            "source_action_id": action_id,
            "evidence_answer_run_ids": [answer_run_id],
            "draft_markdown": "# ExampleBrand FAQ",
            "review_status": "pending_human_review",
            "created_by": "geno-core.knowledge",
            "created_at": now,
        }
        distribution_row = {
            "id": distribution_id,
            "project_id": project_id,
            "content_draft_id": draft_id,
            "platform": "manual",
            "target_url": "",
            "status": "draft_created",
            "submitted_at": None,
            "checked_at": None,
            "notes": "Manual distribution only.",
        }
        draft_audit_row = {
            "id": "8e8c0a1e-8887-48cb-b709-d849d9a505f4",
            "event_type": "content_draft_review_status_updated",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "editor@example.com",
            "target_type": "content_draft",
            "target_id": draft_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"human_review_record_ids": ["f25cdddc-c3e7-4fcb-90b8-557fd6465ea7"]},
            "output_refs": {"content_draft_ids": [draft_id], "review_status": "approved"},
            "method_version": "content_draft_review_status_projection_v1",
            "reason": "project latest human review decision onto content draft review_status",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [{"project_id": project_id}],
                [fact_row],
                [draft_row],
                {
                    "id": prompt_id,
                    "project_id": project_id,
                    "market_code": "AU",
                    "industry_code": "dtc_ecommerce",
                    "text": "Is ExampleBrand good in Australia?",
                    "intent_type": "brand_awareness",
                    "city": "Australia",
                    "language": "en-AU",
                    "target_brand": "ExampleBrand",
                    "competitors": ["CompetitorA"],
                    "priority": 1,
                    "intent_weight": 1.0,
                    "prompt_version": "au_dtc_ecommerce_v1",
                    "status": "active",
                },
                fact_row,
                {
                    "id": answer_run_id,
                    "project_id": project_id,
                    "prompt_question_id": prompt_id,
                    "platform": "perplexity",
                    "surface": "sonar",
                    "access_method": "official_api",
                    "market_code": "AU",
                    "city": "Australia",
                    "language": "en-AU",
                    "device": "desktop",
                    "answer_present": True,
                    "surface_triggered": True,
                    "sample_index": 1,
                    "sample_size": 1,
                    "model_or_surface": "sonar",
                    "account_state": "api_key",
                    "collector_backend_id": "fixture_perplexity_sonar",
                    "collector_version": "fixture-v1",
                    "collected_at": now,
                    "status": "completed",
                    "prompt_text": "Is ExampleBrand good in Australia?",
                    "prompt_intent_type": "brand_awareness",
                    "prompt_priority": 1,
                    "prompt_version": "au_dtc_ecommerce_v1",
                },
                {
                    "id": action_id,
                    "project_id": project_id,
                    "title": "Improve brand mention coverage",
                    "description": "Create citation-ready pages.",
                    "priority": "high",
                    "status": "open",
                    "owner_id": "system",
                    "source_gap_type": "low_mention_rate",
                    "evidence_answer_run_ids": [answer_run_id],
                    "related_source_types": [],
                    "next_check_date": now,
                    "created_at": now,
                },
                [distribution_row],
                [draft_audit_row],
                [
                    {
                        "id": connector_id,
                        "project_id": project_id,
                        "provider": "google_search_console",
                        "connection_status": "planned",
                        "capabilities": ["read_search_queries"],
                        "auth_mode": "oauth",
                        "created_at": now,
                    }
                ],
                [distribution_row],
                [
                    {
                        "id": "425f980b-138f-4afa-8784-79d6f16f92ce",
                        "event_type": "content_engine_fixture_created",
                        "project_id": project_id,
                        "actor_type": "system",
                        "actor_id": "geno-core.knowledge",
                        "target_type": "content_engine_fixture",
                        "target_id": project_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"knowledge_fact_ids": [fact_id]},
                        "output_refs": {"content_draft_ids": [draft_id]},
                        "method_version": "content_engine_fixture_v1",
                        "reason": "test",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_content_engines(
            project_id=project_id,
            review_status="pending_human_review",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeContentEnginePage)
        self.assertEqual(page.total_count, 1)
        record = page.records[0]
        self.assertEqual(record.project_id, project_id)
        self.assertEqual(record.knowledge_facts[0]["fact_type"], "australian_shipping_policy")
        draft = record.content_drafts[0]
        self.assertEqual(draft.draft["review_status"], "pending_human_review")
        self.assertEqual(draft.target_questions[0]["text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(draft.knowledge_facts[0]["id"], fact_id)
        self.assertEqual(draft.answer_runs[0]["prompt_text"], "Is ExampleBrand good in Australia?")
        self.assertEqual(draft.action_recommendation["source_gap_type"], "low_mention_rate")
        self.assertEqual(draft.manual_distribution_records[0]["status"], "draft_created")
        self.assertEqual(draft.audit_events[0]["event_type"], "content_draft_review_status_updated")
        self.assertEqual(record.integration_connectors[0]["provider"], "google_search_console")
        self.assertEqual(record.audit_events[0]["event_type"], "content_engine_fixture_created")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM content_drafts cd WHERE cd.project_id = %s AND cd.review_status = %s", executed_sql)
        self.assertIn("FROM localized_knowledge_facts", executed_sql)
        self.assertIn("FROM prompt_questions WHERE id = %s", executed_sql)
        self.assertIn("FROM action_recommendations WHERE id = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_reads_runtime_traceability_detail(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        report_export_id = "b3efe108-1429-5f5f-bd07-8f1a2d2dd5ad"
        snapshot_id = "a7f7f8aa-5d40-4fdf-a2b3-b8729a9a5e2f"
        contribution_id = "df03794b-e8fc-4b69-aa62-2304a55ff3a9"
        answer_run_id = "438ab927-5873-5516-8df3-47f6c75ef007"
        raw_answer_id = "5d714ed1-25aa-5651-b8b3-5e4b275d278a"
        citation_id = "6e5c424e-1674-58ce-b075-6c52259bbbe5"
        asset_id = "29a279b8-3313-5306-a959-4f0f0de9c950"
        source_graph_id = "41c2fd71-a32f-51a7-92e4-3d4c0f7ab1c2"
        action_id = "4cfd7cd0-a0cc-580f-b448-7b52f3b2937e"
        draft_id = "51dcc4cb-c798-5eac-a08d-86f596c78f0f"
        fact_id = "06975d61-853b-5a25-ae0e-b62bbfe82c15"
        prompt_id = "f1f8ee6a-cd19-5afc-a053-b4d16a5e56c0"
        audit_event_id = "495d24da-90cf-4073-bd9c-16afeb5b3169"
        answer_run_row = {
            "id": answer_run_id,
            "project_id": project_id,
            "prompt_question_id": prompt_id,
            "platform": "perplexity",
            "surface": "sonar",
            "access_method": "official_api",
            "market_code": "AU",
            "city": "Australia",
            "language": "en-AU",
            "device": "desktop",
            "answer_present": True,
            "surface_triggered": True,
            "sample_index": 1,
            "sample_size": 1,
            "model_or_surface": "sonar",
            "account_state": "api_key",
            "collector_backend_id": "fixture_perplexity_sonar",
            "collector_version": "fixture-v1",
            "collected_at": now,
            "status": "completed",
            "prompt_text": "Is ExampleBrand good in Australia?",
            "prompt_intent_type": "brand_awareness",
            "prompt_priority": 1,
            "prompt_version": "au_dtc_ecommerce_v1",
        }
        report_row = {
            "id": report_export_id,
            "project_id": project_id,
            "market_code": "AU",
            "report_version": "worker-runtime-v1",
            "report_type": "worker_runtime",
            "score_snapshot_ids": [snapshot_id],
            "answer_run_ids": [answer_run_id],
            "prompt_version": "au_dtc_ecommerce_v1",
            "scoring_formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "sample_size": 1,
            "window_start": now,
            "window_end": now,
            "methodology_hash": "methodology-hash",
            "markdown_url": "s3://geno-reports/report.md",
            "pdf_url": None,
            "csv_url": "s3://geno-reports/report.csv",
            "exported_by": "system",
            "exported_at": now,
        }
        snapshot_row = {
            "id": snapshot_id,
            "project_id": project_id,
            "scope_type": "collection_slice",
            "scope_value": "worker_runtime",
            "formula_version": "au_visibility_v1",
            "platform_weights_snapshot": {"chatgpt": 0.30, "perplexity": 0.25},
            "final_score": 87.35,
            "trigger_rate": 1.0,
            "mention_rate": 1.0,
            "recommendation_rate": 1.0,
            "answer_run_ids": [answer_run_id],
            "created_at": now,
            "dispersion": 0.0,
        }
        action_row = {
            "id": action_id,
            "project_id": project_id,
            "title": "Improve brand mention coverage",
            "description": "Create citation-ready pages.",
            "priority": "high",
            "status": "open",
            "owner_id": "system",
            "source_gap_type": "low_mention_rate",
            "evidence_answer_run_ids": [answer_run_id],
            "related_source_types": [],
            "next_check_date": now,
            "created_at": now,
        }
        draft_row = {
            "id": draft_id,
            "project_id": project_id,
            "title": "ExampleBrand FAQ for Australian customers",
            "content_type": "evidence_backed_outline",
            "content_template_id": "faq_for_australian_customers",
            "target_question_ids": [prompt_id],
            "target_city": "Sydney",
            "target_platform": "chatgpt/perplexity",
            "target_source_type": "official_site",
            "used_knowledge_fact_ids": [fact_id],
            "source_gap_types": ["low_mention_rate"],
            "source_action_id": action_id,
            "evidence_answer_run_ids": [answer_run_id],
            "draft_markdown": "# ExampleBrand FAQ",
            "review_status": "pending_human_review",
            "created_by": "geno-core.knowledge",
            "created_at": now,
        }
        fact_row = {
            "id": fact_id,
            "project_id": project_id,
            "market_code": "AU",
            "fact_type": "australian_shipping_policy",
            "subject": "ExampleBrand",
            "predicate": "supports_market",
            "object_value": "AU",
            "city": None,
            "evidence_source_id": answer_run_id,
            "confidence": 0.72,
            "status": "active",
            "valid_from": now,
            "valid_until": None,
        }
        audit_row = {
            "id": audit_event_id,
            "event_type": "answer_run_collected",
            "project_id": project_id,
            "actor_type": "worker",
            "actor_id": "fixture_perplexity_sonar",
            "target_type": "answer_run",
            "target_id": answer_run_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"prompt_question_ids": [prompt_id]},
            "output_refs": {"answer_run_ids": [answer_run_id]},
            "method_version": "fixture-v1",
            "reason": "test",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": "b11a8445-6d8f-58f8-b1b5-50c45e22d384",
                    "project_id": project_id,
                    "subject_type": "report_export",
                    "subject_id": report_export_id,
                    "report_export_ids": [report_export_id],
                    "score_snapshot_ids": [snapshot_id],
                    "score_contribution_ids": [contribution_id],
                    "answer_run_ids": [answer_run_id],
                    "raw_answer_ids": [raw_answer_id],
                    "answer_citation_ids": [citation_id],
                    "evidence_asset_ids": [asset_id],
                    "source_graph_ids": [source_graph_id],
                    "source_gap_types": ["official_site:missing_high_weight_source_type"],
                    "action_recommendation_ids": [action_id],
                    "content_draft_ids": [draft_id],
                    "audit_event_ids": [audit_event_id],
                    "explanation_summary": "Report worker-runtime-v1 traces 1 answer runs.",
                },
                report_row,
                snapshot_row,
                [
                    {
                        "id": contribution_id,
                        "score_snapshot_id": snapshot_id,
                        "component_name": "MentionScore",
                        "component_score": 100.0,
                        "weight": 0.18,
                        "weighted_contribution": 18.0,
                        "denominator": "surface_triggered",
                        "evidence_answer_run_ids": [answer_run_id],
                        "positive_evidence_summary": "brand mentioned",
                        "negative_evidence_summary": "",
                        "confidence_note": "avg_parser_confidence=0.9",
                        "created_at": now,
                    }
                ],
                [answer_run_row],
                {
                    "id": "d1466dad-237b-5f5f-b7cc-44e67d628d15",
                    "answer_run_id": answer_run_id,
                    "parser_engine_id": "rule_based_v2_aliases",
                    "analysis_version": "rule_based_v2_aliases",
                    "payload": {"brand_mentioned": True},
                    "confidence": 0.9,
                    "created_at": now,
                },
                [],
                answer_run_row,
                {
                    "id": raw_answer_id,
                    "answer_run_id": answer_run_id,
                    "answer_text": "answer",
                    "raw_payload": {"citations": 1},
                    "raw_payload_hash": "hash",
                    "created_at": now,
                },
                [
                    {
                        "id": citation_id,
                        "answer_run_id": answer_run_id,
                        "url": "https://reviews.example/koala",
                        "domain": "reviews.example",
                        "position": 1,
                        "source_type": "review_site",
                        "created_at": now,
                    }
                ],
                [
                    {
                        "id": asset_id,
                        "answer_run_id": answer_run_id,
                        "asset_type": "html_snapshot",
                        "url": "s3://asset.html",
                        "content_hash": "asset-hash",
                        "created_at": now,
                    }
                ],
                [],
                None,
                [audit_row],
                {"count": 1},
                [
                    {
                        "id": source_graph_id,
                        "project_id": project_id,
                        "source_url": "https://reviews.example/koala",
                        "source_domain": "reviews.example",
                        "source_type": "review_site",
                        "topic": "reviews",
                        "source_gap_type": None,
                        "answer_run_ids": [answer_run_id],
                        "citation_count": 1,
                        "created_at": now,
                    }
                ],
                answer_run_row,
                [],
                [],
                [],
                action_row,
                draft_row,
                {
                    "id": prompt_id,
                    "project_id": project_id,
                    "market_code": "AU",
                    "industry_code": "dtc_ecommerce",
                    "text": "Is ExampleBrand good in Australia?",
                    "intent_type": "brand_awareness",
                    "city": "Australia",
                    "language": "en-AU",
                    "target_brand": "ExampleBrand",
                    "competitors": ["CompetitorA"],
                    "priority": 1,
                    "intent_weight": 1.0,
                    "prompt_version": "au_dtc_ecommerce_v1",
                    "status": "active",
                },
                fact_row,
                answer_run_row,
                action_row,
                [],
                [],
                audit_row,
                [
                    {
                        "id": "53ce3658-f908-56bf-b6de-585bcb7900d1",
                        "project_id": project_id,
                        "source_type": "report_export",
                        "source_id": report_export_id,
                        "target_type": "visibility_score_snapshot",
                        "target_id": snapshot_id,
                        "relation_type": "contains_score_snapshot",
                        "answer_run_ids": [answer_run_id],
                    }
                ],
            ]
        )
        detail = PostgresEvidenceRepository(connection).get_runtime_traceability_detail(
            project_id=project_id,
            report_export_id=report_export_id,
        )
        self.assertIsInstance(detail, RuntimeTraceabilityDetail)
        assert detail is not None
        self.assertEqual(detail.traceability_bundle["subject_id"], report_export_id)
        self.assertEqual(detail.report_exports[0]["report_version"], "worker-runtime-v1")
        self.assertEqual(detail.score_snapshots[0].snapshot["final_score"], 87.35)
        self.assertEqual(detail.evidence_runs[0].raw_answer["id"], raw_answer_id)
        self.assertEqual(detail.evidence_runs[0].citations[0]["id"], citation_id)
        self.assertIsNotNone(detail.citation_graph)
        assert detail.citation_graph is not None
        self.assertEqual(detail.citation_graph.nodes[0].node["source_domain"], "reviews.example")
        self.assertEqual(detail.action_recommendations[0]["id"], action_id)
        self.assertEqual(detail.content_drafts[0].draft["review_status"], "pending_human_review")
        self.assertEqual(detail.audit_events[0]["event_type"], "answer_run_collected")
        self.assertEqual(detail.evidence_links[0]["relation_type"], "contains_score_snapshot")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM traceability_bundles WHERE subject_type = %s", executed_sql)
        self.assertIn("FROM evidence_links WHERE project_id = %s", executed_sql)
        self.assertIn("FROM report_exports WHERE id = %s", executed_sql)
        self.assertIn("FROM content_drafts WHERE id = %s", executed_sql)

    def test_postgres_repository_saves_runtime_saved_view_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        saved_view_id = "dcb0b54f-2d65-5ce3-bd46-c08b85bc4020e"
        saved_view_row = {
            "id": saved_view_id,
            "project_id": project_id,
            "name": "Perplexity Sydney",
            "view_type": "runtime_evidence",
            "filters": {"platform": "perplexity", "city": "Sydney", "intent_type": "brand_awareness"},
            "sort": "cost_desc",
            "query_path": "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc&limit=5",
            "export_path": "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&intent_type=brand_awareness&sort=cost_desc&limit=200",
            "created_by": "runtime-console",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "725067ce-00b5-49a5-a3ec-8b8e74c85f4f",
            "event_type": "runtime_saved_view_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "runtime_saved_view",
            "target_id": saved_view_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"query_path": [saved_view_row["query_path"]]},
            "output_refs": {"runtime_saved_view_ids": [saved_view_id]},
            "method_version": "runtime_saved_view_v1",
            "reason": "save runtime evidence filter view",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[None, saved_view_row, [audit_row]])
        record = PostgresEvidenceRepository(connection).save_runtime_saved_view(
            RuntimeSavedViewInput(
                project_id=project_id,
                name="Perplexity Sydney",
                view_type="runtime_evidence",
                filters=saved_view_row["filters"],
                sort="cost_desc",
                query_path=saved_view_row["query_path"],
                export_path=saved_view_row["export_path"],
                created_by="runtime-console",
            )
        )
        self.assertIsInstance(record, RuntimeSavedView)
        self.assertEqual(record.saved_view["name"], "Perplexity Sydney")
        self.assertEqual(record.saved_view["sort"], "cost_desc")
        self.assertEqual(record.audit_events[0]["event_type"], "runtime_saved_view_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO runtime_saved_views", executed_sql)
        self.assertIn("ON CONFLICT (project_id, name) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_runtime_saved_views_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        saved_view_id = "dcb0b54f-2d65-5ce3-bd46-c08b85bc4020e"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": saved_view_id,
                        "project_id": project_id,
                        "name": "Perplexity Sydney",
                        "view_type": "runtime_evidence",
                        "filters": {"platform": "perplexity", "city": "Sydney"},
                        "sort": "cost_desc",
                        "query_path": "/v1/evidence-runs/runtime?platform=perplexity&city=Sydney&sort=cost_desc&limit=5",
                        "export_path": "/v1/evidence-runs/runtime/export.csv?platform=perplexity&city=Sydney&sort=cost_desc&limit=200",
                        "created_by": "runtime-console",
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
                [
                    {
                        "id": "725067ce-00b5-49a5-a3ec-8b8e74c85f4f",
                        "event_type": "runtime_saved_view_saved",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "runtime-console",
                        "target_type": "runtime_saved_view",
                        "target_id": saved_view_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {},
                        "output_refs": {"runtime_saved_view_ids": [saved_view_id]},
                        "method_version": "runtime_saved_view_v1",
                        "reason": "save runtime evidence filter view",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_saved_views(
            project_id=project_id,
            view_type="runtime_evidence",
            limit=5,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeSavedViewPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].saved_view["name"], "Perplexity Sydney")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "runtime_saved_view_saved")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM runtime_saved_views WHERE project_id = %s AND view_type = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_saves_project_brand_kit_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_kit_id = "0ada83ad-b669-507e-b3c8-9d8574569a62"
        brand_kit_row = {
            "id": brand_kit_id,
            "project_id": project_id,
            "client_name": "Koala AU",
            "prepared_by": "Partner Agency",
            "logo_url": "https://koala.example/logo.png",
            "primary_color": "#0f766e",
            "secondary_color": "#111827",
            "footer_text": "Prepared for Koala AU board review",
            "updated_by": "runtime-console",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
            "event_type": "project_brand_kit_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "project_brand_kit",
            "target_id": brand_kit_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"project_ids": [project_id]},
            "output_refs": {"project_brand_kit_ids": [brand_kit_id]},
            "method_version": "project_brand_kit_v1",
            "reason": "save project white-label brand configuration",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, brand_kit_row, [audit_row]])
        record = PostgresEvidenceRepository(connection).save_project_brand_kit(
            RuntimeProjectBrandKitInput(
                project_id=project_id,
                client_name="Koala AU",
                prepared_by="Partner Agency",
                logo_url="https://koala.example/logo.png",
                primary_color="#0f766e",
                secondary_color="#111827",
                footer_text="Prepared for Koala AU board review",
                updated_by="runtime-console",
            )
        )
        self.assertIsInstance(record, RuntimeProjectBrandKit)
        self.assertEqual(record.brand_kit["client_name"], "Koala AU")
        self.assertEqual(record.brand_kit["prepared_by"], "Partner Agency")
        self.assertEqual(record.audit_events[0]["event_type"], "project_brand_kit_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO project_brand_kits", executed_sql)
        self.assertIn("ON CONFLICT (project_id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_uploads_project_brand_logo_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_kit_id = "0ada83ad-b669-507e-b3c8-9d8574569a62"
        before_row = {
            "id": brand_kit_id,
            "project_id": project_id,
            "client_name": "Koala AU",
            "prepared_by": "Partner Agency",
            "logo_url": "https://koala.example/old-logo.png",
            "primary_color": "#0f766e",
            "secondary_color": "#111827",
            "footer_text": "Prepared for Koala AU board review",
            "updated_by": "runtime-console",
            "created_at": now,
            "updated_at": now,
        }
        saved_row = {
            **before_row,
            "logo_url": f"s3://geno-reports/brand-assets/{project_id}/logo-25f766a3e701-Client-Logo.png",
            "updated_by": "agency-user",
        }
        brand_asset_id = "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4"
        brand_asset_row = {
            "id": brand_asset_id,
            "project_id": project_id,
            "asset_type": "logo",
            "asset_url": saved_row["logo_url"],
            "category": "brand_logo",
            "source_filename": "Client Logo.png",
            "source_content_type": "image/png",
            "content_hash": "25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b",
            "storage_version": "25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b",
            "status": "active",
            "uploaded_by": "agency-user",
            "metadata": {"source": "logo_upload", "brand_kit_id": brand_kit_id},
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "ce333139-53e7-44c8-8c85-ce498d841391",
            "event_type": "project_brand_logo_uploaded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-user",
            "target_type": "project_brand_kit",
            "target_id": brand_kit_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "project_ids": [project_id],
                "source_filename": ["Client Logo.png"],
                "source_content_type": ["image/png"],
                "content_hash": ["25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b"],
            },
            "output_refs": {
                "project_brand_kit_ids": [brand_kit_id],
                "logo_url": [saved_row["logo_url"]],
            },
            "method_version": "project_brand_logo_upload_v1",
            "reason": "archive project brand logo asset and update white-label defaults",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id, "target_brand": "Koala"},
                before_row,
                None,
                brand_asset_row,
                saved_row,
                [audit_row],
            ]
        )
        record = PostgresEvidenceRepository(connection).upload_project_brand_logo(
            RuntimeProjectBrandLogoUpload(
                project_id=project_id,
                logo_url=saved_row["logo_url"],
                filename="Client Logo.png",
                content_type="image/png",
                content_hash="25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b",
                uploaded_by="agency-user",
            )
        )

        self.assertIsInstance(record, RuntimeProjectBrandKit)
        self.assertEqual(record.brand_kit["logo_url"], saved_row["logo_url"])
        self.assertEqual(record.audit_events[0]["event_type"], "project_brand_logo_uploaded")
        self.assertEqual(record.audit_events[0]["input_refs"]["content_hash"][0], "25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b")
        self.assertEqual(record.audit_events[0]["output_refs"]["logo_url"][0], saved_row["logo_url"])
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT id, target_brand FROM projects", executed_sql)
        self.assertIn("ON CONFLICT (project_id) DO UPDATE SET logo_url = EXCLUDED.logo_url", executed_sql)
        self.assertIn("INSERT INTO project_brand_assets", executed_sql)
        self.assertIn("ON CONFLICT (project_id, asset_url) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_project_brand_asset_versions_from_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        active_logo_url = f"s3://geno-reports/brand-assets/{project_id}/logo-active.png"
        brand_kit_row = {
            "id": "0ada83ad-b669-507e-b3c8-9d8574569a62",
            "project_id": project_id,
            "client_name": "Koala AU",
            "prepared_by": "Partner Agency",
            "logo_url": active_logo_url,
            "primary_color": "#0f766e",
            "secondary_color": "#111827",
            "footer_text": "Prepared for Koala AU board review",
            "updated_by": "agency-user",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "ce333139-53e7-44c8-8c85-ce498d841391",
            "event_type": "project_brand_logo_uploaded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-user",
            "target_type": "project_brand_kit",
            "target_id": brand_kit_row["id"],
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "project_ids": [project_id],
                "source_filename": ["Client Logo.png"],
                "source_content_type": ["image/png"],
                "content_hash": ["25f766a3e70154aacaa073a049855d207842f9f6a743c082e693c2cadde4ed1b"],
            },
            "output_refs": {
                "project_brand_kit_ids": [brand_kit_row["id"]],
                "logo_url": [active_logo_url],
            },
            "method_version": "project_brand_logo_upload_v1",
            "reason": "archive project brand logo asset and update white-label defaults",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[brand_kit_row, {"count": 1}, [audit_row]])

        page = PostgresEvidenceRepository(connection).list_project_brand_asset_versions(
            project_id=project_id,
            limit=20,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeProjectBrandAssetVersionPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].asset_url, active_logo_url)
        self.assertEqual(page.records[0].source_filename, "Client Logo.png")
        self.assertEqual(page.records[0].source_content_type, "image/png")
        self.assertTrue(page.records[0].is_active)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s", executed_sql)
        self.assertIn("output_refs ? %s", executed_sql)

    def test_postgres_repository_saves_project_brand_asset_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        asset_id = "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4"
        asset_url = f"s3://geno-reports/brand-assets/{project_id}/hero.png"
        asset_row = {
            "id": asset_id,
            "project_id": project_id,
            "asset_type": "image",
            "asset_url": asset_url,
            "category": "brand_creative",
            "preview_url": f"https://cdn.example.com/{project_id}/hero-preview.png",
            "source_filename": "hero.png",
            "source_content_type": "image/png",
            "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
            "storage_version": "etag-hero-v1",
            "status": "active",
            "scan_status": "pending",
            "scan_checked_at": None,
            "scan_method_version": None,
            "scan_notes": None,
            "uploaded_by": "agency-user",
            "metadata": {"source": "runtime_console_asset_register"},
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "a1305659-1540-4529-86d8-8e90c6b5d446",
            "event_type": "project_brand_asset_registered",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-user",
            "target_type": "project_brand_asset",
            "target_id": asset_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {
                "project_ids": [project_id],
                "asset_url": [asset_url],
                "preview_url": [f"https://cdn.example.com/{project_id}/hero-preview.png"],
                "source_filename": ["hero.png"],
                "source_content_type": ["image/png"],
                "content_hash": ["4d8f0cfa7e4b8f76dd5bce99d403d9fa"],
            },
            "output_refs": {
                "project_brand_asset_ids": [asset_id],
                "asset_url": [asset_url],
                "storage_version": ["etag-hero-v1"],
            },
            "method_version": "project_brand_asset_library_v1",
            "reason": "register project brand asset in library",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, asset_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_project_brand_asset(
            RuntimeProjectBrandAssetInput(
                project_id=project_id,
                asset_type="image",
                asset_url=asset_url,
                category="brand_creative",
                preview_url=f"https://cdn.example.com/{project_id}/hero-preview.png",
                source_filename="hero.png",
                source_content_type="image/png",
                content_hash="4d8f0cfa7e4b8f76dd5bce99d403d9fa",
                storage_version="etag-hero-v1",
                status="active",
                uploaded_by="agency-user",
                metadata={"source": "runtime_console_asset_register"},
            )
        )

        self.assertIsInstance(record, RuntimeProjectBrandAsset)
        self.assertEqual(record.asset["asset_url"], asset_url)
        self.assertEqual(record.asset["category"], "brand_creative")
        self.assertEqual(record.audit_events[0]["event_type"], "project_brand_asset_registered")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO project_brand_assets", executed_sql)
        self.assertIn("ON CONFLICT (project_id, asset_url) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_project_brand_assets(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        asset_id = "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4"
        asset_url = f"s3://geno-reports/brand-assets/{project_id}/hero.png"
        asset_row = {
            "id": asset_id,
            "project_id": project_id,
            "asset_type": "image",
            "asset_url": asset_url,
            "category": "brand_creative",
            "preview_url": f"https://cdn.example.com/{project_id}/hero-preview.png",
            "source_filename": "hero.png",
            "source_content_type": "image/png",
            "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
            "storage_version": "etag-hero-v1",
            "status": "active",
            "scan_status": "passed",
            "scan_checked_at": now,
            "scan_method_version": "manual_asset_scan_v1",
            "scan_notes": "Clean preview",
            "uploaded_by": "agency-user",
            "metadata": {"source": "runtime_console_asset_register"},
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "a1305659-1540-4529-86d8-8e90c6b5d446",
            "event_type": "project_brand_asset_registered",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-user",
            "target_type": "project_brand_asset",
            "target_id": asset_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"project_ids": [project_id], "asset_url": [asset_url]},
            "output_refs": {"project_brand_asset_ids": [asset_id], "asset_url": [asset_url]},
            "method_version": "project_brand_asset_library_v1",
            "reason": "register project brand asset in library",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [asset_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).list_project_brand_assets(
            project_id=project_id,
            asset_type="image",
            category="brand_creative",
            status="active",
            limit=20,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeProjectBrandAssetPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].asset["asset_url"], asset_url)
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "project_brand_asset_registered")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_brand_assets WHERE project_id = %s AND asset_type = %s", executed_sql)
        self.assertIn("ORDER BY updated_at DESC, created_at DESC, id DESC", executed_sql)

    def test_postgres_repository_updates_project_brand_asset_scan_status_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        asset_id = "ddc23a34-2ffb-5a56-a81a-3b98aaf843b4"
        asset_url = f"s3://geno-reports/brand-assets/{project_id}/hero.png"
        before_row = {
            "id": asset_id,
            "project_id": project_id,
            "asset_type": "image",
            "asset_url": asset_url,
            "category": "brand_creative",
            "preview_url": f"https://cdn.example.com/{project_id}/hero-preview.png",
            "source_filename": "hero.png",
            "source_content_type": "image/png",
            "content_hash": "4d8f0cfa7e4b8f76dd5bce99d403d9fa",
            "storage_version": "etag-hero-v1",
            "status": "active",
            "scan_status": "pending",
            "scan_checked_at": None,
            "scan_method_version": None,
            "scan_notes": None,
            "uploaded_by": "agency-user",
            "metadata": {"source": "runtime_console_asset_register"},
            "created_at": now,
            "updated_at": now,
        }
        after_row = {
            **before_row,
            "scan_status": "passed",
            "scan_checked_at": now,
            "scan_method_version": "manual_asset_scan_v1",
            "scan_notes": "Clean preview",
        }
        audit_row = {
            "id": "a1305659-1540-4529-86d8-8e90c6b5d446",
            "event_type": "project_brand_asset_scan_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-user",
            "target_type": "project_brand_asset",
            "target_id": asset_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {
                "project_brand_asset_ids": [asset_id],
                "asset_url": [asset_url],
                "scan_status": ["passed"],
            },
            "output_refs": {
                "project_brand_asset_ids": [asset_id],
                "scan_status": ["passed"],
                "scan_method_version": ["manual_asset_scan_v1"],
            },
            "method_version": "manual_asset_scan_v1",
            "reason": "manual scan passed",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[before_row, after_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).update_project_brand_asset_scan_status(
            RuntimeProjectBrandAssetScanInput(
                asset_id=asset_id,
                scan_status="passed",
                scanned_by="agency-user",
                scan_notes="Clean preview",
                reason="manual scan passed",
            )
        )

        self.assertIsInstance(record, RuntimeProjectBrandAsset)
        self.assertEqual(record.asset["scan_status"], "passed")
        self.assertEqual(record.audit_events[0]["event_type"], "project_brand_asset_scan_recorded")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("UPDATE project_brand_assets", executed_sql)
        self.assertIn("scan_status = %s", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_activates_project_brand_asset_version(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_kit_id = "0ada83ad-b669-507e-b3c8-9d8574569a62"
        previous_logo_url = f"s3://geno-reports/brand-assets/{project_id}/logo-previous.png"
        current_logo_url = f"s3://geno-reports/brand-assets/{project_id}/logo-current.png"
        version_audit_row = {
            "id": "ce333139-53e7-44c8-8c85-ce498d841391",
            "event_type": "project_brand_logo_uploaded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-user",
            "target_type": "project_brand_kit",
            "target_id": brand_kit_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"source_filename": ["Old Logo.png"]},
            "output_refs": {"project_brand_kit_ids": [brand_kit_id], "logo_url": [previous_logo_url]},
            "method_version": "project_brand_logo_upload_v1",
            "reason": "archive project brand logo asset and update white-label defaults",
            "created_at": now,
        }
        before_row = {
            "id": brand_kit_id,
            "project_id": project_id,
            "client_name": "Koala AU",
            "prepared_by": "Partner Agency",
            "logo_url": current_logo_url,
            "primary_color": "#0f766e",
            "secondary_color": "#111827",
            "footer_text": "Prepared for Koala AU board review",
            "updated_by": "runtime-console",
            "created_at": now,
            "updated_at": now,
        }
        saved_row = {
            **before_row,
            "logo_url": previous_logo_url,
            "updated_by": "agency-admin",
        }
        activation_audit_row = {
            "id": "5de7d441-5d21-4f1d-a2f6-a09d2fdbef84",
            "event_type": "project_brand_logo_version_activated",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "agency-admin",
            "target_type": "project_brand_kit",
            "target_id": brand_kit_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"source_audit_event_ids": [version_audit_row["id"]]},
            "output_refs": {"project_brand_kit_ids": [brand_kit_id], "logo_url": [previous_logo_url]},
            "method_version": "project_brand_logo_asset_version_v1",
            "reason": "restore previous logo",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id, "target_brand": "Koala"},
                [version_audit_row],
                before_row,
                saved_row,
                [activation_audit_row],
            ]
        )

        record = PostgresEvidenceRepository(connection).activate_project_brand_logo_version(
            RuntimeProjectBrandAssetActivationInput(
                project_id=project_id,
                asset_url=previous_logo_url,
                activated_by="agency-admin",
                reason="restore previous logo",
            )
        )

        self.assertIsInstance(record, RuntimeProjectBrandKit)
        self.assertEqual(record.brand_kit["logo_url"], previous_logo_url)
        self.assertEqual(record.audit_events[0]["event_type"], "project_brand_logo_version_activated")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("event_type IN (%s, %s)", executed_sql)
        self.assertIn("ON CONFLICT (project_id) DO UPDATE SET logo_url = EXCLUDED.logo_url", executed_sql)
        audit_insert = next(params for sql, params in connection.calls if "INSERT INTO audit_events" in sql)
        self.assertEqual(audit_insert[1], "project_brand_logo_version_activated")
        self.assertEqual(audit_insert[4], "agency-admin")
        self.assertEqual(audit_insert[12], "restore previous logo")

    def test_postgres_repository_reads_project_brand_kit_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_kit_id = "0ada83ad-b669-507e-b3c8-9d8574569a62"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": brand_kit_id,
                    "project_id": project_id,
                    "client_name": "Koala AU",
                    "prepared_by": "Partner Agency",
                    "logo_url": "https://koala.example/logo.png",
                    "primary_color": "#0f766e",
                    "secondary_color": "#111827",
                    "footer_text": "Prepared for Koala AU board review",
                    "updated_by": "runtime-console",
                    "created_at": now,
                    "updated_at": now,
                },
                [
                    {
                        "id": "2782a901-8cdf-47e7-bbdb-345d9ca66efe",
                        "event_type": "project_brand_kit_saved",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "runtime-console",
                        "target_type": "project_brand_kit",
                        "target_id": brand_kit_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"project_ids": [project_id]},
                        "output_refs": {"project_brand_kit_ids": [brand_kit_id]},
                        "method_version": "project_brand_kit_v1",
                        "reason": "save project white-label brand configuration",
                        "created_at": now,
                    }
                ],
            ]
        )
        record = PostgresEvidenceRepository(connection).get_project_brand_kit(project_id=project_id)
        self.assertIsInstance(record, RuntimeProjectBrandKit)
        assert record is not None
        self.assertEqual(record.brand_kit["client_name"], "Koala AU")
        self.assertEqual(record.audit_events[0]["target_type"], "project_brand_kit")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM project_brand_kits WHERE project_id = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_saves_score_weight_config_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        config_id = "7daa9492-8fb2-565e-827a-bfd3de846cde"
        weights = {
            **AU_VISIBILITY_V1,
            "MentionScore": 0.20,
            "FreshnessScore": 0.03,
        }
        config_row = {
            "id": config_id,
            "project_id": project_id,
            "formula_version": "au_visibility_v1",
            "weights": weights,
            "updated_by": "runtime-console",
            "notes": "prioritize mention",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "2d3d80f1-74de-49ee-a990-a47e44d88ccf",
            "event_type": "score_weight_config_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "score_weight_config",
            "target_id": config_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"project_ids": [project_id]},
            "output_refs": {"score_weight_config_ids": [config_id]},
            "method_version": "score_weight_config_v1",
            "reason": "save project-level AU visibility score weights",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, config_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_score_weight_config(
            RuntimeScoreWeightConfigInput(
                project_id=project_id,
                weights=weights,
                updated_by="runtime-console",
                notes="prioritize mention",
            )
        )

        self.assertIsInstance(record, RuntimeScoreWeightConfig)
        self.assertEqual(record.score_weight_config["weights"]["MentionScore"], 0.20)
        self.assertEqual(record.audit_events[0]["event_type"], "score_weight_config_saved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO score_weight_configs", executed_sql)
        self.assertIn("ON CONFLICT (project_id, formula_version) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_saves_candidate_score_formula_weights(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        config_id = "74ef8cfb-06e4-5659-a178-d1e3ee7dc7cb"
        config_row = {
            "id": config_id,
            "project_id": project_id,
            "formula_version": "au_visibility_v1_1_local_boost",
            "weights": AU_VISIBILITY_V1_1_LOCAL_BOOST,
            "updated_by": "runtime-console",
            "notes": "test local boost formula",
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "2d3d80f1-74de-49ee-a990-a47e44d88ccf",
            "event_type": "score_weight_config_saved",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "score_weight_config",
            "target_id": config_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"project_ids": [project_id]},
            "output_refs": {"score_weight_config_ids": [config_id]},
            "method_version": "score_weight_config_v1",
            "reason": "save project-level AU visibility score weights",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, None, config_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_score_weight_config(
            RuntimeScoreWeightConfigInput(
                project_id=project_id,
                formula_version="au_visibility_v1_1_local_boost",
                weights=AU_VISIBILITY_V1_1_LOCAL_BOOST,
                updated_by="runtime-console",
                notes="test local boost formula",
            )
        )

        self.assertEqual(record.score_weight_config["formula_version"], "au_visibility_v1_1_local_boost")
        self.assertEqual(record.score_weight_config["weights"], AU_VISIBILITY_V1_1_LOCAL_BOOST)
        insert_params = next(params for sql, params in connection.calls if "INSERT INTO score_weight_configs" in sql)
        self.assertEqual(insert_params[2], "au_visibility_v1_1_local_boost")

    def test_postgres_repository_reads_score_weight_config_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        config_id = "7daa9492-8fb2-565e-827a-bfd3de846cde"
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": config_id,
                    "project_id": project_id,
                    "formula_version": "au_visibility_v1",
                    "weights": AU_VISIBILITY_V1,
                    "updated_by": "runtime-console",
                    "notes": "default review",
                    "created_at": now,
                    "updated_at": now,
                },
                [
                    {
                        "id": "2d3d80f1-74de-49ee-a990-a47e44d88ccf",
                        "event_type": "score_weight_config_saved",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "runtime-console",
                        "target_type": "score_weight_config",
                        "target_id": config_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"project_ids": [project_id]},
                        "output_refs": {"score_weight_config_ids": [config_id]},
                        "method_version": "score_weight_config_v1",
                        "reason": "save project-level AU visibility score weights",
                        "created_at": now,
                    }
                ],
            ]
        )
        record = PostgresEvidenceRepository(connection).get_score_weight_config(project_id=project_id)
        self.assertIsInstance(record, RuntimeScoreWeightConfig)
        assert record is not None
        self.assertEqual(record.score_weight_config["weights"], AU_VISIBILITY_V1)
        self.assertEqual(record.audit_events[0]["target_type"], "score_weight_config")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM score_weight_configs WHERE project_id = %s AND formula_version = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_saves_human_review_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        target_id = "38f0251c-c380-4197-b6c9-3e630b127844"
        review_row = {
            "id": "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7",
            "project_id": project_id,
            "target_type": "visibility_score_snapshot",
            "target_id": target_id,
            "review_status": "approved",
            "decision": "approved_for_report",
            "reviewer_id": "runtime-console",
            "notes": "reviewed score evidence",
            "payload": {"source": "runtime-console"},
            "created_at": now,
        }
        audit_row = {
            "id": "b9b398cf-7a61-465e-bfdd-0870b9633523",
            "event_type": "human_review_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "human_review_record",
            "target_id": review_row["id"],
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"review_target": [{"target_type": "visibility_score_snapshot", "target_id": target_id}]},
            "output_refs": {"human_review_record_ids": [review_row["id"]]},
            "method_version": "human_review_v1",
            "reason": "record human review decision for an auditable runtime object",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, review_row, [audit_row]])

        record = PostgresEvidenceRepository(connection).save_human_review(
            RuntimeHumanReviewInput(
                project_id=project_id,
                target_type="visibility_score_snapshot",
                target_id=target_id,
                review_status="approved",
                decision="approved_for_report",
                reviewer_id="runtime-console",
                notes="reviewed score evidence",
                payload={"source": "runtime-console"},
            )
        )

        self.assertIsInstance(record, RuntimeHumanReviewRecord)
        self.assertEqual(record.human_review["decision"], "approved_for_report")
        self.assertEqual(record.audit_events[0]["event_type"], "human_review_recorded")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO human_review_records", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_saves_content_draft_review_and_updates_draft_status(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        target_id = "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd"
        draft_row = {
            "id": target_id,
            "project_id": project_id,
            "title": "AU shipping proof page",
            "content_type": "evidence_backed_outline",
            "content_template_id": "faq_for_australian_customers",
            "target_question_ids": [],
            "target_city": "Sydney",
            "target_platform": "chatgpt/perplexity",
            "target_source_type": "official_site",
            "used_knowledge_fact_ids": [],
            "source_gap_types": ["low_mention_rate"],
            "source_action_id": None,
            "evidence_answer_run_ids": ["438ab927-5873-5516-8df3-47f6c75ef007"],
            "draft_markdown": "# AU shipping",
            "review_status": "pending_human_review",
            "created_by": "geno-core.knowledge",
            "created_at": now,
        }
        review_row = {
            "id": "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7",
            "project_id": project_id,
            "target_type": "content_draft",
            "target_id": target_id,
            "review_status": "approved",
            "decision": "approved_for_publish",
            "reviewer_id": "editor@example.com",
            "notes": "approved content evidence",
            "payload": {"source": "runtime-console"},
            "created_at": now,
        }
        audit_rows = [
            {
                "id": "b9b398cf-7a61-465e-bfdd-0870b9633523",
                "event_type": "human_review_recorded",
                "project_id": project_id,
                "actor_type": "user",
                "actor_id": "editor@example.com",
                "target_type": "human_review_record",
                "target_id": review_row["id"],
                "before_hash": None,
                "after_hash": "after",
                "input_refs": {"review_target": [{"target_type": "content_draft", "target_id": target_id}]},
                "output_refs": {"human_review_record_ids": [review_row["id"]]},
                "method_version": "human_review_v1",
                "reason": "record human review decision for an auditable runtime object",
                "created_at": now,
            }
        ]
        connection = RecordingConnection(result_sets=[{"id": project_id}, draft_row, review_row, audit_rows])

        record = PostgresEvidenceRepository(connection).save_human_review(
            RuntimeHumanReviewInput(
                project_id=project_id,
                target_type="content_draft",
                target_id=target_id,
                review_status="approved",
                decision="approved_for_publish",
                reviewer_id="editor@example.com",
                notes="approved content evidence",
                payload={"source": "runtime-console"},
            )
        )

        self.assertEqual(record.human_review["target_type"], "content_draft")
        self.assertEqual(record.human_review["review_status"], "approved")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT id FROM projects WHERE id = %s LIMIT 1", executed_sql)
        self.assertIn("FROM content_drafts WHERE id = %s AND project_id = %s", executed_sql)
        self.assertIn("UPDATE content_drafts SET review_status = %s WHERE id = %s AND project_id = %s", executed_sql)
        self.assertIn("content_draft_review_status_projection_v1", str(connection.calls))

    def test_postgres_repository_lists_runtime_human_reviews_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        review_id = "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7"
        review_row = {
            "id": review_id,
            "project_id": project_id,
            "target_type": "content_draft",
            "target_id": "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
            "review_status": "needs_changes",
            "decision": "rewrite_local_examples",
            "reviewer_id": "editor@example.com",
            "notes": "needs stronger AU evidence",
            "payload": {"target_label": "draft"},
            "created_at": now,
        }
        audit_row = {
            "id": "b9b398cf-7a61-465e-bfdd-0870b9633523",
            "event_type": "human_review_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "editor@example.com",
            "target_type": "human_review_record",
            "target_id": review_id,
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"review_target": [{"target_type": "content_draft", "target_id": review_row["target_id"]}]},
            "output_refs": {"human_review_record_ids": [review_id]},
            "method_version": "human_review_v1",
            "reason": "record human review decision for an auditable runtime object",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [review_row], [audit_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_human_reviews(
            project_id=project_id,
            target_type="content_draft",
            review_status="needs_changes",
            limit=5,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeHumanReviewPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].human_review["decision"], "rewrite_local_examples")
        self.assertEqual(page.records[0].audit_events[0]["target_type"], "human_review_record")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM human_review_records WHERE project_id = %s AND target_type = %s AND review_status = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_exports_runtime_human_reviews_csv(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        review_id = "f25cdddc-c3e7-4fcb-90b8-557fd6465ea7"
        review_row = {
            "id": review_id,
            "project_id": project_id,
            "target_type": "content_draft",
            "target_id": "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
            "review_status": "needs_changes",
            "decision": "rewrite_local_examples",
            "reviewer_id": "editor@example.com",
            "notes": "needs stronger AU evidence",
            "payload": {"target_label": "draft", "source": "runtime-console"},
            "created_at": now,
        }
        audit_row = {
            "id": "b9b398cf-7a61-465e-bfdd-0870b9633523",
            "event_type": "human_review_recorded",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "editor@example.com",
            "target_type": "human_review_record",
            "target_id": review_id,
            "before_hash": None,
            "after_hash": "review-after",
            "input_refs": {"review_target": [{"target_type": "content_draft", "target_id": review_row["target_id"]}]},
            "output_refs": {"human_review_record_ids": [review_id]},
            "method_version": "human_review_v1",
            "reason": "record human review decision for an auditable runtime object",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [review_row], [audit_row]])

        export = PostgresEvidenceRepository(connection).export_runtime_human_reviews_csv(
            project_id=project_id,
            target_type="content_draft",
            review_status="needs_changes",
            limit=10,
            offset=0,
        )

        self.assertEqual(export.export_type, "runtime_human_reviews_csv")
        self.assertEqual(export.filename, "runtime-human-reviews.csv")
        self.assertEqual(export.media_type, "text/csv; charset=utf-8")
        self.assertEqual(export.total_count, 1)
        self.assertEqual(export.row_count, 1)
        self.assertEqual(export.filters["project_id"], project_id)
        self.assertEqual(export.filters["target_type"], "content_draft")
        self.assertEqual(export.filters["review_status"], "needs_changes")
        self.assertIn("human_review_id,project_id,target_type,target_id", export.content)
        self.assertIn(review_id, export.content)
        self.assertIn("content_draft", export.content)
        self.assertIn("needs_changes", export.content)
        self.assertIn("source|target_label", export.content)
        self.assertIn(_artifact_hash("rewrite_local_examples"), export.content)
        self.assertIn(_artifact_hash("editor@example.com"), export.content)
        self.assertIn(_artifact_hash("needs stronger AU evidence"), export.content)
        self.assertIn("human_review_recorded", export.content)
        self.assertIn("human_review_v1", export.content)
        self.assertIn("review-after", export.content)
        self.assertNotIn("rewrite_local_examples", export.content)
        self.assertNotIn("editor@example.com", export.content)
        self.assertNotIn("needs stronger AU evidence", export.content)
        self.assertNotIn("runtime-console", export.content)
        self.assertEqual(export.content_hash, hashlib.sha256(export.content.encode("utf-8")).hexdigest())

    def test_postgres_repository_lists_runtime_human_review_queue(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        queue_row = {
            "project_id": project_id,
            "target_type": "content_draft",
            "target_id": "1e53e0b4-7b1a-54d6-a918-fd8774df7bdd",
            "title": "AU shipping proof page",
            "created_at": now,
            "priority": 9,
            "reason": "content_draft_pending_human_review",
            "evidence_refs": {
                "content_draft_ids": ["1e53e0b4-7b1a-54d6-a918-fd8774df7bdd"],
                "answer_run_ids": ["438ab927-5873-5516-8df3-47f6c75ef007"],
            },
            "queue_status": "pending_review",
            "latest_review": None,
        }
        connection = RecordingConnection(result_sets=[{"count": 1}, [queue_row]])

        page = PostgresEvidenceRepository(connection).list_runtime_human_review_queue(
            project_id=project_id,
            target_type="content_draft",
            queue_status="pending_review",
            limit=10,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeHumanReviewQueuePage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].queue_status, "pending_review")
        self.assertEqual(page.records[0].priority, 9)
        self.assertEqual(page.records[0].evidence_refs["answer_run_ids"], ["438ab927-5873-5516-8df3-47f6c75ef007"])
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM visibility_score_snapshots vss", executed_sql)
        self.assertIn("FROM content_drafts cd", executed_sql)
        self.assertIn("FROM human_review_records", executed_sql)
        self.assertIn("candidate.project_id = %s", executed_sql)
        self.assertIn("candidate.queue_status = %s", executed_sql)
        self.assertIn("review_candidate.source_status IN ('approved', 'acknowledged') THEN 'reviewed'", executed_sql)

    def test_postgres_repository_confirms_entity_alias_with_audit_event(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        alias_row = {
            "id": "b7f7a2fb-9191-50f0-aa33-a56fed6b0ac5",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "examplebrand.com.au",
            "alias_type": "domain",
            "confidence": 1.0,
            "confirmed_by": "runtime-console",
            "created_at": now,
            "project_id": project_id,
            "canonical_name": "ExampleBrand",
            "official_domains": ["https://examplebrand.com.au"],
            "parent_company": None,
            "product_lines": ["mattresses"],
            "status": "active",
        }
        audit_row = {
            "id": "725067ce-00b5-49a5-a3ec-8b8e74c85f4f",
            "event_type": "entity_alias_confirmed",
            "project_id": project_id,
            "actor_type": "user",
            "actor_id": "runtime-console",
            "target_type": "entity_alias",
            "target_id": alias_row["id"],
            "before_hash": None,
            "after_hash": "after",
            "input_refs": {"entity_ids": [brand_id]},
            "output_refs": {"entity_alias_ids": [alias_row["id"]]},
            "method_version": "entity_alias_confirm_v1",
            "reason": "Runtime entity alias confirmation for parser disambiguation",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {
                    "id": brand_id,
                    "project_id": project_id,
                    "canonical_name": "ExampleBrand",
                    "official_domains": ["https://examplebrand.com.au"],
                    "parent_company": None,
                    "product_lines": ["mattresses"],
                    "status": "active",
                },
                None,
                alias_row,
                [audit_row],
            ]
        )
        record = PostgresEvidenceRepository(connection).confirm_entity_alias(
            EntityAliasInput(
                entity_id=brand_id,
                entity_kind="brand",
                alias="examplebrand.com.au",
                alias_type="domain",
                confirmed_by="runtime-console",
                notes="Runtime entity alias confirmation for parser disambiguation",
            )
        )
        self.assertIsInstance(record, RuntimeEntityAlias)
        self.assertEqual(record.entity_alias["alias"], "examplebrand.com.au")
        self.assertEqual(record.entity["canonical_name"], "ExampleBrand")
        self.assertEqual(record.audit_events[0]["event_type"], "entity_alias_confirmed")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM brand_entities WHERE id = %s", executed_sql)
        self.assertIn("INSERT INTO entity_aliases", executed_sql)
        self.assertIn("ON CONFLICT (id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_reads_confirmed_entity_alias_terms(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        competitor_id = "0c0a4e87-c27a-58ee-b379-3cf3adaf7c0d"
        connection = RecordingConnection(
            result_sets=[
                [
                    {"entity_id": brand_id, "alias": "ExampleBrand Australia"},
                    {"entity_id": brand_id, "alias": "examplebrand.com.au"},
                    {"entity_id": competitor_id, "alias": "Competitor AU"},
                    {"entity_id": brand_id, "alias": "ExampleBrand Australia"},
                ]
            ]
        )
        aliases = PostgresEvidenceRepository(connection).get_confirmed_entity_alias_terms(project_id)
        self.assertEqual(
            aliases,
            {
                brand_id: ("ExampleBrand Australia", "examplebrand.com.au"),
                competitor_id: ("Competitor AU",),
            },
        )
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_aliases ea JOIN", executed_sql)
        self.assertIn("entity.entity_kind = ea.entity_kind", executed_sql)
        self.assertIn("WHERE entity.project_id = %s", executed_sql)

    def test_postgres_repository_lists_runtime_entity_alias_candidates(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        connection = RecordingConnection(
            result_sets=[
                [
                    {
                        "id": brand_id,
                        "project_id": project_id,
                        "entity_kind": "brand",
                        "canonical_name": "ExampleBrand",
                        "official_domains": ["https://www.examplebrand.com.au"],
                        "parent_company": "Example Holdings",
                        "product_lines": ["mattresses", "pillows"],
                        "status": "active",
                    }
                ],
                [],
                [],
                [
                    {"entity_id": brand_id, "alias": "ExampleBrand Australia"},
                ],
                [],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_entity_alias_candidates(
            project_id=project_id,
            entity_kind="brand",
            limit=10,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeEntityAliasCandidatePage)
        aliases = [record.candidate["alias"] for record in page.records]
        self.assertNotIn("ExampleBrand Australia", aliases)
        self.assertIn("examplebrand.com.au", aliases)
        self.assertIn("mattresses", aliases)
        self.assertIn("pillows", aliases)
        self.assertIn("Example Holdings", aliases)
        self.assertEqual(page.records[0].confirmed_aliases, ("ExampleBrand Australia",))
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM ( SELECT id, project_id, 'brand' AS entity_kind", executed_sql)
        self.assertIn("WHERE entity.project_id = %s AND entity.entity_kind = %s", executed_sql)

    def test_postgres_repository_mines_runtime_entity_alias_candidates_from_evidence(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        answer_run_id = "0e6cb35e-340c-55df-9b7c-ed6965b6582d"
        connection = RecordingConnection(
            result_sets=[
                [
                    {
                        "id": brand_id,
                        "project_id": project_id,
                        "entity_kind": "brand",
                        "canonical_name": "ExampleBrand",
                        "official_domains": ["https://www.examplebrand.com.au"],
                        "parent_company": None,
                        "product_lines": [],
                        "status": "active",
                    }
                ],
                [
                    {
                        "answer_run_id": answer_run_id,
                        "answer_text": "Australian shoppers often compare Example Brand AU with local retailers.",
                    }
                ],
                [
                    {
                        "answer_run_id": answer_run_id,
                        "url": "https://shop.examplebrand.com.au/mattresses",
                        "domain": "shop.examplebrand.com.au",
                    },
                    {
                        "answer_run_id": answer_run_id,
                        "url": "https://www.examplebrand.com.au/reviews",
                        "domain": "examplebrand.com.au",
                    },
                    {
                        "answer_run_id": answer_run_id,
                        "url": "https://www.youtube.com/watch?v=examplebrand",
                        "domain": "youtube.com",
                    },
                ],
                [],
                [],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_entity_alias_candidates(
            project_id=project_id,
            entity_kind="brand",
            limit=20,
            offset=0,
        )

        candidates = {record.candidate["alias"]: record.candidate for record in page.records}
        self.assertIn("Example Brand AU", candidates)
        self.assertEqual(candidates["Example Brand AU"]["source"], "evidence_answer_text")
        self.assertEqual(candidates["Example Brand AU"]["evidence_count"], 1)
        self.assertEqual(candidates["Example Brand AU"]["evidence_answer_run_ids"], [answer_run_id])
        self.assertIn("shop.examplebrand.com.au", candidates)
        self.assertEqual(candidates["shop.examplebrand.com.au"]["source"], "evidence_citation_domain")
        self.assertEqual(candidates["shop.examplebrand.com.au"]["evidence_urls"], ["https://shop.examplebrand.com.au/mattresses"])
        self.assertEqual(candidates["examplebrand.com.au"]["source"], "official_domain")
        self.assertIn("evidence_citation_domain", candidates["examplebrand.com.au"]["supporting_sources"])
        self.assertNotIn("youtube.com", candidates)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("JOIN raw_answers ra ON ra.answer_run_id = ar.id", executed_sql)
        self.assertIn("JOIN answer_citations ac ON ac.answer_run_id = ar.id", executed_sql)

    def test_postgres_repository_filters_rejected_runtime_entity_alias_candidates(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        rejected_candidate_id = "38f1dbde-f011-542b-bf99-469c56c0ab49"
        connection = RecordingConnection(
            result_sets=[
                [
                    {
                        "id": brand_id,
                        "project_id": project_id,
                        "entity_kind": "brand",
                        "canonical_name": "ExampleBrand",
                        "official_domains": [],
                        "parent_company": None,
                        "product_lines": [],
                        "status": "active",
                    }
                ],
                [],
                [],
                [],
                [
                    {
                        "id": "9ab96227-e324-5b7b-b297-00aa6515236c",
                        "project_id": project_id,
                        "candidate_id": rejected_candidate_id,
                        "entity_id": brand_id,
                        "entity_kind": "brand",
                        "alias": "ExampleBrand Australia",
                        "alias_type": "alias",
                        "source": "canonical_name_market",
                        "confidence": 0.72,
                        "decision": "rejected",
                        "reviewed_by": "runtime-console",
                        "reason": "not the market alias",
                        "notes": "reject noisy candidate",
                        "evidence_answer_run_ids": [],
                        "evidence_urls": [],
                        "payload": {},
                        "created_at": datetime(2026, 6, 12, tzinfo=UTC),
                        "updated_at": datetime(2026, 6, 12, tzinfo=UTC),
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_runtime_entity_alias_candidates(
            project_id=project_id,
            entity_kind="brand",
            limit=20,
            offset=0,
        )

        aliases = [record.candidate["alias"] for record in page.records]
        self.assertNotIn("ExampleBrand Australia", aliases)
        self.assertEqual(page.total_count, 0)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_alias_candidate_reviews", executed_sql)

    def test_postgres_repository_records_runtime_entity_alias_candidate_review(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        candidate_id = "candidate-1"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        now = datetime(2026, 6, 12, tzinfo=UTC)
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                {"id": brand_id},
                None,
                {
                    "id": review_id,
                    "project_id": project_id,
                    "candidate_id": candidate_id,
                    "entity_id": brand_id,
                    "entity_kind": "brand",
                    "alias": "ExampleBrand AU",
                    "alias_type": "alias",
                    "source": "evidence_answer_text",
                    "confidence": 0.8,
                    "decision": "rejected",
                    "reviewed_by": "analyst-1",
                    "reason": "not an owned brand alias",
                    "notes": "Reject repeated noisy candidate",
                    "evidence_answer_run_ids": ["answer-run-1"],
                    "evidence_urls": ["https://examplebrand.com.au/reviews"],
                    "payload": {"source_panel": "runtime_entity_alias_candidates"},
                    "created_at": now,
                    "updated_at": now,
                },
                [
                    {
                        "id": "audit-1",
                        "project_id": project_id,
                        "event_type": "entity_alias_candidate_review_recorded",
                        "actor_type": "user",
                        "actor_id": "analyst-1",
                        "target_type": "entity_alias_candidate_review",
                        "target_id": review_id,
                        "before_hash": None,
                        "after_hash": "hash",
                        "input_refs": {},
                        "output_refs": {},
                        "method_version": "entity_alias_candidate_review_v1",
                        "reason": "Reject repeated noisy candidate",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).record_entity_alias_candidate_review(
            EntityAliasCandidateReviewInput(
                project_id=project_id,
                candidate_id=candidate_id,
                entity_id=brand_id,
                entity_kind="brand",
                alias="ExampleBrand AU",
                alias_type="alias",
                decision="rejected",
                reviewed_by="analyst-1",
                source="evidence_answer_text",
                confidence=0.8,
                reason="not an owned brand alias",
                notes="Reject repeated noisy candidate",
                evidence_answer_run_ids=("answer-run-1",),
                evidence_urls=("https://examplebrand.com.au/reviews",),
                payload={"source_panel": "runtime_entity_alias_candidates"},
            )
        )

        self.assertIsInstance(record, RuntimeEntityAliasCandidateReview)
        self.assertEqual(record.review["decision"], "rejected")
        self.assertEqual(record.audit_events[0]["event_type"], "entity_alias_candidate_review_recorded")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO entity_alias_candidate_reviews", executed_sql)
        self.assertIn("ON CONFLICT (project_id, candidate_id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_records_runtime_entity_alias_candidate_reviews_batch(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        now = datetime(2026, 6, 12, tzinfo=UTC)
        review_1_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        review_2_id = "652f2760-8ba3-5fdd-bd04-84e93b6d6519"
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                {"id": brand_id},
                {"id": project_id},
                {"id": brand_id},
                None,
                {
                    "id": review_1_id,
                    "project_id": project_id,
                    "candidate_id": "candidate-1",
                    "entity_id": brand_id,
                    "entity_kind": "brand",
                    "alias": "ExampleBrand AU",
                    "alias_type": "alias",
                    "source": "evidence_answer_text",
                    "confidence": 0.8,
                    "decision": "rejected",
                    "reviewed_by": "analyst-1",
                    "reason": "batch reject noisy alias candidates",
                    "notes": "Batch reject noisy candidates",
                    "evidence_answer_run_ids": ["answer-run-1"],
                    "evidence_urls": ["https://examplebrand.com.au/reviews"],
                    "payload": {"source_panel": "runtime_entity_alias_candidates"},
                    "created_at": now,
                    "updated_at": now,
                },
                None,
                {
                    "id": review_2_id,
                    "project_id": project_id,
                    "candidate_id": "candidate-2",
                    "entity_id": brand_id,
                    "entity_kind": "brand",
                    "alias": "examplebrand-au.example",
                    "alias_type": "domain",
                    "source": "evidence_citation_domain",
                    "confidence": 0.72,
                    "decision": "rejected",
                    "reviewed_by": "analyst-1",
                    "reason": "batch reject noisy alias candidates",
                    "notes": "Batch reject noisy candidates",
                    "evidence_answer_run_ids": [],
                    "evidence_urls": [],
                    "payload": {"source_panel": "runtime_entity_alias_candidates"},
                    "created_at": now,
                    "updated_at": now,
                },
            ]
        )

        result = PostgresEvidenceRepository(connection).record_entity_alias_candidate_reviews(
            (
                EntityAliasCandidateReviewInput(
                    project_id=project_id,
                    candidate_id="candidate-1",
                    entity_id=brand_id,
                    entity_kind="brand",
                    alias="ExampleBrand AU",
                    alias_type="alias",
                    decision="rejected",
                    reviewed_by="analyst-1",
                    source="evidence_answer_text",
                    confidence=0.8,
                    reason="batch reject noisy alias candidates",
                    evidence_answer_run_ids=("answer-run-1",),
                    evidence_urls=("https://examplebrand.com.au/reviews",),
                    payload={"source_panel": "runtime_entity_alias_candidates"},
                ),
                EntityAliasCandidateReviewInput(
                    project_id=project_id,
                    candidate_id="candidate-2",
                    entity_id=brand_id,
                    entity_kind="brand",
                    alias="examplebrand-au.example",
                    alias_type="domain",
                    decision="rejected",
                    reviewed_by="analyst-1",
                    source="evidence_citation_domain",
                    confidence=0.72,
                    payload={"source_panel": "runtime_entity_alias_candidates"},
                ),
            ),
            reviewed_by="analyst-1",
            notes="Batch reject noisy candidates",
        )

        self.assertIsInstance(result, RuntimeEntityAliasCandidateBatchReviewResult)
        self.assertEqual(result.batch_version, "entity_alias_candidate_review_batch_v1")
        self.assertEqual(result.reviewed_count, 2)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.audit_summary["event_type"], "entity_alias_candidate_batch_reviewed")
        self.assertEqual(result.audit_summary["individual_audit_event_type"], "entity_alias_candidate_review_recorded")
        self.assertEqual(result.records[0].review["decision"], "rejected")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO entity_alias_candidate_reviews", executed_sql)
        self.assertIn("entity_alias_candidate_batch_reviewed", str(connection.calls))
        self.assertIn("INSERT INTO audit_events", executed_sql)

    def test_postgres_repository_lists_runtime_entity_alias_candidate_reviews(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        now = datetime(2026, 6, 12, tzinfo=UTC)
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": review_id,
                        "project_id": project_id,
                        "candidate_id": "candidate-1",
                        "entity_id": brand_id,
                        "entity_kind": "brand",
                        "alias": "ExampleBrand AU",
                        "alias_type": "alias",
                        "source": "evidence_answer_text",
                        "confidence": 0.8,
                        "decision": "rejected",
                        "reviewed_by": "analyst-1",
                        "reason": "not an owned brand alias",
                        "notes": "Reject repeated noisy candidate",
                        "assigned_to": "reviewer@example.com",
                        "assigned_by": "lead@example.com",
                        "assignment_status": "assigned",
                        "assignment_note": "Review by Monday",
                        "assigned_at": now,
                        "due_at": now + timedelta(days=2),
                        "priority": "high",
                        "evidence_answer_run_ids": ["answer-run-1"],
                        "evidence_urls": ["https://examplebrand.com.au/reviews"],
                        "payload": {"source_panel": "runtime_entity_alias_candidates"},
                        "created_at": now,
                        "updated_at": now,
                    }
                ],
                [
                    {
                        "id": "audit-1",
                        "project_id": project_id,
                        "event_type": "entity_alias_candidate_review_recorded",
                        "actor_type": "user",
                        "actor_id": "analyst-1",
                        "target_type": "entity_alias_candidate_review",
                        "target_id": review_id,
                        "before_hash": None,
                        "after_hash": "hash",
                        "input_refs": {},
                        "output_refs": {},
                        "method_version": "entity_alias_candidate_review_v1",
                        "reason": "Reject repeated noisy candidate",
                        "created_at": now,
                    }
                ],
            ]
        )

        page = PostgresEvidenceRepository(connection).list_entity_alias_candidate_reviews(
            project_id=project_id,
            decision="rejected",
            entity_kind="brand",
            assigned_to="reviewer@example.com",
            assignment_status="assigned",
            priority="high",
            due_before=now + timedelta(days=3),
            limit=20,
            offset=0,
        )

        self.assertIsInstance(page, RuntimeEntityAliasCandidateReviewPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].review["candidate_id"], "candidate-1")
        self.assertEqual(page.records[0].review["decision"], "rejected")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "entity_alias_candidate_review_recorded")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_alias_candidate_reviews", executed_sql)
        self.assertIn("decision = %s", executed_sql)
        self.assertIn("entity_kind = %s", executed_sql)
        self.assertIn("assigned_to = %s", executed_sql)
        self.assertIn("assignment_status = %s", executed_sql)
        self.assertIn("priority = %s", executed_sql)
        self.assertIn("due_at <= %s", executed_sql)
        self.assertIn("ORDER BY updated_at DESC, created_at DESC, candidate_id", executed_sql)
        self.assertIn("target_type = %s AND target_id = %s", executed_sql)

    def test_postgres_repository_summarizes_runtime_entity_alias_assignment_queue(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        now = datetime.now(UTC)
        connection = RecordingConnection(
            result_sets=[
                [
                    {
                        "assignment_status": "assigned",
                        "priority": "high",
                        "due_at": now - timedelta(days=1),
                        "assigned_to": "reviewer@example.com",
                    },
                    {
                        "assignment_status": "in_progress",
                        "priority": "urgent",
                        "due_at": now + timedelta(days=2),
                        "assigned_to": "reviewer@example.com",
                    },
                    {
                        "assignment_status": "blocked",
                        "priority": "normal",
                        "due_at": now + timedelta(days=10),
                        "assigned_to": "reviewer-2@example.com",
                    },
                    {
                        "assignment_status": "completed",
                        "priority": "low",
                        "due_at": now - timedelta(days=3),
                        "assigned_to": "reviewer@example.com",
                    },
                    {
                        "assignment_status": "escalated",
                        "priority": "urgent",
                        "due_at": now - timedelta(days=2),
                        "assigned_to": "lead@example.com",
                    },
                    {
                        "assignment_status": "unassigned",
                        "priority": "normal",
                        "due_at": None,
                        "assigned_to": None,
                    },
                ]
            ]
        )

        stats = PostgresEvidenceRepository(connection).get_entity_alias_candidate_assignment_queue_stats(
            project_id=project_id,
            due_soon_before=now + timedelta(days=7),
        )

        self.assertIsInstance(stats, RuntimeEntityAliasCandidateAssignmentQueueStats)
        self.assertEqual(stats.method_version, "entity_alias_assignment_queue_stats_v1")
        self.assertEqual(stats.total_count, 6)
        self.assertEqual(stats.active_count, 4)
        self.assertEqual(stats.unassigned_count, 1)
        self.assertEqual(stats.overdue_count, 2)
        self.assertEqual(stats.due_soon_count, 1)
        self.assertEqual(stats.status_counts["assigned"], 1)
        self.assertEqual(stats.status_counts["completed"], 1)
        self.assertEqual(stats.status_counts["escalated"], 1)
        self.assertEqual(stats.priority_counts["urgent"], 2)
        self.assertEqual(stats.active_statuses, ("assigned", "in_progress", "blocked", "escalated"))
        self.assertLessEqual(stats.oldest_due_at, now)
        self.assertGreater(stats.next_due_at, now)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT assignment_status, priority, due_at, assigned_to", executed_sql)
        self.assertIn("FROM entity_alias_candidate_reviews", executed_sql)
        self.assertIn("WHERE project_id = %s", executed_sql)

    def test_postgres_repository_builds_runtime_entity_alias_assignment_workbench(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        now = datetime.now(UTC)
        review_row = {
            "id": review_id,
            "project_id": project_id,
            "candidate_id": "candidate-1",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": "runtime-console",
            "assigned_by": "lead@example.com",
            "assignment_status": "escalated",
            "assignment_note": "Escalated overdue assignment",
            "assigned_at": now,
            "due_at": now - timedelta(days=1),
            "priority": "urgent",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "089f8f43-d492-5600-85de-8c01956ab37e",
            "project_id": project_id,
            "event_type": "entity_alias_candidate_assignment_reassigned",
            "actor_type": "user",
            "actor_id": "lead@example.com",
            "target_type": "entity_alias_candidate_review",
            "target_id": review_id,
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {"from_assignment_status": "escalated"},
            "output_refs": {"entity_alias_candidate_review_ids": [review_id]},
            "method_version": "entity_alias_candidate_assignment_reassignment_v1",
            "reason": "rebalance escalated assignment queue",
            "created_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                [
                    {"assignment_status": "escalated", "priority": "urgent", "due_at": now - timedelta(days=1)},
                    {"assignment_status": "assigned", "priority": "high", "due_at": now + timedelta(days=2)},
                    {"assignment_status": "blocked", "priority": "normal", "due_at": now + timedelta(days=10)},
                ],
                [review_row],
                [audit_row],
            ]
        )

        workbench = PostgresEvidenceRepository(connection).get_entity_alias_assignment_workbench(
            project_id=project_id,
            reviewer_id="runtime-console",
            due_soon_before=now + timedelta(days=7),
            limit=8,
        )

        self.assertIsInstance(workbench, RuntimeEntityAliasAssignmentWorkbench)
        self.assertEqual(workbench.method_version, "entity_alias_assignment_workbench_v1")
        self.assertEqual(workbench.reviewer_id, "runtime-console")
        self.assertEqual(workbench.total_count, 3)
        self.assertEqual(workbench.active_count, 3)
        self.assertEqual(workbench.overdue_count, 1)
        self.assertEqual(workbench.due_soon_count, 1)
        self.assertEqual(workbench.escalated_count, 1)
        self.assertEqual(workbench.blocked_count, 1)
        self.assertEqual(workbench.status_counts["escalated"], 1)
        self.assertEqual(workbench.priority_counts["urgent"], 1)
        self.assertEqual(workbench.records[0].review["assignment_status"], "escalated")
        self.assertEqual(workbench.records[0].audit_events[0]["event_type"], "entity_alias_candidate_assignment_reassigned")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT assignment_status, priority, due_at", executed_sql)
        self.assertIn("FROM entity_alias_candidate_reviews", executed_sql)
        self.assertIn("assignment_status = ANY(%s)", executed_sql)
        self.assertIn("assigned_to = %s", executed_sql)
        self.assertIn("ORDER BY", executed_sql)
        self.assertIn("LIMIT %s", executed_sql)
        self.assertIn("FROM audit_events", executed_sql)

    def test_postgres_repository_builds_runtime_entity_alias_assignment_workload_summary(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        now = datetime.now(UTC)
        connection = RecordingConnection(
            result_sets=[
                [
                    {
                        "assignment_status": "assigned",
                        "priority": "urgent",
                        "due_at": now - timedelta(days=1),
                        "assigned_to": "reviewer-a@example.com",
                    },
                    {
                        "assignment_status": "in_progress",
                        "priority": "high",
                        "due_at": now + timedelta(days=2),
                        "assigned_to": "reviewer-a@example.com",
                    },
                    {
                        "assignment_status": "blocked",
                        "priority": "normal",
                        "due_at": now + timedelta(days=10),
                        "assigned_to": "reviewer-b@example.com",
                    },
                    {
                        "assignment_status": "escalated",
                        "priority": "urgent",
                        "due_at": now - timedelta(days=2),
                        "assigned_to": "reviewer-b@example.com",
                    },
                    {
                        "assignment_status": "assigned",
                        "priority": "normal",
                        "due_at": None,
                        "assigned_to": None,
                    },
                ]
            ]
        )

        workload = PostgresEvidenceRepository(connection).get_entity_alias_assignment_workload_summary(
            project_id=project_id,
            due_soon_before=now + timedelta(days=7),
        )

        self.assertIsInstance(workload, RuntimeEntityAliasAssignmentWorkloadSummary)
        self.assertEqual(workload.method_version, "entity_alias_assignment_workload_v1")
        self.assertEqual(workload.total_active_count, 5)
        self.assertEqual(workload.unassigned_count, 1)
        self.assertEqual(workload.reviewer_count, 2)
        self.assertEqual(workload.overdue_count, 2)
        self.assertEqual(workload.due_soon_count, 1)
        self.assertEqual(workload.escalated_count, 1)
        self.assertEqual(workload.blocked_count, 1)
        self.assertEqual(workload.active_statuses, ("assigned", "in_progress", "blocked", "escalated"))
        self.assertEqual(workload.reviewer_loads[0]["reviewer_id"], "unassigned")
        reviewer_a = next(load for load in workload.reviewer_loads if load["reviewer_id"] == "reviewer-a@example.com")
        reviewer_b = next(load for load in workload.reviewer_loads if load["reviewer_id"] == "reviewer-b@example.com")
        self.assertEqual(reviewer_a["active_count"], 2)
        self.assertEqual(reviewer_a["overdue_count"], 1)
        self.assertEqual(reviewer_a["due_soon_count"], 1)
        self.assertEqual(reviewer_a["urgent_count"], 1)
        self.assertEqual(reviewer_a["high_count"], 1)
        self.assertEqual(reviewer_a["status_counts"]["assigned"], 1)
        self.assertEqual(reviewer_a["priority_counts"]["urgent"], 1)
        self.assertEqual(reviewer_b["blocked_count"], 1)
        self.assertEqual(reviewer_b["escalated_count"], 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT assignment_status, priority, due_at, assigned_to", executed_sql)
        self.assertIn("FROM entity_alias_candidate_reviews", executed_sql)
        self.assertIn("assignment_status = ANY(%s)", executed_sql)

    def test_postgres_repository_builds_runtime_entity_alias_assignment_dispatch_plan(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        now = datetime.now(UTC)
        unassigned_review = {
            "id": "f3990d72-a58f-5963-9e58-3057ba83b5f7",
            "project_id": project_id,
            "candidate_id": "candidate-unassigned",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": None,
            "assigned_by": None,
            "assignment_status": "unassigned",
            "assignment_note": None,
            "assigned_at": None,
            "due_at": now + timedelta(days=2),
            "priority": "high",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        escalated_review = {
            **unassigned_review,
            "id": "7b549d23-e657-5375-8520-b9794c29ab78",
            "candidate_id": "candidate-escalated",
            "alias": "Example Brand Australia",
            "assigned_to": "reviewer-b@example.com",
            "assignment_status": "escalated",
            "due_at": now - timedelta(days=1),
            "priority": "urgent",
        }
        connection = RecordingConnection(
            result_sets=[
                [
                    {
                        "assignment_status": "assigned",
                        "priority": "normal",
                        "due_at": now + timedelta(days=3),
                        "assigned_to": "reviewer-a@example.com",
                    },
                    {
                        "assignment_status": "in_progress",
                        "priority": "urgent",
                        "due_at": now + timedelta(days=1),
                        "assigned_to": "reviewer-b@example.com",
                    },
                    {
                        "assignment_status": "unassigned",
                        "priority": "high",
                        "due_at": now + timedelta(days=2),
                        "assigned_to": None,
                    },
                ],
                [escalated_review, unassigned_review],
            ]
        )

        plan = PostgresEvidenceRepository(connection).build_entity_alias_assignment_dispatch_plan(
            EntityAliasAssignmentDispatchPlanInput(
                project_id=project_id,
                reviewer_ids=("reviewer-a@example.com", "reviewer-b@example.com"),
                include_statuses=("unassigned", "escalated"),
                max_per_reviewer=2,
                due_soon_before=now + timedelta(days=7),
                limit=10,
            )
        )

        self.assertIsInstance(plan, RuntimeEntityAliasAssignmentDispatchPlan)
        self.assertEqual(plan.method_version, "entity_alias_assignment_dispatch_plan_v1")
        self.assertTrue(plan.dry_run)
        self.assertEqual(plan.strategy, "least_loaded_round_robin")
        self.assertEqual(plan.include_statuses, ("unassigned", "escalated"))
        self.assertEqual(plan.reviewer_ids, ("reviewer-a@example.com", "reviewer-b@example.com"))
        self.assertEqual(plan.candidate_count, 2)
        self.assertEqual(plan.planned_assignment_count, 2)
        self.assertEqual(plan.skipped_count, 0)
        self.assertEqual(plan.proposed_assignments[0]["candidate_id"], "candidate-escalated")
        self.assertEqual(plan.proposed_assignments[0]["recommended_assigned_to"], "reviewer-a@example.com")
        self.assertEqual(plan.proposed_assignments[1]["recommended_assigned_to"], "reviewer-b@example.com")
        reviewer_a = next(load for load in plan.reviewer_loads if load["reviewer_id"] == "reviewer-a@example.com")
        self.assertEqual(reviewer_a["planned_assignment_count"], 1)
        self.assertEqual(reviewer_a["planned_active_count"], 2)
        self.assertEqual(plan.source_summary["dry_run_does_not_write_assignment_state"], True)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("SELECT assignment_status, priority, due_at, assigned_to", executed_sql)
        self.assertIn("SELECT id, project_id, candidate_id", executed_sql)
        self.assertIn("assignment_status = ANY(%s)", executed_sql)
        self.assertIn("LIMIT %s", executed_sql)

    def test_postgres_repository_applies_runtime_entity_alias_assignment_dispatch_plan(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        now = datetime(2026, 6, 15, tzinfo=UTC)
        before_review = {
            "id": "5e28753a-8f9e-5d80-977e-f755c0319e31",
            "project_id": project_id,
            "candidate_id": "candidate-unassigned",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.84,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": None,
            "assigned_by": None,
            "assignment_status": "unassigned",
            "assignment_note": None,
            "assigned_at": None,
            "due_at": now + timedelta(days=2),
            "priority": "high",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        after_review = {
            **before_review,
            "assigned_to": "reviewer-a@example.com",
            "assigned_by": "lead@example.com",
            "assignment_status": "assigned",
            "assignment_note": "Apply dispatch plan",
            "assigned_at": now,
            "updated_at": now,
        }
        audit_row = {
            "id": "c2dddf16-bd76-5d2d-a39b-ef4b4bdebe95",
            "event_type": "entity_alias_candidate_assignment_dispatch_applied",
            "actor_id": "lead@example.com",
            "target_type": "entity_alias_candidate_review",
            "target_id": before_review["id"],
            "occurred_at": now,
            "method_version": "entity_alias_assignment_dispatch_apply_v1",
            "reason": "Apply dispatch plan",
        }
        connection = RecordingConnection(
            result_sets=[
                [
                    {
                        "assignment_status": "assigned",
                        "priority": "normal",
                        "due_at": now + timedelta(days=3),
                        "assigned_to": "reviewer-a@example.com",
                    }
                ],
                [before_review],
                {"id": project_id},
                before_review,
                after_review,
                [audit_row],
            ]
        )

        result = PostgresEvidenceRepository(connection).apply_entity_alias_assignment_dispatch_plan(
            EntityAliasAssignmentDispatchApplyInput(
                project_id=project_id,
                reviewer_ids=("reviewer-a@example.com",),
                include_statuses=("unassigned",),
                max_per_reviewer=2,
                due_soon_before=now + timedelta(days=7),
                limit=10,
                applied_by="lead@example.com",
                assignment_status="assigned",
                assignment_note="Apply dispatch plan",
                reason="Apply dispatch plan",
            )
        )

        self.assertIsInstance(result, RuntimeEntityAliasAssignmentDispatchApplyResult)
        self.assertEqual(result.method_version, "entity_alias_assignment_dispatch_apply_v1")
        self.assertEqual(result.requested_count, 1)
        self.assertEqual(result.applied_count, 1)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.dispatch_plan.method_version, "entity_alias_assignment_dispatch_plan_v1")
        self.assertEqual(result.records[0].review["assigned_to"], "reviewer-a@example.com")
        self.assertEqual(result.audit_summary["event_type"], "entity_alias_assignment_dispatch_plan_applied")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("UPDATE entity_alias_candidate_reviews SET assigned_to = %s", executed_sql)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_enqueues_entity_alias_assignment_overdue_notifications(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        candidate_id = "candidate-1"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        now = datetime(2026, 6, 13, tzinfo=UTC)
        review_row = {
            "id": review_id,
            "project_id": project_id,
            "candidate_id": candidate_id,
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": "reviewer@example.com",
            "assigned_by": "lead@example.com",
            "assignment_status": "assigned",
            "assignment_note": "Review by Monday",
            "assigned_at": now,
            "due_at": now - timedelta(days=1),
            "priority": "urgent",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        notification_id = "dfaa703e-e168-58d1-b951-6853a7ba0810"
        subscription_id = "7d7e88a9-b44c-542e-8be7-c3f7db7fd5f8"
        delivery_id = "f204f229-b9af-5525-8a87-f0c6b79edc12"
        notification_row = {
            "id": notification_id,
            "project_id": project_id,
            "notification_type": "entity_alias_assignment_overdue",
            "severity": "critical",
            "title": "Alias assignment overdue: ExampleBrand AU",
            "message": "ExampleBrand AU alias candidate review is overdue for reviewer@example.com.",
            "target_type": "entity_alias_candidate_review",
            "target_id": review_id,
            "recipient_role": "project_member",
            "status": "unread",
            "payload": {"entity_alias_candidate_review_id": review_id, "priority": "urgent"},
            "created_by": "runtime-console",
            "created_at": now,
            "read_at": None,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        subscription_row = {
            "id": subscription_id,
            "project_id": project_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "event_types": ["entity_alias_assignment_overdue"],
            "severity_threshold": "warning",
            "status": "active",
            "metadata": {},
            "created_by": "runtime-console",
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        delivery_row = {
            "id": delivery_id,
            "project_id": project_id,
            "notification_id": notification_id,
            "subscription_id": subscription_id,
            "channel": "webhook",
            "endpoint_url": "https://hooks.example.com/geno",
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 3,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "response_status": None,
            "response_body_hash": None,
            "error_message": None,
            "payload": {"delivery_version": "runtime_notification_delivery_v1"},
            "created_at": now,
            "updated_by": "runtime-console",
            "updated_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                [review_row],
                notification_row,
                [subscription_row],
                delivery_row,
            ]
        )

        result = PostgresEvidenceRepository(connection).enqueue_entity_alias_assignment_overdue_notifications(
            project_id=project_id,
            assigned_to="reviewer@example.com",
            priority="urgent",
            due_before=now,
            created_by="runtime-console",
            reason="notify overdue alias assignment",
        )

        self.assertIsInstance(result, RuntimeEntityAliasAssignmentNotificationResult)
        self.assertEqual(result.notification_count, 1)
        self.assertEqual(result.delivery_count, 1)
        self.assertEqual(result.notifications[0]["notification_type"], "entity_alias_assignment_overdue")
        self.assertTrue(any(event["event_type"] == "runtime_notification_created" for event in result.audit_events))
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_alias_candidate_reviews", executed_sql)
        self.assertIn("assignment_status = ANY(%s)", executed_sql)
        self.assertIn("due_at < %s", executed_sql)
        self.assertIn("assigned_to = %s", executed_sql)
        self.assertIn("priority = %s", executed_sql)
        self.assertIn("INSERT INTO runtime_notifications", executed_sql)
        self.assertIn("INSERT INTO runtime_notification_deliveries", executed_sql)
        self.assertIn("entity_alias_assignment_overdue", str(connection.calls))

    def test_postgres_repository_escalates_entity_alias_assignment_overdue_reviews(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        candidate_id = "candidate-1"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        now = datetime(2026, 6, 13, tzinfo=UTC)
        before = {
            "id": review_id,
            "project_id": project_id,
            "candidate_id": candidate_id,
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": "reviewer@example.com",
            "assigned_by": "lead@example.com",
            "assignment_status": "assigned",
            "assignment_note": "Review by Monday",
            "assigned_at": now,
            "due_at": now - timedelta(days=1),
            "priority": "urgent",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        after = {**before, "assignment_status": "escalated", "assignment_note": "escalate overdue assignments"}
        connection = RecordingConnection(
            result_sets=[
                {"id": project_id},
                [before],
                after,
            ]
        )

        result = PostgresEvidenceRepository(connection).escalate_entity_alias_assignment_overdue_reviews(
            project_id=project_id,
            assigned_to="reviewer@example.com",
            priority="urgent",
            due_before=now,
            escalated_by="alias-escalation-worker",
            reason="escalate overdue assignments",
        )

        self.assertEqual(result.escalation_count, 1)
        self.assertEqual(result.escalated_reviews[0]["assignment_status"], "escalated")
        self.assertEqual(result.audit_events[0]["event_type"], "entity_alias_candidate_assignment_escalated")
        self.assertEqual(result.audit_events[0]["method_version"], "entity_alias_candidate_assignment_escalation_v1")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_alias_candidate_reviews", executed_sql)
        self.assertIn("assignment_status = ANY(%s)", executed_sql)
        self.assertIn("due_at < %s", executed_sql)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("SET assignment_status = 'escalated'", executed_sql)
        self.assertIn("entity_alias_candidate_assignment_escalated", str(connection.calls))

    def test_postgres_repository_reassigns_entity_alias_assignment_reviews(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        candidate_id = "candidate-1"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        now = datetime(2026, 6, 13, tzinfo=UTC)
        due_at = datetime(2026, 6, 15, tzinfo=UTC)
        before = {
            "id": review_id,
            "project_id": project_id,
            "candidate_id": candidate_id,
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": "reviewer-a@example.com",
            "assigned_by": "lead@example.com",
            "assignment_status": "escalated",
            "assignment_note": "Escalated overdue assignment",
            "assigned_at": now,
            "due_at": now - timedelta(days=1),
            "priority": "urgent",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        after = {
            **before,
            "assigned_to": "reviewer-b@example.com",
            "assigned_by": "lead@example.com",
            "assignment_status": "assigned",
            "assignment_note": "Reassign escalated review",
            "due_at": due_at,
            "priority": "high",
        }
        connection = RecordingConnection(result_sets=[{"id": project_id}, [before], after])

        result = PostgresEvidenceRepository(connection).reassign_entity_alias_candidate_reviews(
            EntityAliasCandidateAssignmentReassignmentInput(
                project_id=project_id,
                assigned_to="reviewer-b@example.com",
                reassigned_by="lead@example.com",
                from_assignment_status="escalated",
                assignment_status="assigned",
                priority="high",
                due_at=due_at,
                assignment_note="Reassign escalated review",
                reason="rebalance escalated assignment queue",
                limit=25,
            )
        )

        self.assertIsInstance(result, RuntimeEntityAliasAssignmentReassignmentResult)
        self.assertEqual(result.reassignment_count, 1)
        self.assertEqual(result.reassigned_reviews[0]["assigned_to"], "reviewer-b@example.com")
        self.assertEqual(result.reassigned_reviews[0]["assignment_status"], "assigned")
        self.assertEqual(result.audit_events[0]["event_type"], "entity_alias_candidate_assignment_reassigned")
        self.assertEqual(result.audit_events[0]["method_version"], "entity_alias_candidate_assignment_reassignment_v1")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_alias_candidate_reviews", executed_sql)
        self.assertIn("assignment_status = %s", executed_sql)
        self.assertIn("LIMIT %s", executed_sql)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("SET assigned_to = %s", executed_sql)
        self.assertIn("entity_alias_candidate_assignment_reassigned", str(connection.calls))

    def test_postgres_repository_assigns_runtime_entity_alias_candidate_review(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        due_at = datetime(2026, 6, 14, 9, 0, tzinfo=UTC)
        now = datetime(2026, 6, 12, tzinfo=UTC)
        before = {
            "id": review_id,
            "project_id": project_id,
            "candidate_id": "candidate-1",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": None,
            "assigned_by": None,
            "assignment_status": "unassigned",
            "assignment_note": None,
            "assigned_at": None,
            "due_at": None,
            "priority": "normal",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        after = {**before, "assigned_to": "reviewer@example.com", "assigned_by": "lead@example.com", "assignment_status": "assigned", "assignment_note": "Review by Monday", "assigned_at": now, "due_at": due_at, "priority": "high"}
        connection = RecordingConnection(
            result_sets=[
                before,
                after,
                [
                    {
                        "id": "audit-assign",
                        "project_id": project_id,
                        "event_type": "entity_alias_candidate_assigned",
                        "actor_type": "user",
                        "actor_id": "lead@example.com",
                        "target_type": "entity_alias_candidate_review",
                        "target_id": review_id,
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {},
                        "output_refs": {},
                        "method_version": "entity_alias_candidate_assignment_v1",
                        "reason": "Assign reviewer",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).assign_entity_alias_candidate_review(
            EntityAliasCandidateAssignmentInput(
                project_id=project_id,
                candidate_id="candidate-1",
                assigned_to="reviewer@example.com",
                assigned_by="lead@example.com",
                assignment_status="assigned",
                priority="high",
                due_at=due_at,
                assignment_note="Review by Monday",
                reason="Assign reviewer",
            )
        )

        self.assertIsInstance(record, RuntimeEntityAliasCandidateReview)
        self.assertEqual(record.review["assigned_to"], "reviewer@example.com")
        self.assertEqual(record.review["priority"], "high")
        self.assertEqual(record.audit_events[0]["event_type"], "entity_alias_candidate_assigned")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("UPDATE entity_alias_candidate_reviews", executed_sql)
        self.assertIn("assigned_to = %s", executed_sql)
        self.assertIn("entity_alias_candidate_assigned", str(connection.calls))

    def test_postgres_repository_claims_runtime_entity_alias_candidate_review(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        now = datetime(2026, 6, 13, tzinfo=UTC)
        before = {
            "id": review_id,
            "project_id": project_id,
            "candidate_id": "candidate-1",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": None,
            "assigned_by": None,
            "assignment_status": "unassigned",
            "assignment_note": None,
            "assigned_at": None,
            "due_at": now + timedelta(days=2),
            "priority": "normal",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        after = {
            **before,
            "assigned_to": "reviewer@example.com",
            "assigned_by": "reviewer@example.com",
            "assignment_status": "assigned",
            "assignment_note": "Claim from queue",
            "assigned_at": now,
        }
        connection = RecordingConnection(
            result_sets=[
                before,
                after,
                [
                    {
                        "id": "audit-claim",
                        "project_id": project_id,
                        "event_type": "entity_alias_candidate_assignment_actioned",
                        "actor_type": "user",
                        "actor_id": "reviewer@example.com",
                        "target_type": "entity_alias_candidate_review",
                        "target_id": review_id,
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {},
                        "output_refs": {},
                        "method_version": "entity_alias_candidate_assignment_action_v1",
                        "reason": "Claim from queue",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).apply_entity_alias_candidate_assignment_action(
            EntityAliasCandidateAssignmentActionInput(
                project_id=project_id,
                candidate_id="candidate-1",
                action="claim",
                updated_by="reviewer@example.com",
                note="Claim from queue",
            )
        )

        self.assertIsInstance(record, RuntimeEntityAliasCandidateReview)
        self.assertEqual(record.review["assigned_to"], "reviewer@example.com")
        self.assertEqual(record.review["assignment_status"], "assigned")
        self.assertEqual(record.audit_events[0]["event_type"], "entity_alias_candidate_assignment_actioned")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("UPDATE entity_alias_candidate_reviews", executed_sql)
        self.assertIn("entity_alias_candidate_assignment_actioned", str(connection.calls))

    def test_postgres_repository_releases_runtime_entity_alias_candidate_review(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        review_id = "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b"
        now = datetime(2026, 6, 13, tzinfo=UTC)
        before = {
            "id": review_id,
            "project_id": project_id,
            "candidate_id": "candidate-1",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": "reviewer@example.com",
            "assigned_by": "reviewer@example.com",
            "assignment_status": "blocked",
            "assignment_note": "Blocked on evidence",
            "assigned_at": now,
            "due_at": now + timedelta(days=2),
            "priority": "high",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        after = {
            **before,
            "assigned_to": None,
            "assigned_by": "reviewer@example.com",
            "assignment_status": "unassigned",
            "assignment_note": "Release back to queue",
            "assigned_at": None,
        }
        connection = RecordingConnection(
            result_sets=[
                before,
                after,
                [
                    {
                        "id": "audit-release",
                        "project_id": project_id,
                        "event_type": "entity_alias_candidate_assignment_actioned",
                        "actor_type": "user",
                        "actor_id": "reviewer@example.com",
                        "target_type": "entity_alias_candidate_review",
                        "target_id": review_id,
                        "before_hash": "before",
                        "after_hash": "after",
                        "input_refs": {},
                        "output_refs": {},
                        "method_version": "entity_alias_candidate_assignment_action_v1",
                        "reason": "Release back to queue",
                        "created_at": now,
                    }
                ],
            ]
        )

        record = PostgresEvidenceRepository(connection).apply_entity_alias_candidate_assignment_action(
            EntityAliasCandidateAssignmentActionInput(
                project_id=project_id,
                candidate_id="candidate-1",
                action="release",
                updated_by="reviewer@example.com",
                note="Release back to queue",
            )
        )

        self.assertIsInstance(record, RuntimeEntityAliasCandidateReview)
        self.assertIsNone(record.review["assigned_to"])
        self.assertEqual(record.review["assignment_status"], "unassigned")
        self.assertEqual(record.audit_events[0]["method_version"], "entity_alias_candidate_assignment_action_v1")
        self.assertEqual(connection.commit_count, 1)

    def test_postgres_repository_batch_claims_runtime_entity_alias_candidate_reviews(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        now = datetime(2026, 6, 13, tzinfo=UTC)
        before_claim = {
            "id": "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b",
            "project_id": project_id,
            "candidate_id": "candidate-1",
            "entity_id": brand_id,
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": None,
            "assigned_by": None,
            "assignment_status": "unassigned",
            "assignment_note": None,
            "assigned_at": None,
            "due_at": now + timedelta(days=2),
            "priority": "normal",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        after_claim = {
            **before_claim,
            "assigned_to": "reviewer@example.com",
            "assigned_by": "reviewer@example.com",
            "assignment_status": "assigned",
            "assignment_note": "Batch claim from workbench",
            "assigned_at": now,
        }
        before_conflict = {**before_claim, "candidate_id": "candidate-2", "assigned_to": "other@example.com"}
        audit_row = {
            "id": "audit-batch-claim",
            "project_id": project_id,
            "event_type": "entity_alias_candidate_assignment_actioned",
            "actor_type": "user",
            "actor_id": "reviewer@example.com",
            "target_type": "entity_alias_candidate_review",
            "target_id": before_claim["id"],
            "before_hash": "before",
            "after_hash": "after",
            "input_refs": {},
            "output_refs": {},
            "method_version": "entity_alias_candidate_assignment_action_v1",
            "reason": "Batch claim from workbench",
            "created_at": now,
        }
        connection = RecordingConnection(result_sets=[before_claim, after_claim, [audit_row], before_conflict])

        result = PostgresEvidenceRepository(connection).apply_entity_alias_candidate_assignment_batch_action(
            EntityAliasCandidateAssignmentBatchActionInput(
                project_id=project_id,
                candidate_ids=("candidate-1", "candidate-2"),
                action="claim",
                updated_by="reviewer@example.com",
                note="Batch claim from workbench",
            )
        )

        self.assertIsInstance(result, RuntimeEntityAliasAssignmentBatchActionResult)
        self.assertEqual(result.action, "claim")
        self.assertEqual(result.requested_count, 2)
        self.assertEqual(result.actioned_count, 1)
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.records[0].review["assigned_to"], "reviewer@example.com")
        self.assertEqual(result.errors[0]["candidate_id"], "candidate-2")
        self.assertEqual(result.audit_summary["event_type"], "entity_alias_candidate_assignment_batch_actioned")
        self.assertEqual(result.audit_summary["method_version"], "entity_alias_candidate_assignment_batch_action_v1")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FOR UPDATE", executed_sql)
        self.assertIn("UPDATE entity_alias_candidate_reviews", executed_sql)
        self.assertIn("entity_alias_candidate_assignment_batch_actioned", str(connection.calls))

    def test_postgres_repository_rejects_assignment_claim_when_already_owned(self) -> None:
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        now = datetime(2026, 6, 13, tzinfo=UTC)
        before = {
            "id": "60f1e5a4-d1d0-511e-b0c8-15dfc081ee9b",
            "project_id": project_id,
            "candidate_id": "candidate-1",
            "entity_id": "3ba88c1e-3ddc-5075-9ac9-29687d539830",
            "entity_kind": "brand",
            "alias": "ExampleBrand AU",
            "alias_type": "alias",
            "source": "evidence_answer_text",
            "confidence": 0.8,
            "decision": "needs_review",
            "reviewed_by": "analyst-1",
            "reason": "review required",
            "notes": "Needs reviewer assignment",
            "assigned_to": "other@example.com",
            "assigned_by": "lead@example.com",
            "assignment_status": "assigned",
            "assignment_note": "Review by Monday",
            "assigned_at": now,
            "due_at": now + timedelta(days=2),
            "priority": "high",
            "evidence_answer_run_ids": ["answer-run-1"],
            "evidence_urls": ["https://examplebrand.com.au/reviews"],
            "payload": {"source_panel": "runtime_entity_alias_candidates"},
            "created_at": now,
            "updated_at": now,
        }
        connection = RecordingConnection(result_sets=[before])

        with self.assertRaisesRegex(ValueError, "already assigned"):
            PostgresEvidenceRepository(connection).apply_entity_alias_candidate_assignment_action(
                EntityAliasCandidateAssignmentActionInput(
                    project_id=project_id,
                    candidate_id="candidate-1",
                    action="claim",
                    updated_by="reviewer@example.com",
                )
            )
        self.assertEqual(connection.commit_count, 0)

    def test_postgres_repository_lists_runtime_entity_aliases_with_audit_events(self) -> None:
        now = datetime(2026, 6, 10, tzinfo=UTC)
        project_id = "9a50797d-a341-55a4-8bdf-cc255c017e5c"
        alias_id = "b7f7a2fb-9191-50f0-aa33-a56fed6b0ac5"
        brand_id = "3ba88c1e-3ddc-5075-9ac9-29687d539830"
        connection = RecordingConnection(
            result_sets=[
                {"count": 1},
                [
                    {
                        "id": alias_id,
                        "entity_id": brand_id,
                        "entity_kind": "brand",
                        "alias": "ExampleBrand Australia",
                        "alias_type": "alias",
                        "confidence": 0.98,
                        "confirmed_by": "runtime-console",
                        "created_at": now,
                        "project_id": project_id,
                        "canonical_name": "ExampleBrand",
                        "official_domains": ["https://examplebrand.com.au"],
                        "parent_company": None,
                        "product_lines": ["mattresses"],
                        "status": "active",
                    }
                ],
                [
                    {
                        "id": "725067ce-00b5-49a5-a3ec-8b8e74c85f4f",
                        "event_type": "entity_alias_confirmed",
                        "project_id": project_id,
                        "actor_type": "user",
                        "actor_id": "runtime-console",
                        "target_type": "entity_alias",
                        "target_id": alias_id,
                        "before_hash": None,
                        "after_hash": "after",
                        "input_refs": {"entity_ids": [brand_id]},
                        "output_refs": {"entity_alias_ids": [alias_id]},
                        "method_version": "entity_alias_confirm_v1",
                        "reason": "confirm entity alias for parser disambiguation",
                        "created_at": now,
                    }
                ],
            ]
        )
        page = PostgresEvidenceRepository(connection).list_runtime_entity_aliases(
            project_id=project_id,
            entity_kind="brand",
            limit=5,
            offset=0,
        )
        self.assertIsInstance(page, RuntimeEntityAliasPage)
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.records[0].entity_alias["alias"], "ExampleBrand Australia")
        self.assertEqual(page.records[0].audit_events[0]["event_type"], "entity_alias_confirmed")
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM entity_aliases ea JOIN", executed_sql)
        self.assertIn("entity.entity_kind = ea.entity_kind", executed_sql)
        self.assertIn("WHERE entity.project_id = %s AND ea.entity_kind = %s", executed_sql)
        self.assertIn("FROM audit_events WHERE project_id = %s AND target_type = %s AND target_id = %s", executed_sql)


if __name__ == "__main__":
    unittest.main()
